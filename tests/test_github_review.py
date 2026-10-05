import json
from pathlib import Path

import httpx
import pytest

from nitless.config import load_settings
from nitless.errors import ConfigError, PublishError
from nitless.models import ChangeRequest, ReviewResult
from nitless.output.github_review import SUMMARY_MARKER, GitHubReviewAdapter, fingerprint
from nitless.output.stale import resolved_body

FIXTURES = Path(__file__).parent / "fixtures"
PR_URL = "https://github.com/octo/widgets/pull/12"
REPO = "/repos/octo/widgets"
ISSUE_COMMENTS, REVIEW_COMMENTS = f"{REPO}/issues/12/comments", f"{REPO}/pulls/12/comments"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env
    for var in ("MR_URL", "LOCAL_REPO", "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "ANTHROPIC_API_KEY",
                "OUTPUT_ADAPTER", "GITHUB_DRY_RUN", "STALE_COMMENTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODEL_STRONG", "m")


@pytest.fixture
def result() -> ReviewResult:
    return ReviewResult.model_validate_json((FIXTURES / "py-partial-refunds.json").read_text())


@pytest.fixture
def change() -> ChangeRequest:
    return ChangeRequest(provider="github", repo="octo/widgets", ref="#12", title="Partial refunds", web_url=PR_URL,
                         base_sha="b" * 40, start_sha="b" * 40, head_sha="0123456789abcdef" + "h" * 24)


class FakeGitHub:
    """Records every request; answers GETs from `comments` and `review_comments`, POST/PATCH with `status`,
    GraphQL from `threads` ({thread id: first comment id})."""

    def __init__(self, comments=(), review_comments=(), status=201, reject_lines=(), threads=None):
        self.comments, self.review_comments = list(comments), list(review_comments)
        self.status, self.reject_lines, self.threads = status, reject_lines, threads or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/graphql":
            query = json.loads(request.content)["query"]
            if "resolveReviewThread" in query:
                return httpx.Response(200, json={"data": {"resolveReviewThread": {"thread": {"id": "t"}}}})
            nodes = [{"id": t, "isResolved": False, "comments": {"nodes": [{"databaseId": c}]}}
                     for t, c in self.threads.items()]
            return httpx.Response(200, json={"data": {"repository": {"pullRequest": {"reviewThreads": {
                "nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}})
        if request.method == "GET":
            assert request.url.params["per_page"] == "100"
            items = self.comments if request.url.path == ISSUE_COMMENTS else self.review_comments
            return httpx.Response(200, json=items)
        if request.method == "POST" and request.url.path == REVIEW_COMMENTS and (
            json.loads(request.content)["line"] in self.reject_lines
        ):
            return httpx.Response(422, json={"message": "Validation Failed",
                                             "errors": [{"message": "Line could not be found in the diff"}]})
        return httpx.Response(self.status, json={"id": 99})

    def sent(self, method: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method]


def adapter(server: FakeGitHub, tmp_path: Path, **overrides) -> GitHubReviewAdapter:
    settings = load_settings(mr_url=PR_URL, github_token="ghp_x", output_adapter="github",
                             output_file=tmp_path / "out" / "review.json", **overrides)
    return GitHubReviewAdapter(settings, transport=httpx.MockTransport(server))


def test_first_run_posts_review_comments_then_the_summary(result, change, tmp_path):
    server = FakeGitHub()
    adapter(server, tmp_path).publish(result, change)

    assert [r.url.path for r in server.sent("GET")] == [ISSUE_COMMENTS, REVIEW_COMMENTS]
    assert all(r.url.host == "api.github.com" for r in server.requests)
    assert all(r.headers["Authorization"] == "Bearer ghp_x" for r in server.requests)
    assert all(r.headers["Accept"] == "application/vnd.github+json" for r in server.requests)
    assert all(r.headers["X-GitHub-Api-Version"] == "2022-11-28" for r in server.requests)
    posts = server.sent("POST")
    assert [r.url.path for r in posts] == [REVIEW_COMMENTS] * 3 + [ISSUE_COMMENTS]
    first = json.loads(posts[0].content)
    assert {k: v for k, v in first.items() if k != "body"} == {
        "commit_id": change.head_sha, "path": "app/services/payments.py", "line": 78, "side": "RIGHT"}
    assert first["body"].startswith("🔴 **app/services/payments.py:78** · critical · `requirements` — ")
    assert first["body"].endswith(f"<!-- nitless:fp={fingerprint(result.findings[0])} -->")
    span = json.loads(posts[2].content)
    assert (span["path"], span["start_line"], span["start_side"], span["line"], span["side"]) == (
        "tests/api/test_payments.py", 94, "RIGHT", 115, "RIGHT")
    summary = json.loads(posts[-1].content)["body"]
    assert summary.startswith(f"# 🤖 AI review of [Partial refunds]({PR_URL})")
    assert summary.endswith(SUMMARY_MARKER)
    assert "💬 Posted as inline comments:\n\n- 🔴 **app/services/payments.py:78** · critical" in summary
    assert "Updated for" not in summary
    assert not server.sent("PATCH")


def test_second_run_skips_present_findings_and_updates_the_summary(result, change, tmp_path):
    fps = [fingerprint(f) for f in result.findings]
    server = FakeGitHub(
        comments=[{"id": 5, "body": f"old report {SUMMARY_MARKER}"}, {"id": 6, "body": "unrelated"}],
        review_comments=[{"id": 7, "body": f"x <!-- nitless:fp={fps[0]} -->"},
                         {"id": 8, "body": f"y <!-- nitless:fp={fps[1]} -->"}],
    )
    adapter(server, tmp_path).publish(result, change)

    (post,) = server.sent("POST")
    assert post.url.path == REVIEW_COMMENTS
    assert json.loads(post.content)["body"].endswith(f"<!-- nitless:fp={fps[2]} -->")
    (patch,) = server.sent("PATCH")
    assert patch.url.path == f"{REPO}/issues/comments/5"
    body = json.loads(patch.content)["body"]
    assert body.endswith(f"_Updated for 01234567._\n\n{SUMMARY_MARKER}")
    assert body.count("**app/services/payments.py:78**") == 2 and "**tests/api/test_payments.py:94-115**" in body


def test_comments_are_read_across_pages(result, change, tmp_path):
    pages = {"1": [{"id": 1, "body": "first page"}], "2": [{"id": 5, "body": SUMMARY_MARKER}]}

    def paged(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(201, json={"id": 99})
        if request.url.path == REVIEW_COMMENTS:
            return httpx.Response(200, json=[])
        page = request.url.params["page"]
        link = f'<https://api.github.com{ISSUE_COMMENTS}?per_page=100&page=2>; rel="next"' if page == "1" else ""
        return httpx.Response(200, json=pages[page], headers={"Link": link})

    settings = load_settings(mr_url=PR_URL, github_token="ghp_x", output_adapter="github", github_dry_run="on")
    GitHubReviewAdapter(settings, transport=httpx.MockTransport(paged)).publish(result, change)
    plan = json.loads((tmp_path / "github-comments.json").read_text())  # OUTPUT_FILE unset: next to the cwd
    assert (plan[-1]["method"], plan[-1]["path"]) == ("PATCH", f"{REPO}/issues/comments/5")


def test_finding_outside_the_diff_moves_into_the_summary(result, change, tmp_path):
    server = FakeGitHub(reject_lines=(115,))
    adapter(server, tmp_path).publish(result, change)

    summary = json.loads(server.sent("POST")[-1].content)["body"]
    assert ("### Findings outside the diff\n\n🟠 **tests/api/test_payments.py:94-115** · major · `test-coverage`"
            in summary)
    assert "- **tests/api/test_payments.py" not in summary
    assert summary.count("**app/services/payments.py:78**") == 2


def test_denied_token_is_a_publish_error(result, change, tmp_path):
    denied = httpx.MockTransport(lambda request: httpx.Response(403, json={"message": "Forbidden"}))
    settings = load_settings(mr_url=PR_URL, github_token="ghp_x", output_adapter="github")
    with pytest.raises(PublishError, match="token lacks pull request write access"):
        GitHubReviewAdapter(settings, transport=denied).publish(result, change)


def test_server_error_is_a_publish_error_with_status(result, change, tmp_path):
    server = FakeGitHub(status=500)
    with pytest.raises(PublishError, match="GitHub API error 500 for POST"):
        adapter(server, tmp_path).publish(result, change)


def test_dry_run_only_reads_and_writes_the_plan(result, change, tmp_path):
    server = FakeGitHub(comments=[{"id": 5, "body": SUMMARY_MARKER}])
    adapter(server, tmp_path, github_dry_run="on").publish(result, change)

    assert {r.method for r in server.requests} == {"GET"}
    plan = json.loads((tmp_path / "out" / "github-comments.json").read_text())
    assert [(p["method"], p["path"]) for p in plan] == [("POST", REVIEW_COMMENTS)] * 3 + [
        ("PATCH", f"{REPO}/issues/comments/5")]
    assert (plan[0]["json"]["line"], plan[0]["json"]["side"]) == (78, "RIGHT")
    assert plan[-1]["json"]["body"].endswith(SUMMARY_MARKER)


def test_validate_needs_a_pull_request_url_and_token(tmp_path):
    local = load_settings(local_repo=tmp_path, base_ref="main", output_adapter="github")
    with pytest.raises(ConfigError, match="needs MR_URL"):
        GitHubReviewAdapter(local).validate()
    gitlab = load_settings(mr_url="https://gitlab.example.com/g/p/-/merge_requests/7", output_adapter="github")
    with pytest.raises(ConfigError, match="GitHub pull request URL"):
        GitHubReviewAdapter(gitlab).validate()
    no_token = load_settings(mr_url=PR_URL, output_adapter="github")
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        GitHubReviewAdapter(no_token).validate()
    GitHubReviewAdapter(load_settings(mr_url=PR_URL, github_token="t", output_adapter="github")).validate()


def test_gh_token_is_an_alias(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_alias")
    settings = load_settings(mr_url=PR_URL, output_adapter="github")
    assert settings.github_token.get_secret_value() == "ghp_alias"


STALE_FP = "0123456789ab"  # matches no finding of the fixture


def stale_comments():
    return [{"id": 40, "path": "app/services/payments.py", "body": f"old finding\n\n<!-- nitless:fp={STALE_FP} -->"},
            {"id": 41, "path": "app/x.py", "body": "<!-- nitless:fp=aaaaaaaaaaaa -->"},
            {"id": 42, "path": "app/x.py", "body": "I fixed it", "in_reply_to_id": 41},
            {"id": 43, "path": "app/y.py", "body": "a human comment"}]


def test_stale_comments_are_rewritten_and_their_threads_resolved(result, change, tmp_path):
    server = FakeGitHub(review_comments=stale_comments(), threads={"T40": 40, "T41": 41, "T43": 43})
    adapter(server, tmp_path).publish(result, change)

    patches = [r for r in server.sent("PATCH") if "/pulls/comments/" in r.url.path]
    assert [r.url.path for r in patches] == [f"{REPO}/pulls/comments/40", f"{REPO}/pulls/comments/41"]
    body = json.loads(patches[0].content)["body"]
    assert body.startswith("✅ No longer found as of 01234567.")
    assert "old finding" in body and "nitless:fp=" not in body
    assert body.endswith(f"<!-- nitless:resolved={STALE_FP} -->")
    resolved = [json.loads(r.content)["variables"]["id"] for r in server.requests
                if r.url.path == "/graphql" and "resolveReviewThread" in json.loads(r.content)["query"]]
    assert resolved == ["T40", "T41"]
    assert not server.sent("DELETE")


def test_delete_mode_deletes_unanswered_comments_and_resolves_answered_ones(result, change, tmp_path):
    server = FakeGitHub(review_comments=stale_comments(), threads={"T41": 41})
    adapter(server, tmp_path, stale_comments="delete").publish(result, change)

    assert [r.url.path for r in server.sent("DELETE")] == [f"{REPO}/pulls/comments/40"]
    assert [r.url.path for r in server.sent("PATCH") if "/pulls/" in r.url.path] == [f"{REPO}/pulls/comments/41"]


@pytest.mark.parametrize("case", ["partial", "keep", "skipped"])
def test_stale_comments_stay_when_the_run_cannot_tell(case, result, change, tmp_path):
    overrides = {"stale_comments": "keep"} if case == "keep" else {}
    if case == "partial":
        result = result.model_copy(update={"status": "partial"})
    if case == "skipped":
        result = result.model_copy(update={"skipped_files": ["app/services/payments.py", "app/x.py"]})
    server = FakeGitHub(review_comments=stale_comments())
    adapter(server, tmp_path, **overrides).publish(result, change)

    assert not server.sent("DELETE")
    assert not [r for r in server.requests if "/pulls/comments/" in r.url.path or r.url.path == "/graphql"]


def test_a_comment_nitless_cannot_edit_is_left_and_the_run_goes_on(result, change, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" and "/pulls/comments/" in request.url.path:
            return httpx.Response(403, json={"message": "Must have admin rights"})
        return server(request)

    server = FakeGitHub(review_comments=stale_comments()[:1])
    settings = load_settings(mr_url=PR_URL, github_token="ghp_x", output_adapter="github")
    GitHubReviewAdapter(settings, transport=httpx.MockTransport(handler)).publish(result, change)

    assert not [r for r in server.requests if r.url.path == "/graphql"]
    assert server.sent("POST")[-1].url.path == ISSUE_COMMENTS  # the summary is still posted


def test_failed_thread_lookup_is_only_a_warning(result, change, tmp_path, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/graphql":
            return httpx.Response(200, json={"errors": [{"message": "Resource not accessible by integration"}]})
        return server(request)

    server = FakeGitHub(review_comments=stale_comments()[:1])
    settings = load_settings(mr_url=PR_URL, github_token="ghp_x", output_adapter="github")
    GitHubReviewAdapter(settings, transport=httpx.MockTransport(handler)).publish(result, change)

    assert "threads stay open" in caplog.text
    assert server.sent("POST")[-1].url.path == ISSUE_COMMENTS


def test_dry_run_plans_the_stale_cleanup(result, change, tmp_path):
    server = FakeGitHub(review_comments=stale_comments())
    adapter(server, tmp_path, github_dry_run="on").publish(result, change)

    assert {r.method for r in server.requests} == {"GET"}
    plan = json.loads((tmp_path / "out" / "github-comments.json").read_text())
    assert [(p["method"], p["path"]) for p in plan[3:-1]] == [
        ("PATCH", f"{REPO}/pulls/comments/40"), ("PATCH", f"{REPO}/pulls/comments/41"), ("POST", "graphql")]


def test_a_resolved_comment_does_not_hide_a_finding_that_comes_back(result, change, tmp_path):
    fp = fingerprint(result.findings[0])
    old = resolved_body(f"x\n\n<!-- nitless:fp={fp} -->", fp, "f" * 40)
    server = FakeGitHub(review_comments=[{"id": 40, "path": result.findings[0].file, "body": old}])
    adapter(server, tmp_path).publish(result, change)

    assert [r.url.path for r in server.sent("POST")] == [REVIEW_COMMENTS] * 3 + [ISSUE_COMMENTS]
    assert not server.sent("PATCH")


def test_the_summary_keeps_a_signed_state_that_the_next_run_reads(result, change, tmp_path, monkeypatch):
    from nitless.incremental import ReviewState

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    result.state = ReviewState(head_sha=change.head_sha, base_sha=change.base_sha, fingerprint="f", result=result,
                               claims=result.findings)
    server = FakeGitHub()
    adapter(server, tmp_path).publish(result, change)
    summary = json.loads(server.sent("POST")[-1].content)["body"]
    assert "<!-- nitless:state=" in summary and summary.endswith(SUMMARY_MARKER)

    later = FakeGitHub(comments=[{"id": 1, "body": f"forged {summary.replace('nitless:summary', 'x')}"},
                                 {"id": 5, "body": summary}])
    state = adapter(later, tmp_path).previous_state()
    assert state.head_sha == change.head_sha and [c.id for c in state.claims] == [f.id for f in result.findings]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-other")  # a state signed with another key is not trusted
    assert adapter(FakeGitHub(comments=[{"id": 5, "body": summary}]), tmp_path).previous_state() is None


def test_an_unreadable_pull_request_means_no_previous_state(tmp_path):
    denied = httpx.MockTransport(lambda request: httpx.Response(403, json={"message": "Forbidden"}))
    settings = load_settings(mr_url=PR_URL, github_token="ghp_x", output_adapter="github")
    assert GitHubReviewAdapter(settings, transport=denied).previous_state() is None
