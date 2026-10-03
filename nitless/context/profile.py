"""The Project Profile: deterministic repository context shared by every reviewer call."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pathspec

from nitless.context.base import ContextItem
from nitless.context.docs import doc_items
from nitless.context.lint import lint_items
from nitless.context.manifests import manifest_items
from nitless.context.repo_map import build_repo_map, list_files

log = logging.getLogger(__name__)

ALWAYS_INCLUDED = ("repo_map", "manifest")


@dataclass
class Profile:
    included: list[ContextItem]
    dropped: list[ContextItem]  # did not fit the token budget
    skipped: list[ContextItem] = field(default_factory=list)  # considered and deliberately left out

    @property
    def tokens(self) -> int:
        return sum(item.tokens for item in self.included)

    def render(self) -> str:
        """Every item wrapped with its source so findings can cite it."""
        parts = ["# Project profile\n\nRepository context selected for this change. When a finding relies on it, "
                 "cite the item's source."]
        for item in self.included:
            parts.append(f"<context kind={quoteattr(item.kind)} source={quoteattr(item.source)}>\n"
                         f"{item.text}\n</context>")
        return "\n\n".join(parts)

    def trace(self) -> list[dict]:
        rows = []
        for status, items in (("included", self.included), ("dropped", self.dropped), ("skipped", self.skipped)):
            for item in items:
                rows.append({"kind": item.kind, "source": item.source, "reason": item.reason,
                             "tokens": item.tokens, "included": status == "included", "status": status})
        return rows


def build_profile(repo: Path, changed_paths: list[str], excludes: list[str], budget_tokens: int = 12000) -> Profile:
    files = list_files(repo, excludes)
    spec = pathspec.PathSpec.from_lines("gitignore", excludes)
    changed = [p for p in changed_paths if not spec.match_file(p)]
    docs, skipped = doc_items(repo, files, changed)
    items = [
        build_repo_map(files, changed),
        *manifest_items(repo, files, changed),
        *docs,
        *lint_items(repo, files, changed),
    ]
    return fit_budget(items, budget_tokens, skipped)


def fit_budget(items: list[ContextItem], budget_tokens: int, skipped: list[ContextItem] | None = None) -> Profile:
    """Greedy by priority; the result keeps discovery order so each document's sections stay together."""
    used = sum(item.tokens for item in items if item.kind in ALWAYS_INCLUDED)
    chosen = {id(item) for item in items if item.kind in ALWAYS_INCLUDED}
    for item in sorted(items, key=lambda it: it.priority):  # stable: ties keep document order
        if id(item) not in chosen and used + item.tokens <= budget_tokens:
            chosen.add(id(item))
            used += item.tokens
    included = [item for item in items if id(item) in chosen]
    dropped = [item for item in items if id(item) not in chosen]
    log.info("project profile: %d items, %d tokens (%d dropped over the %d-token budget)",
             len(included), used, len(dropped), budget_tokens)
    return Profile(included, dropped, skipped or [])
