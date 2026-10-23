# MicroFleet — Intelligent Shared Last-Mile Logistics

MicroFleet is an intelligent shared last-mile logistics platform designed for local merchant cooperatives and shared delivery fleets. This repository contains the native Android application (Java/XML) and the Python FastAPI backend service with SQLite local persistence.

---

## 1. Backend Quickstart

### Prerequisites
- Python 3.12 (`py -3.12` or `python`)
- Git

### Virtual Environment & Dependencies
Create and activate an isolated virtual environment under `backend/.venv`:

```powershell
# Create Python 3.12 venv
py -3.12 -m venv backend/.venv

# Install dependencies
backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
```

### Seed Deterministic Demo Data
Run the idempotent Mumbai demo dataset seeder (creates 3 merchants, 3 riders, 4 simulated orders):

```powershell
backend\.venv\Scripts\python.exe backend\scripts\seed_demo.py
```

### Start the FastAPI Backend
Run the backend on `0.0.0.0:8000` so it is accessible to both localhost and the Android emulator:

```powershell
backend\.venv\Scripts\uvicorn.exe backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)

### Run Automated Backend Tests
Run the comprehensive test suite with pytest (covers health, merchants, riders, orders, state transitions, geospatial snapping, route estimation, routing matrix, and benchmark parsing):

```powershell
backend\.venv\Scripts\pytest.exe -v backend\tests
```

---

## 2. Milestone 2: Geospatial & Routing Infrastructure

### Download and Cache Mumbai Road Network
Fetch OpenStreetMap drivable street network data for the Mumbai demonstration corridor (Lower Parel, Dadar, Prabhadevi, Bandra, Khar, Juhu, Andheri):

```powershell
backend\.venv\Scripts\python.exe backend\scripts\fetch_mumbai_network.py [--force]
```
- Saved to: `backend/data/networks/mumbai_drive_network.graphml` (ignored by Git)
- Metadata: `backend/data/networks/mumbai_drive_network.meta.json` (ODbL attribution, bounding box, 9,240 nodes, 20,457 edges)
- *Fallback*: If OpenStreetMap Overpass servers experience temporary rate-limiting, the script will reuse the existing cached `.graphml` without failing.

### Ingest Public Pickup-and-Delivery Benchmark (Li & Lim PDPTW)
Parse, validate, and normalize public Li & Lim benchmark instances:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\import_pdptw_benchmark.py --probe
```
- Normalized JSON saved to: `backend/data/processed/pdptw_lc101_sample.json`
- *Note on Access*: Direct automated downloads of raw zip archives from SINTEF CMS return `HTTP 403 Forbidden` due to server-side anti-scraping policies. The repository bundles a canonical raw instance (`backend/data/raw/pdp_100/LC101_sample.txt`) for deterministic offline validation.

### Routing Endpoints

#### 1. Check Routing Network Status
```http
GET /api/v1/routing/status
```
Returns network availability, node/edge counts, bounding box coordinates, and travel-time model metadata.

#### 2. Estimate Route Distance & Travel Time
```http
POST /api/v1/routing/estimate
Content-Type: application/json

{
  "origin": {"latitude": 19.0596, "longitude": 72.8295},
  "destination": {"latitude": 19.0178, "longitude": 72.8478},
  "weight": "travel_time"
}
```
Returns snapped road nodes, distance (m/km), duration (s/min), and ordered route coordinate sequence `[[lat, lon], ...]`.

#### 3. Compute Distance & Travel-Time Matrix
```http
POST /api/v1/routing/matrix
Content-Type: application/json

{
  "locations": [
    {"id": "M-MUM-01", "latitude": 19.0596, "longitude": 72.8295},
    {"id": "M-MUM-02", "latitude": 19.0178, "longitude": 72.8478},
    {"id": "M-MUM-03", "latitude": 18.9953, "longitude": 72.8288}
  ],
  "weight": "travel_time"
}
```
Returns $N \times N$ distance and duration matrices maintaining input ordering for GA batching and ACO route optimization.

### Data Domains: Real Road Data vs. Abstract Benchmarks
- **Real Mumbai Operations**: Evaluated strictly through `OSMService` using OpenStreetMap road network geometry, one-way constraints, and speed-imputed free-flow travel times (fallback 25 km/h). *Not live traffic sensor predictions.*
- **Abstract Benchmarks (Li & Lim)**: Evaluated using standard 2D Euclidean distance and benchmark time units. Abstract points are never mapped or snapped to arbitrary real-world coordinates.

---

## 3. Milestone 3: Fuzzy Logic Urgency & Genetic Algorithm Batching

### Preview Fuzzy Order Urgency Scoring
Evaluates deadline slack, waiting time, and priority using a Mamdani-style fuzzy inference engine with centroid defuzzification:

```http
POST /api/v1/optimization/urgency/preview
Content-Type: application/json

{
  "order_ids": ["ORD-MUM-01", "ORD-MUM-04"],
  "limit": 50
}
```
Returns order ID, numerical urgency score (0-100), category (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), estimated solo travel time, calculated deadline slack, and contributing rules.

### Preview GA Batch Optimization & Baseline Comparison
Executes the Genetic Algorithm to partition pending orders into capacity- and compatibility-compliant shared delivery batches. Compares against Independent Orders (solo deliveries) and Deterministic Greedy Batching:

```http
POST /api/v1/optimization/batches/preview
Content-Type: application/json

{
  "ga_config": {
    "population_size": 30,
    "generations": 30,
    "mutation_rate": 0.25,
    "crossover_rate": 0.80,
    "random_seed": 42
  }
}
```
*Note on Preview Mode*: Both preview endpoints evaluate the current state without modifying database records or changing order statuses.

---

## 4. Milestone 4: Ant Colony Optimization (ACO) Pickup-and-Delivery Routing

### Preview ACO Route Optimization & Greedy Baseline Comparison
Optimizes the exact stop-level sequence of pickup and delivery events for GA-proposed batches using Ant Colony Optimization (ACO). Enforces strict operational constraints:
- **Pickup-before-delivery precedence**: Each order's pickup event strictly precedes its delivery.
- **Cumulative onboard capacity**: Dynamic onboard weight (kg) and package counts tracked after every event; vehicle capacity cannot be exceeded at any intermediate stop.
- **Delivery deadlines**: Arrival times estimated with directed road-network travel times and service allowances, enforcing hard deadlines.
- **Candidate rider origins**: Evaluates distinct candidate routes for capacity-compatible fleet riders based on their current coordinates.

```http
POST /api/v1/optimization/routes/preview
Content-Type: application/json

{
  "aco_config": {
    "num_ants": 10,
    "max_iterations": 15,
    "alpha": 1.0,
    "beta": 2.0,
    "evaporation_rate": 0.15,
    "q_deposit": 100.0,
    "random_seed": 42,
    "service_time_seconds": 180.0,
    "max_candidate_riders": 3
  },
  "ga_config": {
    "population_size": 30,
    "generations": 30,
    "random_seed": 42
  }
}
```
*Note on Preview Mode*: Evaluates multi-rider route candidates and compares best feasible ACO route against a deterministic greedy baseline without persisting dispatch assignments or mutating order statuses.

---

## 5. Milestone 5: Reinforcement Learning (RL) for Sequential Rider Assignment

### Train MaskablePPO Dispatch Policy
Train the discrete action-masked PPO policy using the custom Gymnasium `RiderAssignmentEnv`:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\train_rider_assignment.py --timesteps 15000 --seed 42 --eval-scenarios 20
```

- **Environment**: Custom Gymnasium `RiderAssignmentEnv` simulating sequential fleet dispatch.
- **Observation Space**: Fixed 57-dimensional continuous vector normalized to $[-1.0, 1.0]$ (batch urgency, deadline slack, package counts, candidate rider route distance, travel duration, deadline feasibility margin, rider workload, availability lag, proximity, and capacity).
- **Action Space**: Discrete action space with $K=5$ rider slots plus 1 defer action (`Discrete(6)`). Invalid or overloaded riders are masked out via `action_masks()`.
- **Model Checkpoint**: Saved to `backend/models/rider_assignment_maskable_ppo.zip`.
- **Metadata**: Recorded in `backend/models/rider_assignment_maskable_ppo.meta.json`.
- **Evaluation Report**: Saved to `backend/reports/dispatch_evaluation_report.json` comparing MaskablePPO against Nearest-Feasible, Least-Loaded-Feasible, and Weighted-Score baselines across 20 held-out scenarios.

### Preview Integrated End-to-End Dispatch
Executes the unified in-process pipeline: **Fuzzy Urgency $\to$ GA Batching $\to$ ACO Routing $\to$ RL Rider Assignment**:

```http
POST /api/v1/optimization/dispatch/preview
Content-Type: application/json

{
  "policy": "rl",
  "random_seed": 42,
  "aco_config": {
    "num_ants": 10,
    "max_iterations": 15,
    "random_seed": 42
  },
  "ga_config": {
    "population_size": 30,
    "generations": 30,
    "random_seed": 42
  }
}
```

Returns:
- Proposed batches and assigned rider IDs.
- Candidate rider-route options evaluated by the policy.
- Stop sequence, predicted arrival times, travel distance (km), and travel duration (min).
- Dynamic rider workload before and after assignment.
- Simulation timeline and deferred batch diagnostics.
- Comparative baseline metrics summary evaluated on the exact same scenario.

*Note on Preview Mode*: This endpoint is read-only. It performs in-process simulation without mutating persisted order statuses, rider availability, or database records.

---

## 6. Android Client Application

### Prerequisites
- Android Studio Ladybug / Meerkat (or compatible)
- JDK 21 (Temurin-21 or Android Studio embedded JDK)
- Android SDK Platform 36/37, Platform-Tools (ADB)

### Build Debug APK
Build the debug APK using the project's Gradle wrapper:

```powershell
.\gradlew.bat assembleDebug
```

The compiled APK will be generated at:
`app\build\outputs\apk\debug\app-debug.apk`

### Launch on Android Emulator
1. Start an Android Virtual Device (AVD) from Android Studio Device Manager.
2. The Android application connects to the host machine via:
   ```
   http://10.0.2.2:8000/
   ```
   *Note: `10.0.2.2` is the standard Android emulator loopback alias for the development host (`127.0.0.1`). If testing with a physical Android device over Wi-Fi, update the Server URL in the app's "Configure Server URL" dialog to your host machine's LAN IP.*

---

---

## 7. Milestone 6: Full Integration, Authentication & Operational Dispatch Workflow

### Dual Authentication Modes

MicroFleet supports two configurable authentication modes via `.env`:

1. **`AUTH_MODE=development` (Default)**:
   - Built for zero-friction local development and offline automated testing.
   - Accepts Bearer tokens generated by `/api/v1/auth/login` or development identity headers (`X-Dev-User-Email`).
   - Seeds 4 deterministic role profiles:
     - `merchant@microfleet.dev` (Role: `MERCHANT`, linked to `M-MUM-01`)
     - `rider@microfleet.dev` (Role: `RIDER`, linked to `R-MUM-01`)
     - `dispatcher@microfleet.dev` (Role: `DISPATCHER`)
     - `admin@microfleet.dev` (Role: `ADMIN`)
   - Default password for all seeded accounts: `password123`.

2. **`AUTH_MODE=firebase`**:
   - Enforces strict verification of incoming Firebase ID tokens using the official Python `firebase-admin` SDK.
   - Rejects missing, expired, or malformed tokens.
   - Resolves Firebase `uid` and `email` against the authorized `users` table to enforce backend resource permissions.
   - To configure:
     1. Create a Firebase project in the [Firebase Console](https://console.firebase.google.com/).
     2. Register the Android application with package name `com.example.microfleet`.
     3. Enable **Email/Password** authentication in the Firebase Authentication tab.
     4. Generate a private service account key under *Project Settings > Service accounts* and save to an external secure path (e.g. `C:/secrets/firebase-adminsdk.json`).
     5. Set `AUTH_MODE=firebase` and `FIREBASE_SERVICE_ACCOUNT_PATH=C:/secrets/firebase-adminsdk.json` in your `.env`.
     6. Download `google-services.json` and place it in the `app/` directory of the Android project.

### Role-Based Access Control (RBAC)

Resource-level isolation is strictly enforced on the FastAPI backend:
- **`MERCHANT`**: Can only view their own orders and submit orders for their own merchant ID. Cannot access dispatch previews or route assignments.
- **`RIDER`**: Can only access assigned routes/batches assigned to their own rider ID. Can transition deliveries they handle (`PICKED_UP`, `DELIVERED`). Cannot view other riders' routes.
- **`DISPATCHER` / `ADMIN`**: Authorized to run optimization previews, inspect fleet status, and commit dispatch plans.
- **Admin Provisioning**: Users cannot self-register as `DISPATCHER` or `ADMIN`. Accounts must be provisioned via `POST /api/v1/auth/provision-admin` with the secret `ADMIN_PROVISION_SECRET`.

### Operational Dispatch Workflow Endpoints

#### 1. Confirm & Commit Dispatch Plan (Transactional)
Turns an approved preview draft into persisted operational assignments within a single ACID transaction:
```http
POST /api/v1/optimization/dispatch/commit
Authorization: Bearer <dispatcher-token>
Content-Type: application/json

{
  "preview_id": "DRAFT-CF8CF834F73C",
  "approved_batch_ids": ["BATCH-GA-01", "BATCH-GA-02"]
}
```
- Validates preview draft existence, expiry (default: 30 minutes), and order pending states.
- Creates permanent `Batch`, `BatchOrder`, and `Route` records.
- Transitions affected orders from `PENDING` to `BATCHED` / `DISPATCHED`.
- Updates assigned rider status.
- Idempotent: Repeat submissions or expired drafts are rejected with HTTP 400.

#### 2. Rider Delivery Progression
```http
GET /api/v1/riders/{id}/assigned-routes
Authorization: Bearer <rider-token>
```
Returns assigned batches, ordered itinerary stops, expected arrival times, and associated orders.

```http
POST /api/v1/riders/{id}/routes/{route_id}/start
Authorization: Bearer <rider-token>
```
Starts the route, transitioning orders to `DISPATCHED`.

```http
PATCH /api/v1/orders/{id}/status
Authorization: Bearer <rider-token>
Content-Type: application/json

{
  "status": "PICKED_UP"  // or "DELIVERED"
}
```
Progresses order lifecycle through valid state machine transitions (`DISPATCHED` $\to$ `PICKED_UP` $\to$ `DELIVERED`). Automatically marks the parent batch `COMPLETED` when all orders are delivered.

---

## 8. Android Client Architecture

The native Android app (`com.example.microfleet`) provides role-tailored dashboards:
- **`LoginActivity`**: Email & password authentication with quick-dev mode buttons (`Merchant`, `Dispatcher`, `Rider`) and dev mode banner. Automatically navigates to role-specific dashboard upon successful profile resolution.
- **`MainActivity`** (Merchant): Displays merchant information, order creation form with pre-selected merchant profile, and orders list showing real-time batch/rider assignments and delivery states.
- **`DispatcherActivity`** (Dispatcher): Displays fleet status (pending orders, available riders), optimization preview trigger, expandable proposed batch cards with ordered stops and fuzzy urgency scores, unassigned batch diagnostics, baseline policy comparisons, and one-click dispatch plan commitment.
- **`RiderActivity`** (Rider): Itinerary with ordered stops, "Start Route" action, individual order delivery progress (`Mark Picked Up`, `Mark Delivered`), and completed vs outstanding delivery counters.

---

## 9. Operational Capabilities & Architecture

- **Milestone 1**: Native Android client (Java/XML) connected to FastAPI backend with SQLite persistence, order CRUD, and status tracking.
- **Milestone 2**: Real OpenStreetMap driving network (OSMnx 2.1.1) covering the Mumbai delivery corridor (Bandra, Khar, Juhu, Andheri, Dadar, Lower Parel) with local GraphML caching, nearest-node coordinate snapping, route estimation, pairwise distance/duration matrices, and Li & Lim PDPTW academic benchmark pipeline.
- **Milestone 3**: Mamdani Fuzzy Logic order urgency engine and Genetic Algorithm multi-order batching with capacity, compatibility (medical vs perishable), and precedence constraints, with comparative baselines (independent orders and greedy batching).
- **Milestone 4**: Ant Colony Optimization (ACO) pickup-and-delivery route engine evaluating candidate rider origins, cumulative onboard weight/package capacity, pickup-before-delivery precedence, and delivery deadlines, with deterministic greedy baseline comparison.
- **Milestone 5**: Reinforcement Learning (MaskablePPO) sequential fleet rider assignment environment, reward formulation, model persistence, held-out baseline benchmarking, and integrated read-only preview API (`/api/v1/optimization/dispatch/preview`).
- **Milestone 6**: Dual authentication (`development` + `firebase`), user profiles and RBAC, metric-consistent preview reporting, persistent snapshot draft confirmation (`POST /api/v1/optimization/dispatch/commit`), rider delivery progression, and complete role-specific Android screens (`LoginActivity`, `DispatcherActivity`, `RiderActivity`).

---

## 10. Development Constraints & Research Limitations

- **Road Network**: OpenStreetMap driving network represents static road topology. Travel duration estimates use a fixed 30 km/h urban speed model and do not incorporate live traffic feeds.
- **Academic Benchmark**: Direct Sintef CMS download returned HTTP 403; local sample `LC101_sample.txt` is bundled for offline test validation.
- **Policy Comparison**: In simulation evaluations, RL (MaskablePPO) achieves higher mean composite reward, whereas greedy and nearest heuristics may achieve shorter pure travel distance. RL should not be presented as universally superior across every metric.
- **Firebase Status**: Firebase Admin SDK and client architecture are fully implemented and ready for activation upon supplying `google-services.json` and a service account credential. Development mode is active and verified by default.
- **Model Checkpoints**: PyTorch checkpoints (`.zip`) are excluded from Git per `.gitignore`. The RL model can be retrained locally using `backend/scripts/train_rider_assignment.py`.

