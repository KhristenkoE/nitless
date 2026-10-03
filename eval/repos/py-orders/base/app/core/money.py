"""Integer-cent money helpers.

Amounts are always integer minor units (cents). Rates are expressed in basis points
(1 bp = 0.01%, so 10_000 bp = 100%).
"""

BPS_DENOMINATOR = 10_000


def percent_of(amount_cents: int, basis_points: int) -> int:
    """Return ``basis_points`` / 10_000 of ``amount_cents``, rounded half up to a cent."""
    if amount_cents < 0:
        raise ValueError("amount_cents must not be negative")
    if basis_points < 0:
        raise ValueError("basis_points must not be negative")
    return (amount_cents * basis_points + BPS_DENOMINATOR // 2) // BPS_DENOMINATOR


def format_cents(amount_cents: int, currency: str) -> str:
    """Human readable amount for logs and emails, e.g. ``format_cents(123456, "USD") == "1,234.56 USD"``."""
    sign = "-" if amount_cents < 0 else ""
    whole, fraction = divmod(abs(amount_cents), 100)
    return f"{sign}{whole:,}.{fraction:02d} {currency}"


def split_evenly(amount_cents: int, parts: int) -> list[int]:
    """Split an amount into ``parts`` integer shares that add up exactly to the amount."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    base, remainder = divmod(amount_cents, parts)
    return [base + 1 if index < remainder else base for index in range(parts)]
