from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.intelligence.rl.baselines import (
    LeastLoadedFeasibleRiderPolicy,
    NearestFeasibleRiderPolicy,
    WeightedScoreAssignmentPolicy,
    evaluate_policy_on_scenarios,
)
from backend.app.intelligence.rl.dispatcher import RLDispatchService
from backend.app.intelligence.rl.environment import (
    DEFAULT_MAX_CANDIDATE_RIDERS,
    OBS_DIM,
    RiderAssignmentEnv,
    generate_procedural_scenario,
)
from backend.app.intelligence.rl.train import (
    evaluate_rl_policy_on_scenarios,
    load_trained_model,
    train_rl_agent,
)
from backend.app.main import app
from backend.app.models.entities import Batch, Merchant, Order, OrderStatus, Rider, Route


def seed_test_db(db: Session):
    now = datetime.now(timezone.utc)
    m = Merchant(
        id="M-TEST-1",
        name="Test Bandra Bakery",
        merchant_type="Bakery",
        pickup_latitude=19.0596,
        pickup_longitude=72.8295,
        is_active=True,
        created_at=now,
    )
    db.add(m)

    r1 = Rider(
        id="R-TEST-1",
        display_name="Rider Alpha",
        current_latitude=19.0550,
        current_longitude=72.8350,
        weight_capacity_kg=25.0,
        package_count_capacity=10,
        is_available=True,
        created_at=now,
    )
    r2 = Rider(
        id="R-TEST-2",
        display_name="Rider Beta",
        current_latitude=19.0200,
        current_longitude=72.8420,
        weight_capacity_kg=20.0,
        package_count_capacity=8,
        is_available=True,
        created_at=now,
    )
    db.add_all([r1, r2])

    for i in range(1, 5):
        o = Order(
            id=f"ORD-TEST-{i:02d}",
            merchant_id="M-TEST-1",
            pickup_latitude=19.0596,
            pickup_longitude=72.8295,
            delivery_latitude=19.0680 + (i * 0.005),
            delivery_longitude=72.8385 + (i * 0.005),
            delivery_deadline=now + timedelta(hours=i),
            package_type="PARCEL",
            weight_kg=2.0 * i,
            package_count=1,
            customer_priority="STANDARD",
            merchant_priority=i,
            status=OrderStatus.PENDING.value,
            created_at=now - timedelta(minutes=10 * i),
        )
        db.add(o)
    db.commit()


# --- 1. Environment Tests ---

def test_gym_env_reset_and_step_contracts():
    """Verify Gymnasium reset() and step() contracts, shape, and bounded finite observations."""
    env = RiderAssignmentEnv(max_candidate_riders=5, default_seed=42)
    obs, info = env.reset(seed=42)

    assert isinstance(obs, np.ndarray)
    assert obs.shape == (OBS_DIM,)
    assert obs.dtype == np.float32
    # Strictly check finite and bounded in [-1.0, 1.0]
    assert not np.isnan(obs).any()
    assert not np.isinf(obs).any()
    assert (obs >= -1.0).all() and (obs <= 1.0).all()
    assert "action_mask" in info
    assert len(info["action_mask"]) == 6  # 5 riders + 1 defer

    # Take step
    mask = env.action_masks()
    action = 5 if not any(mask[:5]) else int(np.where(mask)[0][0])
    next_obs, reward, terminated, truncated, step_info = env.step(action)

    assert isinstance(next_obs, np.ndarray)
    assert next_obs.shape == (OBS_DIM,)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert "step_reward_breakdown" in step_info


def test_env_deterministic_scenario_seeds():
    """Verify identical random seeds produce identical initial scenarios and observations."""
    env1 = RiderAssignmentEnv(default_seed=99)
    obs1, _ = env1.reset(seed=99)

    env2 = RiderAssignmentEnv(default_seed=99)
    obs2, _ = env2.reset(seed=99)

    np.testing.assert_array_almost_equal(obs1, obs2)
    assert len(env1.batches) == len(env2.batches)
    assert [b.batch_id for b in env1.batches] == [b.batch_id for b in env2.batches]


def test_env_action_masks_defer_always_legal():
    """Verify action masking: action K (defer) is ALWAYS True, preventing deadlock."""
    env = RiderAssignmentEnv(max_candidate_riders=5)
    env.reset(seed=42)

    for _ in range(len(env.batches)):
        mask = env.action_masks()
        assert bool(mask[env.defer_action]) is True
        env.step(env.defer_action)


def test_env_sequential_workload_and_availability_updates():
    """Verify rider workload, availability time, and coordinates update correctly after assignment."""
    env = RiderAssignmentEnv(max_candidate_riders=3, default_seed=42)
    env.reset(seed=42)

    rider_0 = env.riders[0]
    init_lat, init_lon = rider_0.current_lat, rider_0.current_lon
    init_time = rider_0.available_at
    init_workload = rider_0.assigned_batch_count

    mask = env.action_masks()
    if mask[0]:
        obs, rew, term, trunc, info = env.step(0)
        assert rider_0.assigned_batch_count == init_workload + 1
        assert rider_0.available_at > init_time
        # Position updated to destination of assigned route
        assert (rider_0.current_lat != init_lat) or (rider_0.current_lon != init_lon)
        assert len(rider_0.assigned_batches) == 1


def test_env_deferral_behavior_and_termination():
    """Verify deferral records unassigned batches and episode cleanly terminates."""
    env = RiderAssignmentEnv(max_candidate_riders=3, default_seed=42)
    env.reset(seed=42)
    num_batches = len(env.batches)

    terminated = False
    step_count = 0
    while not terminated:
        obs, rew, terminated, trunc, info = env.step(env.defer_action)
        step_count += 1

    assert step_count == num_batches
    assert terminated is True
    assert env.episode_metrics["total_deferred"] == num_batches
    assert env.episode_metrics["total_assigned"] == 0


# --- 2. Baseline Policies Tests ---

def test_baselines_deterministic_selection():
    """Verify nearest, least-loaded, and weighted baseline policies execute legally."""
    env = RiderAssignmentEnv(max_candidate_riders=3)

    for policy in [
        NearestFeasibleRiderPolicy(),
        LeastLoadedFeasibleRiderPolicy(),
        WeightedScoreAssignmentPolicy(),
    ]:
        env.reset(seed=123)
        terminated = False
        while not terminated:
            action = policy.select_action(env)
            mask = env.action_masks()
            assert bool(mask[action]) is True, f"Policy {policy.name} selected masked-out action {action}"
            obs, rew, terminated, trunc, info = env.step(action)

        assert env.episode_metrics["hard_constraint_violations"] == 0


def test_evaluate_policy_on_scenarios_harness():
    """Verify evaluation harness outputs complete metric dictionary."""
    results = evaluate_policy_on_scenarios(
        NearestFeasibleRiderPolicy(),
        scenario_seeds=[101, 102],
        max_candidate_riders=3,
    )
    assert "policy_name" in results
    assert "percentage_batches_assigned" in results
    assert "percentage_on_time" in results
    assert "hard_constraint_violations" in results
    assert results["hard_constraint_violations"] == 0


# --- 3. Training & Checkpoint Tests ---

def test_rl_training_smoke_and_checkpoint_save_load(tmp_path: Path):
    """Verify MaskablePPO training smoke run and checkpoint persistence."""
    model_dir = tmp_path / "models"
    report_dir = tmp_path / "reports"

    model, meta = train_rl_agent(
        total_timesteps=300,
        seed=42,
        model_dir=model_dir,
        report_dir=report_dir,
    )

    checkpoint_file = model_dir / "rider_assignment_maskable_ppo.zip"
    meta_file = model_dir / "rider_assignment_maskable_ppo.meta.json"
    report_file = report_dir / "dispatch_evaluation_report.json"

    assert checkpoint_file.exists()
    assert meta_file.exists()
    assert report_file.exists()

    # Load back the model
    loaded_model, loaded_meta = load_trained_model(
        model_path=str(checkpoint_file),
        meta_path=str(meta_file),
    )
    assert loaded_model is not None
    assert loaded_meta.get("algorithm") == "MaskablePPO"


def test_missing_checkpoint_raises_filenotfound():
    """Verify clear error when model checkpoint is missing."""
    with pytest.raises(FileNotFoundError) as exc_info:
        load_trained_model(model_path="non_existent_model_checkpoint_xyz.zip")
    assert "Trained RL model checkpoint not found" in str(exc_info.value)


# --- 4. Live API & Read-Only Tests ---

def test_api_dispatch_preview_rl_success_and_read_only(client: TestClient, db_session: Session):
    """Verify POST /api/v1/optimization/dispatch/preview executes RL policy and is strictly read-only."""
    seed_test_db(db_session)

    initial_orders = db_session.query(Order).filter(Order.status == OrderStatus.PENDING.value).all()
    initial_order_ids = [o.id for o in initial_orders]
    assert len(initial_orders) >= 3

    resp = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={
            "policy_choice": "rl",
            "ga_config": {
                "population_size": 15,
                "generations": 8,
                "random_seed": 42,
            },
            "aco_config": {
                "num_ants": 5,
                "max_iterations": 4,
                "random_seed": 42,
                "max_candidate_riders": 2,
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()

    assert data["preview_mode"] is True
    assert "assignments" in data
    assert "unassigned_batches" in data
    assert "rider_workloads" in data
    assert "summary" in data
    assert "baseline_comparisons" in data
    assert "policy_metadata" in data

    # Verify baseline comparisons exist
    b_comp = data["baseline_comparisons"]
    assert "nearest_feasible_rider" in b_comp
    assert "least_loaded_feasible_rider" in b_comp
    assert "weighted_score_assignment" in b_comp

    # Strictly verify read-only: no order status changes, no DB Batch or Route rows
    db_orders_after = db_session.query(Order).filter(Order.id.in_(initial_order_ids)).all()
    for o in db_orders_after:
        assert o.status == OrderStatus.PENDING.value
        assert o.batch_order is None

    assert db_session.query(Batch).count() == 0
    assert db_session.query(Route).count() == 0


def test_api_dispatch_preview_baseline_policies(client: TestClient, db_session: Session):
    """Verify preview dispatch works with explicit baseline selection (nearest, least_loaded, weighted)."""
    seed_test_db(db_session)

    for pol in ["nearest", "least_loaded", "weighted"]:
        resp = client.post(
            "/api/v1/optimization/dispatch/preview",
            json={
                "policy_choice": pol,
                "ga_config": {"population_size": 10, "generations": 5, "random_seed": 42},
                "aco_config": {"num_ants": 4, "max_iterations": 3, "random_seed": 42},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["preview_mode"] is True
        assert len(data["rider_workloads"]) >= 1


def test_api_dispatch_preview_validation_errors(client: TestClient, db_session: Session):
    """Verify HTTP errors for missing orders, non-pending orders, missing riders, and invalid policies."""
    seed_test_db(db_session)

    # 1. Non-existent order -> 404
    resp_404 = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={"order_ids": ["ORD-NON-EXISTENT-XYZ"]},
    )
    assert resp_404.status_code == 404

    # 2. Non-existent rider -> 404
    resp_rider_404 = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={"rider_ids": ["RIDER-NON-EXISTENT-XYZ"]},
    )
    assert resp_rider_404.status_code == 404

    # 3. Non-pending order -> 422
    order = db_session.query(Order).first()
    order.status = OrderStatus.DELIVERED.value
    db_session.commit()

    resp_422 = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={"order_ids": [order.id]},
    )
    assert resp_422.status_code == 422

    # 4. Invalid policy choice -> 422
    resp_pol_422 = client.post(
        "/api/v1/optimization/dispatch/preview",
        json={"policy_choice": "invalid_policy_name"},
    )
    assert resp_pol_422.status_code == 422
