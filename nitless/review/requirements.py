"""Requirements check: does the change do what the task asked?

One strong-model call over the task, the project profile, related code and the annotated diff. Each
acceptance criterion gets a status with evidence; unmet ones that map to a changed line also become
`requirements` findings, which own AC coverage (see `merge_findings`).
"""

import re

from pydantic import BaseModel, Field

from nitless import prompts
from nitless.context.intent import Intent
from nitless.diff import FileDiff
from nitless.llm import LLMClient
from nitless.models import ChangeRequest, Criterion, CriterionStatus, Evidence, Finding, Requirements
from nitless.review.naive import build_user_message
from nitless.review.schema import CandidateFinding

MIN_FINDING_CONFIDENCE = {"not_met": 0.6, "partially_met": 0.75}  # a partial gap is a finding only when clear
SEVERITY = {"not_met": "major", "partially_met": "minor"}
DUPLICATE_LINE_SLACK = 5
DUPLICATE_WORD_OVERLAP = 0.4
SEVERITY_RANK = {"info": 0, "minor": 1, "major": 2, "critical": 3}


class CriterionCheck(BaseModel):
    id: str = Field(description="'AC1', 'AC2', ... as numbered in the task; 'intent' when it has no criteria")
    status: CriterionStatus
    evidence: str = Field(description="met: file:line of the diff that implements it. Otherwise what is missing "
                                      "or wrong, citing file:line")
    gap: str | None = Field(default=None, description="not_met/partially_met: one sentence stating the defect in "
                                                      "code terms (which function lacks what, and the consequence)")
    file: str | None = Field(default=None, description="not_met/partially_met: the changed file where the fix "
                                                       "belongs, exactly as in the diff header; null if none")
    line: int | None = Field(default=None, description="new-file line in that file's diff where the missing "
                                                       "behaviour belongs")
    confidence: float = Field(ge=0, le=1, description="probability a senior engineer agrees with the status")


class RequirementsSubmission(BaseModel):
    criteria: list[CriterionCheck] = Field(default_factory=list)
    scope_creep: list[str] = Field(default_factory=list,
                                   description="notable changes beyond the task; empty is normal")
    verdict: str = Field(description="one sentence: does the change do what was asked?")


def assess(llm: LLMClient, model: str, intent: Intent, change: ChangeRequest, files: list[FileDiff],
           profile: str = "", related: str = "") -> RequirementsSubmission:
    task = intent.render() or f"# Task\n\nFrom {intent.describe_source()}.\n\n{intent.intent}"
    if not intent.acceptance_criteria:
        task += "\n\nThe task lists no acceptance criteria: assess its intent as one criterion with id `intent`."
    messages = [
        {"role": "system", "content": prompts.get("requirements_system")},
        {"role": "user", "content": build_user_message(change, files, profile, related, task=task)},
    ]
    return llm.call_tool(model, messages, "submit_requirements",
                         "Submit the status of every acceptance criterion, scope creep and a verdict.",
                         RequirementsSubmission, max_tokens=6000)


def criteria(intent: Intent, submission: RequirementsSubmission) -> list[tuple[Criterion, CriterionCheck | None]]:
    """The task's criteria in order, each with the model's check (None when it skipped one)."""
    wanted = [(f"AC{i}", text) for i, text in enumerate(intent.acceptance_criteria, 1)] or [
        ("intent", intent.intent.strip() or intent.title)]
    checks = {_norm_id(c.id): c for c in submission.criteria}
    out = []
    for cid, text in wanted:
        check = checks.get(cid.lower())
        if check is None:
            out.append((Criterion(id=cid, text=text, status="cannot_determine", evidence="not assessed"), None))
        else:
            out.append((Criterion(id=cid, text=text, status=check.status, evidence=check.evidence.strip()), check))
    return out


def to_requirements(intent: Intent, submission: RequirementsSubmission) -> Requirements:
    rows = [c for c, _ in criteria(intent, submission)]
    return Requirements(source=intent.source, kind=intent.kind, does_what_was_asked=_answer(rows),
                        verdict=submission.verdict.strip(), criteria=rows, out_of_scope=intent.out_of_scope,
                        scope_creep=[s.strip() for s in submission.scope_creep if s.strip()])


def dispute(reqs: Requirements, disputed: dict[str, str]) -> Requirements:
    """Criteria whose gap the verifier refuted ({criterion id: why}) become `cannot_determine`."""
    if not disputed:
        return reqs
    rows = [c.model_copy(update={"status": "cannot_determine", "evidence": f"{c.evidence} Verification disputed "
                                                                           f"the gap: {disputed[c.id]}"})
            if c.id in disputed else c for c in reqs.criteria]
    return reqs.model_copy(update={"criteria": rows, "does_what_was_asked": _answer(rows)})


def criterion_of(finding: Finding | CandidateFinding) -> str | None:
    """The acceptance criterion a `requirements` finding from `to_findings` reports, e.g. 'AC2'."""
    ref = next((e.ref for e in finding.evidence if e.kind == "task"), "")
    return ref.rsplit("#", 1)[1] if finding.category == "requirements" and "#" in ref else None


def _answer(rows: list[Criterion]) -> str:
    statuses = {c.status for c in rows}
    if "not_met" in statuses and "met" not in statuses and "partially_met" not in statuses:
        return "no"
    if statuses & {"not_met", "partially_met"}:
        return "partially"
    return "yes" if "met" in statuses else "unknown"


def to_findings(intent: Intent, submission: RequirementsSubmission, files: list[FileDiff]) -> list[CandidateFinding]:
    """Unmet acceptance criteria the model anchored to changed code, snapped into the nearest hunk of that file."""
    by_path = {f.path: f for f in files}
    out = []
    for criterion, check in criteria(intent, submission):
        if check is None or criterion.id == "intent" or criterion.status not in SEVERITY:
            continue
        diff = by_path.get((check.file or "").strip().removeprefix("./"))
        if diff is None or check.line is None or check.confidence < MIN_FINDING_CONFIDENCE[criterion.status]:
            continue
        line = _snap(diff, check.line)
        out.append(CandidateFinding(
            file=diff.path, line_start=line, severity=SEVERITY[criterion.status], category="requirements",
            message=(check.gap or f"Acceptance criterion {criterion.id} is {criterion.status.replace('_', ' ')}: "
                                  f"{criterion.text}").strip(),
            rationale=f"{criterion.id} of {intent.describe_source()} requires: \"{criterion.text}\" "
                      f"{criterion.evidence}".strip(),
            evidence=[Evidence(kind="task", ref=f"{intent.source}#{criterion.id}", note=criterion.text)],
            confidence=check.confidence,
        ))
    return out


def merge_findings(reviewer: list[CandidateFinding], requirements: list[CandidateFinding],
                   owns_criteria: bool) -> tuple[list[CandidateFinding], list[str]]:
    """Reviewer findings plus requirements findings, without double-reporting one gap.

    When the requirements step checked acceptance criteria it owns the `requirements` category; a reviewer
    finding of another category describing the same gap at the same place is folded into the AC finding.
    """
    kept, notes = [], []
    merged = [r.model_copy() for r in requirements]
    for f in reviewer:
        if owns_criteria and f.category == "requirements":
            notes.append(f"dropped reviewer requirements finding on {f.file}:{f.line_start} "
                         "(acceptance criteria are checked by the requirements step)")
            continue
        twin = next((r for r in merged if _same_gap(f, r)), None)
        if twin is not None:
            if SEVERITY_RANK[f.severity] > SEVERITY_RANK[twin.severity]:
                twin.severity = f.severity
            notes.append(f"merged reviewer finding on {f.file}:{f.line_start} into the requirements finding "
                         f"at {twin.file}:{twin.line_start}")
            continue
        kept.append(f)
    return kept + merged, notes


def _same_gap(f: CandidateFinding, r: CandidateFinding) -> bool:
    if f.file != r.file:
        return False
    end = f.line_end or f.line_start
    if f.line_start > (r.line_end or r.line_start) + DUPLICATE_LINE_SLACK or end < r.line_start - \
            DUPLICATE_LINE_SLACK:
        return False
    mine, theirs = _words(f.message), _words(f"{r.message} {r.evidence[0].note if r.evidence else ''}")
    return bool(mine) and len(mine & theirs) / len(mine) >= DUPLICATE_WORD_OVERLAP


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z_][\w.]{3,}", text)}


def _snap(diff: FileDiff, line: int) -> int:
    if diff.covers_line(line):
        return line
    points = [n for start, end in diff.new_line_ranges() for n in (start, end)]
    return min(points, key=lambda n: abs(n - line)) if points else line


def _norm_id(cid: str) -> str:
    return re.sub(r"[\s#_-]", "", cid).lower()
