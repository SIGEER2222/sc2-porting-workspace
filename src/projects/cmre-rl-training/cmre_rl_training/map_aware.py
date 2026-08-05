"""Map-conditioned environment and actor-critic policy.

The original 49-feature encoder remains untouched. Map context is appended by
the environment and consumed by a small contextual projection, so existing BC
checkpoints remain usable as the shared feature trunk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np

try:
    import torch
    from torch import Tensor, nn
except ModuleNotFoundError as exc:  # pragma: no cover
    raise RuntimeError("PyTorch is required for map-aware policy") from exc

from vibe.ml.model import P2AllyPolicyNet

from .action_space import NUM_ACTIONS, compute_action_mask
from .map_profiles import MapProfile
from .network import P2AllyAC


MAP_AWARE_CHECKPOINT_SCHEMA = "cmre-map-aware-ac.v1"


class MapAwareEnv:
    """Append a fixed map profile vector to an existing RL environment."""

    def __init__(self, env: Any, profile: MapProfile) -> None:
        self.env = env
        self.profile = profile
        self._context = np.asarray(profile.context_vector(), dtype=np.float32)

    @property
    def observation_dim(self) -> int:
        return int(self.env.observation_dim) + len(self._context)

    @property
    def action_dim(self) -> int:
        return int(self.env.action_dim)

    @property
    def state_version(self) -> int:
        return int(self.env.state_version)

    @property
    def last_observation(self) -> Mapping[str, Any] | None:
        return getattr(self.env, "last_observation", None)

    def reset(self) -> np.ndarray:
        return self._append(self.env.reset())

    def step(
        self,
        action_id: str,
        args: Mapping[str, Any] | None = None,
    ) -> tuple[np.ndarray, float, bool, dict[str, Any]]:
        if args is None:
            result = self.env.step(action_id)
        else:
            result = self.env.step(action_id, args)
        obs, reward, terminated, info = result
        return self._append(obs), float(reward), bool(terminated), {
            **dict(info),
            "map_id": self.profile.map_id,
            "map_family": self.profile.family,
        }

    def action_mask(self) -> np.ndarray:
        raw = self.last_observation
        if isinstance(raw, Mapping):
            return compute_action_mask(raw, strict_targets=True)
        return np.asarray(self.env.action_mask(), dtype=bool)

    def context_features(self) -> np.ndarray:
        return self._context.copy()

    def _append(self, observation: Any) -> np.ndarray:
        vector = np.asarray(observation, dtype=np.float32).reshape(-1)
        return np.concatenate((vector, self._context)).astype(np.float32, copy=False)


class MapAwareP2AllyAC(P2AllyAC):
    """P2AllyAC with a learned projection for map-family context."""

    def __init__(
        self,
        hidden_dim: int = 128,
        seed: int = 7,
        num_actions: int = NUM_ACTIONS,
        context_dim: int = 8,
    ) -> None:
        super().__init__(hidden_dim=hidden_dim, seed=seed, num_actions=num_actions)
        self.context_dim = int(context_dim)
        if self.context_dim < 1:
            raise ValueError("context_dim must be >= 1")
        self.context_projection = nn.Sequential(
            nn.Linear(self.context_dim, self.hidden_dim),
            nn.Tanh(),
        )

    @property
    def contextual_input_dim(self) -> int:
        return self.input_dim + self.context_dim

    def forward(self, obs: Tensor, mask: Tensor | None = None) -> tuple[Tensor, Tensor]:
        if obs.ndim == 1:
            obs = obs.unsqueeze(0)
        if obs.shape[-1] != self.contextual_input_dim:
            raise ValueError(
                f"map_aware_feature_dim_mismatch:{obs.shape[-1]}!={self.contextual_input_dim}"
            )
        hidden = self.trunk(obs[:, : self.input_dim].float())
        hidden = hidden + self.context_projection(obs[:, self.input_dim :].float())
        logits = self.action_head(hidden)
        if mask is not None:
            if mask.ndim == 1:
                mask = mask.unsqueeze(0)
            logits = logits.masked_fill(~mask.to(dtype=torch.bool, device=logits.device), float("-inf"))
        return logits, self.value_head(hidden)

    def forward_bc(self, features: Tensor) -> dict[str, Tensor]:
        return P2AllyPolicyNet.forward(self, features)

    def config(self) -> dict[str, Any]:
        config = super().config()
        config["context_dim"] = self.context_dim
        config["context_schema"] = "cmre-map-context.v1"
        return config


def save_map_aware_checkpoint(
    policy: MapAwareP2AllyAC,
    path: str | Path,
    *,
    training: Mapping[str, Any] | None = None,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "schema": MAP_AWARE_CHECKPOINT_SCHEMA,
            "policy_config": policy.config(),
            "num_actions": int(policy.num_actions),
            "input_dim": int(policy.input_dim),
            "context_dim": int(policy.context_dim),
            "state_dict": {key: value.detach().cpu() for key, value in policy.state_dict().items()},
            "training": dict(training or {}),
        },
        destination,
    )
    return destination


def load_map_aware_checkpoint(path: str | Path, *, device: str = "cpu") -> MapAwareP2AllyAC:
    payload = torch.load(Path(path), map_location=device, weights_only=False)
    if not isinstance(payload, Mapping) or payload.get("schema") != MAP_AWARE_CHECKPOINT_SCHEMA:
        raise ValueError("map_aware_checkpoint_schema_mismatch")
    config = dict(payload.get("policy_config", {}))
    policy = MapAwareP2AllyAC(
        hidden_dim=int(config.get("hidden_dim", 128)),
        seed=int(config.get("seed", 7)),
        num_actions=int(config.get("num_actions", NUM_ACTIONS)),
        context_dim=int(config.get("context_dim", 8)),
    )
    policy.load_state_dict(payload["state_dict"], strict=True)
    policy.to(device)
    policy.eval()
    return policy


__all__ = [
    "MAP_AWARE_CHECKPOINT_SCHEMA",
    "MapAwareEnv",
    "MapAwareP2AllyAC",
    "load_map_aware_checkpoint",
    "save_map_aware_checkpoint",
]
