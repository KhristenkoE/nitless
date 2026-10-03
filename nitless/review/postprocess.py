"""Deterministic checks applied to every model finding before it can be published."""

import hashlib
import re
from collections import Counter

from nitless.diff import FileDiff
from nitless.models import SEVERITY_ORDER, Counts, Finding, Requirements, Summary
from nitless.review.schema import CandidateFinding


def fingerprint(c: CandidateFinding) -> str:
    """Stable id, also used later to skip findings already posted on the MR."""
    key = f"{c.file}|{c.category}|{c.line_start}|{c.message.strip().lower()[:80]}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def validate(candidates: list[CandidateFinding], files: list[FileDiff], severity_floor: str,
             min_confidence: float = 0.0) -> tuple[list[Finding], list[str]]:
    """Drop findings that point outside the diff, fall below thresholds, or repeat. Returns (kept, warnings)."""
    by_path = {f.path: f for f in files}
    floor = SEVERITY_ORDER[severity_floor]
    kept: dict[str, Finding] = {}
    warnings: list[str] = []

    for c in candidates:
        diff = by_path.get(c.file.removeprefix("./"))
        if diff is None:
            warnings.append(f"dropped finding on {c.file}: file is not part of this change")
            continue
        if not diff.covers_line(c.line_start):
            warnings.append(f"dropped finding on {c.file}:{c.line_start}: line is outside the changed hunks")
            continue
        if SEVERITY_ORDER[c.severity] < floor or c.confidence < min_confidence:
            continue
        fid = fingerprint(c)
        if fid in kept:
            continue
        kept[fid] = Finding(
            id=fid, file=diff.path, line_start=c.line_start, line_end=max(c.line_end or c.line_start, c.line_start),
            severity=c.severity, category=c.category, message=c.message.strip(), rationale=c.rationale.strip(),
            suggestion=c.suggestion, evidence=c.evidence, confidence=c.confidence,
        )

    findings = sorted(kept.values(), key=lambda f: (-SEVERITY_ORDER[f.severity], f.file, f.line_start))
    return findings, warnings


DUPLICATE_LINE_SLACK = 3
DUPLICATE_WORD_OVERLAP = 0.4


def dedupe_units(per_unit: list[list[CandidateFinding]]) -> tuple[list[CandidateFinding], list[str]]:
    """The findings of every review unit, without one unit repeating another's (same file, nearby lines, and
    the same category or mostly the same words). The copy with the higher severity × confidence is kept."""
    ranked = sorted(((u, c) for u, found in enumerate(per_unit) for c in found),
                    key=lambda uc: -(SEVERITY_ORDER[uc[1].severity] + 1) * uc[1].confidence)
    kept: list[tuple[int, CandidateFinding]] = []
    notes = []
    for unit, c in ranked:
        twin = next((k for u, k in kept if u != unit and _same_issue(c, k)), None)
        if twin is None:
            kept.append((unit, c))
        else:
            notes.append(f"dropped finding on {c.file}:{c.line_start} from review part {unit + 1}: it repeats "
                         f"the finding at {twin.file}:{twin.line_start}")
    order = {id(c): i for i, c in enumerate(c for found in per_unit for c in found)}
    return [c for _, c in sorted(kept, key=lambda uc: order[id(uc[1])])], notes


def _same_issue(a: CandidateFinding, b: CandidateFinding) -> bool:
    if a.file.removeprefix("./") != b.file.removeprefix("./"):
        return False
    if a.line_start > (b.line_end or b.line_start) + DUPLICATE_LINE_SLACK \
            or (a.line_end or a.line_start) < b.line_start - DUPLICATE_LINE_SLACK:
        return False
    mine, theirs = _words(a.message), _words(b.message)
    return a.category == b.category or (bool(mine) and len(mine & theirs) / len(mine) >= DUPLICATE_WORD_OVERLAP)


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z_][\w.]{3,}", text)}


CAP_BY_DIFF_SIZE = ((50, 3), (300, 6))  # changed lines -> most findings worth posting; larger diffs: CAP_LARGE
CAP_LARGE = 10


def finding_cap(changed_lines: int, max_findings: int | None) -> int | None:
    """MAX_FINDINGS if set (0 = no cap), else a cap that grows with the diff: a small change gets few comments."""
    if max_findings is not None:
        return max_findings or None
    return next((cap for size, cap in CAP_BY_DIFF_SIZE if changed_lines <= size), CAP_LARGE)


def priority(f: Finding) -> float:
    """Severity × confidence: what the cap keeps, and the order the verifier lists findings in."""
    return (SEVERITY_ORDER[f.severity] + 1) * f.confidence


def select(findings: list[Finding], verified: set[str], min_confidence: float,
           cap: int | None) -> tuple[list[Finding], dict[str, str]]:
    """The findings worth posting, and {id: why} for the rest.

    Applied in order: the confidence floor (to verified findings only: their confidence is the verifier's
    calibrated one), at most one test-coverage finding, then the per-MR cap, keeping the highest
    severity × confidence.
    """
    dropped: dict[str, str] = {}
    ranked = sorted(findings, key=lambda f: -priority(f))
    kept: list[Finding] = []
    for f in ranked:
        if f.id in verified and f.confidence < min_confidence:
            dropped[f.id] = "min_confidence"
        elif f.category == "test-coverage" and any(k.category == "test-coverage" for k in kept):
            dropped[f.id] = "test_coverage_limit"
        elif cap is not None and len(kept) >= cap:
            dropped[f.id] = "cap"
        else:
            kept.append(f)
    order = {f.id: i for i, f in enumerate(findings)}
    return sorted(kept, key=lambda f: order[f.id]), dropped


def summarize(assessment: str, findings: list[Finding], requirements: Requirements | None = None) -> Summary:
    """Verdict from severities; an unmet acceptance criterion always means changes are needed."""
    severities = Counter(f.severity for f in findings)
    unmet = [c.id for c in requirements.criteria if c.status == "not_met"] if requirements else []
    if severities["critical"] or severities["major"] or unmet:
        verdict = "needs_changes"
    elif findings:
        verdict = "minor_issues"
    else:
        verdict = "no_issues"
    assessment = assessment.strip()
    if requirements and requirements.criteria and requirements.criteria[0].id != "intent":
        met = sum(c.status == "met" for c in requirements.criteria)
        partial = [c.id for c in requirements.criteria if c.status == "partially_met"]
        gaps = [f"{label}: {', '.join(ids)}" for label, ids in (("not met", unmet), ("partially met", partial)) if ids]
        source = requirements.source.rsplit("/", 1)[-1] if "://" not in requirements.source else requirements.source
        assessment += (f" Requirements ({source}): {met}/{len(requirements.criteria)} acceptance "
                       f"criteria met{'; ' + '; '.join(gaps) if gaps else ''}.")
    return Summary(
        assessment=assessment.strip(),
        verdict=verdict,
        counts=Counts(by_severity=dict(severities), by_category=dict(Counter(f.category for f in findings))),
    )
