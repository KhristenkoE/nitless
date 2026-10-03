import json
import re
from pathlib import Path

import pytest

from nitless.config import load_settings
from nitless.errors import ConfigError
from nitless.models import ChangeRequest, ReviewResult
from nitless.output import build_adapters
from nitless.output.markdown import render

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> ReviewResult:
    return ReviewResult.model_validate_json((FIXTURES / f"{name}.json").read_text())


def change(**kw) -> ChangeRequest:
    return ChangeRequest(provider="gitlab", repo="r", ref="!7", title="Add coupons", base_sha="b" * 40,
                         start_sha="s" * 40, head_sha="h" * 40, **kw)


def test_report_has_title_badge_and_finding():
    report = render(load("py-coupon-checkout"), change(web_url="https://h/g/p/-/merge_requests/7"))
    assert report.startswith("# 🤖 AI review of [Add coupons](https://h/g/p/-/merge_requests/7)\n")
    assert "\n\n**Verdict:** 🔴 Needs changes · 🟠 1 major\n" in report
    assert "Status" not in report  # the run status is footer material once there is a verdict
    assert "## 🔍 Findings\n\n### 🟠 Major\n\n🟠 **app/services/orders.py:59** · major · `correctness` — " in report
    assert "🎯 Confidence: 95%" in report
    assert "Requirements" not in report
    footer = report.rstrip().rsplit("\n", 1)[-1]
    assert footer.startswith("<sub>✅ ok · 🧠 strong `claude-opus-5-5`, fast `claude-haiku-4-5")
    assert footer.endswith("/ 3,114 completion tokens · 💸 $0.1885 · ⏱ 86.3 s · nitless 0.1.0</sub>")


def test_requirements_table():
    report = render(load("py-partial-refunds"), None)
    assert "# 🤖 AI review of main..case/py-partial-refunds\n" in report
    assert "Does what was asked: 🟡 **partially**." in report
    assert "| # | Status | Criterion | Evidence |\n|---|---|---|---|\n| AC1 | 🟡 partially met | " in report
    assert "| AC2 | ❌ not met | " in report
    assert "🚫 Out of scope:\n\n- Refunding specific order items" in report
    assert "## ⚠️ Warnings\n\n- merged reviewer finding" in report


def test_empty_result_says_no_findings():
    data = json.loads((FIXTURES / "py-coupon-checkout.json").read_text())
    data["findings"] = []
    report = render(ReviewResult.model_validate(data), None)
    assert "## 🔍 Findings\n\n✅ No findings.\n" in report


def test_error_run_has_error_block():
    data = json.loads((FIXTURES / "py-coupon-checkout.json").read_text())
    data.update(status="error", summary=None, findings=[], error={"kind": "llm", "message": "provider down"})
    report = render(ReviewResult.model_validate(data), None)
    assert "**Status:** ❌ error\n" in report
    assert "Findings" not in report
    assert "## ❌ Error\n\n**llm**: provider down" in report


def test_inline_findings_are_one_line_and_the_rest_outside_the_diff():
    result = load("py-partial-refunds")
    report = render(result, change(), inline={f.id for f in result.findings})
    assert "💬 Posted as inline comments:\n\n- 🔴 **app/services/payments.py:78** · critical" in report
    assert len(re.findall(r"\n- [🔴🟠🟡🔵] \*\*", report)) == 3 and "### Findings outside the diff" not in report
    report = render(result, change(), inline={result.findings[0].id})
    assert "### Findings outside the diff\n\n🟠 **app/services/payments.py:78** · major" in report
    assert "🟠 **tests/api/test_payments.py:94-115** · major · `test-coverage`" in report


def test_two_stdout_reports_are_a_config_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODEL_STRONG", "m")
    common = {"mr_url": "https://h/g/p/-/merge_requests/1", "output_adapter": "json,markdown"}
    with pytest.raises(ConfigError, match="set OUTPUT_FILE or MARKDOWN_FILE"):
        build_adapters(load_settings(**common))
    assert len(build_adapters(load_settings(**common, output_file=tmp_path / "r.json"))) == 2
    assert len(build_adapters(load_settings(**common, markdown_file=tmp_path / "r.md"))) == 2
