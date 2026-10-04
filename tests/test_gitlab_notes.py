import json
from pathlib import Path

import httpx
import pytest

from nitless.config import load_settings
from nitless.errors import ConfigError, PublishError
from nitless.models import ChangeRequest, ReviewResult
from nitless.output.gitlab_notes import SUMMARY_MARKER, GitLabNotesAdapter, fingerprint

FIXTURES = Path(__file__).parent / "fixtures"
MR_URL = "https://gitlab.example.com/group/proj/-/merge_requests/7"
MR_PATH = "/projects/group%2Fproj/merge_requests/7"  # relative to <base_url>/api/v4


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env
    for var in ("MR_URL", "LOCAL_REPO", "GITLAB_TOKEN", "ANTHROPIC_API_KEY", "OUTPUT_ADAPTER", "GITLAB_DRY_RUN",
                "STALE_COMMENTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODEL_STRONG", "m")


@pytest.fixture
def result() -> ReviewResult:
    return ReviewResult.model_validate_json((FIXTURES / "py-partial-refunds.json").read_text())


@pytest.fixture
def change() -> ChangeRequest:
    return ChangeRequest(provider="gitlab", repo="r", ref="!7", title="Partial refunds", web_url=MR_URL,
                         base_sha="b" * 40, start_sha="s" * 40, head_sha="0123456789abcdef" + "h" * 24)


class FakeGitLab:
    """Records every request; answers GETs from `notes` and `discussions`, POST/PUT with `status`."""

    def __init__(self, notes=(), discussions=(), status=201, reject_lines=()):
        self.notes, self.discussions = list(notes), list(discussions)
        self.status, self.reject_lines = status, reject_lines
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET":
            assert request.url.params["per_page"] == "100"
            items = self.notes if request.url.path.endswith("/notes") else self.discussions
            return httpx.Response(200, json=items, headers={"X-Next-Page": ""})
        if request.method == "POST" and request.url.path.endswith("/discussions") and (
            json.loads(request.content)["position"]["new_line"] in self.reject_lines
        ):
            return httpx.Response(400, json={"message": "line_code=>[\"must be a valid line code\"]"})
        return httpx.Response(self.status, json={"id": 99})

    def sent(self, method: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method]


def path(request: httpx.Request) -> str:
    """The path as sent on the wire, with the project still URL-encoded."""
    return request.url.raw_path.split(b"?")[0].decode()


def adapter(server: FakeGitLab, tmp_path: Path, **overrides) -> GitLabNotesAdapter:
    settings = load_settings(mr_url=MR_URL, gitlab_token="glpat-x", output_adapter="gitlab",
                             output_file=tmp_path / "out" / "review.json", **overrides)
    return GitLabNotesAdapter(settings, transport=httpx.MockTransport(server))


def test_first_run_posts_discussions_then_the_summary(result, change, tmp_path):
    server = FakeGitLab()
    adapter(server, tmp_path).publish(result, change)

    assert [path(r) for r in server.sent("GET")] == [f"/api/v4{MR_PATH}/notes", f"/api/v4{MR_PATH}/discussions"]
    assert all(r.headers["PRIVATE-TOKEN"] == "glpat-x" for r in server.requests)
    posts = server.sent("POST")
    assert [path(r) for r in posts] == [f"/api/v4{MR_PATH}/discussions"] * 3 + [f"/api/v4{MR_PATH}/notes"]
    first = json.loads(posts[0].content)
    assert first["position"] == {"position_type": "text", "base_sha": "b" * 40, "start_sha": "s" * 40,
                                 "head_sha": change.head_sha, "new_path": "app/services/payments.py",
                                 "old_path": "app/services/payments.py", "new_line": 78}
    assert first["body"].startswith("🔴 **app/services/payments.py:78** · critical · `requirements` — ")
    assert first["body"].endswith(f"<!-- nitless:fp={fingerprint(result.findings[0])} -->")
    summary = json.loads(posts[-1].content)["body"]
    assert summary.startswith(f"# 🤖 AI review of [Partial refunds]({MR_URL})")
    assert summary.endswith(SUMMARY_MARKER)
    assert "💬 Posted as inline comments:\n\n- 🔴 **app/services/payments.py:78** · critical" in summary
    assert "Updated for" not in summary
    assert not server.sent("PUT")


def test_second_run_skips_present_findings_and_updates_the_summary(result, change, tmp_path):
    fps = [fingerprint(f) for f in result.findings]
    server = FakeGitLab(
        notes=[{"id": 5, "body": f"old report {SUMMARY_MARKER}"}, {"id": 6, "body": f"<!-- nitless:fp={fps[0]} -->"}],
        discussions=[{"id": "d1", "notes": [{"id": 7, "body": f"x <!-- nitless:fp={fps[1]} -->"}]},
                     {"id": "d2", "notes": [{"id": 8, "body": f"y <!-- nitless:fp={fps[2]} -->"}]}],
    )
    adapter(server, tmp_path).publish(result, change)

    assert not server.sent("POST")
    (put,) = server.sent("PUT")
    assert path(put) == f"/api/v4{MR_PATH}/notes/5"
    body = json.loads(put.content)["body"]
    assert body.endswith(f"_Updated for 01234567._\n\n{SUMMARY_MARKER}")
    assert body.count("**app/services/payments.py:78**") == 2 and "**tests/api/test_payments.py:94-115**" in body


def test_notes_are_read_across_pages(result, change, tmp_path):
    pages = {"1": [{"id": 1, "body": "first page"}], "2": [{"id": 5, "body": SUMMARY_MARKER}]}

    def paged(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(201, json={"id": 99})
        if request.url.path.endswith("/discussions"):
            return httpx.Response(200, json=[])
        page = request.url.params["page"]
        return httpx.Response(200, json=pages[page], headers={"X-Next-Page": "2" if page == "1" else ""})

    settings = load_settings(mr_url=MR_URL, gitlab_token="glpat-x", output_adapter="gitlab", gitlab_dry_run="on")
    GitLabNotesAdapter(settings, transport=httpx.MockTransport(paged)).publish(result, change)
    plan = json.loads((tmp_path / "gitlab-notes.json").read_text())  # OUTPUT_FILE unset: next to the cwd
    assert (plan[-1]["method"], plan[-1]["path"]) == ("PUT", f"{MR_PATH}/notes/5")


def test_finding_outside_the_diff_moves_into_the_summary(result, change, tmp_path):
    server = FakeGitLab(reject_lines=(94,))
    adapter(server, tmp_path).publish(result, change)

    summary = json.loads(server.sent("POST")[-1].content)["body"]
    assert ("### Findings outside the diff\n\n🟠 **tests/api/test_payments.py:94-115** · major · `test-coverage`"
            in summary)
    assert "- **tests/api/test_payments.py" not in summary
    assert summary.count("**app/services/payments.py:78**") == 2


def test_denied_token_is_a_publish_error(result, change, tmp_path):
    denied = httpx.MockTransport(lambda request: httpx.Response(401, json={"message": "401 Unauthorized"}))
    settings = load_settings(mr_url=MR_URL, gitlab_token="glpat-x", output_adapter="gitlab")
    with pytest.raises(PublishError, match="token lacks api scope"):
        GitLabNotesAdapter(settings, transport=denied).publish(result, change)


def test_server_error_is_a_publish_error_with_status(result, change, tmp_path):
    server = FakeGitLab(status=500)
    with pytest.raises(PublishError, match="GitLab API error 500 for POST"):
        adapter(server, tmp_path).publish(result, change)


def test_dry_run_only_reads_and_writes_the_plan(result, change, tmp_path):
    server = FakeGitLab(notes=[{"id": 5, "body": SUMMARY_MARKER}])
    adapter(server, tmp_path, gitlab_dry_run="on").publish(result, change)

    assert {r.method for r in server.requests} == {"GET"}
    plan = json.loads((tmp_path / "out" / "gitlab-notes.json").read_text())
    assert [(p["method"], p["path"]) for p in plan] == [("POST", f"{MR_PATH}/discussions")] * 3 + [
        ("PUT", f"{MR_PATH}/notes/5")]
    assert plan[0]["json"]["position"]["new_line"] == 78
    assert plan[-1]["json"]["body"].endswith(SUMMARY_MARKER)


def test_validate_needs_mr_url_and_token(tmp_path):
    local = load_settings(local_repo=tmp_path, base_ref="main", output_adapter="gitlab")
    with pytest.raises(ConfigError, match="needs MR_URL"):
        GitLabNotesAdapter(local).validate()
    no_token = load_settings(mr_url=MR_URL, output_adapter="gitlab")
    with pytest.raises(ConfigError, match="GITLAB_TOKEN with the api scope"):
        GitLabNotesAdapter(no_token).validate()
    GitLabNotesAdapter(load_settings(mr_url=MR_URL, gitlab_token="t", output_adapter="gitlab")).validate()


def stale_discussions():
    note = {"id": 70, "body": "old finding\n\n<!-- nitless:fp=0123456789ab -->", "resolvable": True,
            "resolved": False, "position": {"new_path": "app/services/payments.py"}}
    answered = {"id": 80, "body": "<!-- nitless:fp=aaaaaaaaaaaa -->", "resolvable": True, "resolved": False,
                "position": {"new_path": "app/x.py"}}
    return [{"id": "d1", "notes": [note]},
            {"id": "d2", "notes": [answered, {"id": 81, "body": "fixed", "system": False}]},
            {"id": "d3", "notes": [{"id": 90, "body": "a human thread"}]}]


def test_stale_discussions_are_rewritten_and_resolved(result, change, tmp_path):
    server = FakeGitLab(discussions=stale_discussions())
    adapter(server, tmp_path).publish(result, change)

    puts = [(path(r), json.loads(r.content)) for r in server.sent("PUT")]
    assert [p for p, _ in puts] == [f"/api/v4{MR_PATH}/discussions/d1/notes/70", f"/api/v4{MR_PATH}/discussions/d1",
                                    f"/api/v4{MR_PATH}/discussions/d2/notes/80", f"/api/v4{MR_PATH}/discussions/d2"]
    assert puts[0][1]["body"].startswith("✅ No longer found as of 01234567.")
    assert puts[0][1]["body"].endswith("<!-- nitless:resolved=0123456789ab -->")
    assert puts[1][1] == {"resolved": True}
    assert not server.sent("DELETE")


def test_delete_mode_deletes_unanswered_discussions(result, change, tmp_path):
    server = FakeGitLab(discussions=stale_discussions())
    adapter(server, tmp_path, stale_comments="delete").publish(result, change)

    assert [path(r) for r in server.sent("DELETE")] == [f"/api/v4{MR_PATH}/discussions/d1/notes/70"]
    assert [path(r) for r in server.sent("PUT")] == [f"/api/v4{MR_PATH}/discussions/d2/notes/80",
                                                     f"/api/v4{MR_PATH}/discussions/d2"]


def test_partial_run_leaves_stale_discussions(result, change, tmp_path):
    server = FakeGitLab(discussions=stale_discussions())
    adapter(server, tmp_path).publish(result.model_copy(update={"status": "partial"}), change)

    assert not server.sent("PUT") and not server.sent("DELETE")
