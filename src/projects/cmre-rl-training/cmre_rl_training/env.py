"""CmreRLEnv: unified RL environment for coop PvE training.

Wraps any ``RlBackend`` (simulator or real SC2) behind a Gymnasium-style
``reset`` / ``step`` / ``action_mask`` interface. Observation vectors and
action IDs are shared between BC pretraining and RL fine-tuning, so a policy
trained offline can be loaded directly into the RL loop.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

try:
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover
    raise RuntimeError("numpy is required for CmreRLEnv") from exc

from .action_space import NUM_ACTIONS, compute_action_mask
from .backends import RlBackend
from .observation import encode_rl_observation, rl_feature_count
from .reward import RewardNormalizer, RewardTracker

ObservationEncoder = Callable[[Mapping[str, Any]], "np.ndarray"]


class CmreRLEnv:
    """RL environment backed by a pluggable ``RlBackend``.

    Parameters
    ----------
    backend
        Any object implementing the ``RlBackend`` protocol.
    encoder
        Callable mapping raw observation dict to a 1-D float array.
        Defaults to :func:`encode_rl_observation` which delegates to
        ``vibe/ml/encoder`` when available.
    normalize_reward
        If ``True``, rewards are normalized via a running mean/std tracker.
    """

    def __init__(
        self,
        backend: RlBackend,
        *,
        encoder: ObservationEncoder | None = None,
        normalize_reward: bool = True,
    ) -> None:
        self.backend = backend
        self._encoder = encoder or _default_encoder
        self._reward_tracker = RewardTracker()
        self._reward_normalizer = (
            RewardNormalizer() if normalize_reward else None
        )
        self._observation: Mapping[str, Any] | None = None
        self._step_count: int = 0

    # -- Gymnasium-style API ------------------------------------------------

    @property
    def observation_dim(self) -> int:
        return rl_feature_count()

    @property
    def action_dim(self) -> int:
        return NUM_ACTIONS

    @property
    def state_version(self) -> int:
        return self.backend.state_version

    def reset(self) -> "np.ndarray":
        """Reset the environment and return the initial observation vector."""

        raw = self.backend.reset()
        self._observation = raw
        self._reward_tracker.reset()
        self._step_count = 0
        return self._encoder(raw)

    def step(
        self,
        action_id: str,
        args: Mapping[str, Any] | None = None,
    ) -> tuple["np.ndarray", float, bool, dict[str, Any]]:
        """Execute one action and return ``(obs, reward, terminated, info)``."""

        if self._observation is None:
            raise RuntimeError("call reset() before step()")

        raw, terminated, info = self.backend.step(action_id, args or {})
        prev_obs = self._observation
        self._observation = raw
        self._step_count += 1

        reward = self._reward_tracker.compute(raw, terminated, info, prev_obs)
        if self._reward_normalizer is not None:
            reward = self._reward_normalizer.update(reward)

        obs_vector = self._encoder(raw)
        info = {
            **info,
            "step": self._step_count,
            "state_version": self.backend.state_version,
        }
        return obs_vector, float(reward), bool(terminated), info

    def action_mask(self) -> "np.ndarray":
        """Return boolean mask of legal actions for the current observation."""

        if self._observation is None:
            raise RuntimeError("call reset() before action_mask()")
        return compute_action_mask(self._observation)

    @property
    def last_observation(self) -> Mapping[str, Any] | None:
        return self._observation


def _default_encoder(raw: Mapping[str, Any]) -> "np.ndarray":
    vector = encode_rl_observation(raw)
    return np.asarray(vector, dtype=np.float32)


__all__ = ["CmreRLEnv"]
