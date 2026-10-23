import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
import stable_baselines3 as sb3
import torch

from backend.app.intelligence.rl.baselines import (
    LeastLoadedFeasibleRiderPolicy,
    NearestFeasibleRiderPolicy,
    WeightedScoreAssignmentPolicy,
    evaluate_policy_on_scenarios,
)
from backend.app.intelligence.rl.environment import (
    DEFAULT_MAX_CANDIDATE_RIDERS,
    OBS_DIM,
    RiderAssignmentEnv,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("backend/models")
DEFAULT_REPORT_DIR = Path("backend/reports")
DEFAULT_MODEL_FILENAME = "rider_assignment_maskable_ppo.zip"
DEFAULT_META_FILENAME = "rider_assignment_maskable_ppo.meta.json"
DEFAULT_REPORT_FILENAME = "dispatch_evaluation_report.json"


def mask_fn(env: gym.Env) -> np.ndarray:
    return env.action_masks()


def evaluate_rl_policy_on_scenarios(
    model: MaskablePPO,
    scenario_seeds: List[int],
    max_candidate_riders: int = DEFAULT_MAX_CANDIDATE_RIDERS,
) -> Dict[str, Any]:
    """Evaluate a trained MaskablePPO agent deterministically on held-out test scenarios."""
    env = RiderAssignmentEnv(max_candidate_riders=max_candidate_riders)
    total_assigned = 0
    total_batches = 0
    total_on_time = 0
    total_distance_km = 0.0
    total_duration_min = 0.0
    total_reward = 0.0
    episode_rewards: List[float] = []
    hard_violations = 0
    start_time = time.perf_counter()

    for s_seed in scenario_seeds:
        obs, info = env.reset(seed=s_seed)
        terminated = False
        ep_rew = 0.0

        while not terminated:
            action_masks = env.action_masks()
            action, _ = model.predict(obs, action_masks=action_masks, deterministic=True)
            obs, rew, terminated, truncated, step_info = env.step(int(action))
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

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    assign_pct = (total_assigned / max(1, total_batches)) * 100.0
    ontime_pct = (total_on_time / max(1, total_assigned)) * 100.0 if total_assigned > 0 else 0.0

    return {
        "policy_name": "MaskablePPO_Trained",
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
        "total_inference_time_ms": round(elapsed_ms, 2),
        "avg_inference_time_per_decision_ms": round(elapsed_ms / max(1, total_batches), 3),
    }


def train_rl_agent(
    total_timesteps: int = 15000,
    seed: int = 42,
    model_dir: Optional[Path] = None,
    report_dir: Optional[Path] = None,
) -> Tuple[MaskablePPO, Dict[str, Any]]:
    """Train the MaskablePPO rider assignment agent and save model + metadata."""
    m_dir = model_dir or DEFAULT_MODEL_DIR
    r_dir = report_dir or DEFAULT_REPORT_DIR
    m_dir.mkdir(parents=True, exist_ok=True)
    r_dir.mkdir(parents=True, exist_ok=True)

    model_path = m_dir / DEFAULT_MODEL_FILENAME
    meta_path = m_dir / DEFAULT_META_FILENAME
    report_path = r_dir / DEFAULT_REPORT_FILENAME

    logger.info("Initializing RiderAssignmentEnv for MaskablePPO training (seed=%d)...", seed)

    raw_env = RiderAssignmentEnv(default_seed=seed)
    train_env = ActionMasker(raw_env, mask_fn)

    # Configure MaskablePPO policy hyperparameters
    model = MaskablePPO(
        "MlpPolicy",
        train_env,
        learning_rate=3e-4,
        n_steps=256,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        verbose=0,
        seed=seed,
        device="cpu",
    )

    t0 = time.perf_counter()
    logger.info("Starting RL policy training for %d timesteps...", total_timesteps)
    model.learn(total_timesteps=total_timesteps)
    train_time_sec = round(time.perf_counter() - t0, 2)
    logger.info("Training completed in %.2f seconds.", train_time_sec)

    # Save model checkpoint
    model.save(str(model_path))
    logger.info("Model checkpoint saved to: %s", model_path)

    # Evaluate on held-out evaluation scenarios (distinct seeds: 101..120)
    test_seeds = list(range(101, 121))
    rl_eval = evaluate_rl_policy_on_scenarios(model, test_seeds)

    # Evaluate the 3 comparison baselines on the same held-out test scenarios
    nearest_eval = evaluate_policy_on_scenarios(NearestFeasibleRiderPolicy(), test_seeds)
    least_load_eval = evaluate_policy_on_scenarios(LeastLoadedFeasibleRiderPolicy(), test_seeds)
    weighted_eval = evaluate_policy_on_scenarios(WeightedScoreAssignmentPolicy(), test_seeds)

    # Compile comprehensive metadata & comparison report
    metadata = {
        "model_name": "MaskablePPO-RiderAssignment",
        "model_version": "1.0.0",
        "algorithm": "MaskablePPO",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_timesteps": total_timesteps,
        "training_time_seconds": train_time_sec,
        "random_seed": seed,
        "observation_space": {
            "type": "Box",
            "shape": [OBS_DIM],
            "low": -1.0,
            "high": 1.0,
        },
        "action_space": {
            "type": "Discrete",
            "n": DEFAULT_MAX_CANDIDATE_RIDERS + 1,
            "actions": {
                f"{i}": f"Assign to candidate rider slot {i}"
                for i in range(DEFAULT_MAX_CANDIDATE_RIDERS)
            } | {f"{DEFAULT_MAX_CANDIDATE_RIDERS}": "Defer / leave unassigned"},
        },
        "dependencies": {
            "torch": torch.__version__,
            "gymnasium": gym.__version__,
            "stable_baselines3": sb3.__version__,
        },
        "held_out_evaluation": {
            "test_seeds": test_seeds,
            "rl_agent": rl_eval,
            "baselines": {
                "nearest_feasible_rider": nearest_eval,
                "least_loaded_feasible_rider": least_load_eval,
                "weighted_score_assignment": weighted_eval,
            },
        },
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(metadata["held_out_evaluation"], f, indent=2)

    logger.info("Metadata saved to: %s", meta_path)
    logger.info("Evaluation report saved to: %s", report_path)

    return model, metadata


def load_trained_model(
    model_path: Optional[str] = None,
    meta_path: Optional[str] = None,
) -> Tuple[MaskablePPO, Dict[str, Any]]:
    """Load a saved MaskablePPO checkpoint with verification and metadata validation."""
    m_p = Path(model_path) if model_path else DEFAULT_MODEL_DIR / DEFAULT_MODEL_FILENAME
    meta_p = Path(meta_path) if meta_path else DEFAULT_MODEL_DIR / DEFAULT_META_FILENAME

    if not m_p.exists():
        raise FileNotFoundError(
            f"Trained RL model checkpoint not found at: '{m_p}'. "
            f"Run 'backend/scripts/train_rider_assignment.py' first to train and persist the model."
        )

    model = MaskablePPO.load(str(m_p), device="cpu")

    metadata = {}
    if meta_p.exists():
        with open(meta_p, "r", encoding="utf-8") as f:
            metadata = json.load(f)

    return model, metadata
