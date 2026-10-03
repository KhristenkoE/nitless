from app.models import OrderStatus, Payment, PaymentStatus


def _pay(client, order_id: int, key: str = "idem-key-0001"):
    return client.post(
        "/payments",
        json={"order_id": order_id, "payment_token": "tok_visa"},
        headers={"Idempotency-Key": key},
    )


def test_pay_order_captures_and_marks_order_paid(customer_client, make_order, gateway, session):
    order = make_order()

    response = _pay(customer_client, order.id)

    assert response.status_code == 201
    assert response.json()["status"] == "captured"
    assert response.json()["amount_cents"] == order.total_cents
    session.refresh(order)
    assert order.status is OrderStatus.PAID
    assert len(gateway.charges) == 1


def test_pay_order_is_idempotent(customer_client, make_order, gateway):
    order = make_order()

    first = _pay(customer_client, order.id)
    second = _pay(customer_client, order.id)

    assert first.json()["id"] == second.json()["id"]
    assert len(gateway.charges) == 1


def test_declined_payment_leaves_order_pending(customer_client, make_order, gateway, session):
    gateway.approve = False
    order = make_order()

    response = _pay(customer_client, order.id)

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    session.refresh(order)
    assert order.status is OrderStatus.PENDING


def test_paying_a_paid_order_returns_409(customer_client, make_order):
    order = make_order(status=OrderStatus.PAID)

    response = _pay(customer_client, order.id)

    assert response.status_code == 409


def _captured_payment(session, order) -> Payment:
    payment = Payment(
        order_id=order.id,
        status=PaymentStatus.CAPTURED,
        amount_cents=order.total_cents,
        refunded_cents=0,
        currency="USD",
        provider_ref="ch_1",
        idempotency_key=f"seed-{order.id}",
    )
    session.add(payment)
    session.flush()
    return payment


def test_refund_requires_admin(customer_client, make_order, session):
    order = make_order(status=OrderStatus.PAID)
    payment = _captured_payment(session, order)

    response = customer_client.post(f"/payments/{payment.id}/refunds", json={"reason": "damaged"})

    assert response.status_code == 403


def test_refund_refunds_remaining_amount(admin_client, make_order, gateway, session):
    order = make_order(status=OrderStatus.PAID)
    payment = _captured_payment(session, order)

    response = admin_client.post(f"/payments/{payment.id}/refunds", json={"reason": "damaged in transit"})

    assert response.status_code == 201
    assert response.json()["amount_cents"] == order.total_cents
    session.refresh(payment)
    session.refresh(order)
    assert payment.status is PaymentStatus.REFUNDED
    assert order.status is OrderStatus.REFUNDED
    assert gateway.refunds[0]["amount_cents"] == order.total_cents
