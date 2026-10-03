from types import SimpleNamespace

import pytest

from nitless.context import conventions
from nitless.context.base import ContextItem
from nitless.context.conventions import CARD_BUDGET_TOKENS, build_conventions, documented_rules
from nitless.context.graph import Snippet
from nitless.context.packer import RelatedContext
from nitless.context.profile import Profile
from nitless.diff import parse_diff
from nitless.errors import LLMError

PAYMENTS = [
    "from app.core.errors import ConflictError, NotFoundError",
    "",
    "",
    "def refund(payment, amount):",
    "    if payment is None:",
    "        raise NotFoundError('payment')",
    "    if amount > payment.refundable:",
    "        raise ConflictError('refund exceeds the refundable balance')",
    "    return payment",
]
ORDERS_PEER = {12: "def mark_shipped(order):", 13: "    if order.status != 'paid':",
               14: "        raise ConflictError('order is not paid')"}
DIFF = """\
diff --git a/app/services/orders.py b/app/services/orders.py
--- a/app/services/orders.py
+++ b/app/services/orders.py
@@ -30,2 +30,4 @@
 def place(order):
+    if too_many(order):
+        raise HTTPException(409)
     return order
"""


@pytest.fixture(autouse=True)
def tiny_areas_count(monkeypatch):
    monkeypatch.setattr(conventions, "MIN_AREA_EVIDENCE_TOKENS", 10)  # the fixtures here are a few lines long


class FakeLLM:
    def __init__(self, answers: dict | None = None, error: Exception | None = None):
        self.answers, self.error, self.calls = answers or {}, error, 0

    def call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens=None):
        self.calls += 1
        if self.error:
            raise self.error
        assert "raise HTTPException" not in messages[-1]["content"]  # the change itself is never shown
        return schema.model_validate(self.answers)


def related() -> RelatedContext:
    orders_lines = [""] * 40
    for n, text in ORDERS_PEER.items():
        orders_lines[n - 1] = text
    sources = {"app/services/payments.py": PAYMENTS, "app/services/orders.py": orders_lines}
    siblings = [Snippet("sibling", "app/services/payments.py", ((1, 9),), "sibling of orders.py", 60,
                        "app/services/orders.py"),
                Snippet("sibling", "app/services/orders.py", ((12, 14),), "peer of place", 70,
                        "app/services/orders.py")]
    return RelatedContext([], [], ["place (modified) in app/services/orders.py"],
                          siblings={"app/services/orders.py": siblings},
                          source_of=lambda path: SimpleNamespace(lines=sources[path]) if path in sources else None)


def rule(text: str, *cites: tuple[str, int, str], topic: str = "error-handling") -> dict:
    return {"topic": topic, "rule": text, "evidence": [{"file": f, "line": n, "quote": q} for f, n, q in cites]}


def test_rules_need_a_citation_that_really_is_in_the_shown_code():
    llm = FakeLLM({"rules": [
        rule("Services raise ConflictError from app.core.errors, not HTTP exceptions",
             ("app/services/payments.py", 8, "raise ConflictError("), ("app/services/orders.py", 14, "ConflictError")),
        rule("Lookups raise NotFoundError", ("./app/services/payments.py", 2, "raise NotFoundError")),  # off by 4
        rule("Every service logs with structlog", ("app/services/payments.py", 3, "structlog.get_logger")),
        rule("Services use the unit of work", ("app/db/uow.py", 5, "UnitOfWork")),  # file was never shown
        rule("Money is integer cents", ("app/services/orders.py", 30, "too_many")),  # the changed line, not shown
    ]})
    card = build_conventions(llm, "fast", parse_diff(DIFF), Profile([], []), related())

    assert llm.calls == 1
    kept = {r.text: r.evidence for r in card.rules}
    assert kept == {
        "Services raise ConflictError from app.core.errors, not HTTP exceptions":
            ["app/services/payments.py:8", "app/services/orders.py:14"],
        "Lookups raise NotFoundError": ["app/services/payments.py:6"],  # relocated to where the quote is
    }
    assert all(r.tag == "inferred-from-code" and r.area == "app/services" for r in card.rules)
    [area] = card.areas
    assert area["proposed"] == 5 and area["kept"] == 2 and len(area["dropped"]) == 3
    assert area["evidence"] == ["app/services/orders.py:12-14", "app/services/payments.py:1-9"]
    rendered = card.render()
    assert "## app/services/ (inferred-from-code)" in rendered
    assert "[error-handling] Lookups raise NotFoundError (evidence: app/services/payments.py:6)" in rendered


def test_failures_degrade_to_no_card():
    card = build_conventions(FakeLLM(error=LLMError("quota")), "fast", parse_diff(DIFF), Profile([], []), related())
    assert card.rules == [] and card.render() == "" and "unavailable" in card.warnings[0]

    no_siblings = RelatedContext([], [])
    card = build_conventions(FakeLLM(), "fast", parse_diff(DIFF), Profile([], []), no_siblings)
    assert card.rules == [] and card.areas[0]["status"] == "skipped: no sibling code found"


def test_documented_rules_are_verbatim_code_rules_from_the_profile():
    doc = ContextItem("doc", "CONTRIBUTING.md#Errors", "guide", (
        "## Errors\n"
        "- Services **must** raise domain errors from\n  `app/core/errors.py`, never `HTTPException`.\n"
        "- At least one approval is required to merge.\n"
        "- `pytest` must pass before review.\n"
        "```\n- never shown: inside a fence\n```\n"
        "Plain prose that should use something.\n"), priority=20)
    rules = documented_rules(Profile([doc], []), ["app/services/orders.py"])
    assert [(r.text, r.evidence, r.tag) for r in rules] == [
        ("Services **must** raise domain errors from `app/core/errors.py`, never `HTTPException`.",
         ["CONTRIBUTING.md#Errors"], "documented")]


def test_card_stays_within_budget():
    many = {"rules": [rule(f"Rule number {i} " + "word " * 25, ("app/services/payments.py", 4, "def refund"))
                      for i in range(12)]}
    card = build_conventions(FakeLLM(many), "fast", parse_diff(DIFF), Profile([], []), related())
    assert card.tokens <= CARD_BUDGET_TOKENS and 0 < len(card.rules) <= 5
