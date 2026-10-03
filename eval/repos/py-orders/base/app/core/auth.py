"""Bearer tokens issued by the identity service.

Token format: ``<base64url(json payload)>.<hex hmac-sha256(payload)>`` where the payload
is ``{"sub": <customer id or null>, "admin": <bool>, "exp": <unix seconds>}``.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

from app.core import clock
from app.core.errors import AuthenticationError


@dataclass(frozen=True)
class Principal:
    customer_id: int | None
    is_admin: bool = False

    def can_access_customer(self, customer_id: int) -> bool:
        return self.is_admin or self.customer_id == customer_id


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def issue_token(principal: Principal, secret: str, ttl_seconds: int = 3600) -> str:
    """Used by tests and local tooling; production tokens come from the identity service."""
    exp = int(clock.utcnow().timestamp()) + ttl_seconds
    payload = json.dumps({"sub": principal.customer_id, "admin": principal.is_admin, "exp": exp}).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{encoded}.{_sign(payload, secret)}"


def decode_token(token: str, secret: str) -> Principal:
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        claims = json.loads(payload)
    except ValueError as exc:
        raise AuthenticationError("malformed token") from exc
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        raise AuthenticationError("invalid token signature")
    if int(claims.get("exp", 0)) <= int(clock.utcnow().timestamp()):
        raise AuthenticationError("token expired")
    return Principal(customer_id=claims.get("sub"), is_admin=bool(claims.get("admin", False)))
