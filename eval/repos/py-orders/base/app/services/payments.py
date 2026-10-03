from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ConflictError, NotFoundError, UpstreamError
from app.core.logging import get_logger
from app.models.order import OrderStatus
from app.models.payment import Payment, PaymentStatus, Refund
from app.repositories.orders import OrderRepository
from app.repositories.outbox import OutboxRepository
from app.repositories.payments import PaymentRepository
from app.services.gateway import PaymentGateway

log = get_logger(__name__)


class PaymentService:
    def __init__(self, session: Session, gateway: PaymentGateway) -> None:
        self._gateway = gateway
        self._orders = OrderRepository(session)
        self._payments = PaymentRepository(session)
        self._outbox = OutboxRepository(session)

    def pay_order(self, order_id: int, *, customer_id: int, payment_token: str, idempotency_key: str) -> Payment:
        existing = self._payments.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.order_id != order_id:
                raise ConflictError("idempotency key was already used for another order")
            log.info("payment_replayed", payment_id=existing.id, order_id=order_id)
            return existing

        order = self._orders.get_for_update(order_id)
        if order is None or order.customer_id != customer_id:
            raise NotFoundError("order not found", order_id=order_id)
        if order.status is not OrderStatus.PENDING:
            raise ConflictError("order is not awaiting payment", order_id=order_id, status=order.status)

        result = self._gateway.charge(
            amount_cents=order.total_cents,
            currency=order.currency,
            payment_token=payment_token,
            idempotency_key=idempotency_key,
        )
        now = clock.utcnow()
        payment = Payment(
            order_id=order.id,
            status=PaymentStatus.CAPTURED if result.approved else PaymentStatus.FAILED,
            amount_cents=order.total_cents,
            refunded_cents=0,
            currency=order.currency,
            provider_ref=result.reference,
            idempotency_key=idempotency_key,
            captured_at=now if result.approved else None,
        )
        self._payments.add(payment)
        if not result.approved:
            log.info("payment_declined", order_id=order.id, payment_id=payment.id, reason=result.decline_reason)
            return payment

        order.status = OrderStatus.PAID
        order.paid_at = now
        self._outbox.add(
            "order.paid",
            aggregate_id=order.id,
            payload={"order_id": order.id, "payment_id": payment.id, "amount_cents": payment.amount_cents},
        )
        log.info("payment_captured", order_id=order.id, payment_id=payment.id, amount_cents=payment.amount_cents)
        return payment

    def refund_payment(self, payment_id: int, *, reason: str) -> Refund:
        payment = self._payments.get_for_update(payment_id)
        if payment is None:
            raise NotFoundError("payment not found", payment_id=payment_id)
        if payment.status is not PaymentStatus.CAPTURED or payment.provider_ref is None:
            raise ConflictError("payment cannot be refunded", payment_id=payment_id, status=payment.status)

        amount = payment.amount_cents - payment.refunded_cents
        result = self._gateway.refund(
            provider_ref=payment.provider_ref,
            amount_cents=amount,
            idempotency_key=f"refund-{payment.id}-{payment.refunded_cents}",
        )
        if not result.approved:
            raise UpstreamError("refund was rejected by the payment gateway", payment_id=payment_id)

        refund = Refund(payment_id=payment.id, amount_cents=amount, reason=reason, provider_ref=result.reference)
        self._payments.add_refund(refund)
        payment.refunded_cents += amount
        payment.status = PaymentStatus.REFUNDED

        order = self._orders.get_for_update(payment.order_id)
        if order is not None:
            order.status = OrderStatus.REFUNDED
        self._outbox.add(
            "payment.refunded",
            aggregate_id=payment.order_id,
            payload={"payment_id": payment.id, "refund_id": refund.id, "amount_cents": amount},
        )
        log.info("payment_refunded", payment_id=payment.id, refund_id=refund.id, amount_cents=amount)
        return refund
