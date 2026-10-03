from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrderStatus, OutboxEvent
from tests.conftest import CUSTOMER_ID, OTHER_CUSTOMER_ID


def test_create_order_prices_items_and_records_event(customer_client, make_product, session: Session):
    first = make_product(unit_price_cents=1999)
    second = make_product(unit_price_cents=500)

    response = customer_client.post(
        "/orders",
        json={"items": [{"product_id": first.id, "quantity": 2}, {"product_id": second.id, "quantity": 1}]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["customer_id"] == CUSTOMER_ID
    assert body["status"] == "pending"
    assert body["subtotal_cents"] == 4498
    assert body["total_cents"] == 4498
    assert [item["line_total_cents"] for item in body["items"]] == [3998, 500]
    events = session.scalars(select(OutboxEvent)).all()
    assert [event.event_type for event in events] == ["order.created"]


def test_create_order_with_unknown_product_returns_404(customer_client):
    response = customer_client.post("/orders", json={"items": [{"product_id": 999, "quantity": 1}]})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_create_order_rejects_duplicate_product_lines(customer_client, make_product):
    product = make_product()

    response = customer_client.post(
        "/orders",
        json={"items": [{"product_id": product.id, "quantity": 1}, {"product_id": product.id, "quantity": 2}]},
    )

    assert response.status_code == 422


def test_create_order_with_inactive_product_returns_409(customer_client, make_product):
    product = make_product(active=False)

    response = customer_client.post("/orders", json={"items": [{"product_id": product.id, "quantity": 1}]})

    assert response.status_code == 409


def test_list_orders_returns_only_own_orders(customer_client, make_order):
    own = make_order()
    make_order(customer_id=OTHER_CUSTOMER_ID)

    response = customer_client.get("/orders", params={"limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [order["id"] for order in body["items"]] == [own.id]


def test_get_order_of_another_customer_returns_404(customer_client, make_order):
    order = make_order(customer_id=OTHER_CUSTOMER_ID)

    response = customer_client.get(f"/orders/{order.id}")

    assert response.status_code == 404


def test_cancel_pending_order(customer_client, make_order, session: Session):
    order = make_order()

    response = customer_client.post(f"/orders/{order.id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    session.refresh(order)
    assert order.status is OrderStatus.CANCELLED


def test_cancel_paid_order_returns_409(customer_client, make_order):
    order = make_order(status=OrderStatus.PAID)

    response = customer_client.post(f"/orders/{order.id}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_cancel_another_customers_order_returns_404(customer_client, make_order):
    order = make_order(customer_id=OTHER_CUSTOMER_ID)

    response = customer_client.post(f"/orders/{order.id}/cancel")

    assert response.status_code == 404
