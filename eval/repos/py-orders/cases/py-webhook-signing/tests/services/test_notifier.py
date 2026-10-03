import hashlib
import hmac

import httpx

from app.core.config import Settings
from app.models import OutboxEvent
from app.services.notifier import SIGNATURE_HEADER, WebhookNotifier
from tests.conftest import FROZEN_NOW

SECRET = "whsec_test"


def _event() -> OutboxEvent:
    return OutboxEvent(
        id=7, event_type="order.paid", aggregate_id=3, payload={"order_id": 3}, created_at=FROZEN_NOW, attempts=0
    )


def _notifier(handler, secret: str | None = SECRET) -> WebhookNotifier:
    settings = Settings(webhook_url="https://hooks.example.com/orders", webhook_signing_secret=secret)
    return WebhookNotifier(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _recording(requests: list[httpx.Request], status: int = 204):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status)

    return handler


def test_deliver_posts_event():
    requests: list[httpx.Request] = []

    assert _notifier(_recording(requests)).deliver(_event()) is True
    assert requests[0].headers["X-Orders-Event-Id"] == "7"


def test_deliver_signs_body_with_timestamp():
    requests: list[httpx.Request] = []

    _notifier(_recording(requests)).deliver(_event())

    timestamp = int(FROZEN_NOW.timestamp())
    expected = hmac.new(SECRET.encode(), f"{timestamp}.".encode() + requests[0].content, hashlib.sha256).hexdigest()
    assert requests[0].headers[SIGNATURE_HEADER] == f"t={timestamp},v1={expected}"


def test_deliver_without_secret_sends_no_signature():
    requests: list[httpx.Request] = []

    _notifier(_recording(requests), secret=None).deliver(_event())

    assert SIGNATURE_HEADER not in requests[0].headers


def test_deliver_reports_failure_instead_of_raising():
    assert _notifier(_recording([], status=503)).deliver(_event()) is False


def test_deliver_reports_connection_errors_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    assert _notifier(handler).deliver(_event()) is False
