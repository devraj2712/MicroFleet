import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from backend.app.intelligence.aco.aco_routing import (
    ACOConfig,
    ACORoutingEngine,
    BatchRouteResult,
    RiderRouteOption,
    RouteStop,
    RoutesPreviewResult,
    validate_route,
)
from backend.app.intelligence.fuzzy.fuzzy_urgency import FuzzyUrgencyEngine
from backend.app.intelligence.ga.ga_batching import GABatchingEngine, GAConfig
from backend.app.intelligence.osm.osm_service import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_TRAFFIC_NOTE,
)
from backend.app.intelligence.rl.baselines import (
    LeastLoadedFeasibleRiderPolicy,
    NearestFeasibleRiderPolicy,
    WeightedScoreAssignmentPolicy,
)
from backend.app.intelligence.rl.environment import (
    DEFAULT_MAX_CANDIDATE_RIDERS,
    BatchSimItem,
    DispatchScenario,
    RiderAssignmentEnv,
    RiderSimState,
)
from backend.app.intelligence.rl.train import load_trained_model

logger = logging.getLogger(__name__)


class AssignedBatchItem(BaseModel):
    batch_id: str
    order_ids: List[str]
    assigned_rider_id: str
    assigned_rider_name: str
    distance_km: float
    duration_minutes: float
    all_deadlines_met: bool
    stops: List[RouteStop]
    workload_before: int
    workload_after: int


class UnassignedBatchItem(BaseModel):
    batch_id: str
    order_ids: List[str]
    reason: str


class RiderWorkloadSummary(BaseModel):
    rider_id: str
    display_name: str
    assigned_batches: int
    total_distance_km: float
    total_duration_minutes: float
    final_simulated_availability: datetime


class DispatchPreviewResult(BaseModel):
    """Complete response model for in-process RL dispatch preview."""
    preview_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    assignments: List[AssignedBatchItem]
    unassigned_batches: List[UnassignedBatchItem]
    rider_workloads: List[RiderWorkloadSummary]
    summary: Dict[str, Any]
    baseline_comparisons: Dict[str, Any]
    policy_metadata: Dict[str, Any]
    preview_mode: bool = True
    attribution: str = DEFAULT_ATTRIBUTION
    traffic_note: str = DEFAULT_TRAFFIC_NOTE


class RLDispatchService:
    """Orchestrates in-process Fuzzy -> GA -> ACO -> RL dispatch assignment."""

    @classmethod
    def run_dispatch_pipeline(
        cls,
        orders: List[Any],
        riders: List[Any],
        reference_time: datetime,
        policy_choice: str = "rl",
        ga_config: Optional[GAConfig] = None,
        aco_config: Optional[ACOConfig] = None,
        model_path: Optional[str] = None,
    ) -> DispatchPreviewResult:
        """Execute end-to-end optimization pipeline and sequential RL assignment."""
        now = reference_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 1. Fuzzy Urgency Scoring (for batch ordering & diagnostics)
        urgency_scores: Dict[str, float] = {}
        for o in orders:
            u_res = FuzzyUrgencyEngine.score_order(o, reference_time=now)
            o_id = str(getattr(o, "id", None) or o.get("id"))
            urgency_scores[o_id] = u_res.urgency_score / 100.0  # normalize to [0, 1]

        # 2. GA Batching
        ga_cfg = ga_config or GAConfig()
        ga_comparison = GABatchingEngine.optimize_batches(
            orders=orders,
            riders=riders,
            reference_time=now,
            config=ga_cfg,
        )
        ga_batches = ga_comparison.ga_solution.batches

        # 3. ACO Route Optimization for candidate riders
        aco_cfg = aco_config or ACOConfig()
        aco_routes = ACORoutingEngine.optimize_batches_routes(
            batches=ga_batches,
            all_orders=orders,
            all_riders=riders,
            reference_time=now,
            config=aco_cfg,
        )

        # 4. Construct Simulation Scenario from real ACO outputs
        scenario_riders: List[RiderSimState] = []
        for r in riders:
            r_id = str(getattr(r, "id", None) or r.get("id"))
            name = str(getattr(r, "display_name", None) or r.get("display_name", r_id))
            r_lat = float(getattr(r, "current_latitude", None) or r.get("current_latitude", 0.0))
            r_lon = float(getattr(r, "current_longitude", None) or r.get("current_longitude", 0.0))
            w_cap = float(getattr(r, "weight_capacity_kg", None) or r.get("weight_capacity_kg", 20.0))
            p_cap = int(getattr(r, "package_count_capacity", None) or r.get("package_count_capacity", 10))

            scenario_riders.append(
                RiderSimState(
                    rider_id=r_id,
                    display_name=name,
                    current_lat=r_lat,
                    current_lon=r_lon,
                    weight_capacity_kg=w_cap,
                    package_count_capacity=p_cap,
                    available_at=now,
                )
            )

        order_map = {str(getattr(o, "id", None) or o.get("id")): o for o in orders}
        scenario_batches: List[BatchSimItem] = []
        unassigned_immediate: List[UnassignedBatchItem] = []

        for b_res in aco_routes.batches:
            if not b_res.is_routeable:
                unassigned_immediate.append(
                    UnassignedBatchItem(
                        batch_id=b_res.batch_id,
                        order_ids=b_res.order_ids,
                        reason=b_res.unrouteable_reason or "No feasible candidate routes available.",
                    )
                )
                continue

            b_orders = [order_map[oid] for oid in b_res.order_ids if oid in order_map]
            total_w = sum(float(getattr(o, "weight_kg", 1.0)) for o in b_orders)
            total_p = sum(int(getattr(o, "package_count", 1)) for o in b_orders)
            deadlines = [getattr(o, "delivery_deadline", now + timedelta(hours=2)) for o in b_orders]
            min_dl = min(deadlines) if deadlines else now + timedelta(hours=2)
            if min_dl.tzinfo is None:
                min_dl = min_dl.replace(tzinfo=timezone.utc)

            avg_urg = (
                sum(urgency_scores.get(oid, 0.5) for oid in b_res.order_ids) / max(1, len(b_res.order_ids))
            )

            # Map candidate routes by rider_id
            routes_by_rider = {c.rider_id: c for c in b_res.route_candidates}

            scenario_batches.append(
                BatchSimItem(
                    batch_id=b_res.batch_id,
                    order_ids=b_res.order_ids,
                    total_weight_kg=total_w,
                    total_packages=total_p,
                    urgency_score=round(avg_urg, 3),
                    min_deadline=min_dl,
                    route_candidates=routes_by_rider,
                )
            )

        # Sort batches in documented dispatch order: highest urgency first
        scenario_batches.sort(key=lambda b: -b.urgency_score)

        scenario = DispatchScenario(
            scenario_id=f"DISPATCH-LIVE-{int(now.timestamp())}",
            reference_time=now,
            riders=scenario_riders,
            batches=scenario_batches,
        )

        # 5. Load Policy
        rl_metadata = {}
        model = None
        if policy_choice == "rl":
            try:
                model, rl_metadata = load_trained_model(model_path)
                policy_label = "MaskablePPO (Trained Policy)"
            except FileNotFoundError as e:
                logger.warning(
                    "Trained RL model checkpoint not found (%s). Gracefully falling back to Weighted-Score baseline policy.",
                    e,
                )
                policy_choice = "weighted"
                policy_label = "Weighted-Score Assignment (RL Untrained Fallback)"
                rl_metadata = {
                    "fallback_note": "Trained RL model checkpoint (.zip) not found; run train_rider_assignment.py to train. Evaluated using Weighted-Score baseline.",
                    "trained_checkpoint_missing": True,
                }
        elif policy_choice == "nearest":
            policy_label = "Nearest Feasible Rider Baseline"
        elif policy_choice == "least_loaded":
            policy_label = "Least-Loaded Feasible Rider Baseline"
        elif policy_choice == "weighted":
            policy_label = "Weighted-Score Assignment Baseline"
        else:
            raise ValueError(f"Unknown policy choice: '{policy_choice}'")

        # 6. Execute Sequential Dispatch Simulation
        env = RiderAssignmentEnv(max_candidate_riders=DEFAULT_MAX_CANDIDATE_RIDERS)
        obs, info = env.reset(options={"scenario": scenario})
        terminated = False

        start_infer = time.perf_counter()

        while not terminated:
            action_mask = env.action_masks()

            if policy_choice == "rl":
                action, _ = model.predict(obs, action_masks=action_mask, deterministic=True)
                action = int(action)
            elif policy_choice == "nearest":
                action = NearestFeasibleRiderPolicy().select_action(env)
            elif policy_choice == "least_loaded":
                action = LeastLoadedFeasibleRiderPolicy().select_action(env)
            elif policy_choice == "weighted":
                action = WeightedScoreAssignmentPolicy().select_action(env)

            obs, reward, terminated, truncated, step_info = env.step(action)

        infer_time_ms = round((time.perf_counter() - start_infer) * 1000.0, 2)

        # 7. Collect Assigned and Unassigned Results
        assigned_items: List[AssignedBatchItem] = []
        unassigned_items: List[UnassignedBatchItem] = list(unassigned_immediate)

        for rec in env.assignment_history:
            if rec["status"] == "ASSIGNED":
                route_dict = rec["route"]
                # Convert back to RouteStop models
                stops = [RouteStop(**s) for s in route_dict["stops"]]

                assigned_items.append(
                    AssignedBatchItem(
                        batch_id=rec["batch_id"],
                        order_ids=rec["order_ids"],
                        assigned_rider_id=rec["assigned_rider_id"],
                        assigned_rider_name=rec["assigned_rider_name"],
                        distance_km=route_dict["distance_km"],
                        duration_minutes=route_dict["duration_minutes"],
                        all_deadlines_met=route_dict["all_deadlines_met"],
                        stops=stops,
                        workload_before=rec["workload_before"],
                        workload_after=rec["workload_after"],
                    )
                )
            else:
                unassigned_items.append(
                    UnassignedBatchItem(
                        batch_id=rec["batch_id"],
                        order_ids=rec["order_ids"],
                        reason=rec.get("reason", "Deferred by policy."),
                    )
                )

        # 8. Compile Workloads Summary
        workload_summaries: List[RiderWorkloadSummary] = []
        for r_state in env.riders:
            workload_summaries.append(
                RiderWorkloadSummary(
                    rider_id=r_state.rider_id,
                    display_name=r_state.display_name,
                    assigned_batches=r_state.assigned_batch_count,
                    total_distance_km=round(r_state.total_distance_km, 2),
                    total_duration_minutes=round(r_state.total_duration_min, 1),
                    final_simulated_availability=r_state.available_at,
                )
            )

        total_batches_all = len(ga_batches)
        unrouteable_count = len(unassigned_immediate)

        # 9. Comparative Baseline Evaluation on identical scenario
        baseline_comps = {}
        for b_policy in [
            NearestFeasibleRiderPolicy(),
            LeastLoadedFeasibleRiderPolicy(),
            WeightedScoreAssignmentPolicy(),
        ]:
            b_env = RiderAssignmentEnv(max_candidate_riders=DEFAULT_MAX_CANDIDATE_RIDERS)
            b_env.reset(options={"scenario": scenario})
            b_term = False
            b_rew = 0.0
            while not b_term:
                b_act = b_policy.select_action(b_env)
                _, r_step, b_term, _, _ = b_env.step(b_act)
                b_rew += r_step

            bm = b_env.episode_metrics
            baseline_unassigned_total = bm["total_deferred"] + unrouteable_count
            baseline_comps[b_policy.name] = {
                "assigned_count": bm["total_assigned"],
                "unassigned_count": baseline_unassigned_total,
                "percentage_batches_assigned": round((bm["total_assigned"] / max(1, total_batches_all)) * 100.0, 1),
                "total_distance_km": round(bm["total_distance_km"], 2),
                "total_duration_min": round(bm["total_duration_min"], 1),
                "on_time_count": bm["on_time_count"],
                "episode_reward": round(b_rew, 2),
            }

        summary = {
            "total_candidate_batches": total_batches_all,
            "feasible_batches_count": len(scenario_batches),
            "unrouteable_batches_count": unrouteable_count,
            "assigned_batches_count": len(assigned_items),
            "unassigned_batches_count": len(unassigned_items),
            "percentage_batches_assigned": round((len(assigned_items) / max(1, total_batches_all)) * 100.0, 1),
            "total_distance_km": round(sum(a.distance_km for a in assigned_items), 2),
            "total_duration_minutes": round(sum(a.duration_minutes for a in assigned_items), 1),
            "all_assignments_deadline_feasible": all(a.all_deadlines_met for a in assigned_items),
            "selected_policy": policy_label,
            "inference_time_ms": infer_time_ms,
        }

        return DispatchPreviewResult(
            assignments=assigned_items,
            unassigned_batches=unassigned_items,
            rider_workloads=workload_summaries,
            summary=summary,
            baseline_comparisons=baseline_comps,
            policy_metadata=rl_metadata,
            preview_mode=True,
            attribution=DEFAULT_ATTRIBUTION,
            traffic_note=DEFAULT_TRAFFIC_NOTE,
        )
