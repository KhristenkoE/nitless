"""Human-readable report, also the body of the GitLab summary note."""

import sys
from collections.abc import Collection

from nitless.errors import ConfigError
from nitless.models import SEVERITY_ORDER, ChangeRequest, Finding, ReviewResult
from nitless.output.base import OutputAdapter

VERDICTS = {"no_issues": "✅ No issues", "minor_issues": "🟡 Minor issues", "needs_changes": "🔴 Needs changes"}
STATUS = {"ok": "✅ ok", "partial": "⚠️ partial", "error": "❌ error"}
SEVERITY_ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}
CRITERION_ICON = {"met": "✅", "partially_met": "🟡", "not_met": "❌", "cannot_determine": "❔"}
ASKED_ICON = {"yes": "✅", "partially": "🟡", "no": "❌", "unknown": "❔"}


def render(result: ReviewResult, change: ChangeRequest | None, inline: Collection[str] | None = None) -> str:
    """The report as markdown.

    `inline` is the set of finding ids already posted as inline comments: those are listed as one line
    each and the rest go under "Findings outside the diff". None renders every finding in full.
    """
    parts = [_header(result, change)]
    if result.summary:
        parts.append(result.summary.assessment)
    if result.requirements:
        parts.append(_requirements(result))
    if result.status != "error":  # a failed run has no findings to be silent about
        parts.append(_findings(result.findings) if inline is None else _findings_split(result.findings, set(inline)))
    if result.warnings:
        parts.append("## ⚠️ Warnings\n\n" + _bullets(result.warnings))
    if result.skipped_files:
        parts.append("## ⏭️ Skipped files\n\n" + _bullets(f"`{p}`" for p in result.skipped_files))
    if result.error:
        parts.append(f"## ❌ Error\n\n**{result.error.kind}**: {result.error.message}")
    parts.append(_footer(result))
    return "\n\n".join(parts) + "\n"


def render_finding(f: Finding) -> str:
    """One finding in full: location line, rationale, suggestion, evidence (collapsed), confidence."""
    lines = [f"{finding_line(f)}\n\n{f.rationale}"]
    if f.suggestion:
        lines.append(f"💡 **Suggestion:** {f.suggestion}")
    if f.evidence:
        refs = "\n".join(f"- {e.kind}: `{e.ref}`" + (f" — {e.note}" if e.note else "") for e in f.evidence)
        lines.append(f"<details><summary>📎 Evidence ({len(f.evidence)})</summary>\n\n{refs}\n\n</details>")
    lines.append(f"🎯 Confidence: {round(f.confidence * 100)}%")
    return "\n\n".join(lines)


def finding_line(f: Finding) -> str:
    return f"{SEVERITY_ICON[f.severity]} **{location(f)}** · {f.severity} · `{f.category}` — {f.message}"


def location(f: Finding) -> str:
    span = f"{f.line_start}" if f.line_end == f.line_start else f"{f.line_start}-{f.line_end}"
    return f"{f.file}:{span}"


def _header(result: ReviewResult, change: ChangeRequest | None) -> str:
    subject = result.run.mr
    if change:
        subject = f"[{change.title}]({change.web_url})" if change.web_url else change.title
    title = f"# 🤖 AI review of {subject}" if subject else "# 🤖 AI review"
    if not result.summary:  # nothing was reviewed: the run status is the only thing to say
        return f"{title}\n\n**Status:** {STATUS[result.status]}"
    badge = f"**Verdict:** {VERDICTS[result.summary.verdict]}"
    counts = result.summary.counts.by_severity
    if counts:
        badge += " · " + " · ".join(f"{SEVERITY_ICON[sev]} {counts[sev]} {sev}" for sev in SEVERITY_ORDER
                                    if counts.get(sev))
    if result.status == "partial":
        badge += " · ⚠️ partial run, see warnings"
    return f"{title}\n\n{badge}"


def _requirements(result: ReviewResult) -> str:
    req = result.requirements
    assert req is not None
    lines = [
        "## 📋 Requirements",
        f"Source: `{req.source}` ({req.kind}). Does what was asked: {ASKED_ICON[req.does_what_was_asked]} "
        f"**{req.does_what_was_asked}**. {req.verdict}",
    ]
    if req.criteria:
        rows = ["| # | Status | Criterion | Evidence |", "|---|---|---|---|"]
        rows += [f"| {c.id} | {CRITERION_ICON[c.status]} {c.status.replace('_', ' ')} | {_cell(c.text)} | "
                 f"{_cell(c.evidence)} |" for c in req.criteria]
        lines.append("\n".join(rows))
    if req.out_of_scope:
        lines.append("🚫 Out of scope:\n\n" + _bullets(req.out_of_scope))
    if req.scope_creep:
        lines.append("↗️ Scope creep:\n\n" + _bullets(req.scope_creep))
    return "\n\n".join(lines)


def _findings(findings: list[Finding]) -> str:
    if not findings:
        return "## 🔍 Findings\n\n✅ No findings."
    groups = []
    for severity in sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.__getitem__, reverse=True):
        group = [f for f in findings if f.severity == severity]
        if group:
            groups.append(f"### {SEVERITY_ICON[severity]} {severity.capitalize()}\n\n"
                          + "\n\n".join(render_finding(f) for f in group))
    return "## 🔍 Findings\n\n" + "\n\n".join(groups)


def _findings_split(findings: list[Finding], inline: set[str]) -> str:
    if not findings:
        return "## 🔍 Findings\n\n✅ No findings."
    posted = [f for f in findings if f.id in inline]
    outside = [f for f in findings if f.id not in inline]
    parts = ["## 🔍 Findings"]
    if posted:
        parts.append("💬 Posted as inline comments:\n\n" + _bullets(finding_line(f) for f in posted))
    if outside:
        parts.append("### Findings outside the diff\n\n" + "\n\n".join(render_finding(f) for f in outside))
    return "\n\n".join(parts)


def _footer(result: ReviewResult) -> str:
    run = result.run
    models = ", ".join(f"{role} `{name}`" for role, name in run.models.items())
    prompt = sum(u.prompt_tokens for u in run.usage.values())
    completion = sum(u.completion_tokens for u in run.usage.values())
    duration = f"{run.duration_s:g} s" if run.duration_s is not None else "n/a"
    cost = f" · 💸 ${run.cost_usd:.4f}" if run.cost_usd is not None else ""
    return (f"---\n\n<sub>{STATUS[result.status]} · 🧠 {models} · 🔢 {prompt:,} prompt / {completion:,} completion "
            f"tokens{cost} · ⏱ {duration} · nitless {run.tool_version}</sub>")


def _bullets(items) -> str:
    return "\n".join(f"- {item}" for item in items)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


class MarkdownAdapter(OutputAdapter):
    """The markdown report to MARKDOWN_FILE, or stdout."""

    name = "markdown"

    def validate(self) -> None:
        s = self.settings
        if s.markdown_file is None and "json" in s.output_adapter and s.output_file is None:
            raise ConfigError("json and markdown would both write to stdout; set OUTPUT_FILE or MARKDOWN_FILE")

    def publish(self, result: ReviewResult, change: ChangeRequest | None) -> None:
        report = render(result, change)
        path = self.settings.markdown_file
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report)
        else:
            sys.stdout.write(report)
            sys.stdout.flush()
