"""Unified diff parsing and rendering.

We compute the diff ourselves with `git diff` (rather than trusting the SCM API's
truncated diff) and keep exact old/new line numbers for every line, so findings
can be anchored to real lines.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pathspec

from nitless.git import run_git

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")

FileStatus = Literal["added", "modified", "deleted", "renamed"]


@dataclass
class DiffLine:
    kind: Literal["+", "-", " "]
    old_no: int | None
    new_no: int | None
    text: str


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section: str
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    status: FileStatus = "modified"
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def added(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "+")

    @property
    def removed(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "-")

    def new_line_ranges(self) -> list[tuple[int, int]]:
        """Inclusive new-file line ranges covered by hunks (what a reviewer can anchor to)."""
        return [(h.new_start, h.new_start + max(h.new_count, 1) - 1) for h in self.hunks]

    def covers_line(self, line: int) -> bool:
        if self.status == "deleted":
            return True
        return any(start <= line <= end for start, end in self.new_line_ranges())


def compute_diff(repo: Path, base_sha: str, head_sha: str) -> list[FileDiff]:
    out = run_git(
        ["-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff", "-M", "-U3",
         "--src-prefix=a/", "--dst-prefix=b/", base_sha, head_sha],
        cwd=repo,
    )
    return parse_diff(out)


def _strip_prefix(path: str) -> str | None:
    if path == "/dev/null":
        return None
    if len(path) > 1 and path[0] == path[-1] == '"':
        path = path[1:-1]
    return path[2:] if path[:2] in ("a/", "b/") else path


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0
    old_left = new_left = 0  # lines still expected in the current hunk

    for raw in text.splitlines():
        if hunk is not None and (old_left > 0 or new_left > 0):
            # Inside a hunk, the header counts decide what is content; a removed line
            # like "-- comment" must not be mistaken for a "--- a/file" header.
            kind = raw[:1] or " "
            if kind == "\\":  # "\ No newline at end of file"
                continue
            if kind == "+":
                hunk.lines.append(DiffLine("+", None, new_no, raw[1:]))
                new_no, new_left = new_no + 1, new_left - 1
            elif kind == "-":
                hunk.lines.append(DiffLine("-", old_no, None, raw[1:]))
                old_no, old_left = old_no + 1, old_left - 1
            else:
                hunk.lines.append(DiffLine(" ", old_no, new_no, raw[1:]))
                old_no, new_no = old_no + 1, new_no + 1
                old_left, new_left = old_left - 1, new_left - 1
            continue
        if raw.startswith("diff --git "):
            # Paths here are ambiguous when they contain spaces; later lines override them.
            a, _, b = raw[len("diff --git "):].partition(" b/")
            current = FileDiff(old_path=_strip_prefix(a), new_path=b or None)
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if m := HUNK_RE.match(raw):
            old_no, new_no = int(m[1]), int(m[3])
            old_left = int(m[2]) if m[2] is not None else 1
            new_left = int(m[4]) if m[4] is not None else 1
            hunk = Hunk(old_no, old_left, new_no, new_left, m[5].strip())
            current.hunks.append(hunk)
        elif raw.startswith("--- "):
            current.old_path = _strip_prefix(raw[4:])
        elif raw.startswith("+++ "):
            current.new_path = _strip_prefix(raw[4:])
        elif raw.startswith("new file mode"):
            current.status, current.old_path = "added", None
        elif raw.startswith("deleted file mode"):
            current.status = "deleted"
        elif raw.startswith("rename from "):
            current.status, current.old_path = "renamed", raw[len("rename from "):]
        elif raw.startswith("rename to "):
            current.new_path = raw[len("rename to "):]
        elif raw.startswith("Binary files "):
            current.is_binary = True

    for f in files:
        if f.status == "deleted":
            f.new_path = None
    return files


def filter_excluded(files: list[FileDiff], patterns: list[str]) -> tuple[list[FileDiff], list[str]]:
    spec = pathspec.PathSpec.from_lines("gitignore", patterns)
    kept, skipped = [], []
    for f in files:
        if f.is_binary or spec.match_file(f.path):
            skipped.append(f.path)
        else:
            kept.append(f)
    return kept, skipped


def render_for_llm(files: list[FileDiff]) -> str:
    """Render hunks with explicit new-file line numbers so the model can cite exact lines."""
    parts = []
    for f in files:
        header = f"### {f.path} ({f.status}"
        if f.status == "renamed":
            header += f" from {f.old_path}"
        parts.append(header + ")")
        for h in f.hunks:
            parts.append(f"@@ {h.section}".rstrip())
            for ln in h.lines:
                num = "" if ln.new_no is None else str(ln.new_no)
                parts.append(f"{num:>6} {ln.kind} {ln.text}")
        parts.append("")
    return "\n".join(parts)
