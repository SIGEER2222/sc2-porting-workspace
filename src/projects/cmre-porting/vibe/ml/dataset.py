"""Multi-head imitation dataset built from public simulator observations."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

import torch
from torch.utils.data import Dataset

from .encoder import encode_observation
from .schema import HEAD_LABELS


def _unit_type(unit: Mapping) -> str:
    return str(unit.get("unit_type_id", ""))


def _targets(record: Mapping) -> dict[str, str]:
    observation = record.get("observation", record)
    own = list(observation.get("own_units", ()) or ())
    resources = dict(observation.get("resources", {}) or {})
    types = Counter(_unit_type(unit) for unit in own)
    workers = sum(_unit_type(unit) in {"SCV", "Probe", "Drone"} for unit in own)
    supply_remaining = float(resources.get("supply_cap", 0.0)) - float(resources.get("supply_used", 0.0))
    minerals = float(resources.get("minerals", 0.0))
    gas = float(resources.get("vespene", 0.0))
    geysers = list(observation.get("vespene_geysers", ()) or ())

    if supply_remaining <= 2.0:
        economy = "build_supply"
    elif workers < 12:
        economy = "train_worker"
    elif geysers and gas < 100.0:
        economy = "gather_gas"
    elif minerals > 0.0:
        economy = "gather_minerals"
    else:
        economy = "maintain_economy"

    if types["Refinery"] == 0 and minerals >= 100.0:
        production = "build_refinery"
    elif types["Barracks"] == 0 and minerals >= 150.0:
        production = "build_barracks"
    elif types["Factory"] == 0 and types["Barracks"] > 0 and minerals >= 150.0:
        production = "build_factory"
    elif types["Barracks"] > 0 and minerals >= 50.0:
        production = "train_marine"
    else:
        production = "no_op"

    tactical = str(record.get("label", "follow"))
    if tactical not in HEAD_LABELS["tactical"]:
        tactical = "follow"
    command = str(record.get("requested_mode", "none"))
    if command not in HEAD_LABELS["command"]:
        command = "none"
    return {"economy": economy, "production": production, "tactical": tactical, "command": command}


def build_examples(
    records: Iterable[Mapping],
    *,
    base_region: tuple[float, float, float] = (85.0, 94.0, 14.0),
    support_range: float = 14.0,
) -> list[dict]:
    examples: list[dict] = []
    for record in records:
        observation = record.get("observation", record)
        requested = str(record.get("requested_mode", "follow"))
        examples.append({
            "features": encode_observation(observation, requested, base_region, support_range),
            "targets": _targets(record),
            "seed": int(record.get("seed", 0)),
            "step": int(record.get("step", 0)),
        })
    if not examples:
        raise ValueError("empty_p2_imitation_dataset")
    return examples


class P2IntentDataset(Dataset):
    def __init__(self, examples: Iterable[Mapping]) -> None:
        self.examples = list(examples)
        if not self.examples:
            raise ValueError("empty_p2_intent_dataset")
        self._indices = {
            head: {label: index for index, label in enumerate(labels)}
            for head, labels in HEAD_LABELS.items()
        }

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int):
        example = self.examples[index]
        features = torch.tensor(example["features"], dtype=torch.float32)
        targets = {
            head: torch.tensor(self._indices[head][example["targets"][head]], dtype=torch.long)
            for head in HEAD_LABELS
        }
        return features, targets
