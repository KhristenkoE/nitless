"""Documentation that states the project's rules, selected per change.

Discovery, most important first: agent instruction files (AGENTS.md, CLAUDE.md,
Cursor/Copilot rules) at the root and on changed paths, contributor and style
guides, ADRs, READMEs and ARCHITECTURE docs, MR templates.

Small docs are included whole. Large ones are split by headings and only the
intro, rule-ish sections and sections that mention the changed code are kept;
every kept section says why, and skipped ones are summarised in the trace.
"""

import posixpath
import re
from collections import Counter
from dataclasses import dataclass
from itertools import takewhile
from pathlib import Path

import pathspec

from nitless.context.base import (
    ContextItem,
    estimate_tokens,
    nearest,
    parent_dir,
    project_scope,
    read_text,
    scope_reason,
    truncate,
)
from nitless.context.repo_map import CODE_EXTS

WHOLE_DOC_TOKENS = 1500
SECTION_TOKENS = 1200
INTRO_TOKENS = 400
DOC_TOKENS = 3000  # at most this much of one large document
ADR_SHORT_TOKENS = 700
ADR_FULL_MAX = 5  # relevant ADRs included in full
ADR_ALL_SHORT_MAX = 10  # below this many ADRs, every short one is included
ADR_INDEX_MIN = 4  # from this many ADRs on, an index of titles/status is added

DOC_EXT = r"(\.(md|mdx|mdc|markdown|rst|txt|adoc))?"
RULES_DIR_RE = re.compile(r"^(?:(.*)/)?(\.cursor/rules/.+|\.github/copilot-instructions\.md|\.github/instructions/.+)$")
AGENT_NAMES = {"agents.md", "claude.md", "gemini.md", ".cursorrules", ".windsurfrules"}
GUIDE_RE = re.compile(
    rf"^(contributing|contribute|style[-_ ]?guide|code[-_ ]?style|coding[-_ ]?(guidelines|standards|conventions|style)"
    rf"|conventions|guidelines|development|developing|hacking){DOC_EXT}$", re.I)
DOCS_GUIDE_RE = re.compile(rf"(^|/)docs?/(.+/)?(contributing|style|conventions|guidelines|coding)[^/]*{DOC_EXT}$", re.I)
ADR_RE = re.compile(r"(^|/)(adrs?|decisions|decision-records|architecture-decisions)/.+\.(md|rst|txt|adoc)$", re.I)
README_RE = re.compile(rf"^readme{DOC_EXT}$", re.I)
ARCH_RE = re.compile(rf"^architecture{DOC_EXT}$", re.I)
TEMPLATE_RE = re.compile(r"^(\.github/(pull_request_template\.md|PULL_REQUEST_TEMPLATE/.+)|"
                         r"\.gitlab/merge_request_templates/.+|docs/pull_request_template\.md)$", re.I)

# headings that state rules; STRONG ones also cover their subsections ("Coding conventions > Imports")
STRONG_RULE_RE = re.compile(
    r"\b(conventions?|style|guidelines?|rules?|standards?|(best )?practices?|principles?|naming|dos|don'?ts?|don’t"
    r"|avoid|never|must|contribut\w*|review\w*|coding|pull requests?|merge requests?|architecture|structure|layout)\b",
    re.I)
WEAK_RULE_RE = re.compile(
    r"\b(errors?|exceptions?|test\w*|security|auth\w*|design|apis?|endpoints?|database|db|migrations?"
    r"|schemas?|models?|logging|observability|patterns?|workflow|commits?|lint\w*|format\w*|typ(es?|ing)"
    r"|domain|dependenc\w*|performance|concurren\w*|transactions?|validat\w*|accessib\w*|i18n)\b", re.I)
BOILERPLATE_RE = re.compile(
    r"\b(licen[cs]e\w*|install\w*|getting started|quick ?start|badges?|changelog|change log|release notes"
    r"|acknowledg\w*|credits?|contact|support|sponsor\w*|authors?|maintainers?|contents|toc|roadmap|donat\w*"
    r"|citation|code of conduct|community|screenshots?|demo|faq|thanks|funding|contributors|troubleshoot\w*"
    r"|browser support)\b", re.I)
# path words that say nothing about the domain: layout dirs and architectural layers
STOP_TERMS = (
    "src", "main", "java", "kotlin", "test", "spec", "com", "org", "net", "lib", "app", "index", "init", "package",
    "internal", "pkg", "impl", "util", "common", "core", "resource", "public", "static", "script", "source", "module",
    "file", "base", "service", "controller", "repositor", "model", "schema", "handler", "component", "page", "view",
    "route", "middleware", "entity", "config", "server", "client", "helper", "hook", "type", "constant", "error",
    "exception", "action", "reducer", "selector", "store", "style", "mock", "fixture", "feature", "setting", "form",
    "root", "snapshot", "story", "stories", "default", "shared", "dto", "api",
)
ATX_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SETEXT_RE = re.compile(r"^\s*(={3,}|-{3,}|~{3,}|\^{3,}|\*{3,})\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
GLOBS_RE = re.compile(r"^(globs|applyTo)[ \t]*:[ \t]*(.*)$", re.M)
ALWAYS_RE = re.compile(r"^alwaysApply\s*:\s*true\b", re.M | re.I)
STATUS_RE = re.compile(r"^(?:#+\s*status\s*|[\W_]*status[\W_]*:[\W_]*(\w.*))$", re.I | re.M)


@dataclass
class Section:
    headings: tuple[str, ...]  # heading path; empty for text before the first heading
    text: str  # includes its own heading line
    has_body: bool


def doc_items(repo: Path, files: list[str], changed: list[str]) -> tuple[list[ContextItem], list[ContextItem]]:
    """(selected items, skipped-for-a-reason items for the trace)."""
    terms = path_terms(changed)
    items: list[ContextItem] = []
    skipped: list[ContextItem] = []
    seen: set[str] = set()

    def add(path: str, reason: str, priority: int, text: str | None = None) -> None:
        seen.add(path)
        text = text if text is not None else read_text(repo, path)
        if text and text.strip():
            kept, dropped = select_sections(path, text, reason, priority, terms)
            items.extend(kept)
            skipped.extend(dropped)

    for path in files:  # 1. agent / AI assistant instructions
        if (found := _agent_scope(repo, path, changed)) is not None:
            reason, priority, text = found
            if priority is None:
                skipped.append(ContextItem("doc", path, reason, "", 100))
            else:
                add(path, reason, priority, text)

    project_of = project_scope(files, changed)
    for path in files:  # 2. contributor and style guides
        name, folder = posixpath.basename(path), parent_dir(path)
        if path in seen or (project := project_of(path)) is None:
            continue
        where = f"of {project}/" if project else "at repo level"
        if GUIDE_RE.match(name) and _relative(folder, project) in ("", ".github", ".gitlab", "docs", "doc"):
            add(path, f"contributor/style guide {where}", 20)
        elif GUIDE_RE.match(name) and (reason := scope_reason(f"guide {name}", folder, changed)):
            add(path, reason, 20)
        elif DOCS_GUIDE_RE.search(path):
            add(path, f"style/conventions doc {where}", 22)

    adrs = [p for p in files if ADR_RE.search(p) and p not in seen and project_of(p) is not None
            and not re.search(r"template|^readme|^index", posixpath.basename(p), re.I)]
    items += _adr_items(repo, adrs, terms)
    seen.update(adrs)

    for path in files:  # 4. READMEs and architecture overviews on the changed paths
        name, folder = posixpath.basename(path), parent_dir(path)
        if path in seen:
            continue
        if README_RE.match(name) and (reason := scope_reason("README", folder, changed)):
            add(path, reason, 41 if folder else 40)
        elif ARCH_RE.match(name) and (project := project_of(path)) is not None and (
                _relative(folder, project) in ("", "docs", "doc") or nearest(folder, changed)):
            add(path, f"architecture overview {f'of {project}/' if project else 'of the repo'}", 35)
        elif TEMPLATE_RE.match(path):
            add(path, "merge request template: what the team expects an MR to state", 60)
    return items, skipped


def _relative(folder: str, project: str) -> str:
    rel = posixpath.relpath(folder or ".", project or ".")
    return "" if rel == "." else rel


def _agent_scope(repo: Path, path: str, changed: list[str]) -> tuple[str, int | None, str | None] | None:
    """(reason, priority or None if out of scope, text) for agent instruction files; None for other files."""
    name = posixpath.basename(path)
    if name.lower() in AGENT_NAMES:
        scope = parent_dir(path)
    elif m := RULES_DIR_RE.match(path):
        scope = m[1] or ""
    else:
        return None
    reason = scope_reason(name, scope, changed)
    if reason is None:
        return f"{name} scoped to {scope}/, which has no changed files", None, None
    text = read_text(repo, path) or ""
    meta, _ = split_front_matter(text)
    if (globs := _globs(meta)) and not ALWAYS_RE.search(meta):
        spec = pathspec.PathSpec.from_lines("gitignore", globs)
        matched = [p for p in changed if spec.match_file(p)]
        if not matched:
            return f"rule globs {globs} match no changed file", None, None
        reason += f"; globs {globs} match {matched[0]}"
    hit = nearest(scope, changed)
    return f"AI/agent instructions: {reason}", 10 + min(hit[0] if hit else 0, 9), text


def _globs(meta: str) -> list[str]:
    m = GLOBS_RE.search(meta)
    if not m:
        return []
    value = m[2].strip()
    if not value:  # YAML list on the following lines
        rest = meta[m.end():].strip("\n").splitlines()
        value = ",".join(ln.strip()[1:] for ln in takewhile(lambda ln: ln.strip().startswith("-"), rest))
    return [g.strip(" \"'[]") for g in value.split(",") if g.strip(" \"'[]")]


def split_front_matter(text: str) -> tuple[str, str]:
    if text.startswith("---\n") and (end := text.find("\n---", 4)) != -1:
        return text[4:end], text[end + 4:].lstrip("-\n")
    return "", text


def split_sections(text: str) -> list[Section]:
    """Split markdown (ATX `#` or setext/rst underlined headings) into sections, ignoring code fences."""
    lines = text.splitlines()
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    start = body_start = 0
    in_fence = False

    def close(end: int) -> None:
        chunk = "\n".join(lines[start:end]).strip()
        if chunk:
            has_body = any(ln.strip() for ln in lines[body_start:end])
            sections.append(Section(tuple(title for _, title in stack), chunk, has_body))

    i = 0
    while i < len(lines):
        line = lines[i]
        if FENCE_RE.match(line):
            in_fence = not in_fence
        heading = None
        if not in_fence:
            if m := ATX_RE.match(line):
                heading = (len(m[1]), m[2], 1)
            elif (line.strip() and not line.startswith((" ", "\t", "|", "-", "*", ">"))
                  and i + 1 < len(lines) and SETEXT_RE.match(lines[i + 1])):
                heading = ({"=": 1, "-": 2}.get(lines[i + 1].strip()[0], 3), line.strip(), 2)
        if heading is None:
            i += 1
            continue
        close(i)
        level, title, size = heading
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, _clean_heading(title)))
        start, body_start = i, i + size
        i += size
    close(len(lines))
    return sections


def _clean_heading(title: str) -> str:
    """`## 🚀 [Web App](https://…) **API**` -> `Web App API`."""
    title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title).replace("**", "").replace("`", "")
    return re.sub(r"^[^\w(]+", "", title).strip() or title.strip()


def path_terms(changed: list[str]) -> set[str]:
    """Domain words from changed paths: `server/src/bookings/bookingService.ts` -> booking."""
    terms = set()
    for path in changed:
        if posixpath.splitext(path)[1].lower() not in CODE_EXTS:  # snapshots, images, lockfiles name nothing
            continue
        parts = path.split("/")
        parts[-1] = parts[-1].split(".")[0]
        for part in parts:
            for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+", part):
                word = word.lower()
                if len(word) >= 4 and not word.startswith(STOP_TERMS):
                    terms.add(word)
                    if word.endswith("ies"):
                        terms.add(word[:-3] + "y")
                    elif word.endswith("s") and not word.endswith("ss"):
                        terms.add(word[:-1])
    # "booking" already matches "bookings" as a word prefix
    return {t for t in terms if not any(u != t and t.startswith(u) for u in terms)}


def _term_hits(text: str, terms: set[str]) -> set[str]:
    if not terms:
        return set()
    pattern = re.compile(r"\b(" + "|".join(sorted(map(re.escape, terms))) + r")", re.I)
    return {m.lower() for m in pattern.findall(text)}


def select_sections(path: str, text: str, reason: str, priority: int,
                    terms: set[str]) -> tuple[list[ContextItem], list[ContextItem]]:
    _, body = split_front_matter(text)
    body = body.strip()
    if estimate_tokens(body) <= WHOLE_DOC_TOKENS:
        return [ContextItem("doc", path, reason, body, priority)], []

    sections = split_sections(body)
    if len(sections) <= 1:
        return [ContextItem("doc", path, f"{reason}; no headings, first {SECTION_TOKENS} tokens",
                            truncate(body, SECTION_TOKENS), priority)], []
    hits = [_term_hits(s.text, terms) for s in sections]
    common = _common_terms(hits)
    # a shared document title ("# Bookings API") is not part of any section's own heading path
    title = sections[0].headings[:1]
    if not all(s.headings[:1] == title for s in sections if s.headings):
        title = ()

    candidates: list[tuple[int, int, ContextItem]] = []  # (rank, doc order, item)
    boilerplate: list[str] = []
    irrelevant: list[str] = []
    for i, (section, found) in enumerate(zip(sections, hits, strict=True)):
        own = section.headings[len(title):]
        anchor = " > ".join(own) or "intro"
        if not section.has_body:
            continue
        found -= common
        strong = next((m[0] for h in own if (m := STRONG_RULE_RE.search(h))), None)
        weak = m[0] if own and (m := WEAK_RULE_RE.search(own[-1])) else None
        if i == 0:
            rank, whys, limit = 0, ["document intro"], INTRO_TOKENS
        elif any(BOILERPLATE_RE.search(h) for h in own):
            boilerplate.append(anchor)
            continue
        elif found or strong or weak:
            rank = 1 if found else 2 if strong else 3
            whys = [f"mentions {', '.join(sorted(found))} from changed paths"] if found else []
            whys += [f"heading matches rule keyword '{(strong or weak).lower()}'"] if strong or weak else []
            limit = SECTION_TOKENS
        else:
            irrelevant.append(anchor)
            continue
        section_text = truncate(section.text, limit)
        if section_text != section.text:
            whys.append(f"truncated to {limit} tokens")
        item = ContextItem("doc", f"{path}#{anchor}", f"{reason}; section {', '.join(whys)}", section_text,
                           priority + rank)
        candidates.append((rank, i, item))

    # per-document cap: intro, then sections about the changed code, then strong rules, then weak ones
    kept, over_cap, used = [], [], 0
    for _, i, item in sorted(candidates, key=lambda c: c[:2]):
        if used + item.tokens <= DOC_TOKENS:
            kept.append((i, item))
            used += item.tokens
        else:
            over_cap.append(item.source.partition("#")[2])
    skipped = []
    for label, anchors in (("skipped boilerplate", boilerplate),
                           ("skipped, no rule keyword or changed-path term", irrelevant),
                           (f"skipped, over the {DOC_TOKENS}-token per-document cap", over_cap)):
        if anchors:
            skipped.append(ContextItem("doc", f"{path} ({len(anchors)} sections)",
                                       f"{label}: {'; '.join(anchors[:15])}", "", 100))
    return [item for _, item in sorted(kept, key=lambda k: k[0])], skipped


def _common_terms(hits: list[set[str]]) -> set[str]:
    """Terms found in many sections (the project's own name, say) do not tell sections apart."""
    if len(hits) < 4:
        return set()
    counts = Counter(t for h in hits for t in h)
    return {t for t, n in counts.items() if n > max(2, len(hits) * 0.3)}


def _adr_items(repo: Path, adrs: list[str], terms: set[str]) -> list[ContextItem]:
    """An index of all ADRs when there are many, full text for relevant (or, in small sets, short) ones."""
    texts = {p: t for p in sorted(adrs) if (t := read_text(repo, p))}
    if not texts:
        return []
    hits = {p: _term_hits(t, terms) for p, t in texts.items()}
    common = _common_terms(list(hits.values()))
    hits = {p: h - common for p, h in hits.items()}

    items = []
    if len(texts) >= ADR_INDEX_MIN:
        index = [f"- {p}: {_adr_title(t, p)}" for p, t in texts.items()]
        items.append(ContextItem("doc", "ADR index", f"titles and status of all {len(texts)} ADRs",
                                 "\n".join(index[:80]) + (f"\n… {len(index) - 80} more" if len(index) > 80 else ""),
                                 30))
    relevant = sorted((p for p in texts if hits[p]), key=lambda p: -len(hits[p]))[:ADR_FULL_MAX]
    for path, text in texts.items():
        if path in relevant:
            reason = f"ADR mentions {', '.join(sorted(hits[path]))} from changed paths"
            items += select_sections(path, text, reason, 31, terms)[0]
        elif len(texts) <= ADR_ALL_SHORT_MAX and estimate_tokens(text) <= ADR_SHORT_TOKENS:
            items.append(ContextItem("doc", path, f"short ADR (one of {len(texts)})", text.strip(), 34))
    return items


def _adr_title(text: str, path: str) -> str:
    sections = split_sections(split_front_matter(text)[1])
    title = next((s.headings[0] for s in sections if s.headings), posixpath.basename(path))
    status = ""
    if m := STATUS_RE.search(text):
        status = m[1] or ""
        if not status:  # "## Status" heading: take the next non-empty line
            status = next((ln.strip() for ln in text[m.end():].splitlines() if ln.strip()), "")
    return f"{title} [{status.strip('*_ ')[:40]}]" if status else title
