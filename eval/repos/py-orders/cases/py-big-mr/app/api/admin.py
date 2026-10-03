# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0
"""Back-office endpoints. Every route here inherits the router-level admin check."""

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_catalog_service, get_coupon_service, get_order_service, require_admin
from app.schemas.common import Page
from app.schemas.coupon import CouponCreate, CouponOut
from app.schemas.order import OrderOut
from app.schemas.product import ProductCreate, ProductOut
from app.services.catalog import CatalogService
from app.services.coupons import CouponService
from app.services.orders import OrderService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(data: ProductCreate, service: CatalogService = Depends(get_catalog_service)) -> ProductOut:
    return ProductOut.model_validate(service.create_product(data))


@router.post("/coupons", response_model=CouponOut, status_code=status.HTTP_201_CREATED)
def create_coupon(data: CouponCreate, service: CouponService = Depends(get_coupon_service)) -> CouponOut:
    return CouponOut.model_validate(service.create_coupon(data))


@router.get("/coupons", response_model=Page[CouponOut])
def list_coupons(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: CouponService = Depends(get_coupon_service),
) -> Page[CouponOut]:
    coupons, total = service.list_coupons(limit=limit, offset=offset)
    return Page[CouponOut](
        items=[CouponOut.model_validate(coupon) for coupon in coupons], total=total, limit=limit, offset=offset
    )


@router.post("/orders/{order_id}/ship", response_model=OrderOut)
def ship_order(order_id: int, service: OrderService = Depends(get_order_service)) -> OrderOut:
    return OrderOut.model_validate(service.mark_shipped(order_id))
