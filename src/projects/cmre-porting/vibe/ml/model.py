"""PyTorch shared-trunk, multi-head P2 intent policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

try:
    import torch
    from torch import Tensor, nn
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    raise RuntimeError(
        "PyTorch is required for the selected P2 ML policy; install vibe/ml/requirements.txt"
    ) from exc

from ..ml_policy import ModePrediction
from .encoder import FEATURE_NAMES, FEATURE_SCHEMA, encode_observation, feature_schema_hash
from .schema import HEAD_LABELS, P2Intent


MODEL_SCHEMA = "cmre-ally-intent-pytorch.v2"


class P2AllyPolicyNet(nn.Module):
    """Shared structured encoder with economy/production/tactical/command heads."""

    def __init__(self, hidden_dim: int = 128, seed: int = 7) -> None:
        super().__init__()
        torch.manual_seed(int(seed))
        self.input_dim = len(FEATURE_NAMES)
        self.hidden_dim = max(16, int(hidden_dim))
        self.trunk = nn.Sequential(
            nn.LayerNorm(self.input_dim), nn.Linear(self.input_dim, self.hidden_dim),
            nn.ReLU(), nn.Linear(self.hidden_dim, self.hidden_dim), nn.ReLU(),
        )
        self.heads = nn.ModuleDict({
            head: nn.Linear(self.hidden_dim, len(labels))
            for head, labels in HEAD_LABELS.items()
        })

    def forward(self, features: Tensor) -> dict[str, Tensor]:
        if features.ndim == 1:
            features = features.unsqueeze(0)
        if features.shape[-1] != self.input_dim:
            raise ValueError(f"feature_dim_mismatch:{features.shape[-1]}!={self.input_dim}")
        hidden = self.trunk(features)
        return {head: layer(hidden) for head, layer in self.heads.items()}

    def config(self) -> dict:
        return {
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "heads": {head: list(labels) for head, labels in HEAD_LABELS.items()},
        }

    @staticmethod
    def _observation_version(observation) -> int:
        if isinstance(observation, Mapping):
            mission = dict(observation.get("mission", {}) or {})
            resources = dict(observation.get("resources", {}) or {})
            return int(resources.get("state_version", mission.get("state_version", observation.get("loop", 0))))
        mission = dict(getattr(observation, "mission", {}) or {})
        resources = dict(getattr(observation, "resources", {}) or {})
        return int(resources.get("state_version", mission.get("state_version", getattr(observation, "loop", 0))))

    def predict_intent(
        self,
        observation,
        *,
        requested_mode: str = "follow",
        decision_id: str = "",
        issuer_player_id: int = 2,
        base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
        support_range: float = 14.0,
    ) -> P2Intent:
        if int(issuer_player_id) != 2:
            raise ValueError("p2_model_issuer_must_be_2")
        features = torch.tensor(
            encode_observation(observation, requested_mode, base_region, support_range),
            dtype=torch.float32,
        )
        was_training = self.training
        self.eval()
        with torch.no_grad():
            logits = self(features)
            probabilities = {
                head: torch.softmax(values[0], dim=-1).cpu().tolist()
                for head, values in logits.items()
            }
        if was_training:
            self.train()
        labels = {
            head: HEAD_LABELS[head][max(range(len(values)), key=values.__getitem__)]
            for head, values in probabilities.items()
        }
        probability_map = {
            head: {
                label: float(values[index])
                for index, label in enumerate(HEAD_LABELS[head])
            }
            for head, values in probabilities.items()
        }
        confidence = min(float(max(values)) for values in probabilities.values())
        if not decision_id:
            digest = hashlib.sha256(
                json.dumps([round(value, 6) for value in features.tolist()], separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16]
            decision_id = f"p2-ml-{self._observation_version(observation)}-{digest}"
        return P2Intent(
            schema=MODEL_SCHEMA, decision_id=str(decision_id),
            observation_version=self._observation_version(observation), issuer_player_id=2,
            economy=labels["economy"], production=labels["production"],
            tactical=labels["tactical"], command=labels["command"],
            confidence=max(0.0, min(1.0, confidence)), probabilities=probability_map,
        )

    def predict_mode(self, observation, requested_mode: str = "follow", **kwargs) -> ModePrediction:
        """Compatibility view used by the existing tactical policy consumer."""
        intent = self.predict_intent(observation, requested_mode=requested_mode, **kwargs)
        return ModePrediction(
            label=intent.tactical,
            confidence=intent.probabilities["tactical"][intent.tactical],
            probabilities=intent.probabilities["tactical"],
        )


def save_checkpoint(model: P2AllyPolicyNet, path: str | Path, *, training: Mapping | None = None) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": MODEL_SCHEMA,
        "feature_schema": FEATURE_SCHEMA,
        "feature_schema_hash": feature_schema_hash(),
        "feature_names": list(FEATURE_NAMES),
        "head_labels": {head: list(labels) for head, labels in HEAD_LABELS.items()},
        "config": model.config(),
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "training": dict(training or {}),
    }
    torch.save(payload, destination)
    return destination


def load_checkpoint(path: str | Path, *, device: str = "cpu") -> P2AllyPolicyNet:
    checkpoint_path = Path(path)
    if checkpoint_path.suffix.lower() != ".pt":
        raise ValueError("p2_model_schema_mismatch")
    try:
        payload = torch.load(checkpoint_path, map_location=device, weights_only=True)
    except TypeError:  # Older supported PyTorch versions lack weights_only.
        try:
            payload = torch.load(checkpoint_path, map_location=device)
        except Exception as exc:  # noqa: BLE001 - normalize checkpoint failures
            raise ValueError("p2_model_checkpoint_unreadable") from exc
    except Exception as exc:  # noqa: BLE001 - normalize checkpoint failures
        raise ValueError("p2_model_checkpoint_unreadable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("p2_model_checkpoint_shape_mismatch")
    if payload.get("schema") != MODEL_SCHEMA:
        raise ValueError("p2_model_schema_mismatch")
    if payload.get("feature_schema") != FEATURE_SCHEMA:
        raise ValueError("p2_feature_schema_mismatch")
    if payload.get("feature_schema_hash") != feature_schema_hash():
        raise ValueError("p2_feature_schema_hash_mismatch")
    if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
        raise ValueError("p2_feature_names_mismatch")
    if payload.get("head_labels") != {head: list(labels) for head, labels in HEAD_LABELS.items()}:
        raise ValueError("p2_head_schema_mismatch")
    config = dict(payload.get("config", {}))
    model = P2AllyPolicyNet(hidden_dim=int(config.get("hidden_dim", 128)), seed=1)
    model.load_state_dict(payload["state_dict"], strict=True)
    model.to(device)
    model.eval()
    return model
