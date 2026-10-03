"""What reviewer models must return (the `submit_review` tool arguments)."""

from pydantic import BaseModel, Field

from nitless.models import Category, Evidence, Severity


class CandidateFinding(BaseModel):
    file: str = Field(description="Path of the changed file, exactly as in the diff header")
    line_start: int = Field(description="First new-file line number the finding refers to")
    line_end: int | None = Field(default=None, description="Last line number, if it spans several lines")
    severity: Severity
    category: Category
    message: str = Field(description="One sentence stating the defect")
    rationale: str = Field(description="Why it matters in this project: what breaks, for whom, when")
    suggestion: str | None = Field(default=None, description="Concrete fix, if clear")
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ReviewSubmission(BaseModel):
    assessment: str = Field(description="2-4 sentence overall assessment of the change")
    findings: list[CandidateFinding] = Field(default_factory=list)
