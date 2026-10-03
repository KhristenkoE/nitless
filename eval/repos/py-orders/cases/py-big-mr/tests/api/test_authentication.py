# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

import pytest
from fastapi.testclient import TestClient

from app.api.deps import current_customer_id, require_admin
from app.core.auth import Principal
from app.core.errors import PermissionDeniedError
from tests.conftest import CUSTOMER_ID


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        pytest.param({}, "missing bearer token", id="no-header"),
        pytest.param({"Authorization": "Basic YWRtaW46YWRtaW4="}, "missing bearer token", id="basic-scheme"),
        pytest.param({"Authorization": "bearer token"}, "missing bearer token", id="lower-case-scheme"),
        pytest.param({"Authorization": "Bearer not-a-token"}, "malformed token", id="malformed"),
    ],
)
def test_invalid_credentials_return_401(client: TestClient, headers: dict[str, str], message: str) -> None:
    response = client.get("/admin/coupons", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthenticated", "message": message, "details": {}}}


def test_current_customer_id_returns_token_subject() -> None:
    assert current_customer_id(Principal(customer_id=CUSTOMER_ID)) == CUSTOMER_ID


def test_current_customer_id_rejects_tokens_without_customer() -> None:
    with pytest.raises(PermissionDeniedError, match="a customer token is required"):
        current_customer_id(Principal(customer_id=None, is_admin=True))


def test_require_admin_returns_admin_principal() -> None:
    principal = Principal(customer_id=None, is_admin=True)

    assert require_admin(principal) is principal


def test_require_admin_rejects_customers() -> None:
    with pytest.raises(PermissionDeniedError, match="admin access required"):
        require_admin(Principal(customer_id=CUSTOMER_ID))
