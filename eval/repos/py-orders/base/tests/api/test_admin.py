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
