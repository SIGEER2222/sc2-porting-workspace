"""On-policy rollout collection for ``CmreRLEnv``.

Provides :func:`collect_rollout`, which runs the policy in the environment
for ``n_steps`` (handling auto-reset on termination) and returns a filled
:class:`RolloutBuffer` ready for :class:`PPOTrainer`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

import numpy as np

try:
    import torch
    from torch.distributions import Categorical
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError("PyTorch is required for rollout collection") from exc

from .action_space import ACTION_NAMES, NUM_ACTIONS
from .observation import rl_feature_count
from .ppo import RolloutBuffer

ActionBuilder = Callable[[str, Mapping[str, Any] | None], Mapping[str, Any]]


def collect_rollout(
    env: Any,
    policy: Any,
    n_steps: int,
    *,
    deterministic: bool = False,
    device: str = "cpu",
    action_builder: ActionBuilder | None = None,
    auto_reset_on_terminal: bool = True,
) -> RolloutBuffer:
    """Run ``n_steps`` of interaction and return a populated buffer.

    The environment is auto-reset whenever a terminal step is reached unless
    ``auto_reset_on_terminal`` is false, in which case collection stops at the
    terminal transition.
    The returned buffer's GAE ``last_value`` defaults to 0 (correct when
    the rollout ends on a terminal step); callers can override via
    :meth:`RolloutBuffer.compute_gae` if needed.

    Parameters
    ----------
    env
        Object exposing ``reset()``, ``step(action_id)``, ``action_mask()``,
        ``action_dim``, ``observation_dim`` (i.e. ``CmreRLEnv``).
    policy
        Callable producing ``(logits, value)`` from an obs tensor + mask.
    n_steps
        Number of environment steps to collect.
    deterministic
        If ``True``, pick the greedy (argmax) action among legal ones;
        otherwise sample from the masked Categorical.
    device
        Torch device for the policy forward pass.
    action_builder
        Optional callback that grounds ``(action_name, last_observation)`` into
        canonical action arguments before calling ``env.step``.
    auto_reset_on_terminal
        Keep the default training behavior, or stop a live evaluation at the
        first mission terminal event.
    """

    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")

    obs_dim = int(getattr(env, "observation_dim", rl_feature_count()))
    action_dim = int(getattr(env, "action_dim", NUM_ACTIONS))
    mask_dim = action_dim

    buffer = RolloutBuffer(
        capacity=n_steps,
        obs_dim=obs_dim,
        action_dim=1,
        mask_dim=mask_dim,
    )

    obs = env.reset()
    if isinstance(obs, np.ndarray) and obs.ndim == 1:
        obs_vec = obs
    else:
        obs_vec = np.asarray(obs, dtype=np.float32).flatten()

    for _ in range(n_steps):
        mask = env.action_mask()
        # Ground-feasibility masking: an action the grounder cannot turn into a
        # concrete order (no caster owned, no morph source, no visible enemy,
        # ...) is not a real choice. Masking it here keeps the policy from
        # spending probability mass on structurally impossible actions AND
        # prevents ActionGroundingError from aborting the whole rollout.
        grounded_args: dict[int, Any] = {}
        if action_builder is not None:
            raw_observation = getattr(env, "last_observation", None)
            feasible = np.asarray(mask, dtype=bool).copy()
            for idx in range(min(len(feasible), len(ACTION_NAMES))):
                if not feasible[idx]:
                    continue
                try:
                    grounded_args[idx] = action_builder(
                        ACTION_NAMES[idx], raw_observation
                    )
                except Exception:  # noqa: BLE001 - ungroundable == unavailable
                    feasible[idx] = False
            if feasible.any():
                mask = feasible
        obs_t = torch.as_tensor(obs_vec, dtype=torch.float32, device=device).unsqueeze(0)
        mask_t = torch.as_tensor(mask, dtype=torch.bool, device=device).unsqueeze(0)
        with torch.no_grad():
            logits, value = policy(obs_t, mask_t)
        # Replace -inf from masking with very negative finite for softmax stability
        finite_logits = torch.where(
            torch.isfinite(logits), logits, torch.full_like(logits, -1e9)
        )
        dist = Categorical(logits=finite_logits)
        if deterministic:
            action_idx = int(torch.argmax(finite_logits, dim=-1).item())
        else:
            action_idx = int(dist.sample().item())
        logprob = float(dist.log_prob(torch.tensor(action_idx, device=device)).item())
        value_scalar = float(value.flatten()[0].item())

        action_name = ACTION_NAMES[action_idx] if action_idx < len(ACTION_NAMES) else str(action_idx)
        if action_builder is None:
            next_obs, reward, terminated, info = env.step(action_name)
        else:
            args = grounded_args.get(action_idx)
            if args is None:
                # Every legal action was ungroundable; fall back to the raw
                # dispatch so the episode still advances instead of hanging.
                try:
                    args = action_builder(
                        action_name, getattr(env, "last_observation", None)
                    )
                except Exception:  # noqa: BLE001
                    args = {}
            next_obs, reward, terminated, info = env.step(action_name, args)
        buffer.store(
            obs=obs_vec,
            action=np.array([action_idx], dtype=np.int64),
            logprob=np.array(logprob, dtype=np.float32),
            value=np.array(value_scalar, dtype=np.float32),
            reward=float(reward),
            done=bool(terminated),
            mask=np.asarray(mask, dtype=bool),
        )

        if bool(terminated):
            if not auto_reset_on_terminal:
                break
            obs = env.reset()
        else:
            obs = next_obs
        if isinstance(obs, np.ndarray) and obs.ndim == 1:
            obs_vec = obs
        else:
            obs_vec = np.asarray(obs, dtype=np.float32).flatten()

    return buffer


__all__ = ["ActionBuilder", "collect_rollout"]
