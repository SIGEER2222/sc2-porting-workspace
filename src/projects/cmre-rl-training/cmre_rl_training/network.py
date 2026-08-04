"""P2AllyAC: actor-critic policy network reusing the BC pretrained trunk.

Subclasses :class:`vibe.ml.model.P2AllyPolicyNet` so the shared trunk and 4 BC
heads (economy/production/tactical/command) can be warm-started from a BC
checkpoint (Stage 04). On top of the trunk we add:

- ``action_head``: ``Linear(hidden_dim, NUM_ACTIONS)`` producing masked logits
  over the 19 basic RL actions.
- ``value_head``: ``Linear(hidden_dim, 1)`` producing the state-value estimate.

The :meth:`forward` signature differs from the BC parent: it returns a
``(logits, value)`` tuple suitable for PPO. The BC forward path is preserved
via :meth:`forward_bc` for inspection / Stage 04 BC loading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:
    import torch
    from torch import Tensor, nn
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError(
        "PyTorch is required for P2AllyAC; install vibe/ml/requirements.txt"
    ) from exc

from vibe.ml.model import MODEL_SCHEMA, P2AllyPolicyNet, load_checkpoint

from .action_space import NUM_ACTIONS

RL_CHECKPOINT_SCHEMA = "cmre-rl-ac.v1"


class P2AllyAC(P2AllyPolicyNet):
    """Actor-critic policy with shared trunk + BC heads + RL action/value heads."""

    def __init__(
        self,
        hidden_dim: int = 128,
        seed: int = 7,
        num_actions: int = NUM_ACTIONS,
    ) -> None:
        super().__init__(hidden_dim=hidden_dim, seed=seed)
        self.num_actions = int(num_actions)
        self.action_head = nn.Linear(self.hidden_dim, self.num_actions)
        self.value_head = nn.Linear(self.hidden_dim, 1)

    # -- Actor-critic forward ------------------------------------------------

    def forward(self, obs: Tensor, mask: Tensor | None = None) -> tuple[Tensor, Tensor]:
        """Return ``(logits[B, num_actions], value[B, 1])``.

        If ``mask`` is provided, illegal logits are set to ``-inf`` so that
        downstream ``Categorical`` distributions assign zero probability to
        illegal actions.
        """

        if obs.ndim == 1:
            obs = obs.unsqueeze(0)
        if obs.shape[-1] != self.input_dim:
            raise ValueError(
                f"ac_feature_dim_mismatch:{obs.shape[-1]}!={self.input_dim}"
            )
        hidden = self.trunk(obs.float())
        logits = self.action_head(hidden)
        if mask is not None:
            if mask.ndim == 1:
                mask = mask.unsqueeze(0)
            mask_b = mask.to(dtype=torch.bool, device=logits.device)
            logits = logits.masked_fill(~mask_b, float("-inf"))
        value = self.value_head(hidden)
        return logits, value

    def forward_bc(self, features: Tensor) -> dict[str, Tensor]:
        """Run the original BC head forward (kept for Stage 04 BC inspection)."""

        return super().forward(features)

    # -- Checkpoint helpers --------------------------------------------------

    def config(self) -> dict[str, Any]:
        bc_config = super().config()
        bc_config["num_actions"] = self.num_actions
        return bc_config


def load_bc_checkpoint_into_ac(ac: P2AllyAC, path: str | Path) -> P2AllyAC:
    """Warm-start ``ac.trunk`` + ``ac.heads`` from a BC checkpoint.

    Only the trunk and 4 BC heads are copied. ``action_head`` and ``value_head``
    keep their current (random or RL-trained) initialization.

    Raises
    ------
    ValueError
        If the BC checkpoint's ``hidden_dim`` does not match the AC policy.
    """

    bc = load_checkpoint(path, device="cpu")
    if int(bc.hidden_dim) != int(ac.hidden_dim):
        raise ValueError(
            f"bc_hidden_dim_mismatch:{bc.hidden_dim}!={ac.hidden_dim}"
        )
    ac.trunk.load_state_dict(bc.trunk.state_dict())
    ac.heads.load_state_dict(bc.heads.state_dict())
    return ac


def save_rl_checkpoint(
    policy: P2AllyAC,
    path: str | Path,
    *,
    training: Mapping[str, Any] | None = None,
) -> Path:
    """Save a full RL checkpoint (trunk + BC heads + action/value heads)."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": RL_CHECKPOINT_SCHEMA,
        "policy_config": {
            "hidden_dim": int(policy.hidden_dim),
            "seed": int(policy._seed) if hasattr(policy, "_seed") else 7,
            "num_actions": int(policy.num_actions),
        },
        "num_actions": int(policy.num_actions),
        "input_dim": int(policy.input_dim),
        "state_dict": {
            key: value.detach().cpu() for key, value in policy.state_dict().items()
        },
        "training": dict(training or {}),
    }
    torch.save(payload, destination)
    return destination


def load_rl_checkpoint(
    path: str | Path,
    *,
    device: str = "cpu",
) -> P2AllyAC:
    """Load an RL checkpoint produced by :func:`save_rl_checkpoint`."""

    checkpoint_path = Path(path)
    try:
        payload = torch.load(checkpoint_path, map_location=device, weights_only=False)
    except TypeError:  # older PyTorch without weights_only
        payload = torch.load(checkpoint_path, map_location=device)
    if not isinstance(payload, Mapping):
        raise ValueError("rl_checkpoint_shape_mismatch")
    if payload.get("schema") != RL_CHECKPOINT_SCHEMA:
        raise ValueError("rl_checkpoint_schema_mismatch")
    config = dict(payload.get("policy_config", {}))
    policy = P2AllyAC(
        hidden_dim=int(config.get("hidden_dim", 128)),
        seed=int(config.get("seed", 7)),
        num_actions=int(config.get("num_actions", NUM_ACTIONS)),
    )
    policy.load_state_dict(payload["state_dict"], strict=True)
    policy.to(device)
    policy.eval()
    return policy


__all__ = [
    "P2AllyAC",
    "RL_CHECKPOINT_SCHEMA",
    "load_bc_checkpoint_into_ac",
    "save_rl_checkpoint",
    "load_rl_checkpoint",
]
