from sqlalchemy.orm import Session

from app.core import clock
from app.core.auth import Principal
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.order import Order, OrderItem, OrderStatus
from app.repositories.orders import OrderRepository
from app.repositories.outbox import OutboxRepository
from app.repositories.products import ProductRepository
from app.schemas.order import OrderCreate
from app.services.pricing import compute_totals

log = get_logger(__name__)


class OrderService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._settings = settings
        self._orders = OrderRepository(session)
        self._products = ProductRepository(session)
        self._outbox = OutboxRepository(session)

    def create_order(self, customer_id: int, data: OrderCreate) -> Order:
        products = self._products.get_many(item.product_id for item in data.items)
        missing = sorted({item.product_id for item in data.items} - products.keys())
        if missing:
            raise NotFoundError("product not found", product_ids=missing)

        order = Order(
            customer_id=customer_id,
            status=OrderStatus.PENDING,
            currency=self._settings.default_currency,
            discount_cents=0,
        )
        for item in data.items:
            product = products[item.product_id]
            if not product.active:
                raise ConflictError("product is not available", product_id=product.id)
            if product.currency != order.currency:
                raise ConflictError("product is priced in a different currency", product_id=product.id)
            order.items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item.quantity,
                    unit_price_cents=product.unit_price_cents,
                    line_total_cents=product.unit_price_cents * item.quantity,
                )
            )
        self._apply_totals(order)
        self._orders.add(order)

        self._outbox.add(
            "order.created",
            aggregate_id=order.id,
            payload={"order_id": order.id, "customer_id": customer_id, "total_cents": order.total_cents},
        )
        log.info("order_created", order_id=order.id, customer_id=customer_id, total_cents=order.total_cents)
        return order

    def get_order(self, order_id: int, principal: Principal) -> Order:
        order = self._orders.get(order_id)
        if order is None or not principal.can_access_customer(order.customer_id):
            raise NotFoundError("order not found", order_id=order_id)
        return order

    def list_orders(self, customer_id: int, *, limit: int, offset: int) -> tuple[list[Order], int]:
        return self._orders.list_for_customer(customer_id, limit=limit, offset=offset)

    def mark_shipped(self, order_id: int) -> Order:
        order = self._orders.get_for_update(order_id)
        if order is None:
            raise NotFoundError("order not found", order_id=order_id)
        if order.status is not OrderStatus.PAID:
            raise ConflictError("only paid orders can be shipped", order_id=order_id, status=order.status)
        order.status = OrderStatus.SHIPPED
        order.shipped_at = clock.utcnow()
        self._outbox.add("order.shipped", aggregate_id=order.id, payload={"order_id": order.id})
        log.info("order_shipped", order_id=order.id)
        return order

    def _apply_totals(self, order: Order) -> None:
        totals = compute_totals(
            ((item.unit_price_cents, item.quantity) for item in order.items),
            discount_cents=order.discount_cents,
            tax_bps=self._settings.sales_tax_bps,
        )
        order.subtotal_cents = totals.subtotal_cents
        order.discount_cents = totals.discount_cents
        order.tax_cents = totals.tax_cents
        order.total_cents = totals.total_cents
