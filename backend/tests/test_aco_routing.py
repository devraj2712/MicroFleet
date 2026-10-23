import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.intelligence.aco.aco_routing import (
    ACOConfig,
    ACORoutingEngine,
    BatchRouteResult,
    RiderRouteOption,
    RouteEvent,
    RouteStop,
    RoutesPreviewResult,
    evaluate_route_stops,
    run_greedy_baseline_route,
    validate_route,
)
from backend.app.intelligence.ga.ga_batching import BatchResult, StopPreview
from backend.app.main import app
from backend.app.models.entities import Order, OrderStatus, Rider
from backend.scripts.seed_demo import seed_demo_data


class DummyRider:
    def __init__(
        self,
        id: str,
        display_name: str,
        lat: float,
        lon: float,
        w_cap: float = 20.0,
        p_cap: int = 10,
        avail: bool = True,
    ):
        self.id = id
        self.display_name = display_name
        self.current_latitude = lat
        self.current_longitude = lon
        self.weight_capacity_kg = w_cap
        self.package_count_capacity = p_cap
        self.is_available = avail


class DummyOrder:
    def __init__(
        self,
        id: str,
        p_lat: float,
        p_lon: float,
        d_lat: float,
        d_lon: float,
        deadline: datetime,
        w_kg: float = 2.0,
        p_cnt: int = 1,
        pkg_type: str = "PARCEL",
        handling: str = "",
    ):
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
        self.customer_priority = "STANDARD"
        self.status = "PENDING"


@pytest.fixture
def mock_orders_and_rider():
    now = datetime.now(timezone.utc)
    rider = DummyRider("R-1", "Test Rider Alpha", lat=19.0500, lon=72.8300, w_cap=15.0, p_cap=6)
    order1 = DummyOrder(
        "ORD-1",
        p_lat=19.0520, p_lon=72.8320,
        d_lat=19.0580, d_lon=72.8360,
        deadline=now + timedelta(hours=1),
        w_kg=3.0, p_cnt=1,
    )
    order2 = DummyOrder(
        "ORD-2",
        p_lat=19.0530, p_lon=72.8310,
        d_lat=19.0620, d_lon=72.8400,
        deadline=now + timedelta(hours=2),
        w_kg=4.0, p_cnt=2,
    )
    return [order1, order2], rider, now


def test_route_event_and_stop_modeling(mock_orders_and_rider):
    orders, rider, now = mock_orders_and_rider
    events: List[RouteEvent] = [
        RouteEvent(
            event_id=f"R_{rider.id}",
            event_type="ORIGIN",
            latitude=rider.current_latitude,
            longitude=rider.current_longitude,
            demand_weight_kg=0.0,
            demand_package_count=0,
        ),
        RouteEvent(
            event_id=f"P_{orders[0].id}",
            order_id=orders[0].id,
            event_type="PICKUP",
            latitude=orders[0].pickup_latitude,
            longitude=orders[0].pickup_longitude,
            demand_weight_kg=orders[0].weight_kg,
            demand_package_count=orders[0].package_count,
        ),
        RouteEvent(
            event_id=f"D_{orders[0].id}",
            order_id=orders[0].id,
            event_type="DELIVERY",
            latitude=orders[0].delivery_latitude,
            longitude=orders[0].delivery_longitude,
            deadline=orders[0].delivery_deadline,
            demand_weight_kg=-orders[0].weight_kg,
            demand_package_count=-orders[0].package_count,
        ),
    ]

    assert events[0].event_type == "ORIGIN"
    assert events[1].demand_weight_kg == 3.0
    assert events[1].demand_package_count == 1
    assert events[2].demand_weight_kg == -3.0
    assert events[2].demand_package_count == -1


def test_route_validation_precedence_enforcement(mock_orders_and_rider):
    orders, rider, now = mock_orders_and_rider
    order = orders[0]

    # Valid route: Origin -> Pickup -> Delivery
    valid_stops = [
        RouteStop(
            stop_index=0, event_id="R_R-1", event_type="ORIGIN",
            latitude=rider.current_latitude, longitude=rider.current_longitude,
            arrival_time=now, arrival_offset_seconds=0.0, departure_offset_seconds=0.0,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
        RouteStop(
            stop_index=1, event_id=f"P_{order.id}", order_id=order.id, event_type="PICKUP",
            latitude=order.pickup_latitude, longitude=order.pickup_longitude,
            arrival_time=now + timedelta(seconds=120), arrival_offset_seconds=120.0, departure_offset_seconds=300.0,
            onboard_weight_kg=order.weight_kg, onboard_packages=order.package_count,
        ),
        RouteStop(
            stop_index=2, event_id=f"D_{order.id}", order_id=order.id, event_type="DELIVERY",
            latitude=order.delivery_latitude, longitude=order.delivery_longitude,
            arrival_time=now + timedelta(seconds=600), arrival_offset_seconds=600.0, departure_offset_seconds=780.0,
            deadline=order.delivery_deadline, deadline_slack_seconds=3000.0, is_on_time=True,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
    ]

    is_valid, reasons = validate_route(valid_stops, [order], rider)
    assert is_valid is True
    assert len(reasons) == 0

    # Inverted route: Origin -> Delivery -> Pickup (Violation!)
    invalid_stops = [
        RouteStop(
            stop_index=0, event_id="R_R-1", event_type="ORIGIN",
            latitude=rider.current_latitude, longitude=rider.current_longitude,
            arrival_time=now, arrival_offset_seconds=0.0, departure_offset_seconds=0.0,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
        RouteStop(
            stop_index=1, event_id=f"D_{order.id}", order_id=order.id, event_type="DELIVERY",
            latitude=order.delivery_latitude, longitude=order.delivery_longitude,
            arrival_time=now + timedelta(seconds=120), arrival_offset_seconds=120.0, departure_offset_seconds=300.0,
            deadline=order.delivery_deadline, deadline_slack_seconds=3480.0, is_on_time=True,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
        RouteStop(
            stop_index=2, event_id=f"P_{order.id}", order_id=order.id, event_type="PICKUP",
            latitude=order.pickup_latitude, longitude=order.pickup_longitude,
            arrival_time=now + timedelta(seconds=600), arrival_offset_seconds=600.0, departure_offset_seconds=780.0,
            onboard_weight_kg=order.weight_kg, onboard_packages=order.package_count,
        ),
    ]

    is_valid, reasons = validate_route(invalid_stops, [order], rider)
    assert is_valid is False
    assert any("Precedence violation" in r for r in reasons)


def test_route_validation_cumulative_capacity_throughout_route():
    now = datetime.now(timezone.utc)
    rider = DummyRider("R-SMALL", "Small Capacity Rider", 19.0500, 72.8300, w_cap=10.0, p_cap=5)
    order1 = DummyOrder("O-A", 19.0510, 72.8310, 19.0550, 72.8350, now + timedelta(hours=2), w_kg=6.0, p_cnt=2)
    order2 = DummyOrder("O-B", 19.0520, 72.8320, 19.0560, 72.8360, now + timedelta(hours=2), w_kg=6.0, p_cnt=2)

    # Route that picks up both orders first: onboard load = 6 + 6 = 12kg > 10kg capacity!
    violating_stops = [
        RouteStop(
            stop_index=0, event_id="R_R-SMALL", event_type="ORIGIN",
            latitude=19.0500, longitude=72.8300, arrival_time=now,
            arrival_offset_seconds=0.0, departure_offset_seconds=0.0,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
        RouteStop(
            stop_index=1, event_id="P_O-A", order_id="O-A", event_type="PICKUP",
            latitude=19.0510, longitude=72.8310, arrival_time=now + timedelta(seconds=100),
            arrival_offset_seconds=100.0, departure_offset_seconds=280.0,
            onboard_weight_kg=6.0, onboard_packages=2,
        ),
        RouteStop(
            stop_index=2, event_id="P_O-B", order_id="O-B", event_type="PICKUP",
            latitude=19.0520, longitude=72.8320, arrival_time=now + timedelta(seconds=400),
            arrival_offset_seconds=400.0, departure_offset_seconds=580.0,
            onboard_weight_kg=12.0, onboard_packages=4,  # VIOLATION HERE!
        ),
        RouteStop(
            stop_index=3, event_id="D_O-A", order_id="O-A", event_type="DELIVERY",
            latitude=19.0550, longitude=72.8350, arrival_time=now + timedelta(seconds=800),
            arrival_offset_seconds=800.0, departure_offset_seconds=980.0,
            deadline=order1.delivery_deadline, deadline_slack_seconds=6400.0, is_on_time=True,
            onboard_weight_kg=6.0, onboard_packages=2,
        ),
        RouteStop(
            stop_index=4, event_id="D_O-B", order_id="O-B", event_type="DELIVERY",
            latitude=19.0560, longitude=72.8360, arrival_time=now + timedelta(seconds=1200),
            arrival_offset_seconds=1200.0, departure_offset_seconds=1380.0,
            deadline=order2.delivery_deadline, deadline_slack_seconds=6000.0, is_on_time=True,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
    ]

    is_valid, reasons = validate_route(violating_stops, [order1, order2], rider)
    assert is_valid is False
    assert any("Weight capacity exceeded at stop 2" in r for r in reasons)

    # Interleaved route: P1 -> D1 -> P2 -> D2. Peak onboard weight is 6.0kg <= 10.0kg. Valid!
    interleaved_stops = [
        RouteStop(
            stop_index=0, event_id="R_R-SMALL", event_type="ORIGIN",
            latitude=19.0500, longitude=72.8300, arrival_time=now,
            arrival_offset_seconds=0.0, departure_offset_seconds=0.0,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
        RouteStop(
            stop_index=1, event_id="P_O-A", order_id="O-A", event_type="PICKUP",
            latitude=19.0510, longitude=72.8310, arrival_time=now + timedelta(seconds=100),
            arrival_offset_seconds=100.0, departure_offset_seconds=280.0,
            onboard_weight_kg=6.0, onboard_packages=2,
        ),
        RouteStop(
            stop_index=2, event_id="D_O-A", order_id="O-A", event_type="DELIVERY",
            latitude=19.0550, longitude=72.8350, arrival_time=now + timedelta(seconds=500),
            arrival_offset_seconds=500.0, departure_offset_seconds=680.0,
            deadline=order1.delivery_deadline, deadline_slack_seconds=6700.0, is_on_time=True,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
        RouteStop(
            stop_index=3, event_id="P_O-B", order_id="O-B", event_type="PICKUP",
            latitude=19.0520, longitude=72.8320, arrival_time=now + timedelta(seconds=800),
            arrival_offset_seconds=800.0, departure_offset_seconds=980.0,
            onboard_weight_kg=6.0, onboard_packages=2,
        ),
        RouteStop(
            stop_index=4, event_id="D_O-B", order_id="O-B", event_type="DELIVERY",
            latitude=19.0560, longitude=72.8360, arrival_time=now + timedelta(seconds=1200),
            arrival_offset_seconds=1200.0, departure_offset_seconds=1380.0,
            deadline=order2.delivery_deadline, deadline_slack_seconds=6000.0, is_on_time=True,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
    ]

    is_valid, reasons = validate_route(interleaved_stops, [order1, order2], rider)
    assert is_valid is True
    assert len(reasons) == 0


def test_route_validation_deadline_detection():
    now = datetime.now(timezone.utc)
    rider = DummyRider("R-1", "Alpha", 19.0500, 72.8300, w_cap=20.0, p_cap=10)
    tight_order = DummyOrder("O-TIGHT", 19.0510, 72.8310, 19.0550, 72.8350, now + timedelta(seconds=300), w_kg=2.0)

    # Route arrives at delivery at 600 seconds (300s late)
    late_stops = [
        RouteStop(
            stop_index=0, event_id="R_R-1", event_type="ORIGIN",
            latitude=19.0500, longitude=72.8300, arrival_time=now,
            arrival_offset_seconds=0.0, departure_offset_seconds=0.0,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
        RouteStop(
            stop_index=1, event_id="P_O-TIGHT", order_id="O-TIGHT", event_type="PICKUP",
            latitude=19.0510, longitude=72.8310, arrival_time=now + timedelta(seconds=200),
            arrival_offset_seconds=200.0, departure_offset_seconds=380.0,
            onboard_weight_kg=2.0, onboard_packages=1,
        ),
        RouteStop(
            stop_index=2, event_id="D_O-TIGHT", order_id="O-TIGHT", event_type="DELIVERY",
            latitude=19.0550, longitude=72.8350, arrival_time=now + timedelta(seconds=600),
            arrival_offset_seconds=600.0, departure_offset_seconds=780.0,
            deadline=tight_order.delivery_deadline, deadline_slack_seconds=-300.0, is_on_time=False,
            onboard_weight_kg=0.0, onboard_packages=0,
        ),
    ]

    is_valid, reasons = validate_route(late_stops, [tight_order], rider)
    assert is_valid is False
    assert any("Deadline violation" in r for r in reasons)


def test_asymmetric_directed_cost_matrix_respected():
    """Verify directed travel costs where A->B != B->A (one-way restriction)."""
    now = datetime.now(timezone.utc)
    rider = DummyRider("R-ASYM", "Asymmetric Rider", 19.0000, 72.8000, w_cap=20.0, p_cap=10)
    order = DummyOrder("O-ONEWAY", 19.0100, 72.8100, 19.0200, 72.8200, now + timedelta(hours=3), w_kg=2.0)

    events = [
        RouteEvent(event_id="R_R-ASYM", event_type="ORIGIN", latitude=rider.current_latitude, longitude=rider.current_longitude),
        RouteEvent(event_id="P_O-ONEWAY", order_id="O-ONEWAY", event_type="PICKUP", latitude=order.pickup_latitude, longitude=order.pickup_longitude, service_time_seconds=60.0, demand_weight_kg=2.0, demand_package_count=1),
        RouteEvent(event_id="D_O-ONEWAY", order_id="O-ONEWAY", event_type="DELIVERY", latitude=order.delivery_latitude, longitude=order.delivery_longitude, service_time_seconds=60.0, deadline=order.delivery_deadline, demand_weight_kg=-2.0, demand_package_count=-1),
    ]

    # Asymmetric matrix with (src, dst) keys:
    # R_R-ASYM -> P_O-ONEWAY: 200m / 30s
    # P_O-ONEWAY -> D_O-ONEWAY: 1000m / 150s
    # D_O-ONEWAY -> P_O-ONEWAY: 3000m / 450s (reverse detour)
    cost_matrix = {
        ("R_R-ASYM", "P_O-ONEWAY"): (200.0, 30.0),
        ("R_R-ASYM", "D_O-ONEWAY"): (800.0, 120.0),
        ("P_O-ONEWAY", "D_O-ONEWAY"): (1000.0, 150.0),
        ("P_O-ONEWAY", "R_R-ASYM"): (500.0, 80.0),
        ("D_O-ONEWAY", "P_O-ONEWAY"): (3000.0, 450.0),
        ("D_O-ONEWAY", "R_R-ASYM"): (900.0, 140.0),
    }

    stops_fwd, dist_fwd, dur_fwd, peak_w, peak_p = evaluate_route_stops(events, cost_matrix, now)

    assert dist_fwd == 200.0 + 1000.0  # 1200m
    # Duration: 30s + 60s (pickup svc) + 150s + 60s (delivery svc) = 300s
    assert dur_fwd == 300.0
    assert len(stops_fwd) == 3
    is_valid, reasons = validate_route(stops_fwd, [order], rider)
    assert is_valid is True


def test_rider_starting_location_impact_on_routes():
    """Verify different rider starting locations produce distinct initial legs and route costs."""
    now = datetime.now(timezone.utc)
    order = DummyOrder("O-LOC", 19.0500, 72.8300, 19.0600, 72.8400, now + timedelta(hours=2), w_kg=2.0)

    # Rider A is 100m away from pickup
    rider_near = DummyRider("R-NEAR", "Near Rider", 19.0505, 72.8305, w_cap=20.0, p_cap=10)
    # Rider B is 5km away from pickup
    rider_far = DummyRider("R-FAR", "Far Rider", 19.0100, 72.8100, w_cap=20.0, p_cap=10)

    cost_matrix = {
        ("R_R-NEAR", "P_O-LOC"): (100.0, 20.0),
        ("R_R-NEAR", "D_O-LOC"): (1500.0, 300.0),
        ("R_R-FAR", "P_O-LOC"): (5000.0, 800.0),
        ("R_R-FAR", "D_O-LOC"): (6500.0, 1100.0),
        ("P_O-LOC", "D_O-LOC"): (1400.0, 280.0),
        ("D_O-LOC", "P_O-LOC"): (1400.0, 280.0),
    }

    cfg = ACOConfig(num_ants=5, max_iterations=5, random_seed=42)

    res_near = ACORoutingEngine.optimize_route_for_rider([order], rider_near, cost_matrix, now, cfg)
    res_far = ACORoutingEngine.optimize_route_for_rider([order], rider_far, cost_matrix, now, cfg)

    assert res_near.is_feasible is True
    assert res_far.is_feasible is True
    assert res_near.distance_meters < res_far.distance_meters
    assert res_near.duration_seconds < res_far.duration_seconds
    assert res_near.stops[0].event_id == f"R_{rider_near.id}"
    assert res_far.stops[0].event_id == f"R_{rider_far.id}"


def test_aco_random_seed_reproducibility():
    """Verify identical random seed produces bit-identical best route results."""
    now = datetime.now(timezone.utc)
    rider = DummyRider("R-SEED", "Seed Rider", 19.0500, 72.8300, w_cap=20.0, p_cap=10)
    order1 = DummyOrder("O-1", 19.0520, 72.8320, 19.0600, 72.8400, now + timedelta(hours=2), w_kg=2.0)
    order2 = DummyOrder("O-2", 19.0530, 72.8330, 19.0620, 72.8420, now + timedelta(hours=2), w_kg=3.0)

    loc_ids = [
        f"R_{rider.id}",
        f"P_{order1.id}", f"D_{order1.id}",
        f"P_{order2.id}", f"D_{order2.id}",
    ]
    cost_matrix = {}
    for i, s1 in enumerate(loc_ids):
        for j, s2 in enumerate(loc_ids):
            if s1 != s2:
                dist = abs(i - j) * 500.0 + 100.0
                dur = dist / 10.0
                cost_matrix[(s1, s2)] = (dist, dur)

    cfg1 = ACOConfig(num_ants=8, max_iterations=6, random_seed=999)
    res1 = ACORoutingEngine.optimize_route_for_rider([order1, order2], rider, cost_matrix, now, cfg1)

    cfg2 = ACOConfig(num_ants=8, max_iterations=6, random_seed=999)
    res2 = ACORoutingEngine.optimize_route_for_rider([order1, order2], rider, cost_matrix, now, cfg2)

    assert res1.is_feasible == res2.is_feasible
    assert res1.distance_meters == res2.distance_meters
    assert res1.duration_seconds == res2.duration_seconds
    assert [s.event_id for s in res1.stops] == [s.event_id for s in res2.stops]


def test_aco_parameter_validation_and_bounds():
    """Verify Pydantic bounds reject invalid hyperparameters."""
    # Ants < 2
    with pytest.raises(ValidationError):
        ACOConfig(num_ants=1)

    # Evaporation rate <= 0 or >= 1
    with pytest.raises(ValidationError):
        ACOConfig(evaporation_rate=0.0)

    with pytest.raises(ValidationError):
        ACOConfig(evaporation_rate=0.95)

    # Alpha < 0
    with pytest.raises(ValidationError):
        ACOConfig(alpha=-0.5)

    # Beta < 0
    with pytest.raises(ValidationError):
        ACOConfig(beta=-1.0)


def test_greedy_baseline_comparison_and_diagnostics():
    """Verify greedy baseline runs deterministically and provides honest comparison."""
    now = datetime.now(timezone.utc)
    rider = DummyRider("R-GREEDY", "Greedy Rider", 19.0500, 72.8300, w_cap=20.0, p_cap=10)
    order1 = DummyOrder("O-1", 19.0510, 72.8310, 19.0550, 72.8350, now + timedelta(hours=2), w_kg=2.0)
    order2 = DummyOrder("O-2", 19.0520, 72.8320, 19.0580, 72.8380, now + timedelta(hours=2), w_kg=3.0)

    loc_ids = [
        f"R_{rider.id}",
        f"P_{order1.id}", f"D_{order1.id}",
        f"P_{order2.id}", f"D_{order2.id}",
    ]
    cost_matrix = {}
    for i, s1 in enumerate(loc_ids):
        for j, s2 in enumerate(loc_ids):
            if s1 != s2:
                dist = abs(i - j) * 400.0 + 50.0
                dur = dist / 12.0
                cost_matrix[(s1, s2)] = (dist, dur)

    cfg = ACOConfig(num_ants=6, max_iterations=5, random_seed=42)
    opt = ACORoutingEngine.optimize_route_for_rider([order1, order2], rider, cost_matrix, now, cfg)

    assert "baseline_comparison" in opt.model_dump()
    comp = opt.baseline_comparison
    assert "distance_km" in comp
    assert "duration_min" in comp
    assert "all_deadlines_met" in comp
    assert "is_feasible" in comp
    assert comp["is_feasible"] is True


def test_unreachable_and_empty_batches():
    """Verify unrouteable batch handling when no riders are eligible or pairs are disconnected."""
    now = datetime.now(timezone.utc)
    batch = BatchResult(
        batch_id="BATCH-EMPTY",
        order_ids=["O-HEAVY"],
        designated_rider_id="R-NONE",
        rider_display_name="No Rider",
        eligible_rider_ids=[],
        total_weight_kg=50.0,
        total_packages=20,
        weight_utilization_pct=100.0,
        package_utilization_pct=100.0,
        estimated_distance_km=5.0,
        estimated_duration_min=15.0,
        stops=[],
        deadline_feasible=True,
        lateness_minutes=0.0,
        average_urgency=0.5,
        all_deadlines_met=True,
        precedence_verified=True,
    )
    heavy_order = DummyOrder("O-HEAVY", 19.0500, 72.8300, 19.0600, 72.8400, now + timedelta(hours=2), w_kg=50.0, p_cnt=20)
    small_rider = DummyRider("R-SMALL", "Small Rider", 19.0500, 72.8300, w_cap=15.0, p_cap=5)

    # Empty candidate rider pool for heavy order
    res = ACORoutingEngine.optimize_batches_routes(
        batches=[batch],
        all_orders=[heavy_order],
        all_riders=[small_rider],
        reference_time=now,
    )

    assert len(res.batches) == 1
    assert res.batches[0].is_routeable is False
    assert "No available fleet riders" in (res.batches[0].unrouteable_reason or "")
    assert res.summary["routeable_batches_count"] == 0


def seed_test_db(db: Session):
    now = datetime.now(timezone.utc)
    from backend.app.models.entities import Merchant
    m = Merchant(
        id="M-TEST-1",
        name="Test Bandra Bakery",
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
            package_type="PARCEL",
            weight_kg=2.0 * i,
            package_count=1,
            customer_priority="STANDARD",
            merchant_priority=i,
            status=OrderStatus.PENDING.value,
            created_at=now - timedelta(minutes=10 * i),
        )
        db.add(o)
    db.commit()


def test_api_route_preview_success_and_read_only(client: TestClient, db_session: Session):
    """Verify POST /api/v1/optimization/routes/preview on seeded database is strictly read-only."""
    seed_test_db(db_session)

    # Fetch initial pending orders count and statuses
    initial_orders = db_session.query(Order).filter(Order.status == OrderStatus.PENDING.value).all()
    initial_order_ids = [o.id for o in initial_orders]
    assert len(initial_orders) >= 3

    resp = client.post(
        "/api/v1/optimization/routes/preview",
        json={
            "aco_config": {
                "num_ants": 5,
                "max_iterations": 4,
                "random_seed": 42,
                "max_candidate_riders": 2,
            },
            "ga_config": {
                "population_size": 15,
                "generations": 8,
                "random_seed": 42,
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()

    assert data["preview_mode"] is True
    assert "batches" in data
    assert "summary" in data
    assert "aco_vs_greedy_comparison" in data["summary"]
    assert data["summary"]["total_batches"] >= 1

    # Check each batch
    for b in data["batches"]:
        assert "batch_id" in b
        assert "order_ids" in b
        assert "eligible_rider_ids" in b
        assert "route_candidates" in b
        if b["is_routeable"]:
            best = b["best_feasible_candidate"]
            assert best is not None
            assert best["is_feasible"] is True
            assert len(best["stops"]) >= 3  # Origin + at least 1 pickup + 1 delivery
            assert best["stops"][0]["event_type"] == "ORIGIN"

    # Strictly verify read-only: no order status changes, no batch_order links, and no database Batches/Routes
    from backend.app.models.entities import Batch, Route
    db_orders_after = db_session.query(Order).filter(Order.id.in_(initial_order_ids)).all()
    for o in db_orders_after:
        assert o.status == OrderStatus.PENDING.value
        assert o.batch_order is None

    assert db_session.query(Batch).count() == 0
    assert db_session.query(Route).count() == 0


def test_api_route_preview_validation_errors(client: TestClient, db_session: Session):
    """Verify error responses for missing orders, non-pending orders, and missing riders."""
    seed_test_db(db_session)

    # 1. Non-existent order
    resp = client.post(
        "/api/v1/optimization/routes/preview",
        json={"order_ids": ["ORD-NON-EXISTENT-XYZ"]},
    )
    assert resp.status_code == 404
    assert "Orders not found" in resp.json()["detail"]

    # 2. Non-existent rider
    resp = client.post(
        "/api/v1/optimization/routes/preview",
        json={"rider_ids": ["RIDER-NON-EXISTENT-XYZ"]},
    )
    assert resp.status_code == 404
    assert "Riders not found" in resp.json()["detail"]

    # 3. Non-pending order
    order = db_session.query(Order).first()
    order.status = OrderStatus.DELIVERED.value
    db_session.commit()

    resp = client.post(
        "/api/v1/optimization/routes/preview",
        json={"order_ids": [order.id]},
    )
    assert resp.status_code == 422
    assert "Only PENDING orders can be routed" in resp.json()["detail"]
