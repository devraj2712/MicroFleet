from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend.app.models.entities import OrderStatus


def setup_pending_order(client: TestClient) -> str:
    # Setup merchant
    client.post(
        "/api/v1/merchants",
        json={
            "id": "M-TRANS-01",
            "name": "Transition Merchant",
            "merchant_type": "Grocery",
            "pickup_latitude": 19.01,
            "pickup_longitude": 72.84,
            "is_active": True,
        },
    )

    # Setup order
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    res = client.post(
        "/api/v1/orders",
        json={
            "merchant_id": "M-TRANS-01",
            "delivery_latitude": 19.02,
            "delivery_longitude": 72.85,
            "delivery_deadline": deadline,
            "package_type": "PARCEL",
            "weight_kg": 1.0,
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


def test_valid_order_status_progression(client: TestClient):
    order_id = setup_pending_order(client)

    # PENDING -> BATCHED
    res1 = client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "BATCHED"})
    assert res1.status_code == 200
    assert res1.json()["status"] == "BATCHED"

    # BATCHED -> DISPATCHED
    res2 = client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "DISPATCHED"})
    assert res2.status_code == 200
    assert res2.json()["status"] == "DISPATCHED"

    # DISPATCHED -> DELIVERED
    res3 = client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "DELIVERED"})
    assert res3.status_code == 200
    assert res3.json()["status"] == "DELIVERED"


def test_invalid_order_status_transitions(client: TestClient):
    order_id = setup_pending_order(client)

    # PENDING -> DELIVERED (Illegal skip)
    res = client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "DELIVERED"})
    assert res.status_code == 400
    assert "Illegal order status transition" in res.json()["detail"]

    # Cancel order
    cancel_res = client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "CANCELLED"})
    assert cancel_res.status_code == 200

    # CANCELLED -> DISPATCHED (Terminal state violation)
    res_terminal = client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "DISPATCHED"})
    assert res_terminal.status_code == 400
    assert "Illegal order status transition" in res_terminal.json()["detail"]
