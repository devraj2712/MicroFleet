import copy
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from backend.app.intelligence.fuzzy.fuzzy_urgency import FuzzyUrgencyEngine, FuzzyUrgencyResult
from backend.app.intelligence.osm.osm_service import LocationIdentifier, OSMService

logger = logging.getLogger(__name__)


class GAConfig(BaseModel):
    """Configuration hyperparameters for the Genetic Algorithm batching engine."""
    population_size: int = Field(default=30, ge=10, le=100)
    generations: int = Field(default=30, ge=5, le=100)
    mutation_rate: float = Field(default=0.25, ge=0.01, le=1.0)
    crossover_rate: float = Field(default=0.80, ge=0.1, le=1.0)
    tournament_size: int = Field(default=3, ge=2, le=10)
    elitism_count: int = Field(default=2, ge=1, le=5)
    random_seed: Optional[int] = None
    service_time_seconds: float = Field(default=180.0, description="Service time per stop in seconds")


class StopPreview(BaseModel):
    stop_index: int
    stop_type: str  # "PICKUP" or "DELIVERY"
    order_id: str
    latitude: float
    longitude: float
    estimated_arrival_offset_seconds: float
    estimated_arrival_time: datetime
    deadline: Optional[datetime] = None
    is_on_time: bool = True


class BatchResult(BaseModel):
    batch_id: str
    order_ids: List[str]
    designated_rider_id: str
    rider_display_name: str
    eligible_rider_ids: List[str] = Field(
        default_factory=list,
        description="IDs of all available fleet riders capable of carrying this batch (candidate options for ACO)",
    )
    total_weight_kg: float

    total_packages: int
    weight_utilization_pct: float
    package_utilization_pct: float
    estimated_distance_km: float
    estimated_duration_min: float
    stops: List[StopPreview]
    deadline_feasible: bool
    lateness_minutes: float
    average_urgency: float
    compatibility_verified: bool = True
    precedence_verified: bool = True


class UnassignableOrderResult(BaseModel):
    order_id: str
    reason: str


class BaselineSummary(BaseModel):
    name: str
    total_batches: int
    total_distance_km: float
    total_duration_min: float
    deadline_feasible_orders_count: int
    total_orders_assigned: int
    unassignable_orders_count: int
    average_capacity_utilization_pct: float


class GASolutionResult(BaseModel):
    batches: List[BatchResult]
    total_batches: int
    total_distance_km: float
    total_duration_min: float
    all_deadlines_met: bool
    average_urgency_score: float
    average_capacity_utilization_pct: float
    fitness_history: List[Dict[str, Any]]
    execution_time_ms: float
    algorithm_metadata: Dict[str, Any]


class BaselineComparisonResult(BaseModel):
    ga_solution: GASolutionResult
    independent_baseline: BaselineSummary
    greedy_baseline: BaselineSummary
    unassignable_orders: List[UnassignableOrderResult]
    preview_mode: bool = True


def check_order_compatibility(order_a: Any, order_b: Any) -> Tuple[bool, Optional[str]]:
    """Verify physical and regulatory compatibility between two orders sharing a vehicle.

    Explicit Documented Rules:
      1. MEDICAL prescription pharmaceuticals cannot share a delivery container with
         PERISHABLE groceries or baked foods (cross-contamination safety).
      2. Incompatible handling instructions (e.g. volatile/ambient vs cold chain).
    """
    type_a = str(getattr(order_a, "package_type", "") or "").upper()
    type_b = str(getattr(order_b, "package_type", "") or "").upper()

    if (type_a == "MEDICAL" and type_b == "PERISHABLE") or (type_a == "PERISHABLE" and type_b == "MEDICAL"):
        return False, f"Safety conflict: MEDICAL pharmaceuticals cannot share cargo with PERISHABLE foods."

    req_a = str(getattr(order_a, "handling_requirements", "") or "").lower()
    req_b = str(getattr(order_b, "handling_requirements", "") or "").lower()

    if ("keep dry" in req_a and "perishable" in req_b) or ("keep dry" in req_b and "perishable" in req_a):
        return False, "Conflicting humidity/handling requirements."

    return True, None


def is_batch_compatible(orders: List[Any]) -> Tuple[bool, Optional[str]]:
    """Verify that all orders within a candidate batch are mutually compatible."""
    for i in range(len(orders)):
        for j in range(i + 1, len(orders)):
            compat, reason = check_order_compatibility(orders[i], orders[j])
            if not compat:
                return False, reason
    return True, None


def find_capable_rider(orders: List[Any], riders: List[Any]) -> Optional[Any]:
    """Find the best-matching available rider capable of carrying the batch."""
    total_weight = sum(float(getattr(o, "weight_kg", 1.0)) for o in orders)
    total_pkgs = sum(int(getattr(o, "package_count", 1)) for o in orders)

    capable_riders = [
        r for r in riders
        if bool(getattr(r, "is_available", True))
        and float(getattr(r, "weight_capacity_kg", 20.0)) >= total_weight
        and int(getattr(r, "package_count_capacity", 10)) >= total_pkgs
    ]

    if not capable_riders:
        return None

    # Pick rider that maximizes capacity utilization without exceeding limits (tightest fit)
    return min(capable_riders, key=lambda r: float(getattr(r, "weight_capacity_kg", 20.0)))


class GABatchingEngine:
    """Genetic Algorithm for optimizing multi-order batching with vehicle routing constraints."""

    @classmethod
    def build_cost_matrix(
        cls,
        orders: List[Any],
        riders: List[Any],
    ) -> Dict[Tuple[str, str], Tuple[float, float]]:
        """Precompute road-network distance (m) and travel time (s) matrix for all locations."""
        location_objs: List[LocationIdentifier] = []
        loc_map: Dict[str, Tuple[float, float]] = {}

        # Register pickup and delivery locations for each order
        for o in orders:
            p_id = f"P_{o.id}"
            d_id = f"D_{o.id}"
            if p_id not in loc_map:
                loc_map[p_id] = (float(o.pickup_latitude), float(o.pickup_longitude))
                location_objs.append(LocationIdentifier(id=p_id, latitude=loc_map[p_id][0], longitude=loc_map[p_id][1]))
            if d_id not in loc_map:
                loc_map[d_id] = (float(o.delivery_latitude), float(o.delivery_longitude))
                location_objs.append(LocationIdentifier(id=d_id, latitude=loc_map[d_id][0], longitude=loc_map[d_id][1]))

        # Register rider locations
        for r in riders:
            r_id = f"R_{r.id}"
            if r_id not in loc_map:
                loc_map[r_id] = (float(r.current_latitude), float(r.current_longitude))
                location_objs.append(LocationIdentifier(id=r_id, latitude=loc_map[r_id][0], longitude=loc_map[r_id][1]))

        cost_cache: Dict[Tuple[str, str], Tuple[float, float]] = {}

        try:
            # Query OSMService pairwise matrix
            matrix_res = OSMService.compute_matrix(location_objs, weight="travel_time")
            id_list = matrix_res.location_ids
            for i, src_id in enumerate(id_list):
                for j, tgt_id in enumerate(id_list):
                    d_m = matrix_res.distance_matrix_meters[i][j]
                    t_s = matrix_res.duration_matrix_seconds[i][j]
                    if d_m is not None and t_s is not None:
                        cost_cache[(src_id, tgt_id)] = (d_m, t_s)
                    else:
                        # Fallback for unreachable / disconnected components: Euclidean approx
                        p1 = loc_map[src_id]
                        p2 = loc_map[tgt_id]
                        approx_km = (((p1[0] - p2[0]) * 111.0) ** 2 + ((p1[1] - p2[1]) * 105.0) ** 2) ** 0.5
                        approx_m = approx_km * 1000.0
                        approx_s = (approx_m / (25.0 * 1000 / 3600)) + 600.0  # penalize disconnected
                        cost_cache[(src_id, tgt_id)] = (approx_m, approx_s)
        except Exception as e:
            logger.warning("OSMService matrix precomputation failed (%s). Using fallback Euclidean estimations.", e)
            for src_id, p1 in loc_map.items():
                for tgt_id, p2 in loc_map.items():
                    if src_id == tgt_id:
                        cost_cache[(src_id, tgt_id)] = (0.0, 0.0)
                    else:
                        approx_km = (((p1[0] - p2[0]) * 111.0) ** 2 + ((p1[1] - p2[1]) * 105.0) ** 2) ** 0.5
                        approx_m = approx_km * 1000.0
                        approx_s = (approx_m / (25.0 * 1000 / 3600))
                        cost_cache[(src_id, tgt_id)] = (approx_m, approx_s)

        return cost_cache

    @classmethod
    def evaluate_batch_tour(
        cls,
        batch_orders: List[Any],
        rider: Any,
        cost_matrix: Dict[Tuple[str, str], Tuple[float, float]],
        reference_time: datetime,
        service_time_sec: float = 180.0,
    ) -> Tuple[float, float, List[StopPreview], bool, float]:
        """Fast deterministic preliminary route estimator for a batch.

        Enforces precedence (pickup before delivery) and capacity constraints.
        Returns: (distance_m, duration_s, stops, all_deadlines_met, total_lateness_min).
        NOTE: Exact tour sequencing will be refined by Ant Colony Optimization (ACO) in Milestone 4.
        """
        rider_loc_id = f"R_{rider.id}"

        # Build candidate stops: Pickups can be visited immediately; Deliveries unlocked after pickup
        pending_pickups = {o.id: o for o in batch_orders}
        unlocked_deliveries: Dict[str, Any] = {}

        current_loc_id = rider_loc_id
        current_time_offset = 0.0
        total_dist_m = 0.0

        ordered_stops: List[StopPreview] = []
        all_deadlines_met = True
        total_lateness_min = 0.0

        stop_counter = 1
        num_expected_stops = len(batch_orders) * 2

        while len(ordered_stops) < num_expected_stops:
            best_candidate_id = None
            best_dist = float("inf")
            best_time = float("inf")
            best_type = ""
            best_order = None

            # 1. Evaluate candidate pickups
            for o_id, order in pending_pickups.items():
                target_loc = f"P_{o_id}"
                d_m, t_s = cost_matrix.get((current_loc_id, target_loc), (1000.0, 150.0))
                if t_s < best_time:
                    best_time = t_s
                    best_dist = d_m
                    best_candidate_id = target_loc
                    best_type = "PICKUP"
                    best_order = order

            # 2. Evaluate candidate unlocked deliveries
            for o_id, order in unlocked_deliveries.items():
                target_loc = f"D_{o_id}"
                d_m, t_s = cost_matrix.get((current_loc_id, target_loc), (1000.0, 150.0))
                if t_s < best_time:
                    best_time = t_s
                    best_dist = d_m
                    best_candidate_id = target_loc
                    best_type = "DELIVERY"
                    best_order = order

            if best_candidate_id is None or best_order is None:
                break

            # Advance state along best candidate stop
            total_dist_m += best_dist
            current_time_offset += best_time + service_time_sec
            current_loc_id = best_candidate_id

            arrival_time = reference_time + datetime.timedelta(seconds=current_time_offset) if hasattr(datetime, "timedelta") else reference_time
            # Python datetime.timedelta import safety
            from datetime import timedelta
            arrival_time = reference_time + timedelta(seconds=current_time_offset)

            deadline = getattr(best_order, "delivery_deadline", None)
            if isinstance(deadline, str):
                deadline = datetime.fromisoformat(deadline)
            if deadline and deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            is_on_time = True
            if best_type == "DELIVERY" and deadline:
                if arrival_time > deadline:
                    is_on_time = False
                    all_deadlines_met = False
                    diff_sec = (arrival_time - deadline).total_seconds()
                    total_lateness_min += max(0.0, diff_sec / 60.0)

            lat = float(best_order.pickup_latitude if best_type == "PICKUP" else best_order.delivery_latitude)
            lon = float(best_order.pickup_longitude if best_type == "PICKUP" else best_order.delivery_longitude)

            ordered_stops.append(
                StopPreview(
                    stop_index=stop_counter,
                    stop_type=best_type,
                    order_id=best_order.id,
                    latitude=lat,
                    longitude=lon,
                    estimated_arrival_offset_seconds=round(current_time_offset, 1),
                    estimated_arrival_time=arrival_time,
                    deadline=deadline if best_type == "DELIVERY" else None,
                    is_on_time=is_on_time,
                )
            )
            stop_counter += 1

            if best_type == "PICKUP":
                del pending_pickups[best_order.id]
                unlocked_deliveries[best_order.id] = best_order
            else:
                del unlocked_deliveries[best_order.id]

        return total_dist_m, current_time_offset, ordered_stops, all_deadlines_met, total_lateness_min

    @classmethod
    def evaluate_chromosome_cost(
        cls,
        chromosome: List[List[str]],
        order_dict: Dict[str, Any],
        riders: List[Any],
        urgency_map: Dict[str, FuzzyUrgencyResult],
        cost_matrix: Dict[Tuple[str, str], Tuple[float, float]],
        reference_time: datetime,
        service_time_sec: float,
    ) -> Tuple[float, List[BatchResult]]:
        """Calculate the multi-objective cost and batch specifications of a candidate chromosome partition."""
        batch_results: List[BatchResult] = []
        total_time_min = 0.0
        total_dist_km = 0.0
        total_utilization = 0.0
        total_lateness_min = 0.0
        urgency_service_reward = 0.0

        for b_idx, order_ids in enumerate(chromosome):
            b_orders = [order_dict[oid] for oid in order_ids if oid in order_dict]
            if not b_orders:
                continue

            # Check capacity & find capable rider
            rider = find_capable_rider(b_orders, riders)
            if not rider:
                # Severe infeasibility penalty
                return 10000.0 + len(b_orders) * 1000.0, []

            # Check mutual package compatibility
            compat, _ = is_batch_compatible(b_orders)
            if not compat:
                return 10000.0 + len(b_orders) * 1000.0, []

            # Evaluate preliminary route
            d_m, t_s, stops, on_time, lateness = cls.evaluate_batch_tour(
                b_orders, rider, cost_matrix, reference_time, service_time_sec
            )

            d_km = d_m / 1000.0
            t_min = t_s / 60.0

            total_dist_km += d_km
            total_time_min += t_min
            total_lateness_min += lateness

            w_sum = sum(float(o.weight_kg) for o in b_orders)
            p_sum = sum(int(o.package_count) for o in b_orders)
            r_w_cap = float(rider.weight_capacity_kg)
            r_p_cap = int(rider.package_count_capacity)

            w_util = (w_sum / r_w_cap) * 100.0 if r_w_cap > 0 else 0.0
            p_util = (p_sum / r_p_cap) * 100.0 if r_p_cap > 0 else 0.0
            total_utilization += (w_util / 100.0)

            # Urgency service quality
            b_urgencies = [urgency_map[o.id].urgency_score for o in b_orders if o.id in urgency_map]
            avg_u = sum(b_urgencies) / len(b_urgencies) if b_urgencies else 50.0

            # Reward fast delivery for high urgency batches
            urgency_service_reward += (avg_u / 100.0) * max(0.0, 1.0 - (t_min / 60.0))

            # All capable available riders for this batch
            capable_all = [
                r for r in riders
                if bool(getattr(r, "is_available", True))
                and float(getattr(r, "weight_capacity_kg", 20.0)) >= w_sum
                and int(getattr(r, "package_count_capacity", 10)) >= p_sum
            ]
            eligible_ids = [r.id for r in capable_all]

            batch_results.append(
                BatchResult(
                    batch_id=f"BATCH-GA-{b_idx + 1:02d}",
                    order_ids=order_ids,
                    designated_rider_id=rider.id,
                    rider_display_name=rider.display_name,
                    eligible_rider_ids=eligible_ids,
                    total_weight_kg=round(w_sum, 2),
                    total_packages=p_sum,
                    weight_utilization_pct=round(w_util, 1),
                    package_utilization_pct=round(p_util, 1),
                    estimated_distance_km=round(d_km, 2),
                    estimated_duration_min=round(t_min, 1),
                    stops=stops,
                    deadline_feasible=on_time,
                    lateness_minutes=round(lateness, 1),
                    average_urgency=round(avg_u, 1),
                    compatibility_verified=True,
                    precedence_verified=True,
                )
            )


        num_batches = len(batch_results)
        avg_util = total_utilization / num_batches if num_batches > 0 else 0.0

        # Multi-objective cost formula
        # Weights: Time (1.0/min), Distance (0.5/km), Batch consolidation (15.0/batch),
        # Capacity utilization (-10.0), Urgency service (-5.0), Lateness penalty (+50.0/min)
        cost = (
            1.0 * total_time_min
            + 0.5 * total_dist_km
            + 15.0 * num_batches
            - 10.0 * avg_util
            - 5.0 * urgency_service_reward
            + 50.0 * total_lateness_min
        )

        return cost, batch_results

    @classmethod
    def repair_chromosome(
        cls,
        chromosome: List[List[str]],
        order_dict: Dict[str, Any],
        riders: List[Any],
    ) -> List[List[str]]:
        """Repair invalid partitions: eliminate duplicates, restore missing orders, and split violating batches."""
        seen: Set[str] = set()
        cleaned_batches: List[List[str]] = []

        # 1. Clean duplicates & empty batches
        for batch in chromosome:
            valid_in_batch = []
            for oid in batch:
                if oid in order_dict and oid not in seen:
                    seen.add(oid)
                    valid_in_batch.append(oid)
            if valid_in_batch:
                cleaned_batches.append(valid_in_batch)

        # 2. Restore any missing orders as singletons
        for oid in order_dict.keys():
            if oid not in seen:
                cleaned_batches.append([oid])
                seen.add(oid)

        # 3. Check hard constraints per batch; split any violating batch
        repaired_batches: List[List[str]] = []
        for batch in cleaned_batches:
            b_orders = [order_dict[oid] for oid in batch]
            rider = find_capable_rider(b_orders, riders)
            compat, _ = is_batch_compatible(b_orders)

            if rider is not None and compat:
                repaired_batches.append(batch)
            else:
                # Violating batch: split into valid singletons
                for oid in batch:
                    repaired_batches.append([oid])

        return repaired_batches

    @classmethod
    def crossover(
        cls,
        parent_a: List[List[str]],
        parent_b: List[List[str]],
        order_dict: Dict[str, Any],
        riders: List[Any],
    ) -> List[List[str]]:
        """Set-based partition crossover: inherits subsets of batches from parents."""
        child_batches: List[List[str]] = []
        assigned_orders: Set[str] = set()

        # Randomly inherit a portion of batches from parent A
        for batch in parent_a:
            if random.random() < 0.5 and not any(oid in assigned_orders for oid in batch):
                child_batches.append(copy.deepcopy(batch))
                assigned_orders.update(batch)

        # Inherit remaining unassigned orders from parent B batches
        for batch in parent_b:
            remaining = [oid for oid in batch if oid not in assigned_orders]
            if remaining:
                child_batches.append(remaining)
                assigned_orders.update(remaining)

        # Ensure all orders are present and valid
        return cls.repair_chromosome(child_batches, order_dict, riders)

    @classmethod
    def mutate(
        cls,
        chromosome: List[List[str]],
        order_dict: Dict[str, Any],
        riders: List[Any],
        mutation_rate: float,
    ) -> List[List[str]]:
        """Apply random partition mutations: Move, Merge, Split, or Swap."""
        if random.random() > mutation_rate or not chromosome:
            return chromosome

        new_chrom = copy.deepcopy(chromosome)
        op = random.choice(["MOVE", "MERGE", "SPLIT", "SWAP"])

        if op == "MOVE" and len(new_chrom) > 1:
            # Pick an order from a random batch and move to another
            src_idx = random.randrange(len(new_chrom))
            if len(new_chrom[src_idx]) > 1:
                dest_idx = random.randrange(len(new_chrom))
                if src_idx != dest_idx:
                    oid = new_chrom[src_idx].pop(random.randrange(len(new_chrom[src_idx])))
                    new_chrom[dest_idx].append(oid)

        elif op == "MERGE" and len(new_chrom) >= 2:
            # Try to merge two small batches
            i, j = random.sample(range(len(new_chrom)), 2)
            merged = new_chrom[i] + new_chrom[j]
            b_orders = [order_dict[oid] for oid in merged]
            if find_capable_rider(b_orders, riders) and is_batch_compatible(b_orders)[0]:
                new_chrom = [b for idx, b in enumerate(new_chrom) if idx not in (i, j)]
                new_chrom.append(merged)

        elif op == "SPLIT":
            # Split a multi-order batch
            multi_batches = [idx for idx, b in enumerate(new_chrom) if len(b) >= 2]
            if multi_batches:
                idx = random.choice(multi_batches)
                b = new_chrom[idx]
                cut = len(b) // 2
                new_chrom[idx] = b[:cut]
                new_chrom.append(b[cut:])

        elif op == "SWAP" and len(new_chrom) >= 2:
            # Swap an order between two batches
            i, j = random.sample(range(len(new_chrom)), 2)
            if new_chrom[i] and new_chrom[j]:
                idx_i = random.randrange(len(new_chrom[i]))
                idx_j = random.randrange(len(new_chrom[j]))
                new_chrom[i][idx_i], new_chrom[j][idx_j] = new_chrom[j][idx_j], new_chrom[i][idx_i]

        return cls.repair_chromosome(new_chrom, order_dict, riders)

    @classmethod
    def run_independent_orders_baseline(
        cls,
        feasible_orders: List[Any],
        riders: List[Any],
        cost_matrix: Dict[Tuple[str, str], Tuple[float, float]],
        reference_time: datetime,
        service_time_sec: float,
    ) -> BaselineSummary:
        """Baseline 1: Exactly 1 batch per order (independent solo deliveries)."""
        total_d_km = 0.0
        total_t_min = 0.0
        on_time_count = 0
        util_sum = 0.0

        for o in feasible_orders:
            rider = find_capable_rider([o], riders)
            if rider:
                d_m, t_s, _, on_time, _ = cls.evaluate_batch_tour(
                    [o], rider, cost_matrix, reference_time, service_time_sec
                )
                total_d_km += d_m / 1000.0
                total_t_min += t_s / 60.0
                if on_time:
                    on_time_count += 1
                util_sum += (float(o.weight_kg) / float(rider.weight_capacity_kg)) * 100.0

        n = len(feasible_orders)
        return BaselineSummary(
            name="Independent Orders (Solo Deliveries)",
            total_batches=n,
            total_distance_km=round(total_d_km, 2),
            total_duration_min=round(total_t_min, 1),
            deadline_feasible_orders_count=on_time_count,
            total_orders_assigned=n,
            unassignable_orders_count=0,
            average_capacity_utilization_pct=round(util_sum / n, 1) if n > 0 else 0.0,
        )

    @classmethod
    def run_greedy_batching_baseline(
        cls,
        feasible_orders: List[Any],
        riders: List[Any],
        urgency_map: Dict[str, FuzzyUrgencyResult],
        cost_matrix: Dict[Tuple[str, str], Tuple[float, float]],
        reference_time: datetime,
        service_time_sec: float,
    ) -> BaselineSummary:
        """Baseline 2: Deterministic Greedy Urgency Batching Heuristic.

        Sorts orders by urgency descending. Greedily inserts into existing batches if feasible,
        otherwise allocates a new batch.
        """
        # Sort by urgency descending (handle critical first)
        sorted_orders = sorted(
            feasible_orders,
            key=lambda o: urgency_map.get(o.id, FuzzyUrgencyResult(
                order_id=o.id, urgency_score=50.0, urgency_category="MEDIUM",
                solo_travel_time_seconds=600.0, deadline_slack_minutes=60.0,
                waiting_time_minutes=0.0, priority_score=0.5
            )).urgency_score,
            reverse=True,
        )

        batches: List[List[Any]] = []

        for o in sorted_orders:
            inserted = False
            # Try to insert into best existing batch
            for b in batches:
                cand = b + [o]
                # Check rider capacity and compatibility
                rider = find_capable_rider(cand, riders)
                compat, _ = is_batch_compatible(cand)
                if rider and compat:
                    # Check tour feasibility
                    _, _, _, on_time, _ = cls.evaluate_batch_tour(
                        cand, rider, cost_matrix, reference_time, service_time_sec
                    )
                    if on_time:
                        b.append(o)
                        inserted = True
                        break

            if not inserted:
                # Create a new batch
                batches.append([o])

        # Evaluate greedy batches
        total_d_km = 0.0
        total_t_min = 0.0
        on_time_orders = 0
        util_sum = 0.0

        for b in batches:
            rider = find_capable_rider(b, riders)
            if rider:
                d_m, t_s, stops, _, _ = cls.evaluate_batch_tour(
                    b, rider, cost_matrix, reference_time, service_time_sec
                )
                total_d_km += d_m / 1000.0
                total_t_min += t_s / 60.0
                w_sum = sum(float(o.weight_kg) for o in b)
                util_sum += (w_sum / float(rider.weight_capacity_kg)) * 100.0
                for s in stops:
                    if s.stop_type == "DELIVERY" and s.is_on_time:
                        on_time_orders += 1

        n_batches = len(batches)
        return BaselineSummary(
            name="Deterministic Greedy Urgency Batching",
            total_batches=n_batches,
            total_distance_km=round(total_d_km, 2),
            total_duration_min=round(total_t_min, 1),
            deadline_feasible_orders_count=on_time_orders,
            total_orders_assigned=len(feasible_orders),
            unassignable_orders_count=0,
            average_capacity_utilization_pct=round(util_sum / n_batches, 1) if n_batches > 0 else 0.0,
        )

    @classmethod
    def optimize_batches(
        cls,
        orders: List[Any],
        riders: List[Any],
        reference_time: Optional[datetime] = None,
        config: Optional[GAConfig] = None,
    ) -> BaselineComparisonResult:
        """Execute Genetic Algorithm delivery batching and compare against standard baselines."""
        start_time = time.perf_counter()
        cfg = config or GAConfig()

        if cfg.random_seed is not None:
            random.seed(cfg.random_seed)

        now = reference_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 1. Check for available riders
        available_riders = [r for r in riders if bool(getattr(r, "is_available", True))]
        if not available_riders:
            raise ValueError("No available fleet riders found for batch allocation.")

        # 2. Filter unassignable orders (capacity or physically unreachable)
        max_rider_weight = max(float(r.weight_capacity_kg) for r in available_riders)
        max_rider_pkgs = max(int(r.package_count_capacity) for r in available_riders)

        feasible_orders: List[Any] = []
        unassignable_orders: List[UnassignableOrderResult] = []

        for o in orders:
            w = float(getattr(o, "weight_kg", 1.0))
            p = int(getattr(o, "package_count", 1))

            if w > max_rider_weight:
                unassignable_orders.append(
                    UnassignableOrderResult(
                        order_id=o.id,
                        reason=f"Order weight ({w}kg) exceeds maximum rider capacity in fleet ({max_rider_weight}kg).",
                    )
                )
            elif p > max_rider_pkgs:
                unassignable_orders.append(
                    UnassignableOrderResult(
                        order_id=o.id,
                        reason=f"Package count ({p}) exceeds maximum rider package capacity ({max_rider_pkgs}).",
                    )
                )
            else:
                feasible_orders.append(o)

        if not feasible_orders:
            # All orders unassignable or empty list
            empty_summary = BaselineSummary(
                name="Empty", total_batches=0, total_distance_km=0.0, total_duration_min=0.0,
                deadline_feasible_orders_count=0, total_orders_assigned=0, unassignable_orders_count=len(unassignable_orders),
                average_capacity_utilization_pct=0.0
            )
            empty_ga = GASolutionResult(
                batches=[], total_batches=0, total_distance_km=0.0, total_duration_min=0.0,
                all_deadlines_met=True, average_urgency_score=0.0, average_capacity_utilization_pct=0.0,
                fitness_history=[], execution_time_ms=0.0, algorithm_metadata={}
            )
            return BaselineComparisonResult(
                ga_solution=empty_ga,
                independent_baseline=empty_summary,
                greedy_baseline=empty_summary,
                unassignable_orders=unassignable_orders,
                preview_mode=True,
            )

        # 3. Calculate Fuzzy Urgency Scores for all feasible orders
        urgency_map: Dict[str, FuzzyUrgencyResult] = {}
        for o in feasible_orders:
            urgency_map[o.id] = FuzzyUrgencyEngine.score_order(
                o, reference_time=now, service_time_seconds=cfg.service_time_seconds
            )

        # 4. Precompute road-network travel cost matrix
        cost_matrix = cls.build_cost_matrix(feasible_orders, available_riders)
        order_dict = {o.id: o for o in feasible_orders}
        order_ids = list(order_dict.keys())

        # 5. Initialize GA Population
        population: List[List[List[str]]] = []

        # Individual 0: Independent singleton batches
        indiv_singletons = [[oid] for oid in order_ids]
        population.append(indiv_singletons)

        # Individual 1: Heuristic clustering by merchant / proximity
        merchant_clusters: Dict[str, List[str]] = {}
        for o in feasible_orders:
            m_id = str(getattr(o, "merchant_id", "default"))
            merchant_clusters.setdefault(m_id, []).append(o.id)
        indiv_merchant = list(merchant_clusters.values())
        population.append(cls.repair_chromosome(indiv_merchant, order_dict, available_riders))

        # Remaining individuals: random partitions
        while len(population) < cfg.population_size:
            shuffled = copy.deepcopy(order_ids)
            random.shuffle(shuffled)
            rand_batches: List[List[str]] = []
            curr_b: List[str] = []
            for oid in shuffled:
                curr_b.append(oid)
                # Randomly end batch with probability 0.4
                if random.random() < 0.40:
                    rand_batches.append(curr_b)
                    curr_b = []
            if curr_b:
                rand_batches.append(curr_b)
            population.append(cls.repair_chromosome(rand_batches, order_dict, available_riders))

        # 6. Evolutionary Optimization Loop
        fitness_history: List[Dict[str, Any]] = []
        best_overall_cost = float("inf")
        best_overall_batches: List[BatchResult] = []
        best_overall_chrom: List[List[str]] = []

        for gen in range(cfg.generations):
            # Evaluate all individuals
            evaluations = []
            for chrom in population:
                c_cost, b_res = cls.evaluate_chromosome_cost(
                    chrom, order_dict, available_riders, urgency_map, cost_matrix, now, cfg.service_time_seconds
                )
                fitness = 1000.0 / (1.0 + max(0.0, c_cost))
                evaluations.append((fitness, c_cost, chrom, b_res))

            # Sort descending by fitness (lowest cost first)
            evaluations.sort(key=lambda x: x[0], reverse=True)

            gen_best_f, gen_best_c, gen_best_chrom, gen_best_batches = evaluations[0]
            gen_avg_f = sum(e[0] for e in evaluations) / len(evaluations)

            fitness_history.append({
                "generation": gen + 1,
                "best_fitness": round(gen_best_f, 4),
                "best_cost": round(gen_best_c, 2),
                "avg_fitness": round(gen_avg_f, 4),
                "batches_count": len(gen_best_chrom),
            })

            if gen_best_c < best_overall_cost:
                best_overall_cost = gen_best_c
                best_overall_batches = gen_best_batches
                best_overall_chrom = gen_best_chrom

            # Elitism: preserve top E individuals
            new_pop: List[List[List[str]]] = [
                copy.deepcopy(evaluations[i][2]) for i in range(min(cfg.elitism_count, len(evaluations)))
            ]

            # Reproduction: Selection, Crossover, Mutation
            while len(new_pop) < cfg.population_size:
                # Tournament Selection
                t1 = random.sample(evaluations, min(cfg.tournament_size, len(evaluations)))
                parent_a = max(t1, key=lambda x: x[0])[2]

                t2 = random.sample(evaluations, min(cfg.tournament_size, len(evaluations)))
                parent_b = max(t2, key=lambda x: x[0])[2]

                # Crossover
                if random.random() < cfg.crossover_rate:
                    child = cls.crossover(parent_a, parent_b, order_dict, available_riders)
                else:
                    child = copy.deepcopy(parent_a)

                # Mutation
                child = cls.mutate(child, order_dict, available_riders, cfg.mutation_rate)
                new_pop.append(child)

            population = new_pop

        # 7. Final Independent Validation of Best Batches
        # Ensure every order is present exactly once and all constraints strictly hold
        assigned_check = set()
        for b in best_overall_batches:
            for oid in b.order_ids:
                if oid in assigned_check:
                    logger.error("FATAL: Duplicate order ID in final GA solution: %s", oid)
                assigned_check.add(oid)

        missing = set(order_ids) - assigned_check
        if missing:
            logger.error("FATAL: Missing order IDs in final GA solution: %s", missing)

        total_ga_dist = sum(b.estimated_distance_km for b in best_overall_batches)
        total_ga_time = sum(b.estimated_duration_min for b in best_overall_batches)
        all_met = all(b.deadline_feasible for b in best_overall_batches)
        avg_u_ga = sum(b.average_urgency for b in best_overall_batches) / len(best_overall_batches) if best_overall_batches else 0.0
        avg_cap_ga = sum(b.weight_utilization_pct for b in best_overall_batches) / len(best_overall_batches) if best_overall_batches else 0.0

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        ga_sol = GASolutionResult(
            batches=best_overall_batches,
            total_batches=len(best_overall_batches),
            total_distance_km=round(total_ga_dist, 2),
            total_duration_min=round(total_ga_time, 1),
            all_deadlines_met=all_met,
            average_urgency_score=round(avg_u_ga, 1),
            average_capacity_utilization_pct=round(avg_cap_ga, 1),
            fitness_history=fitness_history,
            execution_time_ms=round(elapsed_ms, 2),
            algorithm_metadata={
                "population_size": cfg.population_size,
                "generations": cfg.generations,
                "mutation_rate": cfg.mutation_rate,
                "crossover_rate": cfg.crossover_rate,
                "random_seed": cfg.random_seed,
                "router_note": "Route costs are preliminary estimates based on greedy precedence insertion; exact tour sequencing will be refined by ACO in Milestone 4.",
            },
        )

        # 8. Compute Baselines under identical conditions
        indiv_base = cls.run_independent_orders_baseline(
            feasible_orders, available_riders, cost_matrix, now, cfg.service_time_seconds
        )
        greedy_base = cls.run_greedy_batching_baseline(
            feasible_orders, available_riders, urgency_map, cost_matrix, now, cfg.service_time_seconds
        )

        return BaselineComparisonResult(
            ga_solution=ga_sol,
            independent_baseline=indiv_base,
            greedy_baseline=greedy_base,
            unassignable_orders=unassignable_orders,
            preview_mode=True,
        )
