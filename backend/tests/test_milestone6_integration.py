import json
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.models.entities import (
    Batch,
    DispatchDraft,
    Order,
    OrderStatus,
    Rider,
    Route,
    RouteStatus,
    User,
    UserRole,
)
from sqlalchemy.orm import Session
from backend.app.models.entities import (
    Batch,
    DispatchDraft,
    Merchant,
    Order,
    OrderStatus,
    Rider,
    Route,
    RouteStatus,
    User,
    UserRole,
)


def seed_test_database(db: Session):
    now = datetime.now(timezone.utc)
    m1 = Merchant(id="M-MUM-01", name="Bandra Artisan Bakery", merchant_type="Bakery", pickup_latitude=19.0596, pickup_longitude=72.8295, is_active=True, created_at=now)
    m2 = Merchant(id="M-MUM-02", name="Dadar Fresh Produce", merchant_type="Grocery", pickup_latitude=19.0178, pickup_longitude=72.8478, is_active=True, created_at=now)
    m3 = Merchant(id="M-MUM-03", name="Lower Parel Medix", merchant_type="Pharmacy", pickup_latitude=18.9953, pickup_longitude=72.8288, is_active=True, created_at=now)
    db.add_all([m1, m2, m3])

    r1 = Rider(id="R-MUM-01", display_name="Aarav Sharma", current_latitude=19.0550, current_longitude=72.8350, weight_capacity_kg=25.0, package_count_capacity=12, is_available=True, created_at=now)
    r2 = Rider(id="R-MUM-02", display_name="Rohan Patel", current_latitude=19.0200, current_longitude=72.8420, weight_capacity_kg=20.0, package_count_capacity=8, is_available=True, created_at=now)
    r3 = Rider(id="R-MUM-03", display_name="Vikram Jadhav", current_latitude=19.0010, current_longitude=72.8250, weight_capacity_kg=30.0, package_count_capacity=15, is_available=True, created_at=now)
    db.add_all([r1, r2, r3])

    o1 = Order(id="ORD-MUM-01", merchant_id="M-MUM-01", pickup_latitude=19.0596, pickup_longitude=72.8295, delivery_latitude=19.0680, delivery_longitude=72.8385, delivery_deadline=now + timedelta(hours=2), package_type="PARCEL", weight_kg=2.5, package_count=1, status=OrderStatus.PENDING.value, created_at=now)
    o2 = Order(id="ORD-MUM-02", merchant_id="M-MUM-01", pickup_latitude=19.0596, pickup_longitude=72.8295, delivery_latitude=19.0760, delivery_longitude=72.8420, delivery_deadline=now + timedelta(hours=3), package_type="PARCEL", weight_kg=3.0, package_count=2, status=OrderStatus.PENDING.value, created_at=now)
    o3 = Order(id="ORD-MUM-03", merchant_id="M-MUM-02", pickup_latitude=19.0178, pickup_longitude=72.8478, delivery_latitude=19.0120, delivery_longitude=72.8310, delivery_deadline=now + timedelta(hours=2), package_type="PERISHABLE", weight_kg=4.0, package_count=2, status=OrderStatus.PENDING.value, created_at=now)
    o4 = Order(id="ORD-MUM-04", merchant_id="M-MUM-03", pickup_latitude=18.9953, pickup_longitude=72.8288, delivery_latitude=18.9810, delivery_longitude=72.8240, delivery_deadline=now + timedelta(hours=1), package_type="MEDICAL", weight_kg=0.8, package_count=1, customer_priority="VIP", status=OrderStatus.PENDING.value, created_at=now)
    db.add_all([o1, o2, o3, o4])

    u1 = User(id="USR-DEV-MERCHANT", email="merchant@microfleet.dev", role=UserRole.MERCHANT.value, merchant_id="M-MUM-01", rider_id=None, is_active=True, created_at=now)
    u2 = User(id="USR-DEV-RIDER", email="rider@microfleet.dev", role=UserRole.RIDER.value, merchant_id=None, rider_id="R-MUM-01", is_active=True, created_at=now)
    u3 = User(id="USR-DEV-DISPATCHER", email="dispatcher@microfleet.dev", role=UserRole.DISPATCHER.value, merchant_id=None, rider_id=None, is_active=True, created_at=now)
    u4 = User(id="USR-DEV-ADMIN", email="admin@microfleet.dev", role=UserRole.ADMIN.value, merchant_id=None, rider_id=None, is_active=True, created_at=now)
    db.add_all([u1, u2, u3, u4])
    db.commit()


@pytest.fixture(autouse=True)
def setup_seed(db_session: Session):
    """Ensure database has fresh seeded data before each test."""
    seed_test_database(db_session)


# ---------------------------------------------------------------------------
# 1. AUTHENTICATION & ROLE-BASED ACCESS CONTROL TESTS
# ---------------------------------------------------------------------------

def test_auth_registration_merchant_and_rider_success(client: TestClient):
    # Register merchant
    res_m = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new_merchant@test.com",
            "password": "Password123!",
            "role": "MERCHANT",
            "display_name": "New Test Merchant",
            "merchant_type": "Grocery",
        },
    )
    assert res_m.status_code == 201
    data_m = res_m.json()
    assert data_m["user"]["role"] == "MERCHANT"
    assert data_m["user"]["merchant_id"] is not None
    assert data_m["access_token"].startswith("dev-token:")

    # Register rider
    res_r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new_rider@test.com",
            "password": "Password123!",
            "role": "RIDER",
            "display_name": "New Test Rider",
            "weight_capacity_kg": 25.0,
            "package_count_capacity": 15,
        },
    )
    assert res_r.status_code == 201
    data_r = res_r.json()
    assert data_r["user"]["role"] == "RIDER"
    assert data_r["user"]["rider_id"] is not None


def test_auth_self_registration_as_admin_or_dispatcher_rejected(client: TestClient):
    # Attempting to register as DISPATCHER directly
    res1 = client.post(
        "/api/v1/auth/register",
        json={"email": "hacker@test.com", "role": "DISPATCHER"},
    )
    assert res1.status_code == 422 or res1.status_code == 400

    # Attempting to register as ADMIN directly
    res2 = client.post(
        "/api/v1/auth/register",
        json={"email": "hacker2@test.com", "role": "ADMIN"},
    )
    assert res2.status_code == 422 or res2.status_code == 400


def test_admin_provisioning_endpoint(client: TestClient):
    # Valid secret
    res_ok = client.post(
        "/api/v1/auth/provision-admin",
        json={
            "email": "ops_lead@microfleet.dev",
            "admin_secret": settings.ADMIN_PROVISION_SECRET,
            "role": "DISPATCHER",
        },
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["role"] == "DISPATCHER"

    # Invalid secret
    res_bad = client.post(
        "/api/v1/auth/provision-admin",
        json={
            "email": "bad_actor@test.com",
            "admin_secret": "wrong-secret-key",
            "role": "ADMIN",
        },
    )
    assert res_bad.status_code == 403


def test_auth_login_dev_mode_and_profile_me(client: TestClient):
    # Login as merchant
    res_login = client.post(
        "/api/v1/auth/login",
        json={"email": "merchant@microfleet.dev"},
    )
    assert res_login.status_code == 200
    token = res_login.json()["access_token"]
    assert res_login.json()["user"]["role"] == "MERCHANT"

    # Call /auth/me with Bearer token
    res_me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_me.status_code == 200
    assert res_me.json()["email"] == "merchant@microfleet.dev"
    assert res_me.json()["merchant_id"] == "M-MUM-01"


def test_firebase_mode_strict_token_enforcement(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "firebase")

    # Missing token in firebase mode -> 401
    res_missing = client.get("/api/v1/auth/me")
    assert res_missing.status_code == 401
    assert "Missing Bearer token" in res_missing.json()["detail"]

    # Invalid token in firebase mode -> 401 or 503
    res_invalid = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer fake-invalid-firebase-token"},
    )
    assert res_invalid.status_code in [401, 503]


# ---------------------------------------------------------------------------
# 2. MERCHANT WORKFLOW & DATA ISOLATION TESTS
# ---------------------------------------------------------------------------

def test_merchant_order_creation_and_data_isolation(client: TestClient):
    now = datetime.now(timezone.utc)
    deadline = (now + timedelta(hours=3)).isoformat()

    # Merchant M-MUM-01 creates order for M-MUM-01 -> SUCCESS
    res_ok = client.post(
        "/api/v1/orders",
        json={
            "merchant_id": "M-MUM-01",
            "delivery_latitude": 19.0680,
            "delivery_longitude": 72.8385,
            "delivery_deadline": deadline,
            "package_type": "PARCEL",
            "weight_kg": 2.0,
            "package_count": 1,
        },
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_ok.status_code == 201
    assert res_ok.json()["merchant_id"] == "M-MUM-01"

    # Merchant M-MUM-01 attempts to create order for M-MUM-02 -> FORBIDDEN (403)
    res_tamper = client.post(
        "/api/v1/orders",
        json={
            "merchant_id": "M-MUM-02",
            "delivery_latitude": 19.0680,
            "delivery_longitude": 72.8385,
            "delivery_deadline": deadline,
            "package_type": "PARCEL",
            "weight_kg": 2.0,
            "package_count": 1,
        },
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_tamper.status_code == 403
    assert "Access denied" in res_tamper.json()["detail"]

    # Merchant listing orders only receives M-MUM-01 orders
    res_list = client.get(
        "/api/v1/orders",
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_list.status_code == 200
    orders = res_list.json()
    assert len(orders) > 0
    for o in orders:
        assert o["merchant_id"] == "M-MUM-01"


# ---------------------------------------------------------------------------
# 3. DISPATCH PREVIEW CONSISTENCY FIX & METRICS AGREEMENT TESTS
# ---------------------------------------------------------------------------

def test_dispatch_preview_metrics_consistency_rl_and_baselines(client: TestClient):
    res = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={
            "policy_choice": "rl",
            "random_seed": 42,
            "aco_config": {"num_ants": 5, "max_iterations": 5, "random_seed": 42},
            "ga_config": {"population_size": 15, "generations": 10, "random_seed": 42},
        },
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res.status_code == 200
    data = res.json()

    # Draft ID & expiry returned
    assert data["preview_id"] is not None
    assert data["preview_id"].startswith("DRAFT-")
    assert data["expires_at"] is not None

    summary = data["summary"]
    total_candidates = summary["total_candidate_batches"]
    assigned_count = summary["assigned_batches_count"]
    unassigned_count = summary["unassigned_batches_count"]

    # 1. RL Summary internal accounting: assigned + unassigned == total candidate batches
    assert assigned_count + unassigned_count == total_candidates
    expected_pct = round((assigned_count / max(1, total_candidates)) * 100.0, 1)
    assert summary["percentage_batches_assigned"] == expected_pct

    # 2. Check each Baseline policy: must evaluate identical total candidate batches
    comps = data["baseline_comparisons"]
    for b_name, bm in comps.items():
        b_assigned = bm["assigned_count"]
        b_unassigned = bm["unassigned_count"]
        # Baseline total batches evaluated MUST equal total_candidates
        assert b_assigned + b_unassigned == total_candidates, (
            f"Baseline '{b_name}' has sum {b_assigned + b_unassigned} != total_candidate_batches {total_candidates}"
        )
        # Denominator for percentage assigned must be total_candidates
        expected_b_pct = round((b_assigned / max(1, total_candidates)) * 100.0, 1)
        assert bm["percentage_batches_assigned"] == expected_b_pct, (
            f"Baseline '{b_name}' pct {bm['percentage_batches_assigned']} != expected {expected_b_pct}"
        )


# ---------------------------------------------------------------------------
# 4. SAFE DISPATCH COMMIT WORKFLOW & TRANSACTIONAL PERSISTENCE TESTS
# ---------------------------------------------------------------------------

def test_dispatch_commit_workflow_and_transactional_persistence(client: TestClient):
    # Step 1: Generate preview
    res_prev = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={
            "policy_choice": "rl",
            "random_seed": 42,
            "aco_config": {"num_ants": 5, "max_iterations": 5, "random_seed": 42},
            "ga_config": {"population_size": 15, "generations": 10, "random_seed": 42},
        },
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_prev.status_code == 200
    prev_data = res_prev.json()
    preview_id = prev_data["preview_id"]

    # Step 2: Attempt commit by merchant -> 403 Forbidden
    res_unauth = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": preview_id},
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_unauth.status_code == 403

    # Step 3: Dispatcher commits the draft -> 200 OK
    res_commit = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": preview_id},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_commit.status_code == 200
    commit_data = res_commit.json()
    assert commit_data["status"] == "committed"
    assert commit_data["preview_id"] == preview_id
    assert len(commit_data["committed_batches"]) > 0

    # Step 4: Verify affected orders in database transitioned to DISPATCHED
    committed_order_ids = []
    for b in commit_data["committed_batches"]:
        committed_order_ids.extend(b["order_ids"])

    for oid in committed_order_ids:
        res_o = client.get(f"/api/v1/orders/{oid}")
        assert res_o.status_code == 200
        assert res_o.json()["status"] == "DISPATCHED"
        assert res_o.json()["assigned_batch_id"] is not None
        assert res_o.json()["assigned_rider_name"] is not None

    # Step 5: Idempotency check — attempting to commit the same draft again -> 400 Bad Request
    res_repeat = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": preview_id},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_repeat.status_code == 400
    assert "already committed" in res_repeat.json()["detail"].lower()


def test_dispatch_commit_rejection_for_expired_or_tampered_drafts(client: TestClient, db_session):
    # Non-existent preview_id -> 404
    res_404 = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": "DRAFT-NONEXISTENT"},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_404.status_code == 404

    # Expired draft -> 400
    expired_draft = DispatchDraft(
        id="DRAFT-EXPIRED-TEST",
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        is_committed=False,
        policy_name="rl",
        snapshot_json=json.dumps({"assignments": []}),
    )
    db_session.add(expired_draft)
    db_session.commit()

    res_exp = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": "DRAFT-EXPIRED-TEST"},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_exp.status_code == 400
    assert "expired" in res_exp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 5. RIDER DELIVERY PROGRESSION & ISOLATION TESTS
# ---------------------------------------------------------------------------

def test_rider_workflow_assigned_routes_and_progression(client: TestClient, db_session: Session):
    # Step 1: Dispatch plan to commit assignments
    res_prev = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={
            "policy_choice": "rl",
            "random_seed": 42,
            "aco_config": {"num_ants": 5, "max_iterations": 5, "random_seed": 42},
            "ga_config": {"population_size": 15, "generations": 10, "random_seed": 42},
        },
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    preview_id = res_prev.json()["preview_id"]
    res_commit = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": preview_id},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    committed_batches = res_commit.json()["committed_batches"]
    first_batch = committed_batches[0]
    assigned_rider_id = first_batch["assigned_rider_id"]
    route_id = first_batch["route_id"]
    assigned_orders = first_batch["order_ids"]

    # Step 2: Unrelated rider check (if rider@microfleet.dev is not the assigned rider, verify 403)
    if assigned_rider_id != "R-MUM-01":
        res_unauth = client.get(
            f"/api/v1/riders/{assigned_rider_id}/assigned-routes",
            headers={"X-Dev-User-Email": "rider@microfleet.dev"},
        )
        assert res_unauth.status_code == 403
        assert "Access denied" in res_unauth.json()["detail"]

    # Step 3: Ensure user exists for the assigned rider
    assigned_email = f"rider_{assigned_rider_id.lower()}@microfleet.dev"
    res_reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": assigned_email,
            "role": "RIDER",
            "display_name": f"Assigned Rider {assigned_rider_id}",
        },
    )
    # If already exists or created, bind rider_id
    from backend.app.models.entities import User
    user_record = db_session.query(User).filter(User.email == assigned_email).first()
    if user_record:
        user_record.rider_id = assigned_rider_id
        db_session.commit()

    # Step 4: Authorized rider checks their assigned routes
    res_routes = client.get(
        f"/api/v1/riders/{assigned_rider_id}/assigned-routes",
        headers={"X-Dev-User-Email": assigned_email},
    )
    assert res_routes.status_code == 200
    routes_list = res_routes.json()
    assert len(routes_list) > 0
    route_obj = routes_list[0]
    assert route_obj["route_id"] == route_id
    assert len(route_obj["ordered_stops"]) > 0

    # Step 5: Authorized rider starts the assigned route
    res_start = client.post(
        f"/api/v1/riders/{assigned_rider_id}/routes/{route_id}/start",
        headers={"X-Dev-User-Email": assigned_email},
    )
    assert res_start.status_code == 200
    assert res_start.json()["route_status"] == "IN_PROGRESS"

    # Step 6: Progress orders: DISPATCHED -> PICKED_UP -> DELIVERED
    target_oid = assigned_orders[0]

    # Pickup event
    res_pickup = client.patch(
        f"/api/v1/orders/{target_oid}/status",
        json={"status": "PICKED_UP"},
        headers={"X-Dev-User-Email": assigned_email},
    )
    assert res_pickup.status_code == 200
    assert res_pickup.json()["status"] == "PICKED_UP"

    # Delivery event
    res_deliver = client.patch(
        f"/api/v1/orders/{target_oid}/status",
        json={"status": "DELIVERED"},
        headers={"X-Dev-User-Email": assigned_email},
    )
    assert res_deliver.status_code == 200
    assert res_deliver.json()["status"] == "DELIVERED"


def test_security_role_restrictions_negative_checks(client: TestClient, db_session: Session):
    """Verify that unauthorized roles are strictly forbidden across endpoints."""
    # 1. Merchant calling optimization dispatch/preview -> 403 Forbidden
    res_m_prev = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={"policy_choice": "rl"},
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_m_prev.status_code == 403
    assert "Access denied" in res_m_prev.json()["detail"]

    # 2. Merchant calling dispatch/commit -> 403 Forbidden
    res_m_commit = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": "DRAFT-TEST"},
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_m_commit.status_code == 403

    # 3. Merchant viewing rider assigned routes -> 403 Forbidden
    res_m_routes = client.get(
        "/api/v1/riders/R-MUM-01/assigned-routes",
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_m_routes.status_code == 403

    # 4. Merchant attempting to start a rider route -> 403 Forbidden
    res_m_start = client.post(
        "/api/v1/riders/R-MUM-01/routes/ROUTE-TEST/start",
        headers={"X-Dev-User-Email": "merchant@microfleet.dev"},
    )
    assert res_m_start.status_code == 403

    # 5. Rider attempting to call dispatch/preview -> 403 Forbidden
    res_r_prev = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={"policy_choice": "rl"},
        headers={"X-Dev-User-Email": "rider@microfleet.dev"},
    )
    assert res_r_prev.status_code == 403

    # 6. Rider attempting to call dispatch/commit -> 403 Forbidden
    res_r_commit = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": "DRAFT-TEST"},
        headers={"X-Dev-User-Email": "rider@microfleet.dev"},
    )
    assert res_r_commit.status_code == 403


def test_dispatch_commit_revalidation_and_rollback_on_stale_or_ineligible_entities(client: TestClient, db_session: Session):
    """Verify commit revalidation: non-pending orders, ineligible riders, and tampered selections fail and rollback."""
    # Step 1: Generate valid preview
    res_prev = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={
            "policy_choice": "rl",
            "random_seed": 42,
            "aco_config": {"num_ants": 5, "max_iterations": 5, "random_seed": 42},
            "ga_config": {"population_size": 15, "generations": 10, "random_seed": 42},
        },
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_prev.status_code == 200
    prev_data = res_prev.json()
    preview_id = prev_data["preview_id"]
    assigned_batches = prev_data["assignments"]
    target_batch = assigned_batches[0]
    target_oid = target_batch["order_ids"][0]
    assigned_rider_id = target_batch["assigned_rider_id"]

    # Test Case A: Tampered approved_batch_ids -> 400 Bad Request
    res_tampered_batch = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": preview_id, "approved_batch_ids": ["BATCH-DOES-NOT-EXIST"]},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_tampered_batch.status_code == 400
    assert "None of the specified 'approved_batch_ids' matched" in res_tampered_batch.json()["detail"]

    # Test Case B: Order becomes non-pending before commit (stale plan) -> 409 Conflict & Transaction Rollback
    ord_obj = db_session.get(Order, target_oid)
    ord_obj.status = OrderStatus.CANCELLED.value
    db_session.commit()

    res_stale = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": preview_id},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_stale.status_code == 409
    assert "no longer PENDING" in res_stale.json()["detail"]

    # Verify rollback: draft remains uncommitted, no Batch records created
    draft = db_session.get(DispatchDraft, preview_id)
    assert not draft.is_committed
    assert db_session.query(Batch).count() == 0

    # Restore order status to PENDING
    ord_obj.status = OrderStatus.PENDING.value
    db_session.commit()

    # Test Case C: Assigned rider becomes unavailable before commit -> 400 Bad Request & Rollback
    rider_obj = db_session.get(Rider, assigned_rider_id)
    rider_obj.is_available = False
    db_session.commit()

    res_ineligible_rider = client.post(
        "/api/v1/optimization/dispatch/commit",
        json={"preview_id": preview_id},
        headers={"X-Dev-User-Email": "dispatcher@microfleet.dev"},
    )
    assert res_ineligible_rider.status_code == 400
    assert "no longer available" in res_ineligible_rider.json()["detail"]

    # Verify rollback again
    draft = db_session.get(DispatchDraft, preview_id)
    assert not draft.is_committed
    assert db_session.query(Batch).count() == 0
