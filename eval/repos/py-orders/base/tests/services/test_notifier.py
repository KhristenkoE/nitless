import httpx

from app.core.config import Settings
from app.models import OutboxEvent
from app.services.notifier import WebhookNotifier
from tests.conftest import FROZEN_NOW


def _event() -> OutboxEvent:
    return OutboxEvent(id=7, event_type="order.paid", aggregate_id=3, payload={"order_id": 3}, created_at=FROZEN_NOW)


def _notifier(handler) -> WebhookNotifier:
    settings = Settings(webhook_url="https://hooks.example.com/orders")
    return WebhookNotifier(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_deliver_posts_event():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    assert _notifier(handler).deliver(_event()) is True
    assert requests[0].headers["X-Orders-Event-Id"] == "7"


def test_deliver_reports_failure_instead_of_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert _notifier(handler).deliver(_event()) is False


def test_deliver_reports_connection_errors_as_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    assert _notifier(handler).deliver(_event()) is False
