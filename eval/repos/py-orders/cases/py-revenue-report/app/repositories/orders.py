from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus

REVENUE_STATUSES = (OrderStatus.PAID, OrderStatus.SHIPPED)


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, order_id: int) -> Order | None:
        return self._session.get(Order, order_id)

    def get_for_update(self, order_id: int) -> Order | None:
        query = select(Order).where(Order.id == order_id).with_for_update()
        return self._session.scalars(query).one_or_none()

    def list_for_customer(self, customer_id: int, *, limit: int, offset: int) -> tuple[list[Order], int]:
        query = select(Order).where(Order.customer_id == customer_id)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._session.scalars(
            query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), total

    def revenue_between(self, start: datetime, end: datetime) -> tuple[int, int]:
        """Number of orders paid in ``[start, end)`` that were not refunded, and the sum of their totals."""
        query = select(func.count(Order.id), func.coalesce(func.sum(Order.total_cents), 0)).where(
            Order.paid_at >= start,
            Order.paid_at < end,
            Order.status.in_(REVENUE_STATUSES),
        )
        order_count, total_cents = self._session.execute(query).one()
        return int(order_count), int(total_cents)

    def add(self, order: Order) -> None:
        self._session.add(order)
        self._session.flush()
