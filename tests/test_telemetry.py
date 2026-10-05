from datetime import UTC, datetime

from nitless.llm.pricing import cost_usd, parse_prices
from nitless.models import ModelUsage, ReviewResult, RunMeta
from nitless.output.markdown import render
from nitless.pipeline import telemetry


def meta(**kw) -> RunMeta:
    return RunMeta(tool_version="0.1.0", started_at=datetime.now(UTC), models={"strong": "m"}, duration_s=12.5,
                   usage={"m": ModelUsage(calls=3, prompt_tokens=40000, completion_tokens=1500)}, **kw)


def test_cost_is_priced_per_model_and_unknown_when_any_model_has_no_price():
    usage = {"claude-opus-5-5": ModelUsage(calls=2, prompt_tokens=100_000, completion_tokens=10_000),
             "claude-haiku-4-5": ModelUsage(calls=1, prompt_tokens=20_000, completion_tokens=1_000)}
    assert cost_usd(usage) == 0.625  # 0.4 + 0.2 + 0.02 + 0.005
    cached = {"claude-sonnet-5-5": ModelUsage(calls=2, prompt_tokens=1_000_000, completion_tokens=0,
                                              cache_read_tokens=500_000, cache_write_tokens=100_000)}
    assert cost_usd(cached) == 1.15  # 400k at $2, 500k read at 0.1x, 100k written at 1.25x
    local = {"llama3:8b": ModelUsage(calls=1, prompt_tokens=1_000_000, completion_tokens=0)}
    assert cost_usd(local) is None
    assert cost_usd(local, parse_prices(["llama3:8b=0.5/1"])) == 0.5


def test_telemetry_line_names_time_calls_tokens_and_cost():
    line = telemetry(meta(cost_usd=0.2449))
    assert line == "12.5s, 3 LLM calls, 40,000 prompt + 1,500 completion tokens (m 41,500), cost $0.2449"
    assert telemetry(meta()).endswith("cost n/a (no price for a model; see MODEL_PRICES)")


def test_markdown_footer_shows_the_cost_only_when_known():
    with_cost = render(ReviewResult(status="ok", run=meta(cost_usd=0.25)), None)
    without = render(ReviewResult(status="ok", run=meta()), None)
    assert "💸 $0.2500" in with_cost and "💸" not in without
