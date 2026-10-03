"""Outgoing webhook delivery for outbox events."""

import hashlib
import hmac
import json

import httpx

from app.core import clock
from app.core.config import Settings
from app.core.logging import get_logger
from app.models.outbox import OutboxEvent

log = get_logger(__name__)

SIGNATURE_HEADER = "X-Orders-Signature"


def sign_payload(body: bytes, secret: str, timestamp: int) -> str:
    """Signature header value: ``t=<unix seconds>,v1=<hex hmac-sha256 of "<t>.<body>">``."""
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


class WebhookNotifier:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._url = settings.webhook_url
        secret = settings.webhook_signing_secret
        self._secret = secret.get_secret_value() if secret is not None else None
        self._client = client or httpx.Client(timeout=settings.webhook_timeout_seconds)

    def deliver(self, event: OutboxEvent) -> bool:
        if self._url is None:
            log.debug("webhook_skipped_no_url", event_id=event.id)
            return True

        try:
            body = self._encode(event)
            headers = {"Content-Type": "application/json", "X-Orders-Event-Id": str(event.id)}
            if self._secret is not None:
                headers[SIGNATURE_HEADER] = sign_payload(body, self._secret, int(clock.utcnow().timestamp()))
            response = self._client.post(self._url, content=body, headers=headers)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "webhook_delivery_failed",
                event_id=event.id,
                event_type=event.event_type,
                attempt=event.attempts + 1,
                error=str(exc),
            )
            return False

        log.info("webhook_delivered", event_id=event.id, event_type=event.event_type, status=response.status_code)
        return True

    @staticmethod
    def _encode(event: OutboxEvent) -> bytes:
        body = {
            "id": str(event.id),
            "type": event.event_type,
            "created_at": event.created_at.isoformat(),
            "data": event.payload,
        }
        return json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
