"""Extract the Reborn Abathur source-of-truth roster and Larva card commands.

The generated JSON deliberately describes only card-exposed Larva commands. An
InfoArray entry without a Larva card button is not a player-facing product.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT = ROOT / "artifacts/projects/cmre-porting/stage26-full-function-invoke/reborn-abathur-baseline.json"
DEFAULT_SWARM_ABIL_DATA = ROOT / "reference/sc2mapster/SC2GameData/campaigns/swarm.sc2campaign/base.sc2data/GameData/AbilData.xml"
DEFAULT_SWARM_UNIT_DATA = ROOT / "reference/sc2mapster/SC2GameData/campaigns/swarm.sc2campaign/base.sc2data/GameData/UnitData.xml"
DEFAULT_UNIT_DATA_LAYERS = (
    ROOT / "reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/UnitData.xml",
    ROOT / "reference/sc2mapster/SC2GameData/mods/liberty.sc2mod/base.sc2data/GameData/UnitData.xml",
    ROOT / "reference/sc2mapster/SC2GameData/mods/swarm.sc2mod/base.sc2data/GameData/UnitData.xml",
    ROOT / "reference/sc2mapster/SC2GameData/campaigns/liberty.sc2campaign/base.sc2data/GameData/UnitData.xml",
    DEFAULT_SWARM_UNIT_DATA,
)
SOURCE_FILES = {
    "unit_data": Path("crys_the_swarm_reborn.SC2Mod/Base.SC2Data/GameData/UnitData.xml"),
    "abil_data": Path("crys_the_swarm_reborn.SC2Mod/Base.SC2Data/GameData/AbilData.xml"),
    "galaxy": Path("crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy"),
}
COMMAND_RE = re.compile(r"^(?P<ability>[^,]+),(?P<command>Train(?P<number>\d+))$")
ALLOW_RE = re.compile(r'TechTreeUnitAllow\s*\([^,]+,\s*"(?P<unit>[^"]+)",\s*(?P<enabled>true|false)\s*\)')
UNIT_GET_TYPE_RE = re.compile(r'UnitGetType\s*\([^)]*\)\s*==\s*"(?P<unit>[^"]+)"')

# UnitUnlocks only mentions altered tech. The campaign's normal starting Zerg
# construction menu is inherited, so record that stable foundation explicitly.
CORE_ZERG_BUILDINGS = frozenset(
    {
        "Hatchery",
        "Lair",
        "Hive",
        "Extractor",
        "SpawningPool",
        "EvolutionChamber",
        "BanelingNest",
        "RoachWarren",
        "HydraliskDen",
        "LurkerDen",
        "InfestationPit",
        "Spire",
        "GreaterSpire",
        "UltraliskCavern",
        "NydusNetwork",
        "SpineCrawler",
        "SporeCrawler",
    }
)
CORE_ZERG_UNITS = frozenset({"Drone", "Larva", "Overlord", "Queen"})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_reborn_root() -> Path:
    candidates = sorted((Path.home() / "Downloads").glob("*0.71*/reborn"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError("Reborn source not found; pass --reborn-root")
    raise RuntimeError("multiple Reborn source roots found; pass --reborn-root")


def require_file(root: Path, relative: Path) -> Path:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"missing Reborn source file: {relative.as_posix()}")
    return path


def parse_train_abilities(abil_data: Path, inherited_abil_data: Path | None = None) -> dict[str, dict[str, Any]]:
    """Merge campaign parent then Reborn overrides at the CAbilTrain/InfoArray level."""
    abilities: dict[str, dict[str, Any]] = {}

    def apply(source: Path, source_kind: str) -> None:
        root = ET.parse(source).getroot()
        for ability in root.findall("CAbilTrain"):
            ability_id = ability.get("id")
            if ability_id is None:
                continue
            entries = abilities.setdefault(ability_id, {})
            for info in ability.findall("InfoArray"):
                command = info.get("index")
                if command is None:
                    continue
                products = [unit.get("value") for unit in info.findall("Unit") if unit.get("value")]
                button = info.find("Button")
                entries[command] = {
                    "products": products,
                    "requirements": button.get("Requirements") if button is not None else None,
                    "button_state": button.get("State") if button is not None else None,
                    "time": info.get("Time"),
                    "source": source_kind,
                }

    if inherited_abil_data is not None:
        apply(inherited_abil_data, "swarm_campaign_inherited")
    apply(abil_data, "reborn_override")
    return abilities


def parse_larva_card(unit_data: Path, train_abilities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    root = ET.parse(unit_data).getroot()
    larva = next((unit for unit in root.findall("CUnit") if unit.get("id") == "Larva"), None)
    if larva is None:
        raise ValueError("CUnit id=Larva is absent from UnitData.xml")
    commands: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for layout in larva.findall("CardLayouts"):
        for button in layout.findall("LayoutButtons"):
            raw_command = button.get("AbilCmd")
            if raw_command is None:
                continue
            match = COMMAND_RE.match(raw_command)
            if match is None:
                raise ValueError(f"Larva card has unsupported AbilCmd: {raw_command}")
            ability = match.group("ability")
            command = match.group("command")
            key = (ability, command)
            if key in seen:
                continue
            seen.add(key)
            if ability not in train_abilities or command not in train_abilities[ability]:
                raise ValueError(f"Larva card command cannot resolve: {raw_command}")
            info = train_abilities[ability][command]
            if not info["products"]:
                raise ValueError(f"Larva card command has no product: {raw_command}")
            commands.append(
                {
                    "ability": ability,
                    "command": command,
                    "command_index": int(match.group("number")) - 1,
                    "products": info["products"],
                    "quantity": len(info["products"]),
                    "requirements": info["requirements"],
                    "button_state": info["button_state"],
                    "time": info["time"],
                    "product_source": info["source"],
                    "card": {
                        "face": button.get("Face"),
                        "row": button.get("Row"),
                        "column": button.get("Column"),
                    },
                }
            )
    commands.sort(key=lambda item: (item["ability"], item["command_index"]))
    return commands


def extract_function_body(source: str, signature: str) -> str:
    start = source.find(signature)
    if start < 0:
        raise ValueError(f"missing Galaxy function: {signature}")
    brace = source.find("{", start)
    if brace < 0:
        raise ValueError(f"missing Galaxy function body: {signature}")
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise ValueError(f"unterminated Galaxy function: {signature}")


def parse_roster(
    galaxy: Path,
    unit_data: Path,
    inherited_unit_data: tuple[Path, ...],
    larva_commands: list[dict[str, Any]],
) -> dict[str, Any]:
    text = galaxy.read_text(encoding="utf-8")
    unlocks = extract_function_body(text, "bool lib48DF4533_gt_UnitUnlocks_Func")
    states: dict[str, set[str]] = defaultdict(set)
    for match in ALLOW_RE.finditer(unlocks):
        states[match.group("unit")].add(match.group("enabled"))
    abathur = extract_function_body(text, "bool lib48DF4533_gt_Abathur_Func")
    abathur_abilities = extract_function_body(text, "bool lib48DF4533_gt_AbathurAbilities_Func")
    catalog_roots = [*(ET.parse(path).getroot() for path in inherited_unit_data), ET.parse(unit_data).getroot()]
    catalog_units = sorted(
        {unit.get("id") for root in catalog_roots for unit in root.findall("CUnit") if unit.get("id")}
    )
    structure_state: dict[str, bool] = {}
    for catalog_root in catalog_roots:
        for unit in catalog_root.findall("CUnit"):
            unit_id = unit.get("id")
            if unit_id is None:
                continue
            for attribute in unit.findall("Attributes"):
                if attribute.get("index") != "Structure":
                    continue
                structure_state[unit_id] = attribute.get("removed") != "1" and attribute.get("value", "1") != "0"
    structures = {unit for unit, is_structure in structure_state.items() if is_structure}
    unlockable_units = sorted(unit for unit, state in states.items() if "true" in state)
    unlockable_buildings = {unit for unit in unlockable_units if unit in structures}
    card_products = {product for command in larva_commands for product in command["products"]}
    original_units = (set(unlockable_units) - unlockable_buildings) | card_products | CORE_ZERG_UNITS
    original_buildings = unlockable_buildings | CORE_ZERG_BUILDINGS
    return {
        "catalog_unit_ids": catalog_units,
        "unit_unlock_inventory": [
            {"unit": unit, "source_states": sorted(states[unit])} for unit in sorted(states)
        ],
        "abathur_unit_hooks": sorted(
            set(UNIT_GET_TYPE_RE.findall(abathur)) | set(UNIT_GET_TYPE_RE.findall(abathur_abilities))
        ),
        "potentially_unlockable": {
            "units": sorted(set(unlockable_units) - unlockable_buildings),
            "buildings": sorted(unlockable_buildings),
        },
        "original_roster": {
            "units": sorted(original_units),
            "buildings": sorted(original_buildings),
            "unit_sources": {
                "core_zerg": sorted(CORE_ZERG_UNITS),
                "unit_unlocks": sorted(set(unlockable_units) - unlockable_buildings),
                "larva_card_products": sorted(card_products),
            },
            "building_sources": {
                "core_zerg": sorted(CORE_ZERG_BUILDINGS),
                "unit_unlocks": sorted(unlockable_buildings),
            },
        },
    }


def build_baseline(
    reborn_root: Path,
    swarm_abil_data: Path | None = DEFAULT_SWARM_ABIL_DATA,
    unit_data_layers: tuple[Path, ...] = DEFAULT_UNIT_DATA_LAYERS,
) -> dict[str, Any]:
    paths = {name: require_file(reborn_root, relative) for name, relative in SOURCE_FILES.items()}
    if swarm_abil_data is not None and not swarm_abil_data.is_file():
        raise FileNotFoundError(f"missing inherited Swarm campaign ability data: {swarm_abil_data}")
    for layer in unit_data_layers:
        if not layer.is_file():
            raise FileNotFoundError(f"missing inherited unit data layer: {layer}")
    train_abilities = parse_train_abilities(paths["abil_data"], swarm_abil_data)
    commands = parse_larva_card(paths["unit_data"], train_abilities)
    roster = parse_roster(paths["galaxy"], paths["unit_data"], unit_data_layers, commands)
    return {
        "schemaVersion": 1,
        "subject": "reborn-abathur",
        "source": {
            "root": "reborn",
            "files": {
                name: {"path": SOURCE_FILES[name].as_posix(), "sha256": sha256(path)}
                for name, path in paths.items()
            },
            "inherited_files": (
                []
                if swarm_abil_data is None
                else [{"path": "reference/sc2mapster/SC2GameData/campaigns/swarm.sc2campaign/base.sc2data/GameData/AbilData.xml", "sha256": sha256(swarm_abil_data)}]
            )
            + [
                {
                    "path": layer.relative_to(ROOT).as_posix(),
                    "sha256": sha256(layer),
                }
                for layer in unit_data_layers
            ],
        },
        "larva": {"unit_id": "Larva", "card_exposed_commands": commands, "command_count": len(commands)},
        "roster": roster,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Reborn Abathur Larva/runtime baseline")
    parser.add_argument("--reborn-root", type=Path, help="unpacked Reborn source root")
    parser.add_argument("--swarm-abil-data", type=Path, default=DEFAULT_SWARM_ABIL_DATA, help="Swarm campaign inherited AbilData.xml")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.reborn_root if args.reborn_root is not None else find_reborn_root()
    baseline = build_baseline(root, args.swarm_abil_data)
    write_json(args.out, baseline)
    print(f"wrote {args.out}: {baseline['larva']['command_count']} card commands, {len(baseline['roster']['catalog_unit_ids'])} catalog units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
