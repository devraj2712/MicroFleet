import pytest
from datetime import datetime, timedelta, timezone
from backend.app.intelligence.rl.dispatcher import RLDispatchService, AssignedBatchItem, UnassignedBatchItem
from backend.app.intelligence.rl.baselines import RouteAwareFleetAssignmentPolicy
from backend.app.intelligence.aco.aco_routing import ACORoutingEngine, ACOConfig, validate_route, RouteStop
from backend.app.intelligence.ga.ga_batching import GAConfig


class MockEntity:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_illustrative_route_aware_fleet_assignment_scenario():
    """
    Validates Section 3 illustrative test scenario:
    - Merchant A (Juhu) -> Order to Virar
    - Rider 1 initially near Khar
    - Merchant B (Borivali) -> Order to Dahisar
    - Rider 2 initially near Borivali
    - Rider 3 available near Lower Parel
    Evaluates separate vs combined vs alternatives using real Mumbai road network distances and durations.
    """
    now = datetime(2026, 10, 24, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Setup Merchants and Orders
    order_juhu_virar = MockEntity(
        id="ORD-JUHU-VIRAR",
        merchant_id="M-JUHU",
        pickup_latitude=19.1075,
        pickup_longitude=72.8263,
        delivery_latitude=19.4564,
        delivery_longitude=72.8081,
        delivery_deadline=now + timedelta(hours=4),
        weight_kg=3.0,
        package_count=1,
        status="PENDING",
        customer_priority="STANDARD",
        merchant_priority=1,
    )

    order_borivali_dahisar = MockEntity(
        id="ORD-BORIVALI-DAHISAR",
        merchant_id="M-BORIVALI",
        pickup_latitude=19.2307,
        pickup_longitude=72.8567,
        delivery_latitude=19.2500,
        delivery_longitude=72.8600,
        delivery_deadline=now + timedelta(hours=3),
        weight_kg=2.0,
        package_count=1,
        status="PENDING",
        customer_priority="STANDARD",
        merchant_priority=1,
    )

    # 2. Setup Fleet Riders
    rider_khar = MockEntity(
        id="R-KHAR",
        display_name="Rider Khar",
        current_latitude=19.0700,
        current_longitude=72.8340,
        weight_capacity_kg=25.0,
        package_count_capacity=10,
        is_available=True,
    )

    rider_borivali = MockEntity(
        id="R-BORIVALI",
        display_name="Rider Borivali",
        current_latitude=19.2280,
        current_longitude=72.8550,
        weight_capacity_kg=20.0,
        package_count_capacity=8,
        is_available=True,
    )

    rider_lower_parel = MockEntity(
        id="R-LOWER-PAREL",
        display_name="Rider Lower Parel",
        current_latitude=18.9900,
        current_longitude=72.8300,
        weight_capacity_kg=30.0,
        package_count_capacity=15,
        is_available=True,
    )

    orders = [order_juhu_virar, order_borivali_dahisar]
    riders = [rider_khar, rider_borivali, rider_lower_parel]

    # Run Route-Aware Fleet Assignment Pipeline
    res = RLDispatchService.run_dispatch_pipeline(
        orders=orders,
        riders=riders,
        reference_time=now,
        policy_choice="route_aware",
    )

    assert len(res.assignments) > 0, "Expected feasible assignments for the illustrative scenario"
    assert res.summary["all_assignments_deadline_feasible"] is True

    # Validate that every assigned batch has an explainable reason and evaluated alternatives
    for a in res.assignments:
        assert len(a.explanation) > 0
        assert "assigned to Batch" in a.explanation
        assert len(a.evaluated_alternatives) > 0
        assert len(a.route_coordinates) > 0, "Route coordinates must be present for polyline map rendering"
        assert a.approach_distance_km >= 0.0
        assert a.distance_km > 0.0
        assert a.duration_minutes > 0.0

    # Ensure baseline comparisons are computed
    assert "route_aware_fleet_assignment" in res.baseline_comparisons
    assert "nearest_feasible_rider" in res.baseline_comparisons


def test_infeasible_order_diagnostics_and_uncomputed_metrics():
    """
    Validates Section 2 & 4:
    - Deliberately infeasible orders are accurately diagnosed
    - Expired deadlines and capacity violations produce informative rejection reasons
    - Unassigned batches do not present failure as 0 km / 0 min
    """
    now = datetime(2026, 10, 24, 10, 0, 0, tzinfo=timezone.utc)

    # Order with deadline in the past
    expired_order = MockEntity(
        id="ORD-EXPIRED",
        merchant_id="M-BANDRA",
        pickup_latitude=19.0596,
        pickup_longitude=72.8295,
        delivery_latitude=19.0680,
        delivery_longitude=72.8385,
        delivery_deadline=now - timedelta(hours=2),  # Already expired by 2 hours
        weight_kg=2.0,
        package_count=1,
        status="PENDING",
        customer_priority="STANDARD",
        merchant_priority=1,
    )

    # Order with capacity exceeding any rider
    oversize_order = MockEntity(
        id="ORD-OVERSIZE",
        merchant_id="M-DADAR",
        pickup_latitude=19.0178,
        pickup_longitude=72.8478,
        delivery_latitude=19.0120,
        delivery_longitude=72.8310,
        delivery_deadline=now + timedelta(hours=3),
        weight_kg=200.0,  # Far exceeds 20-30kg rider limit
        package_count=50,
        status="PENDING",
        customer_priority="STANDARD",
        merchant_priority=1,
    )

    rider = MockEntity(
        id="R-MUM-01",
        display_name="Aarav Sharma",
        current_latitude=19.0550,
        current_longitude=72.8350,
        weight_capacity_kg=25.0,
        package_count_capacity=10,
        is_available=True,
    )

    res = RLDispatchService.run_dispatch_pipeline(
        orders=[expired_order, oversize_order],
        riders=[rider],
        reference_time=now,
        policy_choice="route_aware",
    )

    assert len(res.assignments) == 0
    assert len(res.unassigned_batches) > 0
    assert res.summary["assigned_batches_count"] == 0
    assert res.summary["display_distance"] == "Not available"
    assert res.summary["display_duration"] == "Not available"

    # Check that diagnostic reasons clearly explain the failure
    all_reasons = " ".join(u.reason for u in res.unassigned_batches)
    assert "deadline" in all_reasons.lower() or "capacity" in all_reasons.lower()
