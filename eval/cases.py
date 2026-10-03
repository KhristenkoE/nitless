"""Eval case definitions and the builder that turns them into real git repositories.

Layout of one eval repo (committed in this project):

    eval/repos/<repo>/base/...                 full project at the target-branch state
    eval/repos/<repo>/cases/<case_id>/...      files that the MR adds or replaces (overlay)
    eval/repos/<repo>/cases.yaml               case metadata, see CaseSpec

`build_repo` creates .cache/eval/repos/<repo> with `main` = base and one branch
`case/<case_id>` per case = base + overlay - deletions, committed with the
case's MR title/description as the commit message.

A composed case (`compose: [case_id, ...]`) is one large MR: the overlays of its component cases
applied together, plus its own overlay as filler (behaviour-preserving changes that must stay silent).
Its expected, forbidden and context entries are the union of the components', its noise budget their sum,
and its description is its own followed by the components' titles and descriptions.
"""

import fnmatch
import json
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

EVAL_DIR = Path(__file__).parent
REPOS_DIR = EVAL_DIR / "repos"
BUILD_DIR = EVAL_DIR.parent / ".cache" / "eval"

CaseKind = Literal[
    "related-code-bug",  # bug only visible after reading callers/callees/siblings
    "code-convention",  # violates a convention that exists only in code, not in docs
    "doc-convention",  # violates a rule written in README/CONTRIBUTING/AGENTS.md/lint config
    "missing-ac",  # does not implement an acceptance criterion of the task
    "diff-bug",  # bug visible in the diff itself (sanity check)
    "correct-here",  # trap: looks wrong in isolation but is correct in this project
    "out-of-scope",  # trap: omits something the task marks out of scope
    "clean",  # trap: good change, expect silence
    "nit-bait",  # trap: small change with only stylistic imperfections
    "composed",  # several cases in one large MR, plus silent filler (see `compose`)
]
SILENT_KINDS = {"correct-here", "out-of-scope", "clean", "nit-bait"}


class Anchor(BaseModel):
    file: str
    lines: tuple[int, int] = Field(description="inclusive new-file line range the issue lives in")
    what: str = Field(description="the issue in one sentence, used by the LLM judge to match findings")


class Location(BaseModel):
    file: str
    lines: tuple[int, int]


ContextRef = Location | str  # a file, or a file with a head-side line range


class Expected(Anchor):
    also_at: list[Location] = Field(default_factory=list, description="other places the same issue may be flagged")
    categories: list[str] = Field(default_factory=list, description="acceptable categories; empty = any")
    min_severity: Literal["minor", "major", "critical"] = "minor"


class Task(BaseModel):
    id: str | None = None
    title: str
    intent: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class CaseSpec(BaseModel):
    id: str
    kind: CaseKind
    notes: str = Field(description="for humans: what is planted and why it is hard")
    title: str
    description: str = ""
    compose: list[str] = Field(default_factory=list, description="component case ids (kind: composed)")
    delete: list[str] = Field(default_factory=list)
    task: Task | None = None
    task_in_repo: bool = Field(default=False, description="commit the task as story.json instead of passing it")
    expected: list[Expected] = Field(default_factory=list)
    forbidden: list[Anchor] = Field(default_factory=list, description="regions that must NOT be flagged")
    max_findings: int | None = Field(default=None, description="max findings allowed (default: len(expected))")
    context: list[ContextRef | list[ContextRef]] = Field(
        default_factory=list, description="code a reviewer must see to judge the case; a nested list means any one "
        "of these (scored by eval.context_check, no LLM)")

    @model_validator(mode="after")
    def _consistent(self) -> "CaseSpec":
        if (self.kind == "composed") != bool(self.compose):
            raise ValueError(f"{self.id}: `compose` is required for, and only allowed in, composed cases")
        if self.compose:
            if self.expected or self.forbidden or self.context or self.task or self.max_findings is not None:
                raise ValueError(f"{self.id}: a composed case takes expected/forbidden/context from its components")
            return self
        if self.kind in SILENT_KINDS and self.expected:
            raise ValueError(f"{self.id}: {self.kind} cases must not have expected findings")
        if self.kind not in SILENT_KINDS and not self.expected:
            raise ValueError(f"{self.id}: {self.kind} cases need at least one expected finding")
        if self.kind in ("missing-ac", "out-of-scope") and not self.task:
            raise ValueError(f"{self.id}: {self.kind} cases need a task")
        return self

    @property
    def silent(self) -> bool:
        return self.kind in SILENT_KINDS

    def context_refs(self) -> list[ContextRef]:
        return [ref for entry in self.context for ref in (entry if isinstance(entry, list) else [entry])]

    @property
    def noise_budget(self) -> int:
        return self.max_findings if self.max_findings is not None else len(self.expected)


class RepoSpec(BaseModel):
    language: str
    description: str = ""
    cases: list[CaseSpec]

    @model_validator(mode="after")
    def _compose(self) -> "RepoSpec":
        by_id = {c.id: c for c in self.cases}
        for case in self.cases:
            if not case.compose:
                continue
            parts = [by_id.get(i) for i in case.compose]
            if missing := [i for i, p in zip(case.compose, parts, strict=True) if p is None or p.compose]:
                raise ValueError(f"{case.id}: unknown or composed components {missing}")
            case.expected = [e for p in parts for e in p.expected]
            case.forbidden = [a for p in parts for a in p.forbidden]
            case.context = [ref for p in parts for ref in p.context]
            case.max_findings = sum(p.noise_budget for p in parts)
            sections = [f"## {p.title}" + (f"\n\n{p.description.strip()}" if p.description.strip() else "")
                        for p in parts]
            case.description = "\n\n".join([case.description.strip(), *sections]).strip()
            case.delete = [*dict.fromkeys([*(d for p in parts for d in p.delete), *case.delete])]
        return self

    def components(self, case: CaseSpec) -> list[CaseSpec]:
        return [c for i in case.compose for c in self.cases if c.id == i]


def load_repo_spec(repo: str) -> RepoSpec:
    return RepoSpec.model_validate(yaml.safe_load((REPOS_DIR / repo / "cases.yaml").read_text()))


def selected(case: CaseSpec, patterns: list[str]) -> bool:
    """Glob match over case ids; the catch-all `*` leaves out composed (large, costly) cases: name them."""
    return any(fnmatch.fnmatch(case.id, p) and not (case.compose and p == "*") for p in patterns)


def list_repos() -> list[str]:
    return sorted(p.name for p in REPOS_DIR.iterdir() if (p / "cases.yaml").exists())


def _git(cwd: Path, *args: str) -> str:
    env_args = ["-c", "user.name=eval", "-c", "user.email=eval@example.com", "-c", "commit.gpgsign=false"]
    return subprocess.run(["git", *env_args, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def task_file(repo: str, case: CaseSpec) -> Path | None:
    if not case.task or case.task_in_repo:
        return None
    return BUILD_DIR / "tasks" / repo / f"{case.id}.json"


def build_repo(repo: str) -> Path:
    """(Re)build the git repository for one eval repo and return its path."""
    spec = load_repo_spec(repo)
    src = REPOS_DIR / repo
    dest = BUILD_DIR / "repos" / repo
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src / "base", dest)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "Initial import")

    for case in spec.cases:
        _git(dest, "checkout", "-q", "-B", f"case/{case.id}", "main")
        overlays = [src / "cases" / c.id for c in [*spec.components(case), case]]
        _check_disjoint(case.id, overlays)
        for overlay in overlays:
            if overlay.exists():
                shutil.copytree(overlay, dest, dirs_exist_ok=True)
        for rel in case.delete:
            (dest / rel).unlink()
        if case.task and case.task_in_repo:
            (dest / "story.json").write_text(case.task.model_dump_json(indent=2) + "\n")
        elif path := task_file(repo, case):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(case.task.model_dump_json(indent=2) + "\n")
        _git(dest, "add", "-A")
        message = case.title + ("\n\n" + case.description.strip() if case.description.strip() else "")
        _git(dest, "commit", "-q", "--allow-empty", "-m", message)
    _git(dest, "checkout", "-q", "main")
    return dest


def _check_disjoint(case_id: str, overlays: list[Path]) -> None:
    """Overlays replace whole files, so the parts of a composed case must not touch the same file."""
    owner: dict[str, str] = {}
    for overlay in overlays:
        for path in overlay.rglob("*") if overlay.exists() else []:
            rel = str(path.relative_to(overlay))
            if path.is_file() and owner.setdefault(rel, overlay.name) != overlay.name:
                raise ValueError(f"{case_id}: {rel} is changed by both {owner[rel]} and {overlay.name}")


def validate_repo(repo: str) -> list[str]:
    """Build the repo and check every anchor points at lines inside the case's diff. Returns problems."""
    from nitless.diff import compute_diff

    spec = load_repo_spec(repo)
    path = build_repo(repo)
    problems = []
    seen = set()
    for case in spec.cases:
        if case.id in seen:
            problems.append(f"{case.id}: duplicate case id")
        seen.add(case.id)
        files = {f.path: f for f in compute_diff(path, "main", f"case/{case.id}")}
        if not files:
            problems.append(f"{case.id}: branch has no changes")
        extra = [loc for e in case.expected for loc in e.also_at]
        for anchor in [*case.expected, *case.forbidden, *extra]:
            diff = files.get(anchor.file)
            if diff is None:
                problems.append(f"{case.id}: {anchor.file} is not changed by this case")
                continue
            start, end = anchor.lines
            if start > end or not any(diff.covers_line(n) for n in range(start, end + 1)):
                problems.append(f"{case.id}: {anchor.file}:{start}-{end} is outside the changed hunks "
                                f"{diff.new_line_ranges()}")
        for loc in case.context_refs():
            file, lines = (loc, None) if isinstance(loc, str) else (loc.file, loc.lines)
            try:
                length = len(_git(path, "show", f"case/{case.id}:{file}").splitlines())
            except subprocess.CalledProcessError:
                problems.append(f"{case.id}: context file {file} does not exist")
                continue
            if lines and not 1 <= lines[0] <= lines[1] <= length:
                problems.append(f"{case.id}: context {file}:{lines[0]}-{lines[1]} is outside the file ({length} lines)")
    return problems


if __name__ == "__main__":
    import sys

    total = 0
    for name in sys.argv[1:] or list_repos():
        issues = validate_repo(name)
        total += len(issues)
        cases = load_repo_spec(name).cases
        print(f"{name}: {len(cases)} cases, {'OK' if not issues else f'{len(issues)} problems'}")
        for issue in issues:
            print(f"  - {issue}")
    print(json.dumps({"problems": total}))
    sys.exit(1 if total else 0)
