import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Put project root on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import networkx as nx
import osmnx as ox

# Bounding box for Mumbai Demonstration Spine:
# Covers Lower Parel, Dadar, Prabhadevi, Bandra, Khar, Juhu, and Andheri
# Format for OSMnx 2.x graph_from_bbox: (left, bottom, right, top) = (west, south, east, north)
DEFAULT_BBOX = (72.8100, 18.9750, 72.8650, 19.1350)
NETWORK_TYPE = "drive"
DEFAULT_OUTPUT_GRAPHML = Path("backend/data/networks/mumbai_drive_network.graphml")
DEFAULT_OUTPUT_META = Path("backend/data/networks/mumbai_drive_network.meta.json")

# Urban speed fallbacks in km/h calibrated for Mumbai mixed delivery traffic
FALLBACK_SPEED_KPH = 25.0
HIGHWAY_SPEEDS = {
    "motorway": 50.0,
    "trunk": 40.0,
    "primary": 35.0,
    "secondary": 30.0,
    "tertiary": 25.0,
    "residential": 20.0,
    "living_street": 15.0,
    "unclassified": 20.0,
}


def fetch_or_load_network(
    bbox: tuple = DEFAULT_BBOX,
    graphml_path: Path = DEFAULT_OUTPUT_GRAPHML,
    meta_path: Path = DEFAULT_OUTPUT_META,
    force_refresh: bool = False,
) -> nx.MultiDiGraph:
    """Download and cache Mumbai road network from OpenStreetMap, or load existing cache."""
    graphml_path = Path(graphml_path).resolve()
    meta_path = Path(meta_path).resolve()
    graphml_path.parent.mkdir(parents=True, exist_ok=True)

    if not force_refresh and graphml_path.exists():
        print(f"[CACHE] Found existing road network at: {graphml_path}")
        try:
            G = ox.load_graphml(graphml_path)
            print(f"[CACHE] Successfully loaded graph with {len(G.nodes)} nodes and {len(G.edges)} edges.")
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                print(f"[CACHE] Metadata: Retreived={meta.get('retrieval_date')}, OSMnx={meta.get('osmnx_version')}")
            return G
        except Exception as e:
            print(f"[WARN] Failed to read cached graphml ({e}). Re-downloading...", file=sys.stderr)

    print(f"[DOWNLOAD] Downloading OpenStreetMap '{NETWORK_TYPE}' network for bounding box:")
    print(f"           West (Left)={bbox[0]}, South (Bottom)={bbox[1]}, East (Right)={bbox[2]}, North (Top)={bbox[3]}")
    print("           Attribution: © OpenStreetMap contributors (ODbL)")

    try:
        # Download driving street network
        G = ox.graph_from_bbox(
            bbox=bbox,
            network_type=NETWORK_TYPE,
            simplify=True,
            retain_all=False,
        )
        print(f"[DOWNLOAD] Raw graph downloaded: {len(G.nodes)} nodes, {len(G.edges)} edges.")

        # Impute edge speeds and travel times
        print(f"[PROCESS] Imputing edge speeds (fallback={FALLBACK_SPEED_KPH} km/h) and travel times...")
        G = ox.add_edge_speeds(G, hwy_speeds=HIGHWAY_SPEEDS, fallback=FALLBACK_SPEED_KPH)
        G = ox.add_edge_travel_times(G)

        # Save to GraphML
        print(f"[SAVE] Saving cached network to: {graphml_path}")
        ox.save_graphml(G, filepath=graphml_path)

        # Record metadata
        meta = {
            "dataset_name": "OpenStreetMap Mumbai Delivery Corridor",
            "retrieval_date": datetime.now(timezone.utc).isoformat(),
            "osm_attribution": "© OpenStreetMap contributors, Open Database License (ODbL) 1.0",
            "bounding_box_w_s_e_n": list(bbox),
            "network_type": NETWORK_TYPE,
            "osmnx_version": ox.__version__,
            "networkx_version": nx.__version__,
            "node_count": len(G.nodes),
            "edge_count": len(G.edges),
            "travel_time_model": "Edge length with highway-specific speeds and 25 km/h urban fallback",
            "traffic_note": "Static topological free-flow estimates; does not reflect live traffic congestion.",
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        print(f"[SAVE] Metadata saved to: {meta_path}")
        print("Road network caching completed successfully.")
        return G
    except Exception as e:
        print(f"[ERROR] Failed to fetch or process OpenStreetMap road network: {e}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description="Fetch and cache OpenStreetMap driving network for Mumbai.")
    parser.add_argument("--force", action="store_true", help="Force re-download even if cache exists.")
    args = parser.parse_args()

    fetch_or_load_network(force_refresh=args.force)


if __name__ == "__main__":
    main()
