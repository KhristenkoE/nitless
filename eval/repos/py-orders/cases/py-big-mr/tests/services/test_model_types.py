# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.core import clock
from app.models import Coupon, Order, Product
from app.models.base import UTCDateTime
from tests.conftest import FROZEN_NOW

UTC_PLUS_2 = timezone(timedelta(hours=2))
DIALECT = sqlite.dialect()


def test_bind_converts_aware_datetimes_to_utc() -> None:
    local = datetime(2026, 3, 2, 14, 0, tzinfo=UTC_PLUS_2)

    stored = UTCDateTime().process_bind_param(local, DIALECT)

    assert stored is not None
    assert stored == FROZEN_NOW
    assert stored.tzinfo is UTC


def test_datetimes_are_reloaded_as_utc(session: Session, make_coupon: Callable[..., Coupon]) -> None:
    coupon = make_coupon(expires_at=datetime(2026, 4, 1, 2, 0, tzinfo=UTC_PLUS_2))
    session.expire(coupon)

    assert coupon.expires_at is not None
    assert coupon.expires_at == datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    assert coupon.expires_at.tzinfo is UTC


def test_flushing_a_naive_datetime_fails(make_coupon: Callable[..., Coupon]) -> None:
    with pytest.raises(StatementError, match="naive datetimes cannot be stored"):
        make_coupon(expires_at=datetime(2026, 4, 1, 0, 0))


def test_updated_at_follows_the_clock(
    session: Session, make_product: Callable[..., Product], monkeypatch: pytest.MonkeyPatch
) -> None:
    product = make_product()
    later = FROZEN_NOW + timedelta(minutes=10)
    monkeypatch.setattr(clock, "utcnow", lambda: later)

    product.stock_quantity = 3
    session.flush()

    assert product.created_at == FROZEN_NOW
    assert product.updated_at == later


@pytest.mark.parametrize("percent_off", [0, 101])
def test_coupon_percent_off_is_checked(make_coupon: Callable[..., Coupon], percent_off: int) -> None:
    with pytest.raises(IntegrityError, match="ck_coupons_percent_off_range"):
        make_coupon(percent_off=percent_off)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"unit_price_cents": 0}, "ck_products_unit_price_positive"),
        ({"stock_quantity": -1}, "ck_products_stock_not_negative"),
    ],
)
def test_product_check_constraints(
    make_product: Callable[..., Product], overrides: dict[str, int], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        make_product(**overrides)


def test_order_item_quantity_must_be_positive(make_order: Callable[..., Order]) -> None:
    with pytest.raises(IntegrityError, match="ck_order_items_quantity_positive"):
        make_order(quantity=0)
