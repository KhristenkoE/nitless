import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nitless import incremental, pipeline
from nitless.config import load_settings
from nitless.errors import LLMError
from nitless.incremental import ReviewState, parse_state
from nitless.models import Finding, ReviewResult, RunMeta
from nitless.repo_config import RepoConfig
from nitless.review.schema import CandidateFinding, ReviewSubmission
from nitless.review.verifier import Verdict

KEY = "sk-test"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env
    for var in ("MR_URL", "LOCAL_REPO", "INCREMENTAL", "CONVENTIONS", "OUTPUT_ADAPTER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("MODEL_STRONG", "m")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str = "c") -> str:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def function(name: str, body: str) -> str:
    return f"def {name}(x):\n    y = x\n    {body}\n    return y\n"


class ScriptedLLM:
    """Flags line 3 of every reviewed file; the verifier keeps everything. Records which files each call saw."""

    def __init__(self):
        self.usage, self.usage_by_tool = {}, {}
        self.reviewed: list[list[str]] = []
        self.verified: list[str] = []

    def preflight(self, models):
        pass

    def call_tool(self, model, messages, tool_name, description, schema, max_tokens=None):
        user = messages[-1]["content"]
        if tool_name == "submit_review":
            diff = user.split("## Diff\n", 1)[1]
            files = sorted({line.split()[1] for line in diff.splitlines() if line.startswith("### ")})
            self.reviewed.append(files)
            return ReviewSubmission(assessment=f"Reviewed {', '.join(files)}.", findings=[
                CandidateFinding(file=f, line_start=3, severity="major", category="correctness",
                                 message=f"y is wrong in {f}", rationale="r", confidence=0.9) for f in files])
        if tool_name == "submit_verdict":
            self.verified.append(user.split("\n", 3)[2].split(":")[0])
            return Verdict(counter_argument="none", decision="keep", reason="valid", justification="j",
                           confidence=0.9)
        raise LLMError(f"unexpected {tool_name}")  # intent: degrades to the MR text


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    commit(path, {"app/a.py": function("a", "pass"), "app/b.py": function("b", "pass")})
    git(path, "checkout", "-q", "-b", "feature")
    return path


def review(repo: Path, tmp_path: Path, previous: ReviewState | None, llm: ScriptedLLM, **overrides):
    settings = load_settings(local_repo=repo, base_ref="main", conventions="off", **overrides)
    meta = RunMeta(tool_version="t", started_at=datetime.now(UTC), models={})
    workdir = tmp_path / f"work-{len(llm.reviewed)}-{len(llm.verified)}-{datetime.now().timestamp()}"
    workdir.mkdir()
    result, _, _ = pipeline._review(settings, llm, meta, workdir, previous)
    return result


def test_full_then_unchanged_then_incremental(repo, tmp_path):
    commit(repo, {"app/a.py": function("a", "y = y + 1"), "app/b.py": function("b", "y = y * 2")})
    first_llm = ScriptedLLM()
    first = review(repo, tmp_path, None, first_llm)
    assert first_llm.reviewed == [["app/a.py", "app/b.py"]]
    assert [f.file for f in first.findings] == ["app/a.py", "app/b.py"]
    assert first.context_trace["incremental"]["mode"] == "full"
    state = parse_state(first.state.marker(KEY), KEY)  # through the comment and back
    assert state.head_sha == first.run.head_sha and len(state.claims) == 2

    again = ScriptedLLM()
    same = review(repo, tmp_path, state, again)
    assert again.reviewed == [] and again.verified == []  # no LLM call at all
    assert same.findings == first.findings and same.summary == first.summary
    assert same.context_trace["incremental"]["mode"] == "unchanged"

    commit(repo, {"app/a.py": function("a", "y = y + 2")})  # a new push touching only a.py
    later = ScriptedLLM()
    third = review(repo, tmp_path, state, later)
    assert later.reviewed == [["app/a.py"]]  # only the file that changed since the reviewed head
    assert sorted(later.verified) == ["app/a.py", "app/b.py"]  # b.py's claim is verified again
    assert [f.file for f in third.findings] == ["app/a.py", "app/b.py"]
    assert third.context_trace["incremental"]["changed_since"] == ["app/a.py"]


def test_a_changed_setting_or_a_moved_base_means_a_full_review(repo, tmp_path):
    commit(repo, {"app/a.py": function("a", "y = y + 1")})
    state = parse_state(review(repo, tmp_path, None, ScriptedLLM()).state.marker(KEY), KEY)

    stricter = ScriptedLLM()
    review(repo, tmp_path, state, stricter, severity_floor="critical")
    assert stricter.reviewed == [["app/a.py"]]

    moved = state.model_copy(update={"base_sha": "0" * 40})
    llm = ScriptedLLM()
    assert review(repo, tmp_path, moved, llm).context_trace["incremental"]["reason"] == \
        "the base moved since the last review"
    assert llm.reviewed == [["app/a.py"]]

    off = ScriptedLLM()
    review(repo, tmp_path, state, off, incremental="off")
    assert off.reviewed == [["app/a.py"]]


def test_an_unknown_previous_head_falls_back_to_a_full_review(repo, tmp_path):
    commit(repo, {"app/a.py": function("a", "y = y + 1")})
    state = parse_state(review(repo, tmp_path, None, ScriptedLLM()).state.marker(KEY), KEY)
    commit(repo, {"app/b.py": function("b", "y = 0")})
    gone = state.model_copy(update={"head_sha": "f" * 40})  # force-pushed away

    llm = ScriptedLLM()
    result = review(repo, tmp_path, gone, llm)
    assert result.context_trace["incremental"]["mode"] == "full"
    assert llm.reviewed == [["app/a.py", "app/b.py"]]


def state_for(findings: list[Finding]) -> ReviewState:
    result = ReviewResult(status="ok", run=RunMeta(tool_version="t", started_at=datetime.now(UTC), models={}),
                          findings=findings)
    return ReviewState(head_sha="h" * 40, base_sha="b" * 40, fingerprint="f", result=result, claims=findings)


def finding(n: int) -> Finding:
    return Finding(id=f"id{n}", file=f"f{n}.py", line_start=1, line_end=1, severity="minor", category="correctness",
                   message="m" * 200, rationale="r" * 400, confidence=0.7)


def test_the_state_is_signed_with_the_api_key():
    marker = state_for([finding(1)]).marker(KEY)
    assert parse_state(f"summary\n\n{marker}", KEY).claims[0].id == "id1"
    assert parse_state(marker, "another-key") is None
    assert parse_state(marker.replace("state=", "state=A"), KEY) is None  # edited
    forged = marker.rsplit(".", 1)[0] + "." + "0" * 64 + " -->"
    assert parse_state(forged, KEY) is None
    assert state_for([]).marker("") is None and parse_state(marker, "") is None  # no key: no state


def test_a_state_too_large_for_a_comment_is_not_kept(monkeypatch):
    monkeypatch.setattr(incremental, "MAX_STATE_CHARS", 200)
    assert state_for([finding(n) for n in range(5)]).marker(KEY) is None


def test_fingerprint_follows_review_settings_not_output_settings(tmp_path):
    base = load_settings(local_repo=tmp_path, base_ref="main")
    repo = RepoConfig()
    print_ = incremental.fingerprint(base, repo)
    assert incremental.fingerprint(load_settings(local_repo=tmp_path, base_ref="main", log_level="DEBUG"),
                                   repo) == print_
    assert incremental.fingerprint(load_settings(local_repo=tmp_path, base_ref="main", min_confidence=0.9),
                                   repo) != print_
    assert incremental.fingerprint(base, RepoConfig(instructions="Be strict.")) != print_
