"""BC pretrain checkpoint loading and policy evaluation utilities.

Stage 04 bridges the imitation-learning pipeline (``vibe.ml.training``) and the
RL pipeline (``cmre_rl_training``). The BC checkpoint stores trunk + 4 BC heads
trained on P2 intent data; we load them into :class:`P2AllyAC` so the shared
trunk serves as a warm-started feature extractor for PPO, while the RL
``action_head`` and ``value_head`` remain randomly initialized for on-policy
training.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

try:
    import torch
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError("PyTorch is required for bc_pretrain") from exc

from .action_space import NUM_ACTIONS
from .network import P2AllyAC, load_bc_checkpoint_into_ac
from .rollout import collect_rollout


def load_bc_pretrained_ac(
    bc_checkpoint_path: str | Path,
    *,
    hidden_dim: int = 128,
    seed: int = 7,
    num_actions: int = NUM_ACTIONS,
) -> P2AllyAC:
    """Create a :class:`P2AllyAC` warm-started from a BC checkpoint.

    Parameters
    ----------
    bc_checkpoint_path
        Path to a ``.pt`` file produced by :func:`vibe.ml.model.save_checkpoint`.
    hidden_dim
        Must match the BC checkpoint's ``hidden_dim``; otherwise
        :func:`load_bc_checkpoint_into_ac` raises ``ValueError``.
    seed
        Seed for the AC policy's randomly-initialized ``action_head`` and
        ``value_head``. The trunk and BC heads are overwritten by the BC
        checkpoint, so this seed only affects the RL heads.
    num_actions
        Size of the RL action space (defaults to 19 basic actions).

    Returns
    -------
    P2AllyAC
        Policy with trunk + 4 BC heads loaded from BC checkpoint, and
        action/value heads at random initialization.
    """

    ac = P2AllyAC(hidden_dim=hidden_dim, seed=seed, num_actions=num_actions)
    load_bc_checkpoint_into_ac(ac, bc_checkpoint_path)
    ac.eval()
    return ac


def evaluate_policy_rollout(
    env_factory: Callable[[], Any],
    policy: Any,
    *,
    n_episodes: int = 10,
    n_steps: int = 20,
    deterministic: bool = False,
    device: str = "cpu",
) -> dict[str, Any]:
    """Run ``n_episodes`` rollouts and aggregate reward / step / action metrics.

    Parameters
    ----------
    env_factory
        Zero-arg callable returning a fresh env instance (with ``reset()``,
        ``step()``, ``action_mask()``). A fresh env is created per episode so
        episodes are independent.
    policy
        Callable producing ``(logits, value)`` from obs + mask tensors.
    n_episodes
        Number of independent episodes to run.
    n_steps
        Max steps per episode. Episodes may terminate earlier if the env
        signals ``terminated``.
    deterministic
        If ``True``, pick argmax action; otherwise sample.
    device
        Torch device for the policy forward pass.

    Returns
    -------
    dict
        Aggregated metrics:
        - ``mean_reward``: mean total episode reward
        - ``std_reward``: std of total episode rewards
        - ``mean_steps``: mean steps actually executed per episode
        - ``total_episodes``: number of episodes run
        - ``action_distribution``: ``{action_name: count}`` across all steps
    """

    if n_episodes < 1:
        raise ValueError("n_episodes must be >= 1")
    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")

    from .action_space import ACTION_NAMES

    episode_rewards: list[float] = []
    episode_steps: list[int] = []
    action_counts: Counter[str] = Counter()

    policy.eval()
    for _ in range(n_episodes):
        env = env_factory()
        obs = env.reset()
        if isinstance(obs, np.ndarray) and obs.ndim == 1:
            obs_vec = obs
        else:
            obs_vec = np.asarray(obs, dtype=np.float32).flatten()

        total_reward = 0.0
        steps_run = 0
        for step in range(n_steps):
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

        episode_rewards.append(total_reward)
        episode_steps.append(steps_run)

    rewards_arr = np.array(episode_rewards, dtype=np.float64)
    steps_arr = np.array(episode_steps, dtype=np.float64)
    return {
        "mean_reward": float(rewards_arr.mean()),
        "std_reward": float(rewards_arr.std()),
        "mean_steps": float(steps_arr.mean()),
        "total_episodes": int(n_episodes),
        "action_distribution": dict(action_counts),
    }


__all__ = ["load_bc_pretrained_ac", "evaluate_policy_rollout"]
