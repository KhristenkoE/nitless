import json
from pathlib import Path

import httpx
import pytest

from nitless.config import load_settings
from nitless.errors import ConfigError, PublishError
from nitless.models import ChangeRequest, ReviewResult
from nitless.output.github_review import SUMMARY_MARKER, GitHubReviewAdapter, fingerprint

FIXTURES = Path(__file__).parent / "fixtures"
PR_URL = "https://github.com/octo/widgets/pull/12"
REPO = "/repos/octo/widgets"
ISSUE_COMMENTS, REVIEW_COMMENTS = f"{REPO}/issues/12/comments", f"{REPO}/pulls/12/comments"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env
    for var in ("MR_URL", "LOCAL_REPO", "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "ANTHROPIC_API_KEY",
                "OUTPUT_ADAPTER", "GITHUB_DRY_RUN"):
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
    """Records every request; answers GETs from `comments` and `review_comments`, POST/PATCH with `status`."""

    def __init__(self, comments=(), review_comments=(), status=201, reject_lines=()):
        self.comments, self.review_comments = list(comments), list(review_comments)
        self.status, self.reject_lines = status, reject_lines
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
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
