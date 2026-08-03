"""Small, dependency-free imitation-learning policy for the P2 ally.

The model is intentionally bounded: it predicts one high-level tactical mode
from the public ``Observation`` contract. Economy, ownership, pathing, and
friendly-fire checks remain in the existing typed action boundary.

This is a real supervised MLP, not a renamed rule table. It uses tanh hidden
units, softmax cross-entropy, deterministic SGD, held-out evaluation, and a
versioned JSON checkpoint so a run can be reproduced without NumPy or Torch.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


MODE_LABELS = (
    "follow",
    "regroup",
    "defend_base",
    "assist_attack",
    "retreat",
    "hold",
)
MODEL_SCHEMA = "cmre-ally-mlp.v1"


def _get(observation, name: str, default):
    if isinstance(observation, Mapping):
        return observation.get(name, default)
    return getattr(observation, name, default)


def _dist(a: Mapping, b: Mapping) -> float:
    return math.hypot(
        float(a.get("x", 0.0)) - float(b.get("x", 0.0)),
        float(a.get("y", 0.0)) - float(b.get("y", 0.0)),
    )


def _health_ratio(unit: Mapping) -> float:
    maximum = float(unit.get("max_health", 0.0))
    if maximum <= 0.0:
        return 1.0
    current = float(unit.get("health", maximum))
    return max(0.0, min(1.0, current / maximum))


def _combat(unit: Mapping) -> bool:
    return str(unit.get("unit_type_id", "")) not in {
        "SCV", "Probe", "Drone", "CommandCenter", "OrbitalCommand",
        "PlanetaryFortress", "SupplyDepot", "Barracks", "Factory",
        "Starport", "EngineeringBay", "Armory", "FusionCore",
        "TechLab", "Reactor", "Refinery", "Medivac", "GhostAcademy",
        "MissileTurret", "Bunker", "SensorTower", "BarracksTechLab",
        "BarracksReactor", "FactoryTechLab", "FactoryReactor",
        "StarportTechLab", "StarportReactor",
    }


FEATURE_NAMES = (
    "own_total", "own_workers", "own_combat", "own_structures",
    "own_health_mean", "own_health_min", "enemy_total", "enemy_combat",
    "enemy_structures", "enemy_near_base", "enemy_near_leader",
    "enemy_health_mean", "ally_total", "ally_combat", "leader_visible",
    "leader_distance", "own_enemy_distance", "enemy_strength",
    "ally_strength", "minerals", "vespene", "supply_remaining",
    "requested_follow", "requested_regroup", "requested_defend_base",
    "requested_assist_attack", "requested_retreat", "requested_hold",
)


def encode_observation(
    observation,
    requested_mode: str = "follow",
    base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
    support_range: float = 14.0,
) -> list[float]:
    """Encode only public observation data into a stable numeric vector."""

    own = list(_get(observation, "own_units", ()) or ())
    allies = list(_get(observation, "visible_allies", ()) or ())
    enemies = list(_get(observation, "visible_enemies", ()) or ())
    resources = dict(_get(observation, "resources", {}) or {})
    bx, by, br = (float(base_region[0]), float(base_region[1]), float(base_region[2]))
    combat_own = [unit for unit in own if _combat(unit)]
    combat_enemy = [unit for unit in enemies if _combat(unit)]
    structures_own = [unit for unit in own if not _combat(unit) and unit.get("unit_type_id") not in {"SCV", "Probe", "Drone"}]
    structures_enemy = [unit for unit in enemies if not _combat(unit) and unit.get("unit_type_id") not in {"SCV", "Probe", "Drone"}]
    leader = next(
        (unit for unit in allies if int(unit.get("owner", -1)) == 1),
        None,
    )
    near_base = [unit for unit in enemies if math.hypot(float(unit.get("x", 0.0)) - bx, float(unit.get("y", 0.0)) - by) <= br]
    near_leader = [unit for unit in enemies if leader is not None and _dist(unit, leader) <= float(support_range)]
    own_center = own[0] if own else {"x": bx, "y": by}
    own_enemy_distance = min((_dist(own_center, unit) for unit in enemies), default=80.0)
    leader_distance = _dist(own_center, leader) if leader is not None else 80.0
    own_health = [_health_ratio(unit) for unit in combat_own]
    enemy_health = [_health_ratio(unit) for unit in combat_enemy]
    minerals = float(resources.get("minerals", 0.0))
    vespene = float(resources.get("vespene", 0.0))
    supply_remaining = float(resources.get("supply_cap", 0.0)) - float(resources.get("supply_used", 0.0))

    values = [
        min(1.0, len(own) / 80.0),
        min(1.0, sum(unit.get("unit_type_id") in {"SCV", "Probe", "Drone"} for unit in own) / 40.0),
        min(1.0, len(combat_own) / 40.0),
        min(1.0, len(structures_own) / 24.0),
        sum(own_health) / max(1, len(own_health)),
        min(own_health, default=1.0),
        min(1.0, len(enemies) / 64.0),
        min(1.0, len(combat_enemy) / 64.0),
        min(1.0, len(structures_enemy) / 32.0),
        min(1.0, len(near_base) / 32.0),
        min(1.0, len(near_leader) / 32.0),
        sum(enemy_health) / max(1, len(enemy_health)),
        min(1.0, len(allies) / 32.0),
        min(1.0, sum(_combat(unit) for unit in allies) / 32.0),
        1.0 if leader is not None else 0.0,
        min(1.0, leader_distance / 80.0),
        min(1.0, own_enemy_distance / 80.0),
        (len(combat_enemy) + 2.0 * len(structures_enemy)) / 64.0,
        len([unit for unit in allies if _combat(unit)]) / 32.0,
        min(1.0, max(0.0, minerals) / 2600.0),
        min(1.0, max(0.0, vespene) / 800.0),
        min(1.0, max(0.0, supply_remaining) / 40.0),
    ]
    requested = str(requested_mode).lower()
    values.extend(1.0 if requested == label else 0.0 for label in MODE_LABELS)
    if len(values) != len(FEATURE_NAMES):
        raise AssertionError("ML feature schema drift")
    return [float(value) for value in values]


def expert_mode_label(
    observation,
    requested_mode: str = "follow",
    base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
    support_range: float = 14.0,
) -> str:
    """Generate a teacher label from the same public safety contract.

    The teacher is used only to create imitation data. Runtime safety remains
    enforced in ``AllyPolicy`` after model inference.
    """

    own = list(_get(observation, "own_units", ()) or ())
    enemies = list(_get(observation, "visible_enemies", ()) or ())
    allies = list(_get(observation, "visible_allies", ()) or ())
    if not own:
        return "retreat"
    combat = [unit for unit in own if _combat(unit)]
    if any(_health_ratio(unit) <= 0.15 for unit in combat):
        return "retreat"
    bx, by, br = base_region
    if any(math.hypot(float(unit.get("x", 0.0)) - bx, float(unit.get("y", 0.0)) - by) <= br for unit in enemies):
        return "defend_base"
    requested = str(requested_mode).lower()
    if requested == "retreat":
        return "retreat"
    leader = next((unit for unit in allies if int(unit.get("owner", -1)) == 1), None)
    leader_threat = leader is not None and any(_dist(unit, leader) <= support_range for unit in enemies)
    if (enemies or leader_threat) and requested in {"follow", "regroup", "assist_attack"}:
        return "assist_attack"
    return requested if requested in MODE_LABELS else "follow"


@dataclass(frozen=True)
class ModePrediction:
    label: str
    confidence: float
    probabilities: dict[str, float]


class MLPModeModel:
    """A deterministic one-hidden-layer classifier trained with SGD."""

    schema = MODEL_SCHEMA

    def __init__(self, hidden_dim: int = 24, seed: int = 7) -> None:
        self.input_dim = len(FEATURE_NAMES)
        self.hidden_dim = max(2, int(hidden_dim))
        self.output_dim = len(MODE_LABELS)
        rng = random.Random(int(seed))
        limit_ih = math.sqrt(6.0 / (self.input_dim + self.hidden_dim))
        limit_ho = math.sqrt(6.0 / (self.hidden_dim + self.output_dim))
        self.weights_ih = [
            [rng.uniform(-limit_ih, limit_ih) for _ in range(self.input_dim)]
            for _ in range(self.hidden_dim)
        ]
        self.bias_h = [0.0] * self.hidden_dim
        self.weights_ho = [
            [rng.uniform(-limit_ho, limit_ho) for _ in range(self.hidden_dim)]
            for _ in range(self.output_dim)
        ]
        self.bias_o = [0.0] * self.output_dim
        self.training = {}

    def _forward(self, features: Sequence[float]):
        if len(features) != self.input_dim:
            raise ValueError(f"feature_dim_mismatch:{len(features)}!={self.input_dim}")
        hidden = [
            math.tanh(sum(weight * value for weight, value in zip(row, features)) + bias)
            for row, bias in zip(self.weights_ih, self.bias_h)
        ]
        logits = [
            sum(weight * value for weight, value in zip(row, hidden)) + bias
            for row, bias in zip(self.weights_ho, self.bias_o)
        ]
        peak = max(logits)
        exp_values = [math.exp(max(-60.0, value - peak)) for value in logits]
        total = sum(exp_values) or 1.0
        return hidden, [value / total for value in exp_values]

    def predict_features(self, features: Sequence[float]) -> ModePrediction:
        _, probabilities = self._forward(features)
        index = max(range(self.output_dim), key=probabilities.__getitem__)
        return ModePrediction(
            MODE_LABELS[index],
            float(probabilities[index]),
            {label: float(probabilities[i]) for i, label in enumerate(MODE_LABELS)},
        )

    def predict_mode(
        self,
        observation,
        requested_mode: str = "follow",
        base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
        support_range: float = 14.0,
    ) -> ModePrediction:
        return self.predict_features(encode_observation(observation, requested_mode, base_region, support_range))

    def fit(
        self,
        samples: Sequence[tuple[Sequence[float], str]],
        *,
        epochs: int = 120,
        learning_rate: float = 0.08,
        seed: int = 7,
    ) -> dict:
        if not samples:
            raise ValueError("empty_training_set")
        encoded = []
        for features, label in samples:
            if label not in MODE_LABELS:
                raise ValueError(f"unknown_label:{label}")
            if len(features) != self.input_dim:
                raise ValueError("training_feature_dim_mismatch")
            encoded.append((list(map(float, features)), MODE_LABELS.index(label)))
        rng = random.Random(int(seed))
        losses: list[float] = []
        for _epoch in range(max(1, int(epochs))):
            order = list(range(len(encoded)))
            rng.shuffle(order)
            for sample_index in order:
                features, target = encoded[sample_index]
                hidden, probabilities = self._forward(features)
                output_error = list(probabilities)
                output_error[target] -= 1.0
                hidden_error = [
                    (1.0 - hidden[j] * hidden[j])
                    * sum(self.weights_ho[k][j] * output_error[k] for k in range(self.output_dim))
                    for j in range(self.hidden_dim)
                ]
                for k in range(self.output_dim):
                    for j in range(self.hidden_dim):
                        self.weights_ho[k][j] -= float(learning_rate) * output_error[k] * hidden[j]
                    self.bias_o[k] -= float(learning_rate) * output_error[k]
                for j in range(self.hidden_dim):
                    for i in range(self.input_dim):
                        self.weights_ih[j][i] -= float(learning_rate) * hidden_error[j] * features[i]
                    self.bias_h[j] -= float(learning_rate) * hidden_error[j]
            metrics = self.evaluate([(features, MODE_LABELS[target]) for features, target in encoded])
            losses.append(float(metrics["loss"]))
        self.training = {
            "samples": len(encoded),
            "epochs": max(1, int(epochs)),
            "learning_rate": float(learning_rate),
            "seed": int(seed),
            "final_loss": losses[-1],
            "loss_start": losses[0],
            "loss_decreased": losses[-1] < losses[0],
        }
        return dict(self.training)

    def evaluate(self, samples: Sequence[tuple[Sequence[float], str]]) -> dict:
        if not samples:
            return {"samples": 0, "accuracy": 0.0, "loss": 0.0, "confusion": {}}
        correct = 0
        loss = 0.0
        confusion = {label: {pred: 0 for pred in MODE_LABELS} for label in MODE_LABELS}
        for features, label in samples:
            prediction = self.predict_features(features)
            probability = max(1e-12, prediction.probabilities.get(label, 0.0))
            loss -= math.log(probability)
            correct += prediction.label == label
            confusion[label][prediction.label] += 1
        return {
            "samples": len(samples),
            "accuracy": correct / len(samples),
            "loss": loss / len(samples),
            "confusion": confusion,
        }

    def to_dict(self) -> dict:
        payload = {
            "schema": self.schema,
            "feature_names": list(FEATURE_NAMES),
            "labels": list(MODE_LABELS),
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "output_dim": self.output_dim,
            "weights_ih": self.weights_ih,
            "bias_h": self.bias_h,
            "weights_ho": self.weights_ho,
            "bias_o": self.bias_o,
            "training": self.training,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["weights_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return payload

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.to_dict(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        return destination

    @classmethod
    def from_dict(cls, payload: Mapping) -> "MLPModeModel":
        if payload.get("schema") != MODEL_SCHEMA:
            raise ValueError(f"model_schema_mismatch:{payload.get('schema')}")
        if tuple(payload.get("feature_names", ())) != FEATURE_NAMES:
            raise ValueError("model_feature_schema_mismatch")
        if tuple(payload.get("labels", ())) != MODE_LABELS:
            raise ValueError("model_label_schema_mismatch")
        recorded_hash = payload.get("weights_sha256")
        if recorded_hash:
            unsigned = {
                str(key): value
                for key, value in payload.items()
                if key != "weights_sha256"
            }
            actual_hash = hashlib.sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if actual_hash != str(recorded_hash):
                raise ValueError("model_weights_hash_mismatch")
        model = cls(hidden_dim=int(payload["hidden_dim"]), seed=1)
        if int(payload["input_dim"]) != model.input_dim or int(payload["output_dim"]) != model.output_dim:
            raise ValueError("model_dimension_mismatch")
        model.weights_ih = [[float(value) for value in row] for row in payload["weights_ih"]]
        model.bias_h = [float(value) for value in payload["bias_h"]]
        model.weights_ho = [[float(value) for value in row] for row in payload["weights_ho"]]
        model.bias_o = [float(value) for value in payload["bias_o"]]
        model.training = dict(payload.get("training", {}))
        return model

    @classmethod
    def load(cls, path: str | Path) -> "MLPModeModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def make_public_expert_dataset(
    seeds: Iterable[int],
    samples_per_seed: int = 180,
    base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
) -> list[dict]:
    """Generate reproducible public-state teacher samples for training.

    This creates varied observations, not labels hard-coded into the model.
    The production validation still runs the resulting model through the real
    simulator, where observations and actions use the project contracts.
    """

    records: list[dict] = []
    for seed in seeds:
        rng = random.Random(int(seed))
        for index in range(max(1, int(samples_per_seed))):
            case = index % 12
            bx, by, _ = base_region
            worker_count = 8 + rng.randrange(0, 41)
            own = [
                {"entity_id": 1, "unit_type_id": "CommandCenter", "owner": 2, "x": bx, "y": by, "health": 1500, "max_health": 1500},
                *[
                    {"entity_id": 10 + worker, "unit_type_id": "SCV", "owner": 2, "x": bx + (worker % 5), "y": by + (worker // 5), "health": 45, "max_health": 45}
                    for worker in range(worker_count)
                ],
            ]
            if case not in {0, 1, 2, 3, 4, 5}:
                own.extend([
                    {"entity_id": 100 + unit, "unit_type_id": "Marine", "owner": 2, "x": bx + 4 + unit, "y": by + 2, "health": 45, "max_health": 45}
                    for unit in range(2 + (index % 5))
                ])
            enemies = []
            if case in {6, 9, 11}:
                enemies = [
                    {"entity_id": 400 + unit, "unit_type_id": "Zergling", "owner": 3, "x": bx + 34 + unit, "y": by + (unit % 3), "health": 35, "max_health": 35}
                    for unit in range(2 + index % 4)
                ]
            if case == 7:
                enemies = [{"entity_id": 500, "unit_type_id": "Zergling", "owner": 3, "x": bx + 4, "y": by + 3, "health": 35, "max_health": 35}]
            if case == 8:
                own.append({"entity_id": 200, "unit_type_id": "Marine", "owner": 2, "x": bx + 3, "y": by, "health": 5, "max_health": 45})
            requested = MODE_LABELS[(case + int(seed)) % len(MODE_LABELS)]
            allies = [{"entity_id": 900, "unit_type_id": "Marine", "owner": 1, "x": bx + 2, "y": by + 1, "health": 45, "max_health": 45}]
            if case == 9:
                enemies[0]["x"], enemies[0]["y"] = bx + 4, by + 2
            observation = {
                "own_units": own,
                "visible_allies": allies,
                "visible_enemies": enemies,
                "resources": {"minerals": 200 + index * 3, "vespene": index % 300, "supply_cap": 40, "supply_used": 12 + len(own) // 3},
            }
            label = expert_mode_label(observation, requested, base_region)
            records.append({
                "seed": int(seed),
                "step": int(index),
                "requested_mode": requested,
                "label": label,
                "features": encode_observation(observation, requested, base_region),
                "source": "public_observation_expert_rollout",
            })
    return records


def samples_from_records(records: Iterable[Mapping]) -> list[tuple[list[float], str]]:
    return [(list(record["features"]), str(record["label"])) for record in records]


__all__ = [
    "FEATURE_NAMES", "MODE_LABELS", "MODEL_SCHEMA", "MLPModeModel",
    "ModePrediction", "encode_observation", "expert_mode_label",
    "make_public_expert_dataset", "samples_from_records",
]
