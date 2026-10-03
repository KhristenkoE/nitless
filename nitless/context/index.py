"""Lazy, per-run view of the repository: parsed files, `git grep` and import resolution.

Nothing is indexed up front. Files are parsed when a finder asks for them, definitions are
located by grepping for a name first, so the cost follows the size of the change, not the repo.
"""

import logging
import posixpath
import re
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from nitless.context.base import MAX_FILE_BYTES, read_text
from nitless.context.repo_map import TEST_DIRS, TEST_FILE_RE
from nitless.context.symbols import WORD_RE, Import, SourceFile, language_of, parse

log = logging.getLogger(__name__)

MAX_HITS_PER_WORD = 100
MAX_HITS_PER_FILE = 5  # per word
MAX_LINES_PER_FILE = 50  # per search, across all words
GREP_TIMEOUT_S = 20
# One PCRE alternation is far faster than many `-F -w -e` patterns (1s vs 55s for 300 names on 2k files).
WORD_BOUNDED = r"(?<![\w$])(?:{})(?![\w$])"
JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs", ".cts", ".cjs")
JS_ALIASES = ("@/", "~/", "#/")
PY_STDLIB = frozenset(sys.stdlib_module_names)

Hit = tuple[str, int, str]  # path, line, text


class RepoIndex:
    def __init__(self, repo: Path, files: list[str], base_sha: str):
        self.repo = repo
        self.base_sha = base_sha
        self.files = set(files)
        self._by_basename: dict[str, list[str]] = defaultdict(list)
        self._by_dir: dict[str, list[str]] = defaultdict(list)
        for path in sorted(files):
            self._by_basename[posixpath.basename(path)].append(path)
            self._by_dir[posixpath.dirname(path)].append(path)
        self._sources: dict[str, SourceFile | None] = {}
        self._resolved: dict[tuple[str, Import], str | None] = {}
        self._grepped: dict[tuple[str, tuple[str, ...]], list[Hit]] = {}

    # --- files ------------------------------------------------------------------------------

    def source(self, path: str) -> SourceFile | None:
        """The head-side file, parsed; None when missing, binary or larger than MAX_FILE_BYTES."""
        if path not in self._sources:
            text = read_text(self.repo, path)
            self._sources[path] = parse(path, text) if text is not None else None
        return self._sources[path]

    def base_sources(self, paths: list[str]) -> dict[str, SourceFile]:
        """The base-side versions of `paths`, parsed; read with one `git cat-file --batch`, not a `git show` each."""
        request = "".join(f"{self.base_sha}:{path}\n" for path in paths)
        try:
            proc = subprocess.run(["git", "cat-file", "--batch"], cwd=self.repo, input=request.encode(),
                                  capture_output=True, timeout=GREP_TIMEOUT_S, check=True)
        except (OSError, subprocess.SubprocessError) as e:
            log.debug("cannot read base versions: %s", e)
            return {}
        out, data, pos = {}, proc.stdout, 0
        for path in paths:  # each answer: "<sha> blob <size>\n<content>\n", or "<name> missing\n"
            eol = data.find(b"\n", pos)
            if eol < 0:
                break
            header, pos = data[pos:eol].rsplit(b" ", 2), eol + 1
            if len(header) != 3 or not header[2].isdigit():
                continue
            size = int(header[2])
            blob, pos = data[pos:pos + size], pos + size + 1
            if header[1] == b"blob" and size <= MAX_FILE_BYTES and b"\0" not in blob[:8000]:
                out[path] = parse(path, blob.decode(errors="replace"))
        return out

    def same_dir(self, path: str) -> list[str]:
        ext = posixpath.splitext(path)[1]
        siblings = self._by_dir.get(posixpath.dirname(path), [])
        return [p for p in siblings if p != path and posixpath.splitext(p)[1] == ext]

    def ancestors_named(self, path: str, basename: str) -> list[str]:
        """Files called `basename` in the directories above `path`, nearest first (e.g. conftest.py)."""
        found, folder = [], posixpath.dirname(path)
        while True:
            candidate = posixpath.join(folder, basename) if folder else basename
            if candidate in self.files:
                found.append(candidate)
            if not folder:
                return found
            folder = posixpath.dirname(folder)

    # --- search -----------------------------------------------------------------------------

    def grep(self, words: Iterable[str], pathspecs: tuple[str, ...] = ()) -> dict[str, list[Hit]]:
        """Whole-word hits of each word in tracked files, at most MAX_HITS_PER_WORD each.

        Cached per word, so a finder can search for every changed file's names in one `git grep`
        and look them up per file afterwards. Never raises: a failed search finds nothing.
        """
        words = set(words)
        missing = sorted(w for w in words if (w, pathspecs) not in self._grepped)
        if missing:
            found: dict[str, list[Hit]] = defaultdict(list)
            per_file: Counter[tuple[str, str]] = Counter()
            wanted = set(missing)
            for hit in self._search(missing, pathspecs):
                for word in wanted.intersection(WORD_RE.findall(hit[2])):
                    per_file[word, hit[0]] += 1
                    if len(found[word]) < MAX_HITS_PER_WORD and per_file[word, hit[0]] <= MAX_HITS_PER_FILE:
                        found[word].append(hit)
            for word in missing:
                self._grepped[word, pathspecs] = found.get(word, [])
        return {w: self._grepped[w, pathspecs] for w in words}

    def _search(self, words: list[str], pathspecs: tuple[str, ...]) -> list[Hit]:
        proc = self._git_grep(["-P", "-e", WORD_BOUNDED.format("|".join(map(re.escape, words)))], pathspecs)
        if proc is not None and proc.returncode == 128:  # git built without PCRE: slower, same matches
            proc = self._git_grep(["-w", "-F", *(arg for word in words for arg in ("-e", word))], pathspecs)
        return self._hits(proc) or []

    def search(self, pattern: str, pathspecs: tuple[str, ...] = ()) -> list[Hit] | None:
        """Lines of tracked files matching an extended regex (at most MAX_LINES_PER_FILE per file); None on error."""
        return self._hits(self._git_grep(["-E", "-e", pattern], pathspecs))

    def _hits(self, proc: subprocess.CompletedProcess | None) -> list[Hit] | None:
        if proc is None or proc.returncode not in (0, 1):
            log.debug("git grep failed: %s", proc.stderr.strip() if proc else "timeout")
            return None
        hits = []
        for row in proc.stdout.splitlines():
            path, _, rest = row.partition("\0")
            line, _, text = rest.partition("\0")
            if path in self.files and line.isdigit():
                hits.append((path, int(line), text))
        return hits

    def _git_grep(self, patterns: list[str], pathspecs: tuple[str, ...]) -> subprocess.CompletedProcess | None:
        args = ["git", "grep", "-n", "-z", "-I", "--no-color", f"--max-count={MAX_LINES_PER_FILE}", *patterns]
        try:
            return subprocess.run([*args, "--", *pathspecs], cwd=self.repo, capture_output=True, text=True,
                                  errors="replace", timeout=GREP_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.debug("git grep failed: %s", e)
            return None

    # --- imports ----------------------------------------------------------------------------

    def imports(self, path: str) -> list[tuple[Import, str | None]]:
        """Each import of `path` with the repo file it resolves to (None for external packages)."""
        source = self.source(path)
        if source is None:
            return []
        return [(imp, self.resolve(path, imp)) for imp in source.imports]

    def resolve(self, importer: str, imp: Import) -> str | None:
        key = (importer, imp)
        if key not in self._resolved:
            language = language_of(importer)
            if language == "python":
                target = self._resolve_python(importer, imp)
            elif language == "java":
                target = self._resolve_java(importer, imp)
            else:
                target = self._resolve_js(importer, imp) if language else None
            self._resolved[key] = target
        return self._resolved[key]

    def external_package(self, importer: str, imp: Import) -> str | None:
        """The third-party package an unresolved import comes from ("fastapi", "@tanstack/react-query")."""
        if self.resolve(importer, imp) is not None:
            return None
        language, module = language_of(importer), imp.module
        if language == "python":
            top = module.split(".")[0]
            return top if top and not module.startswith(".") and top not in PY_STDLIB else None
        if language == "java":
            parts = module.split(".")
            return ".".join(parts[:3]) if parts[0] not in ("java", "javax") and len(parts) > 2 else None
        if not module or module.startswith((".", "/", "node:", *JS_ALIASES)):
            return None
        parts = module.split("/")
        return "/".join(parts[:2]) if module.startswith("@") else parts[0]

    def _find(self, candidates: list[str], near: str) -> str | None:
        """First candidate present in the repo; exact path first, then as a path suffix (src/ layouts)."""
        for candidate in candidates:
            if candidate in self.files:
                return candidate
        for candidate in candidates:
            matches = [p for p in self._by_basename.get(posixpath.basename(candidate), [])
                       if p.endswith("/" + candidate)]
            if matches:
                return min(matches, key=lambda p: (hops(p, near), len(p)))
        return None

    def _resolve_python(self, importer: str, imp: Import) -> str | None:
        module = imp.module
        if module.startswith("."):
            dots = len(module) - len(module.lstrip("."))
            folder = posixpath.dirname(importer)
            for _ in range(dots - 1):
                folder = posixpath.dirname(folder)
            rest = module.lstrip(".").replace(".", "/")
            stem = posixpath.join(folder, rest) if rest else folder
            exact_only = True
        else:
            stem, exact_only = module.replace(".", "/"), False
        candidates = []
        if imp.name and imp.name != "*":
            candidates += [f"{stem}/{imp.name}.py", f"{stem}/{imp.name}/__init__.py"]
        candidates += [f"{stem}.py", f"{stem}/__init__.py"]
        if exact_only:
            return next((c for c in candidates if c in self.files), None)
        return self._find(candidates, importer)

    def _resolve_js(self, importer: str, imp: Import) -> str | None:
        spec = imp.module
        if spec.startswith("."):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
        elif spec.startswith(JS_ALIASES):
            base = spec[2:]
        else:
            return None
        stem, ext = posixpath.splitext(base)
        if ext not in JS_EXTS:
            stem = base
        candidates = [base] + [stem + e for e in JS_EXTS] + [f"{stem}/index{e}" for e in JS_EXTS]
        if spec.startswith("."):
            return next((c for c in candidates if c in self.files), None)
        return self._find(candidates, importer)

    def _resolve_java(self, importer: str, imp: Import) -> str | None:
        if imp.name == "*":
            return None
        return self._find([imp.module.replace(".", "/") + ".java"], importer)


def is_test_file(path: str) -> bool:
    parts = path.lower().split("/")
    return bool(TEST_FILE_RE.search(posixpath.basename(path))) or any(p in TEST_DIRS for p in parts[:-1])


def is_test_support(path: str) -> bool:
    """Shared test code that is not itself a test: conftest.py, fixtures, test base classes, setup files."""
    name = posixpath.basename(path)
    return name == "conftest.py" or (is_test_file(path) and not TEST_FILE_RE.search(name))


def hops(a: str, b: str) -> int:
    """Directory hops between two files (0 = same directory)."""
    da, db = a.split("/")[:-1], b.split("/")[:-1]
    common = 0
    for x, y in zip(da, db, strict=False):
        if x != y:
            break
        common += 1
    return len(da) + len(db) - 2 * common

