"""Lint and format configs: the rules tooling already enforces.

The reviewer can cite them as project rules, and knows not to repeat what a linter
in CI will catch anyway. Small configs are included raw; large ones (checkstyle,
PMD, pylintrc, big eslint configs) are reduced to rule names and key values.
"""

import logging
import posixpath
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from nitless.context.base import (
    ContextItem,
    cap_lines,
    estimate_tokens,
    parent_dir,
    project_scope,
    read_text,
    scope_reason,
    truncate,
)
from nitless.context.manifests import flatten, ini_lines

log = logging.getLogger(__name__)

RAW_TOKENS = 500
MAX_LINES = 40
MAX_XML_CONFIGS = 4

ESLINT_RE = re.compile(r"^(\.eslintrc(\.(js|cjs|mjs|json|ya?ml))?|eslint\.config\.[cm]?[jt]s)$")
RAW_RE = re.compile(r"^(\.prettierrc(\.\w+)?|prettier\.config\.[cm]?[jt]s|\.editorconfig|biome\.jsonc?|"
                    r"\.stylelintrc(\.\w+)?|stylelint\.config\.[cm]?js|\.markdownlint(\.\w+)?)$")
TOML_NAMES = {"ruff.toml", ".ruff.toml"}
INI_NAMES = {".flake8", "mypy.ini", ".mypy.ini", "tox.ini", ".pylintrc", "pylintrc", ".isort.cfg"}
XML_RE = re.compile(r"^(checkstyle|.*pmd|pmd.*|ruleset|spotbugs|findbugs).*\.xml$", re.I)
ESLINT_RULE_RE = re.compile(r"""['"]?([@\w/-]+)['"]?\s*:\s*\[?\s*['"]?(error|warn|off|[012])\b""")


def lint_items(repo: Path, files: list[str], changed: list[str]) -> list[ContextItem]:
    items = []
    xml_configs = 0
    project_of = project_scope(files, changed)
    for path in files:
        name = posixpath.basename(path)
        if XML_RE.match(name):  # usually kept in config/ dirs away from the code, and referenced from the build
            if xml_configs >= MAX_XML_CONFIGS or (project := project_of(path)) is None:
                continue
            xml_configs += 1
            reason, priority = f"static-analysis ruleset of {f'{project}/' if project else 'the repo'}", 46
        elif ESLINT_RE.match(name) or RAW_RE.match(name) or name in TOML_NAMES | INI_NAMES \
                or name == ".pre-commit-config.yaml":
            reason = scope_reason(f"lint/format config {name}", parent_dir(path), changed)
            if reason is None:
                continue
            priority = 45
        else:
            continue
        text = read_text(repo, path)
        if not text or not text.strip():
            continue
        try:
            summary = _summarize(name, text)
        except Exception as e:  # malformed files in an unknown repo must never fail the review
            log.debug("cannot parse %s: %s", path, e)
            summary = None
        if summary is None:
            summary = truncate(text.strip(), RAW_TOKENS)
        items.append(ContextItem("lint_config", path, reason, summary, priority))
    return items


def _summarize(name: str, text: str) -> str | None:
    """A compact rule list, or None to include the (truncated) raw file."""
    if XML_RE.match(name):
        return _xml_rules(text)
    if name == ".pre-commit-config.yaml":
        hooks = re.findall(r"^\s*-\s*id:\s*([\w.-]+)", text, re.M)
        return f"pre-commit hooks: {', '.join(hooks)}" if hooks else None
    if estimate_tokens(text) <= RAW_TOKENS:
        return text.strip()
    if name in TOML_NAMES:
        return "\n".join(cap_lines(flatten(tomllib.loads(text)), MAX_LINES))
    if name in INI_NAMES:
        sections = ("flake8", "mypy", "pytest", "isort", "pycodestyle") if name == "tox.ini" else None
        return "\n".join(cap_lines(ini_lines(text, sections), MAX_LINES)) or None
    if ESLINT_RE.match(name):
        rules = [f"{rule}: {level}" for rule, level in ESLINT_RULE_RE.findall(text)]
        extends = re.findall(r"""(?:extends|configs)[\w.]*\s*[:(]?\s*\[?\s*['"]([^'"]+)""", text)
        lines = ([f"extends: {', '.join(dict.fromkeys(extends))}"] if extends else []) + cap_lines(rules, MAX_LINES)
        return "\n".join(lines) or None
    return None


def _xml_rules(text: str) -> str | None:
    """checkstyle modules with their properties, PMD rule refs, SpotBugs filter matches."""
    root = ET.fromstring(text)
    rules = []
    for el in root.iter():
        tag = el.tag.rpartition("}")[2]
        props = [f"{p.get('name')}={p.get('value')}" for p in el if p.tag.rpartition("}")[2] == "property"]
        if tag == "module" and (el.get("name") not in ("Checker", "TreeWalker") or props):
            rules.append(f"{el.get('name')}({', '.join(props)})" if props else str(el.get("name")))
        elif tag == "rule" and (ref := el.get("ref") or el.get("name")):
            excluded = [e.get("name") for e in el if e.tag.rpartition("}")[2] == "exclude"]
            ref = ref.removeprefix("category/").replace(".xml/", "/")
            rules.append(ref + (f" (except {', '.join(map(str, excluded))})" if excluded else ""))
        elif tag in ("Bug", "Class", "Package", "Source", "Method") and el.attrib:
            rules.append(f"{tag}[{' '.join(f'{k}={v}' for k, v in el.attrib.items())}]")
    return "rules: " + ", ".join(rules) if rules else None
