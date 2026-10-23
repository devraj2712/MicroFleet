from datetime import datetime, timedelta, timezone
import pytest

from backend.app.intelligence.fuzzy.fuzzy_urgency import (
    FuzzyUrgencyEngine,
    UrgencyCategory,
    trimf,
    trapmf,
)


def test_membership_functions_math():
    # Triangular: a=10, b=20, c=30
    assert trimf(5, 10, 20, 30) == 0.0
    assert trimf(15, 10, 20, 30) == 0.5
    assert trimf(20, 10, 20, 30) == 1.0
    assert trimf(25, 10, 20, 30) == 0.5
    assert trimf(35, 10, 20, 30) == 0.0

    # Trapezoidal: a=10, b=20, c=40, d=50
    assert trapmf(5, 10, 20, 40, 50) == 0.0
    assert trapmf(15, 10, 20, 40, 50) == 0.5
    assert trapmf(30, 10, 20, 40, 50) == 1.0
    assert trapmf(45, 10, 20, 40, 50) == 0.5
    assert trapmf(55, 10, 20, 40, 50) == 0.0


def test_urgency_score_range_and_output_bounds():
    now = datetime.now(timezone.utc)
    order_mock = {
        "id": "ORD-TEST-01",
        "pickup_latitude": 19.0596,
        "pickup_longitude": 72.8295,
        "delivery_latitude": 19.0178,
        "delivery_longitude": 72.8478,
        "delivery_deadline": now + timedelta(hours=1),
        "created_at": now - timedelta(minutes=15),
        "customer_priority": "STANDARD",
        "merchant_priority": 2,
        "package_type": "PARCEL",
    }
    result = FuzzyUrgencyEngine.score_order(order_mock, reference_time=now)
    assert 0.0 <= result.urgency_score <= 100.0
    assert result.urgency_category in list(UrgencyCategory)
    assert result.order_id == "ORD-TEST-01"
    assert len(result.contributing_rules) > 0


def test_urgency_increases_monotonically_for_tighter_deadlines():
    now = datetime.now(timezone.utc)
    base_order = {
        "id": "ORD-TIGHTENING",
        "pickup_latitude": 19.0596,
        "pickup_longitude": 72.8295,
        "delivery_latitude": 19.0178,
        "delivery_longitude": 72.8478,
        "created_at": now - timedelta(minutes=10),
        "customer_priority": "STANDARD",
        "merchant_priority": 1,
        "package_type": "PARCEL",
    }

    # Order A: Comfortable 3-hour deadline
    order_a = {**base_order, "delivery_deadline": now + timedelta(hours=3)}
    res_a = FuzzyUrgencyEngine.score_order(order_a, reference_time=now)

    # Order B: Tight 30-minute deadline
    order_b = {**base_order, "delivery_deadline": now + timedelta(minutes=30)}
    res_b = FuzzyUrgencyEngine.score_order(order_b, reference_time=now)

    # Order C: Critical 10-minute deadline
    order_c = {**base_order, "delivery_deadline": now + timedelta(minutes=10)}
    res_c = FuzzyUrgencyEngine.score_order(order_c, reference_time=now)

    # Order D: Overdue deadline
    order_d = {**base_order, "delivery_deadline": now - timedelta(minutes=15)}
    res_d = FuzzyUrgencyEngine.score_order(order_d, reference_time=now)

    assert res_a.urgency_score < res_b.urgency_score
    assert res_b.urgency_score < res_c.urgency_score
    assert res_c.urgency_score <= res_d.urgency_score
    assert res_d.urgency_category == UrgencyCategory.CRITICAL


def test_priority_and_waiting_time_influence():
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(minutes=45)  # moderately tight

    # Standard customer with short wait
    order_std = {
        "id": "ORD-STD",
        "pickup_latitude": 19.0596,
        "pickup_longitude": 72.8295,
        "delivery_latitude": 19.0178,
        "delivery_longitude": 72.8478,
        "delivery_deadline": deadline,
        "created_at": now - timedelta(minutes=5),
        "customer_priority": "STANDARD",
        "merchant_priority": 1,
        "package_type": "PARCEL",
    }
    res_std = FuzzyUrgencyEngine.score_order(order_std, reference_time=now)

    # VIP medical customer with long wait
    order_vip = {
        "id": "ORD-VIP",
        "pickup_latitude": 19.0596,
        "pickup_longitude": 72.8295,
        "delivery_latitude": 19.0178,
        "delivery_longitude": 72.8478,
        "delivery_deadline": deadline,
        "created_at": now - timedelta(minutes=60),
        "customer_priority": "VIP",
        "merchant_priority": 8,
        "package_type": "MEDICAL",
        "handling_requirements": "Urgent medicine",
    }
    res_vip = FuzzyUrgencyEngine.score_order(order_vip, reference_time=now)

    assert res_vip.priority_score > res_std.priority_score
    assert res_vip.urgency_score > res_std.urgency_score


def test_timezone_awareness_and_naive_fallback():
    # Naive datetimes (without tzinfo) should be converted cleanly to UTC without error
    now_naive = datetime(2026, 10, 22, 12, 0, 0)
    order_naive = {
        "id": "ORD-NAIVE",
        "pickup_latitude": 19.0596,
        "pickup_longitude": 72.8295,
        "delivery_latitude": 19.0178,
        "delivery_longitude": 72.8478,
        "delivery_deadline": datetime(2026, 10, 22, 13, 0, 0),
        "created_at": datetime(2026, 10, 22, 11, 45, 0),
        "customer_priority": "PREMIUM",
        "merchant_priority": 3,
        "package_type": "PERISHABLE",
    }
    result = FuzzyUrgencyEngine.score_order(order_naive, reference_time=now_naive)
    assert 0.0 <= result.urgency_score <= 100.0
    assert result.deadline_slack_minutes > 0.0


def test_unreachable_route_fallback_handling():
    now = datetime.now(timezone.utc)
    # Coordinate that snaps to disconnected or out-of-bounds location
    order_disconnected = {
        "id": "ORD-DISCONN",
        "pickup_latitude": 19.0596,
        "pickup_longitude": 72.8295,
        "delivery_latitude": 0.0,  # far out-of-bounds in ocean
        "delivery_longitude": 0.0,
        "delivery_deadline": now + timedelta(hours=1),
        "created_at": now - timedelta(minutes=10),
        "customer_priority": "STANDARD",
        "merchant_priority": 1,
        "package_type": "PARCEL",
    }
    result = FuzzyUrgencyEngine.score_order(order_disconnected, reference_time=now)
    assert result.urgency_score >= 0.0
    assert len(result.warnings) > 0
    assert any("defaulted" in w.lower() for w in result.warnings)
