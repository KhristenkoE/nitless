from fastapi import APIRouter, Depends, Query, status

from app.api.deps import current_customer_id, get_order_service, get_principal
from app.core.auth import Principal
from app.schemas.common import Page
from app.schemas.order import OrderCreate, OrderOut
from app.services.orders import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    data: OrderCreate,
    customer_id: int = Depends(current_customer_id),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    order = service.create_order(customer_id, data)
    return OrderOut.model_validate(order)


@router.get("", response_model=Page[OrderOut])
def list_orders(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    customer_id: int = Depends(current_customer_id),
    service: OrderService = Depends(get_order_service),
) -> Page[OrderOut]:
    orders, total = service.list_orders(customer_id, limit=limit, offset=offset)
    return Page[OrderOut](
        items=[OrderOut.model_validate(order) for order in orders], total=total, limit=limit, offset=offset
    )


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    principal: Principal = Depends(get_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    return OrderOut.model_validate(service.get_order(order_id, principal))
