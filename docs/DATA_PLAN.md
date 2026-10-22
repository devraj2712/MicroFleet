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
| **Li & Lim PDPTW Benchmark** | Li & Lim (2001), *Transportation Science* | Golden standard for Pickup-and-Delivery Problem with Time Windows (paired nodes, capacities) | **Candidate** *(Not downloaded)* |
| **Solomon VRPTW Benchmark** | Solomon (1987), *Operations Research* | Vehicle Routing Problem with Time Windows (clustered vs. randomized customer distributions) | **Candidate** *(Not downloaded)* |
| **OpenStreetMap (OSM) Extracts** | OpenStreetMap Foundation (ODbL) via OSMnx | Real-world road network graph, street hierarchy, travel speeds, and node connectivity | **Candidate** *(To be fetched via script)* |
| **Instacart Market Basket Data** | Kaggle / Instacart Public Research Release | Distribution of parcel item counts, order clustering, and temporal order arrival patterns | **Candidate** *(Evaluation only)* |
| **NYC Taxi & Limousine Ride Records** | NYC TLC Open Data | Real urban travel times and spatial pickup-dropoff density distributions | **Candidate** *(Optional reference)* |

---

## 3. Road Network Pipeline: OpenStreetMap & OSMnx

### 3.1 Network Ingestion Architecture
Rather than relying on proprietary, rate-limited mapping APIs, MicroFleet utilizes OSMnx to download and process OpenStreetMap street networks:
1. **Target Region Selection**: A bounded urban subregion (e.g., commercial district such as Shivajinagar/Kothrud, Pune, or a defined bounding box `[north, south, east, west]`).
2. **Network Type**: Filtered for driveable roads (`network_type='drive'`) or bicycle/two-wheeler accessible infrastructure (`network_type='bike'`).
3. **Graph Simplification**: Dead-ends retained for delivery access, but intermediate geometric nodes without intersections simplified to reduce memory footprint.
4. **Edge Impedances**: Edge weights computed from actual road lengths (`meters`) and imputed speed limits (`speed_kph`), yielding edge travel times (`seconds`).
5. **Persistence**: The extracted `MultiDiGraph` is serialized to `backend/data/networks/<region_name>.graphml`.

### 3.2 Geospatial Coordinate Snapping & Matrix Generation
- **Coordinate Snapping**: For any arbitrary geographic point $(lat, lon)$ generated for a merchant or recipient, `ox.distance.nearest_nodes` snaps to the nearest navigable road node.
- **Shortest Path Computation**: Pairwise travel time and distance matrices are computed using Dijkstra or A* algorithms over the cached graph.
- **Matrix Caching**: For a batch of $N$ locations, the $N \times N$ matrix is stored in-memory during optimization to avoid redundant shortest-path recomputations.

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
