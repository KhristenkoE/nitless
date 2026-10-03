"""Verifier: an adversarial second look at every candidate finding before it can be published.

One strong-model call per finding, concurrently. Each call gets the finding and the material to refute it:
  code      the enclosing function at the finding in the new version (`+` marks added lines) and the same
            symbol in the base version, so behaviour the base code already had is recognisable as such
  related   the related-code blocks already packed for the reviewer that mention the finding's file or symbols
  rules     the conventions card and the project-doc sections closest to the finding
  task      acceptance criteria and out-of-scope items, the MR, and the other findings (for duplicates)
  tools     with TOOLS=on, repository lookups within a small budget (a type definition, a schema, callers)
The model argues against the finding first, then keeps, drops or downgrades it. A failed call leaves the
finding unverified: it is kept with a warning, never dropped silently. `apply` turns verdicts into findings;
`postprocess.select` then applies the confidence floor and the per-MR cap.
"""

import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import quoteattr

from pydantic import BaseModel, Field

from nitless.context.base import ContextItem, truncate
from nitless.context.graph import cut
from nitless.context.index import RepoIndex
from nitless.context.intent import Intent
from nitless.context.packer import RelatedContext, format_ranges
from nitless.context.profile import Profile
from nitless.context.symbols import SourceFile
from nitless.diff import FileDiff
from nitless.errors import ReviewerError
from nitless.llm import LLMClient
from nitless.models import SEVERITY_ORDER, ChangeRequest, Finding, Severity
from nitless.review.postprocess import priority
from nitless.review.requirements import criterion_of
from nitless.review.tools import Toolbox

log = logging.getLogger(__name__)

SYSTEM_PROMPT = resources.files("nitless.prompts").joinpath("verifier_system.md").read_text()
TOOLS_PROMPT = resources.files("nitless.prompts").joinpath("verifier_tools.md").read_text()
MAX_TOOL_ROUNDS = 2
MAX_WORKERS = 6
MAX_OUTPUT_TOKENS = 6000  # reasoning deployments count their thinking against this
CODE_LINES = 70  # new/base code shown around a finding
WINDOW = 12  # lines around a finding outside any function
RELATED_BUDGET_TOKENS = 3500
DOCS_BUDGET_TOKENS = 1800
DESCRIPTION_TOKENS = 600
MIN_RELATED_SCORE = 2
CODE_WORD_RE = re.compile(r"`([^`]{2,80})`|\b([a-z]+[A-Z]\w*|[A-Z][a-z]+[A-Z]\w*|[A-Za-z]+_\w+|\w+\.\w+\(?)")
PATH_RE = re.compile(r"[\w./-]+\.[A-Za-z]{1,5}")
WORD_RE = re.compile(r"[A-Za-z][a-z]{4,}")

Decision = Literal["keep", "drop", "downgrade"]
Reason = Literal["valid", "incorrect", "correct-in-this-project", "pre-existing", "out-of-scope", "nit",
                 "speculative", "duplicate"]


class Verdict(BaseModel):
    """What the verifier returns (the `submit_verdict` tool arguments). Field order makes it argue first."""

    counter_argument: str = Field(description="First, the strongest case that this finding is wrong, pre-existing, "
                                              "correct in this project, out of scope, a nit, speculative or a "
                                              "duplicate, checked against the material shown")
    decision: Decision
    reason: Reason = Field(description="'valid' for a kept finding; otherwise the main reason to drop or downgrade")
    severity: Severity | None = Field(default=None, description="downgrade only: the lower severity it deserves")
    justification: str = Field(description="One sentence explaining the decision")
    confidence: float = Field(ge=0, le=1, description="Probability that a senior engineer on this team, seeing "
                                                      "this material, agrees the finding must be addressed")


@dataclass
class Check:
    finding: Finding
    verdict: Verdict | None = None
    error: str | None = None  # the call failed: the finding stays unverified


@dataclass
class Verification:
    """The outcome of the verification stage: what gets published, and every candidate's fate."""

    published: list[Finding]
    checks: list[Check]
    dropped: dict[str, str]  # finding id -> verifier | severity_floor | min_confidence | test_coverage_limit | cap
    model: str | None  # None: VERIFY=off
    min_confidence: float
    cap: int | None
    changed_lines: int
    duration_s: float = 0.0

    @property
    def warnings(self) -> list[str]:
        return [f"verifier failed on {c.finding.file}:{c.finding.line_start}; finding kept unverified: {c.error}"
                for c in self.checks if c.error]

    def refuted_criteria(self) -> dict[str, str]:
        """{criterion id: why} for requirements findings the verifier dropped as not a real gap."""
        return {cid: c.verdict.justification for c in self.checks
                if c.verdict and c.verdict.decision == "drop" and c.verdict.reason != "duplicate"
                and (cid := criterion_of(c.finding))}

    def trace(self) -> dict:
        return {"enabled": self.model is not None, "model": self.model, "min_confidence": self.min_confidence,
                "cap": self.cap, "changed_lines": self.changed_lines, "candidates": len(self.checks),
                "published": len(self.published), "unverified": sum(c.error is not None for c in self.checks),
                "duration_s": self.duration_s, "findings": trace_rows(self.checks, self.published, self.dropped)}


class Assessment(BaseModel):
    assessment: str = Field(description="2-4 sentence overall assessment covering only the published findings")


RESTATE_PROMPT = (
    "You edit the overall assessment of a code review. Some findings the reviewer mentioned were withdrawn "
    "after verification and will not be posted. Rewrite the assessment so it mentions only the published "
    "findings: remove or soften statements about withdrawn ones, keep everything else (what the change does, "
    "what it does well) and the reviewer's tone. With no published findings, say the change looks good. "
    "2-4 sentences. Call `submit_assessment` exactly once.")


MERGE_PROMPT = (" The assessment was written in parts, one per part of a large merge request: merge them into one "
                "assessment of the whole merge request.")


def restate(llm: LLMClient, model: str, assessment: str, v: Verification, parts: int = 1) -> str:
    """The reviewer's assessment without the withdrawn findings (fast model), and merged into one when a split
    review wrote it in `parts`. Unchanged if nothing was withdrawn from a single-part assessment."""
    withdrawn = [c.finding for c in v.checks if c.finding.id in v.dropped]
    if (not withdrawn and parts == 1) or not assessment.strip():
        return assessment
    listing = "\n".join(f"- {f.file}:{f.line_start} {f.message}" for f in v.published) or "(none)"
    removed = "\n".join(f"- {f.file}:{f.line_start} {f.message}" for f in withdrawn) or "(none)"
    try:
        return llm.call_tool(model, [
            {"role": "system", "content": RESTATE_PROMPT + (MERGE_PROMPT if parts > 1 else "")},
            {"role": "user", "content": f"Assessment:\n{assessment}\n\nPublished findings:\n{listing}\n\n"
                                        f"Withdrawn findings:\n{removed}"},
        ], "submit_assessment", "Submit the edited assessment.", Assessment, max_tokens=800).assessment
    except ReviewerError as e:
        log.warning("could not restate the assessment: %s", e)
        return f"{assessment.strip()} ({len(withdrawn)} candidate findings were withdrawn after verification.)"


@dataclass
class Material:
    """Everything a verifier call may show, gathered once per merge request."""

    change: ChangeRequest
    files: dict[str, FileDiff]
    head: dict[str, SourceFile]  # changed files, new version
    base: dict[str, SourceFile]  # changed files, base version, by new path
    related: list[ContextItem] = field(default_factory=list)
    related_notes: list[str] = field(default_factory=list)
    docs: list[ContextItem] = field(default_factory=list)
    card: str = ""
    task: str = ""


def build_material(repo_dir: Path, change: ChangeRequest, files: list[FileDiff], profile: Profile,
                   related: RelatedContext, intent: Intent, card: str, index: RepoIndex | None = None) -> Material:
    index = index or RepoIndex(repo_dir, [], change.base_sha)
    olds = index.base_sources([f.old_path for f in files if f.old_path and f.status != "added"])
    head = {f.path: src for f in files if f.status != "deleted" and (src := index.source(f.path)) is not None}
    base = {f.path: olds[f.old_path] for f in files if f.old_path in olds and f.status != "added"}
    return Material(change, {f.path: f for f in files}, head, base, related.included, related.notes,
                    [item for item in profile.included if item.kind == "doc"], card, intent.render())


# --- calls ------------------------------------------------------------------------------------


def verify(llm: LLMClient, model: str, findings: list[Finding], material: Material,
           tools: Callable[[str], Toolbox] | None = None) -> list[Check]:
    """One verdict per finding, in the order given. Never raises: a failed call is an unverified Check.

    `tools`, when given, makes a toolbox for each finding (named by the finding's location).
    """
    if not findings:
        return []
    started = time.monotonic()
    ranked = sorted(findings, key=lambda f: -priority(f))  # the order duplicates are judged in
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(findings))) as pool:
        checks = list(pool.map(lambda f: _check(llm, model, f, ranked, material,
                                                tools(f"verify {f.file}:{f.line_start}") if tools else None),
                               findings))
    log.info("verifier: %d findings, %d dropped, %d unverified, %.1fs", len(checks),
             sum(c.verdict is not None and c.verdict.decision == "drop" for c in checks),
             sum(c.verdict is None for c in checks), time.monotonic() - started)
    return checks


def _check(llm: LLMClient, model: str, finding: Finding, ranked: list[Finding], material: Material,
           tools: Toolbox | None = None) -> Check:
    system = SYSTEM_PROMPT if tools is None else f"{SYSTEM_PROMPT}\n\n{TOOLS_PROMPT.format(calls=tools.max_calls)}"
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": build_message(finding, ranked, material)}]
    description = "Submit the verdict on this one finding."
    try:
        verdict = llm.call_tool(model, messages, "submit_verdict", description, Verdict,
                                max_tokens=MAX_OUTPUT_TOKENS) if tools is None else \
            llm.run_agent(model, messages, tools, "submit_verdict", description, Verdict,
                          max_rounds=MAX_TOOL_ROUNDS, max_tokens=MAX_OUTPUT_TOKENS)
    except ReviewerError as e:
        log.warning("verifier failed on %s:%s: %s", finding.file, finding.line_start, e)
        return Check(finding, error=str(e))
    return Check(finding, verdict)


# --- verdicts ---------------------------------------------------------------------------------


def apply(checks: list[Check], severity_floor: str) -> tuple[list[Finding], dict[str, str]]:
    """Findings updated by their verdicts (severity, calibrated confidence); {id: why} for those dropped."""
    floor = SEVERITY_ORDER[severity_floor]
    kept: list[Finding] = []
    dropped: dict[str, str] = {}
    for c in checks:
        v, f = c.verdict, c.finding
        if v is None:
            kept.append(f)
            continue
        if v.decision == "drop":
            dropped[f.id] = "verifier"
            continue
        severity = downgraded(f.severity, v.severity) if v.decision == "downgrade" else f.severity
        if SEVERITY_ORDER[severity] < floor:
            dropped[f.id] = "severity_floor"
            continue
        kept.append(f.model_copy(update={"severity": severity, "confidence": v.confidence}))
    return kept, dropped


def downgraded(current: Severity, proposed: Severity | None) -> Severity:
    """The proposed severity if it is lower; otherwise one step down."""
    if proposed is not None and SEVERITY_ORDER[proposed] < SEVERITY_ORDER[current]:
        return proposed
    by_rank = {rank: name for name, rank in SEVERITY_ORDER.items()}
    return by_rank[max(0, SEVERITY_ORDER[current] - 1)]  # type: ignore[return-value]


def trace_rows(checks: list[Check], final: list[Finding], dropped: dict[str, str]) -> list[dict]:
    """Every candidate's fate: the reviewer's claim, the verdict, and whether (and by what) it was dropped."""
    by_id = {f.id: f for f in final}
    rows = []
    for c in checks:
        f, v = c.finding, c.verdict
        row = {"id": f.id, "file": f.file, "line": f.line_start, "category": f.category, "message": f.message,
               "reviewer": {"severity": f.severity, "confidence": f.confidence},
               "verdict": v.model_dump() if v else None, "error": c.error,
               "status": "kept" if f.id in by_id else "dropped", "dropped_by": dropped.get(f.id)}
        if f.id in by_id:
            row["published"] = {"severity": by_id[f.id].severity, "confidence": by_id[f.id].confidence}
        rows.append(row)
    return rows


# --- the prompt -------------------------------------------------------------------------------


def build_message(finding: Finding, ranked: list[Finding], m: Material) -> str:
    parts = [render_finding(finding)]
    diff = m.files.get(finding.file)
    if diff is not None:
        new_code, base_code = code_at(diff, m.head.get(diff.path), m.base.get(diff.path), finding.line_start,
                                      finding.line_end)
        parts += [f"# Code at the finding (new version)\n\n{new_code}",
                  f"# The same code before this change (base version)\n\n{base_code}"]
    parts.append(render_change(m))
    if m.task:
        parts.append(m.task)
    if rules := render_rules(finding, m):
        parts.append(rules)
    if related := render_related(finding, m):
        parts.append(related)
    parts.append(render_others(finding, ranked))
    return "\n\n".join(parts)


def render_finding(f: Finding) -> str:
    lines = [f"# Finding under review\n\n{f.file}:{f.line_start}-{f.line_end} · {f.severity} · {f.category} · "
             f"reviewer confidence {f.confidence:.2f}",
             f"Message: {f.message}", f"Rationale: {f.rationale}"]
    if f.suggestion:
        lines.append(f"Suggestion: {f.suggestion}")
    if f.evidence:
        lines.append("Evidence cited:\n" + "\n".join(
            f"- {e.kind} {e.ref}{': ' + e.note if e.note else ''}" for e in f.evidence))
    return "\n".join(lines)


def code_at(diff: FileDiff, head: SourceFile | None, base: SourceFile | None, start: int, end: int
            ) -> tuple[str, str]:
    """The new-version code around a finding, and the same symbol (or region) in the base version."""
    if head is None:
        return "(new version unavailable: deleted or unreadable)", "(not shown)"
    added = {ln.new_no for h in diff.hunks for ln in h.lines if ln.kind == "+" and ln.new_no is not None}
    d = head.enclosing(start, {"function", "method"}) or head.enclosing(start)
    if d is not None and (d.kind in ("function", "method") or d.size <= CODE_LINES):
        ranges, title = cut(d, start, CODE_LINES), f"{d.kind} `{d.qualname}`"
    else:
        d = None
        ranges, title = ((max(1, start - WINDOW), min(len(head.lines), max(end, start) + WINDOW)),), "lines"
    new = (f"{title} in {diff.path}, lines {format_ranges(list(ranges))}; `+` marks lines this change added.\n"
           + numbered(head.lines, ranges, added))

    if diff.status == "added" or base is None:
        return new, "The file is new in this change." if diff.status == "added" else "(base version unavailable)"
    if d is not None:
        before = next((b for b in base.definitions if b.qualname == d.qualname), None)
        if before is None:
            return new, f"`{d.qualname}` does not exist in the base version: this change adds it."
        b_ranges = cut(before, None, CODE_LINES)
        return new, f"{before.kind} `{before.qualname}` in {diff.old_path}, lines {format_ranges(list(b_ranges))}.\n" \
            + numbered(base.lines, b_ranges)
    old_start = _old_line(diff, start)
    b_ranges = ((max(1, old_start - WINDOW), min(len(base.lines), old_start + WINDOW + max(0, end - start))),)
    return new, f"{diff.old_path}, lines {format_ranges(list(b_ranges))}.\n" + numbered(base.lines, b_ranges)


def numbered(lines: list[str], ranges: tuple[tuple[int, int], ...], added: set[int] | None = None) -> str:
    out = []
    for i, (a, b) in enumerate(ranges):
        if i:
            out.append("     …")
        out += [f"{n:>6} {'+' if added and n in added else ' '} {lines[n - 1]}"
                for n in range(a, min(b, len(lines)) + 1)]
    return "\n".join(out)


def _old_line(diff: FileDiff, new_line: int) -> int:
    """The base-version line that corresponds to a new-version line (via the nearest unchanged line before it)."""
    offset = 0
    for h in diff.hunks:
        if h.new_start > new_line:
            break
        if new_line >= h.new_start + h.new_count:  # past this hunk
            offset = (h.old_start + h.old_count) - (h.new_start + h.new_count)
            continue
        pairs = [(ln.old_no, ln.new_no) for ln in h.lines
                 if ln.old_no is not None and ln.new_no is not None and ln.new_no <= new_line]
        offset = pairs[-1][0] - pairs[-1][1] if pairs else h.old_start - h.new_start
    return max(1, new_line + offset)


def render_change(m: Material) -> str:
    description = truncate(m.change.description.strip() or "(no description)", DESCRIPTION_TOKENS)
    changed = "\n".join(f"- {f.path} ({f.status}, +{f.added} -{f.removed})" for f in m.files.values())
    return f"# Merge request: {m.change.title}\n\n{description}\n\nFiles changed:\n{changed}"


def render_rules(f: Finding, m: Material) -> str:
    parts = [m.card] if m.card else []
    docs = select(f, m.docs, DOCS_BUDGET_TOKENS, min_score=1)
    if docs:
        parts.append("# Project documentation (excerpts closest to the finding)\n\n" + "\n\n".join(
            f"<context kind=\"doc\" source={quoteattr(d.source)}>\n{d.text}\n</context>" for d in docs))
    if f.category == "test-coverage" and m.related_notes:
        parts.append("# Test notes\n\n" + "\n".join(f"- {n}" for n in m.related_notes))
    return "\n\n".join(parts)


def render_related(f: Finding, m: Material) -> str:
    items = select(f, m.related, RELATED_BUDGET_TOKENS, min_score=MIN_RELATED_SCORE)
    if not items:
        return ""
    return ("# Related code (outside the diff; left column is the head-version line number)\n\n"
            + "\n\n".join(f"<context kind={quoteattr(i.kind)} source={quoteattr(i.source)} "
                          f"reason={quoteattr(i.reason)}>\n{i.text}\n</context>" for i in items))


def render_others(f: Finding, ranked: list[Finding]) -> str:
    rows = [f"[{n}] {o.file}:{o.line_start} {o.severity}/{o.category}: {o.message}"
            + ("   <- the finding under review" if o.id == f.id else "")
            for n, o in enumerate(ranked, 1)]
    return "# All findings on this merge request, most important first\n\n" + "\n".join(rows)


def select(f: Finding, items: list[ContextItem], budget_tokens: int, min_score: int) -> list[ContextItem]:
    """The items that talk about what the finding talks about: cited files, its code identifiers, its words."""
    text = " ".join([f.message, f.rationale, f.suggestion or "",
                     *(f"{e.ref} {e.note or ''}" for e in f.evidence)])
    names = {w for m in CODE_WORD_RE.finditer(text) for w in re.findall(r"[A-Za-z_]\w{2,}", m[1] or m[2])}
    paths = {p.split("#")[0] for p in PATH_RE.findall(text)} | {e.ref.split(":")[0].split("#")[0]
                                                                  for e in f.evidence}
    words = {w.lower() for w in WORD_RE.findall(text)}

    def score(item: ContextItem) -> int:
        path = item.source.split(":")[0].split("#")[0]
        s = 3 if any(path.endswith(p) or p.endswith(path) for p in paths if p) else 0
        s += 1 if path == f.file else 0
        s += min(4, sum(1 for n in names if n in item.text))
        if item.kind == "doc":
            s += min(3, len(words & {w.lower() for w in WORD_RE.findall(item.text)}) // 4)
        return s

    chosen, used = [], 0
    for s, item in sorted(((score(it), it) for it in items), key=lambda t: -t[0]):
        if s < min_score:
            break
        if used + item.tokens <= budget_tokens:
            chosen.append(item)
            used += item.tokens
    return chosen
