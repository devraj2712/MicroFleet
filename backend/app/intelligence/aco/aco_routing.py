import copy
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from backend.app.intelligence.ga.ga_batching import (
    BatchResult,
    GABatchingEngine,
    GAConfig,
)
from backend.app.intelligence.osm.osm_service import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_TRAFFIC_NOTE,
    LocationIdentifier,
    OSMService,
)

logger = logging.getLogger(__name__)


class ACOConfig(BaseModel):
    """Hyperparameters for Ant Colony Optimization pickup-and-delivery routing."""
    num_ants: int = Field(default=10, ge=2, le=50, description="Number of ants per iteration")
    max_iterations: int = Field(default=15, ge=2, le=100, description="Maximum iterations of pheromone update")
    alpha: float = Field(default=1.0, ge=0.0, le=5.0, description="Pheromone influence factor")
    beta: float = Field(default=2.0, ge=0.0, le=10.0, description="Heuristic desirability influence factor")
    evaporation_rate: float = Field(default=0.15, ge=0.01, le=0.90, description="Pheromone evaporation rate")
    q_deposit: float = Field(default=100.0, ge=1.0, le=1000.0, description="Pheromone deposit coefficient")
    random_seed: Optional[int] = Field(None, description="Random seed for reproducible route exploration")
    service_time_seconds: float = Field(default=180.0, ge=0.0, le=1800.0, description="Service time allowance per stop")
    max_candidate_riders: int = Field(default=5, ge=1, le=10, description="Upper bound on candidate riders evaluated per batch")


class RouteEvent(BaseModel):
    """Discrete pickup, delivery, or origin waypoint in a delivery route."""
    event_id: str
    order_id: Optional[str] = None
    event_type: str  # "ORIGIN", "PICKUP", "DELIVERY"
    latitude: float
    longitude: float
    service_time_seconds: float = 0.0
    deadline: Optional[datetime] = None
    demand_weight_kg: float = 0.0
    demand_package_count: int = 0


class RouteStop(BaseModel):
    """Ordered stop in an evaluated candidate delivery route."""
    stop_index: int
    event_id: str
    order_id: Optional[str] = None
    event_type: str
    latitude: float
    longitude: float
    arrival_time: datetime
    arrival_offset_seconds: float
    departure_offset_seconds: float
    deadline: Optional[datetime] = None
    deadline_slack_seconds: Optional[float] = None
    is_on_time: bool = True
    onboard_weight_kg: float
    onboard_packages: int


class RiderRouteOption(BaseModel):
    """Evaluated candidate route for a specific rider-batch pairing."""
    rider_id: str
    rider_display_name: str
    stops: List[RouteStop]
    distance_meters: float
    distance_km: float
    duration_seconds: float
    duration_minutes: float
    peak_weight_kg: float
    peak_packages: int
    peak_weight_utilization_pct: float
    peak_package_utilization_pct: float
    all_deadlines_met: bool
    is_feasible: bool
    infeasibility_reasons: List[str] = Field(default_factory=list)
    aco_execution_time_ms: float
    baseline_comparison: Dict[str, Any] = Field(
        default_factory=dict,
        description="Side-by-side metrics against the deterministic greedy routing baseline",
    )


class BatchRouteResult(BaseModel):
    """ACO route options generated for a candidate batch across eligible fleet riders."""
    batch_id: str
    order_ids: List[str]
    eligible_rider_ids: List[str]
    route_candidates: List[RiderRouteOption]
    best_feasible_candidate: Optional[RiderRouteOption] = None
    is_routeable: bool
    unrouteable_reason: Optional[str] = None


class RoutesPreviewResult(BaseModel):
    """Complete preview response for ACO route optimization across all batches."""
    batches: List[BatchRouteResult]
    summary: Dict[str, Any]
    preview_mode: bool = True
    attribution: str = DEFAULT_ATTRIBUTION
    traffic_note: str = DEFAULT_TRAFFIC_NOTE


def validate_route(
    stops: List[RouteStop],
    orders: List[Any],
    rider: Any,
) -> Tuple[bool, List[str]]:
    """Independent validator checking precedence, capacity throughout route, and delivery deadlines."""
    reasons: List[str] = []
    num_orders = len(orders)
    expected_stops = 1 + (num_orders * 2)  # 1 origin + pickups + deliveries

    if len(stops) != expected_stops:
        reasons.append(f"Incomplete route: contains {len(stops)} stops, expected {expected_stops}.")
        return False, reasons

    # 1. Origin stop verification
    if stops[0].event_type != "ORIGIN":
        reasons.append(f"First stop must be ORIGIN, found '{stops[0].event_type}'.")

    # 2. Precedence verification: pickup must strictly precede delivery for each order
    pickup_indices: Dict[str, int] = {}
    delivery_indices: Dict[str, int] = {}

    for s in stops:
        if s.event_type == "PICKUP" and s.order_id:
            if s.order_id in pickup_indices:
                reasons.append(f"Duplicate pickup event for order {s.order_id}.")
            pickup_indices[s.order_id] = s.stop_index
        elif s.event_type == "DELIVERY" and s.order_id:
            if s.order_id in delivery_indices:
                reasons.append(f"Duplicate delivery event for order {s.order_id}.")
            delivery_indices[s.order_id] = s.stop_index

    for o in orders:
        o_id = str(getattr(o, "id", None) or o.get("id"))
        if o_id not in pickup_indices:
            reasons.append(f"Missing pickup stop for order {o_id}.")
        if o_id not in delivery_indices:
            reasons.append(f"Missing delivery stop for order {o_id}.")
        if o_id in pickup_indices and o_id in delivery_indices:
            if pickup_indices[o_id] >= delivery_indices[o_id]:
                reasons.append(
                    f"Precedence violation for order {o_id}: pickup (stop {pickup_indices[o_id]}) "
                    f"must occur before delivery (stop {delivery_indices[o_id]})."
                )

    # 3. Capacity throughout route verification
    r_w_cap = float(getattr(rider, "weight_capacity_kg", 20.0))
    r_p_cap = int(getattr(rider, "package_count_capacity", 10))

    for s in stops:
        if s.onboard_weight_kg > r_w_cap + 1e-4:
            reasons.append(
                f"Weight capacity exceeded at stop {s.stop_index} ({s.event_type} {s.order_id}): "
                f"onboard={s.onboard_weight_kg:.2f}kg > capacity={r_w_cap:.2f}kg."
            )
        if s.onboard_packages > r_p_cap:
            reasons.append(
                f"Package count capacity exceeded at stop {s.stop_index}: "
                f"onboard={s.onboard_packages} > capacity={r_p_cap}."
            )

    # Final stop must have 0 onboard load
    if stops[-1].onboard_weight_kg > 1e-4 or stops[-1].onboard_packages != 0:
        reasons.append(
            f"Non-zero load at final delivery: {stops[-1].onboard_weight_kg:.2f}kg, "
            f"{stops[-1].onboard_packages} packages remaining."
        )

    # 4. Delivery deadline verification
    for s in stops:
        if s.event_type == "DELIVERY" and s.deadline is not None:
            if s.arrival_time > s.deadline:
                reasons.append(
                    f"Deadline violation at stop {s.stop_index} (order {s.order_id}): "
                    f"arrival={s.arrival_time.isoformat()} > deadline={s.deadline.isoformat()}."
                )

    return (len(reasons) == 0), reasons


def evaluate_route_stops(
    ordered_events: List[RouteEvent],
    cost_matrix: Dict[Tuple[str, str], Tuple[float, float]],
    reference_time: datetime,
) -> Tuple[List[RouteStop], float, float, float, int]:
    """Calculate arrival times, onboard loads, distance and duration along an ordered event sequence."""
    stops: List[RouteStop] = []
    curr_offset = 0.0
    total_dist_m = 0.0
    curr_weight = 0.0
    curr_pkgs = 0
    peak_weight = 0.0
    peak_pkgs = 0

    for idx, ev in enumerate(ordered_events):
        if idx == 0:
            # Origin stop
            arr_time = reference_time
            dep_offset = 0.0
            stops.append(
                RouteStop(
                    stop_index=0,
                    event_id=ev.event_id,
                    order_id=None,
                    event_type="ORIGIN",
                    latitude=ev.latitude,
                    longitude=ev.longitude,
                    arrival_time=arr_time,
                    arrival_offset_seconds=0.0,
                    departure_offset_seconds=0.0,
                    deadline=None,
                    deadline_slack_seconds=None,
                    is_on_time=True,
                    onboard_weight_kg=0.0,
                    onboard_packages=0,
                )
            )
            continue

        prev_ev = ordered_events[idx - 1]
        pair_key = (prev_ev.event_id, ev.event_id)
        d_m, t_s = cost_matrix.get(pair_key, (1000.0, 150.0))

        total_dist_m += d_m
        curr_offset += t_s
        arr_time = reference_time + timedelta(seconds=curr_offset)
        dep_offset = curr_offset + ev.service_time_seconds
        curr_offset = dep_offset

        # Update onboard load
        curr_weight = max(0.0, round(curr_weight + ev.demand_weight_kg, 4))
        curr_pkgs = max(0, curr_pkgs + ev.demand_package_count)
        peak_weight = max(peak_weight, curr_weight)
        peak_pkgs = max(peak_pkgs, curr_pkgs)

        is_on_time = True
        slack_sec = None
        if ev.event_type == "DELIVERY" and ev.deadline:
            slack_sec = (ev.deadline - arr_time).total_seconds()
            if slack_sec < 0:
                is_on_time = False

        stops.append(
            RouteStop(
                stop_index=idx,
                event_id=ev.event_id,
                order_id=ev.order_id,
                event_type=ev.event_type,
                latitude=ev.latitude,
                longitude=ev.longitude,
                arrival_time=arr_time,
                arrival_offset_seconds=round(curr_offset - ev.service_time_seconds, 1),
                departure_offset_seconds=round(dep_offset, 1),
                deadline=ev.deadline,
                deadline_slack_seconds=round(slack_sec, 1) if slack_sec is not None else None,
                is_on_time=is_on_time,
                onboard_weight_kg=round(curr_weight, 2),
                onboard_packages=curr_pkgs,
            )
        )

    total_duration_sec = curr_offset
    return stops, total_dist_m, total_duration_sec, peak_weight, peak_pkgs


def build_route_events(orders: List[Any], rider: Any, service_time_sec: float) -> Tuple[RouteEvent, List[RouteEvent]]:
    """Construct distinct origin, pickup, and delivery events for a rider-batch pair."""
    r_lat = float(getattr(rider, "current_latitude", 0.0))
    r_lon = float(getattr(rider, "current_longitude", 0.0))

    origin_ev = RouteEvent(
        event_id=f"R_{rider.id}",
        order_id=None,
        event_type="ORIGIN",
        latitude=r_lat,
        longitude=r_lon,
        service_time_seconds=0.0,
        demand_weight_kg=0.0,
        demand_package_count=0,
    )

    task_events: List[RouteEvent] = []
    for o in orders:
        o_id = str(getattr(o, "id", None) or o.get("id"))
        p_lat = float(getattr(o, "pickup_latitude", None) or o.get("pickup_latitude"))
        p_lon = float(getattr(o, "pickup_longitude", None) or o.get("pickup_longitude"))
        d_lat = float(getattr(o, "delivery_latitude", None) or o.get("delivery_latitude"))
        d_lon = float(getattr(o, "delivery_longitude", None) or o.get("delivery_longitude"))
        w = float(getattr(o, "weight_kg", None) or o.get("weight_kg", 1.0))
        pkgs = int(getattr(o, "package_count", None) or o.get("package_count", 1))

        dl = getattr(o, "delivery_deadline", None) or o.get("delivery_deadline")
        if isinstance(dl, str):
            dl = datetime.fromisoformat(dl)
        if dl and dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)

        # Pickup Event: increases onboard load
        task_events.append(
            RouteEvent(
                event_id=f"P_{o_id}",
                order_id=o_id,
                event_type="PICKUP",
                latitude=p_lat,
                longitude=p_lon,
                service_time_seconds=service_time_sec,
                deadline=None,
                demand_weight_kg=w,
                demand_package_count=pkgs,
            )
        )

        # Delivery Event: decreases onboard load, checks deadline
        task_events.append(
            RouteEvent(
                event_id=f"D_{o_id}",
                order_id=o_id,
                event_type="DELIVERY",
                latitude=d_lat,
                longitude=d_lon,
                service_time_seconds=service_time_sec,
                deadline=dl,
                demand_weight_kg=-w,
                demand_package_count=-pkgs,
            )
        )

    return origin_ev, task_events


def run_greedy_baseline_route(
    origin_ev: RouteEvent,
    task_events: List[RouteEvent],
    orders: List[Any],
    rider: Any,
    cost_matrix: Dict[Tuple[str, str], Tuple[float, float]],
    reference_time: datetime,
) -> Tuple[List[RouteStop], float, float, bool, List[str]]:
    """Deterministic, constraint-aware greedy baseline route builder."""
    ordered = [origin_ev]
    visited_ids: Set[str] = set()
    picked_orders: Set[str] = set()

    curr_ev = origin_ev
    curr_weight = 0.0
    curr_pkgs = 0
    curr_time_offset = 0.0

    r_w_cap = float(getattr(rider, "weight_capacity_kg", 20.0))
    r_p_cap = int(getattr(rider, "package_count_capacity", 10))

    while len(visited_ids) < len(task_events):
        feasible_candidates: List[RouteEvent] = []

        for ev in task_events:
            if ev.event_id in visited_ids:
                continue

            # Precedence: Delivery requires order to be picked up first
            if ev.event_type == "DELIVERY" and ev.order_id not in picked_orders:
                continue

            # Capacity: Check cumulative weight and package limits
            if curr_weight + ev.demand_weight_kg > r_w_cap + 1e-4:
                continue
            if curr_pkgs + ev.demand_package_count > r_p_cap:
                continue

            feasible_candidates.append(ev)

        if not feasible_candidates:
            break

        # Check deadline feasibility among candidates; prioritize on-time candidates
        on_time_candidates: List[RouteEvent] = []
        for cand in feasible_candidates:
            _, t_s = cost_matrix.get((curr_ev.event_id, cand.event_id), (1000.0, 150.0))
            cand_arr_time = reference_time + timedelta(seconds=curr_time_offset + t_s)
            if cand.event_type != "DELIVERY" or cand.deadline is None or cand_arr_time <= cand.deadline:
                on_time_candidates.append(cand)

        pool = on_time_candidates if on_time_candidates else feasible_candidates

        # Greedily pick stop with minimum road travel time; tie-break by event_id
        best_cand = min(
            pool,
            key=lambda c: (
                cost_matrix.get((curr_ev.event_id, c.event_id), (1000.0, 150.0))[1],
                c.event_id,
            ),
        )

        _, t_s = cost_matrix.get((curr_ev.event_id, best_cand.event_id), (1000.0, 150.0))
        curr_time_offset += t_s + best_cand.service_time_seconds
        curr_weight += best_cand.demand_weight_kg
        curr_pkgs += best_cand.demand_package_count

        visited_ids.add(best_cand.event_id)
        if best_cand.event_type == "PICKUP" and best_cand.order_id:
            picked_orders.add(best_cand.order_id)

        ordered.append(best_cand)
        curr_ev = best_cand

    stops, dist_m, dur_s, _, _ = evaluate_route_stops(ordered, cost_matrix, reference_time)
    is_valid, reasons = validate_route(stops, orders, rider)
    return stops, dist_m, dur_s, is_valid, reasons


class ACORoutingEngine:
    """Ant Colony Optimization engine for vehicle routing with pickup-and-delivery precedence."""

    @classmethod
    def optimize_route_for_rider(
        cls,
        batch_orders: List[Any],
        rider: Any,
        cost_matrix: Dict[Tuple[str, str], Tuple[float, float]],
        reference_time: datetime,
        config: ACOConfig,
    ) -> RiderRouteOption:
        """Execute ACO search to find the optimal pickup-and-delivery tour for a rider-batch pair."""
        start_time = time.perf_counter()
        origin_ev, task_events = build_route_events(batch_orders, rider, config.service_time_seconds)
        all_events = [origin_ev] + task_events
        num_tasks = len(task_events)

        # 1. Run deterministic greedy baseline on identical input
        g_stops, g_dist_m, g_dur_s, g_valid, g_reasons = run_greedy_baseline_route(
            origin_ev, task_events, batch_orders, rider, cost_matrix, reference_time
        )
        g_deadlines = all(s.is_on_time for s in g_stops if s.event_type == "DELIVERY")
        greedy_metrics = {
            "distance_km": round(g_dist_m / 1000.0, 2),
            "duration_min": round(g_dur_s / 60.0, 1),
            "all_deadlines_met": g_deadlines,
            "is_feasible": g_valid,
            "stops_count": len(g_stops),
        }

        # 2. Initialize ACO Pheromone Matrix & Heuristics
        # Events indexed 0 .. 2K
        event_ids = [ev.event_id for ev in all_events]
        event_index = {ev.event_id: idx for idx, ev in enumerate(all_events)}

        tau_0 = 1.0
        pheromone: Dict[Tuple[str, str], float] = {
            (u, v): tau_0 for u in event_ids for v in event_ids if u != v
        }

        # Heuristic desirability: inverse travel time
        heuristic: Dict[Tuple[str, str], float] = {}
        for u in event_ids:
            for v in event_ids:
                if u != v:
                    _, t_s = cost_matrix.get((u, v), (1000.0, 150.0))
                    heuristic[(u, v)] = 100.0 / (t_s + 1.0)

        r_w_cap = float(getattr(rider, "weight_capacity_kg", 20.0))
        r_p_cap = int(getattr(rider, "package_count_capacity", 10))

        # Reproducibility seed
        rng = random.Random(config.random_seed) if config.random_seed is not None else random.Random()

        best_feasible_stops: Optional[List[RouteStop]] = None
        best_feasible_cost = float("inf")
        best_feasible_dist_m = float("inf")
        best_feasible_dur_s = float("inf")
        best_feasible_peak_w = 0.0
        best_feasible_peak_p = 0

        best_effort_stops: Optional[List[RouteStop]] = None
        best_effort_cost = float("inf")
        best_effort_reasons: List[str] = []

        # 3. ACO Evolutionary Iteration Loop
        for iteration in range(config.max_iterations):
            iteration_feasible_routes = []

            for ant_idx in range(config.num_ants):
                # Ant constructs a candidate tour starting at origin
                ant_events: List[RouteEvent] = [origin_ev]
                visited: Set[str] = set()
                picked: Set[str] = set()

                curr_ev = origin_ev
                curr_weight = 0.0
                curr_pkgs = 0
                curr_offset = 0.0

                dead_ended = False

                for step in range(num_tasks):
                    # Determine feasible candidates for next step
                    feasible_next: List[RouteEvent] = []
                    for cand in task_events:
                        if cand.event_id in visited:
                            continue
                        if cand.event_type == "DELIVERY" and cand.order_id not in picked:
                            continue
                        if curr_weight + cand.demand_weight_kg > r_w_cap + 1e-4:
                            continue
                        if curr_pkgs + cand.demand_package_count > r_p_cap:
                            continue
                        feasible_next.append(cand)

                    if not feasible_next:
                        dead_ended = True
                        break

                    # ACO Probabilistic Transition
                    weights: List[float] = []
                    for cand in feasible_next:
                        edge = (curr_ev.event_id, cand.event_id)
                        t_val = pheromone.get(edge, tau_0) ** config.alpha
                        h_val = heuristic.get(edge, 1.0) ** config.beta
                        weights.append(t_val * h_val)

                    total_w = sum(weights)
                    if total_w <= 0.0:
                        chosen = rng.choice(feasible_next)
                    else:
                        norm_probs = [w / total_w for w in weights]
                        # Roulette-wheel sampling
                        rnd = rng.random()
                        cum = 0.0
                        chosen = feasible_next[-1]
                        for c_cand, p in zip(feasible_next, norm_probs):
                            cum += p
                            if rnd <= cum:
                                chosen = c_cand
                                break

                    # Advance state
                    _, t_s = cost_matrix.get((curr_ev.event_id, chosen.event_id), (1000.0, 150.0))
                    curr_offset += t_s + chosen.service_time_seconds
                    curr_weight += chosen.demand_weight_kg
                    curr_pkgs += chosen.demand_package_count

                    visited.add(chosen.event_id)
                    if chosen.event_type == "PICKUP" and chosen.order_id:
                        picked.add(chosen.order_id)

                    ant_events.append(chosen)
                    curr_ev = chosen

                if dead_ended or len(ant_events) != len(all_events):
                    continue

                # Evaluate and validate completed ant route
                stops, dist_m, dur_s, peak_w, peak_p = evaluate_route_stops(
                    ant_events, cost_matrix, reference_time
                )
                is_valid, reasons = validate_route(stops, batch_orders, rider)

                # Objective cost: Duration (min) + 0.5 * Distance (km) + Penalty for late stops
                lateness_min = sum(
                    abs(s.deadline_slack_seconds / 60.0)
                    for s in stops
                    if s.event_type == "DELIVERY" and s.deadline_slack_seconds is not None and s.deadline_slack_seconds < 0
                )
                route_cost = (dur_s / 60.0) + (0.5 * dist_m / 1000.0) + (50.0 * lateness_min)

                if is_valid:
                    iteration_feasible_routes.append((ant_events, route_cost, dist_m, dur_s, stops))
                    if route_cost < best_feasible_cost:
                        best_feasible_cost = route_cost
                        best_feasible_dist_m = dist_m
                        best_feasible_dur_s = dur_s
                        best_feasible_stops = stops
                        best_feasible_peak_w = peak_w
                        best_feasible_peak_p = peak_p
                else:
                    if route_cost < best_effort_cost:
                        best_effort_cost = route_cost
                        best_effort_stops = stops
                        best_effort_reasons = reasons

            # 4. Pheromone Evaporation
            rho = config.evaporation_rate
            for edge in pheromone:
                pheromone[edge] = max(0.01, (1.0 - rho) * pheromone[edge])

            # 5. Pheromone Deposition (Only feasible solutions deposit pheromone)
            for f_events, f_cost, _, _, _ in iteration_feasible_routes:
                deposit = config.q_deposit / max(1.0, f_cost)
                for u_ev, v_ev in zip(f_events[:-1], f_events[1:]):
                    e = (u_ev.event_id, v_ev.event_id)
                    pheromone[e] = min(100.0, pheromone.get(e, tau_0) + deposit)

            # Elitist deposition bonus for overall best feasible route
            if best_feasible_stops is not None and best_feasible_cost < float("inf"):
                e_deposit = (config.q_deposit * 2.0) / max(1.0, best_feasible_cost)
                for u_s, v_s in zip(best_feasible_stops[:-1], best_feasible_stops[1:]):
                    e = (u_s.event_id, v_s.event_id)
                    pheromone[e] = min(100.0, pheromone.get(e, tau_0) + e_deposit)

        # 6. Assemble Final Option
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        if best_feasible_stops is not None:
            final_stops = best_feasible_stops
            final_dist_m = best_feasible_dist_m
            final_dur_s = best_feasible_dur_s
            final_is_feasible = True
            final_reasons: List[str] = []
            final_peak_w = best_feasible_peak_w
            final_peak_p = best_feasible_peak_p
        elif best_effort_stops is not None:
            final_stops = best_effort_stops
            final_dist_m = sum(
                cost_matrix.get((s1.event_id, s2.event_id), (1000.0, 150.0))[0]
                for s1, s2 in zip(best_effort_stops[:-1], best_effort_stops[1:])
            )
            final_dur_s = best_effort_stops[-1].departure_offset_seconds if best_effort_stops else 0.0
            final_is_feasible = False
            final_reasons = best_effort_reasons or ["Could not find route satisfying all deadlines and capacities."]
            final_peak_w = max((s.onboard_weight_kg for s in best_effort_stops), default=0.0)
            final_peak_p = max((s.onboard_packages for s in best_effort_stops), default=0)
        else:
            # Fall back to greedy baseline result
            final_stops = g_stops
            final_dist_m = g_dist_m
            final_dur_s = g_dur_s
            final_is_feasible = g_valid
            final_reasons = g_reasons if not g_valid else []
            final_peak_w = max((s.onboard_weight_kg for s in g_stops), default=0.0)
            final_peak_p = max((s.onboard_packages for s in g_stops), default=0)

        all_deadlines = all(s.is_on_time for s in final_stops if s.event_type == "DELIVERY")
        w_cap = float(getattr(rider, "weight_capacity_kg", 20.0))
        p_cap = int(getattr(rider, "package_count_capacity", 10))

        return RiderRouteOption(
            rider_id=rider.id,
            rider_display_name=getattr(rider, "display_name", rider.id),
            stops=final_stops,
            distance_meters=round(final_dist_m, 1),
            distance_km=round(final_dist_m / 1000.0, 2),
            duration_seconds=round(final_dur_s, 1),
            duration_minutes=round(final_dur_s / 60.0, 1),
            peak_weight_kg=round(final_peak_w, 2),
            peak_packages=final_peak_p,
            peak_weight_utilization_pct=round((final_peak_w / w_cap) * 100.0, 1) if w_cap > 0 else 0.0,
            peak_package_utilization_pct=round((final_peak_p / p_cap) * 100.0, 1) if p_cap > 0 else 0.0,
            all_deadlines_met=all_deadlines,
            is_feasible=final_is_feasible,
            infeasibility_reasons=final_reasons,
            aco_execution_time_ms=round(elapsed_ms, 2),
            baseline_comparison=greedy_metrics,
        )

    @classmethod
    def optimize_batches_routes(
        cls,
        batches: List[BatchResult],
        all_orders: List[Any],
        all_riders: List[Any],
        reference_time: Optional[datetime] = None,
        config: Optional[ACOConfig] = None,
    ) -> RoutesPreviewResult:
        """Evaluate ACO routes and greedy baselines for all GA batches across capable candidate riders."""
        now = reference_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        cfg = config or ACOConfig()
        order_map = {str(getattr(o, "id", None) or o.get("id")): o for o in all_orders}
        rider_map = {str(r.id): r for r in all_riders}

        # Precompute road travel cost matrix for all relevant locations
        cost_matrix = GABatchingEngine.build_cost_matrix(all_orders, all_riders)

        batch_route_results: List[BatchRouteResult] = []
        total_aco_dist_km = 0.0
        total_aco_dur_min = 0.0
        total_greedy_dist_km = 0.0
        total_greedy_dur_min = 0.0
        routeable_count = 0
        total_options_evaluated = 0

        for batch in batches:
            b_orders = [order_map[oid] for oid in batch.order_ids if oid in order_map]
            if not b_orders:
                continue

            # Identify eligible riders for this batch
            b_w = sum(float(getattr(o, "weight_kg", 1.0)) for o in b_orders)
            b_p = sum(int(getattr(o, "package_count", 1)) for o in b_orders)

            eligible_candidates = [
                r for r in all_riders
                if bool(getattr(r, "is_available", True))
                and float(getattr(r, "weight_capacity_kg", 20.0)) >= b_w
                and int(getattr(r, "package_count_capacity", 10)) >= b_p
            ]

            if not eligible_candidates:
                batch_route_results.append(
                    BatchRouteResult(
                        batch_id=batch.batch_id,
                        order_ids=batch.order_ids,
                        eligible_rider_ids=[],
                        route_candidates=[],
                        best_feasible_candidate=None,
                        is_routeable=False,
                        unrouteable_reason="No available fleet riders have sufficient capacity for this batch.",
                    )
                )
                continue

            # Evaluate the nearest riders first so a candidate cap cannot exclude
            # the rider who is closest to this batch's pickup locations.
            pickup_ids = [f"P_{order.id}" for order in b_orders]

            def approach_key(rider: Any) -> Tuple[float, float, str]:
                rider_id = f"R_{rider.id}"
                approaches = [
                    cost_matrix.get((rider_id, pickup_id), (float("inf"), float("inf")))
                    for pickup_id in pickup_ids
                ]
                distance_m, duration_s = min(approaches, key=lambda pair: (pair[1], pair[0]))
                return duration_s, distance_m, str(rider.id)

            eligible_candidates.sort(key=approach_key)
            eval_candidates = eligible_candidates[: cfg.max_candidate_riders]
            rider_options: List[RiderRouteOption] = []

            for rider in eval_candidates:
                opt = cls.optimize_route_for_rider(b_orders, rider, cost_matrix, now, cfg)
                rider_options.append(opt)
                total_options_evaluated += 1

            # Pick best feasible candidate (lowest travel cost)
            feasible_options = [opt for opt in rider_options if opt.is_feasible]
            if feasible_options:
                best_opt = min(feasible_options, key=lambda o: (o.duration_seconds, o.distance_meters))
                is_routeable = True
                unrouteable_reason = None
                routeable_count += 1

                total_aco_dist_km += best_opt.distance_km
                total_aco_dur_min += best_opt.duration_minutes

                # Aggregate greedy baseline comparison
                g_comp = best_opt.baseline_comparison
                total_greedy_dist_km += g_comp.get("distance_km", best_opt.distance_km)
                total_greedy_dur_min += g_comp.get("duration_min", best_opt.duration_minutes)
            else:
                best_opt = min(rider_options, key=lambda o: (o.duration_seconds, o.distance_meters)) if rider_options else None
                is_routeable = False
                unrouteable_reason = "No candidate route met all delivery deadlines and capacity limits."

            batch_route_results.append(
                BatchRouteResult(
                    batch_id=batch.batch_id,
                    order_ids=batch.order_ids,
                    eligible_rider_ids=[r.id for r in eligible_candidates],
                    route_candidates=rider_options,
                    best_feasible_candidate=best_opt if is_routeable else None,
                    is_routeable=is_routeable,
                    unrouteable_reason=unrouteable_reason,
                )
            )

        # Summary statistics
        dist_delta_pct = (
            round(((total_aco_dist_km - total_greedy_dist_km) / total_greedy_dist_km) * 100.0, 1)
            if total_greedy_dist_km > 0
            else 0.0
        )
        dur_delta_pct = (
            round(((total_aco_dur_min - total_greedy_dur_min) / total_greedy_dur_min) * 100.0, 1)
            if total_greedy_dur_min > 0
            else 0.0
        )

        summary = {
            "total_batches": len(batches),
            "routeable_batches_count": routeable_count,
            "total_route_candidates_evaluated": total_options_evaluated,
            "aco_vs_greedy_comparison": {
                "aco_total_distance_km": round(total_aco_dist_km, 2),
                "aco_total_duration_min": round(total_aco_dur_min, 1),
                "greedy_total_distance_km": round(total_greedy_dist_km, 2),
                "greedy_total_duration_min": round(total_greedy_dur_min, 1),
                "distance_delta_pct": dist_delta_pct,
                "duration_delta_pct": dur_delta_pct,
            },
        }

        return RoutesPreviewResult(
            batches=batch_route_results,
            summary=summary,
            preview_mode=True,
            attribution=DEFAULT_ATTRIBUTION,
            traffic_note=DEFAULT_TRAFFIC_NOTE,
        )
