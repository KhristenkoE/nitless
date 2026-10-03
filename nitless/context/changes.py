"""Which symbols a change touches: added, modified, signature-changed or removed definitions."""

from dataclasses import dataclass
from typing import Literal

from nitless.context.symbols import Definition, SourceFile
from nitless.diff import FileDiff

Change = Literal["added", "modified", "signature", "removed"]


@dataclass(frozen=True)
class ChangedSymbol:
    path: str
    definition: Definition  # head side; base side for removed symbols
    change: Change
    old_signature: str | None = None

    @property
    def breaking(self) -> bool:
        """Callers written against the old code may no longer work."""
        return self.change in ("signature", "removed")

    def describe(self) -> str:
        if self.change == "signature":
            return f"{self.definition.qualname} (signature changed from `{self.old_signature}`)"
        return f"{self.definition.qualname} ({self.change})"


@dataclass
class ChangedFile:
    diff: FileDiff
    new: SourceFile | None  # None for deleted or unreadable files
    old: SourceFile | None  # None for added files
    added_lines: set[int]  # new-side line numbers of `+` lines
    removed_lines: set[int]  # old-side line numbers of `-` lines
    symbols: list[ChangedSymbol]

    @property
    def path(self) -> str:
        return self.diff.path

    def in_diff(self, start: int, end: int) -> bool:
        """True when the whole range is already visible in the rendered diff hunks."""
        if self.diff.status == "added":
            return True
        return any(s <= start and end <= e for s, e in self.diff.new_line_ranges())


def changed_file(diff: FileDiff, new: SourceFile | None, old: SourceFile | None) -> ChangedFile:
    added = {ln.new_no for h in diff.hunks for ln in h.lines if ln.kind == "+" and ln.new_no is not None}
    removed = {ln.old_no for h in diff.hunks for ln in h.lines if ln.kind == "-" and ln.old_no is not None}
    # A pure deletion leaves no `+` line; anchor it at the hunk position so the enclosing symbol counts.
    touched = added | {h.new_start for h in diff.hunks if not any(ln.kind == "+" for ln in h.lines)}
    if new is not None:  # an added blank line between two methods does not change their class
        touched = {n for n in touched if n > len(new.lines) or new.lines[n - 1].strip()}
    return ChangedFile(diff, new, old, added, removed, changed_symbols(diff.path, new, old, touched, removed))


def changed_symbols(path: str, new: SourceFile | None, old: SourceFile | None,
                    touched: set[int], removed: set[int]) -> list[ChangedSymbol]:
    old_defs = {d.qualname: d for d in old.definitions} if old else {}
    new_defs = {d.qualname: d for d in new.definitions} if new else {}
    out: list[ChangedSymbol] = []
    for qualname, d in new_defs.items():
        if not any(d.contains(n) for n in touched) or _only_members_changed(d, new, touched):
            continue
        before = old_defs.get(qualname)
        if before is None:
            out.append(ChangedSymbol(path, d, "added"))
        elif before.signature != d.signature and d.kind != "variable":
            out.append(ChangedSymbol(path, d, "signature", before.signature))
        else:
            out.append(ChangedSymbol(path, d, "modified"))
    new_names = {d.name for d in new.definitions} if new else set()
    for qualname, d in old_defs.items():
        if qualname not in new_defs and d.name not in new_names and any(d.contains(n) for n in removed):
            out.append(ChangedSymbol(path, d, "removed"))
    return out


def _only_members_changed(d: Definition, source: SourceFile | None, touched: set[int]) -> bool:
    """A class whose changed lines all sit inside its members is represented by those members."""
    if source is None or d.kind not in ("class", "interface", "enum", "record"):
        return False
    members = source.members(d)
    return all(any(m.contains(n) for m in members) for n in touched if d.contains(n))
