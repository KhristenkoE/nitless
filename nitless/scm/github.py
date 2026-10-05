"""GitHub pull requests via the REST API (metadata) and git over HTTPS (code). github.com and Enterprise."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from nitless.errors import ChangeNotFoundError, ConfigError, RepoAccessError
from nitless.git import GitError, auth_env, run_git
from nitless.models import ChangeRequest
from nitless.scm.base import ScmProvider

log = logging.getLogger(__name__)

PR_URL_RE = re.compile(r"^(?P<scheme>https?)://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)")
GIT_USER = "x-access-token"  # the basic-auth user GitHub expects next to a token over HTTPS
API_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


@dataclass(frozen=True)
class PullRequestRef:
    base_url: str  # e.g. https://github.com
    owner: str
    repo: str
    number: int

    @property
    def project(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def web_url(self) -> str:
        return f"{self.base_url}/{self.project}/pull/{self.number}"

    @property
    def api_url(self) -> str:
        host = self.base_url.split("://", 1)[1]
        return "https://api.github.com" if host == "github.com" else f"{self.base_url}/api/v3"


def is_pr_url(url: str | None) -> bool:
    return bool(url) and PR_URL_RE.match(url.strip()) is not None  # type: ignore[arg-type]


def parse_pr_url(url: str) -> PullRequestRef:
    m = PR_URL_RE.match(url.strip())
    if not m:
        raise ConfigError(
            f"MR_URL is not a GitHub pull request URL: {url!r} (expected https://<host>/<owner>/<repo>/pull/<number>)"
        )
    return PullRequestRef(f"{m['scheme']}://{m['host']}", m["owner"], m["repo"], int(m["number"]))


class GitHubProvider(ScmProvider):
    name = "github"

    def __init__(self, ref: PullRequestRef, token: str | None, clone_url: str | None = None,
                 timeout_s: float = 30, transport: httpx.BaseTransport | None = None):
        self.ref = ref
        self.token = token
        self.clone_url = clone_url or f"{ref.base_url}/{ref.project}.git"
        headers = {**API_HEADERS, **({"Authorization": f"Bearer {token}"} if token else {})}
        self._http = httpx.Client(base_url=ref.api_url, headers=headers, timeout=timeout_s, transport=transport)

    def _get(self, path: str) -> dict:
        try:
            resp = self._http.get(path)
        except httpx.HTTPError as e:
            raise RepoAccessError(f"cannot reach GitHub at {self.ref.api_url}: {e}") from None
        if resp.status_code in (401, 403):
            hint = "token is invalid or lacks pull request read access" if self.token else "no GITHUB_TOKEN provided"
            raise RepoAccessError(f"GitHub denied access to {self.ref.project} ({resp.status_code}): {hint}")
        if resp.status_code == 404:
            hint = "" if self.token else " (private repositories need GITHUB_TOKEN)"
            raise ChangeNotFoundError(f"pull request #{self.ref.number} not found in {self.ref.project}{hint}")
        if resp.is_error:
            raise RepoAccessError(f"GitHub API error {resp.status_code} for {path}: {resp.text[:200]}")
        return resp.json()

    def fetch_change(self) -> ChangeRequest:
        pr = self._get(f"/repos/{self.ref.owner}/{self.ref.repo}/pulls/{self.ref.number}")
        base, head = pr.get("base") or {}, pr.get("head") or {}
        if not base.get("sha") or not head.get("sha"):
            raise ChangeNotFoundError(f"pull request #{self.ref.number} has no base or head commit yet")
        # GitHub reports the target branch tip as `base`, not a merge base; the pipeline diffs base..head as
        # given, which is what the GitLab provider does with GitLab's diff_refs as well.
        return ChangeRequest(
            provider=self.name,
            repo=self.ref.project,
            ref=f"#{self.ref.number}",
            title=pr.get("title") or "",
            description=pr.get("body") or "",
            author=(pr.get("user") or {}).get("login"),
            web_url=pr.get("html_url") or self.ref.web_url,
            source_branch=head.get("ref"),
            target_branch=base.get("ref"),
            base_sha=base["sha"],
            start_sha=base["sha"],
            head_sha=head["sha"],
        )

    def checkout(self, change: ChangeRequest, dest: Path) -> Path:
        env = auth_env(self.token, user=GIT_USER)
        secrets = (self.token or "",)
        try:
            run_git(["init", "-q", str(dest)])
            run_git(["remote", "add", "origin", self.clone_url], cwd=dest)
            try:
                # Two shallow commits are enough to diff and to read the head tree.
                run_git(["fetch", "-q", "--depth=1", "--no-tags", "origin", change.head_sha, change.base_sha],
                        cwd=dest, env=env, secrets=secrets)
            except GitError:
                # Server refuses fetching by SHA: fall back to the PR and target branch refs.
                log.info("fetch by SHA refused, fetching PR refs instead")
                refspecs = [f"+refs/pull/{self.ref.number}/head:refs/pr/head"]
                if change.target_branch:
                    refspecs.append(f"+refs/heads/{change.target_branch}:refs/pr/target")
                run_git(["fetch", "-q", "--no-tags", "origin", *refspecs], cwd=dest, env=env, secrets=secrets)
            run_git(["checkout", "-q", "--detach", change.head_sha], cwd=dest)
            run_git(["cat-file", "-e", f"{change.base_sha}^{{commit}}"], cwd=dest)
        except GitError as e:
            raise RepoAccessError(f"cannot fetch {self.clone_url}: {e}") from None
        return dest

    def fetch_commit(self, repo_dir: Path, sha: str) -> None:
        run_git(["fetch", "-q", "--depth=1", "--no-tags", "origin", sha], cwd=repo_dir,
                env=auth_env(self.token, user=GIT_USER), secrets=(self.token or "",))
