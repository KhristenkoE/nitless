"""Outgoing webhook delivery for outbox events."""

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.outbox import OutboxEvent

log = get_logger(__name__)


class WebhookNotifier:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._url = settings.webhook_url
        self._client = client or httpx.Client(timeout=settings.webhook_timeout_seconds)

    def deliver(self, event: OutboxEvent) -> bool:
        if self._url is None:
            log.debug("webhook_skipped_no_url", event_id=event.id)
            return True

        body = {
            "id": str(event.id),
            "type": event.event_type,
            "created_at": event.created_at.isoformat(),
            "data": event.payload,
        }
        try:
            response = self._client.post(self._url, json=body, headers={"X-Orders-Event-Id": str(event.id)})
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("webhook_delivery_failed", event_id=event.id, event_type=event.event_type, error=str(exc))
            return False

        log.info("webhook_delivered", event_id=event.id, event_type=event.event_type, status=response.status_code)
        return True
