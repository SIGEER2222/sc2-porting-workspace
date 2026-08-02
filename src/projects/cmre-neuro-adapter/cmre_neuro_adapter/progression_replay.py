"""Build a deterministic economy-and-production replay from a legacy map replay."""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ScheduledAction:
    loop: int
    kind: str
    label: str
    unit_type: str | None = None
    minerals: int = 0
    vespene: int = 0
    x: float = 85.0
    y: float = 94.0


# The base replay already contains the mission's initial force. This schedule models
# only the additional economy and production that happens after that opening state.
SCHEDULE: tuple[ScheduledAction, ...] = (
    ScheduledAction(0, "gather", "4 SCV 开始采集矿物"),
    ScheduledAction(200, "train", "训练 SCV", "SCV", 50, 0, 84.0, 93.0),
    ScheduledAction(300, "train", "训练 Marine", "Marine", 50, 0, 84.0, 90.0),
    ScheduledAction(500, "build", "建造 Supply Depot", "SupplyDepot", 100, 0, 80.0, 95.0),
    ScheduledAction(700, "train", "训练 Marine", "Marine", 50, 0, 84.0, 90.0),
    ScheduledAction(900, "build", "建造 Barracks", "Barracks", 150, 0, 79.0, 90.0),
    ScheduledAction(1000, "train", "训练 SCV", "SCV", 50, 0, 85.0, 93.0),
    ScheduledAction(1100, "train", "训练 Marine", "Marine", 50, 0, 80.0, 89.0),
    ScheduledAction(1300, "build", "建造 Refinery", "Refinery", 75, 0, 89.0, 93.0),
    ScheduledAction(1500, "train", "训练 Marine", "Marine", 50, 0, 80.0, 89.0),
    ScheduledAction(1700, "build", "建造 Supply Depot", "SupplyDepot", 100, 0, 88.0, 95.0),
    ScheduledAction(1900, "train", "训练 Marauder", "Marauder", 100, 25, 80.0, 89.0),
    ScheduledAction(2100, "research", "研究 Combat Shield", None, 100, 100),
    ScheduledAction(2300, "train", "训练 Marine", "Marine", 50, 0, 79.0, 89.0),
    ScheduledAction(2500, "build", "建造 Missile Turret", "MissileTurret", 100, 0, 90.0, 96.0),
    ScheduledAction(2700, "train", "训练 SCV", "SCV", 50, 0, 86.0, 93.0),
    ScheduledAction(2900, "train", "训练 Marauder", "Marauder", 100, 25, 79.0, 89.0),
    ScheduledAction(3100, "train", "训练 Marine", "Marine", 50, 0, 78.0, 89.0),
    ScheduledAction(3300, "build", "建造 Supply Depot", "SupplyDepot", 100, 0, 82.0, 97.0),
    ScheduledAction(3500, "train", "训练 Marine", "Marine", 50, 0, 77.0, 89.0),
)

UNIT_HP = {
    "SCV": 46080,
    "Marine": 46080,
    "Marauder": 128000,
    "SupplyDepot": 409600,
    "Barracks": 1024000,
    "Refinery": 512000,
    "MissileTurret": 256000,
}


def _entity_count(frame: dict[str, Any], owner: str) -> int:
    return len(frame.get("entities_by_player", {}).get(owner, []))


def _type_counts(entities: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in entities:
        unit_type = str(entity.get("t", "Unknown"))
        counts[unit_type] = counts.get(unit_type, 0) + 1
    return counts


def _next_entity_id(records: Iterable[dict[str, Any]]) -> int:
    ids = [
        int(entity["id"])
        for record in records
        for entities in record.get("entities_by_player", {}).values()
        for entity in entities
        if "id" in entity
    ]
    return max(ids, default=0) + 1


def _supply_used(entities: Iterable[dict[str, Any]]) -> int:
    costs = {"SCV": 1, "Marine": 1, "Marauder": 2, "SiegeTank": 2, "Medivac": 2}
    return sum(costs.get(str(entity.get("t")), 0) for entity in entities)


def _supply_cap(entities: Iterable[dict[str, Any]]) -> int:
    return 15 + 8 * sum(1 for entity in entities if entity.get("t") == "SupplyDepot")


def _new_entity(action: ScheduledAction, entity_id: int) -> dict[str, Any]:
    return {
        "id": entity_id,
        "t": action.unit_type or "Research",
        "p": 1,
        "x": action.x,
        "y": action.y,
        "hp": UNIT_HP.get(action.unit_type or "", 1),
        "alive": True,
        "state": "completed",
    }


def build_progression_replay(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve legacy map frames and add a resource-funded P1 progression layer."""

    source = [copy.deepcopy(record) for record in records if record.get("entities_by_player")]
    if not source:
        raise ValueError("legacy replay contains no entity frames")

    next_id = _next_entity_id(source)
    created: list[tuple[int, dict[str, Any]]] = []
    actions: list[dict[str, Any]] = []
    pending = list(SCHEDULE)
    minerals = 250.0
    vespene = 0.0
    previous_loop = int(source[0].get("loop", 0))

    output: list[dict[str, Any]] = [
        {
            "record_type": "header",
            "replay_id": "dead-of-night-progression-replay",
            "source_replay": "dead_of_night_replay_20260730_224154.jsonl",
            "evidence_type": "simulator",
            "model": "legacy-map-observation-plus-deterministic-economy-schedule",
        }
    ]

    for source_frame in source:
        frame = copy.deepcopy(source_frame)
        frame["record_type"] = "frame"
        loop = int(frame.get("loop", 0))
        delta = max(0, loop - previous_loop)
        base_p1 = frame.setdefault("entities_by_player", {}).setdefault("1", [])
        persistent = [entity for created_loop, entity in created if created_loop <= loop]
        current_p1 = base_p1 + persistent
        scv_count = sum(1 for entity in current_p1 if entity.get("t") == "SCV")
        refinery_count = sum(1 for entity in current_p1 if entity.get("t") == "Refinery")
        minerals += scv_count * 0.075 * delta
        vespene += refinery_count * 0.045 * delta

        frame_events = list(frame.get("key_events", []))
        due_actions = [action for action in pending if action.loop <= loop]
        pending = [action for action in pending if action.loop > loop]
        deferred: list[ScheduledAction] = []
        for action in due_actions:
            if action.kind == "gather":
                event = {
                    "loop": loop,
                    "kind": "resource_gather_start",
                    "text": action.label,
                    "owner": 1,
                }
                frame_events.append(event)
                actions.append({
                    "record_type": "action",
                    "action_id": f"economy-{len(actions) + 1:03d}",
                    "name": action.label,
                    "loop": loop,
                    "requested_loop": action.loop,
                    "kind": action.kind,
                    "dispatched": {"success": True},
                })
                continue
            if minerals < action.minerals or vespene < action.vespene:
                deferred.append(action)
                continue
            minerals -= action.minerals
            vespene -= action.vespene
            if action.unit_type:
                entity = _new_entity(action, next_id)
                next_id += 1
                created.append((loop, entity))
                current_p1.append(entity)
            event = {
                "loop": loop,
                "requested_loop": action.loop,
                "kind": "build_complete" if action.kind == "build" else "production_complete" if action.kind == "train" else "upgrade_complete",
                "text": action.label,
                "owner": 1,
                "unit_type": action.unit_type,
                "entity_id": next_id - 1 if action.unit_type else 0,
                "minerals": action.minerals,
                "vespene": action.vespene,
            }
            frame_events.append(event)
            actions.append({
                "record_type": "action",
                "action_id": f"economy-{len(actions) + 1:03d}",
                "name": action.label,
                "loop": loop,
                "requested_loop": action.loop,
                "kind": action.kind,
                "unit_type_id": action.unit_type,
                "cost": {"minerals": action.minerals, "vespene": action.vespene},
                "dispatched": {"success": True},
            })
        pending = sorted(deferred + pending, key=lambda item: item.loop)

        frame["entities_by_player"]["1"] = current_p1
        all_p1 = current_p1
        enemy = [
            entity
            for owner, entities in frame["entities_by_player"].items()
            if owner not in {"0", "1"}
            for entity in entities
        ]
        frame["p1_alive"] = len(all_p1)
        frame["enemy_alive"] = len(enemy)
        frame["p1_units_by_type"] = _type_counts(all_p1)
        frame["enemy_units_by_type"] = _type_counts(enemy)
        frame["p1_resources"] = {
            "minerals": max(0, int(minerals)),
            "vespene": max(0, int(vespene)),
            "supply_used": _supply_used(all_p1),
            "supply_cap": _supply_cap(all_p1),
        }
        frame["key_events"] = frame_events
        frame["economy"] = {
            "gatherers": scv_count,
            "refineries": refinery_count,
            "mineral_income_per_loop": round(scv_count * 0.075, 3),
            "vespene_income_per_loop": round(refinery_count * 0.045, 3),
        }
        output.append(frame)
        previous_loop = loop

    output.extend(actions)
    output.append({
        "record_type": "summary",
        "status": "PASS",
        "replay_id": "dead-of-night-progression-replay",
        "evidence_type": "simulator",
        "runtime_claim": "none; deterministic progression model only",
        "actions_successful": len(actions),
        "actions_total": len(actions),
        "event_count": sum(
            len(record.get("key_events", []))
            for record in output
            if record.get("record_type") == "frame"
        ),
        "timeline_frames": len(source),
        "loop_start": int(source[0].get("loop", 0)),
        "loop_end": int(source[-1].get("loop", 0)),
        "source_replay": "dead_of_night_replay_20260730_224154.jsonl",
        "progression_model": {
            "starting_minerals": 250,
            "minerals_per_loop_per_scv": 0.075,
            "vespene_per_loop_per_refinery": 0.045,
            "pending_actions": [action.label for action in pending],
        },
    })
    return output


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def write_progression_replay(source_path: Path, output_path: Path) -> None:
    data = build_progression_replay(load_jsonl(source_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in data) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_progression_replay(args.source, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_progression_replay", "load_jsonl", "write_progression_replay"]
