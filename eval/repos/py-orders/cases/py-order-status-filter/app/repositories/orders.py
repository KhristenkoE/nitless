from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, order_id: int) -> Order | None:
        return self._session.get(Order, order_id)

    def get_for_update(self, order_id: int) -> Order | None:
        query = select(Order).where(Order.id == order_id).with_for_update()
        return self._session.scalars(query).one_or_none()

    def list_for_customer(
        self, customer_id: int, *, status: OrderStatus | None = None, limit: int, offset: int
    ) -> tuple[list[Order], int]:
        query = select(Order).where(Order.customer_id == customer_id)
        if status is not None:
            query = query.where(Order.status == status)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._session.scalars(
            query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), total

    def add(self, order: Order) -> None:
        self._session.add(order)
        self._session.flush()
