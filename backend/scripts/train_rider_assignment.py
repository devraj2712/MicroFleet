import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.intelligence.rl.train import train_rl_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MicroFleet-RL-Trainer")


def main():
    parser = argparse.ArgumentParser(description="Train MicroFleet MaskablePPO Rider Assignment Policy")
    parser.add_argument("--timesteps", type=int, default=15000, help="Total training timesteps (default: 15000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible training (default: 42)")
    parser.add_argument("--model-dir", type=str, default="backend/models", help="Directory to save model checkpoint")
    parser.add_argument("--report-dir", type=str, default="backend/reports", help="Directory to save evaluation report")

    args = parser.parse_args()

    print(f"=== MICROFLEET RL TRAINING: MaskablePPO Rider Assignment ===")
    print(f"Configuration: timesteps={args.timesteps}, seed={args.seed}, model_dir='{args.model_dir}'")

    model, meta = train_rl_agent(
        total_timesteps=args.timesteps,
        seed=args.seed,
        model_dir=Path(args.model_dir),
        report_dir=Path(args.report_dir),
    )

    print("\n=== TRAINING SUCCESSFUL ===")
    print(f"Model Checkpoint: {args.model_dir}/rider_assignment_maskable_ppo.zip")
    print(f"Metadata File:    {args.model_dir}/rider_assignment_maskable_ppo.meta.json")
    print(f"Training Time:    {meta['training_time_seconds']} seconds")

    eval_res = meta.get("held_out_evaluation", {})
    rl_agent = eval_res.get("rl_agent", {})
    baselines = eval_res.get("baselines", {})

    print("\n=== HELD-OUT SCENARIO EVALUATION RESULTS (20 Scenarios) ===")
    print(f"{'Policy Name':<32} {'Assigned %':<12} {'On-Time %':<12} {'Dist (km)':<12} {'Dur (min)':<12} {'Reward':<10}")
    print("-" * 92)

    print(
        f"{rl_agent.get('policy_name', 'RL_Agent'):<32} "
        f"{rl_agent.get('percentage_batches_assigned', 0.0):<12.1f} "
        f"{rl_agent.get('percentage_on_time', 0.0):<12.1f} "
        f"{rl_agent.get('total_distance_km', 0.0):<12.2f} "
        f"{rl_agent.get('total_duration_min', 0.0):<12.1f} "
        f"{rl_agent.get('average_episode_reward', 0.0):<10.2f}"
    )

    for b_name, b_data in baselines.items():
        print(
            f"{b_name:<32} "
            f"{b_data.get('percentage_batches_assigned', 0.0):<12.1f} "
            f"{b_data.get('percentage_on_time', 0.0):<12.1f} "
            f"{b_data.get('total_distance_km', 0.0):<12.2f} "
            f"{b_data.get('total_duration_min', 0.0):<12.1f} "
            f"{b_data.get('average_episode_reward', 0.0):<10.2f}"
        )


if __name__ == "__main__":
    main()
