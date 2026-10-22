from fastapi.testclient import TestClient


def test_create_and_list_merchants(client: TestClient):
    # 1. Create merchant
    payload = {
        "id": "M-TEST-01",
        "name": "Test Bakery",
        "merchant_type": "Bakery",
        "pickup_latitude": 19.05,
        "pickup_longitude": 72.83,
        "is_active": True,
    }
    response = client.post("/api/v1/merchants", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["id"] == "M-TEST-01"
    assert created["name"] == "Test Bakery"

    # 2. List merchants
    list_res = client.get("/api/v1/merchants")
    assert list_res.status_code == 200
    merchants = list_res.json()
    assert len(merchants) == 1
    assert merchants[0]["id"] == "M-TEST-01"

    # 3. Duplicate ID conflict
    dup_res = client.post("/api/v1/merchants", json=payload)
    assert dup_res.status_code == 409


def test_merchant_coordinate_validation(client: TestClient):
    # Invalid latitude (> 90)
    invalid_payload = {
        "name": "Invalid Merchant",
        "pickup_latitude": 95.0,
        "pickup_longitude": 72.83,
    }
    res = client.post("/api/v1/merchants", json=invalid_payload)
    assert res.status_code == 422


def test_create_and_update_rider(client: TestClient):
    # 1. Create rider
    payload = {
        "id": "R-TEST-01",
        "display_name": "Test Rider",
        "current_latitude": 19.06,
        "current_longitude": 72.84,
        "weight_capacity_kg": 20.0,
        "package_count_capacity": 10,
        "is_available": True,
    }
    res = client.post("/api/v1/riders", json=payload)
    assert res.status_code == 201
    rider = res.json()
    assert rider["id"] == "R-TEST-01"
    assert rider["is_available"] is True

    # 2. Toggle availability
    patch_res = client.patch("/api/v1/riders/R-TEST-01/availability", json={"is_available": False})
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["is_available"] is False

    # 3. Listing with filter
    active_res = client.get("/api/v1/riders?available_only=true")
    assert active_res.status_code == 200
    assert len(active_res.json()) == 0
