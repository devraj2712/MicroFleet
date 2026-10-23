# MicroFleet — Data Strategy, Provenance & Benchmark Plan

## 1. Overview & Data Philosophy

MicroFleet evaluates and executes multi-agent urban logistics using a combination of **real-world geospatial road networks**, **established Vehicle Routing Problem (VRP) academic benchmarks**, and **carefully modeled synthetic operational attributes**. 

To maintain scientific integrity and reproducibility:
- No dataset is claimed as downloaded or verified until explicitly acquired, checksum-validated, and parsed in future phases.
- Real road network topology is separated from order demand generation.
- All stochastic elements (customer arrival times, package weights, kitchen preparation delays) are deterministically generated via seeded pseudo-random processes.

---

## 2. Candidate Datasets & Academic Benchmarks

The following candidate data sources have been identified for algorithmic validation and benchmarking. None of these have been downloaded or bundled in the initial workspace; they represent the acquisition targets for subsequent phases:

| Candidate Dataset | Origin / Reference | Primary Application | Status |
| :--- | :--- | :--- | :--- |
| **Li & Lim PDPTW Benchmark** | Li & Lim (2001), *Transportation Science* / SINTEF TOP | Gold standard for Pickup-and-Delivery Problem with Time Windows (paired nodes, capacities) | **Candidate / Local Test Fixture** *(Automated download blocked by SINTEF CMS HTTP 403; local test fixture used for format verification)* |
| **Solomon VRPTW Benchmark** | Solomon (1987), *Operations Research* | Vehicle Routing Problem with Time Windows (clustered vs. randomized customer distributions) | **Candidate** *(Not downloaded)* |

| **OpenStreetMap (OSM) Extracts** | OpenStreetMap Foundation (ODbL) via OSMnx 2.1.1 | Real-world road network graph, street hierarchy, travel speeds, and node connectivity | **Acquired & Cached** *(Mumbai Delivery Corridor: 9,240 nodes, 20,457 edges)* |
| **Instacart Market Basket Data** | Kaggle / Instacart Public Research Release | Distribution of parcel item counts, order clustering, and temporal order arrival patterns | **Candidate** *(Evaluation only)* |
| **NYC Taxi & Limousine Ride Records** | NYC TLC Open Data | Real urban travel times and spatial pickup-dropoff density distributions | **Candidate** *(Optional reference)* |

---

## 3. Road Network Pipeline: OpenStreetMap & OSMnx

### 3.1 Network Ingestion Architecture
Rather than relying on proprietary, rate-limited mapping APIs, MicroFleet utilizes OSMnx to download and process OpenStreetMap street networks:
1. **Target Region Selection**: The Mumbai demonstration corridor covering Lower Parel, Dadar, Prabhadevi, Bandra, Khar, Juhu, and Andheri with bounding box:
   - West (Left): `72.8100`
   - South (Bottom): `18.9750`
   - East (Right): `72.8650`
   - North (Top): `19.1350`
2. **Network Type**: Filtered for drivable delivery roads (`network_type='drive'`).
3. **Graph Simplification**: Geometric intersections simplified (`simplify=True`) while preserving access topology.
4. **Edge Speeds & Travel Times**: Edge speeds imputed using street hierarchy (motorway: 50 km/h, primary: 35 km/h, secondary: 30 km/h, tertiary: 25 km/h, residential: 20 km/h) with a conservative urban fallback of `25.0 km/h`. Free-flow travel times computed per edge using `ox.add_edge_travel_times`.
   - *Note*: These values represent topological free-flow estimates, NOT live traffic sensor data.
5. **Persistence**: The extracted `MultiDiGraph` is serialized locally to:
   - GraphML: `backend/data/networks/mumbai_drive_network.graphml` (ignored by Git)
   - Metadata: `backend/data/networks/mumbai_drive_network.meta.json` (contains attribution, bbox, node/edge counts, retrieval timestamp).
6. **Reproducible Command**:
   ```bash
   backend/.venv/Scripts/python backend/scripts/fetch_mumbai_network.py [--force]
   ```

### 3.2 Geospatial Coordinate Snapping & Matrix Generation
- **Coordinate Snapping**: `OSMService.snap_coordinate(latitude, longitude, max_dist_m=1000)` maps coordinates to the nearest road network node using OSMnx spatial indices. Points exceeding the maximum snap threshold or out-of-bounds coordinates are strictly rejected.
- **Shortest Path Computation**: Pairwise travel time and distance estimates computed via directed Dijkstra over the graph. One-way restrictions and turn impedances are respected.
- **Matrix Service**: `OSMService.compute_matrix(locations, weight)` computes $N \times N$ distance and duration matrices using single-source Dijkstra trees, preserving input ordering and detecting disconnected/unreachable nodes.
- **Caching**: Snapped node coordinates and pairwise route estimates are cached in memory to eliminate redundant graph traversals.


---

## 4. Operational Attributes: Real vs. Synthesized Breakdown

Public VRP benchmarks provide spatial coordinates and capacities, but do not provide the dynamic operational attributes required by modern app-driven fleets (e.g., kitchen preparation statuses, customer SLA priority tiers, rider battery percentages). 

The table below delineates the source of each field:

| Entity | Attribute | Source Type | Acquisition / Synthesis Strategy |
| :--- | :--- | :--- | :--- |
| **Merchant** | Name, Address | Real / Synthetic | Seeded generator mapped to real urban points of interest |
| | Latitude, Longitude | Real OSM Nodes | Sampled uniformly from commercial street nodes in OSM graph |
| | Average Prep Time | Synthesized | Uniform distribution: $U(10, 25)$ minutes |
| **Order** | Pickup Location | Real OSM Nodes | Associated merchant's road node |
| | Drop-off Location | Real OSM Nodes | Sampled from residential street nodes within radius $R \le 6\text{ km}$ |
| | Weight (kg) | Synthesized | Log-normal distribution: $\mu=2.5\text{ kg}, \sigma=1.2\text{ kg}$, max $15\text{ kg}$ |
| | Volume ($\text{m}^3$) | Synthesized | Proportional to weight with random packaging factor |
| | Creation Timestamp | Simulated Clock | Deterministic arrival sequence following Poisson process |
| | Promised SLA Deadline | Derived | $\text{Timestamp} + \text{PrepTime} + \text{DirectTravelTime} + \text{Buffer}(20\text{ min})$ |
| | Kitchen Prep Delay | Synthesized | Truncated Gaussian $\mathcal{N}(0, 5\text{ min})$ modeling merchant variance |
| | Customer Priority Tier | Synthesized | Categorical: `STANDARD` (70%), `PREMIUM` (20%), `VIP` (10%) |
| **Rider** | Initial Position | Real OSM Nodes | Distributed randomly across urban sector hubs |
| | Payload Capacity | Configured | Fixed: $25\text{ kg}$ weight, $0.15\text{ m}^3$ volume (cargo two-wheeler) |
| | Battery / Fuel State | Synthesized | Uniform: $U(30\%, 100\%)$ at shift start |
| | Remaining Shift Time | Synthesized | Uniform: $U(60, 360)$ minutes |

---

## 5. Schema Validation & Data Contracts

All data flowing between the storage layer, the API endpoints, and the intelligence algorithms will be strictly validated using **Pydantic v2 schemas**.

### Core Schemas:
- `MerchantSchema`: Identity, verified road node, operational status.
- `OrderCreateSchema` / `OrderSchema`: Full order details, coordinates, dimensions, SLA timestamps.
- `RiderStateSchema`: Fleet telemetry, active capacity, current location.
- `BatchSchema`: List of orders assigned to a single cluster, aggregate weight and volume.
- `RouteSchema`: Ordered sequence of `WaypointSchema` objects with estimated arrival times.
- `BenchmarkScenarioSchema`: Complete reproducible configuration containing order list, merchant list, rider fleet, and road graph identifier.

---

## 6. Reproducible Benchmark Scenarios

To ensure scientific measurement and prevent regression during algorithm iteration, three deterministic scenario tiers will be generated via `backend/scripts/generate_scenarios.py`:

### Scenario Tier A: Micro Cluster (Smoke & Sanity Test)
- **Scale**: 10 Orders, 3 Merchants, 2 Riders.
- **Area**: $2\text{ km} \times 2\text{ km}$ urban district.
- **Purpose**: Rapid algorithm unit tests, visual debugging of routes, and verification of precedence constraints (no delivery before pickup).
- **Execution Target**: Total dispatch cycle $< 500\text{ ms}$.

### Scenario Tier B: Urban Sector (Standard Evaluation)
- **Scale**: 50 Orders, 10 Merchants, 8 Riders.
- **Area**: $6\text{ km} \times 6\text{ km}$ urban subregion.
- **Purpose**: Core benchmarking of GA batching efficiency, ACO tour length, and RL rider matching against baseline heuristics (FCFS, Greedy Nearest-Neighbor).
- **Execution Target**: Total dispatch cycle $< 5\text{ s}$.

### Scenario Tier C: Dense Peak Hour (Stress & Scalability Test)
- **Scale**: 200 Orders, 30 Merchants, 25 Riders.
- **Area**: $12\text{ km} \times 12\text{ km}$ metropolitan cluster.
- **Purpose**: Evaluation of algorithmic scaling, memory usage, GA convergence stability, and RL inference latency under heavy load.
- **Execution Target**: Total dispatch cycle $< 30\text{ s}$.

---

## 7. Public Pickup-and-Delivery Benchmark Pipeline (Li & Lim PDPTW)

### 7.1 Provenance & License
- **Origin**: Li & Lim (2001), *A Metaheuristic for the Pickup and Delivery Problem with Time Windows*, based on Solomon (1987) instances extended with paired precedence and demand symmetry.
- **Repository**: Hosted by SINTEF Digital, Department of Mathematics and Cybernetics (`https://www.sintef.no/projectweb/top/pdptw/li-lim-benchmark/`).
- **License**: Freely accessible for scientific, educational, and academic benchmarking.
- **Retrieval Blocker & Resolution**: Automated programmatic HTTP downloads directly from SINTEF's CMS (`/contentassets/.../pdp_100.zip`) return `HTTP Error 403: Forbidden` due to server-side anti-scraping / Episerver CMS protection. In accordance with project protocol, this blocker is explicitly documented. To enable offline parser and data pipeline implementation without making unverified claims, a local test fixture was authored based on the documented format:
  - Local Test Fixture: `backend/data/raw/pdp_100/LC101_sample.txt` *(format verification fixture; does NOT imply official archive download)*
  - Ingestion & validation script: `backend/scripts/import_pdptw_benchmark.py`
  - Normalized JSON artifact: `backend/data/processed/pdptw_lc101_sample.json`


### 7.2 Ingestion & Integrity Validation
The parser validates all structural and mathematical invariants:
1. **Depot Invariant**: Customer 0 has demand 0, service time 0, and pickup/delivery indices of 0.
2. **Precedence Pairing**: For every pickup node $p$, corresponding delivery node $d$ exists and explicitly points back to $p$ (`pickup_node == p`).
3. **Demand Symmetry**: $\text{demand}(p) = -\text{demand}(d)$ and $\text{demand}(p) \le \text{vehicle\_capacity}$.
4. **Time Windows**: $\text{ready\_time} \le \text{due\_date}$ for all nodes.

### 7.3 Reproducible Command
```bash
backend/.venv/Scripts/python backend/scripts/import_pdptw_benchmark.py --probe
```

---

## 8. Separation of Data Domains: Benchmark vs. Geographic Data

To prevent methodological errors:
- **Real Mumbai Data**: Evaluated strictly through `OSMService` using actual OpenStreetMap network topology, node coordinates $(lat, lon)$, directed one-way edges, and estimated travel times.
- **Abstract Academic Benchmarks (Li & Lim)**: Evaluated using standard 2D Euclidean distance ($d = \sqrt{(x_1 - x_2)^2 + (y_1 - y_2)^2}$) and instance-native time units. Benchmark nodes are **never** snapped to arbitrary Mumbai roads or misrepresented as geographic coordinates.

