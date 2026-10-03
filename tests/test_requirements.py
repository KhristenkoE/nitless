from nitless.context.intent import Intent
from nitless.diff import parse_diff
from nitless.review.postprocess import summarize, validate
from nitless.review.requirements import (
    RequirementsSubmission,
    merge_findings,
    to_findings,
    to_requirements,
)
from nitless.review.schema import CandidateFinding

DIFF = """\
diff --git a/app/services/orders.py b/app/services/orders.py
--- a/app/services/orders.py
+++ b/app/services/orders.py
@@ -70,3 +70,8 @@
 def get_order(order_id):
+    pass
+
+def cancel_order(order):
+    order.status = "cancelled"
+    return order
     return None

"""
FILES = parse_diff(DIFF)
INTENT = Intent(source="story.json", kind="repo", title="ORD-318", intent="Customers cancel unpaid orders.",
                acceptance_criteria=["POST /orders/{id}/cancel returns the cancelled order",
                                     "An order.cancelled event is written to the outbox",
                                     "Paid orders return 409"],
                out_of_scope=["Refunds"])


def submission(**overrides) -> RequirementsSubmission:
    checks = [
        {"id": "AC1", "status": "met", "evidence": "app/services/orders.py:73", "confidence": 0.9},
        {"id": "AC 2", "status": "not_met", "evidence": "no OutboxRepository.add call in cancel_order",
         "gap": "cancel_order never writes the order.cancelled outbox event", "file": "app/services/orders.py",
         "line": 90, "confidence": 0.85},
    ]
    return RequirementsSubmission.model_validate({"criteria": checks, "scope_creep": [], "verdict": "Mostly.",
                                                  **overrides})


def test_every_criterion_gets_a_status_and_the_answer_is_derived():
    reqs = to_requirements(INTENT, submission())
    assert [(c.id, c.status) for c in reqs.criteria] == [("AC1", "met"), ("AC2", "not_met"),
                                                          ("AC3", "cannot_determine")]  # skipped by the model
    assert reqs.criteria[2].evidence == "not assessed"
    assert reqs.does_what_was_asked == "partially" and reqs.out_of_scope == ["Refunds"]
    assert reqs.kind == "repo" and reqs.source == "story.json"


def test_unmet_criteria_become_anchored_requirements_findings():
    [finding] = to_findings(INTENT, submission(), FILES)
    assert finding.category == "requirements" and finding.severity == "major"
    assert finding.file == "app/services/orders.py" and finding.line_start == 77  # line 90 snapped into the hunk
    assert finding.message == "cancel_order never writes the order.cancelled outbox event"
    assert "AC2" in finding.rationale and "outbox" in finding.rationale
    assert finding.evidence[0].ref == "story.json#AC2"
    kept, warnings = validate([finding], FILES, "minor")
    assert len(kept) == 1 and warnings == []

    unsure = submission(criteria=[{"id": "AC2", "status": "partially_met", "evidence": "?", "file":
                                   "app/services/orders.py", "line": 74, "confidence": 0.4},
                                  {"id": "AC3", "status": "not_met", "evidence": "no 409", "file": None,
                                   "line": None, "confidence": 0.9}])
    assert to_findings(INTENT, unsure, FILES) == []  # low confidence, or nowhere in the diff to anchor it


def test_reviewer_findings_do_not_duplicate_the_requirements_step():
    def reviewer(**kw) -> CandidateFinding:
        base = dict(file="app/services/orders.py", line_start=74, severity="critical", category="reliability",
                    message="cancel_order does not write the order.cancelled outbox event", rationale="r",
                    confidence=0.8)
        return CandidateFinding(**{**base, **kw})

    ac_findings = to_findings(INTENT, submission(), FILES)
    other_bug = reviewer(message="status is set without checking that the order is pending", line_start=74)
    ac_claim = reviewer(category="requirements", message="AC3 is not implemented", line_start=76)
    merged, notes = merge_findings([reviewer(), other_bug, ac_claim], ac_findings, owns_criteria=True)
    assert [(f.category, f.message) for f in merged] == [
        ("reliability", other_bug.message),
        ("requirements", "cancel_order never writes the order.cancelled outbox event")]
    assert merged[1].severity == "critical"  # the folded-in reviewer finding was more severe
    assert len(notes) == 2

    # without acceptance criteria the reviewer keeps its own requirements findings
    merged, _ = merge_findings([ac_claim], [], owns_criteria=False)
    assert merged == [ac_claim]


def test_unmet_criterion_forces_needs_changes_and_is_summarized():
    reqs = to_requirements(INTENT, submission())
    summary = summarize("Clean code.", [], reqs)
    assert summary.verdict == "needs_changes"
    assert summary.assessment == ("Clean code. Requirements (story.json): 1/3 acceptance criteria met; "
                                  "not met: AC2.")
    all_met = submission(criteria=[{"id": f"AC{i}", "status": "met", "evidence": "x", "confidence": 1}
                                   for i in (1, 2, 3)])
    assert summarize("Clean.", [], to_requirements(INTENT, all_met)).verdict == "no_issues"


def test_intent_without_criteria_is_one_criterion_and_never_a_finding():
    intent = INTENT.model_copy(update={"acceptance_criteria": []})
    checked = submission(criteria=[{"id": "intent", "status": "not_met", "evidence": "nothing cancels",
                                    "file": "app/services/orders.py", "line": 74, "confidence": 0.9}])
    reqs = to_requirements(intent, checked)
    assert [(c.id, c.text) for c in reqs.criteria] == [("intent", "Customers cancel unpaid orders.")]
    assert reqs.does_what_was_asked == "no"
    assert to_findings(intent, checked, FILES) == []
