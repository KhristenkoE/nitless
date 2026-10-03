# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0

def test_list_products_hides_inactive(customer_client, make_product) -> None:
    visible = make_product()
    make_product(active=False)

    response = customer_client.get("/products")

    assert response.status_code == 200
    assert [product["id"] for product in response.json()["items"]] == [visible.id]


def test_get_product(customer_client, make_product) -> None:
    product = make_product(unit_price_cents=1299)

    response = customer_client.get(f"/products/{product.id}")

    assert response.status_code == 200
    assert response.json()["unit_price_cents"] == 1299


def test_get_unknown_product_returns_404(customer_client) -> None:
    assert customer_client.get("/products/12345").status_code == 404


def test_products_require_authentication(client) -> None:
    assert client.get("/products").status_code == 401
