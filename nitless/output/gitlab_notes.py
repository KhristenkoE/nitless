"""Findings as GitLab merge request discussions plus one summary note, idempotent across runs."""

import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from nitless.config import Settings
from nitless.errors import ConfigError, PublishError
from nitless.incremental import ReviewState, parse_state
from nitless.models import ChangeRequest, Finding, ReviewResult
from nitless.output.base import OutputAdapter
from nitless.output.markdown import render, render_finding
from nitless.output.stale import can_clear, is_stale, resolved_body
from nitless.scm.gitlab import parse_mr_url

log = logging.getLogger(__name__)

SUMMARY_MARKER = "<!-- nitless:summary -->"
FINGERPRINT_RE = re.compile(r"<!-- nitless:fp=([0-9a-f]{12}) -->")
DRY_RUN_FILE = "gitlab-notes.json"


def fingerprint(f: Finding) -> str:
    """Same location and category → same inline comment, however the message is worded this time."""
    return hashlib.sha1(f"{f.file}:{f.line_start}:{f.line_end}:{f.category}".encode()).hexdigest()[:12]


class GitLabNotesAdapter(OutputAdapter):
    """Inline discussions for findings on changed lines, the report as a summary note.

    Existing notes are read first: a finding whose fingerprint is already there is skipped and the
    summary note is updated in place. A finding GitLab cannot place (400: the line is not part of the
    diff) is listed in the summary instead. A discussion from an earlier run whose finding is gone is resolved
    (see `nitless.output.stale`). Failed runs are never posted (`publishes_errors`).
    """

    name = "gitlab"
    publishes_errors = False

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        super().__init__(settings)
        self._transport = transport  # tests pass httpx.MockTransport

    def validate(self) -> None:
        if not self.settings.mr_url:
            raise ConfigError("the gitlab adapter needs MR_URL: it posts to a merge request, not to LOCAL_REPO")
        if not self.settings.gitlab_token:
            raise ConfigError("the gitlab adapter needs GITLAB_TOKEN with the api scope to post notes")

    def _connect(self) -> str:
        """Opens the client; returns the merge request's API path."""
        ref = parse_mr_url(self.settings.mr_url)  # type: ignore[arg-type]  (validate() checked)
        token = self.settings.gitlab_token.get_secret_value()  # type: ignore[union-attr]
        self._http = httpx.Client(base_url=f"{ref.base_url}/api/v4", headers={"PRIVATE-TOKEN": token},
                                  timeout=30, transport=self._transport)
        return f"/projects/{quote(ref.project, safe='')}/merge_requests/{ref.iid}"

    def previous_state(self) -> ReviewState | None:
        mr = self._connect()
        try:
            notes = self._list(f"{mr}/notes")
        except PublishError as e:
            log.info("gitlab: cannot read the previous review (%s), reviewing in full", e)
            return None
        summary = next((n["body"] for n in notes if SUMMARY_MARKER in n["body"]), "")
        return parse_state(summary, self.settings.llm_key)

    def publish(self, result: ReviewResult, change: ChangeRequest | None) -> None:
        if change is None:
            raise PublishError("nothing to post: the change was not resolved")
        mr = self._connect()
        dry_run = self.settings.gitlab_dry_run
        planned: list[dict] = []  # dry run: the requests that were not sent

        notes = self._list(f"{mr}/notes")
        discussions = self._list(f"{mr}/discussions")
        bodies = [n["body"] for n in notes]
        bodies += [n["body"] for d in discussions for n in d.get("notes", [])]
        present = {fp for body in bodies for fp in FINGERPRINT_RE.findall(body)}
        summary_id = next((n["id"] for n in notes if SUMMARY_MARKER in n["body"]), None)

        inline: set[str] = set()
        skipped = outside = 0
        for f in result.findings:
            fp = fingerprint(f)
            if fp in present:
                inline.add(f.id)
                skipped += 1
                continue
            payload = {"body": f"{render_finding(f)}\n\n<!-- nitless:fp={fp} -->",
                       "position": _position(f, change)}
            if dry_run:
                planned.append({"method": "POST", "path": f"{mr}/discussions", "json": payload})
                inline.add(f.id)
            elif self._request("POST", f"{mr}/discussions", payload, tolerate=(400,)).status_code == 400:
                outside += 1
            else:
                inline.add(f.id)

        current = {fingerprint(f) for f in result.findings}
        cleared = self._clear_stale(mr, discussions, current, result, change, planned if dry_run else None)

        body = render(result, change, inline=inline).rstrip()
        if summary_id is not None:
            body += f"\n\n_Updated for {change.head_sha[:8]}._"
        if result.state is not None and (state := result.state.marker(self.settings.llm_key)):
            body += f"\n\n{state}"
        body += f"\n\n{SUMMARY_MARKER}"
        method, path = ("PUT", f"{mr}/notes/{summary_id}") if summary_id is not None else ("POST", f"{mr}/notes")
        if dry_run:
            planned.append({"method": method, "path": path, "json": {"body": body}})
            out = self._dry_run_path()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(planned, indent=2, ensure_ascii=False) + "\n")
            log.info("dry run: %d requests for inline notes and 1 for the summary written to %s, nothing posted",
                     len(planned) - 1, out)
            return
        self._request(method, path, {"body": body})
        log.info("gitlab: %d inline notes posted, %d already present, %d outside the diff listed in the summary, "
                 "%d stale %s; summary note %s", len(inline) - skipped, skipped, outside, cleared,
                 "deleted or resolved" if self.settings.stale_comments == "delete" else "resolved",
                 "updated" if summary_id else "created")

    def _clear_stale(self, mr: str, discussions: list[dict], current: set[str], result: ReviewResult,
                     change: ChangeRequest, planned: list[dict] | None) -> int:
        """Resolve (or delete) this tool's earlier discussions whose finding is gone; `planned` set: dry run."""
        mode = self.settings.stale_comments
        if mode == "keep" or not can_clear(result):
            return 0
        cleared = 0
        for d in discussions:
            notes = [n for n in d.get("notes", []) if not n.get("system")]
            first = notes[0] if notes else {}
            m = FINGERPRINT_RE.search(first.get("body") or "")
            file = (first.get("position") or {}).get("new_path")
            if not m or not is_stale(m[1], file, current, result):
                continue
            note = f"{mr}/discussions/{d['id']}/notes/{first['id']}"
            if mode == "delete" and len(notes) == 1:
                requests = [("DELETE", note, None)]
            else:
                requests = [("PUT", note, {"body": resolved_body(first["body"], m[1], change.head_sha)})]
                if first.get("resolvable") and not first.get("resolved"):
                    requests.append(("PUT", f"{mr}/discussions/{d['id']}", {"resolved": True}))
            for method, path, payload in requests:
                if planned is not None:
                    planned.append({"method": method, "path": path, "json": payload})
                elif (status := self._request(method, path, payload, tolerate=(403, 404)).status_code) in (403, 404):
                    log.warning("gitlab: cannot update stale discussion %s (%d), left as is", d["id"], status)
                    break
            else:
                cleared += 1
        return cleared

    def _dry_run_path(self) -> Path:
        out = self.settings.output_file
        return (out.parent if out else Path.cwd()) / DRY_RUN_FILE

    def _list(self, path: str) -> list[dict]:
        """Every page of a list endpoint."""
        items: list[dict] = []
        page: str | None = "1"
        while page:
            resp = self._request("GET", path, params={"per_page": 100, "page": page})
            items += resp.json()
            page = resp.headers.get("X-Next-Page") or None
        return items

    def _request(self, method: str, path: str, json: dict | None = None, *, params: dict | None = None,
                 tolerate: tuple[int, ...] = ()) -> httpx.Response:
        try:
            resp = self._http.request(method, path, json=json, params=params)
        except httpx.HTTPError as e:
            raise PublishError(f"cannot reach GitLab for {method} {path}: {e}") from None
        if resp.status_code in tolerate:
            return resp
        if resp.status_code in (401, 403):
            raise PublishError(f"GitLab denied {method} {path} ({resp.status_code}): token lacks api scope")
        if resp.status_code == 404:
            raise PublishError(f"GitLab has no {path} (404): merge request or note not found")
        if resp.is_error:
            raise PublishError(f"GitLab API error {resp.status_code} for {method} {path}: {resp.text[:200]}")
        return resp


def _position(f: Finding, change: ChangeRequest) -> dict:
    return {"position_type": "text", "base_sha": change.base_sha, "start_sha": change.start_sha,
            "head_sha": change.head_sha, "new_path": f.file, "old_path": f.file, "new_line": f.line_start}
