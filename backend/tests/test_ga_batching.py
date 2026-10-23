from datetime import datetime, timedelta, timezone
from typing import List
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.intelligence.ga.ga_batching import (
    GABatchingEngine,
    GAConfig,
    is_batch_compatible,
)
from backend.app.models.entities import Order, OrderStatus, Rider
from backend.scripts.seed_demo import seed_demo_data


class MockRider:
    def __init__(self, id: str, display_name: str, lat: float, lon: float, w_cap: float, p_cap: int, avail: bool = True):
        self.id = id
        self.display_name = display_name
        self.current_latitude = lat
        self.current_longitude = lon
        self.weight_capacity_kg = w_cap
        self.package_count_capacity = p_cap
        self.is_available = avail


class MockOrder:
    def __init__(self, id: str, p_lat: float, p_lon: float, d_lat: float, d_lon: float, deadline: datetime,
                 w_kg: float, p_cnt: int, pkg_type: str = "PARCEL", handling: str = "", customer_prio: str = "STANDARD"):
        self.id = id
        self.merchant_id = "M-TEST"
        self.pickup_latitude = p_lat
        self.pickup_longitude = p_lon
        self.delivery_latitude = d_lat
        self.delivery_longitude = d_lon
        self.delivery_deadline = deadline
        self.created_at = deadline - timedelta(hours=2)
        self.weight_kg = w_kg
        self.package_count = p_cnt
        self.package_type = pkg_type
        self.handling_requirements = handling
        self.customer_priority = customer_prio
        self.merchant_priority = 1
        self.status = "PENDING"


@pytest.fixture
def sample_fleet():
    return [
        MockRider("R-1", "Rider One", 19.0550, 72.8350, w_cap=25.0, p_cap=10, avail=True),
        MockRider("R-2", "Rider Two", 19.0200, 72.8420, w_cap=20.0, p_cap=8, avail=True),
    ]


@pytest.fixture
def sample_orders():
    now = datetime.now(timezone.utc)
    return [
        MockOrder("O-1", 19.0596, 72.8295, 19.0680, 72.8385, now + timedelta(hours=2), w_kg=2.5, p_cnt=1, pkg_type="PARCEL"),
        MockOrder("O-2", 19.0596, 72.8295, 19.0760, 72.8420, now + timedelta(hours=3), w_kg=3.0, p_cnt=2, pkg_type="PARCEL"),
        MockOrder("O-3", 19.0178, 72.8478, 19.0120, 72.8310, now + timedelta(hours=2), w_kg=5.0, p_cnt=2, pkg_type="PERISHABLE"),
        MockOrder("O-4", 18.9953, 72.8288, 18.9810, 72.8240, now + timedelta(hours=1), w_kg=1.0, p_cnt=1, pkg_type="MEDICAL"),
    ]


def test_ga_partition_integrity_and_no_order_loss(sample_orders, sample_fleet):
    cfg = GAConfig(population_size=15, generations=10, random_seed=42)
    result = GABatchingEngine.optimize_batches(sample_orders, sample_fleet, config=cfg)

    assigned_orders = []
    for b in result.ga_solution.batches:
        for oid in b.order_ids:
            assigned_orders.append(oid)

    # Every order must belong to exactly one proposed batch
    assert len(assigned_orders) == len(sample_orders)
    assert set(assigned_orders) == {o.id for o in sample_orders}
    assert result.preview_mode is True


def test_ga_capacity_constraints_strictly_enforced(sample_orders, sample_fleet):
    cfg = GAConfig(population_size=15, generations=10, random_seed=42)
    result = GABatchingEngine.optimize_batches(sample_orders, sample_fleet, config=cfg)

    rider_map = {r.id: r for r in sample_fleet}
    for b in result.ga_solution.batches:
        rider = rider_map[b.designated_rider_id]
        assert b.total_weight_kg <= rider.weight_capacity_kg
        assert b.total_packages <= rider.package_count_capacity
        assert b.weight_utilization_pct <= 100.0
        assert b.package_utilization_pct <= 100.0


def test_ga_package_compatibility_medical_perishable_conflict(sample_fleet):
    now = datetime.now(timezone.utc)
    medical_order = MockOrder("O-MED", 19.0596, 72.8295, 19.0680, 72.8385, now + timedelta(hours=2), w_kg=1.0, p_cnt=1, pkg_type="MEDICAL")
    perishable_order = MockOrder("O-PERISH", 19.0596, 72.8295, 19.0760, 72.8420, now + timedelta(hours=2), w_kg=2.0, p_cnt=1, pkg_type="PERISHABLE")

    compat, reason = is_batch_compatible([medical_order, perishable_order])
    assert compat is False
    assert "MEDICAL" in reason and "PERISHABLE" in reason

    # GA must NOT group medical and perishable orders together
    cfg = GAConfig(population_size=15, generations=10, random_seed=42)
    result = GABatchingEngine.optimize_batches([medical_order, perishable_order], sample_fleet, config=cfg)

    for b in result.ga_solution.batches:
        # No single batch can contain both O-MED and O-PERISH
        assert not ("O-MED" in b.order_ids and "O-PERISH" in b.order_ids)


def test_ga_precedence_constraint_pickup_before_delivery(sample_orders, sample_fleet):
    cfg = GAConfig(population_size=15, generations=10, random_seed=42)
    result = GABatchingEngine.optimize_batches(sample_orders, sample_fleet, config=cfg)

    for b in result.ga_solution.batches:
        assert b.precedence_verified is True
        pickup_indices = {}
        delivery_indices = {}

        for s in b.stops:
            if s.stop_type == "PICKUP":
                pickup_indices[s.order_id] = s.stop_index
            elif s.stop_type == "DELIVERY":
                delivery_indices[s.order_id] = s.stop_index

        for oid in b.order_ids:
            assert oid in pickup_indices
            assert oid in delivery_indices
            # Pickup must strictly precede delivery
            assert pickup_indices[oid] < delivery_indices[oid]


def test_ga_seeded_runs_are_reproducible(sample_orders, sample_fleet):
    cfg1 = GAConfig(population_size=20, generations=15, random_seed=123)
    res1 = GABatchingEngine.optimize_batches(sample_orders, sample_fleet, config=cfg1)

    cfg2 = GAConfig(population_size=20, generations=15, random_seed=123)
    res2 = GABatchingEngine.optimize_batches(sample_orders, sample_fleet, config=cfg2)

    assert res1.ga_solution.total_batches == res2.ga_solution.total_batches
    assert res1.ga_solution.total_distance_km == res2.ga_solution.total_distance_km
    assert len(res1.ga_solution.batches) == len(res2.ga_solution.batches)
    for b1, b2 in zip(res1.ga_solution.batches, res2.ga_solution.batches):
        assert set(b1.order_ids) == set(b2.order_ids)


def test_ga_unassignable_impossible_order_detection(sample_fleet):
    now = datetime.now(timezone.utc)
    # Order weighing 100kg exceeds max rider capacity of 25kg
    impossible_order = MockOrder("O-HEAVY", 19.0596, 72.8295, 19.0680, 72.8385, now + timedelta(hours=2), w_kg=100.0, p_cnt=1)
    normal_order = MockOrder("O-NORMAL", 19.0596, 72.8295, 19.0760, 72.8420, now + timedelta(hours=2), w_kg=2.0, p_cnt=1)

    cfg = GAConfig(population_size=10, generations=5, random_seed=42)
    result = GABatchingEngine.optimize_batches([impossible_order, normal_order], sample_fleet, config=cfg)

    # Heavy order must be reported as unassignable with explicit reason
    assert len(result.unassignable_orders) == 1
    assert result.unassignable_orders[0].order_id == "O-HEAVY"
    assert "exceeds maximum rider capacity" in result.unassignable_orders[0].reason

    # Normal order assigned
    assert result.ga_solution.total_batches == 1
    assert result.ga_solution.batches[0].order_ids == ["O-NORMAL"]


def test_ga_absent_riders_error(sample_orders):
    # Empty rider list
    with pytest.raises(ValueError) as excinfo:
        GABatchingEngine.optimize_batches(sample_orders, riders=[])
    assert "No available fleet riders" in str(excinfo.value)


def test_baseline_comparisons_structure(sample_orders, sample_fleet):
    cfg = GAConfig(population_size=15, generations=10, random_seed=42)
    result = GABatchingEngine.optimize_batches(sample_orders, sample_fleet, config=cfg)

    # Baseline 1: Independent solo orders
    assert result.independent_baseline.total_batches == len(sample_orders)
    assert result.independent_baseline.total_orders_assigned == len(sample_orders)

    # Baseline 2: Greedy batching
    assert result.greedy_baseline.total_orders_assigned == len(sample_orders)
    assert result.greedy_baseline.total_batches >= 1


def seed_test_db(db: Session):
    """Seed test SQLite in-memory database session with sample merchants, riders, and pending orders."""
    from backend.app.models.entities import Merchant
    now = datetime.now(timezone.utc)
    m = Merchant(
        id="M-TEST-1",
        name="Bandra Bakery",
        merchant_type="Bakery",
        pickup_latitude=19.0596,
        pickup_longitude=72.8295,
        is_active=True,
        created_at=now,
    )
    db.add(m)

    r1 = Rider(
        id="R-TEST-1",
        display_name="Rider Alpha",
        current_latitude=19.0550,
        current_longitude=72.8350,
        weight_capacity_kg=25.0,
        package_count_capacity=10,
        is_available=True,
        created_at=now,
    )
    r2 = Rider(
        id="R-TEST-2",
        display_name="Rider Beta",
        current_latitude=19.0200,
        current_longitude=72.8420,
        weight_capacity_kg=20.0,
        package_count_capacity=8,
        is_available=True,
        created_at=now,
    )
    db.add_all([r1, r2])

    for i in range(1, 5):
        o = Order(
            id=f"ORD-TEST-{i:02d}",
            merchant_id="M-TEST-1",
            pickup_latitude=19.0596,
            pickup_longitude=72.8295,
            delivery_latitude=19.0680 + (i * 0.005),
            delivery_longitude=72.8385 + (i * 0.005),
            delivery_deadline=now + timedelta(hours=i),
            package_type="PARCEL" if i % 2 == 0 else "PERISHABLE",
            weight_kg=2.0 * i,
            package_count=1,
            customer_priority="VIP" if i == 1 else "STANDARD",
            merchant_priority=i,
            status=OrderStatus.PENDING.value,
            created_at=now - timedelta(minutes=10 * i),
        )
        db.add(o)
    db.commit()


def test_api_urgency_preview(client: TestClient, db_session: Session):
    seed_test_db(db_session)
    resp = client.post("/api/v1/optimization/urgency/preview", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview_mode"] is True
    assert len(data["scored_orders"]) == 4
    assert data["summary"]["total_orders"] == 4
    assert "average_urgency" in data["summary"]

    # Verify orders in DB are still PENDING (not altered by preview)
    orders = db_session.query(Order).all()
    for o in orders:
        assert o.status == OrderStatus.PENDING.value


def test_api_batches_preview(client: TestClient, db_session: Session):
    seed_test_db(db_session)
    payload = {
        "ga_config": {
            "population_size": 15,
            "generations": 10,
            "random_seed": 42
        }
    }
    resp = client.post("/api/v1/optimization/batches/preview", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview_mode"] is True
    assert "ga_solution" in data
    assert "independent_baseline" in data
    assert "greedy_baseline" in data
    assert len(data["ga_solution"]["batches"]) >= 1

    # Verify no persistent DB modifications occurred
    orders = db_session.query(Order).all()
    for o in orders:
        assert o.status == OrderStatus.PENDING.value


def test_api_invalid_and_non_pending_orders_validation(client: TestClient, db_session: Session):
    seed_test_db(db_session)
    # Non-existent order ID -> 404
    resp_404 = client.post(
        "/api/v1/optimization/urgency/preview",
        json={"order_ids": ["ORD-NON-EXISTENT"]}
    )
    assert resp_404.status_code == 404
    assert "not found" in resp_404.json()["detail"].lower()

    # Change one order to DELIVERED
    order1 = db_session.get(Order, "ORD-TEST-01")
    order1.status = OrderStatus.DELIVERED.value
    db_session.commit()

    # Urgency preview with non-pending order -> 422
    resp_422 = client.post(
        "/api/v1/optimization/urgency/preview",
        json={"order_ids": ["ORD-TEST-01"]}
    )
    assert resp_422.status_code == 422
    assert "pending" in resp_422.json()["detail"].lower()

    # Batches preview with non-pending order -> 422
    resp_batches_422 = client.post(
        "/api/v1/optimization/batches/preview",
        json={"order_ids": ["ORD-TEST-01"]}
    )
    assert resp_batches_422.status_code == 422
    assert "pending" in resp_batches_422.json()["detail"].lower()

