"""Shared pieces of the context funnel: the ContextItem record and safe file reading."""

import logging
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 1_000_000
PROJECT_MARKERS = {"package.json", "pyproject.toml", "setup.py", "setup.cfg", "pom.xml", "build.gradle",
                   "build.gradle.kts", "go.mod", "Cargo.toml"}

Kind = Literal["repo_map", "manifest", "doc", "lint_config",  # project profile
               "enclosing", "caller", "callee", "sibling", "test", "fixture", "config"]  # related code


@dataclass
class ContextItem:
    kind: Kind
    source: str  # "README.md", "CONTRIBUTING.md#Server rules", "package.json"
    reason: str  # why it was selected, shown in the trace
    text: str
    priority: int  # lower = more important; decides what survives the token budget
    score: float | None = None  # related code: relevance, higher = more important

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def cap_lines(lines: list[str], limit: int) -> list[str]:
    return lines if len(lines) <= limit else [*lines[:limit], f"… {len(lines) - limit} more"]


def truncate(text: str, max_tokens: int) -> str:
    limit = max_tokens * 4
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n… (truncated)"


def read_text(repo: Path, path: str) -> str | None:
    """Read a repo file as text; None for missing, oversized or binary files."""
    full = repo / path
    try:
        if full.stat().st_size > MAX_FILE_BYTES:
            log.debug("skipping %s: larger than %d bytes", path, MAX_FILE_BYTES)
            return None
        data = full.read_bytes()
    except OSError as e:
        log.debug("cannot read %s: %s", path, e)
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def parent_dir(path: str) -> str:
    return posixpath.dirname(path)


def distance(scope_dir: str, path: str) -> int | None:
    """How many directories `path` sits below `scope_dir`, or None if it is outside it."""
    if scope_dir and not path.startswith(scope_dir + "/"):
        return None
    depth = scope_dir.count("/") + 1 if scope_dir else 0
    return path.count("/") - depth


def nearest(scope_dir: str, changed: list[str]) -> tuple[int, str] | None:
    """The closest changed file under `scope_dir`, as (distance, path)."""
    hits = [(d, p) for p in changed if (d := distance(scope_dir, p)) is not None]
    return min(hits) if hits else None


def scope_reason(what: str, scope_dir: str, changed: list[str]) -> str | None:
    """Explain why a directory-scoped file applies to this change, or None if it does not."""
    if not scope_dir:
        return f"repo-level {what}"
    hit = nearest(scope_dir, changed)
    if hit is None:
        return None
    under = sum(1 for p in changed if distance(scope_dir, p) is not None)
    return f"{what} in {scope_dir}/, an ancestor dir of {hit[1]} ({under} changed file{'s' * (under != 1)})"


def project_scope(files: list[str], changed: list[str]) -> Callable[[str], str | None]:
    """Map a file to the (sub-)project dir owning it, or None when that sub-project has no changed files.

    Keeps ADRs and rulesets of unrelated monorepo packages (or vendored fixture projects) out of the context.
    """
    projects = {parent_dir(p) for p in files if posixpath.basename(p) in PROJECT_MARKERS}

    def owner_if_changed(path: str) -> str | None:
        owner = parent_dir(path)
        while owner and owner not in projects:
            owner = parent_dir(owner)
        return owner if not owner or nearest(owner, changed) else None

    return owner_if_changed
