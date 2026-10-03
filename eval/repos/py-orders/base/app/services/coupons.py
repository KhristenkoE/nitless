from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.core.logging import get_logger
from app.models.coupon import Coupon
from app.repositories.coupons import CouponRepository
from app.schemas.coupon import CouponCreate

log = get_logger(__name__)


class CouponService:
    def __init__(self, session: Session) -> None:
        self._coupons = CouponRepository(session)

    def create_coupon(self, data: CouponCreate) -> Coupon:
        code = data.code.upper()
        if self._coupons.get_by_code(code) is not None:
            raise ConflictError("coupon code already exists", code=code)
        coupon = Coupon(code=code, percent_off=data.percent_off, expires_at=data.expires_at, active=True)
        self._coupons.add(coupon)
        log.info("coupon_created", coupon_id=coupon.id, code=code, percent_off=coupon.percent_off)
        return coupon

    def list_coupons(self, *, limit: int, offset: int) -> tuple[list[Coupon], int]:
        return self._coupons.list(limit=limit, offset=offset)
