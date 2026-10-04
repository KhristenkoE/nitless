"""Findings as GitHub pull request review comments plus one summary comment, idempotent across runs."""

import json
import logging
import re
from pathlib import Path

import httpx

from nitless.config import Settings
from nitless.errors import ConfigError, PublishError
from nitless.models import ChangeRequest, Finding, ReviewResult
from nitless.output.base import OutputAdapter
from nitless.output.gitlab_notes import FINGERPRINT_RE, SUMMARY_MARKER, fingerprint
from nitless.output.markdown import render, render_finding
from nitless.output.stale import can_clear, is_stale, resolved_body
from nitless.scm.github import API_HEADERS, PullRequestRef, is_pr_url, parse_pr_url

log = logging.getLogger(__name__)

DRY_RUN_FILE = "github-comments.json"
NEXT_PAGE_RE = re.compile(r'<[^>]*[?&]page=(\d+)[^>]*>;\s*rel="next"')
# REST cannot resolve a review thread; GraphQL can, given the thread id of the comment.
THREADS_QUERY = """query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) { pullRequest(number: $number) {
    reviewThreads(first: 100, after: $cursor) {
      nodes { id isResolved comments(first: 1) { nodes { databaseId } } }
      pageInfo { hasNextPage endCursor } } } } }"""
RESOLVE_MUTATION = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { id } } }"


class GitHubReviewAdapter(OutputAdapter):
    """Review comments for findings on changed lines, the report as an issue comment on the pull request.

    Existing comments are read first: a finding whose fingerprint is already there is skipped and the
    summary comment is updated in place. A finding GitHub cannot place (422: the line is not part of the
    diff) is listed in the summary instead. A comment from an earlier run whose finding is gone is resolved
    (see `nitless.output.stale`). Failed runs are never posted (`publishes_errors`).
    """

    name = "github"
    publishes_errors = False

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        super().__init__(settings)
        self._transport = transport  # tests pass httpx.MockTransport

    def validate(self) -> None:
        if not self.settings.mr_url:
            raise ConfigError("the github adapter needs MR_URL: it posts to a pull request, not to LOCAL_REPO")
        if not is_pr_url(self.settings.mr_url):
            raise ConfigError("the github adapter needs MR_URL to be a GitHub pull request URL "
                              "(https://<host>/<owner>/<repo>/pull/<number>)")
        if not self.settings.github_token:
            raise ConfigError("the github adapter needs GITHUB_TOKEN with pull request write access to post comments")

    def publish(self, result: ReviewResult, change: ChangeRequest | None) -> None:
        if change is None:
            raise PublishError("nothing to post: the change was not resolved")
        ref = parse_pr_url(self.settings.mr_url)  # type: ignore[arg-type]  (validate() checked)
        token = self.settings.github_token.get_secret_value()  # type: ignore[union-attr]
        headers = {**API_HEADERS, "Authorization": f"Bearer {token}"}
        self._http = httpx.Client(base_url=ref.api_url, headers=headers, timeout=30, transport=self._transport)
        repo = f"/repos/{ref.owner}/{ref.repo}"
        issue, pulls = f"{repo}/issues/{ref.number}", f"{repo}/pulls/{ref.number}"
        dry_run = self.settings.github_dry_run
        planned: list[dict] = []  # dry run: the requests that were not sent

        comments = self._list(f"{issue}/comments")
        review_comments = self._list(f"{pulls}/comments")
        bodies = [c.get("body") or "" for c in comments + review_comments]
        present = {fp for body in bodies for fp in FINGERPRINT_RE.findall(body)}
        summary_id = next((c["id"] for c in comments if SUMMARY_MARKER in (c.get("body") or "")), None)

        inline: set[str] = set()
        skipped = outside = 0
        for f in result.findings:
            fp = fingerprint(f)
            if fp in present:
                inline.add(f.id)
                skipped += 1
                continue
            payload = {"body": f"{render_finding(f)}\n\n<!-- nitless:fp={fp} -->", **_position(f, change)}
            if dry_run:
                planned.append({"method": "POST", "path": f"{pulls}/comments", "json": payload})
                inline.add(f.id)
            elif self._request("POST", f"{pulls}/comments", payload, tolerate=(422,)).status_code == 422:
                outside += 1
            else:
                inline.add(f.id)

        current = {fingerprint(f) for f in result.findings}
        cleared = self._clear_stale(ref, review_comments, current, result, change, planned if dry_run else None)

        body = render(result, change, inline=inline).rstrip()
        if summary_id is not None:
            body += f"\n\n_Updated for {change.head_sha[:8]}._"
        body += f"\n\n{SUMMARY_MARKER}"
        method, path = (("PATCH", f"{repo}/issues/comments/{summary_id}") if summary_id is not None
                        else ("POST", f"{issue}/comments"))
        if dry_run:
            planned.append({"method": method, "path": path, "json": {"body": body}})
            out = self._dry_run_path()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(planned, indent=2, ensure_ascii=False) + "\n")
            log.info("dry run: %d requests for review comments and 1 for the summary written to %s, nothing posted",
                     len(planned) - 1, out)
            return
        self._request(method, path, {"body": body})
        log.info("github: %d review comments posted, %d already present, %d outside the diff listed in the summary, "
                 "%d stale %s; summary comment %s", len(inline) - skipped, skipped, outside, cleared,
                 "deleted or resolved" if self.settings.stale_comments == "delete" else "resolved",
                 "updated" if summary_id else "created")

    def _clear_stale(self, ref: PullRequestRef, review_comments: list[dict], current: set[str],
                     result: ReviewResult, change: ChangeRequest, planned: list[dict] | None) -> int:
        """Resolve (or delete) this tool's earlier comments whose finding is gone; `planned` set: dry run."""
        mode = self.settings.stale_comments
        if mode == "keep" or not can_clear(result):
            return 0
        replied = {c["in_reply_to_id"] for c in review_comments if c.get("in_reply_to_id")}
        cleared, to_resolve = 0, []
        for c in review_comments:
            m = FINGERPRINT_RE.search(c.get("body") or "")
            if c.get("in_reply_to_id") or not m or not is_stale(m[1], c.get("path"), current, result):
                continue
            path = f"/repos/{ref.owner}/{ref.repo}/pulls/comments/{c['id']}"
            if mode == "delete" and c["id"] not in replied:
                method, payload = "DELETE", None
            else:
                method, payload = "PATCH", {"body": resolved_body(c["body"], m[1], change.head_sha)}
                to_resolve.append(c["id"])
            if planned is not None:
                planned.append({"method": method, "path": path, "json": payload})
            elif (status := self._request(method, path, payload, tolerate=(403, 404)).status_code) in (403, 404):
                log.warning("github: cannot %s stale comment %s (%d), left as is",
                            method.lower(), c["id"], status)
                to_resolve = [i for i in to_resolve if i != c["id"]]
                continue
            cleared += 1
        if to_resolve:
            if planned is not None:
                planned.append({"method": "POST", "path": "graphql", "json": {"resolveReviewThread": to_resolve}})
            else:
                self._resolve_threads(ref, set(to_resolve))
        return cleared

    def _resolve_threads(self, ref: PullRequestRef, comment_ids: set[int]) -> None:
        """Mark the threads that start with these comments resolved; best effort, the edit already says it."""
        url = ref.api_url.removesuffix("/v3") + "/graphql"  # api.github.com/graphql, <host>/api/graphql
        variables: dict = {"owner": ref.owner, "repo": ref.repo, "number": ref.number, "cursor": None}
        threads: list[str] = []
        while True:
            data = self._graphql(url, THREADS_QUERY, variables)
            if data is None:
                return
            conn = data["repository"]["pullRequest"]["reviewThreads"]
            threads += [t["id"] for t in conn["nodes"] if not t["isResolved"]
                        and any(c["databaseId"] in comment_ids for c in t["comments"]["nodes"])]
            if not conn["pageInfo"]["hasNextPage"]:
                break
            variables["cursor"] = conn["pageInfo"]["endCursor"]
        for thread in threads:
            if self._graphql(url, RESOLVE_MUTATION, {"id": thread}) is None:
                return

    def _graphql(self, url: str, query: str, variables: dict) -> dict | None:
        try:
            resp = self._http.post(url, json={"query": query, "variables": variables})
            data = resp.json() if not resp.is_error else None
        except (httpx.HTTPError, ValueError) as e:
            log.warning("github: stale comments rewritten, but their threads stay open: %s", e)
            return None
        if data is None or data.get("errors") or not data.get("data"):
            detail = (data or {}).get("errors") or f"HTTP {resp.status_code}"
            log.warning("github: stale comments rewritten, but their threads stay open: %s", str(detail)[:200])
            return None
        return data["data"]

    def _dry_run_path(self) -> Path:
        out = self.settings.output_file
        return (out.parent if out else Path.cwd()) / DRY_RUN_FILE

    def _list(self, path: str) -> list[dict]:
        """Every page of a list endpoint: follow the Link header, stop at a short page without one."""
        items: list[dict] = []
        page: int | None = 1
        while page:
            resp = self._request("GET", path, params={"per_page": 100, "page": page})
            batch = resp.json()
            items += batch
            m = NEXT_PAGE_RE.search(resp.headers.get("Link", ""))
            page = int(m[1]) if m else (page + 1 if len(batch) >= 100 else None)
        return items

    def _request(self, method: str, path: str, json: dict | None = None, *, params: dict | None = None,
                 tolerate: tuple[int, ...] = ()) -> httpx.Response:
        try:
            resp = self._http.request(method, path, json=json, params=params)
        except httpx.HTTPError as e:
            raise PublishError(f"cannot reach GitHub for {method} {path}: {e}") from None
        if resp.status_code in tolerate:
            return resp
        if resp.status_code in (401, 403):
            raise PublishError(f"GitHub denied {method} {path} ({resp.status_code}): "
                               "token lacks pull request write access")
        if resp.status_code == 404:
            raise PublishError(f"GitHub has no {path} (404): pull request or comment not found")
        if resp.is_error:
            raise PublishError(f"GitHub API error {resp.status_code} for {method} {path}: {resp.text[:200]}")
        return resp


def _position(f: Finding, change: ChangeRequest) -> dict:
    pos = {"commit_id": change.head_sha, "path": f.file, "line": f.line_end, "side": "RIGHT"}
    if f.line_start < f.line_end:
        pos |= {"start_line": f.line_start, "start_side": "RIGHT"}
    return pos
