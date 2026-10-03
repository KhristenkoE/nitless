from datetime import timedelta

from app.models import OutboxEvent
from app.services.outbox_relay import relay_pending
from tests.conftest import FROZEN_NOW


class StubNotifier:
    def __init__(self, succeed: bool) -> None:
        self.succeed = succeed
        self.seen: list[int] = []

    def deliver(self, event: OutboxEvent) -> bool:
        self.seen.append(event.id)
        return self.succeed


def _event(session, **overrides) -> OutboxEvent:
    event = OutboxEvent(event_type="order.created", aggregate_id=1, payload={"order_id": 1}, **overrides)
    session.add(event)
    session.flush()
    return event


def test_delivered_events_are_marked(session):
    event = _event(session)

    delivered = relay_pending(session, StubNotifier(succeed=True), batch_size=10, max_attempts=3)

    assert delivered == 1
    assert event.delivered_at == FROZEN_NOW


def test_failed_delivery_is_retried_with_backoff(session):
    event = _event(session)

    relay_pending(session, StubNotifier(succeed=False), batch_size=10, max_attempts=3)

    assert event.attempts == 1
    assert event.next_attempt_at == FROZEN_NOW + timedelta(seconds=2)
    assert event.delivered_at is None


def test_event_is_dead_after_max_attempts(session):
    event = _event(session, attempts=2)

    relay_pending(session, StubNotifier(succeed=False), batch_size=10, max_attempts=3)

    assert event.dead_at == FROZEN_NOW
