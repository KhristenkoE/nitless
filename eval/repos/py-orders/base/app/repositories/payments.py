from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payment import Payment, Refund


class PaymentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, payment_id: int) -> Payment | None:
        return self._session.get(Payment, payment_id)

    def get_for_update(self, payment_id: int) -> Payment | None:
        query = select(Payment).where(Payment.id == payment_id).with_for_update()
        return self._session.scalars(query).one_or_none()

    def get_by_idempotency_key(self, key: str) -> Payment | None:
        return self._session.scalars(select(Payment).where(Payment.idempotency_key == key)).one_or_none()

    def add(self, payment: Payment) -> None:
        self._session.add(payment)
        self._session.flush()

    def add_refund(self, refund: Refund) -> None:
        self._session.add(refund)
        self._session.flush()
