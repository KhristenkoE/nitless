# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Iterator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.auth import Principal, decode_token
from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.services.catalog import CatalogService
from app.services.coupons import CouponService
from app.services.gateway import PaymentGateway
from app.services.orders import OrderService
from app.services.payments import PaymentService


def get_session() -> Iterator[Session]:
    """One transaction per request: committed when the endpoint returns, rolled back on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_principal(
    authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> Principal:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AuthenticationError("missing bearer token")
    return decode_token(authorization.removeprefix("Bearer "), settings.auth_secret.get_secret_value())


def current_customer_id(principal: Principal = Depends(get_principal)) -> int:
    if principal.customer_id is None:
        raise PermissionDeniedError("a customer token is required")
    return principal.customer_id


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise PermissionDeniedError("admin access required")
    return principal


def get_payment_gateway(settings: Settings = Depends(get_settings)) -> PaymentGateway:
    return PaymentGateway(settings)


def get_order_service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> OrderService:
    return OrderService(session, settings)


def get_payment_service(
    session: Session = Depends(get_session), gateway: PaymentGateway = Depends(get_payment_gateway)
) -> PaymentService:
    return PaymentService(session, gateway)


def get_catalog_service(session: Session = Depends(get_session)) -> CatalogService:
    return CatalogService(session)


def get_coupon_service(session: Session = Depends(get_session)) -> CouponService:
    return CouponService(session)
