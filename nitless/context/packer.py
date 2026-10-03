"""Context Packer: merge overlapping related-code snippets, fit them into a token budget, render with provenance."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from xml.sax.saxutils import quoteattr

from nitless.context.base import ContextItem, Kind
from nitless.context.symbols import SourceFile

if TYPE_CHECKING:
    from nitless.context.changes import ChangedSymbol
    from nitless.context.graph import Snippet

log = logging.getLogger(__name__)

KIND_ORDER = ("enclosing", "caller", "callee", "test", "fixture", "sibling", "config")
MERGE_GAP = 2  # snippets of one file this close together become one block
MAX_REASONS = 3

RELATED_HEADER = (
    "# Related code\n\n"
    "Code outside the diff that the change touches, selected by following symbols: the rest of each changed "
    "function (enclosing), usages of changed symbols (caller, test), definitions the changed lines use "
    "(callee, fixture), similar code in this repo (sibling) and framework setup (config). Each block says why "
    "it was selected; the left column is the line number in the head version of that file. Use it to confirm "
    "or refute a suspicion before reporting it, and cite `source` in the finding's evidence."
)


@dataclass
class RelatedContext:
    included: list[ContextItem]
    dropped: list[ContextItem]  # did not fit the token budget
    symbols: list[str] = field(default_factory=list)  # changed symbols, described
    notes: list[str] = field(default_factory=list)  # e.g. changed code without a related test
    budget_tokens: int = 0
    duration_s: float = 0.0
    # every sibling snippet the graph found (packed or not), by the changed file it was found for, best first,
    # and the index's file reader: the conventions card reads its evidence from these
    siblings: "dict[str, list[Snippet]]" = field(default_factory=dict)
    source_of: Callable[[str], SourceFile | None] | None = None

    @property
    def tokens(self) -> int:
        return sum(item.tokens for item in self.included)

    def render(self) -> str:
        if not self.included:
            return ""
        parts = [RELATED_HEADER]
        for item in self.included:
            parts.append(f"<context kind={quoteattr(item.kind)} source={quoteattr(item.source)} "
                         f"reason={quoteattr(item.reason)}>\n{item.text}\n</context>")
        return "\n\n".join(parts)

    def trace(self) -> dict:
        rows = [{"kind": item.kind, "source": item.source, "reason": item.reason, "tokens": item.tokens,
                 "score": item.score, "status": status}
                for status, items in (("included", self.included), ("dropped", self.dropped)) for item in items]
        return {"tokens": self.tokens, "budget_tokens": self.budget_tokens, "duration_s": self.duration_s,
                "changed_symbols": self.symbols, "notes": self.notes, "items": rows}


@dataclass
class _Block:
    path: str
    kind: Kind
    ranges: list[tuple[int, int]]
    reasons: list[str]
    score: float


def pack(snippets: "list[Snippet]", source_of: Callable[[str], SourceFile | None], budget_tokens: int,
         symbols: "list[ChangedSymbol]", notes: list[str]) -> RelatedContext:
    items = []
    for block in merge(snippets):
        src = source_of(block.path)
        if src is None:
            continue
        ranges = [(max(1, a), min(len(src.lines), b)) for a, b in block.ranges if a <= len(src.lines)]
        if not ranges:
            continue
        reason = "; ".join(block.reasons[:MAX_REASONS])
        if len(block.reasons) > MAX_REASONS:
            reason += f"; +{len(block.reasons) - MAX_REASONS} more"
        items.append(ContextItem(block.kind, f"{block.path}:{format_ranges(ranges)}", reason,
                                 render_lines(src.lines, ranges), priority=0, score=round(block.score, 1)))

    included, dropped, used = [], [], 0
    for item in sorted(items, key=lambda it: -(it.score or 0)):
        if used + item.tokens <= budget_tokens:
            included.append(item)
            used += item.tokens
        else:
            dropped.append(item)
    included.sort(key=lambda it: (KIND_ORDER.index(it.kind), -(it.score or 0)))
    log.info("related code: %d items, %d tokens (%d dropped over the %d-token budget)",
             len(included), used, len(dropped), budget_tokens)
    return RelatedContext(included, dropped, [s.describe() + f" in {s.path}" for s in symbols], notes,
                          budget_tokens)


def merge(snippets: "list[Snippet]") -> list[_Block]:
    """One block per cluster of overlapping (or nearly adjacent) snippets of a file; the best snippet names it."""
    blocks: list[_Block] = []
    for s in sorted(snippets, key=lambda s: -s.score):
        ranges = list(s.ranges)
        touching = [b for b in blocks if b.path == s.path and _touches(b.ranges, ranges)]
        if not touching:
            blocks.append(_Block(s.path, s.kind, _union(ranges), [s.reason], s.score))
            continue
        keep = touching[0]
        for other in touching[1:]:
            keep.ranges += other.ranges
            keep.reasons += [r for r in other.reasons if r not in keep.reasons]
            blocks.remove(other)
        keep.ranges = _union(keep.ranges + ranges)
        if s.reason not in keep.reasons:
            keep.reasons.append(s.reason)
    return blocks


def _touches(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    return any(x1 <= y2 + MERGE_GAP and y1 <= x2 + MERGE_GAP for x1, x2 in a for y1, y2 in b)


def _union(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + MERGE_GAP + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def format_ranges(ranges: list[tuple[int, int]]) -> str:
    return ",".join(f"{a}-{b}" if a != b else str(a) for a, b in ranges)


def render_lines(lines: list[str], ranges: list[tuple[int, int]]) -> str:
    """Numbered lines like the diff rendering; `…` marks skipped lines between ranges."""
    out = []
    for i, (a, b) in enumerate(ranges):
        if i:
            out.append("     …")
        out += [f"{n:>6}  {lines[n - 1]}" for n in range(a, b + 1)]
    return "\n".join(out)
