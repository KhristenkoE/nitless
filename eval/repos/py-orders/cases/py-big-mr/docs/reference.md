# API reference

The public functions, classes and methods of every module with their signatures, as of this
release. Tests and migrations are not listed.

## `app/api/admin.py`

- `def create_product(data: ProductCreate, service: CatalogService=Depends(get_catalog_service)) -> ProductOut`
- `def create_coupon(data: CouponCreate, service: CouponService=Depends(get_coupon_service)) -> CouponOut`
- `def list_coupons(limit: int=Query(50, ge=1, le=100), offset: int=Query(0, ge=0), service: CouponService=Depends(get_coupon_service)) -> Page[CouponOut]`
- `def ship_order(order_id: int, service: OrderService=Depends(get_order_service)) -> OrderOut`

## `app/api/deps.py`

- `def get_session() -> Iterator[Session]` — One transaction per request: committed when the endpoint returns, rolled back on error.
- `def get_principal(authorization: str | None=Header(default=None), settings: Settings=Depends(get_settings)) -> Principal`
- `def current_customer_id(principal: Principal=Depends(get_principal)) -> int`
- `def require_admin(principal: Principal=Depends(get_principal)) -> Principal`
- `def get_payment_gateway(settings: Settings=Depends(get_settings)) -> PaymentGateway`
- `def get_order_service(session: Session=Depends(get_session), settings: Settings=Depends(get_settings)) -> OrderService`
- `def get_payment_service(session: Session=Depends(get_session), gateway: PaymentGateway=Depends(get_payment_gateway)) -> PaymentService`
- `def get_catalog_service(session: Session=Depends(get_session)) -> CatalogService`
- `def get_coupon_service(session: Session=Depends(get_session)) -> CouponService`

## `app/api/health.py`

- `def live() -> HealthOut`
- `def ready(response: Response, engine: Engine=Depends(get_engine)) -> HealthOut`

## `app/api/orders.py`

- `def create_order(data: OrderCreate, customer_id: int=Depends(current_customer_id), service: OrderService=Depends(get_order_service)) -> OrderOut`
- `def list_orders(limit: int=Query(50, ge=1, le=100), offset: int=Query(0, ge=0), customer_id: int=Depends(current_customer_id), service: OrderService=Depends(get_order_service)) -> Page[OrderOut]`
- `def get_order(order_id: int, principal: Principal=Depends(get_principal), service: OrderService=Depends(get_order_service)) -> OrderOut`

## `app/api/payments.py`

- `def create_payment(data: PaymentCreate, idempotency_key: str=Header(alias='Idempotency-Key', min_length=8, max_length=255), customer_id: int=Depends(current_customer_id), service: PaymentService=Depends(get_payment_service)) -> PaymentOut`
- `def refund_payment(payment_id: int, data: RefundCreate, service: PaymentService=Depends(get_payment_service)) -> RefundOut`

## `app/api/products.py`

- `def list_products(limit: int=Query(50, ge=1, le=100), offset: int=Query(0, ge=0), service: CatalogService=Depends(get_catalog_service)) -> Page[ProductOut]`
- `def get_product_by_sku(sku: str, service: CatalogService=Depends(get_catalog_service)) -> ProductOut`
- `def get_product(product_id: int, service: CatalogService=Depends(get_catalog_service)) -> ProductOut`

## `app/core/auth.py`

- `class Principal`
  - `def can_access_customer(self, customer_id: int) -> bool`
- `def issue_token(principal: Principal, secret: str, ttl_seconds: int=3600) -> str` — Used by tests and local tooling; production tokens come from the identity service.
- `def decode_token(token: str, secret: str) -> Principal`

## `app/core/clock.py`

- `def utcnow() -> datetime`

## `app/core/config.py`

- `class Settings(BaseSettings)`
- `def get_settings() -> Settings`

## `app/core/db.py`

- `def get_engine() -> Engine`
- `def get_sessionmaker() -> sessionmaker[Session]`
- `def session_scope() -> Iterator[Session]` — Unit of work for code running outside a request (worker, scripts).

## `app/core/errors.py`

- `class DomainError(Exception)`
- `class InvalidRequestError(DomainError)`
- `class AuthenticationError(DomainError)`
- `class PermissionDeniedError(DomainError)`
- `class NotFoundError(DomainError)`
- `class ConflictError(DomainError)`
- `class UpstreamError(DomainError)`

## `app/core/logging.py`

- `def setup_logging(settings: Settings) -> None`
- `def get_logger(name: str) -> structlog.stdlib.BoundLogger`

## `app/core/money.py`

- `def percent_of(amount_cents: int, basis_points: int) -> int` — Return ``basis_points`` / 10_000 of ``amount_cents``, rounded half up to a cent.
- `def format_cents(amount_cents: int, currency: str) -> str` — Human readable amount for logs and emails, e.g. ``format_cents(123456, "USD") == "1,234.56 USD"``.
- `def split_evenly(amount_cents: int, parts: int) -> list[int]` — Split an amount into ``parts`` integer shares that add up exactly to the amount.

## `app/main.py`

- `def create_app() -> FastAPI`

## `app/models/base.py`

- `class UTCDateTime(TypeDecorator[datetime])` — Timezone-aware timestamp. Rejects naive values and always returns aware UTC datetimes.
  - `def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None`
  - `def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None`
- `class Base(DeclarativeBase)`
- `def now_utc() -> datetime`
- `class TimestampMixin`

## `app/models/coupon.py`

- `class Coupon(TimestampMixin, Base)`
  - `def is_redeemable(self, at: datetime) -> bool`

## `app/models/order.py`

- `class OrderStatus(StrEnum)`
- `class Order(TimestampMixin, Base)`
- `class OrderItem(Base)`

## `app/models/outbox.py`

- `class OutboxEvent(Base)`

## `app/models/payment.py`

- `class PaymentStatus(StrEnum)`
- `class Payment(TimestampMixin, Base)`
- `class Refund(TimestampMixin, Base)`

## `app/models/product.py`

- `class Product(TimestampMixin, Base)`

## `app/repositories/coupons.py`

- `class CouponRepository`
  - `def get_by_code(self, code: str) -> Coupon | None`
  - `def list(self, *, limit: int, offset: int) -> tuple[list[Coupon], int]`
  - `def add(self, coupon: Coupon) -> None`

## `app/repositories/orders.py`

- `class OrderRepository`
  - `def get(self, order_id: int) -> Order | None`
  - `def get_for_update(self, order_id: int) -> Order | None`
  - `def list_for_customer(self, customer_id: int, *, limit: int, offset: int) -> tuple[list[Order], int]`
  - `def add(self, order: Order) -> None`

## `app/repositories/outbox.py`

- `class OutboxRepository`
  - `def add(self, event_type: str, *, aggregate_id: int, payload: dict[str, Any]) -> OutboxEvent`
  - `def fetch_due(self, now: datetime, *, limit: int) -> list[OutboxEvent]`
  - `def mark_delivered(self, event: OutboxEvent, at: datetime) -> None`
  - `def schedule_retry(self, event: OutboxEvent, *, attempts: int, next_attempt_at: datetime) -> None`
  - `def mark_dead(self, event: OutboxEvent, *, attempts: int, at: datetime) -> None`

## `app/repositories/payments.py`

- `class PaymentRepository`
  - `def get(self, payment_id: int) -> Payment | None`
  - `def get_for_update(self, payment_id: int) -> Payment | None`
  - `def get_by_idempotency_key(self, key: str) -> Payment | None`
  - `def add(self, payment: Payment) -> None`
  - `def add_refund(self, refund: Refund) -> None`

## `app/repositories/products.py`

- `class ProductRepository`
  - `def get(self, product_id: int) -> Product | None`
  - `def get_many(self, product_ids: Iterable[int]) -> dict[int, Product]`
  - `def get_by_sku(self, sku: str) -> Product | None`
  - `def sku_exists(self, sku: str) -> bool`
  - `def list_active(self, *, limit: int, offset: int) -> tuple[list[Product], int]`
  - `def add(self, product: Product) -> None`

## `app/schemas/common.py`

- `class Page(BaseModel, Generic[T])`
- `class HealthOut(BaseModel)`

## `app/schemas/coupon.py`

- `class CouponCreate(BaseModel)`
- `class CouponOut(BaseModel)`

## `app/schemas/order.py`

- `class OrderItemIn(BaseModel)`
- `class OrderCreate(BaseModel)`
- `class OrderItemOut(BaseModel)`
- `class OrderOut(BaseModel)`

## `app/schemas/payment.py`

- `class PaymentCreate(BaseModel)`
- `class PaymentOut(BaseModel)`
- `class RefundCreate(BaseModel)`
- `class RefundOut(BaseModel)`

## `app/schemas/product.py`

- `class ProductCreate(BaseModel)`
- `class ProductOut(BaseModel)`

## `app/services/catalog.py`

- `class CatalogService`
  - `def list_products(self, *, limit: int, offset: int) -> tuple[list[Product], int]`
  - `def get_product(self, product_id: int) -> Product`
  - `def get_product_by_sku(self, sku: str) -> Product`
  - `def create_product(self, data: ProductCreate) -> Product`

## `app/services/coupons.py`

- `class CouponService`
  - `def create_coupon(self, data: CouponCreate) -> Coupon`
  - `def list_coupons(self, *, limit: int, offset: int) -> tuple[list[Coupon], int]`

## `app/services/gateway.py`

- `class GatewayResult`
- `class PaymentGateway`
  - `def charge(self, *, amount_cents: int, currency: str, payment_token: str, idempotency_key: str) -> GatewayResult`
  - `def refund(self, *, provider_ref: str, amount_cents: int, idempotency_key: str) -> GatewayResult`

## `app/services/notifier.py`

- `def sign_payload(body: bytes, secret: str, timestamp: int) -> str` — Signature header value: ``t=<unix seconds>,v1=<hex hmac-sha256 of "<t>.<body>">``.
- `class WebhookNotifier`
  - `def deliver(self, event: OutboxEvent) -> bool`

## `app/services/orders.py`

- `class OrderService`
  - `def create_order(self, customer_id: int, data: OrderCreate) -> Order`
  - `def get_order(self, order_id: int, principal: Principal) -> Order`
  - `def list_orders(self, customer_id: int, *, limit: int, offset: int) -> tuple[list[Order], int]`
  - `def mark_shipped(self, order_id: int) -> Order`

## `app/services/outbox_relay.py`

- `class Notifier(Protocol)`
  - `def deliver(self, event: OutboxEvent) -> bool`
- `def backoff(attempts: int) -> timedelta`
- `def relay_pending_events(session: Session, notifier: Notifier, *, batch_size: int, max_attempts: int) -> int` — Deliver due outbox events. Returns how many were delivered. The caller owns the transaction.

## `app/services/payments.py`

- `class PaymentService`
  - `def pay_order(self, order_id: int, *, customer_id: int, payment_token: str, idempotency_key: str) -> Payment`
  - `def refund_payment(self, payment_id: int, *, reason: str, amount_cents: int | None=None) -> Refund`

## `app/services/pricing.py`

- `class Totals`
- `def compute_totals(lines: Iterable[tuple[int, int]], *, discount_cents: int=0, tax_bps: int=0) -> Totals` — Totals for ``(unit_price_cents, quantity)`` lines. Tax is charged on the discounted amount.

## `app/worker.py`

- `def main() -> None`
