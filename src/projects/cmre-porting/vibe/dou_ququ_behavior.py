"""Deterministic VM specification for the opt-in 斗蛐蛐 behavior plugin.

The VM deliberately models event boundaries instead of pretending to be SC2.
Galaxy/Data runtime evidence is collected separately by the stage workflow.
"""
from __future__ import annotations

import asyncio
import copy
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .debug_vm import DebugVm


PLUGIN_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PLUGIN_ROOT / "dou_ququ_behavior.json"


class DouQuquError(ValueError):
    """A fail-closed plugin request error."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise DouQuquError("INVALID_CONFIG", "schemaVersion 1 is required")
    for key in ("units", "rules", "functions"):
        if not isinstance(data.get(key), dict):
            raise DouQuquError("INVALID_CONFIG", f"{key} must be an object")
    return data


def load_function_metadata(path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    return copy.deepcopy(load_config(path)["functions"])


@dataclass
class DouQuquUnit:
    tag: int
    unit_type: str
    owner: int
    x: float
    y: float
    life_max: float
    life: float
    energy_max: float
    energy: float
    storage_max: int = 0
    stored_mines: int = 0
    generated_by: int | None = None
    generated_kind: str | None = None
    alive: bool = True

    def snapshot(self) -> dict[str, Any]:
        result = asdict(self)
        result["position"] = {"x": self.x, "y": self.y}
        result.pop("x")
        result.pop("y")
        return result


class DouQuquWorld:
    """Small deterministic event world used by the runtime plugin."""

    def __init__(self, config: Mapping[str, Any] | None = None, *, seed: int = 42) -> None:
        self.config = copy.deepcopy(dict(config or load_config()))
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.clock = 0.0
        self.version = 0
        self.next_tag = 1
        self.units: dict[int, DouQuquUnit] = {}
        self.minerals: dict[int, int] = {}
        self.generated_zealots_by_reaver: dict[int, int] = {}
        self.banshee_elapsed: dict[int, float] = {}
        self.proc_chance_overrides: dict[str, int] = {}
        self.events: list[dict[str, Any]] = []
        self.reset(seed=self.seed)

    def reset(self, *, seed: int | None = None) -> dict[str, Any]:
        if seed is not None:
            self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.clock = 0.0
        self.version = 0
        self.next_tag = 1
        self.units = {}
        initial_minerals = int(self.config.get("initialMinerals", 500))
        self.minerals = {1: initial_minerals, 2: initial_minerals}
        self.generated_zealots_by_reaver = {}
        self.banshee_elapsed = {}
        self.proc_chance_overrides = {}
        self.events = []
        return self.snapshot()

    def _touch(self, event: str, **fields: Any) -> dict[str, Any]:
        self.version += 1
        record = {"event": event, "time": round(self.clock, 3), **fields}
        self.events.append(record)
        return record

    def _unit(self, tag: int, *, alive: bool = True) -> DouQuquUnit:
        try:
            unit = self.units[int(tag)]
        except (KeyError, ValueError) as exc:
            raise DouQuquError("UNIT_NOT_FOUND", str(tag)) from exc
        if alive and not unit.alive:
            raise DouQuquError("UNIT_DEAD", str(tag))
        return unit

    def _unit_defaults(self, unit_type: str) -> Mapping[str, Any]:
        defaults = self.config["units"].get(unit_type)
        if not isinstance(defaults, dict):
            raise DouQuquError("UNIT_TYPE_NOT_SUPPORTED", unit_type)
        return defaults

    def spawn(
        self,
        unit_type: str,
        owner: int,
        x: float = 0.0,
        y: float = 0.0,
        *,
        energy: float | None = None,
        life: float | None = None,
        generated_by: int | None = None,
        generated_kind: str | None = None,
    ) -> DouQuquUnit:
        defaults = self._unit_defaults(unit_type)
        tag = self.next_tag
        self.next_tag += 1
        life_max = float(defaults.get("lifeMax", 100.0))
        energy_max = float(defaults.get("energyMax", 0.0))
        storage_rule = self.config["rules"].get("vultureStorage", {})
        is_vulture = unit_type == storage_rule.get("sourceUnit", "Vulture")
        storage_max = (
            int(storage_rule.get("baseStorage", 3)) + int(storage_rule.get("storageBonus", 2))
            if is_vulture
            else 0
        )
        unit = DouQuquUnit(
            tag=tag,
            unit_type=unit_type,
            owner=int(owner),
            x=float(x),
            y=float(y),
            life_max=life_max,
            life=life_max if life is None else max(0.0, min(float(life), life_max)),
            energy_max=energy_max,
            energy=energy_max if energy is None else max(0.0, min(float(energy), energy_max)),
            storage_max=storage_max,
            stored_mines=storage_max,
            generated_by=generated_by,
            generated_kind=generated_kind,
        )
        self.units[tag] = unit
        if unit_type == self.config["rules"].get("infestedBansheeHatch", {}).get("sourceUnit"):
            self.banshee_elapsed[tag] = 0.0
        self._touch(
            "unit_spawned",
            unit=unit_type,
            tag=tag,
            owner=int(owner),
            position={"x": unit.x, "y": unit.y},
            generatedBy=generated_by,
            generatedKind=generated_kind,
        )
        return unit

    def set_minerals(self, owner: int, minerals: int) -> dict[str, Any]:
        if int(owner) < 0 or int(owner) > 15:
            raise DouQuquError("PLAYER_INVALID", str(owner))
        if int(minerals) < 0:
            raise DouQuquError("MINERALS_INVALID", str(minerals))
        self.minerals[int(owner)] = int(minerals)
        self._touch("minerals_set", owner=int(owner), minerals=int(minerals))
        return {"owner": int(owner), "minerals": self.minerals[int(owner)]}

    def set_energy(self, tag: int, energy: float) -> dict[str, Any]:
        unit = self._unit(tag)
        if energy < 0.0:
            raise DouQuquError("ENERGY_INVALID", str(energy))
        unit.energy = min(float(energy), unit.energy_max)
        self.version += 1
        return unit.snapshot()

    def set_life(self, tag: int, life: float) -> dict[str, Any]:
        unit = self._unit(tag, alive=False)
        if life < 0.0:
            raise DouQuquError("LIFE_INVALID", str(life))
        unit.life = min(float(life), unit.life_max)
        unit.alive = unit.life > 0.0
        self.version += 1
        return unit.snapshot()

    def _chance(self, rule: Mapping[str, Any], key: str, override_key: str | None = None) -> tuple[int, int, bool]:
        roll = self.rng.randint(1, 100)
        chance = self.proc_chance_overrides.get(override_key or "", int(rule.get(key, 0)))
        return roll, chance, roll <= chance

    def proc_chances(self) -> dict[str, int]:
        reaver = self.config["rules"].get("reaverAttack", {})
        brood_lord = self.config["rules"].get("broodLordAttack", {})
        return {
            "reaverOrdinaryPercent": self.proc_chance_overrides.get("reaver_ordinary_percent", int(reaver.get("ordinaryChancePercent", 20))),
            "reaverKillPercent": self.proc_chance_overrides.get("reaver_kill_percent", int(reaver.get("killChancePercent", 30))),
            "broodLordPercent": self.proc_chance_overrides.get("broodlord_percent", int(brood_lord.get("chancePercent", 15))),
        }

    def set_proc_chances(self, reaver_ordinary_percent: int, reaver_kill_percent: int, broodlord_percent: int) -> dict[str, int]:
        values = {
            "reaver_ordinary_percent": int(reaver_ordinary_percent),
            "reaver_kill_percent": int(reaver_kill_percent),
            "broodlord_percent": int(broodlord_percent),
        }
        if any(value < 0 or value > 100 for value in values.values()):
            raise DouQuquError("CHANCE_PERCENT_INVALID", str(values))
        self.proc_chance_overrides = values
        self._touch("proc_chances_set", **self.proc_chances())
        return self.proc_chances()

    def reset_proc_chances(self) -> dict[str, int]:
        self.proc_chance_overrides = {}
        self._touch("proc_chances_reset", **self.proc_chances())
        return self.proc_chances()

    def _spawn_at(
        self,
        unit_type: str,
        owner: int,
        x: float,
        y: float,
        count: int,
        cause: str,
        *,
        generated_by: int | None = None,
        generated_kind: str | None = None,
    ) -> list[int]:
        tags = [
            self.spawn(
                unit_type,
                owner,
                x,
                y,
                generated_by=generated_by,
                generated_kind=generated_kind,
            ).tag
            for _ in range(int(count))
        ]
        self._touch(
            "effect_spawned",
            cause=cause,
            unit=unit_type,
            tags=tags,
            owner=owner,
            position={"x": float(x), "y": float(y)},
        )
        return tags

    def reaver_scarab_impact(
        self,
        attacker_tag: int,
        victim_tag: int,
        fatal: bool,
        impact_x: float,
        impact_y: float,
    ) -> dict[str, Any]:
        attacker = self._unit(attacker_tag)
        victim = self._unit(victim_tag, alive=False)
        rule = self.config["rules"].get("reaverAttack", {})
        result: dict[str, Any] = {
            "attacker": attacker.tag,
            "victim": victim.tag,
            "fatal": bool(fatal),
            "impactPoint": {"x": float(impact_x), "y": float(impact_y)},
            "triggered": False,
            "spawned": [],
        }
        if attacker.unit_type != rule.get("sourceUnit") or attacker.owner == victim.owner:
            self._touch("scarab_impact_ignored", **result)
            return result
        chance_key = "killChancePercent" if fatal else "ordinaryChancePercent"
        override_key = "reaver_kill_percent" if fatal else "reaver_ordinary_percent"
        roll, chance, triggered = self._chance(rule, chance_key, override_key)
        result.update({"roll": roll, "chancePercent": chance, "triggered": triggered})
        if triggered:
            current = self.generated_zealots_by_reaver.get(attacker.tag, 0)
            maximum = int(rule.get("maxActiveGenerated", 3))
            if current >= maximum:
                result["triggered"] = False
                result["blocked"] = "max_active_generated"
            else:
                spawned = self._spawn_at(
                    str(rule["spawnUnit"]),
                    attacker.owner,
                    float(impact_x),
                    float(impact_y),
                    int(rule.get("spawnCount", 1)),
                    "reaver_scarab_kill" if fatal else "reaver_scarab_hit",
                    generated_by=attacker.tag,
                    generated_kind="reaver_scarab_zealot",
                )
                self.generated_zealots_by_reaver[attacker.tag] = current + len(spawned)
                result["spawned"] = spawned
                result["activeGenerated"] = self.generated_zealots_by_reaver[attacker.tag]
        self._touch("scarab_impact", **result)
        return result

    def on_attack(self, attacker_tag: int, target_tag: int) -> dict[str, Any]:
        attacker = self._unit(attacker_tag)
        target = self._unit(target_tag)
        impact = {"x": target.x, "y": target.y}
        reaver_rule = self.config["rules"].get("reaverAttack", {})
        if attacker.unit_type == reaver_rule.get("sourceUnit"):
            return self.reaver_scarab_impact(attacker.tag, target.tag, False, impact["x"], impact["y"])

        rule = self.config["rules"].get("broodLordAttack", {})
        result: dict[str, Any] = {
            "attacker": attacker.tag,
            "target": target.tag,
            "attackerType": attacker.unit_type,
            "triggered": False,
            "spawned": [],
        }
        if attacker.unit_type != rule.get("sourceUnit") or attacker.owner == target.owner:
            self._touch("attack_ignored", **result)
            return result
        roll, chance, triggered = self._chance(rule, "chancePercent", "broodlord_percent")
        result.update({"roll": roll, "chancePercent": chance, "triggered": triggered})
        if triggered:
            # This is metadata for the real CEffectLaunchMissile chain. The VM
            # must not turn a projectile proc into a target-point unit spawn.
            result["projectile"] = {
                "unit": rule["projectileUnit"],
                "launchEffect": rule["launchEffect"],
                "target": {"x": target.x, "y": target.y},
            }
            self._touch("brood_lord_projectile_requested", **result)
        else:
            self._touch("attack_checked", **result)
        return result

    def on_death(self, victim_tag: int) -> dict[str, Any]:
        victim = self._unit(victim_tag)
        victim.alive = False
        victim.life = 0.0
        spawned: list[int] = []
        if victim.generated_kind == "reaver_scarab_zealot" and victim.generated_by is not None:
            current = self.generated_zealots_by_reaver.get(victim.generated_by, 0)
            self.generated_zealots_by_reaver[victim.generated_by] = max(0, current - 1)
            self._touch(
                "reaver_zealot_slot_released",
                reaver=victim.generated_by,
                zealot=victim.tag,
                activeGenerated=self.generated_zealots_by_reaver[victim.generated_by],
            )
        rule = self.config["rules"].get("vultureDeath", {})
        if victim.unit_type == rule.get("sourceUnit"):
            spawned = self._spawn_at(
                str(rule["spawnUnit"]), victim.owner, victim.x, victim.y,
                int(rule.get("spawnCount", 3)), "vulture_death",
            )
        self._touch("unit_died", victim=victim.tag, unit=victim.unit_type, spawned=spawned)
        return {"victim": victim.tag, "alreadyDead": False, "spawned": spawned}

    def on_kill(self, killer_tag: int, victim_tag: int) -> dict[str, Any]:
        killer = self._unit(killer_tag)
        victim = self._unit(victim_tag)
        death = self.on_death(victim.tag)
        result: dict[str, Any] = {
            "killer": killer.tag,
            "victim": victim.tag,
            "healed": 0.0,
            "spawned": list(death["spawned"]),
            "enemy": killer.owner != victim.owner,
        }
        if not result["enemy"]:
            self._touch("unit_kill_ignored", **result)
            return result

        reaver_rule = self.config["rules"].get("reaverAttack", {})
        if killer.unit_type == reaver_rule.get("sourceUnit"):
            scarab = self.reaver_scarab_impact(killer.tag, victim.tag, True, victim.x, victim.y)
            result["scarabImpact"] = scarab
            result["spawned"].extend(scarab["spawned"])

        hydra_rule = self.config["rules"].get("hydraliskKill", {})
        if killer.unit_type == hydra_rule.get("sourceUnit"):
            before = killer.life
            killer.life = min(killer.life_max, killer.life + float(hydra_rule.get("healAmount", 25.0)))
            result["healed"] = killer.life - before

        kerrigan_rule = self.config["rules"].get("kerriganKill", {})
        whitelist = set(kerrigan_rule.get("killerWhitelist", []))
        if killer.unit_type in whitelist and killer.generated_kind != "kerrigan_kill_broodling":
            broodlings = self._spawn_at(
                str(kerrigan_rule["spawnUnit"]), killer.owner, victim.x, victim.y,
                int(kerrigan_rule.get("spawnCount", 2)), "kerrigan_kill",
                generated_by=killer.tag,
                generated_kind="kerrigan_kill_broodling",
            )
            result["spawned"].extend(broodlings)
            result["kerriganBroodlings"] = broodlings
        self._touch("unit_kill_processed", **result)
        return result

    def banshee_hatch(
        self,
        unit_tag: int,
        *,
        requested_energy: int | None = None,
        requested_count: int | None = None,
    ) -> dict[str, Any]:
        unit = self._unit(unit_tag)
        rule = self.config["rules"].get("infestedBansheeHatch", {})
        if unit.unit_type != rule.get("sourceUnit"):
            raise DouQuquError("UNIT_TYPE_INVALID", unit.unit_type)
        if requested_count is None:
            if requested_energy is None:
                raise DouQuquError("HATCH_REQUEST_REQUIRED", "requested_energy or requested_count")
            energy_cost = float(rule.get("energyCost", 20.0))
            if requested_energy not in (20, 40, 60, 80):
                raise DouQuquError("HATCH_TIER_INVALID", str(requested_energy))
            requested_count = int(requested_energy // energy_cost)
        if int(requested_count) not in (1, 2, 3, 4):
            raise DouQuquError("HATCH_COUNT_INVALID", str(requested_count))
        cost = int(requested_count * float(rule.get("energyCost", 20.0)))
        if unit.energy < cost:
            return {"unit": unit.tag, "status": "insufficient_energy", "energy": unit.energy, "cost": cost, "spawned": []}
        unit.energy -= cost
        spawned = self._spawn_at(
            str(rule["spawnUnit"]), unit.owner, unit.x, unit.y,
            int(requested_count), "infested_banshee_hatch",
        )
        self._touch("banshee_hatched", caster=unit.tag, count=int(requested_count), cost=cost, spawned=spawned)
        return {"unit": unit.tag, "status": "hatched", "energy": unit.energy, "cost": cost, "spawned": spawned}

    def tick(self, seconds: float) -> dict[str, Any]:
        if seconds < 0.0:
            raise DouQuquError("TIME_INVALID", str(seconds))
        self.clock += float(seconds)
        spawned: list[int] = []
        rule = self.config["rules"].get("infestedBansheeHatch", {})
        interval = float(rule.get("intervalSeconds", 10.0))
        energy_cost = float(rule.get("energyCost", 20.0))
        # Hatchlings are added to self.units during the loop. Iterate over a
        # snapshot so a periodic proc cannot invalidate the active iterator.
        for unit in list(self.units.values()):
            if not unit.alive or unit.unit_type != rule.get("sourceUnit"):
                continue
            elapsed = self.banshee_elapsed.get(unit.tag, 0.0) + float(seconds)
            while elapsed >= interval:
                elapsed -= interval
                if unit.energy < energy_cost:
                    continue
                unit.energy -= energy_cost
                spawned.extend(self._spawn_at(
                    str(rule["spawnUnit"]), unit.owner, unit.x, unit.y,
                    int(rule.get("spawnCount", 1)), "infested_banshee_interval",
                ))
            self.banshee_elapsed[unit.tag] = elapsed
        self._touch("tick", seconds=float(seconds))
        return {"seconds": float(seconds), "clock": self.clock, "spawned": spawned}

    def refill_vulture(self, tag: int) -> dict[str, Any]:
        unit = self._unit(tag)
        rule = self.config["rules"].get("vultureStorage", {})
        if unit.unit_type != rule.get("sourceUnit"):
            raise DouQuquError("UNIT_TYPE_INVALID", unit.unit_type)
        if unit.stored_mines >= unit.storage_max:
            return {"unit": tag, "status": "already_full", "minerals": self.minerals.get(unit.owner, 0)}
        cost = int(rule.get("refillCost", 50))
        minerals = self.minerals.get(unit.owner, 0)
        if minerals < cost:
            return {"unit": tag, "status": "insufficient_minerals", "minerals": minerals, "cost": cost}
        self.minerals[unit.owner] = minerals - cost
        unit.stored_mines = unit.storage_max
        self._touch("vulture_refilled", unit=tag, cost=cost, minerals=self.minerals[unit.owner])
        return {"unit": tag, "status": "refilled", "storedMines": unit.stored_mines, "minerals": self.minerals[unit.owner]}

    def consume_mines(self, tag: int, count: int = 1) -> dict[str, Any]:
        unit = self._unit(tag)
        rule = self.config["rules"].get("vultureStorage", {})
        if unit.unit_type != rule.get("sourceUnit"):
            raise DouQuquError("UNIT_TYPE_INVALID", unit.unit_type)
        if count <= 0:
            raise DouQuquError("MINE_COUNT_INVALID", str(count))
        if unit.stored_mines < int(count):
            raise DouQuquError("MINES_EMPTY", str(tag))
        unit.stored_mines -= int(count)
        self._touch("vulture_mines_consumed", unit=tag, count=int(count), storedMines=unit.stored_mines)
        return {"unit": tag, "status": "consumed", "storedMines": unit.stored_mines}

    def snapshot(self) -> dict[str, Any]:
        return {
            "clock": self.clock,
            "version": self.version,
            "seed": self.seed,
            "minerals": dict(sorted(self.minerals.items())),
            "activeGeneratedZealots": dict(sorted(self.generated_zealots_by_reaver.items())),
            "units": [unit.snapshot() for unit in sorted(self.units.values(), key=lambda item: item.tag)],
            "events": self.events[-50:],
        }


class DouQuquVmBridge:
    """Explicit function bridge from ``DebugVm`` to the behavior plugin."""

    def __init__(self, *, config: Mapping[str, Any] | None = None, seed: int = 42) -> None:
        self.world = DouQuquWorld(config, seed=seed)
        self._dispatch = {
            "douququ.reset": self._reset,
            "douququ.runtime.set_proc_chances": self._set_proc_chances,
            "douququ.runtime.reset_proc_chances": self._reset_proc_chances,
            "douququ.unit.spawn": self._spawn,
            "douququ.unit.set_energy": self._set_energy,
            "douququ.unit.set_life": self._set_life,
            "douququ.player.set_minerals": self._set_minerals,
            "douququ.attack": self._attack,
            "douququ.reaver.scarab_impact": self._reaver_impact,
            "douququ.kill": self._kill,
            "douququ.banshee.hatch": self._banshee_hatch,
            "douququ.tick": self._tick,
            "douququ.vulture.refill": self._refill,
            "douququ.vulture.consume": self._consume,
            "douququ.snapshot": self._snapshot,
        }

    def _reset(self, args: dict[str, Any]) -> Any:
        return self.world.reset(seed=int(args.get("seed", self.world.seed)))

    def _set_proc_chances(self, args: dict[str, Any]) -> Any:
        return self.world.set_proc_chances(
            args["reaver_ordinary_percent"],
            args["reaver_kill_percent"],
            args["broodlord_percent"],
        )

    def _reset_proc_chances(self, args: dict[str, Any]) -> Any:
        del args
        return self.world.reset_proc_chances()

    def _spawn(self, args: dict[str, Any]) -> Any:
        return self.world.spawn(args["unit_type"], args["owner"], args.get("x", 0.0), args.get("y", 0.0)).snapshot()

    def _set_energy(self, args: dict[str, Any]) -> Any:
        return self.world.set_energy(args["unit_tag"], args["energy"])

    def _set_life(self, args: dict[str, Any]) -> Any:
        return self.world.set_life(args["unit_tag"], args["life"])

    def _set_minerals(self, args: dict[str, Any]) -> Any:
        return self.world.set_minerals(args["owner"], args["minerals"])

    def _attack(self, args: dict[str, Any]) -> Any:
        return self.world.on_attack(args["attacker_tag"], args["target_tag"])

    def _reaver_impact(self, args: dict[str, Any]) -> Any:
        return self.world.reaver_scarab_impact(
            args["attacker_tag"], args["victim_tag"], bool(args.get("fatal", False)),
            args["impact_x"], args["impact_y"],
        )

    def _kill(self, args: dict[str, Any]) -> Any:
        return self.world.on_kill(args["killer_tag"], args["victim_tag"])

    def _banshee_hatch(self, args: dict[str, Any]) -> Any:
        return self.world.banshee_hatch(
            args["unit_tag"],
            requested_energy=args.get("requested_energy"),
            requested_count=args.get("requested_count"),
        )

    def _tick(self, args: dict[str, Any]) -> Any:
        return self.world.tick(args["seconds"])

    def _refill(self, args: dict[str, Any]) -> Any:
        return self.world.refill_vulture(args["unit_tag"])

    def _consume(self, args: dict[str, Any]) -> Any:
        return self.world.consume_mines(args["unit_tag"], args.get("count", 1))

    def _snapshot(self, args: dict[str, Any]) -> Any:
        del args
        return self.world.snapshot()

    def call(self, function_id: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = self._dispatch.get(function_id)
        if handler is None:
            return {"kind": "error", "error_code": "FUNCTION_NOT_FOUND", "state_version": self.world.version, "payload": {"function_id": function_id}}
        try:
            payload = handler(args)
        except DouQuquError as exc:
            return {"kind": "error", "error_code": exc.code, "state_version": self.world.version, "payload": {"reason": exc.code, "detail": exc.detail}}
        return {"kind": "result", "error_code": "OK", "state_version": self.world.version, "payload": payload}

    def step(self, loops: int = 1) -> dict[str, Any]:
        return self.call("douququ.tick", {"seconds": float(loops)})


class DouQuquVm:
    """Convenience owner for the existing typed DebugVm and plugin bridge."""

    def __init__(self, *, config: Mapping[str, Any] | None = None, seed: int = 42, max_instructions: int = 512) -> None:
        config_data = copy.deepcopy(dict(config or load_config()))
        self.bridge = DouQuquVmBridge(config=config_data, seed=seed)
        self.vm = DebugVm(self.bridge, function_metadata=load_function_metadata(), max_instructions=max_instructions)

    async def run(self, program: dict[str, Any]) -> dict[str, Any]:
        return await self.vm.run(program)

    def run_sync(self, program: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.run(program))


def create_dou_ququ_vm(*, config_path: Path = CONFIG_PATH, seed: int = 42) -> DouQuquVm:
    return DouQuquVm(config=load_config(config_path), seed=seed)


__all__ = [
    "DouQuquError", "DouQuquUnit", "DouQuquWorld", "DouQuquVmBridge", "DouQuquVm",
    "create_dou_ququ_vm", "load_config", "load_function_metadata",
]
