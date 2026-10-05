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

# Prompt cache reads and writes, as a share of the input price (5-minute entries).
CACHE_READ_RATE: dict[str, float] = {"claude-opus-5-5": 0.05}
DEFAULT_CACHE_READ_RATE = 0.1
CACHE_WRITE_RATE = 1.25


def parse_prices(entries: list[str]) -> dict[str, tuple[float, float]]:
    """`model=input/output` entries, e.g. `gpt-x=1.25/10`."""
    prices = {}
    for entry in entries:
        model, _, rates = entry.rpartition("=")
        inp, _, out = rates.partition("/")
        prices[model.strip()] = (float(inp), float(out))
    return prices


def cost_usd(usage: dict[str, ModelUsage], overrides: dict[str, tuple[float, float]] | None = None) -> float | None:
    """What the run cost at list prices; None when any model used has no known price."""
    table = {**PRICES, **(overrides or {})}
    total = 0.0
    for model, u in usage.items():
        if model not in table:
            return None
        inp, out = table[model]
        uncached = u.prompt_tokens - u.cache_read_tokens - u.cache_write_tokens
        read = u.cache_read_tokens * CACHE_READ_RATE.get(model, DEFAULT_CACHE_READ_RATE)
        total += ((uncached + read + u.cache_write_tokens * CACHE_WRITE_RATE) * inp + u.completion_tokens * out) \
            / 1_000_000
    return round(total, 4)


def unpriced(usage: dict[str, ModelUsage], overrides: dict[str, tuple[float, float]] | None = None) -> list[str]:
    table = {**PRICES, **(overrides or {})}
    return [m for m in usage if m not in table]
