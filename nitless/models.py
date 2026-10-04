"""Public data model: the change under review and the review result (the JSON output schema)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

Severity = Literal["critical", "major", "minor", "info"]
SEVERITY_ORDER: dict[str, int] = {"critical": 3, "major": 2, "minor": 1, "info": 0}

Category = Literal[
    "correctness",
    "security",
    "performance",
    "reliability",
    "api-contract",
    "convention",
    "test-coverage",
    "requirements",
]
CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]


class ChangeRequest(BaseModel):
    """A merge request (or a local base..head range) resolved to concrete commits."""

    provider: str
    repo: str
    ref: str
    title: str
    description: str = ""
    author: str | None = None
    web_url: str | None = None
    source_branch: str | None = None
    target_branch: str | None = None
    base_sha: str
    start_sha: str
    head_sha: str


class Evidence(BaseModel):
    kind: str = Field(description="What the evidence is, e.g. 'caller', 'sibling', 'doc', 'diff'")
    ref: str = Field(description="Where it is, e.g. 'src/api/users.py:42' or 'CONTRIBUTING.md#errors'")
    note: str | None = None


class Finding(BaseModel):
    id: str
    file: str
    line_start: int
    line_end: int
    severity: Severity
    category: Category
    message: str
    rationale: str
    suggestion: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class Counts(BaseModel):
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)


class Summary(BaseModel):
    assessment: str
    verdict: Literal["no_issues", "minor_issues", "needs_changes"]
    counts: Counts


class ModelUsage(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class RunMeta(BaseModel):
    tool_version: str
    repo: str | None = None
    mr: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    models: dict[str, str]
    started_at: datetime
    duration_s: float | None = None
    usage: dict[str, ModelUsage] = Field(default_factory=dict)
    cost_usd: float | None = Field(default=None, description="the run's cost at list prices (USD); null when a "
                                   "model used has no known price")


class ErrorInfo(BaseModel):
    kind: str
    message: str


IntentKind = Literal["explicit", "repo", "mr"]  # TASK_SOURCE, a story file in the repo, the MR description
CriterionStatus = Literal["met", "partially_met", "not_met", "cannot_determine"]


class Criterion(BaseModel):
    id: str = Field(description="'AC1', 'AC2', ... in task order; 'intent' when the task has no criteria")
    text: str
    status: CriterionStatus
    evidence: str = Field(description="file:line in the diff that implements it, or what is missing")


class Requirements(BaseModel):
    """Does the change do what the task asked? Present only when a task with an intent or criteria was found."""

    source: str = Field(description="where the task came from: a path, URL, 'story.json' or 'merge request'")
    kind: IntentKind
    does_what_was_asked: Literal["yes", "partially", "no", "unknown"]
    verdict: str = Field(description="one sentence")
    criteria: list[Criterion] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list, description="what the task excludes, as stated there")
    scope_creep: list[str] = Field(default_factory=list, description="notable changes beyond the task")


class ReviewResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    status: Literal["ok", "partial", "error"]
    run: RunMeta
    summary: Summary | None = None
    requirements: Requirements | None = None
    findings: list[Finding] = Field(default_factory=list)
    skipped_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    context_trace: dict = Field(default_factory=dict)
    state: Any = Field(default=None, exclude=True)  # nitless.incremental.ReviewState, kept by posting adapters
