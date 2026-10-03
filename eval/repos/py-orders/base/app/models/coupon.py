from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime


class Coupon(TimestampMixin, Base):
    __tablename__ = "coupons"
    __table_args__ = (CheckConstraint("percent_off BETWEEN 1 AND 100", name="percent_off_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    percent_off: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    def is_redeemable(self, at: datetime) -> bool:
        return self.active and (self.expires_at is None or at < self.expires_at)
