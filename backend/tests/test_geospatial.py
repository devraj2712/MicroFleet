import networkx as nx
import pytest
from fastapi.testclient import TestClient

from backend.app.intelligence.osm.osm_service import (
    CoordinateOutOfBoundsError,
    DestinationUnreachableError,
    NetworkUnavailableError,
    OSMService,
    SnapDistanceExceededError,
)
from backend.app.schemas.schemas import LocationIdentifier


@pytest.fixture(autouse=True)
def setup_mock_network():
    """Build a deterministic in-memory directed road graph fixture for offline testing."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "epsg:4326"

    # 5 nodes in Mumbai decimal coordinates
    G.add_node(1, y=19.0500, x=72.8300, street_count=3)
    G.add_node(2, y=19.0600, x=72.8300, street_count=2)
    G.add_node(3, y=19.0600, x=72.8400, street_count=3)
    G.add_node(4, y=19.0500, x=72.8400, street_count=2)
    # Disconnected node (island)
    G.add_node(5, y=19.0800, x=72.8500, street_count=1)

    # Path A: 1 -> 2 -> 3 (Longer distance, but faster highway travel time)
    # Total distance: 1000 + 1000 = 2000m; Total time: 120 + 60 = 180s
    G.add_edge(1, 2, 0, length=1000.0, speed_kph=30.0, travel_time=120.0, oneway=True)
    G.add_edge(2, 3, 0, length=1000.0, speed_kph=60.0, travel_time=60.0, oneway=True)

    # Path B: 1 -> 4 -> 3 (Shorter distance, but slow congested alley)
    # Total distance: 800 + 800 = 1600m; Total time: 288 + 288 = 576s
    G.add_edge(1, 4, 0, length=800.0, speed_kph=10.0, travel_time=288.0, oneway=True)
    G.add_edge(4, 3, 0, length=800.0, speed_kph=10.0, travel_time=288.0, oneway=True)

    meta = {
        "dataset_name": "Test Mock Road Network",
        "node_count": len(G.nodes),
        "edge_count": len(G.edges),
        "network_type": "drive",
        "bounding_box_w_s_e_n": [72.8300, 19.0500, 72.8500, 19.0800],
        "travel_time_model": "Deterministic Unit Test Weights",
        "osm_attribution": "© Test Attribution",
        "traffic_note": "Offline deterministic test fixture",
    }

    OSMService.set_graph_for_testing(G, meta)
    yield
    # Clean up
    OSMService._graph = None
    OSMService._metadata = None
    OSMService._snap_cache.clear()
    OSMService._route_cache.clear()


def test_routing_status():
    status = OSMService.get_status()
    assert status.available is True
    assert status.node_count == 5
    assert status.edge_count == 4
    assert status.network_type == "drive"
    assert "Test Mock" in str(status.travel_time_model) or "Deterministic" in str(status.travel_time_model)


def test_coordinate_snapping_valid():
    # Near Node 1 (19.0500, 72.8300)
    snapped = OSMService.snap_coordinate(19.05005, 72.83005, max_dist_m=100.0)
    assert snapped.snapped_node_id == 1
    assert snapped.within_max_snap is True
    assert snapped.snap_distance_meters < 20.0
    assert snapped.snapped_latitude == 19.0500
    assert snapped.snapped_longitude == 72.8300


def test_coordinate_snapping_out_of_bounds():
    with pytest.raises(CoordinateOutOfBoundsError):
        OSMService.snap_coordinate(95.0, 72.8300)

    with pytest.raises(CoordinateOutOfBoundsError):
        OSMService.snap_coordinate(19.0500, -195.0)


def test_coordinate_snapping_exceeds_max_distance():
    # Far outside bounding area
    with pytest.raises(SnapDistanceExceededError):
        OSMService.snap_coordinate(19.9999, 73.9999, max_dist_m=500.0, strict=True)


def test_route_estimation_different_weights():
    # 1. Optimizing for length (distance) must choose 1 -> 4 -> 3 (1600m)
    route_dist = OSMService.estimate_route(19.0500, 72.8300, 19.0600, 72.8400, weight="length")
    assert route_dist.route_nodes == [1, 4, 3]
    assert route_dist.distance_meters == 1600.0
    assert route_dist.duration_seconds == 576.0
    assert len(route_dist.route_coordinates) == 3

    # 2. Optimizing for travel_time must choose 1 -> 2 -> 3 (180s)
    route_time = OSMService.estimate_route(19.0500, 72.8300, 19.0600, 72.8400, weight="travel_time")
    assert route_time.route_nodes == [1, 2, 3]
    assert route_time.distance_meters == 2000.0
    assert route_time.duration_seconds == 180.0


def test_route_directed_one_way():
    # Graph has 1 -> 2, but no 2 -> 1
    with pytest.raises(DestinationUnreachableError):
        OSMService.estimate_route(19.0600, 72.8300, 19.0500, 72.8300)


def test_route_disconnected_destination():
    # Node 5 has no inbound edges
    with pytest.raises(DestinationUnreachableError):
        OSMService.estimate_route(19.0500, 72.8300, 19.0800, 72.8500)


def test_route_same_node_snapping():
    # Origin and destination both snap to Node 1
    route = OSMService.estimate_route(19.05001, 72.83001, 19.05002, 72.83002)
    assert route.distance_meters == 0.0
    assert route.duration_seconds == 0.0
    assert route.route_node_count == 1
    assert route.route_nodes == [1]


def test_pairwise_matrix_ordering_and_values():
    locations = [
        LocationIdentifier(id="LOC-1", latitude=19.0500, longitude=72.8300),  # Node 1
        LocationIdentifier(id="LOC-2", latitude=19.0600, longitude=72.8300),  # Node 2
        LocationIdentifier(id="LOC-3", latitude=19.0600, longitude=72.8400),  # Node 3
        LocationIdentifier(id="LOC-5", latitude=19.0800, longitude=72.8500),  # Node 5 (disconnected)
    ]

    matrix_res = OSMService.compute_matrix(locations, weight="travel_time")
    assert matrix_res.location_ids == ["LOC-1", "LOC-2", "LOC-3", "LOC-5"]

    # Diagonal is zero
    for i in range(4):
        assert matrix_res.distance_matrix_meters[i][i] == 0.0
        assert matrix_res.duration_matrix_seconds[i][i] == 0.0

    # LOC-1 -> LOC-2: 1000m, 120s
    assert matrix_res.distance_matrix_meters[0][1] == 1000.0
    assert matrix_res.duration_matrix_seconds[0][1] == 120.0

    # LOC-1 -> LOC-3: travel time optimal path via node 2 = 120 + 60 = 180s, distance 2000m
    assert matrix_res.distance_matrix_meters[0][2] == 2000.0
    assert matrix_res.duration_matrix_seconds[0][2] == 180.0

    # LOC-2 -> LOC-1 is unreachable (one way): None
    assert matrix_res.distance_matrix_meters[1][0] is None
    assert ["LOC-2", "LOC-1"] in matrix_res.unreachable_pairs

    # LOC-1 -> LOC-5 is unreachable: None
    assert matrix_res.distance_matrix_meters[0][3] is None
    assert ["LOC-1", "LOC-5"] in matrix_res.unreachable_pairs


def test_api_routing_status(client: TestClient):
    resp = client.get("/api/v1/routing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["node_count"] == 5
    assert data["edge_count"] == 4


def test_api_route_estimate_success(client: TestClient):
    payload = {
        "origin": {"latitude": 19.0500, "longitude": 72.8300},
        "destination": {"latitude": 19.0600, "longitude": 72.8400},
        "weight": "travel_time",
    }
    resp = client.post("/api/v1/routing/estimate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["route_nodes"] == [1, 2, 3]
    assert data["distance_meters"] == 2000.0
    assert data["duration_seconds"] == 180.0
    assert len(data["route_coordinates"]) == 3


def test_api_route_estimate_unreachable_404(client: TestClient):
    payload = {
        "origin": {"latitude": 19.0500, "longitude": 72.8300},
        "destination": {"latitude": 19.0800, "longitude": 72.8500},
        "weight": "travel_time",
    }
    resp = client.post("/api/v1/routing/estimate", json=payload)
    assert resp.status_code == 404
    assert "No drivable road path exists" in resp.json()["detail"]


def test_api_routing_matrix_success(client: TestClient):
    payload = {
        "locations": [
            {"id": "A", "latitude": 19.0500, "longitude": 72.8300},
            {"id": "B", "latitude": 19.0600, "longitude": 72.8300},
        ],
        "weight": "travel_time",
    }
    resp = client.post("/api/v1/routing/matrix", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["location_ids"] == ["A", "B"]
    assert data["distance_matrix_meters"][0][1] == 1000.0
    assert data["duration_matrix_seconds"][0][1] == 120.0


def test_network_unavailable_handling():
    # Clear graph and point to a non-existent path
    OSMService._graph = None
    with pytest.raises(NetworkUnavailableError):
        OSMService.load_network(graphml_path="non_existent_graph.graphml")

    status = OSMService.get_status(graphml_path="non_existent_graph.graphml")
    assert status.available is False
    assert status.node_count == 0

