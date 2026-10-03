"""GitLab merge requests via the REST API (metadata) and git over HTTPS (code)."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from nitless.errors import ChangeNotFoundError, ConfigError, RepoAccessError
from nitless.git import GitError, auth_env, run_git
from nitless.models import ChangeRequest
from nitless.scm.base import ScmProvider

log = logging.getLogger(__name__)

MR_URL_RE = re.compile(r"^(?P<scheme>https?)://(?P<host>[^/]+)/(?P<project>.+?)/-/merge_requests/(?P<iid>\d+)")


@dataclass(frozen=True)
class MergeRequestRef:
    base_url: str  # e.g. https://gitlab.example.com
    project: str  # e.g. group/sub/project
    iid: int

    @property
    def web_url(self) -> str:
        return f"{self.base_url}/{self.project}/-/merge_requests/{self.iid}"


def parse_mr_url(url: str) -> MergeRequestRef:
    m = MR_URL_RE.match(url.strip())
    if not m:
        raise ConfigError(
            f"MR_URL is not a GitLab merge request URL: {url!r} "
            "(expected https://<host>/<group>/<project>/-/merge_requests/<iid>)"
        )
    return MergeRequestRef(f"{m['scheme']}://{m['host']}", m["project"], int(m["iid"]))


class GitLabProvider(ScmProvider):
    name = "gitlab"

    def __init__(self, ref: MergeRequestRef, token: str | None, clone_url: str | None = None,
                 timeout_s: float = 30):
        self.ref = ref
        self.token = token
        self.clone_url = clone_url or f"{ref.base_url}/{ref.project}.git"
        headers = {"PRIVATE-TOKEN": token} if token else {}
        self._http = httpx.Client(base_url=f"{ref.base_url}/api/v4", headers=headers, timeout=timeout_s)

    def _get(self, path: str) -> dict:
        try:
            resp = self._http.get(path)
        except httpx.HTTPError as e:
            raise RepoAccessError(f"cannot reach GitLab at {self.ref.base_url}: {e}") from None
        if resp.status_code in (401, 403):
            hint = "token is invalid or lacks read_api scope" if self.token else "no GITLAB_TOKEN provided"
            raise RepoAccessError(f"GitLab denied access to {self.ref.project} ({resp.status_code}): {hint}")
        if resp.status_code == 404:
            hint = "" if self.token else " (private projects need GITLAB_TOKEN)"
            raise ChangeNotFoundError(f"merge request !{self.ref.iid} not found in {self.ref.project}{hint}")
        if resp.is_error:
            raise RepoAccessError(f"GitLab API error {resp.status_code} for {path}: {resp.text[:200]}")
        return resp.json()

    def fetch_change(self) -> ChangeRequest:
        project = quote(self.ref.project, safe="")
        mr = self._get(f"/projects/{project}/merge_requests/{self.ref.iid}")
        refs = mr.get("diff_refs") or {}
        if not refs.get("head_sha") or not refs.get("base_sha"):
            raise ChangeNotFoundError(f"merge request !{self.ref.iid} has no diff yet (empty or still preparing)")
        return ChangeRequest(
            provider=self.name,
            repo=f"{self.ref.base_url}/{self.ref.project}",
            ref=mr.get("web_url") or self.ref.web_url,
            title=mr.get("title") or "",
            description=mr.get("description") or "",
            author=(mr.get("author") or {}).get("username"),
            web_url=mr.get("web_url"),
            source_branch=mr.get("source_branch"),
            target_branch=mr.get("target_branch"),
            base_sha=refs["base_sha"],
            start_sha=refs.get("start_sha") or refs["base_sha"],
            head_sha=refs["head_sha"],
        )

    def checkout(self, change: ChangeRequest, dest: Path) -> Path:
        env = auth_env(self.token)
        secrets = (self.token or "",)
        try:
            run_git(["init", "-q", str(dest)])
            run_git(["remote", "add", "origin", self.clone_url], cwd=dest)
            try:
                # Two shallow commits are enough to diff and to read the head tree.
                run_git(["fetch", "-q", "--depth=1", "--no-tags", "origin", change.head_sha, change.base_sha],
                        cwd=dest, env=env, secrets=secrets)
            except GitError:
                # Server refuses fetching by SHA: fall back to the MR and target branch refs.
                log.info("fetch by SHA refused, fetching MR refs instead")
                refspecs = [f"+refs/merge-requests/{self.ref.iid}/head:refs/mr/head"]
                if change.target_branch:
                    refspecs.append(f"+refs/heads/{change.target_branch}:refs/mr/target")
                run_git(["fetch", "-q", "--no-tags", "origin", *refspecs], cwd=dest, env=env, secrets=secrets)
            run_git(["checkout", "-q", "--detach", change.head_sha], cwd=dest)
            run_git(["cat-file", "-e", f"{change.base_sha}^{{commit}}"], cwd=dest)
        except GitError as e:
            raise RepoAccessError(f"cannot fetch {self.clone_url}: {e}") from None
        return dest
