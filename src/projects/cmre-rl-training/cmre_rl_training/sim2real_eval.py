"""Sim2Real evaluation: compare policies on a common environment.

Stage 05 evaluation entry point. Supports:
- BC-only policy (trunk + BC heads loaded, RL heads random)
- BC+PPO policy (BC-pretrained + N steps of PPO training)
- random+PPO policy (random init + N steps of PPO training)

The evaluation runs each policy for ``n_episodes`` and aggregates
mean_reward / mean_steps / survival_rate. Results are written to a JSON
report under ``artifacts/stage-05-sim2real-eval/``.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

try:
    import torch
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError("PyTorch is required for sim2real_eval") from exc

from .action_space import ACTION_NAMES, NUM_ACTIONS
from .bc_pretrain import load_bc_pretrained_ac
from .network import P2AllyAC
from .ppo import PPOTrainer
from .rollout import collect_rollout


def _run_episode(
    env: Any,
    policy: Any,
    *,
    n_steps: int,
    deterministic: bool = False,
    device: str = "cpu",
) -> tuple[float, int, dict[str, int]]:
    """Run one episode and return (total_reward, steps_run, action_counts)."""

    obs = env.reset()
    if isinstance(obs, np.ndarray) and obs.ndim == 1:
        obs_vec = obs
    else:
        obs_vec = np.asarray(obs, dtype=np.float32).flatten()

    total_reward = 0.0
    steps_run = 0
    action_counts: Counter[str] = Counter()

    policy.eval()
    for _ in range(n_steps):
        mask = env.action_mask()
        obs_t = torch.as_tensor(obs_vec, dtype=torch.float32, device=device).unsqueeze(0)
        mask_t = torch.as_tensor(mask, dtype=torch.bool, device=device).unsqueeze(0)
        with torch.no_grad():
            logits, _ = policy(obs_t, mask_t)
        finite_logits = torch.where(
            torch.isfinite(logits), logits, torch.full_like(logits, -1e9)
        )
        if deterministic:
            action_idx = int(torch.argmax(finite_logits, dim=-1).item())
        else:
            from torch.distributions import Categorical

            dist = Categorical(logits=finite_logits)
            action_idx = int(dist.sample().item())

        action_name = (
            ACTION_NAMES[action_idx]
            if action_idx < len(ACTION_NAMES)
            else str(action_idx)
        )
        action_counts[action_name] += 1

        next_obs, reward, terminated, _info = env.step(action_name)
        total_reward += float(reward)
        steps_run += 1

        if bool(terminated):
            break
        if isinstance(next_obs, np.ndarray) and next_obs.ndim == 1:
            obs_vec = next_obs
        else:
            obs_vec = np.asarray(next_obs, dtype=np.float32).flatten()

    return total_reward, steps_run, dict(action_counts)


def evaluate_sim2real(
    env_factory: Callable[[], Any],
    policies: Mapping[str, Any],
    *,
    n_episodes: int = 10,
    n_steps: int = 20,
    deterministic: bool = False,
    device: str = "cpu",
) -> dict[str, dict[str, Any]]:
    """Evaluate multiple policies on the same env type.

    Parameters
    ----------
    env_factory
        Zero-arg callable returning a fresh env instance per episode.
    policies
        Mapping from policy name to policy object.
    n_episodes
        Episodes per policy.
    n_steps
        Max steps per episode.
    deterministic
        If ``True``, pick argmax action; otherwise sample.

    Returns
    -------
    dict
        ``{policy_name: {mean_reward, std_reward, mean_steps, survival_rate,
                          total_episodes, action_distribution}}``
    """

    if n_episodes < 1:
        raise ValueError("n_episodes must be >= 1")
    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")

    results: dict[str, dict[str, Any]] = {}
    for name, policy in policies.items():
        episode_rewards: list[float] = []
        episode_steps: list[int] = []
        episode_survivals: list[bool] = []
        action_counter: Counter[str] = Counter()

        for _ in range(n_episodes):
            env = env_factory()
            reward, steps, counts = _run_episode(
                env, policy, n_steps=n_steps, deterministic=deterministic, device=device
            )
            episode_rewards.append(reward)
            episode_steps.append(steps)
            # Survived = reached max steps without termination
            episode_survivals.append(steps >= n_steps)
            for action_name, count in counts.items():
                action_counter[action_name] += count

        rewards_arr = np.array(episode_rewards, dtype=np.float64)
        steps_arr = np.array(episode_steps, dtype=np.float64)
        survivals_arr = np.array(episode_survivals, dtype=np.float64)
        results[name] = {
            "mean_reward": float(rewards_arr.mean()),
            "std_reward": float(rewards_arr.std()),
            "mean_steps": float(steps_arr.mean()),
            "survival_rate": float(survivals_arr.mean()),
            "total_episodes": int(n_episodes),
            "action_distribution": dict(action_counter),
        }
    return results


def train_policy_with_ppo(
    policy: P2AllyAC,
    env_factory: Callable[[], Any],
    *,
    n_train_steps: int = 50,
    rollout_size: int = 10,
    lr: float = 3e-4,
    epochs: int = 2,
    batch_size: int = 8,
) -> dict[str, float]:
    """Run N steps of PPO training on a policy. Returns last-batch metrics."""

    if n_train_steps < 1:
        return {"total_loss": 0.0, "policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}

    trainer = PPOTrainer(
        policy, lr=lr, epochs=epochs, batch_size=batch_size,
    )
    last_metrics = {"total_loss": 0.0, "policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}
    steps_done = 0
    while steps_done < n_train_steps:
        env = env_factory()
        env.reset()
        buf = collect_rollout(env, policy, n_steps=min(rollout_size, n_train_steps - steps_done))
        if len(buf) == 0:
            break
        last_metrics = trainer.train(buf)
        steps_done += len(buf)
    return last_metrics


def generate_sim2real_report(
    *,
    env_factory: Callable[[], Any],
    output_path: str | Path,
    bc_checkpoint_path: str | Path | None = None,
    n_episodes: int = 10,
    n_steps: int = 20,
    ppo_train_steps: int = 50,
    ppo_rollout_size: int = 10,
    deterministic: bool = False,
) -> dict[str, Any]:
    """Generate a full sim2real comparison report.

    Evaluates up to 4 policies:
    - random_init: P2AllyAC with random weights
    - bc_pretrained: P2AllyAC with BC trunk + random RL heads
    - random_ppo: random_init + PPO training
    - bc_ppo: bc_pretrained + PPO training

    If ``bc_checkpoint_path`` is None or missing, BC variants are skipped.
    """

    bc_path = Path(bc_checkpoint_path) if bc_checkpoint_path else None
    has_bc = bc_path is not None and bc_path.exists()

    policies: dict[str, P2AllyAC] = {"random_init": P2AllyAC(hidden_dim=128, seed=7)}

    if has_bc:
        policies["bc_pretrained"] = load_bc_pretrained_ac(
            bc_path, hidden_dim=128, seed=7  # type: ignore[arg-type]
        )

    # Train PPO variants on copies of the base policies
    ppo_metrics: dict[str, dict[str, float]] = {}
    if ppo_train_steps > 0:
        random_ppo = P2AllyAC(hidden_dim=128, seed=7)
        ppo_metrics["random_ppo"] = train_policy_with_ppo(
            random_ppo, env_factory,
            n_train_steps=ppo_train_steps, rollout_size=ppo_rollout_size,
        )
        policies["random_ppo"] = random_ppo

        if has_bc:
            bc_ppo = load_bc_pretrained_ac(
                bc_path, hidden_dim=128, seed=7  # type: ignore[arg-type]
            )
            ppo_metrics["bc_ppo"] = train_policy_with_ppo(
                bc_ppo, env_factory,
                n_train_steps=ppo_train_steps, rollout_size=ppo_rollout_size,
            )
            policies["bc_ppo"] = bc_ppo

    # Evaluate all policies
    results = evaluate_sim2real(
        env_factory, policies,
        n_episodes=n_episodes, n_steps=n_steps, deterministic=deterministic,
    )

    # Determine gate pass: at least bc_pretrained or bc_ppo completes evaluation
    # without NaN/Inf and mean_steps > 0
    all_finite = all(
        np.isfinite(m["mean_reward"]) and np.isfinite(m["mean_steps"]) and m["mean_steps"] > 0
        for m in results.values()
    )

    report = {
        "stage": "05-sim2real-eval",
        "env_type": env_factory().__class__.__name__ if hasattr(env_factory, "__call__") else "unknown",
        "n_episodes": n_episodes,
        "n_steps": n_steps,
        "ppo_train_steps": ppo_train_steps,
        "bc_checkpoint": str(bc_path) if bc_path else None,
        "bc_checkpoint_available": bool(has_bc),
        "ppo_training_metrics": ppo_metrics,
        "policies": results,
        "all_gates_pass": bool(all_finite),
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


__all__ = [
    "evaluate_sim2real",
    "train_policy_with_ppo",
    "generate_sim2real_report",
]
