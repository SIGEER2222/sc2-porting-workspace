"""Evaluate BC-pretrained P2AllyAC vs random init on FakeBackend.

Stage 04 runtime evidence generator. Produces a JSON report comparing:
- BC checkpoint metadata (epochs, accuracy)
- Trunk weight transfer verification
- BC heads output parity with original BC model
- 100-step rollout stability (no NaN/Inf, action diversity)
- PPO training compatibility (finite losses)
- BC-pretrained vs random init action distribution

Usage:
    python tools/evaluate_bc_pretrain.py [--output PATH]

Output:
    artifacts/stage-04-bc-pretrain/evaluation-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "src" / "projects" / "cmre-rl-training"
CMRE_PORTING_SRC = REPO_ROOT / "src" / "projects" / "cmre-porting"
CMRE_NEURO_SRC = REPO_ROOT / "src" / "projects" / "cmre-neuro-adapter"

for path in (str(PROJECT_ROOT), str(CMRE_NEURO_SRC), str(CMRE_PORTING_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

import numpy as np
import torch

from cmre_rl_training.action_space import NUM_ACTIONS
from cmre_rl_training.bc_pretrain import evaluate_policy_rollout, load_bc_pretrained_ac
from cmre_rl_training.backends import FakeBackend
from cmre_rl_training.env import CmreRLEnv
from cmre_rl_training.network import P2AllyAC
from cmre_rl_training.observation import rl_feature_count
from cmre_rl_training.ppo import PPOTrainer
from cmre_rl_training.rollout import collect_rollout

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
    / "stage-04-bc-pretrain"
    / "evaluation-report.json"
)


def _checkpoint_metadata(path: Path) -> dict[str, Any]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    training = dict(payload.get("training", {}))
    return {
        "schema": payload.get("schema"),
        "hidden_dim": payload.get("config", {}).get("hidden_dim"),
        "input_dim": payload.get("config", {}).get("input_dim"),
        "epochs": training.get("epochs"),
        "train_accuracy_mean": training.get("train", {}).get("accuracy_mean"),
        "holdout_accuracy_mean": training.get("holdout", {}).get("accuracy_mean"),
        "loss_start": training.get("loss_start"),
        "loss_end": training.get("loss_end"),
        "loss_decreased": training.get("loss_decreased"),
    }


def _trunk_parity_check(bc_checkpoint: Path) -> dict[str, Any]:
    from vibe.ml.model import load_checkpoint

    bc_model = load_checkpoint(bc_checkpoint, device="cpu")
    bc_model.eval()
    ac = load_bc_pretrained_ac(bc_checkpoint, hidden_dim=128, seed=7)
    ac.eval()

    obs = torch.randn(16, rl_feature_count())
    with torch.no_grad():
        bc_hidden = bc_model.trunk(obs)
        ac_hidden = ac.trunk(obs)
        bc_outputs = bc_model(obs)
        ac_outputs = ac.forward_bc(obs)

    trunk_max_diff = float((ac_hidden - bc_hidden).abs().max().item())
    head_max_diffs = {}
    for head in ("economy", "production", "tactical", "command"):
        diff = float((ac_outputs[head] - bc_outputs[head]).abs().max().item())
        head_max_diffs[head] = diff

    return {
        "trunk_max_abs_diff": trunk_max_diff,
        "head_max_abs_diffs": head_max_diffs,
        "trunk_parity": trunk_max_diff < 1e-6,
        "heads_parity": all(d < 1e-6 for d in head_max_diffs.values()),
    }


def _rollout_stability(policy: Any, *, n_steps: int = 100) -> dict[str, Any]:
    env = CmreRLEnv(FakeBackend(max_steps=n_steps + 5), normalize_reward=False)
    env.reset()
    buf = collect_rollout(env, policy, n_steps=n_steps, deterministic=False)

    obs = buf.observations_tensor()
    logprobs = buf.logprobs_tensor()
    actions = buf.actions_tensor().flatten().tolist()
    unique_actions = sorted(set(actions))

    return {
        "n_steps": len(buf),
        "obs_finite": bool(torch.isfinite(obs).all().item()),
        "logprobs_finite": bool(torch.isfinite(logprobs).all().item()),
        "actions_in_range": bool(all(0 <= a < NUM_ACTIONS for a in actions)),
        "unique_actions_count": len(unique_actions),
        "unique_action_indices": unique_actions,
        "action_entropy": float(-sum(
            (actions.count(a) / len(actions)) * np.log(actions.count(a) / len(actions))
            for a in unique_actions
            if actions.count(a) > 0
        )),
    }


def _ppo_training_check(policy: Any, *, n_steps: int = 20) -> dict[str, Any]:
    env = CmreRLEnv(FakeBackend(max_steps=30), normalize_reward=False)
    trainer = PPOTrainer(policy, lr=1e-3, epochs=2, batch_size=8)
    env.reset()
    buf = collect_rollout(env, policy, n_steps=n_steps, deterministic=False)
    metrics = trainer.train(buf)
    return {
        "buffer_size": len(buf),
        "total_loss": metrics["total_loss"],
        "policy_loss": metrics["policy_loss"],
        "value_loss": metrics["value_loss"],
        "entropy": metrics["entropy"],
        "all_finite": bool(all(np.isfinite(v) for v in metrics.values())),
    }


def _action_distribution_compare(bc_checkpoint: Path) -> dict[str, Any]:
    env_factory = lambda: CmreRLEnv(FakeBackend(max_steps=20), normalize_reward=False)
    random_policy = P2AllyAC(hidden_dim=128, seed=7)
    bc_policy = load_bc_pretrained_ac(bc_checkpoint, hidden_dim=128, seed=7)

    random_metrics = evaluate_policy_rollout(
        env_factory, random_policy, n_episodes=10, n_steps=20, deterministic=False
    )
    bc_metrics = evaluate_policy_rollout(
        env_factory, bc_policy, n_episodes=10, n_steps=20, deterministic=False
    )

    return {
        "random_init": {
            "mean_reward": random_metrics["mean_reward"],
            "std_reward": random_metrics["std_reward"],
            "mean_steps": random_metrics["mean_steps"],
            "action_distribution": random_metrics["action_distribution"],
        },
        "bc_pretrained": {
            "mean_reward": bc_metrics["mean_reward"],
            "std_reward": bc_metrics["std_reward"],
            "mean_steps": bc_metrics["mean_steps"],
            "action_distribution": bc_metrics["action_distribution"],
        },
        "note": (
            "FakeBackend reward is action-independent; mean_reward parity is expected. "
            "Action distribution differences arise from different trunk feature "
            "representations feeding the random action_head."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 04 BC pretrain evaluation")
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
    args = parser.parse_args()

    bc_path = Path(args.bc_checkpoint)
    if not bc_path.exists():
        print(f"ERROR: BC checkpoint not found: {bc_path}", file=sys.stderr)
        return 1

    print(f"[1/5] Loading BC checkpoint metadata: {bc_path.name}")
    metadata = _checkpoint_metadata(bc_path)
    print(f"      schema={metadata['schema']}, hidden_dim={metadata['hidden_dim']}, "
          f"holdout_acc={metadata['holdout_accuracy_mean']:.4f}")

    print("[2/5] Verifying trunk + BC heads parity")
    parity = _trunk_parity_check(bc_path)
    print(f"      trunk_max_diff={parity['trunk_max_abs_diff']:.2e}, "
          f"heads_parity={parity['heads_parity']}")

    print("[3/5] BC-pretrained 100-step rollout stability")
    bc_policy = load_bc_pretrained_ac(bc_path, hidden_dim=128, seed=7)
    stability = _rollout_stability(bc_policy, n_steps=100)
    print(f"      obs_finite={stability['obs_finite']}, "
          f"unique_actions={stability['unique_actions_count']}, "
          f"entropy={stability['action_entropy']:.3f}")

    print("[4/5] PPO training compatibility on BC-pretrained policy")
    bc_policy2 = load_bc_pretrained_ac(bc_path, hidden_dim=128, seed=7)
    ppo_check = _ppo_training_check(bc_policy2, n_steps=20)
    print(f"      total_loss={ppo_check['total_loss']:.4f}, "
          f"all_finite={ppo_check['all_finite']}")

    print("[5/5] BC-pretrained vs random init action distribution")
    comparison = _action_distribution_compare(bc_path)
    print(f"      random_mean_reward={comparison['random_init']['mean_reward']:.3f}, "
          f"bc_mean_reward={comparison['bc_pretrained']['mean_reward']:.3f}")

    report = {
        "stage": "04-bc-pretrain",
        "bc_checkpoint": str(bc_path.relative_to(REPO_ROOT)),
        "metadata": metadata,
        "trunk_heads_parity": parity,
        "rollout_stability_100_steps": stability,
        "ppo_training_compatibility": ppo_check,
        "bc_vs_random_comparison": comparison,
        "all_gates_pass": bool(
            parity["trunk_parity"]
            and parity["heads_parity"]
            and stability["obs_finite"]
            and stability["logprobs_finite"]
            and ppo_check["all_finite"]
        ),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved: {output_path}")
    print(f"All gates pass: {report['all_gates_pass']}")
    return 0 if report["all_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
