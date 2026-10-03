"""End-to-end run: preflight → task → acquire → triage → context → review → validate → verify → publish.

    triage    classify every changed file and hunk (trivial / normal / risky), deterministically
    context   profile + related code (deterministic), then task intent ∥ conventions card (fast model)
    review    the review units (one for a change that fits UNIT_BUDGET_TOKENS, else groups of linked files
              without their trivial hunks), one strong-model reviewer per unit ∥ the requirements check
              (one call for the whole change, only for a task with criteria/intent); unit findings are
              merged and cross-unit duplicates dropped
    verify    an adversarial verdict on every candidate finding (verifier model, VERIFY=on), then the
              deterministic post-filter: confidence floor, one test-coverage finding, a per-MR cap

Any ReviewerError aborts the review and produces an `error` result with a specific exit code, except a
failed review unit when another unit succeeded: the result is then `partial`, with a warning.
Findings are never emitted after a failure.
"""

import logging
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from nitless import __version__
from nitless.config import Settings
from nitless.context import Profile, RelatedContext, build_profile, build_related
from nitless.context.conventions import ConventionsCard, build_conventions
from nitless.context.index import RepoIndex
from nitless.context.intent import Intent, TaskDocument, find_story_file, load_task_source, mr_document, parse_intent
from nitless.context.repo_map import list_files
from nitless.diff import FileDiff, compute_diff, filter_excluded
from nitless.errors import DiffTooLargeError, PublishError, QuotaExhaustedError, ReviewerError
from nitless.llm import LLMClient
from nitless.llm.pricing import cost_usd, parse_prices
from nitless.models import ChangeRequest, ErrorInfo, Finding, ReviewResult, RunMeta
from nitless.output import OutputAdapter
from nitless.review import naive, requirements, units, verifier
from nitless.review.postprocess import dedupe_units, finding_cap, select, summarize, validate
from nitless.review.requirements import RequirementsSubmission
from nitless.review.schema import CandidateFinding, ReviewSubmission
from nitless.review.tools import Toolbox
from nitless.review.triage import Triage, triage
from nitless.scm import make_provider

log = logging.getLogger(__name__)

LOW_PRIORITY_PARTS = ("test", "tests", "spec", "docs", "doc", "fixtures", "examples")
MAX_PARALLEL_CALLS = 4  # reviewer units + the requirements check in flight at once (provider rate limits)
MAX_TOOL_TOKENS = 20000  # tool results one reviewer call may read; the verifier gets a quarter


@dataclass
class Selection:
    """What gets reviewed, and what was left out and why."""

    task: TaskDocument
    files: list[FileDiff]  # without trivial hunks when the review is split
    index: RepoIndex
    triage: Triage
    split: bool  # too large for one reviewer call
    skipped: list[str] = field(default_factory=list)  # excluded paths (and a committed story file)
    oversize: list[str] = field(default_factory=list)  # over MAX_DIFF_LINES
    trivial: list[str] = field(default_factory=list)  # trivial files, left out of a split review


@dataclass
class Reviewed:
    """The reviewer units' merged outcome and the requirements check."""

    assessment: str
    candidates: list[CandidateFinding]
    parts: int
    checked: RequirementsSubmission | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # cross-unit duplicates dropped
    units: list[dict] = field(default_factory=list)  # per-unit trace rows


def run(settings: Settings, adapters: list[OutputAdapter]) -> int:
    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    models = {"strong": settings.model_strong, "fast": settings.model_fast}
    meta = RunMeta(tool_version=__version__, started_at=started_at,
                   models={**models, "verifier": settings.model_verifier} if settings.verify else models)
    llm = LLMClient(settings)
    change: ChangeRequest | None = None
    exit_code = 0

    try:
        with ExitStack() as stack:
            workdir = settings.workdir or Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="nitless-")))
            result, change = _review(settings, llm, meta, workdir)
    except ReviewerError as e:
        log.error("%s error: %s", e.kind, e)
        result = ReviewResult(status="error", run=meta, error=ErrorInfo(kind=e.kind, message=str(e)))
        exit_code = e.exit_code

    meta.duration_s = round(time.monotonic() - t0, 1)
    meta.usage = llm.usage
    meta.cost_usd = cost_usd(llm.usage, parse_prices(settings.model_prices))
    log.info("run: %s", telemetry(meta))
    return _publish(result, change, adapters) or exit_code


def telemetry(meta: RunMeta) -> str:
    """One line for the end of every run: time, calls, tokens per model, cost."""
    calls = sum(u.calls for u in meta.usage.values())
    prompt = sum(u.prompt_tokens for u in meta.usage.values())
    completion = sum(u.completion_tokens for u in meta.usage.values())
    by_model = ", ".join(f"{m} {u.prompt_tokens + u.completion_tokens:,}" for m, u in meta.usage.items())
    cost = f"${meta.cost_usd:.4f}" if meta.cost_usd is not None else "n/a (no price for a model; see MODEL_PRICES)"
    return (f"{meta.duration_s}s, {calls} LLM calls, {prompt:,} prompt + {completion:,} completion tokens"
            f"{f' ({by_model})' if by_model else ''}, cost {cost}")


def _review(settings: Settings, llm: LLMClient, meta: RunMeta, workdir: Path) -> tuple[ReviewResult, ChangeRequest]:
    llm.preflight(settings.models)
    explicit_task = None
    if settings.task_source:  # read before cloning: an unreadable task source fails the run (exit 5)
        explicit_task = load_task_source(settings.task_source, settings.gitlab_token, settings.mr_url)

    provider = make_provider(settings)
    change = provider.fetch_change()
    meta.repo, meta.mr = change.repo, change.ref
    meta.base_sha, meta.head_sha = change.base_sha, change.head_sha
    log.info("reviewing %s: %s (%s..%s)", change.ref, change.title, change.base_sha[:10], change.head_sha[:10])

    repo_dir = provider.checkout(change, workdir / "repo")
    sel = select_files(repo_dir, change, settings, explicit_task)
    status = "partial" if sel.oversize else "ok"
    warnings = [f"diff exceeds MAX_DIFF_LINES={settings.max_diff_lines}; skipped {len(sel.oversize)} files"] \
        if sel.oversize else []
    skipped = sel.skipped + sel.trivial + sel.oversize
    files = sel.files
    if not files:
        return ReviewResult(status=status, run=meta, summary=summarize("No reviewable changes.", []),
                            skipped_files=skipped, warnings=warnings,
                            context_trace={"triage": sel.triage.trace()}), change

    profile, related = build_context(repo_dir, files, change.base_sha, settings, sel.index)
    intent, card = understand(settings, llm, sel.task, files, profile, related)
    warnings += card.warnings if card else []
    review_units = plan_units(repo_dir, sel, related, change.base_sha, settings)
    tool_trace: list[dict] = []
    reviewed = review_and_check(settings, llm, change, files, profile, review_units, related, intent, card, sel,
                                tool_trace)
    if reviewed.warnings:
        status, warnings = "partial", [*warnings, *reviewed.warnings]

    candidates, notes, reqs = reviewed.candidates, list(reviewed.notes), None
    if reviewed.checked is not None:
        reqs = requirements.to_requirements(intent, reviewed.checked)
        unmet = requirements.to_findings(intent, reviewed.checked, files)
        candidates, merged = requirements.merge_findings(candidates, unmet, bool(intent.acceptance_criteria))
        notes += merged
    findings, dropped = validate(candidates, files, settings.severity_floor)
    for w in notes + dropped:
        log.warning(w)

    material = verifier.build_material(repo_dir, change, files, profile, related, intent,
                                       card.render() if card else "", sel.index)
    shown = {item.source for item in material.related}
    for unit in review_units:  # a split review: the verifier may use what any unit's reviewer saw
        material.related += [item for item in unit.related.included if item.source not in shown]
        shown |= {item.source for item in unit.related.included}
    verification = verify(settings, llm, findings, material, _toolboxes(
        settings, sel.index, tool_trace, max(1, settings.max_tool_calls // 2), MAX_TOOL_TOKENS // 4))
    reqs = requirements.dispute(reqs, verification.refuted_criteria()) if reqs else None
    assessment = verifier.restate(llm, settings.model_fast, reviewed.assessment, verification, reviewed.parts)

    return ReviewResult(
        status=status, run=meta, summary=summarize(assessment, verification.published, reqs), requirements=reqs,
        findings=verification.published, skipped_files=skipped,
        warnings=warnings + notes + dropped + verification.warnings,
        context_trace={"profile": profile.trace(), "intent": intent.trace(),
                       "conventions": card.trace() if card else {"enabled": False}, "related": related.trace(),
                       "triage": sel.triage.trace(), "units": reviewed.units,
                       "tools": {"enabled": settings.tools, "calls": tool_trace},
                       "verification": verification.trace(),
                       "llm_usage_by_step": {k: v.model_dump() for k, v in llm.usage_by_tool.items()}},
    ), change


def select_files(repo_dir: Path, change: ChangeRequest, settings: Settings, explicit_task: TaskDocument | None
                 ) -> Selection:
    """The task and the files to review: excludes, triage, trivial hunks (split reviews only), size budget."""
    all_files = compute_diff(repo_dir, change.base_sha, change.head_sha)
    story = find_story_file(repo_dir, [f.path for f in all_files if f.status != "deleted"])
    task = explicit_task or story or mr_document(change)
    files, skipped = filter_excluded([f for f in all_files if not story or f.path != story.path], settings.excludes)
    skipped += [story.path] if story else []  # a committed story file is the task, not code to review
    index = RepoIndex(repo_dir, list_files(repo_dir, settings.excludes), change.base_sha)
    triaged = triage(files, index)
    split = settings.max_units > 1 and units.diff_tokens(files) > settings.unit_budget_tokens
    trivial = []
    if split:
        reviewable = triaged.reviewable(files)
        trivial = [f.path for f in files if f.path not in {r.path for r in reviewable}]
        files = reviewable
    files, oversize = apply_size_budget(files, settings, triaged)
    log.info("%d files to review, %d excluded, %d trivial, %d skipped for size%s", len(files), len(skipped),
             len(trivial), len(oversize), " (split review)" if split else "")
    return Selection(task, files, index, triaged, split, skipped, oversize, trivial)


def plan_units(repo_dir: Path, sel: Selection, related: RelatedContext, base_sha: str,
               settings: Settings) -> list[units.Unit]:
    """One unit with the change's related code, or (split review) linked groups with their own related code."""
    if not sel.split:
        return [units.Unit(sel.files, related=related)]
    parts = units.split(sel.files, sel.index, settings.unit_budget_tokens, settings.max_units)
    for unit in parts:
        unit.related = related if len(parts) == 1 else build_related(
            repo_dir, unit.files, base_sha, settings.excludes, settings.related_budget_tokens, sel.index)
    log.info("split review: %d units (%s diff tokens)", len(parts), ", ".join(str(u.tokens) for u in parts))
    return parts


def understand(settings: Settings, llm: LLMClient, task: TaskDocument, files: list[FileDiff], profile: Profile,
               related: RelatedContext) -> tuple[Intent, ConventionsCard | None]:
    """Task intent and conventions card, concurrently (both fast model). Only an explicit task source may fail."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        card = pool.submit(build_conventions, llm, settings.model_fast, files, profile, related) \
            if settings.conventions else None
        intent = parse_intent(task, llm, settings.model_fast)
    log.info("task from %s (%s): %d acceptance criteria, %d out of scope", intent.source, intent.parsed_by,
             len(intent.acceptance_criteria), len(intent.out_of_scope))
    return intent, card.result() if card else None


def review_and_check(settings: Settings, llm: LLMClient, change: ChangeRequest, files: list[FileDiff],
                     profile: Profile, review_units: list[units.Unit], related: RelatedContext, intent: Intent,
                     card: ConventionsCard | None, sel: Selection, tool_trace: list[dict]) -> Reviewed:
    """Every unit's reviewer and the requirements check, concurrently. The check degrades to a warning, and so
    does a failed unit while another one succeeds; with every unit failed the review fails. A spent daily token
    quota always fails it: a partial review that reads as clean is worse than a loud exit 7."""
    profile_text, count = profile.render(), len(review_units)
    toolbox = _toolboxes(settings, sel.index, tool_trace, settings.max_tool_calls, MAX_TOOL_TOKENS)

    def review_unit(n: int, unit: units.Unit) -> ReviewSubmission:
        conventions = (card.render_for(unit.paths) if count > 1 else card.render()) if card else ""
        return naive.review(llm, settings.model_strong, change, unit.files, profile_text, unit.related.render(),
                            conventions, intent.render(),
                            units.scope_note(unit, n, count, files, sel.triage) if sel.split else "",
                            toolbox(f"unit {n}") if toolbox else None)

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
        check: Future | None = pool.submit(
            requirements.assess, llm, settings.model_strong, intent, change, files, profile_text, related.render(),
        ) if intent.assessable else None
        started = time.monotonic()
        reviews = [pool.submit(review_unit, n, unit) for n, unit in enumerate(review_units, 1)]

    submissions, rows, failures = [], [], []
    for n, (unit, future) in enumerate(zip(review_units, reviews, strict=True), 1):
        row = {"unit": n, "files": unit.paths, "diff_tokens": unit.tokens, "related_tokens": unit.related.tokens,
               "links": unit.links}
        try:
            submissions.append((n, future.result()))
            rows.append({**row, "status": "ok", "findings": len(submissions[-1][1].findings)})
        except QuotaExhaustedError:
            raise
        except ReviewerError as e:
            log.warning("review of unit %d failed: %s", n, e)
            failures.append((n, unit, e))
            rows.append({**row, "status": "failed", "error": str(e)})
    if not submissions:
        raise failures[0][2]
    log.info("reviewed %d units in %.1fs", count, time.monotonic() - started)
    candidates, notes = dedupe_units([s.findings for _, s in submissions])
    assessment = submissions[0][1].assessment if count == 1 else "\n".join(
        f"Part {n}: {s.assessment}" for n, s in submissions)
    warnings = [f"review of part {n} ({', '.join(u.paths[:5])}{', …' if len(u.paths) > 5 else ''}) failed: {e}"
                for n, u, e in failures]

    checked = None
    if check is not None:
        try:
            checked = check.result()
        except QuotaExhaustedError:
            raise
        except ReviewerError as e:
            log.warning("requirements check failed: %s", e)
            warnings.append(f"requirements check failed: {e}")
    return Reviewed(assessment, candidates, len(submissions), checked, warnings, notes, rows)


def _toolboxes(settings: Settings, index: RepoIndex, trace: list[dict], calls: int,
               tokens: int) -> Callable[[str], Toolbox] | None:
    """Makes a toolbox with this budget for each agent (TOOLS=on), all logging into `trace`; None with TOOLS=off."""
    if not settings.tools:
        return None
    lock = threading.Lock()
    return lambda owner: Toolbox(index, owner, calls, tokens, trace, lock)


def verify(settings: Settings, llm: LLMClient, findings: list[Finding], material: verifier.Material,
           tools: Callable[[str], Toolbox] | None = None) -> verifier.Verification:
    """Verifier verdicts (VERIFY=on), then the deterministic post-filter. Dropped findings stay in the trace."""
    started = time.monotonic()
    checks = verifier.verify(llm, settings.model_verifier, findings, material, tools) if settings.verify \
        else [verifier.Check(f) for f in findings]
    changed_lines = sum(f.added + f.removed for f in material.files.values())
    return post_filter(settings, checks, changed_lines, round(time.monotonic() - started, 1))


def post_filter(settings: Settings, checks: list[verifier.Check], changed_lines: int,
                duration_s: float = 0.0) -> verifier.Verification:
    """Apply verdicts, then the confidence floor, the test-coverage limit and the per-MR cap."""
    kept, dropped = verifier.apply(checks, settings.severity_floor)
    cap = finding_cap(changed_lines, settings.max_findings)
    verified = {c.finding.id for c in checks if c.verdict is not None}
    published, filtered = select(kept, verified, settings.min_confidence, cap)
    return verifier.Verification(published, checks, {**dropped, **filtered},
                                 settings.model_verifier if settings.verify else None, settings.min_confidence,
                                 cap, changed_lines, duration_s)


def build_context(repo_dir: Path, files: list[FileDiff], base_sha: str, settings: Settings,
                  index: RepoIndex | None = None) -> tuple[Profile, RelatedContext]:
    """Deterministic context for the reviewer: the project profile, then code related to the changed symbols."""
    profile = build_profile(repo_dir, [f.path for f in files], settings.excludes, settings.context_budget_tokens)
    related = build_related(repo_dir, files, base_sha, settings.excludes, settings.related_budget_tokens, index)
    return profile, related


def apply_size_budget(files: list[FileDiff], settings: Settings,
                      triaged: Triage | None = None) -> tuple[list[FileDiff], list[str]]:
    """Files within MAX_DIFF_LINES: risky ones first, then code before tests and docs, then smaller first."""
    total = sum(f.added + f.removed for f in files)
    if total <= settings.max_diff_lines:
        return files, []
    if settings.on_oversize == "fail":
        raise DiffTooLargeError(
            f"diff has {total} changed lines, above MAX_DIFF_LINES={settings.max_diff_lines} "
            "(raise the limit or set ON_OVERSIZE=partial)")

    def priority(f: FileDiff) -> tuple[bool, bool, int]:
        low = any(part.lower() in LOW_PRIORITY_PARTS for part in Path(f.path).parts[:-1])
        return bool(triaged) and triaged.level(f.path) != "risky", low, f.added + f.removed

    kept, skipped, budget = [], [], settings.max_diff_lines
    for f in sorted(files, key=priority):
        size = f.added + f.removed
        if size <= budget:
            kept.append(f)
            budget -= size
        else:
            skipped.append(f.path)
    order = {f.path: i for i, f in enumerate(files)}
    return sorted(kept, key=lambda f: order[f.path]), skipped


def _publish(result: ReviewResult, change: ChangeRequest | None, adapters: list[OutputAdapter]) -> int:
    exit_code = 0
    for adapter in adapters:
        if result.status == "error" and not adapter.publishes_errors:
            continue
        try:
            adapter.publish(result, change)
        except PublishError as e:
            log.error("adapter %s failed: %s", adapter.name, e)
            exit_code = e.exit_code
    return exit_code
