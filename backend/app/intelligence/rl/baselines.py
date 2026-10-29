from typing import Any, Dict, List, Optional
import numpy as np

from backend.app.intelligence.rl.environment import RiderAssignmentEnv


class BaselinePolicy:
    """Base interface for deterministic rider assignment heuristics."""
    name: str = "base"

    def select_action(self, env: RiderAssignmentEnv) -> int:
        raise NotImplementedError


class NearestFeasibleRiderPolicy(BaselinePolicy):
    """Selects the eligible candidate rider with the shortest route distance."""
    name = "nearest_feasible_rider"

    def select_action(self, env: RiderAssignmentEnv) -> int:
        mask = env.action_masks()
        defer_action = env.defer_action

        # If no rider is feasible, must defer
        feasible_slots = [i for i in range(env.max_candidate_riders) if mask[i]]
        if not feasible_slots:
            return defer_action

        batch = env.batches[env.current_batch_idx]
        best_slot = -1
        min_dist = float("inf")

        for slot in feasible_slots:
            rider = env.riders[slot]
            route = batch.route_candidates.get(rider.rider_id)
            if route and route.distance_km < min_dist:
                min_dist = route.distance_km
                best_slot = slot

        return best_slot if best_slot >= 0 else defer_action


class LeastLoadedFeasibleRiderPolicy(BaselinePolicy):
    """Selects the eligible candidate rider with the lowest accumulated workload."""
    name = "least_loaded_feasible_rider"

    def select_action(self, env: RiderAssignmentEnv) -> int:
        mask = env.action_masks()
        defer_action = env.defer_action

        feasible_slots = [i for i in range(env.max_candidate_riders) if mask[i]]
        if not feasible_slots:
            return defer_action

        best_slot = -1
        min_load_tuple = (float("inf"), float("inf"))

        for slot in feasible_slots:
            rider = env.riders[slot]
            # Primary criterion: assigned batch count; secondary: cumulative duration
            load_tuple = (rider.assigned_batch_count, rider.total_duration_min)
            if load_tuple < min_load_tuple:
                min_load_tuple = load_tuple
                best_slot = slot

        return best_slot if best_slot >= 0 else defer_action


class WeightedScoreAssignmentPolicy(BaselinePolicy):
    """Scores candidate riders balancing travel distance, route duration, load, and deadline slack."""
    name = "weighted_score_assignment"

    def select_action(self, env: RiderAssignmentEnv) -> int:
        mask = env.action_masks()
        defer_action = env.defer_action

        feasible_slots = [i for i in range(env.max_candidate_riders) if mask[i]]
        if not feasible_slots:
            return defer_action

        batch = env.batches[env.current_batch_idx]
        best_slot = -1
        best_score = float("inf")

        for slot in feasible_slots:
            rider = env.riders[slot]
            route = batch.route_candidates.get(rider.rider_id)
            if not route:
                continue

            norm_dist = route.distance_km / 10.0
            norm_dur = route.duration_minutes / 60.0
            norm_load = rider.assigned_batch_count / 3.0

            # Minimum deadline slack among stops
            min_slack = 3600.0
            for s in route.stops:
                if s.deadline_slack_seconds is not None:
                    min_slack = min(min_slack, s.deadline_slack_seconds)
            norm_slack = np.clip(min_slack / 3600.0, -1.0, 1.0)

            score = (
                0.35 * norm_dist
                + 0.35 * norm_dur
                + 0.25 * norm_load
                - 0.15 * norm_slack
            )

            if score < best_score:
                best_score = score
                best_slot = slot

        return best_slot if best_slot >= 0 else defer_action


class RouteAwareFleetAssignmentPolicy(BaselinePolicy):
    """Minimizes total fleet incremental cost combining approach time, route duration/distance, and workload."""
    name = "route_aware_fleet_assignment"

    def select_action(self, env: RiderAssignmentEnv) -> int:
        mask = env.action_masks()
        defer_action = env.defer_action

        feasible_slots = [i for i in range(env.max_candidate_riders) if mask[i]]
        if not feasible_slots:
            return defer_action

        batch = env.batches[env.current_batch_idx]
        best_slot = -1
        best_cost = float("inf")

        for slot in feasible_slots:
            rider = env.riders[slot]
            route = batch.route_candidates.get(rider.rider_id)
            if not route:
                continue

            appr_km = getattr(route, "approach_distance_km", 0.0)
            appr_min = getattr(route, "approach_duration_minutes", 0.0)

            # Documented fleet objective cost:
            # 1.0 * duration_minutes + 0.5 * distance_km + 0.2 * approach_distance_km + 2.0 * assigned_count
            cost = (
                route.duration_minutes
                + (0.5 * route.distance_km)
                + (0.2 * appr_km)
                + (2.0 * rider.assigned_batch_count)
            )

            # Deterministic tie-breaker: rider_id ascending
            if cost < best_cost or (best_slot >= 0 and abs(cost - best_cost) < 1e-4 and rider.rider_id < env.riders[best_slot].rider_id):
                best_cost = cost
                best_slot = slot

        return best_slot if best_slot >= 0 else defer_action


def evaluate_policy_on_scenarios(
    policy: BaselinePolicy,
    scenario_seeds: List[int],
    max_candidate_riders: int = 5,
) -> Dict[str, Any]:
    """Evaluate an assignment policy deterministically across a list of scenarios."""
    env = RiderAssignmentEnv(max_candidate_riders=max_candidate_riders)
    total_assigned = 0
    total_batches = 0
    total_on_time = 0
    total_distance_km = 0.0
    total_duration_min = 0.0
    total_reward = 0.0
    episode_rewards: List[float] = []
    hard_violations = 0

    for s_seed in scenario_seeds:
        obs, info = env.reset(seed=s_seed)
        terminated = False
        ep_rew = 0.0

        while not terminated:
            action = policy.select_action(env)
            obs, rew, terminated, truncated, step_info = env.step(action)
            ep_rew += rew

        m = env.episode_metrics
        total_assigned += m["total_assigned"]
        total_batches += len(env.batches)
        total_on_time += m["on_time_count"]
        total_distance_km += m["total_distance_km"]
        total_duration_min += m["total_duration_min"]
        hard_violations += m["hard_constraint_violations"]
        total_reward += ep_rew
        episode_rewards.append(ep_rew)

    assign_pct = (total_assigned / max(1, total_batches)) * 100.0
    ontime_pct = (total_on_time / max(1, total_assigned)) * 100.0 if total_assigned > 0 else 0.0

    return {
        "policy_name": policy.name,
        "scenarios_evaluated": len(scenario_seeds),
        "total_batches": total_batches,
        "total_assigned": total_assigned,
        "total_unassigned": total_batches - total_assigned,
        "percentage_batches_assigned": round(assign_pct, 1),
        "percentage_on_time": round(ontime_pct, 1),
        "total_distance_km": round(total_distance_km, 2),
        "total_duration_min": round(total_duration_min, 1),
        "hard_constraint_violations": hard_violations,
        "average_episode_reward": round(float(np.mean(episode_rewards)), 2),
        "reward_std_dev": round(float(np.std(episode_rewards)), 2),
    }
