"""Shared-policy PPO training across a registry of map environments.

The trainer intentionally keeps map orchestration outside the environment and
policy implementations. Each map gets a fresh environment, a deterministic
profile, and an action grounder, while one actor-critic and one optimizer are
updated across all maps in the configured order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from .action_grounding import ActionGrounder
from .action_metrics import aggregate_action_summaries, summarize_rollout_actions
from .action_space import NUM_ACTIONS
from .bc_pretrain import load_bc_checkpoint_into_ac
from .map_aware import (
    MapAwareEnv,
    MapAwareP2AllyAC,
    save_map_aware_checkpoint,
)
from .map_profiles import MapProfile, MapProfileRegistry, map_context_schema_hash
from .ppo import PPOTrainer
from .rollout import collect_rollout


EnvFactory = Callable[[], Any]


@dataclass(frozen=True)
class MultiMapTrainingConfig:
    """Bounded PPO settings for one repeatable multi-map training run."""

    map_names: tuple[str, ...] | None = None
    iterations: int = 1
    rollout_steps: int = 32
    hidden_dim: int = 128
    seed: int = 7
    learning_rate: float = 3e-4
    ppo_epochs: int = 4
    batch_size: int = 64
    ent_coef: float = 0.01
    ent_floor: float = 0.0
    device: str = "cpu"
    deterministic_rollout: bool = False
    checkpoint_path: str | Path | None = None
    bc_checkpoint_path: str | Path | None = None

    def __post_init__(self) -> None:
        if self.iterations < 1:
            raise ValueError("iterations must be >= 1")
        if self.rollout_steps < 1:
            raise ValueError("rollout_steps must be >= 1")
        if self.hidden_dim < 1:
            raise ValueError("hidden_dim must be >= 1")
        if self.ppo_epochs < 1:
            raise ValueError("ppo_epochs must be >= 1")
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be > 0")


class MultiMapSelfTrainer:
    """Train one map-conditioned policy over multiple environment factories."""

    def __init__(
        self,
        env_factories: Mapping[str, EnvFactory],
        *,
        config: MultiMapTrainingConfig | None = None,
        registry: MapProfileRegistry | None = None,
        policy: MapAwareP2AllyAC | None = None,
    ) -> None:
        if not env_factories:
            raise ValueError("env_factories must contain at least one map")
        self.config = config or MultiMapTrainingConfig()
        self.registry = registry or MapProfileRegistry()
        self.env_factories = dict(env_factories)
        requested_maps = self.config.map_names
        map_names = tuple(requested_maps or sorted(self.env_factories))
        if not map_names:
            raise ValueError("map_names must contain at least one map")
        missing = [name for name in map_names if name not in self.env_factories]
        if missing:
            raise ValueError(f"missing_env_factory:{','.join(missing)}")
        if len(set(map_names)) != len(map_names):
            raise ValueError("map_names must be unique")
        self.map_names = map_names
        self.profiles: dict[str, MapProfile] = {
            name: self.registry.resolve(name) for name in self.map_names
        }
        context_dim = next(iter(self.profiles.values())).context_dim
        if any(profile.context_dim != context_dim for profile in self.profiles.values()):
            raise ValueError("map_context_dim_mismatch")

        self.policy = policy or MapAwareP2AllyAC(
            hidden_dim=self.config.hidden_dim,
            seed=self.config.seed,
            num_actions=NUM_ACTIONS,
            context_dim=context_dim,
        )
        if int(self.policy.context_dim) != context_dim:
            raise ValueError(
                f"policy_context_dim_mismatch:{self.policy.context_dim}!={context_dim}"
            )
        self.policy.to(self.config.device)
        if self.config.bc_checkpoint_path is not None:
            load_bc_checkpoint_into_ac(self.policy, self.config.bc_checkpoint_path)
        self._grounders = {
            name: ActionGrounder(profile) for name, profile in self.profiles.items()
        }

    def train(self) -> dict[str, Any]:
        """Run PPO over every configured map and return auditable metrics."""

        trainer = PPOTrainer(
            self.policy,
            lr=self.config.learning_rate,
            epochs=self.config.ppo_epochs,
            batch_size=self.config.batch_size,
            ent_coef=self.config.ent_coef,
            ent_floor=self.config.ent_floor,
        )
        map_metrics: dict[str, dict[str, Any]] = {
            name: {
                "profile": _profile_metadata(self.profiles[name]),
                "iterations": [],
                "steps": 0,
                "reward_sum": 0.0,
            }
            for name in self.map_names
        }

        for iteration in range(self.config.iterations):
            for map_name in self.map_names:
                base_env = self.env_factories[map_name]()
                env = MapAwareEnv(base_env, self.profiles[map_name])
                try:
                    buffer = collect_rollout(
                        env,
                        self.policy,
                        n_steps=self.config.rollout_steps,
                        deterministic=self.config.deterministic_rollout,
                        device=self.config.device,
                        action_builder=self._grounders[map_name].ground,
                    )
                    metrics = trainer.train(buffer)
                    rewards = [
                        float(step.reward)
                        for step in getattr(buffer, "_steps", ())
                    ]
                    action_metrics = summarize_rollout_actions(buffer)
                    map_result = map_metrics[map_name]
                    map_result["iterations"].append({
                        "iteration": iteration,
                        "steps": len(buffer),
                        "mean_reward": float(np.mean(rewards)) if rewards else 0.0,
                        "ppo": dict(metrics),
                        "action_metrics": action_metrics,
                    })
                    map_result["steps"] += len(buffer)
                    map_result["reward_sum"] += float(sum(rewards))
                finally:
                    close = getattr(base_env, "close", None)
                    if callable(close):
                        close()

        total_steps = sum(int(item["steps"]) for item in map_metrics.values())
        total_reward = sum(float(item["reward_sum"]) for item in map_metrics.values())
        for item in map_metrics.values():
            item["mean_reward"] = (
                float(item["reward_sum"]) / int(item["steps"])
                if item["steps"]
                else 0.0
            )
            item["action_metrics"] = aggregate_action_summaries([
                iteration["action_metrics"]
                for iteration in item["iterations"]
                if "action_metrics" in iteration
            ])
            del item["reward_sum"]

        report: dict[str, Any] = {
            "schema": "cmre-multi-map-training.v1",
            "context_schema_hash": map_context_schema_hash(),
            "maps": map_metrics,
            "map_order": list(self.map_names),
            "iterations": self.config.iterations,
            "total_steps": total_steps,
            "total_mean_reward": total_reward / total_steps if total_steps else 0.0,
            "policy_config": self.policy.config(),
            "action_metrics": aggregate_action_summaries([
                iteration["action_metrics"]
                for map_result in map_metrics.values()
                for iteration in map_result["iterations"]
                if "action_metrics" in iteration
            ]),
        }
        if self.config.checkpoint_path is not None:
            checkpoint = save_map_aware_checkpoint(
                self.policy,
                self.config.checkpoint_path,
                training={
                    "report_schema": report["schema"],
                    "context_schema_hash": report["context_schema_hash"],
                    "map_order": list(self.map_names),
                    "total_steps": total_steps,
                    "ent_coef": self.config.ent_coef,
                    "ent_floor": self.config.ent_floor,
                },
            )
            report["checkpoint_path"] = str(checkpoint)
        return report


def _profile_metadata(profile: MapProfile) -> dict[str, Any]:
    return {
        "map_id": profile.map_id,
        "family": profile.family,
        "win_condition": profile.win_condition,
        "known": profile.known,
        "night_cycle": profile.night_cycle,
        "context_vector": list(profile.context_vector()),
    }


__all__ = ["MultiMapSelfTrainer", "MultiMapTrainingConfig"]
