import pytest

from app.core.money import format_cents, percent_of, split_evenly


@pytest.mark.parametrize(
    ("amount", "bps", "expected"),
    [(10_000, 825, 825), (999, 1_500, 150), (1, 5_000, 1), (0, 2_000, 0), (12_345, 10_000, 12_345)],
)
def test_percent_of_rounds_half_up(amount, bps, expected):
    assert percent_of(amount, bps) == expected


def test_format_cents():
    assert format_cents(123_456, "USD") == "1,234.56 USD"
    assert format_cents(-5, "EUR") == "-0.05 EUR"


def test_split_evenly_preserves_total():
    parts = split_evenly(1_000, 3)

    assert parts == [334, 333, 333]
    assert sum(parts) == 1_000
