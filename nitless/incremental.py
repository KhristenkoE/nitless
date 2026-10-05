"""Reviews that build on the previous one of the same pull request (INCREMENTAL=on).

The posting adapters keep a compact state in their summary comment: the head and base that were reviewed, a
fingerprint of everything that shapes a review (nitless version, models, review settings, the repository's
config and prompts) and the published findings as the reviewer claimed them, before the verifier's verdict.

    same head, same fingerprint      the stored result is published again; no LLM call
    new head, same base, fingerprint only files whose content changed since the reviewed head are reviewed;
                                     the claims on the other files are verified again with the new context,
                                     so a claim that a change elsewhere fixed is dropped like any other
    anything else                    a full review (rebased or force-pushed branch, new settings or version)

The requirements check always sees the whole change: acceptance criteria are judged on all of it.

The state is signed with a key derived from the LLM API key, which only the run has: anyone can comment on a
pull request, so an unsigned or forged state ("this head is reviewed, no findings") is ignored. Without an
API key (a keyless local server) no state is kept or trusted.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

from nitless import __version__, prompts
from nitless.config import Settings
from nitless.diff import FileDiff
from nitless.git import GitError, run_git
from nitless.models import Finding, ReviewResult
from nitless.repo_config import RepoConfig

log = logging.getLogger(__name__)

STATE_RE = re.compile(r"<!-- nitless:state=([A-Za-z0-9+/=]+)\.([0-9a-f]{64}) -->")
MAX_STATE_CHARS = 30000  # the comment must stay well under GitHub's 65536 and GitLab's 1M limits
# Settings that change what a review finds; output and runtime settings do not.
REVIEW_SETTINGS = ("model_strong", "model_fast", "model_verifier", "severity_floor", "min_confidence",
                   "max_findings", "verify", "conventions", "tools", "max_tool_calls", "path_excludes",
                   "ignore_categories", "max_diff_lines", "on_oversize", "unit_budget_tokens", "max_units",
                   "context_budget_tokens", "related_budget_tokens", "task_source")


class ReviewState(BaseModel):
    head_sha: str
    base_sha: str
    fingerprint: str
    result: ReviewResult  # as published, without the trace
    claims: list[Finding]  # the published findings before the verifier's verdict, requirements excluded

    def marker(self, api_key: str) -> str | None:
        """The state as a signed hidden comment line; None without a key or when it would be too large."""
        if not api_key:
            return None
        raw = self.model_dump_json(exclude={"result": {"context_trace"}}).encode()
        encoded = base64.b64encode(zlib.compress(raw, 9)).decode()
        if len(encoded) > MAX_STATE_CHARS:
            return None
        return f"<!-- nitless:state={encoded}.{_sign(encoded, api_key)} -->"


def parse_state(body: str, api_key: str) -> ReviewState | None:
    """The state kept in a summary comment; None when there is none, it is not signed by us, or is unreadable."""
    m = STATE_RE.search(body)
    if not m or not api_key:
        return None
    if not hmac.compare_digest(m[2], _sign(m[1], api_key)):
        log.warning("previous review state has a wrong signature (another API key, or edited); reviewing in full")
        return None
    try:
        return ReviewState.model_validate_json(zlib.decompress(base64.b64decode(m[1])))
    except (ValueError, zlib.error, ValidationError) as e:
        log.info("previous review state unreadable, reviewing in full: %s", e)
        return None


def _sign(encoded: str, api_key: str) -> str:
    key = hashlib.sha256(b"nitless-state:" + api_key.encode()).digest()
    return hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()


def fingerprint(settings: Settings, repo: RepoConfig) -> str:
    values = {key: getattr(settings, key) for key in REVIEW_SETTINGS}
    data = {"version": __version__, "settings": values, "repo": repo.model_dump(mode="json"),
            "repo_prompts": repo.prompts, "prompts": {name: prompts.default(name) for name in prompts.PROMPT_NAMES}}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class Plan:
    """What this run reviews, given the previous state."""

    mode: str  # full | unchanged | incremental
    reason: str
    changed: set[str] = field(default_factory=set)  # incremental: paths whose content changed since the state
    previous: ReviewState | None = None

    def carried(self, reviewable: set[str]) -> list[Finding]:
        """Incremental: the previous claims on files this run does not review but the change still contains."""
        if self.mode != "incremental" or self.previous is None:
            return []
        return [c for c in self.previous.claims if c.file not in self.changed and c.file in reviewable]

    def trace(self) -> dict:
        row: dict = {"mode": self.mode, "reason": self.reason}
        if self.previous is not None:
            row["previous_head"] = self.previous.head_sha
        if self.mode == "incremental":
            row["changed_since"] = sorted(self.changed)
        return row


def plan(settings: Settings, previous: ReviewState | None, head_sha: str, base_sha: str, current: str,
         repo_dir: Path, fetch: Callable[[str], None] | None = None) -> Plan:
    """Decide between a full, an unchanged and an incremental review. `fetch(sha)` makes a commit available."""
    if not settings.incremental:
        return Plan("full", "INCREMENTAL=off")
    if previous is None:
        return Plan("full", "no previous review")
    if previous.fingerprint != current:
        return Plan("full", "settings, config, prompts or nitless version changed since the last review")
    if previous.result.status != "ok":
        return Plan("full", f"the last review was {previous.result.status}")
    if previous.base_sha != base_sha:
        return Plan("full", "the base moved since the last review")
    if previous.head_sha == head_sha:
        return Plan("unchanged", "this head was reviewed with the same settings", previous=previous)
    try:
        if fetch is not None:
            fetch(previous.head_sha)
        out = run_git(["diff", "--name-only", "--no-renames", previous.head_sha, head_sha], cwd=repo_dir)
    except GitError as e:
        log.info("previous head %s unavailable (%s), reviewing in full", previous.head_sha[:8], e)
        return Plan("full", "the last reviewed head is no longer available (force-push?)")
    changed = {line for line in out.splitlines() if line}
    return Plan("incremental", f"{len(changed)} files changed since {previous.head_sha[:8]}", changed, previous)


def scope_note(reviewed: list[FileDiff], files: list[FileDiff], p: Plan) -> str:
    """Tells the reviewer of an incremental run which files it reviews and that the rest was reviewed before."""
    since = p.previous.head_sha[:8] if p.previous else "the last review"
    listed = "\n".join(f"- {f.path}" for f in reviewed)
    others = len(files) - len(reviewed)
    return (f"## Scope of this review\nThis merge request was reviewed at {since}. The files in the diff below "
            f"changed since then and are reviewed now; report issues only in them.\n{listed}"
            + (f"\n\nThe other {others} changed files were reviewed before and their findings are checked again "
               "separately; treat them as ordinary repository code here." if others else ""))
