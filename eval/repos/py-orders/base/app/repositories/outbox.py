from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.outbox import OutboxEvent


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event_type: str, *, aggregate_id: int, payload: dict[str, Any]) -> OutboxEvent:
        event = OutboxEvent(event_type=event_type, aggregate_id=aggregate_id, payload=payload)
        self._session.add(event)
        self._session.flush()
        return event

    def fetch_due(self, now: datetime, *, limit: int) -> list[OutboxEvent]:
        query = (
            select(OutboxEvent)
            .where(
                OutboxEvent.delivered_at.is_(None),
                OutboxEvent.dead_at.is_(None),
                OutboxEvent.next_attempt_at <= now,
            )
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.scalars(query).all())

    def mark_delivered(self, event: OutboxEvent, at: datetime) -> None:
        event.delivered_at = at

    def schedule_retry(self, event: OutboxEvent, *, attempts: int, next_attempt_at: datetime) -> None:
        event.attempts = attempts
        event.next_attempt_at = next_attempt_at

    def mark_dead(self, event: OutboxEvent, *, attempts: int, at: datetime) -> None:
        event.attempts = attempts
        event.dead_at = at
