# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models import OutboxEvent
from app.services.outbox_relay import MAX_BACKOFF, backoff, relay_pending_events
from tests.conftest import FROZEN_NOW


class RecordingNotifier:
    def __init__(self, failing_ids: frozenset[int] = frozenset()) -> None:
        self.failing_ids = failing_ids
        self.seen: list[int] = []

    def deliver(self, event: OutboxEvent) -> bool:
        self.seen.append(event.id)
        return event.id not in self.failing_ids


def _add_event(session: Session, **overrides: Any) -> OutboxEvent:
    event = OutboxEvent(event_type="order.paid", aggregate_id=1, payload={"order_id": 1}, **overrides)
    session.add(event)
    session.flush()
    return event


@pytest.mark.parametrize(
    ("attempts", "expected"),
    [
        (0, timedelta(seconds=1)),
        (1, timedelta(seconds=2)),
        (3, timedelta(seconds=8)),
        (11, timedelta(seconds=2048)),
        (12, MAX_BACKOFF),
        (30, MAX_BACKOFF),
    ],
)
def test_backoff_doubles_up_to_one_hour(attempts: int, expected: timedelta) -> None:
    assert backoff(attempts) == expected


@pytest.mark.parametrize(
    ("overrides", "is_due"),
    [
        pytest.param({"next_attempt_at": FROZEN_NOW}, True, id="due-now"),
        pytest.param({"next_attempt_at": FROZEN_NOW - timedelta(minutes=5)}, True, id="overdue"),
        pytest.param({"next_attempt_at": FROZEN_NOW + timedelta(seconds=1)}, False, id="scheduled-later"),
        pytest.param({"delivered_at": FROZEN_NOW - timedelta(minutes=1)}, False, id="already-delivered"),
        pytest.param({"dead_at": FROZEN_NOW - timedelta(minutes=1)}, False, id="dead"),
    ],
)
def test_only_due_events_are_relayed(session: Session, overrides: dict[str, Any], is_due: bool) -> None:
    event = _add_event(session, **overrides)
    notifier = RecordingNotifier()

    delivered = relay_pending_events(session, notifier, batch_size=10, max_attempts=3)

    assert notifier.seen == ([event.id] if is_due else [])
    assert delivered == (1 if is_due else 0)


def test_batch_size_limits_events_in_id_order(session: Session) -> None:
    first, second, third = [_add_event(session) for _ in range(3)]
    notifier = RecordingNotifier()

    delivered = relay_pending_events(session, notifier, batch_size=2, max_attempts=3)

    assert delivered == 2
    assert notifier.seen == [first.id, second.id]
    assert third.delivered_at is None


def test_returns_only_successful_deliveries(session: Session) -> None:
    ok, failing = _add_event(session), _add_event(session)

    delivered = relay_pending_events(
        session, RecordingNotifier(failing_ids=frozenset({failing.id})), batch_size=10, max_attempts=3
    )

    assert delivered == 1
    assert ok.delivered_at == FROZEN_NOW
    assert failing.delivered_at is None
    assert failing.attempts == 1


@pytest.mark.parametrize(
    ("previous_attempts", "expected_delay"),
    [(0, timedelta(seconds=2)), (1, timedelta(seconds=4)), (4, timedelta(seconds=32))],
)
def test_retry_delay_grows_with_attempts(session: Session, previous_attempts: int, expected_delay: timedelta) -> None:
    event = _add_event(session, attempts=previous_attempts)

    relay_pending_events(session, RecordingNotifier(failing_ids=frozenset({event.id})), batch_size=10, max_attempts=8)

    assert event.attempts == previous_attempts + 1
    assert event.next_attempt_at == FROZEN_NOW + expected_delay
    assert event.dead_at is None


@pytest.mark.parametrize(("previous_attempts", "is_dead"), [(0, False), (1, False), (2, True)])
def test_event_dies_on_last_allowed_attempt(session: Session, previous_attempts: int, is_dead: bool) -> None:
    event = _add_event(session, attempts=previous_attempts)

    relay_pending_events(session, RecordingNotifier(failing_ids=frozenset({event.id})), batch_size=10, max_attempts=3)

    assert event.attempts == previous_attempts + 1
    assert event.dead_at == (FROZEN_NOW if is_dead else None)
    assert event.delivered_at is None
