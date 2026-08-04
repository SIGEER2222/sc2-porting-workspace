"""RolloutBuffer + GAE + PPOTrainer for on-policy RL on ``CmreRLEnv``.

The :class:`RolloutBuffer` stores per-step transitions and computes
Generalized Advantage Estimation (GAE-λ). :class:`PPOTrainer` consumes a
filled buffer and runs clipped-surrogate updates for ``epochs`` minibatch
passes, with a value-loss term and an entropy bonus.

This is a minimal, dependency-light PPO implementation suitable for the
deterministic ``SimulatorRlBackend``; it does not implement off-policy
correction, RNN hidden state, or distributed collection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    import torch
    from torch import Tensor
    from torch.distributions import Categorical
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError(
        "PyTorch is required for PPOTrainer; install vibe/ml/requirements.txt"
    ) from exc


@dataclass
class _Step:
    obs: np.ndarray
    action: np.ndarray
    logprob: np.ndarray
    value: np.ndarray
    reward: float
    done: bool
    mask: np.ndarray


class RolloutBuffer:
    """Fixed-capacity on-policy transition store with GAE-λ computation."""

    def __init__(
        self,
        *,
        capacity: int,
        obs_dim: int,
        action_dim: int = 1,
        mask_dim: int | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = int(capacity)
        self.obs_dim = int(obs_dim)
        self.action_dim = int(action_dim)
        self.mask_dim = int(mask_dim) if mask_dim is not None else 0
        self._steps: list[_Step] = []

    # -- Collection ---------------------------------------------------------

    def store(
        self,
        *,
        obs: np.ndarray,
        action: np.ndarray,
        logprob: np.ndarray,
        value: np.ndarray,
        reward: float,
        done: bool,
        mask: np.ndarray | None = None,
    ) -> None:
        if len(self._steps) >= self.capacity:
            raise RuntimeError("rollout_buffer_overflow")
        self._steps.append(
            _Step(
                obs=np.asarray(obs, dtype=np.float32),
                action=np.asarray(action, dtype=np.int64),
                logprob=np.asarray(logprob, dtype=np.float32),
                value=np.asarray(value, dtype=np.float32),
                reward=float(reward),
                done=bool(done),
                mask=(np.asarray(mask, dtype=bool) if mask is not None else None),
            )
        )

    def clear(self) -> None:
        self._steps.clear()

    def __len__(self) -> int:
        return len(self._steps)

    # -- GAE ----------------------------------------------------------------

    def compute_gae(
        self,
        *,
        gamma: float = 0.99,
        lam: float = 0.95,
        normalize: bool = True,
        last_value: float = 0.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute GAE-λ advantages and discounted returns.

        Parameters
        ----------
        gamma
            Discount factor.
        lam
            GAE lambda (0 = TD, 1 = Monte-Carlo).
        normalize
            If ``True`` (default), returns advantages with zero mean and
            unit variance. Returns are NOT normalized.
        last_value
            Bootstrap value V(s_T) for the truncated final step. Defaults to
            0.0, which is correct when the last step is terminal.
        """

        n = len(self._steps)
        if n == 0:
            return (
                np.zeros(0, dtype=np.float32),
                np.zeros(0, dtype=np.float32),
            )
        rewards = np.array([s.reward for s in self._steps], dtype=np.float64)
        values = np.array([float(s.value.flatten()[0]) for s in self._steps], dtype=np.float64)
        dones = np.array([s.done for s in self._steps], dtype=np.float64)

        advantages = np.zeros(n, dtype=np.float64)
        last_gae = 0.0
        for t in reversed(range(n)):
            if t == n - 1:
                next_value = float(last_value)
            else:
                next_value = values[t + 1]
            delta = rewards[t] + gamma * next_value * (1.0 - dones[t]) - values[t]
            last_gae = delta + gamma * lam * (1.0 - dones[t]) * last_gae
            advantages[t] = last_gae
        returns = advantages + values

        if normalize and n > 1:
            adv_mean = float(advantages.mean())
            adv_std = float(advantages.std())
            if adv_std > 1e-8:
                advantages = (advantages - adv_mean) / adv_std

        return advantages.astype(np.float32), returns.astype(np.float32)

    # -- Batched tensor access ----------------------------------------------

    def observations_tensor(self) -> "Tensor":
        if not self._steps:
            return torch.zeros(0, self.obs_dim)
        return torch.as_tensor(
            np.stack([s.obs for s in self._steps]), dtype=torch.float32
        )

    def actions_tensor(self) -> "Tensor":
        if not self._steps:
            return torch.zeros(0, self.action_dim, dtype=torch.long)
        actions = np.stack([s.action.flatten() for s in self._steps])
        return torch.as_tensor(actions, dtype=torch.long)

    def masks_tensor(self) -> "Tensor | None":
        if not self._steps or self._steps[0].mask is None:
            return None
        masks = np.stack([s.mask for s in self._steps])
        return torch.as_tensor(masks, dtype=torch.bool)

    def logprobs_tensor(self) -> "Tensor":
        if not self._steps:
            return torch.zeros(0, dtype=torch.float32)
        return torch.as_tensor(
            np.array([float(s.logprob.flatten()[0]) for s in self._steps]),
            dtype=torch.float32,
        )


class PPOTrainer:
    """Clipped PPO trainer operating on a :class:`RolloutBuffer`."""

    def __init__(
        self,
        policy: Any,
        *,
        lr: float = 3e-4,
        clip: float = 0.2,
        gamma: float = 0.99,
        lam: float = 0.95,
        epochs: int = 4,
        batch_size: int = 64,
        ent_coef: float = 0.01,
        vf_coef: float = 0.5,
        max_grad_norm: float = 0.5,
        normalize_advantages: bool = True,
    ) -> None:
        self.policy = policy
        self.lr = float(lr)
        self.clip = float(clip)
        self.gamma = float(gamma)
        self.lam = float(lam)
        self.epochs = int(epochs)
        self.batch_size = int(batch_size)
        self.ent_coef = float(ent_coef)
        self.vf_coef = float(vf_coef)
        self.max_grad_norm = float(max_grad_norm)
        self.normalize_advantages = bool(normalize_advantages)
        self._optimizer = torch.optim.Adam(policy.parameters(), lr=self.lr)

    def train(self, buffer: RolloutBuffer) -> dict[str, float]:
        """Run ``epochs`` minibatch updates over the buffer.

        Returns a metrics dict with the last minibatch's loss components.
        """

        n = len(buffer)
        if n == 0:
            return {"total_loss": 0.0, "policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}

        advantages, returns = buffer.compute_gae(
            gamma=self.gamma,
            lam=self.lam,
            normalize=self.normalize_advantages,
        )
        obs = buffer.observations_tensor()
        actions = buffer.actions_tensor()
        old_logprobs = buffer.logprobs_tensor()
        masks = buffer.masks_tensor()
        adv_t = torch.as_tensor(advantages, dtype=torch.float32)
        ret_t = torch.as_tensor(returns, dtype=torch.float32)

        self.policy.train()
        last_metrics = {"total_loss": 0.0, "policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}
        batch_size = max(1, min(self.batch_size, n))

        for _ in range(self.epochs):
            perm = torch.randperm(n)
            for start in range(0, n, batch_size):
                idx = perm[start : start + batch_size]
                batch_obs = obs[idx]
                batch_act = actions[idx]
                batch_old_lp = old_logprobs[idx]
                batch_adv = adv_t[idx]
                batch_ret = ret_t[idx]
                batch_mask = masks[idx] if masks is not None else None

                logits, value = self.policy(batch_obs, batch_mask)
                # Replace -inf logits with large finite negative for stable softmax
                # (already excluded from sampling by mask, but Categorical still
                # needs finite numbers; masked_fill handles it).
                logits = torch.where(
                    torch.isfinite(logits), logits, torch.full_like(logits, -1e9)
                )
                dist = Categorical(logits=logits)
                new_logprobs = dist.log_prob(batch_act)
                entropy = dist.entropy().mean()

                # Clipped surrogate policy loss
                ratio = torch.exp(new_logprobs - batch_old_lp)
                surr1 = ratio * batch_adv
                surr2 = torch.clamp(ratio, 1.0 - self.clip, 1.0 + self.clip) * batch_adv
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss (MSE)
                value_loss = torch.nn.functional.mse_loss(value.flatten(), batch_ret)

                total_loss = (
                    policy_loss
                    + self.vf_coef * value_loss
                    - self.ent_coef * entropy
                )

                self._optimizer.zero_grad()
                total_loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    self.policy.parameters(), self.max_grad_norm
                )
                self._optimizer.step()

                last_metrics = {
                    "total_loss": float(total_loss.item()),
                    "policy_loss": float(policy_loss.item()),
                    "value_loss": float(value_loss.item()),
                    "entropy": float(entropy.item()),
                }
        return last_metrics


__all__ = ["RolloutBuffer", "PPOTrainer"]
