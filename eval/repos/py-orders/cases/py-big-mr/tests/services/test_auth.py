# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from app.core import clock
from app.core.auth import Principal, decode_token, issue_token
from app.core.errors import AuthenticationError
from tests.conftest import FROZEN_NOW

SECRET = "test-auth-secret"


def _hand_built_token(claims: dict[str, object], secret: str = SECRET) -> str:
    """Build a token following the format documented in ``app.core.auth``."""
    payload = json.dumps(claims).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


@pytest.mark.parametrize(
    ("principal", "customer_id", "expected"),
    [
        (Principal(customer_id=1), 1, True),
        (Principal(customer_id=1), 2, False),
        (Principal(customer_id=None), 1, False),
        (Principal(customer_id=None, is_admin=True), 1, True),
        (Principal(customer_id=1, is_admin=True), 2, True),
    ],
)
def test_can_access_customer(principal: Principal, customer_id: int, expected: bool) -> None:
    assert principal.can_access_customer(customer_id) is expected


@pytest.mark.parametrize(
    "principal",
    [Principal(customer_id=4711), Principal(customer_id=None, is_admin=True), Principal(customer_id=7, is_admin=True)],
)
def test_issued_token_round_trips(principal: Principal) -> None:
    assert decode_token(issue_token(principal, SECRET), SECRET) == principal


def test_hand_built_token_is_accepted() -> None:
    exp = int(FROZEN_NOW.timestamp()) + 60
    token = _hand_built_token({"sub": 42, "admin": False, "exp": exp})

    assert decode_token(token, SECRET) == Principal(customer_id=42, is_admin=False)


@pytest.mark.parametrize("elapsed_seconds", [0, 59])
def test_token_is_valid_before_ttl_elapses(monkeypatch: pytest.MonkeyPatch, elapsed_seconds: int) -> None:
    token = issue_token(Principal(customer_id=1), SECRET, ttl_seconds=60)
    monkeypatch.setattr(clock, "utcnow", lambda: FROZEN_NOW + timedelta(seconds=elapsed_seconds))

    assert decode_token(token, SECRET) == Principal(customer_id=1)


@pytest.mark.parametrize("elapsed_seconds", [60, 3600])
def test_token_expires_once_ttl_elapses(monkeypatch: pytest.MonkeyPatch, elapsed_seconds: int) -> None:
    token = issue_token(Principal(customer_id=1), SECRET, ttl_seconds=60)
    monkeypatch.setattr(clock, "utcnow", lambda: FROZEN_NOW + timedelta(seconds=elapsed_seconds))

    with pytest.raises(AuthenticationError, match="token expired"):
        decode_token(token, SECRET)


def test_token_without_exp_claim_is_expired() -> None:
    token = _hand_built_token({"sub": 1, "admin": False})

    with pytest.raises(AuthenticationError, match="token expired"):
        decode_token(token, SECRET)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = issue_token(Principal(customer_id=1), "another-secret")

    with pytest.raises(AuthenticationError, match="invalid token signature"):
        decode_token(token, SECRET)


def test_token_with_tampered_payload_is_rejected() -> None:
    _, signature = issue_token(Principal(customer_id=1), SECRET).split(".", 1)
    forged_claims = {"sub": 1, "admin": True, "exp": int(FROZEN_NOW.timestamp()) + 3600}
    forged_payload, _ = _hand_built_token(forged_claims).split(".", 1)

    with pytest.raises(AuthenticationError, match="invalid token signature"):
        decode_token(f"{forged_payload}.{signature}", SECRET)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("", id="empty"),
        pytest.param("no-separator", id="no-separator"),
        pytest.param("a.signature", id="invalid-base64"),
        pytest.param(f"{base64.urlsafe_b64encode(b'not json').decode()}.signature", id="invalid-json"),
    ],
)
def test_malformed_token_is_rejected(token: str) -> None:
    with pytest.raises(AuthenticationError, match="malformed token") as excinfo:
        decode_token(token, SECRET)

    assert excinfo.value.code == "unauthenticated"
