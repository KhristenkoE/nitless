"""The Conventions card: evidence-backed rules for the areas a change touches.

inferred-from-code  For each changed area (the directory of changed files), the fast model reads the sibling
                    and peer code the symbol graph already selected for those files (never the change itself)
                    and names the patterns it follows. Every rule must cite `file:line` + a quote from that
                    code; citations are checked against the lines shown and rules without one are dropped.
documented          Rule-like bullets ("must", "never", ...) of the doc sections in the project profile,
                    copied verbatim with their source. No model call.

One fast-model call per area, at most MAX_AREAS, run concurrently. Never raises: a failure means no card.
"""

import logging
import posixpath
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal
from xml.sax.saxutils import quoteattr

from pydantic import BaseModel, Field

from nitless import prompts
from nitless.context.base import estimate_tokens
from nitless.context.docs import path_terms
from nitless.context.packer import RelatedContext, format_ranges, render_lines
from nitless.context.profile import Profile
from nitless.diff import FileDiff
from nitless.llm import LLMClient

log = logging.getLogger(__name__)

MAX_AREAS = 4
MAX_FILES_PER_AREA = 4
AREA_BUDGET_TOKENS = 6000  # evidence shown to the model per area
WHOLE_FILE_LINES = 250  # unchanged sibling files up to this long are shown whole, longer ones as the graph's snippets
MIN_AREA_EVIDENCE_TOKENS = 300  # less sibling code than this is not worth a model call
MAX_RULES_PER_AREA = 5
MAX_EVIDENCE = 3
MAX_DOC_RULES = 6
CARD_BUDGET_TOKENS = 1500
QUOTE_WINDOW = 2  # a quote may sit this many lines from the cited one
DOC_RULE_RE = re.compile(r"\b(must|never|always|should|do not|don't|only|avoid|prefer|required?|instead of)\b", re.I)
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")
PROCESS_RE = re.compile(r"\b(approv\w*|reviewers?|before (you ask for )?review|must pass|CI|pipelines?|commit messages?"
                        r"|changelog|merge requests?|pull requests?)\b", re.I)  # team process, not code

Topic = Literal["error-handling", "results", "validation", "logging", "layering", "persistence", "time-money",
                "naming", "testing", "other"]


class Citation(BaseModel):
    file: str = Field(description="Path exactly as in the <code file=...> header")
    line: int = Field(description="Line number from the left column")
    quote: str = Field(description="A short fragment copied exactly from that line (an identifier or <= 60 chars)")


class ProposedRule(BaseModel):
    topic: Topic
    rule: str = Field(description="One line, <= 30 words, naming the concrete types/helpers/modules involved")
    evidence: list[Citation] = Field(description="1-3 places in the shown code that follow the rule")


class RuleSubmission(BaseModel):
    rules: list[ProposedRule] = Field(default_factory=list)


@dataclass
class Rule:
    tag: Literal["documented", "inferred-from-code"]
    area: str  # a directory, or the doc source for documented rules
    topic: str
    text: str
    evidence: list[str]  # "path:line" or a doc source


@dataclass
class Area:
    name: str
    changed: list[str]
    symbols: list[str]
    shown: dict[str, dict[int, str]] = field(default_factory=dict)  # file -> line number -> text
    blocks: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # "path:ranges", for the trace

    @property
    def tokens(self) -> int:
        return sum(estimate_tokens(b) for b in self.blocks)


@dataclass
class ConventionsCard:
    rules: list[Rule] = field(default_factory=list)
    areas: list[dict] = field(default_factory=list)  # per-area trace rows
    warnings: list[str] = field(default_factory=list)
    dropped_for_budget: int = 0
    duration_s: float = 0.0

    def render(self) -> str:
        if not self.rules:
            return ""
        return render_card(self.rules)

    def render_for(self, paths: list[str]) -> str:
        """The card for part of a change: documented rules, and inferred rules of the areas holding `paths`."""
        dirs = {posixpath.dirname(p) for p in paths}
        rules = [r for r in self.rules if r.tag == "documented" or r.area in dirs]
        return render_card(rules) if rules else ""

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.render())

    def trace(self) -> dict:
        return {"tokens": self.tokens, "duration_s": self.duration_s, "areas": self.areas,
                "rules": [{"tag": r.tag, "area": r.area, "topic": r.topic, "rule": r.text, "evidence": r.evidence}
                          for r in self.rules],
                "dropped_for_budget": self.dropped_for_budget, "warnings": self.warnings}


CARD_HEADER = (
    "# Conventions card\n\n"
    "Rules this codebase follows in the areas the change touches. `documented` rules are quoted from the project "
    "docs (full text in the Project profile). `inferred-from-code` rules were extracted from existing code in these "
    "areas; each cites where the pattern is followed, and the cited lines are verified to exist.")


def render_card(rules: list[Rule]) -> str:
    parts = [CARD_HEADER]
    by_area: dict[tuple[str, str], list[Rule]] = defaultdict(list)
    for r in rules:
        by_area[("Documented" if r.tag == "documented" else f"{r.area or '(repo root)'}/", r.tag)].append(r)
    for (title, tag), group in by_area.items():
        lines = [f"## {title} ({tag})"]
        for r in group:
            lines.append(f"- {r.text} (source: {r.area})" if r.tag == "documented"
                         else f"- [{r.topic}] {r.text} (evidence: {', '.join(r.evidence)})")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def build_conventions(llm: LLMClient, model: str, files: list[FileDiff], profile: Profile,
                      related: RelatedContext) -> ConventionsCard:
    started = time.monotonic()
    card = ConventionsCard()
    try:
        documented = documented_rules(profile, [f.path for f in files])
        areas, skipped = select_areas(files, related)
        card.areas += skipped
        with ThreadPoolExecutor(max_workers=max(1, len(areas))) as pool:
            results = list(pool.map(lambda a: _infer(llm, model, a), areas))
        inferred: list[Rule] = []
        for rules, row, warning in results:
            card.areas.append(row)
            inferred += rules
            if warning:
                card.warnings.append(warning)
        card.rules, card.dropped_for_budget = fit_card(documented, _dedupe(inferred))
    except Exception as e:  # noqa: BLE001 - the card is an optional input; the review goes on without it
        log.warning("conventions card unavailable: %s", e)
        log.debug("conventions failure", exc_info=True)
        card.warnings.append(f"conventions card unavailable: {e}")
    card.duration_s = round(time.monotonic() - started, 2)
    log.info("conventions card: %d rules (%d documented), %d tokens, %.1fs", len(card.rules),
             sum(r.tag == "documented" for r in card.rules), card.tokens, card.duration_s)
    return card


# --- areas and their evidence -------------------------------------------------------------------


def select_areas(files: list[FileDiff], related: RelatedContext) -> tuple[list[Area], list[dict]]:
    """Changed files grouped by directory, biggest change first; only areas with sibling code to learn from."""
    groups: dict[str, list[FileDiff]] = defaultdict(list)
    for f in files:
        if f.status != "deleted":
            groups[posixpath.dirname(f.path)].append(f)
    ranked = sorted(groups.items(), key=lambda kv: -sum(f.added + f.removed for f in kv[1]))
    areas, skipped = [], []
    for name, group in ranked:
        changed = [f.path for f in group]
        if not any(related.siblings.get(p) for p in changed):
            skipped.append({"area": name, "changed_files": changed, "status": "skipped: no sibling code found"})
            continue
        if len(areas) >= MAX_AREAS:
            skipped.append({"area": name, "changed_files": changed, "status": f"skipped: over {MAX_AREAS} areas"})
            continue
        symbols = [s for s in related.symbols if any(s.endswith(f" in {p}") for p in changed)]
        area = Area(name, changed, symbols)
        _collect_evidence(area, related, {f.path for f in files})
        if area.tokens >= MIN_AREA_EVIDENCE_TOKENS:
            areas.append(area)
        else:
            skipped.append({"area": name, "changed_files": changed, "evidence": area.sources,
                            "status": f"skipped: under {MIN_AREA_EVIDENCE_TOKENS} tokens of sibling code"})
    return areas, skipped


def _collect_evidence(area: Area, related: RelatedContext, changed: set[str]) -> None:
    """Sibling files (whole when short) and peer snippets, best first, within AREA_BUDGET_TOKENS.

    Changed files contribute only the graph's snippets of their unchanged peers, never the change.
    """
    snippets = sorted((s for p in area.changed for s in related.siblings.get(p, [])), key=lambda s: -s.score)
    by_file: dict[str, list] = defaultdict(list)
    for s in snippets:
        by_file[s.path].append(s)
    used = 0
    for path in list(by_file)[:MAX_FILES_PER_AREA]:
        src = related.source_of(path) if related.source_of else None
        if src is None or not src.lines:
            continue
        options = [_union([r for s in by_file[path] for r in s.ranges])]
        if path not in changed and len(src.lines) <= WHOLE_FILE_LINES:
            options.insert(0, [(1, len(src.lines))])
        reasons = list(dict.fromkeys(s.reason for s in by_file[path]))[:2]
        for ranges in options:
            ranges = [(max(1, a), min(len(src.lines), b)) for a, b in ranges if a <= len(src.lines)]
            block = (f"<code file={quoteattr(path)} lines={quoteattr(format_ranges(ranges))} "
                     f"why={quoteattr('; '.join(reasons))}>\n{render_lines(src.lines, ranges)}\n</code>")
            if used + estimate_tokens(block) <= AREA_BUDGET_TOKENS:
                used += estimate_tokens(block)
                area.blocks.append(block)
                area.sources.append(f"{path}:{format_ranges(ranges)}")
                shown = area.shown.setdefault(path, {})
                for a, b in ranges:
                    shown.update({n: src.lines[n - 1] for n in range(a, b + 1)})
                break


def _union(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


# --- inference and verification -----------------------------------------------------------------


def _infer(llm: LLMClient, model: str, area: Area) -> tuple[list[Rule], dict, str | None]:
    started = time.monotonic()
    row: dict = {"area": area.name, "changed_files": area.changed, "evidence": area.sources,
                 "evidence_tokens": area.tokens}
    try:
        submission = llm.call_tool(model, [
            {"role": "system", "content": prompts.get("conventions_system")},
            {"role": "user", "content": _area_message(area)},
        ], "submit_conventions", "Submit the conventions this code follows, each with cited evidence.",
            RuleSubmission, max_tokens=3000)
    except Exception as e:  # noqa: BLE001 - one area failing must not take the card down
        row.update(status=f"failed: {e}", duration_s=round(time.monotonic() - started, 2))
        return [], row, f"conventions for {area.name or '(root)'}/ unavailable: {e}"
    rules, dropped = verify_rules(submission.rules, area)
    row.update(status="ok", proposed=len(submission.rules), kept=len(rules), dropped=dropped,
               duration_s=round(time.monotonic() - started, 2))
    return rules, row, None


def _area_message(area: Area) -> str:
    changed = "\n".join(f"- {p}" for p in area.changed)
    symbols = "\n".join(f"- {s}" for s in area.symbols[:12]) or "- (none detected)"
    return (f"# Area: {area.name or '(repository root)'}/\n\n"
            f"A merge request changes these files:\n{changed}\n\nChanged symbols:\n{symbols}\n\n"
            "Existing code in and around this area follows (the change itself is not shown). "
            "The left column is the line number.\n\n" + "\n\n".join(area.blocks))


def verify_rules(proposed: list[ProposedRule], area: Area) -> tuple[list[Rule], list[dict]]:
    """Keep rules with at least one citation whose quote is found at (or near) the cited line of shown code."""
    kept, dropped = [], []
    for p in proposed[:MAX_RULES_PER_AREA * 2]:
        refs = list(dict.fromkeys(ref for c in p.evidence if (ref := verify_citation(c, area.shown))))
        text = " ".join(p.rule.split())
        if not text:
            continue
        if not refs:
            dropped.append({"rule": text, "why": "no citation found in the shown code",
                            "cited": [f"{c.file}:{c.line}" for c in p.evidence]})
            continue
        if len(kept) < MAX_RULES_PER_AREA:
            kept.append(Rule("inferred-from-code", area.name, p.topic, text, refs[:MAX_EVIDENCE]))
    return kept, dropped


def verify_citation(c: Citation, shown: dict[str, dict[int, str]]) -> str | None:
    """`path:line` where the quote really is: the cited line or one near it, else its first occurrence in the file.

    None when the file was not shown or the quote does not occur in the shown lines.
    """
    path = c.file.strip().removeprefix("./")
    lines = shown.get(path)
    parts = [p for p in (_norm(x) for x in re.split(r"\.\.\.|…", c.quote)) if p]
    if not lines or not parts or sum(map(len, parts)) < 3:
        return None

    def found_at(n: int, span: int) -> bool:  # the quote starts on line n and may wrap onto the next ones
        window = " ".join(_norm(lines[k]) for k in range(n, n + span) if k in lines)
        return n in lines and all(p in window for p in parts)

    near = range(c.line - QUOTE_WINDOW, c.line + QUOTE_WINDOW + 1)
    for span in (1, 3):  # single-line matches first; near the cited line, then anywhere in the shown code
        for candidates in (near, sorted(lines)):
            hits = [n for n in candidates if found_at(n, span)]
            if hits:
                return f"{path}:{min(hits, key=lambda n: abs(n - c.line))}"
    return None


def _norm(text: str) -> str:
    return " ".join(text.strip().strip("`").split())


def _dedupe(rules: list[Rule]) -> list[Rule]:
    seen: dict[str, Rule] = {}
    for r in rules:
        key = re.sub(r"\W+", " ", r.text.lower()).strip()
        if key in seen:
            seen[key].evidence = list(dict.fromkeys(seen[key].evidence + r.evidence))[:MAX_EVIDENCE]
        else:
            seen[key] = r
    return list(seen.values())


# --- documented rules and the budget ------------------------------------------------------------


def documented_rules(profile: Profile, changed: list[str]) -> list[Rule]:
    """Rule-like bullets about code in the profile's doc sections, those mentioning the changed paths first."""
    terms = path_terms(changed)
    term_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, terms))) + r")", re.I) if terms else None
    found: list[tuple[int, int, Rule]] = []
    for item in profile.included:
        if item.kind != "doc":
            continue
        for text in _bullets(item.text):
            if not DOC_RULE_RE.search(text) or PROCESS_RE.search(text):
                continue
            text = text if len(text) <= 220 else text[:217].rsplit(" ", 1)[0] + "…"
            relevant = 0 if term_re and term_re.search(text) else 1
            found.append((relevant, item.priority, Rule("documented", item.source, "documented", text,
                                                         [item.source])))
    found.sort(key=lambda t: t[:2])
    return [r for _, _, r in found[:MAX_DOC_RULES]]


def _bullets(markdown: str) -> list[str]:
    """Bullet items outside code fences, with their wrapped continuation lines joined."""
    items: list[str] = []
    current: list[str] | None = None
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence, current = not in_fence, None
            continue
        if in_fence:
            continue
        if m := BULLET_RE.match(line):
            current = [m[1].strip()]
            items.append("")
        elif current is not None and line.strip() and not line.lstrip().startswith(("#", "|", ">")):
            current.append(line.strip())
        else:
            current = None
            continue
        items[-1] = " ".join(current)
    return items


def fit_card(documented: list[Rule], inferred: list[Rule]) -> tuple[list[Rule], int]:
    """Inferred rules first (they exist nowhere else in the prompt), then documented ones, within the budget."""
    kept: list[Rule] = []
    dropped = 0
    for rule in [*inferred, *documented]:
        if estimate_tokens(render_card([*kept, rule])) <= CARD_BUDGET_TOKENS:
            kept.append(rule)
        else:
            dropped += 1
    return [r for r in kept if r.tag == "documented"] + [r for r in kept if r.tag != "documented"], dropped
