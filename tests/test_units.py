import subprocess
from pathlib import Path

import pytest

from nitless.config import Settings
from nitless.context.index import RepoIndex
from nitless.context.intent import Intent
from nitless.context.repo_map import list_files
from nitless.diff import compute_diff, parse_diff
from nitless.errors import LLMError, QuotaExhaustedError
from nitless.models import ChangeRequest
from nitless.pipeline import build_context, plan_units, review_and_check, select_files
from nitless.review import naive
from nitless.review.schema import ReviewSubmission
from nitless.review.triage import triage
from nitless.review.units import Unit, diff_tokens, find_links, split


def commit(root: Path, base: dict[str, str], head: dict[str, str]) -> ChangeRequest:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)]
    subprocess.run([*git, "init", "-q"], check=True)
    shas = []
    for files in (base, head):
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "Add discount"], check=True)
        shas.append(subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
    return ChangeRequest(provider="local", repo=str(root), ref="HEAD", title="Add discount",
                         description="Applies the discount.", base_sha=shas[0], start_sha=shas[0], head_sha=shas[1])


def body(name: str, lines: int, value: str = "1") -> str:
    return f"def {name}(x):\n" + "".join(f"    x = x + {value}  # step {i}\n" for i in range(lines)) + "    return x\n"


BASE = {
    "app/pricing.py": body("discount", 3),
    "app/orders.py": "from app.pricing import discount\n\n\ndef total(order):\n    return discount(order)\n",
    "app/reports.py": body("weekly", 3),
    "tests/test_pricing.py": "from app.pricing import discount\n\n\ndef test_discount():\n    assert discount(1)\n",
}
HEAD = {
    "app/pricing.py": body("discount", 3, "2"),
    "app/orders.py": "from app.pricing import discount\n\n\ndef total(order):\n    return discount(order) + 1\n",
    "app/reports.py": body("weekly", 3, "3"),
    "tests/test_pricing.py": "from app.pricing import discount\n\n\ndef test_discount():\n    assert discount(2)\n",
}


def index_and_files(root: Path, change: ChangeRequest):
    return RepoIndex(root, list_files(root, []), change.base_sha), compute_diff(root, change.base_sha, change.head_sha)


def test_linked_files_share_a_unit_and_the_budget_splits_the_rest(tmp_path):
    change = commit(tmp_path, BASE, HEAD)
    index, files = index_and_files(tmp_path, change)
    reasons = {(link.a, link.b): link.reason for link in find_links(files, index)}
    assert reasons[("app/orders.py", "app/pricing.py")] == "app/orders.py uses discount changed in app/pricing.py"
    assert reasons[("tests/test_pricing.py", "app/pricing.py")] == "tests/test_pricing.py tests app/pricing.py"

    linked = {"app/orders.py", "app/pricing.py", "tests/test_pricing.py"}
    budget = diff_tokens([f for f in files if f.path in linked])
    groups = [set(u.paths) for u in split(files, index, budget, max_units=6)]
    assert groups == [{"app/orders.py", "app/pricing.py", "tests/test_pricing.py"}, {"app/reports.py"}]

    assert len(split(files, index, 10**6, max_units=6)) == 1  # everything fits: one unit
    assert len(split(files, index, 1, max_units=2)) == 2  # over the unit limit: the smallest are merged


def test_signature_changes_are_risky_with_an_index(tmp_path):
    change = commit(tmp_path, BASE, {"app/pricing.py": BASE["app/pricing.py"].replace("(x)", "(x, rate)")})
    index, files = index_and_files(tmp_path, change)
    assert triage(files, index).files["app/pricing.py"].reasons == ["changes the signature of discount"]


class FakeLLM:
    def __init__(self):
        self.messages = []

    def call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens=None):
        self.messages.append(messages)
        return ReviewSubmission(assessment="Fine.")


def test_a_small_change_is_one_unit_with_the_single_call_prompt(tmp_path):
    change = commit(tmp_path, BASE, HEAD)
    settings = Settings.model_construct()
    sel = select_files(tmp_path, change, settings, None)
    profile, related = build_context(tmp_path, sel.files, change.base_sha, settings, sel.index)
    [unit] = plan_units(tmp_path, sel, related, change.base_sha, settings)
    intent = Intent(source="merge request", kind="mr")  # nothing to assess: only the reviewer runs
    llm = FakeLLM()
    reviewed = review_and_check(settings, llm, change, sel.files, profile, [unit], related, intent, None, sel, [])

    assert not sel.split and reviewed.parts == 1 and reviewed.units[0]["files"] == [f.path for f in sel.files]
    [messages] = llm.messages
    assert messages == [  # exactly what the single-call reviewer sent before review units existed
        {"role": "system", "content": naive.SYSTEM_PROMPT},
        {"role": "user", "content": naive.build_user_message(change, sel.files, profile.render(), related.render())},
    ]


def test_the_review_prompt_layout_is_unchanged():
    change = ChangeRequest(provider="local", repo="r", ref="HEAD", title="T", base_sha="a", start_sha="a",
                           head_sha="b")
    files = parse_diff(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n")
    assert naive.build_user_message(change, files, "P", "R", "C", "K") == (
        "P\n\nC\n\nR\n\nK\n\n# Merge request: T\n\n## Description\n(no description)\n\n## Diff\n"
        "Left column is the new-file line number; `+` added, `-` removed, blank unchanged.\n\n"
        "### a.py (modified)\n@@\n       - x = 1\n     1 + x = 2\n")


class FailingLLM(FakeLLM):
    def call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens=None):
        if "### app/reports.py" in messages[-1]["content"]:
            raise LLMError("call failed (500)")
        return super().call_tool(model, messages, tool_name, tool_description, schema, max_tokens)


def test_a_failed_unit_makes_the_review_partial_and_all_failed_units_fail_it(tmp_path):
    change = commit(tmp_path, BASE, HEAD)
    settings = Settings.model_construct()
    sel = select_files(tmp_path, change, settings, None)
    profile, related = build_context(tmp_path, sel.files, change.base_sha, settings, sel.index)
    parts = [Unit([f for f in sel.files if f.path != "app/reports.py"], related=related),
             Unit([f for f in sel.files if f.path == "app/reports.py"], related=related)]
    intent = Intent(source="merge request", kind="mr")
    reviewed = review_and_check(settings, FailingLLM(), change, sel.files, profile, parts, related, intent, None,
                                sel, [])
    assert reviewed.parts == 1 and [u["status"] for u in reviewed.units] == ["ok", "failed"]
    assert reviewed.warnings[0].startswith("review of part 2 (app/reports.py) failed")
    with pytest.raises(LLMError):
        review_and_check(settings, FailingLLM(), change, sel.files, profile, parts[1:], related, intent, None, sel, [])


class QuotaLLM(FailingLLM):
    def call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens=None):
        if "### app/reports.py" in messages[-1]["content"]:
            raise QuotaExhaustedError("quota exhausted for m")
        return FakeLLM.call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens)


def test_a_spent_daily_quota_fails_the_review_even_when_other_units_succeeded(tmp_path):
    change = commit(tmp_path, BASE, HEAD)
    settings = Settings.model_construct()
    sel = select_files(tmp_path, change, settings, None)
    profile, related = build_context(tmp_path, sel.files, change.base_sha, settings, sel.index)
    parts = [Unit([f for f in sel.files if f.path != "app/reports.py"], related=related),
             Unit([f for f in sel.files if f.path == "app/reports.py"], related=related)]
    intent = Intent(source="merge request", kind="mr")
    with pytest.raises(QuotaExhaustedError):
        review_and_check(settings, QuotaLLM(), change, sel.files, profile, parts, related, intent, None, sel, [])
