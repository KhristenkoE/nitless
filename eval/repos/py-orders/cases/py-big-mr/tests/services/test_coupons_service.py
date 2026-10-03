# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ConflictError
from app.models import Coupon
from app.repositories.coupons import CouponRepository
from app.schemas.coupon import CouponCreate
from app.services.coupons import CouponService
from tests.conftest import FROZEN_NOW

MakeCoupon = Callable[..., Coupon]


def _set_now(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    monkeypatch.setattr(clock, "utcnow", lambda: now)


@pytest.mark.parametrize(
    ("active", "expires_at", "expected"),
    [
        (True, None, True),
        (False, None, False),
        (True, FROZEN_NOW + timedelta(seconds=1), True),
        (True, FROZEN_NOW, False),
        (True, FROZEN_NOW - timedelta(days=1), False),
        (False, FROZEN_NOW + timedelta(days=1), False),
    ],
)
def test_is_redeemable(active: bool, expires_at: datetime | None, expected: bool) -> None:
    coupon = Coupon(code="SPRING15", percent_off=15, active=active, expires_at=expires_at)

    assert coupon.is_redeemable(FROZEN_NOW) is expected


@pytest.mark.parametrize("lookup", ["SPRING15", "spring15", "  Spring15 "])
def test_get_by_code_is_case_insensitive(session: Session, make_coupon: MakeCoupon, lookup: str) -> None:
    coupon = make_coupon(code="SPRING15")

    assert CouponRepository(session).get_by_code(lookup) is coupon


def test_get_by_code_returns_none_for_unknown_code(session: Session, make_coupon: MakeCoupon) -> None:
    make_coupon(code="SPRING15")

    assert CouponRepository(session).get_by_code("SPRING") is None


def test_create_coupon_stores_upper_case_code(session: Session) -> None:
    expires_at = FROZEN_NOW + timedelta(days=30)

    coupon = CouponService(session).create_coupon(CouponCreate(code="summer20", percent_off=20, expires_at=expires_at))

    assert coupon.id is not None
    assert coupon.code == "SUMMER20"
    assert coupon.percent_off == 20
    assert coupon.active is True
    assert coupon.expires_at == expires_at
    assert coupon.created_at == FROZEN_NOW
    assert CouponRepository(session).get_by_code("SUMMER20") is coupon


def test_create_coupon_rejects_duplicate_code_regardless_of_case(session: Session, make_coupon: MakeCoupon) -> None:
    make_coupon(code="SPRING15")

    with pytest.raises(ConflictError) as excinfo:
        CouponService(session).create_coupon(CouponCreate(code="spring15", percent_off=10))

    assert excinfo.value.details == {"code": "SPRING15"}


@pytest.mark.parametrize(
    ("limit", "offset", "expected_codes"),
    [
        (50, 0, ["NEWEST", "MIDDLE", "OLDEST"]),
        (2, 0, ["NEWEST", "MIDDLE"]),
        (2, 2, ["OLDEST"]),
        (2, 3, []),
    ],
)
def test_list_coupons_pages_newest_first(
    session: Session,
    make_coupon: MakeCoupon,
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
    offset: int,
    expected_codes: list[str],
) -> None:
    for hours_ago, code in [(2, "OLDEST"), (1, "MIDDLE"), (0, "NEWEST")]:
        _set_now(monkeypatch, FROZEN_NOW - timedelta(hours=hours_ago))
        make_coupon(code=code)

    coupons, total = CouponService(session).list_coupons(limit=limit, offset=offset)

    assert [coupon.code for coupon in coupons] == expected_codes
    assert total == 3
