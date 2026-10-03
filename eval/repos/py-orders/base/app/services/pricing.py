from collections.abc import Iterable
from dataclasses import dataclass

from app.core.money import percent_of


@dataclass(frozen=True)
class Totals:
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int


def compute_totals(lines: Iterable[tuple[int, int]], *, discount_cents: int = 0, tax_bps: int = 0) -> Totals:
    """Totals for ``(unit_price_cents, quantity)`` lines. Tax is charged on the discounted amount."""
    subtotal = sum(unit_price_cents * quantity for unit_price_cents, quantity in lines)
    if not 0 <= discount_cents <= subtotal:
        raise ValueError("discount_cents must be between 0 and the subtotal")
    taxable = subtotal - discount_cents
    tax = percent_of(taxable, tax_bps)
    return Totals(
        subtotal_cents=subtotal,
        discount_cents=discount_cents,
        tax_cents=tax,
        total_cents=taxable + tax,
    )
