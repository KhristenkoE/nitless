import subprocess
from pathlib import Path

from nitless.config import Settings
from nitless.context import Profile, RelatedContext
from nitless.context.intent import Intent
from nitless.diff import compute_diff
from nitless.errors import LLMError
from nitless.models import ChangeRequest, Criterion, Evidence, Finding, Requirements
from nitless.pipeline import verify
from nitless.review import verifier
from nitless.review.postprocess import finding_cap, select
from nitless.review.requirements import dispute

BASE = {
    "app/orders.py": "def total(items):\n    return sum(i.price for i in items)\n\n\ndef count(items):\n"
                     "    return len(items)\n",
}
HEAD = {
    "app/orders.py": "def total(items):\n    subtotal = sum(i.price for i in items)\n    return subtotal * 0.9\n\n\n"
                     "def count(items):\n    return len(items)\n\n\ndef first(items):\n    return items[0]\n",
}


def finding(message="Discount applied to every order", line=3, severity="major", category="correctness",
            confidence=0.8, **kw) -> Finding:
    return Finding(id=kw.pop("id", message[:8]), file="app/orders.py", line_start=line, line_end=line,
                   severity=severity, category=category, message=message, rationale="Totals are wrong.",
                   confidence=confidence, **kw)


def verdict(decision="keep", reason="valid", confidence=0.9, severity=None) -> dict:
    return {"counter_argument": "Maybe intended.", "decision": decision, "reason": reason, "severity": severity,
            "justification": "Because.", "confidence": confidence}


class FakeLLM:
    """Answers each verifier call by the finding's message; a message mapped to an exception raises it."""

    def __init__(self, answers: dict):
        self.answers, self.prompts = answers, []

    def call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens=None):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        head = prompt.split("# Code at the finding")[0]
        answer = next(a for key, a in self.answers.items() if f"Message: {key}" in head)
        if isinstance(answer, Exception):
            raise answer
        return schema.model_validate(answer)


def repo(tmp_path: Path) -> tuple[Path, ChangeRequest]:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(tmp_path)]
    subprocess.run([*git, "init", "-q"], check=True)
    shas = []
    for files in (BASE, HEAD):
        for path, text in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(text)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "c"], check=True)
        shas.append(subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
    change = ChangeRequest(provider="local", repo=str(tmp_path), ref="a..b", title="Apply the loyalty discount",
                           description="Orders get 10% off.", base_sha=shas[0], start_sha=shas[0], head_sha=shas[1])
    return tmp_path, change


def material(tmp_path: Path) -> verifier.Material:
    root, change = repo(tmp_path)
    files = compute_diff(root, change.base_sha, change.head_sha)
    intent = Intent(source="mr", kind="explicit", title="T", intent="Discount",
                    acceptance_criteria=["Orders get 10% off"], out_of_scope=["Coupons"])
    return verifier.build_material(root, change, files, Profile([], []), RelatedContext([], []), intent, "")


def settings(**kw) -> Settings:
    return Settings(local_repo=Path("."), base_ref="main", anthropic_api_key="k", model_strong="m", **kw)


def test_code_at_shows_the_enclosing_function_and_the_same_symbol_before_the_change(tmp_path):
    m = material(tmp_path)
    diff = m.files["app/orders.py"]
    new, base = verifier.code_at(diff, m.head["app/orders.py"], m.base["app/orders.py"], 3, 3)
    assert "function `total`" in new and "     3 +     return subtotal * 0.9" in new
    assert "     1   def total(items):" in new  # unchanged line, no marker
    assert "return sum(i.price for i in items)" in base and "0.9" not in base

    new, base = verifier.code_at(diff, m.head["app/orders.py"], m.base["app/orders.py"], 11, 11)
    assert "function `first`" in new
    assert base == "`first` does not exist in the base version: this change adds it."


def test_message_carries_finding_code_task_and_the_other_findings(tmp_path):
    m = material(tmp_path)
    a, b = finding(), finding("Index error on empty list", line=11, severity="minor", id="b")
    text = verifier.build_message(b, [a, b], m)
    assert text.startswith("# Finding under review") and "Message: Index error on empty list" in text
    assert "# The same code before this change" in text and "Apply the loyalty discount" in text
    assert "AC1: Orders get 10% off" in text and "- Coupons" in text
    assert "[1] app/orders.py:3 major/correctness: Discount applied" in text
    assert "[2] app/orders.py:11 minor/correctness: Index error on empty list   <- the finding under review" in text


def test_verdicts_keep_drop_and_downgrade(tmp_path):
    findings = [finding("Real bug", id="keep"), finding("Refuted", id="drop"),
                finding("Overstated", id="down"), finding("Barely", id="floor", severity="minor")]
    llm = FakeLLM({"Real bug": verdict(confidence=0.95), "Refuted": verdict("drop", "incorrect", 0.1),
                   "Overstated": verdict("downgrade", "speculative", 0.7, "minor"),
                   "Barely": verdict("downgrade", "nit", 0.6, "info")})
    result = verify(settings(max_findings=0), llm, findings, material(tmp_path))
    assert [(f.id, f.severity, f.confidence) for f in result.published] == [("keep", "major", 0.95),
                                                                            ("down", "minor", 0.7)]
    assert result.dropped == {"drop": "verifier", "floor": "severity_floor"}
    rows = {r["id"]: r for r in result.trace()["findings"]}
    assert rows["drop"]["status"] == "dropped" and rows["drop"]["verdict"]["reason"] == "incorrect"
    assert rows["down"]["reviewer"] == {"severity": "major", "confidence": 0.8}
    assert rows["down"]["published"] == {"severity": "minor", "confidence": 0.7}
    assert result.trace()["candidates"] == 4 and result.trace()["published"] == 2
    assert all("# Code at the finding" in p for p in llm.prompts)


def test_downgrade_without_a_lower_severity_steps_down_once():
    assert verifier.downgraded("major", None) == "minor"
    assert verifier.downgraded("major", "critical") == "minor"
    assert verifier.downgraded("critical", "minor") == "minor"


def test_a_failed_call_keeps_the_finding_unverified_with_a_warning(tmp_path):
    llm = FakeLLM({"Real bug": LLMError("call failed (500)"), "Other": verdict("drop", "nit", 0.2)})
    result = verify(settings(min_confidence=0.9), llm, [finding("Real bug", confidence=0.4, id="a"),
                                                        finding("Other", id="b")], material(tmp_path))
    assert [f.id for f in result.published] == ["a"]  # the confidence floor applies to verified findings only
    assert result.published[0].confidence == 0.4
    assert result.warnings == ["verifier failed on app/orders.py:3; finding kept unverified: call failed (500)"]
    assert result.trace()["unverified"] == 1


def test_verify_off_publishes_the_candidates_through_the_post_filter_only(tmp_path):
    llm = FakeLLM({})
    result = verify(settings(verify=False), llm, [finding(confidence=0.1)], material(tmp_path))
    assert len(result.published) == 1 and llm.prompts == []
    assert result.trace()["enabled"] is False


def test_confidence_floor_one_test_coverage_finding_and_the_cap():
    findings = [finding("a", id="a", severity="minor", confidence=0.9),  # 1.8
                finding("b", id="b", severity="major", confidence=0.5),  # 1.5
                finding("c", id="c", severity="critical", confidence=0.6),  # 2.4
                finding("t1", id="t1", category="test-coverage", severity="minor", confidence=0.8),  # 1.6
                finding("t2", id="t2", category="test-coverage", severity="minor", confidence=0.7),
                finding("low", id="low", confidence=0.3)]
    kept, dropped = select(findings, {f.id for f in findings}, min_confidence=0.4, cap=3)
    assert [f.id for f in kept] == ["a", "c", "t1"]  # the original order, best three by severity × confidence
    assert dropped == {"low": "min_confidence", "t2": "test_coverage_limit", "b": "cap"}
    kept, _ = select(findings, set(), min_confidence=0.4, cap=None)
    assert len(kept) == 5  # nothing verified: no confidence floor


def test_cap_scales_with_the_diff_unless_configured():
    assert [finding_cap(n, None) for n in (10, 50, 51, 300, 301)] == [3, 3, 6, 6, 10]
    assert finding_cap(10, 2) == 2 and finding_cap(10, 0) is None


def test_a_refuted_requirements_gap_is_no_longer_reported_as_unmet(tmp_path):
    reqs = Requirements(source="story.json", kind="repo", does_what_was_asked="partially", verdict="Mostly.",
                        criteria=[Criterion(id="AC1", text="x", status="met", evidence="a.py:1"),
                                  Criterion(id="AC2", text="y", status="not_met", evidence="missing")])
    gap = finding("Criterion 2 is missing", id="req", category="requirements",
                  evidence=[Evidence(kind="task", ref="story.json#AC2", note="y")])
    llm = FakeLLM({"Criterion 2": verdict("drop", "incorrect", 0.1)})
    result = verify(settings(), llm, [gap], material(tmp_path))
    assert result.refuted_criteria() == {"AC2": "Because."}
    disputed = dispute(reqs, result.refuted_criteria())
    assert disputed.criteria[1].status == "cannot_determine"
    assert "Verification disputed" in disputed.criteria[1].evidence
    assert disputed.does_what_was_asked == "yes"


def test_restate_only_when_findings_were_withdrawn(tmp_path):
    class Restater:
        def call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens=None):
            assert "Withdrawn findings:\n- app/orders.py:3 Refuted" in messages[-1]["content"]
            return schema(assessment="Looks good.")

    m = material(tmp_path)
    kept = verify(settings(), FakeLLM({"Real bug": verdict()}), [finding("Real bug")], m)
    assert verifier.restate(Restater(), "fast", "One bug.", kept) == "One bug."
    dropped = verify(settings(), FakeLLM({"Refuted": verdict("drop", "incorrect", 0.1)}), [finding("Refuted")], m)
    assert verifier.restate(Restater(), "fast", "One bug.", dropped) == "Looks good."
