from app.models import OrderStatus


def test_admin_routes_reject_customers(customer_client):
    response = customer_client.post("/admin/coupons", json={"code": "SPRING15", "percent_off": 15})

    assert response.status_code == 403


def test_create_product(admin_client):
    response = admin_client.post(
        "/admin/products", json={"sku": "MUG-001", "name": "Mug", "unit_price_cents": 1200, "stock_quantity": 5}
    )

    assert response.status_code == 201
    assert response.json()["sku"] == "MUG-001"


def test_create_product_with_duplicate_sku_returns_409(admin_client, make_product):
    product = make_product()

    response = admin_client.post("/admin/products", json={"sku": product.sku, "name": "Copy", "unit_price_cents": 100})

    assert response.status_code == 409


def test_create_coupon_normalises_code(admin_client):
    response = admin_client.post("/admin/coupons", json={"code": "spring15", "percent_off": 15})

    assert response.status_code == 201
    assert response.json()["code"] == "SPRING15"
    assert response.json()["percent_off"] == 15


def test_ship_paid_order(admin_client, make_order):
    order = make_order(status=OrderStatus.PAID)

    response = admin_client.post(f"/admin/orders/{order.id}/ship")

    assert response.status_code == 200
    assert response.json()["status"] == "shipped"


def test_ship_pending_order_returns_409(admin_client, make_order):
    order = make_order()

    assert admin_client.post(f"/admin/orders/{order.id}/ship").status_code == 409


def test_revenue_report_counts_paid_and_shipped_orders(admin_client, make_order, session, frozen_clock):
    for status in (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.REFUNDED):
        order = make_order(status=status)
        order.paid_at = frozen_clock
    make_order(status=OrderStatus.PENDING)
    session.flush()

    response = admin_client.get("/admin/reports/revenue", params={"start": "2026-03-01", "end": "2026-03-02"})

    assert response.status_code == 200
    body = response.json()
    assert body["order_count"] == 2
    assert body["gross_revenue"] == 100.0
    assert body["average_order_value"] == 50.0


def test_revenue_report_rejects_inverted_range(admin_client):
    response = admin_client.get("/admin/reports/revenue", params={"start": "2026-03-02", "end": "2026-03-01"})

    assert response.status_code == 422
