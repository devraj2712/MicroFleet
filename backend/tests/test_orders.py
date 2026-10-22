from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient


def create_sample_merchant(client: TestClient, merchant_id: str = "M-TEST-ORD") -> str:
    res = client.post(
        "/api/v1/merchants",
        json={
            "id": merchant_id,
            "name": "Bandra Central Store",
            "merchant_type": "Retail",
            "pickup_latitude": 19.055,
            "pickup_longitude": 72.835,
            "is_active": True,
        },
    )
    assert res.status_code == 201
    return merchant_id


def test_create_order_success(client: TestClient):
    m_id = create_sample_merchant(client)
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    order_payload = {
        "merchant_id": m_id,
        "delivery_latitude": 19.070,
        "delivery_longitude": 72.845,
        "delivery_deadline": deadline,
        "package_type": "PARCEL",
        "weight_kg": 2.5,
        "package_count": 2,
        "customer_priority": "PREMIUM",
        "merchant_priority": 1,
    }

    res = client.post("/api/v1/orders", json=order_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["id"].startswith("ORD-")
    assert data["merchant_id"] == m_id
    assert data["status"] == "PENDING"
    assert data["pickup_latitude"] == 19.055
    assert data["pickup_longitude"] == 72.835


def test_create_order_unknown_merchant(client: TestClient):
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    order_payload = {
        "merchant_id": "M-NON-EXISTENT",
        "delivery_latitude": 19.070,
        "delivery_longitude": 72.845,
        "delivery_deadline": deadline,
        "package_type": "PARCEL",
        "weight_kg": 2.0,
    }
    res = client.post("/api/v1/orders", json=order_payload)
    assert res.status_code == 404
    assert "does not exist" in res.json()["detail"]


def test_create_order_invalid_inputs(client: TestClient):
    m_id = create_sample_merchant(client, "M-TEST-INVALID")
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    # Invalid delivery latitude (> 90)
    bad_coords = {
        "merchant_id": m_id,
        "delivery_latitude": 120.0,
        "delivery_longitude": 72.845,
        "delivery_deadline": deadline,
        "package_type": "PARCEL",
        "weight_kg": 2.0,
    }
    res = client.post("/api/v1/orders", json=bad_coords)
    assert res.status_code == 422

    # Negative weight
    bad_weight = {
        "merchant_id": m_id,
        "delivery_latitude": 19.07,
        "delivery_longitude": 72.845,
        "delivery_deadline": deadline,
        "package_type": "PARCEL",
        "weight_kg": -5.0,
    }
    res = client.post("/api/v1/orders", json=bad_weight)
    assert res.status_code == 422


def test_get_orders_and_filtering(client: TestClient):
    m_id = create_sample_merchant(client, "M-TEST-FILTER")
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    res = client.post(
        "/api/v1/orders",
        json={
            "merchant_id": m_id,
            "delivery_latitude": 19.070,
            "delivery_longitude": 72.845,
            "delivery_deadline": deadline,
            "package_type": "DOC",
            "weight_kg": 0.5,
        },
    )
    assert res.status_code == 201
    order_id = res.json()["id"]

    # Get single order
    get_res = client.get(f"/api/v1/orders/{order_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == order_id

    # List orders
    list_res = client.get("/api/v1/orders?status=PENDING")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1
