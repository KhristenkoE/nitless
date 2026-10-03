from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboxEvent
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


def test_create_order_reserves_stock(customer_client, make_product, session: Session):
    first = make_product(stock_quantity=5)
    second = make_product(stock_quantity=1)

    response = customer_client.post(
        "/orders",
        json={"items": [{"product_id": first.id, "quantity": 2}, {"product_id": second.id, "quantity": 1}]},
    )

    assert response.status_code == 201
    session.refresh(first)
    session.refresh(second)
    assert first.stock_quantity == 3
    assert second.stock_quantity == 0


def test_create_order_with_insufficient_stock_returns_409(customer_client, make_product, session: Session):
    product = make_product(stock_quantity=1)

    response = customer_client.post("/orders", json={"items": [{"product_id": product.id, "quantity": 2}]})

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"product_id": product.id, "requested": 2, "available": 1}
    session.refresh(product)
    assert product.stock_quantity == 1
    assert session.scalars(select(OutboxEvent)).all() == []


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
