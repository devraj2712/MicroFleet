from pathlib import Path
import pytest

from backend.app.intelligence.osm.pdptw_benchmark import (
    parse_pdptw_file,
    parse_pdptw_text,
    PDPTWInstance,
)


def test_parse_valid_pdptw_sample():
    sample_file = Path("backend/data/raw/pdp_100/LC101_sample.txt")
    assert sample_file.exists(), "Sample benchmark file must exist"

    instance = parse_pdptw_file(sample_file)
    assert instance.instance_name == "LC101_sample"
    assert instance.vehicle_number == 25
    assert instance.vehicle_capacity == 200.0
    assert instance.depot.cust_no == 0
    assert instance.depot.demand == 0.0

    # 11 total nodes (1 depot + 5 pickup + 5 delivery)
    assert len(instance.nodes) == 11
    assert len(instance.requests) == 5
    assert instance.validation_status == "VALID"
    assert len(instance.validation_notes) == 0

    # Verify pickup-delivery request pair 1 -> 6
    req1 = next(r for r in instance.requests if r.pickup_cust_no == 1)
    assert req1.delivery_cust_no == 6
    assert req1.demand == 10.0

    # Verify abstract Euclidean distance matrix properties
    assert len(instance.euclidean_distance_matrix) == 11
    assert instance.euclidean_distance_matrix[0][0] == 0.0
    # Symmetric Euclidean distance in 2D plane
    for i in range(11):
        for j in range(11):
            assert instance.euclidean_distance_matrix[i][j] == instance.euclidean_distance_matrix[j][i]


def test_inverted_time_window_detection():
    raw = """1 100
CUST NO.  XCOORD.   YCOORD.   DEMAND   READY TIME  DUE DATE   SERVICE TIME   PICKUP   DELIVERY
0 0 0 0 0 100 0 0 0
1 10 10 10 80 50 10 0 2
2 20 20 -10 90 120 10 1 0
"""
    instance = parse_pdptw_text(raw, instance_name="INVERTED_TW")
    assert instance.validation_status == "WARNINGS_FOUND"
    assert any("time window inverted" in note for note in instance.validation_notes)


def test_pairing_mismatch_detection():
    # Node 1 points to 2, but node 2 points to 3 (mismatch)
    raw = """1 100
CUST NO.  XCOORD.   YCOORD.   DEMAND   READY TIME  DUE DATE   SERVICE TIME   PICKUP   DELIVERY
0 0 0 0 0 100 0 0 0
1 10 10 10 10 50 10 0 2
2 20 20 -10 60 100 10 3 0
"""
    instance = parse_pdptw_text(raw, instance_name="MISMATCH")
    assert instance.validation_status == "WARNINGS_FOUND"
    assert any("Pairing mismatch" in note for note in instance.validation_notes)


def test_demand_asymmetry_detection():
    # Node 1 demand 15, node 2 demand -10 (not equal and opposite)
    raw = """1 100
CUST NO.  XCOORD.   YCOORD.   DEMAND   READY TIME  DUE DATE   SERVICE TIME   PICKUP   DELIVERY
0 0 0 0 0 100 0 0 0
1 10 10 15 10 50 10 0 2
2 20 20 -10 60 100 10 1 0
"""
    instance = parse_pdptw_text(raw, instance_name="ASYMMETRY")
    assert instance.validation_status == "WARNINGS_FOUND"
    assert any("Demand symmetry mismatch" in note for note in instance.validation_notes)


def test_capacity_exceeded_detection():
    # Vehicle capacity is 50, but pickup demand is 60
    raw = """1 50
CUST NO.  XCOORD.   YCOORD.   DEMAND   READY TIME  DUE DATE   SERVICE TIME   PICKUP   DELIVERY
0 0 0 0 0 100 0 0 0
1 10 10 60 10 50 10 0 2
2 20 20 -60 60 100 10 1 0
"""
    instance = parse_pdptw_text(raw, instance_name="OVERCAPACITY")
    assert instance.validation_status == "WARNINGS_FOUND"
    assert any("exceeds vehicle capacity" in note for note in instance.validation_notes)
