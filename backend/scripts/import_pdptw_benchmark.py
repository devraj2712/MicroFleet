import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.intelligence.osm.pdptw_benchmark import parse_pdptw_file

DEFAULT_INPUT_FILE = Path("backend/data/raw/pdp_100/LC101_sample.txt")
DEFAULT_OUTPUT_FILE = Path("backend/data/processed/pdptw_lc101_sample.json")
SINTEF_BENCHMARK_PAGE = "https://www.sintef.no/projectweb/top/pdptw/li-lim-benchmark/"
SINTEF_ZIP_ASSET = "https://www.sintef.no/contentassets/a27cfcfcfb134d1ab09117cf4872cf02/pdp_100.zip"


def probe_sintef_access():
    """Probe SINTEF server and report accessibility or security blocking status."""
    print(f"[PROVENANCE] Checking SINTEF PDPTW benchmark online repository...")
    print(f"             URL: {SINTEF_BENCHMARK_PAGE}")
    headers = {"User-Agent": "MicroFleet/1.0 (academic research)"}
    try:
        req = urllib.request.Request(SINTEF_BENCHMARK_PAGE, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"             SINTEF web portal HTTP status: {resp.status}")
    except Exception as e:
        print(f"             [NOTE] Direct programmatic access to SINTEF web portal returned: {e}")
        print("             SINTEF's Episerver CMS enforces HTTP 403 Forbidden on automated requests.")
        print("             Standard research practice: Manual browser download or local import pipeline.")


def import_benchmark(input_path: Path, output_path: Path):
    """Parse raw benchmark instance, validate pairing and constraints, and export normalized JSON."""
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()

    if not input_path.exists():
        print(f"[ERROR] Input benchmark file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[IMPORT] Parsing raw PDPTW benchmark: {input_path}")
    instance = parse_pdptw_file(input_path)

    print(f"         Instance: {instance.instance_name}")
    print(f"         Vehicles: {instance.vehicle_number}, Capacity: {instance.vehicle_capacity}")
    print(f"         Total Nodes: {len(instance.nodes)} (Depot: 1, Requests: {len(instance.requests)})")
    print(f"         Coordinate Domain: {instance.coordinate_domain[:40]}...")
    print(f"         Validation Status: {instance.validation_status}")

    if instance.validation_notes:
        print("         Validation Warnings:")
        for note in instance.validation_notes:
            print(f"           ! {note}")
    else:
        print("         Pairing Integrity: All pickup-delivery pairs and demands verified 100% consistent.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        # Pydantic v2 model_dump_json or json
        f.write(instance.model_dump_json(indent=2))

    print(f"[SAVE] Normalized benchmark instance saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Li & Lim PDPTW Public Benchmark Ingestion and Validation Pipeline.")
    parser.add_argument("--probe", action="store_true", help="Probe SINTEF server access.")
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT_FILE), help="Path to raw benchmark file.")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_FILE), help="Path to normalized JSON output.")
    args = parser.parse_args()

    probe_sintef_access()
    import_benchmark(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
