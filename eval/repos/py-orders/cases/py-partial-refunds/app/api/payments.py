from fastapi import APIRouter, Depends, Header, status

from app.api.deps import current_customer_id, get_payment_service, require_admin
from app.schemas.payment import PaymentCreate, PaymentOut, RefundCreate, RefundOut
from app.services.payments import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    data: PaymentCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=255),
    customer_id: int = Depends(current_customer_id),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    payment = service.pay_order(
        data.order_id,
        customer_id=customer_id,
        payment_token=data.payment_token,
        idempotency_key=idempotency_key,
    )
    return PaymentOut.model_validate(payment)


@router.post(
    "/{payment_id}/refunds",
    response_model=RefundOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def refund_payment(
    payment_id: int,
    data: RefundCreate,
    service: PaymentService = Depends(get_payment_service),
) -> RefundOut:
    refund = service.refund_payment(payment_id, reason=data.reason, amount_cents=data.amount_cents)
    return RefundOut.model_validate(refund)
