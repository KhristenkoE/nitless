import base64

import httpx
import pytest
from pydantic import SecretStr

from nitless.config import Settings
from nitless.errors import ChangeNotFoundError, ConfigError, RepoAccessError
from nitless.git import auth_env
from nitless.scm import make_provider
from nitless.scm.github import GitHubProvider, PullRequestRef, parse_pr_url
from nitless.scm.gitlab import GitLabProvider

PR_URL = "https://github.com/octo/widgets/pull/12"


def test_parse_pr_url_on_github_com():
    ref = parse_pr_url("https://github.com/octo/widgets/pull/12/files")
    assert ref == PullRequestRef("https://github.com", "octo", "widgets", 12)
    assert ref.api_url == "https://api.github.com"
    assert ref.web_url == PR_URL


def test_parse_pr_url_on_an_enterprise_host():
    ref = parse_pr_url("https://ghe.example.com/team/svc/pull/3")
    assert (ref.base_url, ref.project, ref.number) == ("https://ghe.example.com", "team/svc", 3)
    assert ref.api_url == "https://ghe.example.com/api/v3"


def test_parse_pr_url_rejects_a_gitlab_url():
    with pytest.raises(ConfigError, match="not a GitHub pull request URL"):
        parse_pr_url("https://gitlab.example.com/group/proj/-/merge_requests/7")


PR_JSON = {
    "number": 12, "title": "Add widgets", "body": "Closes #4", "html_url": PR_URL,
    "user": {"login": "octocat"},
    "base": {"ref": "main", "sha": "b" * 40},
    "head": {"ref": "feature/widgets", "sha": "h" * 40},
}


def provider(handler, token="ghp_x") -> GitHubProvider:
    return GitHubProvider(parse_pr_url(PR_URL), token=token, transport=httpx.MockTransport(handler))


def test_fetch_change_maps_the_pull_request():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=PR_JSON)

    change = provider(handler).fetch_change()

    (req,) = seen
    assert str(req.url) == "https://api.github.com/repos/octo/widgets/pulls/12"
    assert req.headers["Authorization"] == "Bearer ghp_x"
    assert req.headers["Accept"] == "application/vnd.github+json"
    assert req.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert change.provider == "github" and change.repo == "octo/widgets" and change.ref == "#12"
    assert (change.title, change.description, change.author, change.web_url) == (
        "Add widgets", "Closes #4", "octocat", PR_URL)
    assert (change.source_branch, change.target_branch) == ("feature/widgets", "main")
    assert (change.base_sha, change.start_sha, change.head_sha) == ("b" * 40, "b" * 40, "h" * 40)


def test_missing_pull_request_is_change_not_found():
    with pytest.raises(ChangeNotFoundError, match="pull request #12 not found in octo/widgets"):
        provider(lambda r: httpx.Response(404, json={"message": "Not Found"})).fetch_change()


def test_denied_access_is_repo_access_error_with_a_token_hint():
    with pytest.raises(RepoAccessError, match="lacks pull request read access"):
        provider(lambda r: httpx.Response(401, json={"message": "Bad credentials"})).fetch_change()
    with pytest.raises(RepoAccessError, match="no GITHUB_TOKEN provided"):
        provider(lambda r: httpx.Response(403), token=None).fetch_change()


def test_unreachable_api_is_repo_access_error():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(RepoAccessError, match="cannot reach GitHub"):
        provider(down).fetch_change()


def test_make_provider_dispatches_on_the_url():
    github = make_provider(Settings.model_construct(mr_url=PR_URL, github_token=SecretStr("ghp_x"), repo_url=None,
                                                    local_repo=None))
    assert isinstance(github, GitHubProvider) and github.token == "ghp_x"
    assert github.clone_url == "https://github.com/octo/widgets.git"

    gitlab = make_provider(Settings.model_construct(mr_url="https://gitlab.example.com/g/p/-/merge_requests/7",
                                                    gitlab_token=SecretStr("glpat-x"), repo_url=None,
                                                    local_repo=None))
    assert isinstance(gitlab, GitLabProvider) and gitlab.token == "glpat-x"


def test_git_auth_uses_the_github_basic_auth_user():
    env = auth_env("ghp_x", user="x-access-token")
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Basic " + base64.b64encode(b"x-access-token:ghp_x").decode()
    assert auth_env("t")["GIT_CONFIG_VALUE_0"].endswith(base64.b64encode(b"oauth2:t").decode())
