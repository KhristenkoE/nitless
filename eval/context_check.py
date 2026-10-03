"""Deterministic context-recall eval: does the packed context contain what a reviewer needs? No LLM calls.

    uv run python -m eval.context_check                      # every repo
    uv run python -m eval.context_check ts-bookings --case 'ts-room-*' -v
    uv run python -m eval.context_check --budget 2000        # does ranking keep what matters?

For each case with a `context:` list, builds the case's context exactly as the pipeline does (file selection
and triage, profile, related code, and for a split review each unit's related code) and checks every required
location: a file must appear in a profile item or a related-code block, and a line range must overlap the lines
that block shows. The baseline column is what the reviewer saw before related code existed: the profile plus
the diff hunks (±3 lines of context).
"""

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from eval.cases import CaseSpec, build_repo, list_repos, load_repo_spec, selected
from nitless.config import Settings
from nitless.context import Profile, RelatedContext
from nitless.diff import FileDiff
from nitless.models import ChangeRequest
from nitless.pipeline import build_context, plan_units, select_files

SOURCE_RE = re.compile(r"^(?P<path>.+?):(?P<ranges>\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)$")


@dataclass
class Check:
    required: str
    baseline: str | None  # where the reviewer saw it before related code: "diff" / "profile"
    found: str | None  # where it is now: "diff" / "profile" / "related:<kind>"


@dataclass
class CaseResult:
    case_id: str
    checks: list[Check]
    profile_tokens: int
    related_tokens: int
    dropped: int
    seconds: float
    related: RelatedContext
    units: int = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repos", nargs="*", help="eval repos (default: all)")
    parser.add_argument("--case", default="*", help="glob over case ids")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every selected block per case")
    parser.add_argument("--budget", type=int, help="related-code token budget (default: RELATED_BUDGET_TOKENS)")
    parser.add_argument("--unit-budget", type=int, help="diff tokens per review unit (default: UNIT_BUDGET_TOKENS)")
    parser.add_argument("--max-units", type=int, help="review units per MR (default: MAX_UNITS; 1 = one call)")
    args = parser.parse_args()

    settings = Settings.model_construct()  # defaults only; no target or API key needed
    if args.budget is not None:
        settings.related_budget_tokens = args.budget
    if args.unit_budget:
        settings.unit_budget_tokens = args.unit_budget
    if args.max_units:
        settings.max_units = args.max_units
    results = []
    for repo in args.repos or list_repos():
        path = build_repo(repo)
        for case in load_repo_spec(repo).cases:
            if case.context and selected(case, [args.case]):
                subprocess.run(["git", "checkout", "-q", f"case/{case.id}"], cwd=path, check=True)
                results.append(check_case(case, path, settings))
                report(results[-1], args.verbose)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=path, check=True)
    summarize(results)
    return 0


def check_case(case: CaseSpec, repo: Path, settings: Settings) -> CaseResult:
    change = ChangeRequest(provider="local", repo=str(repo), ref="HEAD", title=case.title, base_sha="main",
                           start_sha="main", head_sha="HEAD")
    started = time.monotonic()
    sel = select_files(repo, change, settings, None)
    files = sel.files
    profile, related = build_context(repo, files, "main", settings, sel.index)
    parts = plan_units(repo, sel, related, "main", settings)
    seconds = time.monotonic() - started
    shown = RelatedContext([item for u in parts for item in u.related.included],
                           [item for u in parts for item in u.related.dropped])
    checks = []
    for entry in case.context:
        alternatives = entry if isinstance(entry, list) else [entry]
        refs = [(ref, None) if isinstance(ref, str) else (ref.file, ref.lines) for ref in alternatives]
        label = " | ".join(file if lines is None else f"{file}:{lines[0]}-{lines[1]}" for file, lines in refs)
        baseline = next((w for f, lines in refs if (w := _in_diff(files, f, lines) or _in_profile(profile, f))), None)
        found = baseline or next((w for file, lines in refs if (w := _in_related(shown, file, lines))), None)
        checks.append(Check(label, baseline, found))
    return CaseResult(case.id, checks, profile.tokens, shown.tokens, len(shown.dropped), seconds, shown, len(parts))


def _in_diff(files: list[FileDiff], file: str, lines: tuple[int, int] | None) -> str | None:
    diff = next((f for f in files if f.path == file), None)
    if diff is None:
        return None
    if lines is None or diff.status == "added":
        return "diff"
    return "diff" if any(_overlap(lines, r) for r in diff.new_line_ranges()) else None


def _in_profile(profile: Profile, file: str) -> str | None:
    return "profile" if any(item.source.split("#")[0] == file for item in profile.included) else None


def _in_related(related: RelatedContext, file: str, lines: tuple[int, int] | None) -> str | None:
    for item in related.included:
        m = SOURCE_RE.match(item.source)
        if not m or m["path"] != file:
            continue
        shown = [tuple(int(n) for n in (part.split("-") * 2)[:2]) for part in m["ranges"].split(",")]
        if lines is None or any(_overlap(lines, r) for r in shown):
            return f"related:{item.kind}"
    return None


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def report(result: CaseResult, verbose: bool) -> None:
    hits = sum(c.found is not None for c in result.checks)
    units = f", {result.units} review units" if result.units > 1 else ""
    print(f"{result.case_id}: {hits}/{len(result.checks)}  profile {result.profile_tokens} + related "
          f"{result.related_tokens} tokens ({result.dropped} dropped{units}), {result.seconds:.2f}s")
    for c in result.checks:
        status = c.found or "MISS"
        print(f"    {'ok ' if c.found else '-- '} {c.required}  [{status}{'' if c.baseline else ', new'}]")
    missed = any(c.found is None for c in result.checks)
    if verbose or missed:
        print("    selected:")
        for item in result.related.included:
            print(f"      {item.kind:<9} {item.score:>5}  {item.source}  ({item.tokens} tok)")
    if verbose:
        for note in result.related.notes:
            print(f"    note: {note}")


def summarize(results: list[CaseResult]) -> None:
    if not results:
        print("no cases with a `context:` list matched")
        return
    checks = [c for r in results for c in r.checks]
    before = sum(c.baseline is not None for c in checks)
    after = sum(c.found is not None for c in checks)
    n = len(results)
    print()
    print(f"cases: {n}, required locations: {len(checks)}")
    print(f"context recall: {after}/{len(checks)} = {after / len(checks):.0%} "
          f"(profile + diff only: {before}/{len(checks)} = {before / len(checks):.0%})")
    print(f"cases fully covered: {sum(all(c.found for c in r.checks) for r in results)}/{n}")
    print(f"avg tokens: profile {sum(r.profile_tokens for r in results) / n:.0f}, "
          f"related {sum(r.related_tokens for r in results) / n:.0f} (max {max(r.related_tokens for r in results)})")
    print(f"time: avg {sum(r.seconds for r in results) / n:.2f}s, max {max(r.seconds for r in results):.2f}s")


if __name__ == "__main__":
    sys.exit(main())
