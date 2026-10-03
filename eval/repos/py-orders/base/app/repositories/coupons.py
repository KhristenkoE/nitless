from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.coupon import Coupon


class CouponRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_code(self, code: str) -> Coupon | None:
        """Codes are stored upper-case; lookups are case-insensitive."""
        return self._session.scalars(select(Coupon).where(Coupon.code == code.strip().upper())).one_or_none()

    def list(self, *, limit: int, offset: int) -> tuple[list[Coupon], int]:
        query = select(Coupon)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._session.scalars(query.order_by(Coupon.created_at.desc()).limit(limit).offset(offset)).all()
        return list(rows), total

    def add(self, coupon: Coupon) -> None:
        self._session.add(coupon)
        self._session.flush()
