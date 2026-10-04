"""USD per million tokens (input, output). Only list prices that were checked against the provider's page;
anything else is reported as unknown rather than guessed. MODEL_PRICES adds or overrides entries."""

from nitless.models import ModelUsage

PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def parse_prices(entries: list[str]) -> dict[str, tuple[float, float]]:
    """`model=input/output` entries, e.g. `gpt-x=1.25/10`, or `model=rate` when both cost the same."""
    prices = {}
    for entry in entries:
        model, _, rates = entry.rpartition("=")
        inp, sep, out = rates.partition("/")
        if not sep:
            out = inp  # one rate for input and output
        prices[model.strip()] = (float(out), float(inp))
    return prices


def cost_usd(usage: dict[str, ModelUsage], overrides: dict[str, tuple[float, float]] | None = None) -> float | None:
    """What the run cost at list prices; None when any model used has no known price."""
    table = {**PRICES, **(overrides or {})}
    total = 0.0
    for model, u in usage.items():
        if model not in table:
            return None
        inp, out = table[model]
        total += (u.prompt_tokens * inp + u.completion_tokens * out) / 1_000_000
    return round(total, 4)


def unpriced(usage: dict[str, ModelUsage], overrides: dict[str, tuple[float, float]] | None = None) -> list[str]:
    table = {**PRICES, **(overrides or {})}
    return [m for m in usage if m not in table]
