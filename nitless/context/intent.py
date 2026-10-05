"""What the change is supposed to do: the task (story, issue, ticket) behind the merge request.

Sources, strongest first:
  explicit  TASK_SOURCE: a local .json/.yaml/.md/.txt file or an http(s) URL. A GitLab issue or work item URL
            (…/-/issues/<iid>, …/-/work_items/<iid>) is read through the API with GITLAB_TOKEN. Anything
            unreadable fails the run with TaskSourceError: a review against the wrong task is worse than none.
  repo      a story file the MR adds or changes, at the repo root or in a changed top-level directory
            (STORY_FILES). An unchanged one is ignored as likely stale; an unparsable one falls back to `mr`.
  mr        the MR title and description (weak intent). Only a description with a checklist, an
            "Acceptance criteria" or an out-of-scope section is sent to the model for extraction.

Structured data (JSON/YAML with title/intent/acceptance_criteria/out_of_scope or common aliases) maps
directly; free text goes to the fast model, whose criteria must be grounded in the source text.
"""

import json
import logging
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

import httpx
import yaml
from pydantic import BaseModel, Field, SecretStr

from nitless import prompts
from nitless.context.base import read_text
from nitless.errors import LLMError, TaskSourceError
from nitless.llm import LLMClient
from nitless.models import ChangeRequest, IntentKind

log = logging.getLogger(__name__)

STORY_FILES = ("story.json", "task.json", ".task.json", "story.md", "TASK.md")  # first match wins, root first
MAX_SOURCE_CHARS = 30_000
MIN_GROUNDING = 0.6  # share of an extracted item's words that must occur in the source text
GITLAB_WORK_ITEM_RE = re.compile(
    r"^(?P<base>https?://[^/]+)/(?P<project>.+?)/-/(?:issues|work_items)/(?P<iid>\d+)/?(?:[?#].*)?$")
# signals that free text (usually an MR description) states criteria or exclusions worth extracting
TASK_MARKERS_RE = re.compile(
    r"acceptance criteria|definition of done|\bACs?\b\s*[:\d]|^\s*[-*]\s+\[[ xX]\]|given .+ when .+ then"
    r"|out of scope|out-of-scope|non-goals?|not in scope|will follow|follow-?up|separate (?:mr|pr|ticket|story)",
    re.I | re.M)

KEYS = {  # normalized key (lowercase, alphanumerics only) -> field
    "id": "id", "key": "id", "iid": "id", "ticket": "id",
    "title": "title", "summary": "title", "name": "title",
    "intent": "intent", "description": "intent", "goal": "intent", "story": "intent", "userstory": "intent",
    "body": "intent", "details": "intent",
    "acceptancecriteria": "acceptance_criteria", "acceptance": "acceptance_criteria", "ac": "acceptance_criteria",
    "acs": "acceptance_criteria", "criteria": "acceptance_criteria", "definitionofdone": "acceptance_criteria",
    "outofscope": "out_of_scope", "nongoals": "out_of_scope", "notinscope": "out_of_scope",
    "exclusions": "out_of_scope",
}
ITEM_TEXT_KEYS = ("text", "description", "title", "name", "criterion", "value")
BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|[a-z]\)|AC\s?\d+[.):]?)?\s*(?:\[[ xX]\]\s*)?")


class Intent(BaseModel):
    source: str
    kind: IntentKind
    title: str = ""
    intent: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    raw: str = ""
    parsed_by: Literal["structured", "llm", "none"] = "none"
    path: str | None = None  # repo path of a story file, which is then not reviewed as code

    @property
    def assessable(self) -> bool:
        """Worth a requirements check: criteria to test, or at least a task stated outside the MR."""
        return bool(self.acceptance_criteria) or (self.kind != "mr" and bool(self.intent.strip()))

    def describe_source(self) -> str:
        return {"explicit": f"task source {self.source}", "repo": f"{self.source}, committed with the change",
                "mr": "the merge request description"}[self.kind]

    def render(self) -> str:
        """The task section of a prompt. For MR-derived intent only what was extracted (the MR is shown anyway)."""
        if self.kind == "mr" and not (self.acceptance_criteria or self.out_of_scope):
            return ""
        parts = [f"# Task\n\nFrom {self.describe_source()}."]
        if self.kind != "mr":
            parts.append(f"## {self.title or '(untitled)'}\n\n{self.intent.strip() or '(no intent stated)'}")
        if self.acceptance_criteria:
            parts.append("### Acceptance criteria\n" + "\n".join(
                f"- AC{i}: {ac}" for i, ac in enumerate(self.acceptance_criteria, 1)))
        if self.out_of_scope:
            parts.append("### Out of scope\nThe task explicitly excludes the following. Do not report any of it as "
                         "missing and do not ask for it:\n" + "\n".join(f"- {item}" for item in self.out_of_scope))
        return "\n\n".join(parts)

    def trace(self) -> dict:
        return {"source": self.source, "kind": self.kind, "parsed_by": self.parsed_by, "title": self.title,
                "acceptance_criteria": len(self.acceptance_criteria), "out_of_scope": len(self.out_of_scope),
                "raw_chars": len(self.raw)}


class TaskExtraction(BaseModel):
    """What the fast model returns for free-text tasks (the `submit_task` tool arguments)."""

    title: str = Field(default="", description="The task title, verbatim if the text has one")
    intent: str = Field(default="", description="1-3 sentences: what the change should achieve and why")
    acceptance_criteria: list[str] = Field(
        default_factory=list, description="Each criterion as written in the text; empty if the text states none")
    out_of_scope: list[str] = Field(
        default_factory=list, description="Each thing the text explicitly excludes or defers, as written")


@dataclass
class TaskDocument:
    """A task as read from its source, before it is parsed."""

    source: str
    kind: IntentKind
    text: str
    data: Any = None  # parsed JSON/YAML, when the source is structured
    path: str | None = None


# --- reading ------------------------------------------------------------------------------------


def load_task_source(value: str, gitlab_token: SecretStr | None = None, mr_url: str | None = None,
                     timeout_s: float = 30) -> TaskDocument:
    """Read an explicit TASK_SOURCE. Raises TaskSourceError when it cannot be read or is empty."""
    value = value.strip()
    if urlparse(value).scheme in ("http", "https"):
        doc = _fetch_url(value, gitlab_token, mr_url, timeout_s)
    else:
        doc = _read_file(Path(value).expanduser())
    if not doc.text.strip() and not doc.data:
        raise TaskSourceError(f"task source {value} is empty")
    return doc


def _read_file(path: Path) -> TaskDocument:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise TaskSourceError(f"task source file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise TaskSourceError(f"cannot read task source {path}: {e}") from None
    try:
        data = _parse_structured(text, path.suffix.lower())
    except ValueError as e:
        raise TaskSourceError(f"task source {path} is not valid {path.suffix[1:].upper()}: {e}") from None
    return TaskDocument(str(path), "explicit", text, data)


def _parse_structured(text: str, suffix: str) -> Any:
    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(str(e)) from None
    if suffix in (".yaml", ".yml"):
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError(str(e).splitlines()[0]) from None
    return None


def _fetch_url(url: str, gitlab_token: SecretStr | None, mr_url: str | None, timeout_s: float) -> TaskDocument:
    if m := GITLAB_WORK_ITEM_RE.match(url):
        return _fetch_gitlab_issue(url, m["base"], m["project"], int(m["iid"]), gitlab_token, mr_url, timeout_s)
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=timeout_s)
    except httpx.HTTPError as e:
        raise TaskSourceError(f"cannot fetch task source {url}: {e}") from None
    if resp.is_error:
        raise TaskSourceError(f"task source {url} returned HTTP {resp.status_code}")
    content_type = resp.headers.get("content-type", "")
    text = resp.text[:MAX_SOURCE_CHARS]
    if "json" in content_type:
        try:
            return TaskDocument(url, "explicit", text, resp.json())
        except ValueError:
            raise TaskSourceError(f"task source {url} is not valid JSON") from None
    if "html" in content_type:
        text = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", text, flags=re.S | re.I)
        text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()
    return TaskDocument(url, "explicit", text)


def _fetch_gitlab_issue(url: str, base: str, project: str, iid: int, token: SecretStr | None, mr_url: str | None,
                        timeout_s: float) -> TaskDocument:
    """An issue (work items of type issue share its iid) via the REST API.

    The token is only sent to the GitLab host of MR_URL (or to any host when reviewing a local repo).
    """
    mr_host = urlparse(mr_url).netloc if mr_url else None
    send_token = token is not None and (mr_host is None or mr_host == urlparse(base).netloc)
    headers = {"PRIVATE-TOKEN": token.get_secret_value()} if send_token and token else {}
    api = f"{base}/api/v4/projects/{quote(project, safe='')}/issues/{iid}"
    try:
        resp = httpx.get(api, headers=headers, timeout=timeout_s)
    except httpx.HTTPError as e:
        raise TaskSourceError(f"cannot reach GitLab for task source {url}: {e}") from None
    if resp.status_code in (401, 403, 404):
        hint = "" if headers else " (no GITLAB_TOKEN sent for this host)"
        raise TaskSourceError(f"GitLab issue {project}#{iid} not accessible ({resp.status_code}){hint}")
    if resp.is_error:
        raise TaskSourceError(f"GitLab API error {resp.status_code} for task source {url}")
    issue = resp.json()
    title, description = issue.get("title") or "", issue.get("description") or ""
    return TaskDocument(url, "explicit", f"# {title}\n\n{description}".strip()[:MAX_SOURCE_CHARS])


def find_story_file(repo: Path, changed: list[str]) -> TaskDocument | None:
    """A story file in the repo: at the root, then in the changed top-level dirs.

    One this change adds or modifies wins; otherwise an existing one is used, since the task may have
    been committed to the target branch before the MR.
    """
    changed_set = set(changed)
    tops = sorted({p.split("/", 1)[0] for p in changed if "/" in p}, key=lambda d: -sum(
        p.startswith(d + "/") for p in changed))
    candidates = [posixpath.join(folder, name) for folder in ["", *tops] for name in STORY_FILES]
    for path in sorted(candidates, key=lambda p: p not in changed_set):  # stable: changed ones first
        if not (repo / path).is_file() or (text := read_text(repo, path)) is None:
            continue
        try:
            data = _parse_structured(text, posixpath.splitext(path)[1])
        except ValueError as e:
            log.warning("ignoring story file %s: %s", path, e)
            continue
        if path not in changed_set:
            log.info("using %s from the repository (not changed by this MR)", path)
        return TaskDocument(path, "repo", text, data, path=path)
    return None


def mr_document(change: ChangeRequest) -> TaskDocument:
    return TaskDocument("merge request", "mr", f"# {change.title}\n\n{change.description}".strip())


# --- parsing ------------------------------------------------------------------------------------


def parse_intent(doc: TaskDocument, llm: LLMClient | None, model: str) -> Intent:
    """Normalize a task document. Free text goes to the fast model; MR text only if it has task markers.

    Extraction failures are fatal for an explicit source and degrade to the raw text otherwise.
    """
    base = Intent(source=doc.source, kind=doc.kind, raw=doc.text, path=doc.path)
    if isinstance(doc.data, dict) and (fields := _from_mapping(doc.data)):
        intent = base.model_copy(update={**fields, "parsed_by": "structured"})
        if intent.acceptance_criteria or not TASK_MARKERS_RE.search(intent.intent):
            return intent
        base, doc = intent, TaskDocument(doc.source, doc.kind, f"# {intent.title}\n\n{intent.intent}", path=doc.path)
    elif doc.data is not None:
        doc = TaskDocument(doc.source, doc.kind, yaml.safe_dump(doc.data, sort_keys=False), path=doc.path)

    title, _, rest = doc.text.removeprefix("# ").partition("\n")
    fallback = base.model_copy(update={"title": base.title or title.strip(), "intent": base.intent or rest.strip()})
    if doc.kind == "mr" and not TASK_MARKERS_RE.search(doc.text):
        return fallback
    if llm is None:
        return fallback
    try:
        extracted = extract(llm, model, doc)
    except LLMError as e:
        if doc.kind == "explicit":
            raise
        log.warning("task extraction from %s failed, using its text as the intent: %s", doc.source, e)
        return fallback
    grounded = {"acceptance_criteria": _grounded(extracted.acceptance_criteria, doc.text),
                "out_of_scope": _grounded(extracted.out_of_scope, doc.text)}
    return fallback.model_copy(update={
        "title": base.title or extracted.title.strip() or fallback.title,
        "intent": base.intent if base.parsed_by == "structured" else extracted.intent.strip() or fallback.intent,
        **grounded, "parsed_by": "llm"})


def extract(llm: LLMClient, model: str, doc: TaskDocument) -> TaskExtraction:
    where = "a merge request description" if doc.kind == "mr" else f"a task ({doc.source})"
    messages = [
        {"role": "system", "content": prompts.get("intent_system")},
        {"role": "user", "content": f"Extract the task from {where}:\n\n<text>\n{doc.text[:MAX_SOURCE_CHARS]}\n"
                                    "</text>"},
    ]
    return llm.call_tool(model, messages, "submit_task", "Submit the task's intent, criteria and exclusions.",
                         TaskExtraction, max_tokens=3000)


def _from_mapping(data: dict) -> dict | None:
    """Known task fields of a JSON/YAML object (Jira-style `fields` included), or None if there are none."""
    if isinstance(data.get("fields"), dict):
        data = {**data["fields"], **{k: v for k, v in data.items() if k != "fields"}}
    found: dict[str, Any] = {}
    for key, value in data.items():
        field = KEYS.get(re.sub(r"[^a-z0-9]", "", str(key).lower()))
        if field and field not in found and value not in (None, "", []):
            found[field] = value
    if not found.keys() & {"title", "intent", "acceptance_criteria"}:
        return None
    title = _text(found.get("title"))
    if (ticket := _text(found.get("id"))) and ticket not in title:
        title = f"{ticket}: {title}" if title else ticket
    return {"title": title, "intent": _text(found.get("intent")),
            "acceptance_criteria": _items(found.get("acceptance_criteria")),
            "out_of_scope": _items(found.get("out_of_scope"))}


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(_items(value))
    if isinstance(value, dict):
        return next((str(value[k]).strip() for k in ITEM_TEXT_KEYS if value.get(k)), "")
    return "" if value is None else str(value).strip()


def _items(value: Any) -> list[str]:
    """A list of criteria from a list (of strings or objects) or a bulleted/numbered string."""
    if value is None:
        return []
    if isinstance(value, str):
        return [line for raw in value.splitlines() if (line := BULLET_RE.sub("", raw, count=1).strip())]
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        return [str(value)]
    return [text for item in value if (text := _text(item))]


def _grounded(items: list[str], source: str) -> list[str]:
    """Drop extracted items whose words mostly do not occur in the source: criteria are copied, never invented."""
    words = set(re.findall(r"\w{3,}", source.lower()))
    kept = []
    for item in (i.strip() for i in items):
        own = re.findall(r"\w{3,}", item.lower())
        if own and sum(w in words for w in own) / len(own) >= MIN_GROUNDING:
            kept.append(item)
        elif item:
            log.info("dropping extracted task item not grounded in the source: %s", item[:120])
    return kept
