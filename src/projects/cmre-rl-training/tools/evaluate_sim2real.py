"""Evaluate sim2real: compare BC-pretrained vs random init policies.

Stage 05 runtime evidence generator. Produces a JSON report comparing:
- random_init: P2AllyAC with random weights
- bc_pretrained: P2AllyAC with BC trunk + random RL heads
- random_ppo: random_init + PPO training
- bc_ppo: bc_pretrained + PPO training

Usage:
    python tools/evaluate_sim2real.py [--output PATH] [--ppo-steps N]

Output:
    artifacts/stage-05-sim2real-eval/evaluation-report.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "src" / "projects" / "cmre-rl-training"
CMRE_PORTING_SRC = REPO_ROOT / "src" / "projects" / "cmre-porting"
CMRE_NEURO_SRC = REPO_ROOT / "src" / "projects" / "cmre-neuro-adapter"

for path in (str(PROJECT_ROOT), str(CMRE_NEURO_SRC), str(CMRE_PORTING_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cmre_rl_training.backends import FakeBackend
from cmre_rl_training.env import CmreRLEnv
from cmre_rl_training.sim2real_eval import generate_sim2real_report

BC_CHECKPOINT = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage25-ai-ally-capability-completion"
    / "ml-ally-policy-pytorch-20260804"
    / "ally-intent.pt"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "artifacts"
    / "stage-05-sim2real-eval"
    / "evaluation-report.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 05 sim2real evaluation")
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help="Output JSON report path",
    )
    parser.add_argument(
        "--bc-checkpoint",
        type=str,
        default=str(BC_CHECKPOINT),
        help="BC checkpoint .pt path",
    )
    parser.add_argument(
        "--ppo-steps",
        type=int,
        default=50,
        help="PPO training steps for PPO variants (0 to skip)",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=10,
        help="Evaluation episodes per policy",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=15,
        help="Max steps per episode",
    )
    args = parser.parse_args()

    bc_path = Path(args.bc_checkpoint)
    if not bc_path.exists():
        print(f"WARNING: BC checkpoint not found: {bc_path}", file=sys.stderr)
        print("BC variants will be skipped.", file=sys.stderr)

    print(f"[Stage 05] Sim2Real evaluation")
    print(f"  BC checkpoint: {bc_path.name if bc_path.exists() else 'N/A'}")
    print(f"  PPO train steps: {args.ppo_steps}")
    print(f"  Episodes/policy: {args.episodes}")
    print(f"  Max steps/episode: {args.steps}")
    print()

    env_factory = lambda: CmreRLEnv(FakeBackend(max_steps=args.steps), normalize_reward=False)

    print("[1/1] Generating sim2real comparison report...")
    report = generate_sim2real_report(
        env_factory=env_factory,
        output_path=args.output,
        bc_checkpoint_path=bc_path if bc_path.exists() else None,
        n_episodes=args.episodes,
        n_steps=args.steps,
        ppo_train_steps=args.ppo_steps,
        ppo_rollout_size=min(10, args.steps),
        deterministic=False,
    )

    print(f"\nReport saved: {args.output}")
    print(f"All gates pass: {report['all_gates_pass']}")
    print()
    print("Policy comparison:")
    for name, metrics in report["policies"].items():
        print(f"  {name:20s}: mean_reward={metrics['mean_reward']:.3f}, "
              f"mean_steps={metrics['mean_steps']:.1f}, "
              f"survival_rate={metrics['survival_rate']:.2%}")

    if report.get("ppo_training_metrics"):
        print("\nPPO training metrics (last batch):")
        for name, metrics in report["ppo_training_metrics"].items():
            print(f"  {name:20s}: total_loss={metrics['total_loss']:.4f}")

    return 0 if report["all_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
