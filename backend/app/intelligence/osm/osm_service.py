import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx
import osmnx as ox

from backend.app.core.config import settings
from backend.app.schemas.schemas import (
    LocationCoordinate,
    LocationIdentifier,
    RouteEstimateResponse,
    RoutingMatrixResponse,
    RoutingStatusResponse,
    SnappedPointResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_ATTRIBUTION = "© OpenStreetMap contributors, Open Database License (ODbL) 1.0"
DEFAULT_TRAFFIC_NOTE = "Static topological free-flow estimates; does not reflect live traffic congestion."
DEFAULT_TRAVEL_TIME_MODEL = "Edge length with highway-specific speeds and 25 km/h urban fallback"


class NetworkUnavailableError(Exception):
    """Raised when no valid cached OpenStreetMap road network is found."""


class CoordinateOutOfBoundsError(ValueError):
    """Raised when geographic coordinates are physically invalid or out of range."""


class SnapDistanceExceededError(ValueError):
    """Raised when coordinates cannot be snapped within the allowed maximum distance."""


class DestinationUnreachableError(Exception):
    """Raised when no directed path connects origin and destination on the road network."""


class OSMService:
    """Modular geospatial and routing service using cached OpenStreetMap road networks."""

    _graph: Optional[nx.MultiDiGraph] = None
    _metadata: Optional[dict] = None
    _snap_cache: Dict[Tuple[float, float], SnappedPointResponse] = {}
    _route_cache: Dict[Tuple[int, int, str], Tuple[List[int], float, float]] = {}

    @classmethod
    def load_network(
        cls,
        graphml_path: Optional[str] = None,
        meta_path: Optional[str] = None,
        force_reload: bool = False,
    ) -> nx.MultiDiGraph:
        """Load and validate the cached GraphML road network.

        Raises NetworkUnavailableError if the graph file does not exist or is invalid.
        """
        if cls._graph is not None and not force_reload:
            return cls._graph

        resolved_graphml = Path(graphml_path or settings.OSM_GRAPHML_PATH).resolve()
        resolved_meta = Path(meta_path or settings.OSM_METADATA_PATH).resolve()

        if not resolved_graphml.exists():
            cls._graph = None
            cls._metadata = None
            raise NetworkUnavailableError(
                f"Road network graph not found at '{resolved_graphml.name}'. "
                "Run 'backend/scripts/fetch_mumbai_network.py' to download and cache the road network."
            )

        try:
            logger.info("Loading cached road network from: %s", resolved_graphml)
            G = ox.load_graphml(resolved_graphml)

            if len(G.nodes) == 0 or len(G.edges) == 0:
                raise NetworkUnavailableError(
                    f"GraphML at '{resolved_graphml.name}' is empty (0 nodes or 0 edges)."
                )

            # Ensure all edges have length and travel_time numeric attributes
            for u, v, k, data in G.edges(keys=True, data=True):
                # Ensure length is a float
                if "length" not in data or data["length"] is None:
                    data["length"] = 10.0
                else:
                    data["length"] = float(data["length"])

                # Ensure travel_time is a float
                if "travel_time" not in data or data["travel_time"] is None:
                    # fallback: length (m) / (25 km/h in m/s = 6.944 m/s)
                    speed_mps = (settings.DEFAULT_SPEED_FALLBACK_KPH * 1000.0) / 3600.0
                    data["travel_time"] = data["length"] / speed_mps
                else:
                    data["travel_time"] = float(data["travel_time"])

            cls._graph = G

            # Load metadata JSON if present
            if resolved_meta.exists():
                try:
                    with open(resolved_meta, "r", encoding="utf-8") as f:
                        cls._metadata = json.load(f)
                except Exception as meta_err:
                    logger.warning("Could not read metadata file: %s", meta_err)
                    cls._metadata = None
            else:
                cls._metadata = None

            # Reset in-memory caches upon new graph load
            cls._snap_cache.clear()
            cls._route_cache.clear()

            logger.info(
                "Successfully loaded road network: %d nodes, %d edges.",
                len(cls._graph.nodes),
                len(cls._graph.edges),
            )
            return cls._graph
        except Exception as e:
            cls._graph = None
            cls._metadata = None
            if isinstance(e, NetworkUnavailableError):
                raise
            raise NetworkUnavailableError(f"Failed to load GraphML network: {e}") from e

    @classmethod
    def set_graph_for_testing(
        cls,
        graph: nx.MultiDiGraph,
        metadata: Optional[dict] = None,
    ) -> None:
        """Inject a custom in-memory graph fixture for deterministic offline unit testing."""
        cls._graph = graph
        cls._metadata = metadata or {
            "dataset_name": "Test In-Memory Fixture",
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "travel_time_model": "Unit test deterministic weights",
            "osm_attribution": "Synthetic / Test Data",
            "traffic_note": "Offline test fixture",
        }
        cls._snap_cache.clear()
        cls._route_cache.clear()

    @classmethod
    def get_status(cls, graphml_path: Optional[str] = None) -> RoutingStatusResponse:
        """Inspect and return current routing network status and coverage metadata."""
        try:
            G = cls.load_network(graphml_path=graphml_path)
            meta = cls._metadata or {}
            bbox = meta.get("bounding_box_w_s_e_n")
            if not bbox and len(G.nodes) > 0:
                lons = [data.get("x", 0.0) for _, data in G.nodes(data=True)]
                lats = [data.get("y", 0.0) for _, data in G.nodes(data=True)]
                bbox = [min(lons), min(lats), max(lons), max(lats)]

            return RoutingStatusResponse(
                available=True,
                network_type=meta.get("network_type", "drive"),
                node_count=len(G.nodes),
                edge_count=len(G.edges),
                bounding_box_w_s_e_n=bbox,
                retrieval_date=meta.get("retrieval_date"),
                osmnx_version=meta.get("osmnx_version", ox.__version__),
                networkx_version=meta.get("networkx_version", nx.__version__),
                travel_time_model=meta.get("travel_time_model", DEFAULT_TRAVEL_TIME_MODEL),
                osm_attribution=meta.get("osm_attribution", DEFAULT_ATTRIBUTION),
                traffic_note=meta.get("traffic_note", DEFAULT_TRAFFIC_NOTE),
            )
        except NetworkUnavailableError:
            return RoutingStatusResponse(
                available=False,
                network_type=None,
                node_count=0,
                edge_count=0,
                bounding_box_w_s_e_n=None,
                retrieval_date=None,
                osmnx_version=ox.__version__,
                networkx_version=nx.__version__,
                travel_time_model=DEFAULT_TRAVEL_TIME_MODEL,
                osm_attribution=DEFAULT_ATTRIBUTION,
                traffic_note=DEFAULT_TRAFFIC_NOTE,
            )

    @classmethod
    def snap_coordinate(
        cls,
        latitude: float,
        longitude: float,
        max_dist_m: Optional[float] = None,
        strict: bool = True,
    ) -> SnappedPointResponse:
        """Snap latitude/longitude coordinate to nearest drivable road network node."""
        if not (-90.0 <= latitude <= 90.0):
            raise CoordinateOutOfBoundsError(f"Invalid latitude {latitude}. Must be between -90 and 90.")
        if not (-180.0 <= longitude <= 180.0):
            raise CoordinateOutOfBoundsError(f"Invalid longitude {longitude}. Must be between -180 and 180.")

        max_dist = max_dist_m if max_dist_m is not None else settings.MAX_SNAP_DISTANCE_METERS

        # Cache key rounded to 5 decimal places (~1.1 meter resolution)
        cache_key = (round(latitude, 5), round(longitude, 5))
        if cache_key in cls._snap_cache:
            cached = cls._snap_cache[cache_key]
            if strict and not cached.within_max_snap:
                raise SnapDistanceExceededError(
                    f"Coordinate ({latitude}, {longitude}) snap distance {cached.snap_distance_meters:.1f}m "
                    f"exceeds maximum allowed threshold of {max_dist:.1f}m."
                )
            return cached

        G = cls.load_network()

        # OSMnx nearest_nodes requires X=longitude, Y=latitude
        nearest_node, dist_m = ox.nearest_nodes(G, X=longitude, Y=latitude, return_dist=True)
        nearest_node = int(nearest_node)
        dist_m = float(dist_m)

        node_data = G.nodes[nearest_node]
        snapped_lat = float(node_data.get("y", 0.0))
        snapped_lon = float(node_data.get("x", 0.0))
        within_max = dist_m <= max_dist

        result = SnappedPointResponse(
            original_latitude=latitude,
            original_longitude=longitude,
            snapped_node_id=nearest_node,
            snapped_latitude=snapped_lat,
            snapped_longitude=snapped_lon,
            snap_distance_meters=dist_m,
            within_max_snap=within_max,
        )

        cls._snap_cache[cache_key] = result

        if strict and not within_max:
            raise SnapDistanceExceededError(
                f"Coordinate ({latitude}, {longitude}) snap distance {dist_m:.1f}m "
                f"exceeds maximum allowed threshold of {max_dist:.1f}m."
            )

        return result

    @classmethod
    def estimate_route(
        cls,
        orig_lat: float,
        orig_lon: float,
        dest_lat: float,
        dest_lon: float,
        weight: str = "travel_time",
        max_snap_dist: Optional[float] = None,
    ) -> RouteEstimateResponse:
        """Estimate road-network shortest route between origin and destination coordinates."""
        if weight not in ("travel_time", "length"):
            raise ValueError(f"Unsupported routing metric '{weight}'. Use 'travel_time' or 'length'.")

        G = cls.load_network()
        orig_snap = cls.snap_coordinate(orig_lat, orig_lon, max_dist_m=max_snap_dist, strict=True)
        dest_snap = cls.snap_coordinate(dest_lat, dest_lon, max_dist_m=max_snap_dist, strict=True)

        orig_node = orig_snap.snapped_node_id
        dest_node = dest_snap.snapped_node_id

        # Same snapped node: zero travel needed
        if orig_node == dest_node:
            route_coords = [[orig_snap.snapped_latitude, orig_snap.snapped_longitude]]
            return RouteEstimateResponse(
                origin_snapped=orig_snap,
                destination_snapped=dest_snap,
                distance_meters=0.0,
                distance_km=0.0,
                duration_seconds=0.0,
                duration_minutes=0.0,
                route_node_count=1,
                route_nodes=[orig_node],
                route_coordinates=route_coords,
                metric_used=weight,
                attribution=DEFAULT_ATTRIBUTION,
                traffic_note=DEFAULT_TRAFFIC_NOTE,
            )

        cache_key = (orig_node, dest_node, weight)
        if cache_key in cls._route_cache:
            path_nodes, total_length_m, total_time_s = cls._route_cache[cache_key]
        else:
            try:
                path_nodes = nx.shortest_path(G, orig_node, dest_node, weight=weight)
            except nx.NetworkXNoPath as no_path_err:
                raise DestinationUnreachableError(
                    f"No drivable road path exists from node {orig_node} to node {dest_node}."
                ) from no_path_err
            except nx.NodeNotFound as not_found_err:
                raise DestinationUnreachableError(
                    f"Road network node not found: {not_found_err}"
                ) from not_found_err

            # Compute exact distance (length) and travel_time along the computed path
            total_length_m = 0.0
            total_time_s = 0.0
            for u, v in zip(path_nodes[:-1], path_nodes[1:]):
                # In MultiDiGraph, pick edge with minimum weight between u and v
                edge_dict = G.get_edge_data(u, v)
                best_edge = min(edge_dict.values(), key=lambda e: float(e.get(weight, float("inf"))))
                total_length_m += float(best_edge.get("length", 0.0))
                total_time_s += float(best_edge.get("travel_time", 0.0))

            cls._route_cache[cache_key] = (path_nodes, total_length_m, total_time_s)

        route_coords = [
            [float(G.nodes[n].get("y", 0.0)), float(G.nodes[n].get("x", 0.0))]
            for n in path_nodes
        ]

        return RouteEstimateResponse(
            origin_snapped=orig_snap,
            destination_snapped=dest_snap,
            distance_meters=round(total_length_m, 2),
            distance_km=round(total_length_m / 1000.0, 3),
            duration_seconds=round(total_time_s, 1),
            duration_minutes=round(total_time_s / 60.0, 2),
            route_node_count=len(path_nodes),
            route_nodes=path_nodes,
            route_coordinates=route_coords,
            metric_used=weight,
            attribution=cls._metadata.get("osm_attribution", DEFAULT_ATTRIBUTION) if cls._metadata else DEFAULT_ATTRIBUTION,
            traffic_note=cls._metadata.get("traffic_note", DEFAULT_TRAFFIC_NOTE) if cls._metadata else DEFAULT_TRAFFIC_NOTE,
        )

    @classmethod
    def compute_matrix(
        cls,
        locations: List[LocationIdentifier],
        weight: str = "travel_time",
        max_snap_dist: Optional[float] = None,
    ) -> RoutingMatrixResponse:
        """Compute pairwise distance and estimated travel-time matrices for given locations.

        Preserves exact input order. Directly usable by GA and ACO optimization modules.
        """
        if weight not in ("travel_time", "length"):
            raise ValueError(f"Unsupported routing metric '{weight}'. Use 'travel_time' or 'length'.")

        if len(locations) < 2:
            raise ValueError("Routing matrix requires at least 2 locations.")
        if len(locations) > 50:
            raise ValueError(f"Routing matrix request exceeds maximum of 50 locations (received {len(locations)}).")

        G = cls.load_network()
        n = len(locations)
        location_ids = [loc.id for loc in locations]

        # 1. Snap all locations in input order
        snapped_nodes: List[int] = []
        for loc in locations:
            snapped = cls.snap_coordinate(loc.latitude, loc.longitude, max_dist_m=max_snap_dist, strict=True)
            snapped_nodes.append(snapped.snapped_node_id)

        # 2. Compute shortest paths using single-source Dijkstra per unique source node
        unique_sources = set(snapped_nodes)
        source_dist_map: Dict[int, Dict[int, float]] = {}
        source_time_map: Dict[int, Dict[int, float]] = {}

        for src in unique_sources:
            try:
                # Single-source Dijkstra returning shortest path trees based on requested optimization metric
                lengths, paths = nx.single_source_dijkstra(G, src, weight=weight)
                source_dist_map[src] = {}
                source_time_map[src] = {}

                for tgt, path in paths.items():
                    if src == tgt:
                        source_dist_map[src][tgt] = 0.0
                        source_time_map[src][tgt] = 0.0
                        continue

                    # Calculate actual length and travel_time along the chosen path
                    p_len = 0.0
                    p_time = 0.0
                    for u, v in zip(path[:-1], path[1:]):
                        edge_dict = G.get_edge_data(u, v)
                        best_edge = min(edge_dict.values(), key=lambda e: float(e.get(weight, float("inf"))))
                        p_len += float(best_edge.get("length", 0.0))
                        p_time += float(best_edge.get("travel_time", 0.0))

                    source_dist_map[src][tgt] = p_len
                    source_time_map[src][tgt] = p_time
            except Exception as e:
                logger.error("Dijkstra calculation failed for source node %s: %s", src, e)
                source_time_map[src] = {}
                source_dist_map[src] = {}

        # 3. Assemble N x N distance and duration matrices
        distance_matrix: List[List[Optional[float]]] = [[None] * n for _ in range(n)]
        duration_matrix: List[List[Optional[float]]] = [[None] * n for _ in range(n)]
        unreachable_pairs: List[List[str]] = []

        for i in range(n):
            src_node = snapped_nodes[i]
            for j in range(n):
                if i == j:
                    distance_matrix[i][j] = 0.0
                    duration_matrix[i][j] = 0.0
                    continue

                tgt_node = snapped_nodes[j]
                if src_node == tgt_node:
                    distance_matrix[i][j] = 0.0
                    duration_matrix[i][j] = 0.0
                    continue

                dist_val = source_dist_map.get(src_node, {}).get(tgt_node)
                time_val = source_time_map.get(src_node, {}).get(tgt_node)

                if dist_val is not None and time_val is not None:
                    distance_matrix[i][j] = round(float(dist_val), 2)
                    duration_matrix[i][j] = round(float(time_val), 1)
                else:
                    distance_matrix[i][j] = None
                    duration_matrix[i][j] = None
                    unreachable_pairs.append([location_ids[i], location_ids[j]])

        meta = cls._metadata or {}
        return RoutingMatrixResponse(
            location_ids=location_ids,
            distance_matrix_meters=distance_matrix,
            duration_matrix_seconds=duration_matrix,
            unreachable_pairs=unreachable_pairs,
            units={
                "distance": "meters",
                "duration": "seconds",
            },
            metadata={
                "matrix_dimension": n,
                "weight_model": meta.get("travel_time_model", DEFAULT_TRAVEL_TIME_MODEL),
                "osm_attribution": meta.get("osm_attribution", DEFAULT_ATTRIBUTION),
                "traffic_note": meta.get("traffic_note", DEFAULT_TRAFFIC_NOTE),
                "osmnx_version": meta.get("osmnx_version", ox.__version__),
            },
        )
