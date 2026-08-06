"""PyTorch imitation policy for the P1 native participant.

The dataset builder intentionally keeps an ``unknown`` bucket for replay
events whose selected-unit or ability semantics cannot be recovered from the
captured stream. Unknown events never enter the optimizer. The runtime model
only chooses a high-level action family; map-objective resolution and the
typed SC2 action adapter remain authoritative.
"""

from __future__ import annotations

import bisect
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import torch
from torch import Tensor, nn


MODEL_SCHEMA = "cmre-p1-action-pytorch.v1"
FEATURE_SCHEMA = "cmre-p1-observation.v1"
ACTION_LABELS = ("move", "attack", "gather", "build", "train", "defend", "hold")
FEATURE_NAMES = (
    "own_total", "own_workers", "own_combat", "own_structures",
    "own_health_mean", "own_health_min", "enemy_total", "enemy_combat",
    "enemy_near_base", "enemy_near_own", "enemy_health_mean", "ally_total",
    "minerals", "vespene", "supply_remaining", "loop_progress",
    "own_center_x", "own_center_y", "enemy_strength", "own_strength",
)


def feature_schema_hash() -> str:
    return hashlib.sha256(
        json.dumps(
            {"schema": FEATURE_SCHEMA, "features": FEATURE_NAMES},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _value(item: Mapping | object, *names: str, default=0):
    for name in names:
        if isinstance(item, Mapping) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default


def _unit_id(unit: Mapping) -> str:
    return str(_value(unit, "unit_type_id", "unit_type", default=""))


def _unit_int(unit: Mapping) -> int:
    try:
        return int(_value(unit, "unit_type_int", default=0))
    except (TypeError, ValueError):
        return 0


def _is_worker(unit: Mapping) -> bool:
    return _unit_id(unit).upper() in {"SCV", "PROBE", "DRONE"} or _unit_int(unit) == 4382


def _is_structure(unit: Mapping) -> bool:
    return _unit_id(unit).upper() in {
        "COMMANDCENTER", "ORBITALCOMMAND", "PLANETARYFORTRESS", "SUPPLYDEPOT",
        "REFINERY", "BARRACKS", "FACTORY", "STARPORT", "ENGINEERINGBAY",
        "ARMORY", "BUNKER", "MISSILETURRET", "TECHLAB", "REACTOR",
    } or _unit_int(unit) == 4390


def _hp_ratio(unit: Mapping) -> float:
    current = float(_value(unit, "health", default=0) or 0)
    maximum = float(_value(unit, "max_health", "health_max", default=0) or 0)
    if current > 10000 or maximum > 10000:
        current /= 1024.0
        maximum /= 1024.0
    return max(0.0, min(1.0, current / maximum)) if maximum > 0 else 1.0


def _xy(unit: Mapping) -> tuple[float, float]:
    return float(_value(unit, "x", default=0.0)), float(_value(unit, "y", default=0.0))


def _distance(a: Mapping, b: Mapping) -> float:
    ax, ay = _xy(a)
    bx, by = _xy(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def encode_observation(observation: Mapping | object) -> list[float]:
    own = list(_value(observation, "own_units", default=()) or ())
    enemies = list(_value(observation, "visible_enemies", default=()) or ())
    allies = list(_value(observation, "visible_allies", default=()) or ())
    resources = dict(_value(observation, "resources", default={}) or {})
    workers = [unit for unit in own if _is_worker(unit)]
    structures = [unit for unit in own if _is_structure(unit)]
    combat = [unit for unit in own if unit not in workers and unit not in structures]
    enemy_combat = [unit for unit in enemies if not _is_structure(unit)]
    center = own[0] if own else {"x": 85.0, "y": 94.0}
    base = {"x": 85.0, "y": 94.0}
    own_health = [_hp_ratio(unit) for unit in combat]
    enemy_health = [_hp_ratio(unit) for unit in enemy_combat]
    enemy_near_base = [unit for unit in enemies if _distance(unit, base) <= 14.0]
    enemy_near_own = [unit for unit in enemies if _distance(unit, center) <= 14.0]
    cx, cy = _xy(center)
    minerals = float(resources.get("minerals", 0.0) or 0.0)
    vespene = float(resources.get("vespene", 0.0) or 0.0)
    supply_remaining = float(resources.get("supply_cap", 0.0) or 0.0) - float(
        resources.get("supply_used", 0.0) or 0.0
    )
    loop = float(_value(observation, "loop", default=0) or 0)
    values = [
        min(1.0, len(own) / 80.0), min(1.0, len(workers) / 40.0),
        min(1.0, len(combat) / 40.0), min(1.0, len(structures) / 32.0),
        sum(own_health) / max(1, len(own_health)), min(own_health, default=1.0),
        min(1.0, len(enemies) / 128.0), min(1.0, len(enemy_combat) / 128.0),
        min(1.0, len(enemy_near_base) / 32.0), min(1.0, len(enemy_near_own) / 32.0),
        sum(enemy_health) / max(1, len(enemy_health)), min(1.0, len(allies) / 64.0),
        min(1.0, max(0.0, minerals) / 4000.0), min(1.0, max(0.0, vespene) / 1500.0),
        min(1.0, max(0.0, supply_remaining) / 40.0), min(1.0, loop / 16164.0),
        min(1.0, max(0.0, cx) / 180.0), min(1.0, max(0.0, cy) / 180.0),
        min(1.0, (len(enemy_combat) + 2 * len([u for u in enemies if _is_structure(u)])) / 128.0),
        min(1.0, len(combat) / 40.0),
    ]
    if len(values) != len(FEATURE_NAMES):
        raise AssertionError("p1_feature_schema_drift")
    return [float(value) for value in values]


@dataclass(frozen=True)
class P1ActionPrediction:
    label: str
    confidence: float
    probabilities: dict[str, float]
    decision_id: str = ""
    observation_version: int = 0
    issuer_player_id: int = 1

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": float(self.confidence),
            "probabilities": {key: float(value) for key, value in self.probabilities.items()},
            "decision_id": self.decision_id,
            "observation_version": int(self.observation_version),
            "issuer_player_id": int(self.issuer_player_id),
        }


class P1ActionPolicyNet(nn.Module):
    def __init__(self, hidden_dim: int = 64, seed: int = 7) -> None:
        super().__init__()
        torch.manual_seed(int(seed))
        self.input_dim = len(FEATURE_NAMES)
        self.hidden_dim = max(16, int(hidden_dim))
        self.trunk = nn.Sequential(
            nn.LayerNorm(self.input_dim), nn.Linear(self.input_dim, self.hidden_dim),
            nn.ReLU(), nn.Linear(self.hidden_dim, self.hidden_dim), nn.ReLU(),
        )
        self.head = nn.Linear(self.hidden_dim, len(ACTION_LABELS))
        self.checkpoint_metadata: dict = {}

    def forward(self, features: Tensor) -> Tensor:
        if features.ndim == 1:
            features = features.unsqueeze(0)
        if features.shape[-1] != self.input_dim:
            raise ValueError(f"p1_feature_dim_mismatch:{features.shape[-1]}!={self.input_dim}")
        return self.head(self.trunk(features))

    def predict_action(self, observation, *, decision_id: str = "", player_id: int = 1) -> P1ActionPrediction:
        if int(player_id) != 1:
            raise ValueError("p1_model_issuer_must_be_1")
        features = torch.tensor(encode_observation(observation), dtype=torch.float32)
        was_training = self.training
        self.eval()
        with torch.no_grad():
            probabilities = torch.softmax(self(features)[0], dim=-1).tolist()
        if was_training:
            self.train()
        label_index = max(range(len(probabilities)), key=probabilities.__getitem__)
        version = int(dict(_value(observation, "resources", default={}) or {}).get(
            "state_version", _value(observation, "loop", default=0)
        ))
        return P1ActionPrediction(
            label=ACTION_LABELS[label_index],
            confidence=float(probabilities[label_index]),
            probabilities={label: float(probabilities[index]) for index, label in enumerate(ACTION_LABELS)},
            decision_id=str(decision_id), observation_version=version,
        )


def _manual_observation(frame: Mapping) -> dict:
    units = list(frame.get("units", ()) or ())
    own, allies, enemies = [], [], []
    for unit in units:
        owner = int(unit.get("owner", 0) or 0)
        normalized = {
            "entity_id": int(unit.get("tag", 0) or 0),
            "unit_type_id": str(unit.get("unit_type", unit.get("unit_type_int", ""))),
            "unit_type_int": int(unit.get("unit_type_int", 0) or 0),
            "owner": owner,
            "x": float(unit.get("x", 0.0) or 0.0), "y": float(unit.get("y", 0.0) or 0.0),
            "health": float(unit.get("health", 0.0) or 0.0),
            "max_health": float(unit.get("health_max", 0.0) or 0.0),
        }
        if owner == 1:
            own.append(normalized)
        elif owner == 2:
            allies.append(normalized)
        elif owner in {3, 4, 5, 6, 7}:
            enemies.append(normalized)
    resources = dict(frame.get("p1_resources", {}) or {})
    resources["state_version"] = int(frame.get("loop", 0) or 0)
    return {
        "loop": int(frame.get("loop", 0) or 0), "own_units": own,
        "visible_allies": allies, "visible_enemies": enemies, "resources": resources,
    }


def classify_manual_action(action: Mapping, frame: Mapping) -> str:
    """Return a label only when the captured event proves its semantics."""
    if action.get("event") != "NNet.Game.SCmdEvent":
        return "unknown"
    # In this capture a direct point command with cmd_flags=264 and no
    # ability link is the only action family whose semantics are recoverable
    # without selected-unit metadata: a native move command.
    if (
        action.get("target_point")
        and action.get("cmd_flags") == 264
        and action.get("ability_link") is None
    ):
        return "move"
    return "unknown"


def build_manual_dataset(observations_path: str | Path, actions_path: str | Path) -> dict:
    observation_path, action_path = Path(observations_path), Path(actions_path)
    frames = [json.loads(line) for line in observation_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    actions = [json.loads(line) for line in action_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    frames.sort(key=lambda frame: int(frame.get("loop", 0)))
    loops = [int(frame.get("loop", 0)) for frame in frames]
    examples: list[dict] = []
    audit = Counter()
    for action in actions:
        label = classify_manual_action(action, frames[0] if frames else {})
        audit[label] += 1
        if label == "unknown" or not frames:
            continue
        index = max(0, bisect.bisect_right(loops, int(action.get("loop", 0))) - 1)
        frame = frames[index]
        observation = _manual_observation(frame)
        examples.append({
            "features": encode_observation(observation), "label": label,
            "loop": int(action.get("loop", 0)), "source_action": dict(action),
            "source_frame_loop": int(frame.get("loop", 0)),
        })
    return {
        "schema": "cmre-p1-manual-imitation.v1",
        "evidence_type": "runtime",
        "source_observations": str(observation_path).replace("\\", "/"),
        "source_actions": str(action_path).replace("\\", "/"),
        "frame_count": len(frames), "action_count": len(actions),
        "label_audit": dict(audit), "examples": examples,
    }


def _metrics(model: P1ActionPolicyNet, examples: list[dict]) -> dict:
    if not examples:
        return {"samples": 0, "accuracy": 0.0, "loss": 0.0}
    targets = {label: index for index, label in enumerate(ACTION_LABELS)}
    features = torch.tensor([item["features"] for item in examples], dtype=torch.float32)
    labels = torch.tensor([targets[item["label"]] for item in examples], dtype=torch.long)
    model.eval()
    with torch.no_grad():
        logits = model(features)
        loss = nn.CrossEntropyLoss()(logits, labels).item()
        accuracy = float((logits.argmax(dim=-1) == labels).float().mean().item())
    return {"samples": len(examples), "accuracy": accuracy, "loss": float(loss)}


def train_p1_model(
    train_examples: Iterable[Mapping], holdout_examples: Iterable[Mapping], *,
    epochs: int = 40, hidden_dim: int = 64, learning_rate: float = 0.002,
    seed: int = 7, checkpoint_path: str | Path | None = None,
) -> tuple[P1ActionPolicyNet, dict]:
    train_data, holdout_data = list(train_examples), list(holdout_examples)
    if not train_data:
        raise ValueError("empty_p1_imitation_dataset")
    torch.manual_seed(int(seed)); torch.set_num_threads(1)
    indices = {label: index for index, label in enumerate(ACTION_LABELS)}
    features = torch.tensor([item["features"] for item in train_data], dtype=torch.float32)
    labels = torch.tensor([indices[item["label"]] for item in train_data], dtype=torch.long)
    model = P1ActionPolicyNet(hidden_dim=hidden_dim, seed=seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(learning_rate))
    criterion = nn.CrossEntropyLoss()
    losses: list[float] = []
    for _ in range(max(1, int(epochs))):
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(features), labels)
        loss.backward(); optimizer.step(); losses.append(float(loss.item()))
    metadata = {
        "schema": MODEL_SCHEMA, "feature_schema": FEATURE_SCHEMA,
        "feature_schema_hash": feature_schema_hash(), "action_labels": list(ACTION_LABELS),
        "epochs": max(1, int(epochs)), "seed": int(seed), "learning_rate": float(learning_rate),
        "loss_start": losses[0], "loss_end": losses[-1], "loss_decreased": losses[-1] < losses[0],
        "train": _metrics(model, train_data), "holdout": _metrics(model, holdout_data),
        "unknown_excluded": True,
    }
    model.checkpoint_metadata = {"schema": MODEL_SCHEMA, "feature_schema": FEATURE_SCHEMA, "training": metadata}
    if checkpoint_path is not None:
        save_checkpoint(model, checkpoint_path, training=metadata)
    return model, metadata


def save_checkpoint(model: P1ActionPolicyNet, path: str | Path, *, training: Mapping | None = None) -> Path:
    destination = Path(path); destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": MODEL_SCHEMA, "feature_schema": FEATURE_SCHEMA,
        "feature_schema_hash": feature_schema_hash(), "feature_names": list(FEATURE_NAMES),
        "action_labels": list(ACTION_LABELS),
        "config": {"input_dim": model.input_dim, "hidden_dim": model.hidden_dim},
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "training": dict(training or {}),
    }
    torch.save(payload, destination)
    return destination


def load_checkpoint(path: str | Path, *, device: str = "cpu") -> P1ActionPolicyNet:
    checkpoint_path = Path(path)
    if checkpoint_path.suffix.lower() != ".pt":
        raise ValueError("p1_model_schema_mismatch")
    payload = torch.load(checkpoint_path, map_location=device, weights_only=True)
    if not isinstance(payload, Mapping) or payload.get("schema") != MODEL_SCHEMA:
        raise ValueError("p1_model_schema_mismatch")
    if payload.get("feature_schema") != FEATURE_SCHEMA or payload.get("feature_schema_hash") != feature_schema_hash():
        raise ValueError("p1_feature_schema_mismatch")
    if tuple(payload.get("feature_names", ())) != FEATURE_NAMES or tuple(payload.get("action_labels", ())) != ACTION_LABELS:
        raise ValueError("p1_head_schema_mismatch")
    config = dict(payload.get("config", {}))
    model = P1ActionPolicyNet(hidden_dim=int(config.get("hidden_dim", 64)), seed=1)
    model.load_state_dict(payload["state_dict"], strict=True); model.to(device); model.eval()
    model.checkpoint_metadata = {
        "schema": payload.get("schema"), "feature_schema": payload.get("feature_schema"),
        "feature_schema_hash": payload.get("feature_schema_hash"), "training": dict(payload.get("training", {})),
    }
    return model


def train_from_manual_replay(
    observations_path: str | Path, actions_path: str | Path, checkpoint_path: str | Path,
    report_path: str | Path | None = None,
) -> dict:
    dataset = build_manual_dataset(observations_path, actions_path)
    examples = list(dataset["examples"])
    if len(examples) < 2:
        raise ValueError("insufficient_confirmed_p1_examples")
    split = max(1, min(len(examples) - 1, int(len(examples) * 0.8)))
    model, metrics = train_p1_model(examples[:split], examples[split:], checkpoint_path=checkpoint_path)
    report = {**dataset, "split": {"train": split, "holdout": len(examples) - split}, "training": metrics,
              "checkpoint": str(checkpoint_path).replace("\\", "/"),
              "checkpoint_sha256": hashlib.sha256(Path(checkpoint_path).read_bytes()).hexdigest()}
    if report_path is not None:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Train the P1 PyTorch action policy from a native manual replay")
    parser.add_argument("--observations", required=True)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    print(json.dumps(train_from_manual_replay(args.observations, args.actions, args.checkpoint, args.report), ensure_ascii=False, indent=2))
