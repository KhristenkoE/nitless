"""The symbol graph around a change: code outside the diff that a reviewer needs to judge it.

Seven finders each return scored Snippets (kind + file ranges + reason):
  enclosing  the rest of the changed function, its class header and the file's imports
  caller     usages of modified/removed symbols (breaking changes first), import-confirmed
  callee     definitions the changed lines use: the contract (signature, docs, short body)
  sibling    the most similar peer method in the same file and peer files (as skeletons)
  test       existing tests that exercise the changed symbols
  fixture    pytest fixtures and shared test helpers the changed tests rely on
  config     bootstrap code configuring a framework the changed file uses (QueryClient, @ControllerAdvice)
packer.py merges overlapping snippets and fits them into the token budget.
"""

import logging
import posixpath
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nitless.context.changes import ChangedFile, ChangedSymbol, changed_file
from nitless.context.index import RepoIndex, hops, is_test_file, is_test_support
from nitless.context.packer import RelatedContext, pack
from nitless.context.repo_map import list_files
from nitless.context.symbols import CLASS_KINDS, WORD_RE, Definition, Import, Ref, SourceFile
from nitless.diff import FileDiff

log = logging.getLogger(__name__)

RelatedKind = Literal["enclosing", "caller", "callee", "sibling", "test", "fixture", "config"]
Ranges = tuple[tuple[int, int], ...]

MAX_SNIPPET_LINES = 60
FOCUS_WINDOW = 20  # lines kept around the point of interest when a definition is longer than a snippet
CONTRACT_LINES = 40  # callee: docs + signature + the start of the body
CLASS_PROLOGUE_LINES = 20  # fields between a class header and its first member
WHOLE_FILE_LINES = 40  # sibling files this short are shown whole instead of as a skeleton
MAX_CALLERS_PER_SYMBOL = 6
MAX_TESTS_PER_SYMBOL = 3
MAX_CALLEES_PER_FILE = 15
MAX_USED_CALLEES = 3  # callees whose other call sites are shown, per changed file
MAX_USES_PER_CALLEE = 2
MAX_PEERS_PER_FILE = 3
MAX_SIBLINGS_PER_FILE = 2
MAX_CONFIG_FILES = 3
MAX_CANDIDATE_FILES = 40  # files parsed per changed file when looking for members or siblings
MAX_NAME_HITS = 40  # an unconfirmed name with more hits than this is too ambiguous to follow
MIN_PEER_SIMILARITY = 0.15
MIN_SIBLING_SIMILARITY = 0.3
COMMON_NAMES = frozenset({  # too generic to follow by name alone
    "get", "set", "list", "run", "create", "update", "delete", "remove", "add", "save", "find", "load", "apply",
    "call", "execute", "handle", "process", "build", "parse", "render", "main", "start", "stop", "close", "open",
    "read", "write", "init", "setup", "reset", "clear", "size", "length", "count", "index", "type", "filter", "map",
    "id", "name", "value", "data", "key", "keys", "items", "values", "toString", "equals", "hashCode", "__init__",
    "constructor", "of", "from", "to", "next", "test",
})
BOOTSTRAP_RE = re.compile(
    r"^(main|app|index|server|bootstrap|application|wsgi|asgi|setup|urls)\.(py|[cm]?[jt]sx?)$"
    r"|(Application|Config|Configuration)\.java$", re.IGNORECASE)
JAVA_BOOTSTRAP_ANNOTATIONS = ("ControllerAdvice", "RestControllerAdvice", "Configuration", "SpringBootApplication")


@dataclass(frozen=True)
class Snippet:
    kind: RelatedKind
    path: str
    ranges: Ranges
    reason: str
    score: float
    origin: str = ""  # the changed file a sibling was selected for (the conventions card groups by it)


@dataclass
class Callee:
    path: str
    definition: Definition
    how: str  # how the reference was resolved, for the reason
    uses: int = 0
    direct: bool = False  # used on an added line, not only elsewhere in a changed function


def build_related(repo: Path, diffs: list[FileDiff], base_sha: str, excludes: list[str],
                  budget_tokens: int, index: RepoIndex | None = None) -> RelatedContext:
    """Related code for `diffs` (the change, or one review unit of it), packed into `budget_tokens`. Never raises.

    Pass `index` to share parsed files and `git grep` results between calls.
    """
    started = time.monotonic()
    try:
        index = index or RepoIndex(repo, list_files(repo, excludes), base_sha)
        graph = SymbolGraph(index, diffs)
        snippets = graph.collect()
    except Exception as e:  # noqa: BLE001 - related code is an optional input; the review goes on without it
        log.warning("related code unavailable: %s", e)
        log.debug("related code failure", exc_info=True)
        return RelatedContext([], [], [], [f"related code unavailable: {e}"])
    related = pack(snippets, index.source, budget_tokens, graph.symbols, graph.notes)
    related.duration_s = round(time.monotonic() - started, 2)
    related.source_of = index.source
    for s in sorted(snippets, key=lambda s: -s.score):
        if s.kind == "sibling" and s.origin:
            related.siblings.setdefault(s.origin, []).append(s)
    return related


class SymbolGraph:
    def __init__(self, index: RepoIndex, diffs: list[FileDiff]):
        self.index = index
        self.changes: dict[str, ChangedFile] = {}
        olds = index.base_sources([d.old_path for d in diffs if d.old_path and d.status != "added"])
        for diff in diffs:
            new = index.source(diff.path) if diff.status != "deleted" else None
            old = olds.get(diff.old_path) if diff.status != "added" else None
            self.changes[diff.path] = changed_file(diff, new, old)
        self.notes: list[str] = []
        self._word_cache: dict[str, set[str]] = {}

    @property
    def symbols(self) -> list[ChangedSymbol]:
        return [s for ch in self.changes.values() for s in ch.symbols]

    def collect(self) -> list[Snippet]:
        snippets: list[Snippet] = []
        for finder in (self.enclosing, self.callers, self.callees, self.peers, self.siblings, self.fixtures,
                       self.config):
            try:
                snippets += finder()
            except Exception as e:  # noqa: BLE001 - one broken finder must not take the others down
                log.debug("%s finder failed: %s", finder.__name__, e, exc_info=True)
        return [s for s in snippets if not self._visible(s)]

    def _visible(self, snippet: Snippet) -> bool:
        """Already fully shown in the diff."""
        ch = self.changes.get(snippet.path)
        return ch is not None and all(ch.in_diff(a, b) for a, b in snippet.ranges)

    def _code_changes(self) -> list[ChangedFile]:
        return [ch for ch in self.changes.values() if ch.new is not None and not is_test_file(ch.path)]

    # --- enclosing --------------------------------------------------------------------------

    def enclosing(self) -> list[Snippet]:
        out = []
        for ch in self._code_changes():
            src = ch.new
            if ch.diff.status == "added":
                continue
            if src.import_block:
                out.append(Snippet("enclosing", ch.path, (src.import_block,), f"imports of {ch.path}", 90))
            for sym in ch.symbols:
                d = sym.definition
                if sym.change == "removed":
                    continue
                if d.kind in ("function", "method"):
                    focus = min((n for n in ch.added_lines if d.contains(n)), default=d.line)
                    out.append(Snippet("enclosing", ch.path, cut(d, focus),
                                       f"enclosing {d.kind} {d.qualname} of the change", 100))
                parent = _parent(src, d)
                if parent is not None and parent.kind in CLASS_KINDS:
                    out.append(Snippet("enclosing", ch.path, class_header(src, parent),
                                       f"class {parent.qualname} around the changed {d.name}", 95))
        return out

    # --- callers and tests ------------------------------------------------------------------

    def callers(self) -> list[Snippet]:
        # A class whose body changed is not a breaking change for code that merely mentions it.
        symbols = [s for s in self.symbols if not is_test_file(s.path) and len(_call_name(s)) >= 3
                   and (s.definition.kind not in CLASS_KINDS or s.breaking)]
        by_name = self.index.grep(_call_name(s) for s in symbols)
        out, tested = [], set()
        for sym in symbols:
            name = _call_name(sym)
            candidates = []
            for path, line, _ in by_name[name]:
                test = is_test_file(path)
                if (sym.change == "added" and not test) or self._is_self(sym, path, line):
                    continue
                confirmation = self._confirm(path, line, name, sym.path, sym.definition.qualname)
                if confirmation is False:
                    continue
                if confirmation is None and (name in COMMON_NAMES or len(by_name[name]) > MAX_NAME_HITS):
                    continue
                snippet = self._usage_snippet(sym, path, line, test, confirmation)
                if snippet is not None:
                    candidates.append(snippet)
                    if test:
                        tested.add(sym.path)
            out += _best(candidates, "test", MAX_TESTS_PER_SYMBOL) + _best(candidates, "caller", MAX_CALLERS_PER_SYMBOL)
        self._note_untested(symbols, tested)
        return out

    def _is_self(self, sym: ChangedSymbol, path: str, line: int) -> bool:
        if path == sym.path and sym.definition.contains(line) and sym.change != "removed":
            return True
        ch = self.changes.get(path)
        return ch is not None and ch.in_diff(line, line)

    def _confirm(self, path: str, line: int, name: str, def_path: str, qualname: str) -> str | bool | None:
        """Why the hit is a real usage of the definition (str), False when it provably is not, None when unknown."""
        src = self.index.source(path)
        if src is None:
            return None
        imports_at = src.import_block or (0, 0)
        refs = [r for r in src.references(line, line) if r.name == name]
        if src.language and (not refs or imports_at[0] <= line <= imports_at[1]):
            return False  # the word only appears in a comment, a string or an import
        if path == def_path:
            return "same file"
        if any(d.line == line and d.name == name for d in src.definitions):
            return False  # another definition with the same name
        imports = self.index.imports(path)
        for ref in refs:
            root = (ref.receiver or "").split(".")[0].split("(")[0]
            for imp, target in imports:
                if root and imp.alias == root:
                    return f"via {root}, imported from {imp.module}" if target == def_path else False
        for imp, target in imports:
            if imp.alias == name and imp.name is not None:
                return f"imports {name} from {imp.module}" if target == def_path else False
        module = next((imp.module for imp, target in imports if target == def_path), None)
        if module is not None:
            return f"imports {module}"
        if src.language == "java" and posixpath.dirname(path) == posixpath.dirname(def_path):
            return "same package"
        owner = qualname.split(".")[0]
        if "." in qualname and owner in self._words(path):
            return f"references {owner}"
        return None

    def _words(self, path: str) -> set[str]:
        if path not in self._word_cache:
            src = self.index.source(path)
            self._word_cache[path] = set(WORD_RE.findall("\n".join(src.lines))) if src else set()
        return self._word_cache[path]

    def _usage_snippet(self, sym: ChangedSymbol, path: str, line: int, test: bool,
                       confirmation: str | None) -> Snippet | None:
        src = self.index.source(path)
        if src is None:
            return None
        where = src.enclosing(line, {"function", "method", "variable"})
        ranges = cut(where, line) if where else ((max(1, line - 5), min(len(src.lines), line + 5)),)
        score = (60 if test else 70) + (15 if sym.breaking else 0) + (10 if confirmation else 0) - min(10, 2 * hops(
            path, sym.path))
        what = f"{'test of' if test else 'caller of'} {sym.describe()}"
        return Snippet("test" if test else "caller", path, ranges,
                       f"{what}; {confirmation or 'name match, unconfirmed'}", score)

    def _note_untested(self, symbols: list[ChangedSymbol], tested: set[str]) -> None:
        test_text = " ".join("\n".join(ch.new.lines) for ch in self.changes.values()
                             if ch.new is not None and is_test_file(ch.path))
        test_words = set(WORD_RE.findall(test_text))
        for path in sorted({s.path for s in symbols if s.change != "removed"} - tested):
            names = [s.definition.name for s in symbols if s.path == path and s.change != "removed"]
            if not any(n in test_words for n in names):
                self.notes.append(f"no test references the changed symbols of {path}: {', '.join(names[:6])}")

    # --- callees ----------------------------------------------------------------------------

    def callees(self) -> list[Snippet]:
        out: list[Snippet] = []
        apis: dict[str, list[Callee]] = {}  # functions each changed file calls, for _other_uses
        for ch in self.changes.values():
            if ch.new is None or not ch.added_lines:
                continue
            bindings = {imp.alias: (imp, target) for imp, target in self.index.imports(ch.path) if imp.alias}
            found: dict[tuple[str, str], Callee] = {}
            for ref, direct in self._changed_refs(ch):
                resolved = self._resolve(ch, ref, bindings)
                if resolved is None:
                    continue
                path, d, how = resolved
                callee = found.setdefault((path, d.qualname), Callee(path, d, how))
                callee.uses += 1
                callee.direct |= direct
            ranked = sorted(found.values(), key=lambda c: -self._callee_score(ch, c))
            snippets = [s for c in ranked if (s := self._contract(ch, c))][:MAX_CALLEES_PER_FILE]
            out += snippets + [hop for s in snippets for hop in self._second_hop(s)]
            if not is_test_file(ch.path):
                apis[ch.path] = [c for c in ranked if c.direct and c.definition.kind in ("function", "method")
                                 and not is_test_file(c.path)]
        self.index.grep(c.definition.name for functions in apis.values() for c in functions)  # one search for all
        for path, functions in apis.items():
            out += self._other_uses(self.changes[path], functions)
        return out

    def _changed_refs(self, ch: ChangedFile) -> list[tuple[Ref, bool]]:
        """References on added lines (direct), then the rest of each changed function (its dependencies)."""
        refs = [(ref, True) for start, end in _runs(ch.added_lines) for ref in ch.new.references(start, end)]
        for sym in ch.symbols:
            d = sym.definition
            if sym.change != "removed" and d.kind in ("function", "method"):
                refs += [(ref, False) for ref in ch.new.references(d.start, d.end) if ref.line not in ch.added_lines]
        return refs

    def _resolve(self, ch: ChangedFile, ref: Ref, bindings: dict[str, tuple[Import, str | None]]
                 ) -> tuple[str, Definition, str] | None:
        """Where the thing a changed line uses is defined: imports first, then the same file, then members."""
        src = ch.new
        receiver = ref.receiver
        if receiver in ("self", "this", "cls"):
            return _found(ch.path, _member(src, ref.name), "same class")
        root = (receiver or "").split(".")[0]
        if receiver and root in bindings:
            imp, target = bindings[root]
            if target is None:
                return None
            d = _member(self.index.source(target), ref.name, owner=imp.name)
            return _found(target, d, f"{receiver}.{ref.name} from {imp.module}")
        if receiver:
            return self._typed_member(ch, ref)
        if ref.name in bindings:
            imp, target = bindings[ref.name]
            if target is None:
                return None
            name = ref.name if imp.name in (None, "default", "*") else imp.name
            return _found(target, _top_level(self.index.source(target), name), f"{ref.name} from {imp.module}")
        d = _top_level(src, ref.name)
        if d is not None:
            return ch.path, d, "same file"
        if src.language == "java":  # same-package classes need no import
            sibling = posixpath.join(posixpath.dirname(ch.path), f"{ref.name}.java")
            if sibling in self.index.files:
                return _found(sibling, _top_level(self.index.source(sibling), ref.name), "same package")
        return None

    def _typed_member(self, ch: ChangedFile, ref: Ref) -> tuple[str, Definition, str] | None:
        """`x.name(...)` with an untyped receiver: a member `name` of a class the changed file mentions."""
        words = self._words(ch.path)
        candidates = [t for _, t in self.index.imports(ch.path) if t] + self.index.same_dir(ch.path)
        for path in dict.fromkeys(candidates[:MAX_CANDIDATE_FILES]):
            src = self.index.source(path)
            for d in src.named(ref.name) if src else []:
                owner = d.qualname.rsplit(".", 1)[0]
                if "." in d.qualname and owner.split(".")[-1] in words:
                    return path, d, f"{ref.receiver}.{ref.name}, member of {owner}"
        return None

    def _callee_score(self, ch: ChangedFile, c: Callee) -> float:
        d = c.definition
        score = 80 - (5 if c.how == "same file" else 0) - (10 if " member of " in c.how else 0)
        score += min(6, 2 * (c.uses - 1)) - (10 if d.size <= 4 and d.kind not in CLASS_KINDS else 0)
        return score - (15 if is_test_file(ch.path) else 0) - (0 if c.direct else 15)

    def _contract(self, ch: ChangedFile, c: Callee) -> Snippet | None:
        d, target = c.definition, self.changes.get(c.path)
        if target is not None and target.in_diff(d.start, d.end):
            return None
        src = self.index.source(c.path)
        if src is None or (c.path == ch.path and any(d.contains(n) for n in ch.added_lines)):
            return None
        kind: RelatedKind = "fixture" if is_test_support(c.path) else "callee"
        used_by = f"the change in {ch.path}" if c.direct else f"a changed function in {ch.path}"
        return Snippet(kind, c.path, contract(src, d), f"{d.kind} {d.qualname} used by {used_by} ({c.how})",
                       self._callee_score(ch, c))

    def _other_uses(self, ch: ChangedFile, functions: list[Callee]) -> list[Snippet]:
        """How the rest of the codebase calls the functions the change calls; rarely used APIs first,
        because their few callers show the intended way to use them (StockLevel.setQuantity -> StockLedger.record)."""
        by_name = self.index.grep(c.definition.name for c in functions)
        ranked = []
        for c in functions:
            d, uses = c.definition, []
            for path, line, _ in by_name[d.name]:
                if path in self.changes or is_test_file(path) or (path == c.path and d.contains(line)):
                    continue
                confirmation = self._confirm(path, line, d.name, c.path, d.qualname)
                if confirmation:
                    uses.append((hops(path, ch.path), path, line, confirmation))
            if uses:
                ranked.append((len(uses), d.qualname, sorted(uses)[:MAX_USES_PER_CALLEE]))
        out = []
        for count, qualname, uses in sorted(ranked)[:MAX_USED_CALLEES]:
            for _, path, line, confirmation in uses:
                src = self.index.source(path)
                where = src.enclosing(line, {"function", "method", "variable"}) if src else None
                if where is not None:
                    out.append(Snippet("sibling", path, cut(where, line),
                                       f"another use of {qualname}, which the change also calls "
                                       f"({count} use{'s' * (count != 1)} outside the change; {confirmation})", 50,
                                       ch.path))
        return out

    def _second_hop(self, snippet: Snippet) -> list[Snippet]:
        """Same-file helpers a short callee delegates to (apiClient.get -> request)."""
        src = self.index.source(snippet.path)
        start, end = snippet.ranges[0]
        if src is None or end - start >= CONTRACT_LINES or snippet.kind != "callee":
            return []
        out, seen = [], set()
        for ref in src.references(start, end):
            d = _top_level(src, ref.name) if ref.receiver in (None, "this", "self") else None
            if d is None or d.name in seen or (d.start <= start and end <= d.end) or start <= d.line <= end:
                continue
            seen.add(d.name)
            out.append(Snippet("callee", snippet.path, contract(src, d),
                               f"{d.kind} {d.qualname}, which the callee at {snippet.path}:{start} relies on",
                               snippet.score - 20))
        return out[:3]

    # --- siblings ---------------------------------------------------------------------------

    def peers(self) -> list[Snippet]:
        """The most similar other member of the same class/file: how this codebase does the same thing."""
        out = []
        for ch in self._code_changes():
            src, found = ch.new, []
            changed = [s.definition for s in ch.symbols
                       if s.change != "removed" and s.definition.kind in ("function", "method")]
            for d in changed:
                mine = _names(src, d)
                parent = d.qualname.rpartition(".")[0]
                best, best_sim = None, 0.0
                for other in src.definitions:
                    if other.kind != d.kind or other.qualname.rpartition(".")[0] != parent or \
                            any(_overlaps(other, c) for c in changed):
                        continue
                    sim = _jaccard(mine, _names(src, other))
                    if sim > best_sim:
                        best, best_sim = other, sim
                if best is not None and best_sim >= MIN_PEER_SIMILARITY:
                    shared = ", ".join(sorted(mine & _names(src, best))[:5])
                    found.append(Snippet("sibling", ch.path, cut(best, None),
                                         f"peer of {d.qualname} in the same file (shares {shared})",
                                         55 + 20 * best_sim, ch.path))
            out += sorted(found, key=lambda s: -s.score)[:MAX_PEERS_PER_FILE]
        return out

    def siblings(self) -> list[Snippet]:
        """Peer files for code-only conventions: same directory/naming pattern, similar imports."""
        out: list[Snippet] = []
        taken: set[str] = set()
        changes = self._code_changes()
        self.index.grep(_module_word(t) for ch in changes for _, t in self.index.imports(ch.path) if t)  # one search
        for ch in changes:
            own = self._import_keys(ch.path)
            scored = []
            for path in self._sibling_candidates(ch.path):
                if path in self.changes or path in taken or is_test_file(path):
                    continue
                same_dir = posixpath.dirname(path) == posixpath.dirname(ch.path)
                sim = _jaccard(own, self._import_keys(path)) + 0.25 * same_dir + 0.25 * _same_pattern(ch.path, path)
                if sim >= MIN_SIBLING_SIMILARITY:
                    scored.append((sim, path, same_dir))
            focus = {r.name for a, b in _runs(ch.added_lines) for r in ch.new.references(a, b)}
            for sim, path, same_dir in sorted(scored, reverse=True)[:MAX_SIBLINGS_PER_FILE]:
                src = self.index.source(path)
                why = [w for w, ok in (("same directory", same_dir), ("same naming pattern",
                                                                       _same_pattern(ch.path, path))) if ok]
                shared = sorted(k.split(":", 1)[1] for k in own & self._import_keys(path))[:4]
                if shared:
                    why.append("shares imports " + ", ".join(shared))
                taken.add(path)
                out.append(Snippet("sibling", path, skeleton(src, focus),
                                   f"sibling of {ch.path}: {'; '.join(why)} (skeleton)", 40 + 20 * min(sim, 1.0),
                                   ch.path))
        return out

    def _sibling_candidates(self, path: str) -> list[str]:
        """Same-directory files, plus files importing the same in-repo modules as `path`."""
        targets = {t for _, t in self.index.imports(path) if t}
        stems = {_module_word(t) for t in targets}
        importers = []
        for hit_path in dict.fromkeys(p for hits in self.index.grep(stems).values() for p, _, _ in hits):
            if hit_path != path and targets & {t for _, t in self.index.imports(hit_path) if t}:
                importers.append(hit_path)
        return list(dict.fromkeys(self.index.same_dir(path)[:MAX_CANDIDATE_FILES] + importers))[
            : 2 * MAX_CANDIDATE_FILES]

    def _import_keys(self, path: str) -> set[str]:
        keys = set()
        for imp, target in self.index.imports(path):
            package = self.index.external_package(path, imp)
            if target:
                keys.add("repo:" + _module_word(target))
            elif package:
                keys.add("pkg:" + package)
        return keys

    # --- fixtures ---------------------------------------------------------------------------

    def fixtures(self) -> list[Snippet]:
        """pytest fixtures used by changed tests (resolved by name through the conftest.py chain)."""
        out = []
        for ch in self.changes.values():
            if ch.new is None or ch.new.language != "python" or not is_test_file(ch.path):
                continue
            used = {r.name for a, b in _runs(ch.added_lines) for r in ch.new.references(a, b) if r.receiver is None}
            for conftest in self.index.ancestors_named(ch.path, "conftest.py"):
                src = self.index.source(conftest)
                if src is None or conftest == ch.path:
                    continue
                for d in src.definitions:
                    if "." in d.qualname or d.name not in used:
                        continue
                    out.append(Snippet("fixture", conftest, cut(d, None),
                                       f"fixture {d.name} used by the changed tests in {ch.path}", 65))
                    for dep in {r.name for r in src.references(d.line, d.header_end)} - {d.name}:
                        for dd in src.named(dep):
                            if "." not in dd.qualname:
                                out.append(Snippet("fixture", conftest, cut(dd, None),
                                                   f"fixture {dep}, requested by fixture {d.name}", 50))
        return out

    # --- config -----------------------------------------------------------------------------

    def config(self) -> list[Snippet]:
        """Bootstrap/config code that configures a framework the changed file imports."""
        bootstrap = {p for p in self.index.files if BOOTSTRAP_RE.search(posixpath.basename(p))}
        for hits in self.index.grep(JAVA_BOOTSTRAP_ANNOTATIONS, ("*.java",)).values():
            bootstrap.update(path for path, _, text in hits if text.lstrip().startswith("@"))
        found: dict[str, Snippet] = {}
        for ch in self._code_changes():
            packages = self._packages(ch.path)
            if not packages:
                continue
            nearest = sorted(bootstrap - set(self.changes), key=lambda p: hops(p, ch.path))[:MAX_CANDIDATE_FILES]
            for path in nearest:
                snippet = self._config_snippet(path, packages, ch.path)
                if snippet is not None and (path not in found or found[path].score < snippet.score):
                    found[path] = snippet
        return sorted(found.values(), key=lambda s: -s.score)[:MAX_CONFIG_FILES]

    def _packages(self, path: str) -> dict[str, list[Import]]:
        out: dict[str, list[Import]] = defaultdict(list)
        for imp, _ in self.index.imports(path):
            package = self.index.external_package(path, imp)
            if package:
                out[package].append(imp)
        return out

    def _config_snippet(self, path: str, packages: dict[str, list[Import]], changed: str) -> Snippet | None:
        src = self.index.source(path)
        if src is None:
            return None
        theirs = self._packages(path)
        shared = sorted(set(packages) & set(theirs))
        if not shared:
            return None
        names = {imp.alias for package in shared for imp in theirs[package] if imp.alias}
        imports = src.import_block or (0, 0)
        ranges = []
        for start, end in src.blocks:
            if start >= imports[0] and end <= imports[1]:
                continue
            if names & {r.name for r in src.references(start, end)}:
                ranges.append((start, min(end, start + MAX_SNIPPET_LINES - 1)))
        if not ranges:
            return None
        return Snippet("config", path, tuple(ranges), f"configures {', '.join(shared)}, which {changed} uses",
                       45 - min(10, hops(path, changed)))


# --- snippet shapes ---------------------------------------------------------------------------


def cut(d: Definition, focus: int | None, limit: int = MAX_SNIPPET_LINES) -> Ranges:
    """A definition as a snippet; long ones keep their header plus a window around `focus`."""
    if d.size <= limit:
        return ((d.start, d.end),)
    header = (d.start, min(d.header_end, d.start + limit // 3))
    if focus is None or focus <= header[1] + FOCUS_WINDOW:
        return ((d.start, d.start + limit - 1),)
    return header, (max(header[1] + 1, focus - FOCUS_WINDOW), min(d.end, focus + FOCUS_WINDOW))


def contract(src: SourceFile, d: Definition) -> Ranges:
    """What a caller relies on: docs + signature + the start of the body; classes as a skeleton."""
    if d.kind in CLASS_KINDS and d.size > CONTRACT_LINES:
        members = src.members(d)
        first_member = min((m.start for m in members), default=d.end)
        ranges = [(d.start, min(d.header_end + CLASS_PROLOGUE_LINES, first_member - 1, d.end))]
        return (*ranges, *((m.line, m.header_end) for m in members))
    ranges = [(d.start, min(d.end, d.start + CONTRACT_LINES - 1))]
    parent = _parent(src, d)
    if parent is not None and parent.kind in CLASS_KINDS and parent.header_end - parent.start < 12:
        ranges.insert(0, (parent.start, parent.header_end))
    return tuple(ranges)


def class_header(src: SourceFile, cls: Definition) -> Ranges:
    """Class docs + declaration + fields before the first member, and a short constructor."""
    members = src.members(cls)
    first_member = min((m.start for m in members), default=cls.end)
    ranges = [(cls.start, max(cls.header_end, min(first_member - 1, cls.header_end + CLASS_PROLOGUE_LINES)))]
    for m in members:
        if m.name in ("__init__", "constructor", cls.name) and m.size <= 15:
            ranges.append((m.start, m.end))
    return tuple(ranges)


def skeleton(src: SourceFile, focus: set[str]) -> Ranges:
    """Signatures of a file's top-level definitions and their members, plus its most relevant function."""
    if len(src.lines) <= WHOLE_FILE_LINES:
        return ((1, len(src.lines)),)
    ranges = [(d.line, d.header_end) for d in src.definitions if d.qualname.count(".") <= 1]
    functions = [d for d in src.definitions if d.kind in ("function", "method")]
    if functions:
        best = max(functions, key=lambda d: (len(focus & _names(src, d)), -d.size))
        ranges += cut(best, None, limit=30)
    return tuple(sorted(ranges))


# --- helpers ----------------------------------------------------------------------------------


def _found(path: str, d: Definition | None, how: str) -> tuple[str, Definition, str] | None:
    return (path, d, how) if d is not None else None


def _top_level(src: SourceFile | None, name: str) -> Definition | None:
    if src is None:
        return None
    return next((d for d in src.definitions if d.qualname == name), None)


def _member(src: SourceFile | None, name: str, owner: str | None = None) -> Definition | None:
    """`name` as a member of `owner` (or of any class), falling back to a top-level definition."""
    if src is None:
        return None
    if owner:
        hit = next((d for d in src.definitions if d.qualname == f"{owner}.{name}"), None)
        if hit is not None:
            return hit
    return next((d for d in src.definitions if d.qualname == name), None) or \
        next((d for d in src.definitions if d.name == name), None)


def _parent(src: SourceFile, d: Definition) -> Definition | None:
    owner = d.qualname.rpartition(".")[0]
    return next((p for p in src.definitions if p.qualname == owner), None) if owner else None


def _call_name(sym: ChangedSymbol) -> str:
    """The word callers write: constructors are called by their class name."""
    d = sym.definition
    if d.name in ("__init__", "constructor"):
        return d.qualname.split(".")[-2] if "." in d.qualname else d.name
    return d.name


def _names(src: SourceFile, d: Definition) -> set[str]:
    return {r.name for r in src.references(d.header_end, d.end)} - {d.name}


def _words(src: SourceFile) -> set[str]:
    return set(WORD_RE.findall("\n".join(src.lines)))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _overlaps(a: Definition, b: Definition) -> bool:
    return a.start <= b.end and b.start <= a.end


def _runs(lines: set[int]) -> list[tuple[int, int]]:
    """Contiguous runs of line numbers: {3, 4, 5, 9} -> [(3, 5), (9, 9)]."""
    runs: list[tuple[int, int]] = []
    for n in sorted(lines):
        if runs and n == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    return runs


def _module_word(path: str) -> str:
    """The word other files use to import `path`: its stem, or the directory name of an index/__init__ file."""
    stem = posixpath.splitext(posixpath.basename(path))[0]
    return posixpath.basename(posixpath.dirname(path)) if stem in ("index", "__init__") else stem


def _name_tokens(path: str) -> list[str]:
    stem = posixpath.splitext(posixpath.basename(path))[0]
    return [t.lower() for t in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", stem)]


def _same_pattern(a: str, b: str) -> bool:
    """`*Service.java`, `*_repository.py`, `use*.ts`: the first or last name token matches."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if len(ta) < 2 or len(tb) < 2 or posixpath.splitext(a)[1] != posixpath.splitext(b)[1]:
        return False
    return ta[0] == tb[0] or ta[-1] == tb[-1]


def _best(snippets: list[Snippet], kind: str, limit: int) -> list[Snippet]:
    return sorted((s for s in snippets if s.kind == kind), key=lambda s: -s.score)[:limit]
