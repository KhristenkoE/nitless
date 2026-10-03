"""A compact, bounded map of the repository: languages, layout, tests.

The tree is collapsed to per-directory file counts everywhere except along the
paths of changed files, where sibling files are listed: that is where the local
conventions a reviewer should compare against live.
"""

import posixpath
import re
from collections import Counter, defaultdict
from pathlib import Path

import pathspec

from nitless.context.base import ContextItem
from nitless.git import run_git

LANGUAGES = {
    ".py": "Python", ".pyi": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy", ".go": "Go",
    ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".c": "C", ".h": "C/C++", ".cpp": "C++",
    ".cc": "C++", ".hpp": "C++", ".swift": "Swift", ".m": "Objective-C", ".dart": "Dart", ".vue": "Vue",
    ".svelte": "Svelte", ".sql": "SQL", ".sh": "Shell", ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".less": "Less", ".md": "Markdown", ".rst": "reStructuredText", ".json": "JSON", ".yaml": "YAML",
    ".yml": "YAML", ".toml": "TOML", ".xml": "XML", ".tf": "Terraform", ".proto": "Protobuf",
    ".graphql": "GraphQL", ".gql": "GraphQL",
}
TOP_LANGUAGES = 8
MAX_DIR_ENTRIES = 30  # per directory holding changed files (and the root)
MAX_PASSING_ENTRIES = 8  # per directory the changed paths only pass through
MAX_TREE_LINES = 160  # whole tree, keeps the map around 1.5k tokens on any repo

TEST_FILE_RE = re.compile(
    r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$|(Test|Tests|IT)\.(java|kt)$|_spec\.rb$|_test\.go$)"
)
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "it", "e2e", "testing", "androidtest", "sharedtest",
             "testfixtures", "integrationtest", "integration-tests"}
CODE_EXTS = {".py", ".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs", ".cjs", ".java", ".kt", ".go", ".rb", ".cs", ".scala",
             ".vue", ".svelte"}


def list_files(repo: Path, excludes: list[str]) -> list[str]:
    """Tracked files, minus the review's gitignore-style excludes."""
    out = run_git(["-c", "core.quotePath=false", "ls-files", "-z"], cwd=repo)
    spec = pathspec.PathSpec.from_lines("gitignore", excludes)
    return [p for p in out.split("\0") if p and not spec.match_file(p)]


def build_repo_map(files: list[str], changed: list[str]) -> ContextItem:
    lines = [f"{len(files)} tracked files. Languages: {_languages(files)}", ""]
    tests = _test_layout(files)
    if tests:
        lines += [tests, ""]
    lines.append("Layout (dirs collapsed to file counts; expanded along changed files, marked *):")
    lines += _tree(sorted(set(files) | set(changed)), changed)  # changed files may be new
    reason = "repository layout, languages and test layout; expanded along the changed files' directories"
    return ContextItem("repo_map", "repository map", reason, "\n".join(lines), priority=0)


def _languages(files: list[str]) -> str:
    counts = Counter(LANGUAGES.get(posixpath.splitext(p)[1].lower()) for p in files)
    counts.pop(None, None)
    top = counts.most_common(TOP_LANGUAGES)
    return ", ".join(f"{lang} {n}" for lang, n in top) or "none recognised"


def _test_layout(files: list[str]) -> str:
    """Where tests live and how they are named: `tests/ (10: api/ 5, services/ 4)`, `*.test.ts (4)`."""
    roots: Counter[str] = Counter()
    subdirs: defaultdict[str, Counter[str]] = defaultdict(Counter)
    colocated: Counter[str] = Counter()
    naming: Counter[str] = Counter()
    for p in files:
        *parts, name = p.split("/")
        m = TEST_FILE_RE.search(name)
        idx = next((i for i, part in enumerate(parts) if part.lower() in TEST_DIRS), None)
        if (m is None and idx is None) or posixpath.splitext(name)[1] not in CODE_EXTS:
            continue
        if m:
            naming["test_*.py" if m[0].startswith("test_") else "*" + m[0]] += 1
        if idx is None:
            colocated["/".join(parts) or "."] += 1
            continue
        root = "/".join(parts[: idx + 1])
        roots[root] += 1
        if idx + 1 < len(parts):
            subdirs[root][parts[idx + 1]] += 1
    if not roots and not colocated:
        return "Tests: none found."
    found = []
    for root, n in roots.most_common(4):
        subs = subdirs[root]
        detail = ": " + ", ".join(f"{d}/ {k}" for d, k in subs.most_common(4)) if len(subs) > 1 else ""
        found.append(f"{root}/ ({n}{detail})")
    where = []
    if roots:
        where.append("Test dirs: " + ", ".join(found) + (f" and {len(roots) - 4} more" if len(roots) > 4 else ""))
    if colocated:
        n, example = len(colocated), colocated.most_common(1)[0][0]
        where.append(f"Co-located with sources in {n} dir{'s' * (n != 1)} (e.g. {example}/)")
    names = ", ".join(f"{pat} ({n})" for pat, n in naming.most_common(4)) or "no file-name convention"
    total = sum(roots.values()) + sum(colocated.values())
    return f"Tests: {total} file{'s' * (total != 1)}. {'. '.join(where)}. Naming: {names}."


def _tree(files: list[str], changed: list[str]) -> list[str]:
    children: defaultdict[str, set[str]] = defaultdict(set)  # dir -> child dirs
    dir_files: defaultdict[str, list[str]] = defaultdict(list)
    counts: Counter[str] = Counter()  # dir -> files below it
    for p in files:
        parts = p.split("/")
        for i in range(len(parts) - 1):
            parent, child = "/".join(parts[:i]), "/".join(parts[: i + 1])
            children[parent].add(child)
            counts[child] += 1
        dir_files["/".join(parts[:-1])].append(p)

    changed_set = set(changed)
    changed_dirs = {posixpath.dirname(p) for p in changed}
    expanded = {""}
    for p in changed:
        parts = p.split("/")
        expanded.update("/".join(parts[:i]) for i in range(1, len(parts)))

    lines: list[str] = []

    def walk(d: str, depth: int) -> None:
        entries = sorted(children[d]) + sorted(dir_files[d])
        pinned = [e for e in entries if e in expanded or e in changed_set]
        limit = MAX_DIR_ENTRIES if d in changed_dirs or not d else MAX_PASSING_ENTRIES
        if len(entries) > limit:
            others = [e for e in entries if e not in pinned]
            keep = set(pinned) | set(others[: max(limit - len(pinned), 0)])
            hidden = len(entries) - len(keep)
            entries = [e for e in entries if e in keep]
        else:
            hidden = 0
        indent = "  " * depth
        for e in entries:
            if len(lines) >= MAX_TREE_LINES:
                return
            if e in children[d]:
                start = e
                while len(children[e]) == 1 and not dir_files[e]:  # src/main/java/com/acme -> one line
                    e = next(iter(children[e]))
                n = counts[e]
                lines.append(f"{indent}{posixpath.relpath(e, d or '.')}/ ({n} file{'s' * (n != 1)})")
                if start in expanded:
                    walk(e, depth + 1)
            else:
                lines.append(f"{indent}{posixpath.basename(e)}{' *' if e in changed_set else ''}")
        if hidden:
            lines.append(f"{indent}… {hidden} more")

    walk("", 0)
    if len(lines) >= MAX_TREE_LINES:
        lines.append("… (tree truncated)")
    return lines
