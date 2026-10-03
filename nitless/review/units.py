"""Review units: a large change split into groups of files that must be reviewed together.

A change whose diff fits UNIT_BUDGET_TOKENS is one unit, reviewed exactly as a single call always was.
A larger one loses its trivial hunks (triage.py) and is split along links between its changed files:
  uses     file A imports file B and uses a symbol whose definition B changes   (strongest)
  tests    a test file and the file it is named after
  imports  file A imports file B (or, in Java, mentions a class of its package)
Files are merged strongest link first while a unit's diff stays within the budget; what remains is
packed by directory, so small neighbouring groups share a unit. Each unit then gets its own related
code, packed for its changed symbols (the other units' changes count as ordinary repository code).
"""

import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field

from nitless.context.base import estimate_tokens
from nitless.context.index import RepoIndex, is_test_file
from nitless.context.packer import RelatedContext
from nitless.context.symbols import WORD_RE, language_of
from nitless.diff import FileDiff, render_for_llm
from nitless.review.triage import Triage

TEST_AFFIX_RE = re.compile(r"^(test_|tests_)|(_test|_tests|Test|Tests|IT|\.test|\.spec|_spec)$")
MIN_STEM = 4  # shorter class names are too ambiguous to link Java files by mention
MAX_LISTED_FILES = 40


@dataclass
class Unit:
    files: list[FileDiff]
    links: list[str] = field(default_factory=list)  # why these files are reviewed together
    related: RelatedContext | None = None

    @property
    def paths(self) -> list[str]:
        return [f.path for f in self.files]

    @property
    def tokens(self) -> int:
        return diff_tokens(self.files)


@dataclass(frozen=True)
class Link:
    weight: int
    a: str
    b: str
    reason: str


def diff_tokens(files: list[FileDiff]) -> int:
    return estimate_tokens(render_for_llm(files))


def split(files: list[FileDiff], index: RepoIndex, budget_tokens: int, max_units: int) -> list[Unit]:
    """Group `files` into units whose diffs fit `budget_tokens` (a single file larger than that is its own unit)."""
    order = {f.path: i for i, f in enumerate(files)}
    size = {f.path: diff_tokens([f]) for f in files}
    groups: dict[str, list[str]] = {p: [p] for p in order}  # root -> members
    root = {p: p for p in order}
    why: dict[str, list[str]] = defaultdict(list)

    for link in sorted(find_links(files, index), key=lambda k: (-k.weight, order[k.a], order[k.b])):
        ra, rb = root[link.a], root[link.b]
        if ra == rb or sum(size[p] for p in groups[ra] + groups[rb]) > budget_tokens:
            continue
        groups[ra] += groups.pop(rb)
        why[ra] += [*why.pop(rb, []), link.reason]
        for p in groups[ra]:
            root[p] = ra

    units: list[Unit] = []
    for r in sorted(groups, key=lambda r: (_area(groups[r]), order[r])):  # pack neighbours together
        members = sorted(groups[r], key=order.__getitem__)
        tokens = sum(size[p] for p in members)
        last = units[-1] if units else None
        if last is not None and sum(size[p] for p in last.paths) + tokens <= budget_tokens:
            last.files += [files[order[p]] for p in members]
            last.links += why[r]
        else:
            units.append(Unit([files[order[p]] for p in members], list(why[r])))
    while len(units) > max(1, max_units):  # over the unit limit: merge the two smallest
        a, b = sorted(units, key=lambda u: u.tokens)[:2]
        a.files, a.links = a.files + b.files, a.links + b.links
        units.remove(b)
    for u in units:
        u.files.sort(key=lambda f: order[f.path])
    return sorted(units, key=lambda u: order[u.files[0].path])


def find_links(files: list[FileDiff], index: RepoIndex) -> list[Link]:
    present = {f.path for f in files if f.status != "deleted"}
    changed_names = {f.path: _changed_names(f, index) for f in files if f.path in present}
    links: list[Link] = []
    for a in present:
        words = _words(index, a)
        targets = {t for _, t in index.imports(a) if t in present and t != a}
        if language_of(a) == "java":  # same package: no import needed
            targets |= {b for b in present if b != a and posixpath.dirname(b) == posixpath.dirname(a)
                        and len(stem := posixpath.splitext(posixpath.basename(b))[0]) >= MIN_STEM and stem in words}
        for b in sorted(targets):
            used = sorted(changed_names.get(b, set()) & words)
            links.append(Link(3, a, b, f"{a} uses {', '.join(used[:3])} changed in {b}") if used
                         else Link(2, a, b, f"{a} depends on {b}"))
    subjects = defaultdict(list)
    for p in present:
        if not is_test_file(p):
            subjects[_subject(p)].append(p)
    for t in sorted(p for p in present if is_test_file(p)):
        candidates = subjects.get(_subject(t), [])
        best = max((_shared_dirs(t, impl) for impl in candidates), default=0)
        links += [Link(3, t, impl, f"{t} tests {impl}") for impl in candidates if _shared_dirs(t, impl) == best]
    return links


def scope_note(unit: Unit, number: int, count: int, files: list[FileDiff], triage: Triage) -> str:
    """What the reviewer of one part of a large change needs to know about the rest of it ("" if nothing)."""
    lines = []
    if count > 1:
        lines.append(f"This merge request is large, so it is reviewed in {count} parts; this is part {number}. "
                     "Its diff below holds files that belong together. Report issues only in these files; the "
                     "other parts are reviewed separately, and their files are ordinary repository code here.")
        risky = [f"- {p}: {', '.join(triage.files[p].reasons)}" for p in unit.paths if triage.level(p) == "risky"]
        if risky:
            lines += ["", "Riskier changes in this part (triage):", *risky]
        others = [f for f in files if f.path not in set(unit.paths)]
        if others:
            listed = [f"- {f.path} ({f.status}, +{f.added} -{f.removed})" for f in others[:MAX_LISTED_FILES]]
            more = [f"- … {len(others) - MAX_LISTED_FILES} more"] if len(others) > MAX_LISTED_FILES else []
            lines += ["", "Changed in the other parts:", *listed, *more]
    if omitted := triage.omitted():
        kinds = ", ".join(f"{kind} {n}" for kind, n in omitted.most_common())
        renames = ", ".join(f"{a} → {b}" for a, b in sorted(triage.renames)[:8])
        lines += ["", f"Left out of the diff as trivial (cannot change behaviour): {kinds}."
                  + (f" Mechanical renames: {renames}." if renames else "")]
    return "## Scope of this review\n" + "\n".join(lines).strip() if lines else ""


def _changed_names(f: FileDiff, index: RepoIndex) -> set[str]:
    """Names of the definitions the diff's hunks touch in the head version."""
    src = index.source(f.path)
    if src is None:
        return set()
    ranges = f.new_line_ranges()
    return {d.name for d in src.definitions if any(d.start <= end and start <= d.end for start, end in ranges)}


def _words(index: RepoIndex, path: str) -> set[str]:
    src = index.source(path)
    return set(WORD_RE.findall("\n".join(src.lines))) if src else set()


def _subject(path: str) -> str:
    stem = posixpath.splitext(posixpath.basename(path))[0]
    stem = posixpath.splitext(stem)[0] if stem.endswith((".test", ".spec")) else stem
    return TEST_AFFIX_RE.sub("", stem).lower()


def _shared_dirs(a: str, b: str) -> int:
    """Directory names two paths have in common (tests/api/test_orders.py and app/api/orders.py share `api`)."""
    return len(set(a.split("/")[:-1]) & set(b.split("/")[:-1]))


def _area(paths: list[str]) -> str:
    return posixpath.commonpath([posixpath.dirname(p) for p in paths]) if paths else ""
