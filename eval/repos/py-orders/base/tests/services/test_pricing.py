import pytest

from app.services.pricing import compute_totals


def test_totals_without_discount_or_tax():
    totals = compute_totals([(1000, 2), (250, 1)])

    assert totals.subtotal_cents == 2250
    assert totals.total_cents == 2250


def test_tax_is_charged_on_discounted_amount():
    totals = compute_totals([(10_000, 1)], discount_cents=1_000, tax_bps=825)

    assert totals.tax_cents == 743
    assert totals.total_cents == 9_743


def test_discount_cannot_exceed_subtotal():
    with pytest.raises(ValueError):
        compute_totals([(100, 1)], discount_cents=101)
