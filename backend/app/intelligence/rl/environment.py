import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from pydantic import BaseModel, Field

from backend.app.intelligence.aco.aco_routing import (
    BatchRouteResult,
    RiderRouteOption,
    RouteStop,
)

DEFAULT_MAX_CANDIDATE_RIDERS = 5
OBS_DIM = 7 + (10 * DEFAULT_MAX_CANDIDATE_RIDERS)  # 57 features


class RiderSimState(BaseModel):
    """Tracks dynamic operational state of a fleet rider during sequential simulation."""
    rider_id: str
    display_name: str
    current_lat: float
    current_lon: float
    weight_capacity_kg: float = 20.0
    package_count_capacity: int = 10
    available_at: datetime
    assigned_batch_count: int = 0
    total_distance_km: float = 0.0
    total_duration_min: float = 0.0
    assigned_batches: List[str] = Field(default_factory=list)


class BatchSimItem(BaseModel):
    """Represents a candidate delivery batch and its candidate route options for dispatch."""
    batch_id: str
    order_ids: List[str]
    total_weight_kg: float
    total_packages: int
    urgency_score: float = 0.5  # [0.0, 1.0]
    min_deadline: datetime
    route_candidates: Dict[str, RiderRouteOption] = Field(
        default_factory=dict,
        description="Maps rider_id to evaluated ACO route candidate",
    )


class DispatchScenario(BaseModel):
    """A reproducible multi-batch, multi-rider operational dispatch scenario."""
    scenario_id: str
    reference_time: datetime
    riders: List[RiderSimState]
    batches: List[BatchSimItem]


# Canonical Mumbai geographic hubs for procedural realistic scenario generation
MUMBAI_HUBS = [
    {"name": "Bandra West", "lat": 19.0596, "lon": 72.8295},
    {"name": "Dadar Commercial", "lat": 19.0178, "lon": 72.8478},
    {"name": "Lower Parel Hub", "lat": 18.9953, "lon": 72.8288},
    {"name": "Khar West", "lat": 19.0700, "lon": 72.8340},
    {"name": "Prabhadevi", "lat": 19.0150, "lon": 72.8280},
    {"name": "Juhu North", "lat": 19.1020, "lon": 72.8260},
]


def generate_procedural_scenario(seed: int, num_batches: int = 5, num_riders: int = 3) -> DispatchScenario:
    """Generate a realistic, deterministic Mumbai dispatch scenario for training and validation."""
    rng = np.random.RandomState(seed)
    now = datetime(2026, 10, 23, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Initialize fleet riders
    riders: List[RiderSimState] = []
    rider_names = ["Aarav Sharma", "Rohan Patel", "Vikram Jadhav", "Sneha Iyer", "Karan Mehta"]
    for i in range(num_riders):
        hub = MUMBAI_HUBS[i % len(MUMBAI_HUBS)]
        r_lat = hub["lat"] + rng.uniform(-0.005, 0.005)
        r_lon = hub["lon"] + rng.uniform(-0.005, 0.005)
        w_cap = 20.0 if i % 2 == 0 else 25.0
        p_cap = 8 if i % 2 == 0 else 10
        riders.append(
            RiderSimState(
                rider_id=f"R-SIM-{i+1:02d}",
                display_name=f"{rider_names[i % len(rider_names)]} (SIM)",
                current_lat=round(r_lat, 5),
                current_lon=round(r_lon, 5),
                weight_capacity_kg=w_cap,
                package_count_capacity=p_cap,
                available_at=now,
            )
        )

    # 2. Generate delivery batches
    batches: List[BatchSimItem] = []
    for b_idx in range(num_batches):
        b_id = f"BATCH-SIM-{b_idx+1:02d}"
        order_count = rng.randint(1, 4)
        order_ids = [f"ORD-S{b_idx+1}-{o+1:02d}" for o in range(order_count)]
        weight_kg = round(float(rng.uniform(1.5, 9.0)), 2)
        pkg_cnt = int(rng.randint(1, 5))
        urgency = round(float(rng.uniform(0.2, 0.95)), 2)
        deadline_lead_min = rng.choice([45, 60, 90, 120])
        min_dl = now + timedelta(minutes=int(deadline_lead_min))

        p_hub = MUMBAI_HUBS[rng.randint(0, len(MUMBAI_HUBS))]
        d_hub = MUMBAI_HUBS[rng.randint(0, len(MUMBAI_HUBS))]

        # Generate candidate routes for all riders
        candidate_routes: Dict[str, RiderRouteOption] = {}
        for rider in riders:
            # Estimate road distance based on coordinates
            d_lat = abs(rider.current_lat - p_hub["lat"]) + abs(p_hub["lat"] - d_hub["lat"])
            d_lon = abs(rider.current_lon - p_hub["lon"]) + abs(p_hub["lon"] - d_hub["lon"])
            # Approx 1 deg ~ 111 km in Mumbai
            dist_km = round(max(1.2, (d_lat + d_lon) * 85.0 + rng.uniform(0.5, 2.0)), 2)
            dist_m = dist_km * 1000.0
            # Approx 22 km/h average driving speed + service times (3 min per stop)
            drive_min = (dist_km / 22.0) * 60.0
            svc_min = (order_count * 2) * 3.0
            dur_min = round(drive_min + svc_min, 1)
            dur_sec = dur_min * 60.0

            arrival_time = now + timedelta(seconds=dur_sec)
            slack_sec = (min_dl - arrival_time).total_seconds()
            on_time = slack_sec >= 0.0

            # Capacity check
            cap_ok = (weight_kg <= rider.weight_capacity_kg) and (pkg_cnt <= rider.package_count_capacity)
            is_feasible = cap_ok and on_time

            stops = [
                RouteStop(
                    stop_index=0,
                    event_id=f"R_{rider.rider_id}",
                    event_type="ORIGIN",
                    latitude=rider.current_lat,
                    longitude=rider.current_lon,
                    arrival_time=now,
                    arrival_offset_seconds=0.0,
                    departure_offset_seconds=0.0,
                    onboard_weight_kg=0.0,
                    onboard_packages=0,
                ),
                RouteStop(
                    stop_index=1,
                    event_id=f"P_{order_ids[0]}",
                    order_id=order_ids[0],
                    event_type="PICKUP",
                    latitude=p_hub["lat"],
                    longitude=p_hub["lon"],
                    arrival_time=now + timedelta(minutes=round(drive_min * 0.4, 1)),
                    arrival_offset_seconds=round(drive_min * 24.0, 1),
                    departure_offset_seconds=round(drive_min * 24.0 + 180.0, 1),
                    onboard_weight_kg=weight_kg,
                    onboard_packages=pkg_cnt,
                ),
                RouteStop(
                    stop_index=2,
                    event_id=f"D_{order_ids[0]}",
                    order_id=order_ids[0],
                    event_type="DELIVERY",
                    latitude=d_hub["lat"],
                    longitude=d_hub["lon"],
                    arrival_time=arrival_time,
                    arrival_offset_seconds=dur_sec - 180.0,
                    departure_offset_seconds=dur_sec,
                    deadline=min_dl,
                    deadline_slack_seconds=slack_sec,
                    is_on_time=on_time,
                    onboard_weight_kg=0.0,
                    onboard_packages=0,
                ),
            ]

            reasons = []
            if not cap_ok:
                reasons.append("Weight or package capacity exceeded.")
            if not on_time:
                reasons.append(f"Deadline violation: {slack_sec:.1f}s late.")

            candidate_routes[rider.rider_id] = RiderRouteOption(
                rider_id=rider.rider_id,
                rider_display_name=rider.display_name,
                stops=stops,
                distance_meters=dist_m,
                distance_km=dist_km,
                duration_seconds=dur_sec,
                duration_minutes=dur_min,
                peak_weight_kg=weight_kg,
                peak_packages=pkg_cnt,
                peak_weight_utilization_pct=round((weight_kg / rider.weight_capacity_kg) * 100.0, 1),
                peak_package_utilization_pct=round((pkg_cnt / rider.package_count_capacity) * 100.0, 1),
                all_deadlines_met=on_time,
                is_feasible=is_feasible,
                infeasibility_reasons=reasons,
                aco_execution_time_ms=1.5,
                baseline_comparison={
                    "distance_km": dist_km,
                    "duration_min": dur_min,
                    "all_deadlines_met": on_time,
                    "is_feasible": is_feasible,
                },
            )

        batches.append(
            BatchSimItem(
                batch_id=b_id,
                order_ids=order_ids,
                total_weight_kg=weight_kg,
                total_packages=pkg_cnt,
                urgency_score=urgency,
                min_deadline=min_dl,
                route_candidates=candidate_routes,
            )
        )

    # Sort batches by urgency (highest first) as standard dispatch ordering
    batches.sort(key=lambda b: -b.urgency_score)

    return DispatchScenario(
        scenario_id=f"SCENARIO-{seed}",
        reference_time=now,
        riders=riders,
        batches=batches,
    )


class RiderAssignmentEnv(gym.Env):
    """Gymnasium environment for sequential rider dispatch assignment using MaskablePPO."""
    metadata = {"render_modes": []}

    def __init__(
        self,
        max_candidate_riders: int = DEFAULT_MAX_CANDIDATE_RIDERS,
        default_seed: int = 42,
    ):
        super().__init__()
        self.max_candidate_riders = max_candidate_riders
        self.default_seed = default_seed
        self.obs_dim = 7 + (10 * self.max_candidate_riders)

        # Action Space: 0 .. (max_candidate_riders - 1) = assign to rider slot, max_candidate_riders = defer
        self.action_space = spaces.Discrete(self.max_candidate_riders + 1)
        self.defer_action = self.max_candidate_riders

        # Observation Space: normalized features bounded in [-1.0, 1.0]
        self.observation_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(self.obs_dim,),
            dtype=np.float32,
        )

        # Environment state variables
        self.scenario: Optional[DispatchScenario] = None
        self.current_sim_time: datetime = datetime.now(timezone.utc)
        self.current_batch_idx: int = 0
        self.riders: List[RiderSimState] = []
        self.batches: List[BatchSimItem] = []
        self.assignment_history: List[Dict[str, Any]] = []
        self.episode_metrics: Dict[str, Any] = {}

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Reset the environment to the beginning of a dispatch scenario."""
        super().reset(seed=seed)
        eff_seed = seed if seed is not None else self.default_seed

        if options and "scenario" in options:
            self.scenario = copy.deepcopy(options["scenario"])
        elif options and "batches" in options and "riders" in options:
            # Construct scenario directly from live batches & riders
            self.scenario = DispatchScenario(
                scenario_id=options.get("scenario_id", f"SCENARIO-LIVE-{eff_seed}"),
                reference_time=options.get("reference_time", datetime.now(timezone.utc)),
                riders=copy.deepcopy(options["riders"]),
                batches=copy.deepcopy(options["batches"]),
            )
        else:
            self.scenario = generate_procedural_scenario(seed=eff_seed)

        self.current_sim_time = self.scenario.reference_time
        self.current_batch_idx = 0
        self.riders = self.scenario.riders
        self.batches = self.scenario.batches
        self.assignment_history = []
        self.episode_metrics = {
            "total_assigned": 0,
            "total_deferred": 0,
            "on_time_count": 0,
            "late_count": 0,
            "total_distance_km": 0.0,
            "total_duration_min": 0.0,
            "hard_constraint_violations": 0,
            "reward_components": {
                "R_assign": 0.0,
                "R_ontime": 0.0,
                "R_duration": 0.0,
                "R_distance": 0.0,
                "R_imbalance": 0.0,
                "R_defer": 0.0,
                "R_invalid": 0.0,
            },
        }

        obs = self._build_observation(self.current_batch_idx)
        info = {
            "scenario_id": self.scenario.scenario_id,
            "total_batches": len(self.batches),
            "total_riders": len(self.riders),
            "action_mask": self.action_masks(),
        }
        return obs, info

    def action_masks(self) -> np.ndarray:
        """Return boolean mask of valid actions for the current batch. Action K (defer) is always True."""
        mask = np.zeros(self.action_space.n, dtype=bool)
        # Defer action is always legal to prevent environment deadlock
        mask[self.defer_action] = True

        if self.current_batch_idx >= len(self.batches):
            return mask

        batch = self.batches[self.current_batch_idx]

        for slot_idx in range(self.max_candidate_riders):
            if slot_idx >= len(self.riders):
                mask[slot_idx] = False
                continue

            rider = self.riders[slot_idx]
            route_opt = batch.route_candidates.get(rider.rider_id)

            if route_opt is None:
                mask[slot_idx] = False
                continue

            # Hard Constraint 1: Weight & package capacity
            cap_ok = (
                batch.total_weight_kg <= rider.weight_capacity_kg
                and batch.total_packages <= rider.package_count_capacity
            )

            # Hard Constraint 2: ACO route feasibility and precedence
            route_ok = route_opt.is_feasible and route_opt.all_deadlines_met

            # Hard Constraint 3: Overlapping conflicting schedule
            # Rider can serve if currently idle or if available before the delivery deadline
            sched_ok = rider.available_at <= batch.min_deadline

            if cap_ok and route_ok and sched_ok:
                mask[slot_idx] = True
            else:
                mask[slot_idx] = False

        return mask

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """Execute one sequential dispatch decision."""
        if self.current_batch_idx >= len(self.batches):
            obs = np.zeros(self.obs_dim, dtype=np.float32)
            return obs, 0.0, True, False, {"info": "Episode already completed"}

        batch = self.batches[self.current_batch_idx]
        mask = self.action_masks()
        reward = 0.0
        step_reward_breakdown: Dict[str, float] = {}

        if not mask[action]:
            # Invalid action penalized defensively
            r_inv = -20.0
            reward += r_inv
            self.episode_metrics["hard_constraint_violations"] += 1
            self.episode_metrics["reward_components"]["R_invalid"] += r_inv
            step_reward_breakdown["R_invalid"] = r_inv

            # Record unassigned due to invalid selection
            self.assignment_history.append({
                "batch_id": batch.batch_id,
                "order_ids": batch.order_ids,
                "action": action,
                "action_type": "INVALID_ACTION",
                "assigned_rider_id": None,
                "status": "UNASSIGNED",
                "reason": f"Action {action} violated hard operational constraints.",
            })
            self.episode_metrics["total_deferred"] += 1

        elif action == self.defer_action:
            # Explicit Deferral Action
            any_feasible_available = any(mask[:self.max_candidate_riders])
            # If agent chose to defer when a feasible candidate was available, penalize more severely
            r_def = -8.0 if any_feasible_available else -1.0
            reward += r_def
            self.episode_metrics["reward_components"]["R_defer"] += r_def
            step_reward_breakdown["R_defer"] = r_def

            self.assignment_history.append({
                "batch_id": batch.batch_id,
                "order_ids": batch.order_ids,
                "action": action,
                "action_type": "DEFER",
                "assigned_rider_id": None,
                "status": "UNASSIGNED",
                "reason": "Deferred by dispatch policy." if any_feasible_available else "No feasible candidate rider available.",
            })
            self.episode_metrics["total_deferred"] += 1

        else:
            # Feasible Rider Assignment
            selected_rider = self.riders[action]
            route_opt = batch.route_candidates[selected_rider.rider_id]

            # 1. Base assignment reward
            r_assign = 10.0
            # 2. On-time delivery bonus / deadline lateness penalty
            r_ontime = 5.0 if route_opt.all_deadlines_met else -10.0
            # 3. Efficiency penalties
            r_dur = -0.05 * route_opt.duration_minutes
            r_dist = -0.05 * route_opt.distance_km

            # 4. Workload balance penalty: deviation from fleet mean
            fleet_loads = [r.assigned_batch_count for r in self.riders]
            mean_load = float(np.mean(fleet_loads)) if fleet_loads else 0.0
            r_imbal = -2.0 * abs((selected_rider.assigned_batch_count + 1) - mean_load)

            step_reward = r_assign + r_ontime + r_dur + r_dist + r_imbal
            reward += step_reward

            self.episode_metrics["reward_components"]["R_assign"] += r_assign
            self.episode_metrics["reward_components"]["R_ontime"] += r_ontime
            self.episode_metrics["reward_components"]["R_duration"] += r_dur
            self.episode_metrics["reward_components"]["R_distance"] += r_dist
            self.episode_metrics["reward_components"]["R_imbalance"] += r_imbal

            step_reward_breakdown = {
                "R_assign": r_assign,
                "R_ontime": r_ontime,
                "R_duration": r_dur,
                "R_distance": r_dist,
                "R_imbalance": r_imbal,
            }

            # Update Rider Simulation State
            workload_before = selected_rider.assigned_batch_count
            selected_rider.assigned_batch_count += 1
            selected_rider.total_distance_km += route_opt.distance_km
            selected_rider.total_duration_min += route_opt.duration_minutes
            selected_rider.assigned_batches.append(batch.batch_id)

            # Advance rider availability time:
            # If rider is currently idle, starts at current_sim_time; if busy, chains sequentially
            start_time = max(self.current_sim_time, selected_rider.available_at)
            finish_time = start_time + timedelta(seconds=route_opt.duration_seconds)
            selected_rider.available_at = finish_time

            # Update rider position to final delivery stop of the assigned route
            if route_opt.stops:
                final_stop = route_opt.stops[-1]
                selected_rider.current_lat = final_stop.latitude
                selected_rider.current_lon = final_stop.longitude

            self.episode_metrics["total_assigned"] += 1
            if route_opt.all_deadlines_met:
                self.episode_metrics["on_time_count"] += 1
            else:
                self.episode_metrics["late_count"] += 1
            self.episode_metrics["total_distance_km"] += route_opt.distance_km
            self.episode_metrics["total_duration_min"] += route_opt.duration_minutes

            self.assignment_history.append({
                "batch_id": batch.batch_id,
                "order_ids": batch.order_ids,
                "action": action,
                "action_type": "ASSIGN",
                "assigned_rider_id": selected_rider.rider_id,
                "assigned_rider_name": selected_rider.display_name,
                "status": "ASSIGNED",
                "route": route_opt.model_dump(),
                "workload_before": workload_before,
                "workload_after": selected_rider.assigned_batch_count,
            })

        # Advance to next batch
        self.current_batch_idx += 1
        terminated = self.current_batch_idx >= len(self.batches)
        truncated = False

        next_obs = self._build_observation(self.current_batch_idx)

        info = {
            "step_reward_breakdown": step_reward_breakdown,
            "current_batch_idx": self.current_batch_idx,
            "terminated": terminated,
            "action_mask": self.action_masks(),
            "episode_metrics": self.episode_metrics,
        }

        return next_obs, float(reward), terminated, truncated, info

    def _build_observation(self, batch_idx: int) -> np.ndarray:
        """Construct the fixed-size normalized observation vector for the current decision step."""
        obs = np.zeros(self.obs_dim, dtype=np.float32)

        if batch_idx >= len(self.batches):
            return obs

        batch = self.batches[batch_idx]

        # 1. Global / Batch Features (Indices 0..6)
        # Urgency [0.0, 1.0]
        obs[0] = np.clip(batch.urgency_score, 0.0, 1.0)
        # Order count normalized by 5.0
        obs[1] = np.clip(len(batch.order_ids) / 5.0, 0.0, 1.0)
        # Batch weight normalized by 25.0 kg
        obs[2] = np.clip(batch.total_weight_kg / 25.0, 0.0, 1.0)
        # Package count normalized by 10
        obs[3] = np.clip(batch.total_packages / 10.0, 0.0, 1.0)
        # Deadline slack normalized by 2 hours (7200s), clipped in [-1.0, 1.0]
        slack_s = (batch.min_deadline - self.current_sim_time).total_seconds()
        obs[4] = np.clip(slack_s / 7200.0, -1.0, 1.0)
        # Simulation progress ratio
        obs[5] = np.clip(batch_idx / max(1, len(self.batches)), 0.0, 1.0)
        # Remaining batches ratio
        obs[6] = np.clip((len(self.batches) - batch_idx) / max(1, len(self.batches)), 0.0, 1.0)

        # 2. Per-Rider Slot Features (10 features per slot)
        base_offset = 7
        for slot_idx in range(self.max_candidate_riders):
            slot_start = base_offset + (slot_idx * 10)

            if slot_idx >= len(self.riders):
                # Empty / unused rider slot -> remaining zeros
                continue

            rider = self.riders[slot_idx]
            route_opt = batch.route_candidates.get(rider.rider_id)

            # Slot active
            obs[slot_start + 0] = 1.0

            if route_opt is not None:
                # Route feasible
                obs[slot_start + 1] = 1.0 if route_opt.is_feasible else 0.0
                # Route distance normalized by 20.0 km
                obs[slot_start + 2] = np.clip(route_opt.distance_km / 20.0, 0.0, 1.0)
                # Route duration normalized by 120.0 min
                obs[slot_start + 3] = np.clip(route_opt.duration_minutes / 120.0, 0.0, 1.0)
                # Deadline margin (min slack) normalized by 60 min, clipped in [-1.0, 1.0]
                min_slack = 3600.0
                for stop in route_opt.stops:
                    if stop.deadline_slack_seconds is not None:
                        min_slack = min(min_slack, stop.deadline_slack_seconds)
                obs[slot_start + 4] = np.clip(min_slack / 3600.0, -1.0, 1.0)
            else:
                obs[slot_start + 1] = 0.0
                obs[slot_start + 2] = 1.0  # high distance penalty
                obs[slot_start + 3] = 1.0  # high duration penalty
                obs[slot_start + 4] = -1.0

            # Rider idle status (available now)
            is_idle = 1.0 if rider.available_at <= self.current_sim_time else 0.0
            obs[slot_start + 5] = is_idle

            # Time until available in minutes (normalized by 60.0 min)
            wait_sec = max(0.0, (rider.available_at - self.current_sim_time).total_seconds())
            obs[slot_start + 6] = np.clip((wait_sec / 60.0) / 60.0, 0.0, 1.0)

            # Assigned batches workload (normalized by 5)
            obs[slot_start + 7] = np.clip(rider.assigned_batch_count / 5.0, 0.0, 1.0)

            # Remaining weight capacity ratio
            rem_w = max(0.0, rider.weight_capacity_kg - batch.total_weight_kg)
            obs[slot_start + 8] = np.clip(rem_w / max(1.0, rider.weight_capacity_kg), 0.0, 1.0)

            # Remaining package capacity ratio
            rem_p = max(0, rider.package_count_capacity - batch.total_packages)
            obs[slot_start + 9] = np.clip(rem_p / max(1, rider.package_count_capacity), 0.0, 1.0)

        # Enforce strict float32 and no NaN or Inf
        obs = np.nan_to_num(obs, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float32)
        return obs
