"""Read-only repository tools for the reviewer and verifier agents (TOOLS=on).

Tools reach only the files the review indexes: tracked files of the checked-out head, minus the excludes.
Untracked files, `.git` and anything outside the checkout are unreachable, and a path that tries to leave
the repository is rejected. Every result is capped, and a Toolbox enforces one agent's budget: at most
`max_calls` calls and `max_tokens` tokens of results, each call appended to the shared trace.
"""

import posixpath
import re
import threading
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from nitless.context.base import estimate_tokens, truncate
from nitless.context.graph import contract, cut
from nitless.context.index import RepoIndex
from nitless.context.packer import format_ranges, render_lines
from nitless.context.symbols import CLASS_KINDS

MAX_RESULT_TOKENS = 3000
MAX_READ_LINES = 200
MAX_HITS = 40
MAX_DEFINITIONS = 3
MAX_ENTRIES = 150
MAX_LINE_CHARS = 200
SYMBOL_RE = re.compile(r"[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*")


class ToolError(Exception):
    """A tool call the model can correct (bad path, bad pattern); reported back to it, never raised further."""


def _fn(name: str, description: str, properties: dict[str, dict], required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


PATH = {"type": "string", "description": "repository-relative path, e.g. src/app/models.py"}
SYMBOL = {"type": "string", "description": "a function, class, method or field name; `Class.method` narrows it"}
SPECS = [
    _fn("read_file", f"Read lines of a repository file at the head version (at most {MAX_READ_LINES} lines).",
        {"path": PATH, "start": {"type": "integer", "description": "first line, 1-based (default 1)"},
         "end": {"type": "integer", "description": "last line, inclusive"}}, ["path"]),
    _fn("grep", f"Search tracked files with an extended regular expression (at most {MAX_HITS} matching lines).",
        {"pattern": {"type": "string", "description": "extended regex, e.g. 'percent_off|basis_points'"},
         "glob": {"type": "string", "description": "optional path filter, e.g. '*.py' or 'src/api/*'"}},
        ["pattern"]),
    _fn("find_definition", "Show where a symbol is defined: its signature, docs and body (or a class skeleton).",
        {"symbol": SYMBOL}, ["symbol"]),
    _fn("find_references", f"List lines that use a symbol as a whole word (at most {MAX_HITS}).",
        {"symbol": SYMBOL}, ["symbol"]),
    _fn("list_dir", "List the files and subdirectories of a repository directory.",
        {"path": {**PATH, "description": "directory; '' or '.' for the repository root"}}, []),
]


def safe_path(repo: Path, path: str) -> str:
    """A normalized repository-relative path, or ToolError if it is absolute or leaves the repository."""
    raw = str(path or "").strip().replace("\\", "/")
    if "\0" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ToolError(f"{path!r} is not a repository-relative path")
    rel = posixpath.normpath(raw or ".")
    if rel == ".." or rel.startswith("../"):
        raise ToolError(f"{path!r} is outside the repository")
    root = repo.resolve()
    if not (root / rel).resolve().is_relative_to(root):  # a symlink pointing out of the checkout
        raise ToolError(f"{path!r} is outside the repository")
    return "" if rel == "." else rel


class Toolbox:
    """One agent's tools and budget. Thread-safe for the shared trace; one Toolbox per agent."""

    specs = SPECS

    def __init__(self, index: RepoIndex, owner: str, max_calls: int, max_tokens: int,
                 trace: list[dict] | None = None, lock: AbstractContextManager | None = None):
        self.index, self.owner = index, owner
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.calls = self.tokens = 0
        self.trace = trace if trace is not None else []
        self._lock = lock or threading.Lock()

    @property
    def exhausted(self) -> bool:
        return self.calls >= self.max_calls or self.tokens >= self.max_tokens

    def call(self, name: str, args: dict[str, Any]) -> str:
        if self.exhausted:
            return "Tool budget exhausted: submit your answer now."
        handler = {"read_file": self.read_file, "grep": self.grep, "find_definition": self.find_definition,
                   "find_references": self.find_references, "list_dir": self.list_dir}.get(name)
        error = None
        try:
            if handler is None:
                raise ToolError(f"unknown tool {name!r}")
            text = handler(**args)
        except (ToolError, TypeError, ValueError) as e:
            error = str(e)[:200]
            text = f"error: {error}"
        text = truncate(text, max(200, min(MAX_RESULT_TOKENS, self.max_tokens - self.tokens)))
        size = estimate_tokens(text)
        with self._lock:
            self.calls += 1
            self.tokens += size
            self.trace.append({"unit": self.owner, "tool": name, "args": args, "result_tokens": size,
                               **({"error": error} if error else {})})
        return text

    # --- tools --------------------------------------------------------------------------------

    def read_file(self, path: str, start: int = 1, end: int | None = None) -> str:
        rel = self._file(path)
        src = self.index.source(rel)
        if src is None:
            raise ToolError(f"{rel} is binary or too large to read")
        total = len(src.lines)
        start = max(1, int(start))
        end = min(total, int(end) if end else start + MAX_READ_LINES - 1, start + MAX_READ_LINES - 1)
        if start > total or end < start:
            raise ToolError(f"no lines {start}-{end}: {rel} has {total} lines")
        return f"{rel}, lines {start}-{end} of {total}\n" + render_lines(src.lines, [(start, end)])

    def grep(self, pattern: str, glob: str | None = None) -> str:
        if not pattern or len(pattern) > 200:
            raise ToolError("pattern must be 1-200 characters")
        pathspecs = (self._glob(glob),) if glob else ()
        hits = self.index.search(pattern, pathspecs)
        if hits is None:
            raise ToolError(f"invalid pattern or search failed: {pattern!r}")
        return _hit_list(hits, f"matches for /{pattern}/" + (f" in {glob}" if glob else ""))

    def find_definition(self, symbol: str) -> str:
        name, owner = self._symbol(symbol)
        found = []
        for path in dict.fromkeys(p for p, _, _ in self.index.grep([name])[name]):
            src = self.index.source(path)
            for d in src.named(name) if src else []:
                if owner is None or d.qualname.endswith(f"{owner}.{name}"):
                    ranges = contract(src, d) if d.kind in CLASS_KINDS else cut(d, None)
                    found.append(f"{d.kind} {d.qualname} in {path}, lines {format_ranges(list(ranges))}\n"
                                 + render_lines(src.lines, list(ranges)))
        if not found:
            return f"no definition of {symbol} found in the indexed files"
        more = len(found) - MAX_DEFINITIONS
        return "\n\n".join(found[:MAX_DEFINITIONS]) + (f"\n\n({more} more definitions not shown)" if more > 0 else "")

    def find_references(self, symbol: str) -> str:
        name, _ = self._symbol(symbol)
        hits = [(p, n, t) for p, n, t in self.index.grep([name])[name] if not self._defines(p, n, name)]
        return _hit_list(hits, f"references to {name}")

    def _defines(self, path: str, line: int, name: str) -> bool:
        src = self.index.source(path)
        return src is not None and any(d.line == line for d in src.named(name))

    def list_dir(self, path: str = "") -> str:
        rel = safe_path(self.index.repo, path)
        prefix = f"{rel}/" if rel else ""
        files, dirs = [], {}
        for p in sorted(self.index.files):
            if not p.startswith(prefix):
                continue
            rest = p[len(prefix):]
            if "/" in rest:
                top = rest.split("/", 1)[0]
                dirs[top] = dirs.get(top, 0) + 1
            else:
                files.append(rest)
        if not files and not dirs:
            raise ToolError(f"{path!r} is not a directory with tracked files")
        entries = [f"{d}/ ({n} files)" for d, n in dirs.items()] + files
        more = f"\n… {len(entries) - MAX_ENTRIES} more" if len(entries) > MAX_ENTRIES else ""
        return f"{rel or '.'}/\n" + "\n".join(entries[:MAX_ENTRIES]) + more

    # --- argument checks ----------------------------------------------------------------------

    def _file(self, path: str) -> str:
        rel = safe_path(self.index.repo, path)
        if rel not in self.index.files:
            raise ToolError(f"{rel or '.'} is not a tracked file (use list_dir or grep to find files)")
        return rel

    def _glob(self, glob: str) -> str:
        if glob.startswith(":") or ".." in glob.split("/"):
            raise ToolError(f"unsupported glob {glob!r}")
        return safe_path(self.index.repo, glob)

    @staticmethod
    def _symbol(symbol: str) -> tuple[str, str | None]:
        symbol = str(symbol or "").strip()
        if not SYMBOL_RE.fullmatch(symbol):
            raise ToolError(f"{symbol!r} is not a symbol name")
        owner, _, name = symbol.rpartition(".")
        return name, owner.rsplit(".", 1)[-1] or None


def _hit_list(hits: list[tuple[str, int, str]], title: str) -> str:
    if not hits:
        return f"no {title}"
    rows = [f"{p}:{n}: {t.strip()[:MAX_LINE_CHARS]}" for p, n, t in hits[:MAX_HITS]]
    more = f"\n… {len(hits) - MAX_HITS} more" if len(hits) > MAX_HITS else ""
    return f"{len(hits)} {title}:\n" + "\n".join(rows) + more
