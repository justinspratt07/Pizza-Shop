"""
Basic test runner for the PizzaShop Sprint 2 Flask application.

Run:
    python run_tests.py
"""

import server


def test_registration_login_order_and_manager_flow():
    server.CARTS.clear()
    server.ORDERS.clear()
    server.PAYMENTS.clear()
    server.ORDER_EVENT_PIPELINE.clear()
    server.ORDER_CONFIRMATIONS.clear()

    # Backend validation and payment tests from server.py
    server.run_tests()
    assert "33101" in server.SALES_TAX_RATES_BY_ZIP
    assert "331" in server.SALES_TAX_RATES_BY_ZIP_PREFIX

    # Flask route smoke tests
    client = server.app.test_client()

    for route in ["/", "/order", "/register", "/login", "/manage", "/api/menu"]:
        response = client.get(route)
        assert response.status_code == 200, f"{route} returned {response.status_code}"

    # Registration validation: create a user
    import uuid
    test_email = f"student-{uuid.uuid4().hex[:8]}@example.com"
    user_data = {
        "full_name": "Student Tester",
        "email": test_email,
        "phone": "555-222-3333",
        "address": "123 Pizza Street",
        "zip_code": "80202",
        "password": "password123",
        "confirm_password": "password123",
    }
    response = client.post("/register", data=user_data, follow_redirects=True)
    assert response.status_code == 200

    # Login
    response = client.post(
        "/login",
        data={"email": test_email, "password": "password123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Welcome back" in response.data

    # Cart and checkout with successful mock payment
    response = client.post(
        "/cart/add",
        data={"menu_item_id": "p01", "quantity": "2"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Item added to cart" in response.data

    response = client.get("/api/tax-estimate?zip_code=90001")
    assert response.status_code == 200
    estimate = response.get_json()
    assert estimate["zip_code"] == "90001"
    assert estimate["tax_rate"] == str(server.get_sales_tax_rate("90001"))

    response = client.post(
        "/checkout",
        data={
            "name": "Student Tester",
            "phone": "555-222-3333",
            "address": "123 Pizza Street",
            "zip_code": "80202",
            "payment_token": "tok_success",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Payment successful" in response.data

    # Manager login and menu access
    response = client.post(
        "/manage",
        data={"password": server.MANAGER_PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("is_manager") is True

    response = client.get("/manage/menu")
    assert response.status_code == 200
    assert b"Menu administration" in response.data

    response = client.get("/manage/orders")
    assert response.status_code == 200
    assert b"Customer order history" in response.data

    confirmed_order_id = next(
        order.order_id
        for order in server.ORDERS.values()
        if order.status == server.OrderStatus.CONFIRMED
    )
    response = client.post(
        f"/manage/orders/{confirmed_order_id}/refund",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Order refunded" in response.data
    assert server.ORDERS[confirmed_order_id].status == server.OrderStatus.REFUNDED

    response = client.post(
        "/api/orders",
        json={
            "session_id": "manager-cancel-session",
            "name": "Cancel Tester",
            "phone": "555-777-8888",
            "address": "400 Cancel Road",
            "zip_code": "80202",
            "items": [{"menu_item_id": "p02", "quantity": 1}],
        },
    )
    assert response.status_code == 201
    cancel_order_id = response.get_json()["order"]["order_id"]
    response = client.post(
        f"/manage/orders/{cancel_order_id}/cancel",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Order canceled" in response.data
    assert server.ORDERS[cancel_order_id].status == server.OrderStatus.CANCELED

    # Sprint 2 API flow: place order -> create payment intent -> confirm payment
    # -> read confirmation record. This verifies the API data pipeline that links
    # the place-order system with the order-confirmation system.
    response = client.post(
        "/api/orders",
        json={
            "session_id": "api-test-session",
            "name": "API Tester",
            "phone": "555-444-3333",
            "address": "500 Integration Road",
            "zip_code": "90001",
            "items": [{"menu_item_id": "p01", "quantity": 1}],
        },
    )
    assert response.status_code == 201
    order_data = response.get_json()["order"]
    assert order_data["customer"]["zip_code"] == "90001"
    assert order_data["tax_rate"] == str(server.get_sales_tax_rate("90001"))
    order_id = order_data["order_id"]

    response = client.post("/api/payments/intent", json={"order_id": order_id})
    assert response.status_code == 201
    payment_intent = response.get_json()["payment_intent"]
    assert payment_intent["status"] == "pending"
    assert payment_intent["client_secret"].startswith("mock_secret_")

    response = client.post(
        "/api/payments/confirm",
        json={"order_id": order_id, "payment_token": "tok_success"},
    )
    assert response.status_code == 200
    confirmed = response.get_json()
    assert confirmed["order"]["status"] == "confirmed"
    assert "order_confirmation" in confirmed

    response = client.get(f"/api/order-confirmations/{order_id}")
    assert response.status_code == 200
    assert response.get_json()["order_confirmation"]["order_id"] == order_id

    response = client.get("/api/order-events")
    assert response.status_code == 200
    event_types = {event["event_type"] for event in response.get_json()["events"]}
    assert {
        "order_placed",
        "payment_intent_created",
        "payment_succeeded",
        "order_confirmation_created",
    }.issubset(event_types)

    print("All Sprint 2 functional checks passed.")


if __name__ == "__main__":
    test_registration_login_order_and_manager_flow()
