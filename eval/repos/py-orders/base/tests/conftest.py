from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_payment_gateway, get_session
from app.core import clock
from app.core.auth import Principal, issue_token
from app.core.config import get_settings
from app.main import app
from app.models import Base, Coupon, Order, OrderItem, OrderStatus, Product
from app.services.gateway import GatewayResult

FROZEN_NOW = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
CUSTOMER_ID = 4711
OTHER_CUSTOMER_ID = 4712
_sku = count(1)


class FakeGateway:
    def __init__(self) -> None:
        self.approve = True
        self.charges: list[dict[str, object]] = []
        self.refunds: list[dict[str, object]] = []

    def charge(self, **kwargs: object) -> GatewayResult:
        self.charges.append(kwargs)
        if not self.approve:
            return GatewayResult(approved=False, reference=None, decline_reason="insufficient_funds")
        return GatewayResult(approved=True, reference=f"ch_{len(self.charges)}")

    def refund(self, **kwargs: object) -> GatewayResult:
        self.refunds.append(kwargs)
        return GatewayResult(approved=True, reference=f"re_{len(self.refunds)}")


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(clock, "utcnow", lambda: FROZEN_NOW)
    return FROZEN_NOW


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        yield db
    engine.dispose()


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def client(session: Session, gateway: FakeGateway) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        yield session
        session.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_payment_gateway] = lambda: gateway
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth(principal: Principal) -> dict[str, str]:
    token = issue_token(principal, get_settings().auth_secret.get_secret_value())
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def customer_client(client: TestClient) -> TestClient:
    client.headers.update(_auth(Principal(customer_id=CUSTOMER_ID)))
    return client


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    client.headers.update(_auth(Principal(customer_id=None, is_admin=True)))
    return client


@pytest.fixture
def other_customer_headers() -> dict[str, str]:
    return _auth(Principal(customer_id=OTHER_CUSTOMER_ID))


@pytest.fixture
def make_product(session: Session):  # type: ignore[no-untyped-def]
    def _make(*, unit_price_cents: int = 2500, stock_quantity: int = 10, active: bool = True) -> Product:
        product = Product(
            sku=f"SKU-{next(_sku):04d}",
            name="Test product",
            unit_price_cents=unit_price_cents,
            currency="USD",
            active=active,
            stock_quantity=stock_quantity,
        )
        session.add(product)
        session.flush()
        return product

    return _make


@pytest.fixture
def make_order(session: Session, make_product):  # type: ignore[no-untyped-def]
    def _make(*, customer_id: int = CUSTOMER_ID, status: OrderStatus = OrderStatus.PENDING, quantity: int = 2) -> Order:
        product = make_product()
        line_total = product.unit_price_cents * quantity
        order = Order(
            customer_id=customer_id,
            status=status,
            currency="USD",
            subtotal_cents=line_total,
            discount_cents=0,
            tax_cents=0,
            total_cents=line_total,
        )
        order.items.append(
            OrderItem(
                product_id=product.id,
                quantity=quantity,
                unit_price_cents=product.unit_price_cents,
                line_total_cents=line_total,
            )
        )
        session.add(order)
        session.flush()
        return order

    return _make


@pytest.fixture
def make_coupon(session: Session):  # type: ignore[no-untyped-def]
    def _make(*, code: str = "SPRING15", percent_off: int = 15, expires_at: datetime | None = None) -> Coupon:
        coupon = Coupon(code=code, percent_off=percent_off, expires_at=expires_at, active=True)
        session.add(coupon)
        session.flush()
        return coupon

    return _make
