# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from datetime import timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from app.core import clock
from app.core.logging import get_logger
from app.models.outbox import OutboxEvent
from app.repositories.outbox import OutboxRepository

log = get_logger(__name__)

MAX_BACKOFF = timedelta(hours=1)


class Notifier(Protocol):
    def deliver(self, event: OutboxEvent) -> bool: ...


def backoff(attempts: int) -> timedelta:
    return min(timedelta(seconds=2**attempts), MAX_BACKOFF)


def relay_pending_events(session: Session, notifier: Notifier, *, batch_size: int, max_attempts: int) -> int:
    """Deliver due outbox events. Returns how many were delivered. The caller owns the transaction."""
    outbox = OutboxRepository(session)
    now = clock.utcnow()
    delivered = 0
    for event in outbox.fetch_due(now, limit=batch_size):
        if notifier.deliver(event):
            outbox.mark_delivered(event, now)
            delivered += 1
            continue
        attempts = event.attempts + 1
        if attempts >= max_attempts:
            outbox.mark_dead(event, attempts=attempts, at=now)
            log.error("outbox_event_dead", event_id=event.id, event_type=event.event_type, attempts=attempts)
        else:
            outbox.schedule_retry(event, attempts=attempts, next_attempt_at=now + backoff(attempts))
    return delivered
