# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import clock
from app.models import Coupon
from tests.conftest import FROZEN_NOW

MakeCoupon = Callable[..., Coupon]


def test_create_coupon_returns_all_fields(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/admin/coupons", json={"code": "Summer20", "percent_off": 20, "expires_at": "2026-04-01T00:00:00Z"}
    )

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert body["code"] == "SUMMER20"
    assert body["percent_off"] == 20
    assert body["active"] is True
    assert datetime.fromisoformat(body["expires_at"]) == datetime(2026, 4, 1, tzinfo=UTC)
    assert datetime.fromisoformat(body["created_at"]) == FROZEN_NOW


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"code": "ABC", "percent_off": 1}, id="shortest-code-lowest-percent"),
        pytest.param({"code": "A" * 32, "percent_off": 100}, id="longest-code-full-discount"),
        pytest.param({"code": "summer_sale-26", "percent_off": 10}, id="underscore-and-dash"),
    ],
)
def test_create_coupon_accepts_boundary_values(admin_client: TestClient, payload: dict[str, Any]) -> None:
    response = admin_client.post("/admin/coupons", json=payload)

    assert response.status_code == 201
    assert response.json()["expires_at"] is None


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"code": "AB", "percent_off": 10}, id="code-too-short"),
        pytest.param({"code": "A" * 33, "percent_off": 10}, id="code-too-long"),
        pytest.param({"code": "SPRING 15", "percent_off": 10}, id="code-with-space"),
        pytest.param({"code": "SPRING15!", "percent_off": 10}, id="code-with-punctuation"),
        pytest.param({"code": "SPRING15", "percent_off": 0}, id="percent-zero"),
        pytest.param({"code": "SPRING15", "percent_off": 101}, id="percent-over-100"),
        pytest.param({"code": "SPRING15", "percent_off": 10, "expires_at": "2026-04-01T00:00:00"}, id="naive-expiry"),
        pytest.param({"percent_off": 10}, id="missing-code"),
    ],
)
def test_create_coupon_rejects_invalid_payload(admin_client: TestClient, payload: dict[str, Any]) -> None:
    assert admin_client.post("/admin/coupons", json=payload).status_code == 422


def test_create_coupon_with_existing_code_returns_409(admin_client: TestClient, make_coupon: MakeCoupon) -> None:
    make_coupon(code="SPRING15")

    response = admin_client.post("/admin/coupons", json={"code": "spring15", "percent_off": 10})

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "coupon code already exists", "details": {"code": "SPRING15"}}
    }


def test_list_coupons_uses_default_page(admin_client: TestClient, make_coupon: MakeCoupon) -> None:
    coupon = make_coupon(code="SPRING15", percent_off=15)

    response = admin_client.get("/admin/coupons")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [coupon.id]


def test_list_coupons_pages_newest_first(
    admin_client: TestClient, make_coupon: MakeCoupon, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clock, "utcnow", lambda: FROZEN_NOW - timedelta(days=1))
    make_coupon(code="OLDER")
    monkeypatch.setattr(clock, "utcnow", lambda: FROZEN_NOW)
    make_coupon(code="NEWER")

    first_page = admin_client.get("/admin/coupons", params={"limit": 1}).json()
    second_page = admin_client.get("/admin/coupons", params={"limit": 1, "offset": 1}).json()

    assert [item["code"] for item in first_page["items"]] == ["NEWER"]
    assert [item["code"] for item in second_page["items"]] == ["OLDER"]
    assert first_page["total"] == second_page["total"] == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_coupons_rejects_invalid_paging(admin_client: TestClient, params: dict[str, int]) -> None:
    assert admin_client.get("/admin/coupons", params=params).status_code == 422


def test_list_coupons_requires_admin(customer_client: TestClient) -> None:
    response = customer_client.get("/admin/coupons")

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "permission_denied", "message": "admin access required", "details": {}}
