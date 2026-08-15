#!/usr/bin/env python3
"""End-to-end runtime probe for the staged 斗蛐蛐 behavior plugin.

The launcher owns the SC2 process. This probe owns one API game session and
drives the map through the registered Vibe functions, then observes the real
unit state and the plugin's debug-bank markers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.vibe_host import RpcRequest, read_bank, write_bank_request  # noqa: E402
from s2clientprotocol import common_pb2, query_pb2, raw_pb2, sc2api_pb2 as sc_pb  # noqa: E402


MARKERS = {
    "reaver": "douququ_reaver_scarab_impact",
    "vulture_refill": "douququ_vulture_refill",
    "vulture_death": "douququ_vulture_death_mines",
    "banshee": "douququ_banshee_hatch",
    "broodlord": "douququ_broodlord_projectile",
    "hydralisk": "douququ_hydralisk_heal",
    "kerrigan": "douququ_kerrigan_broodlings",
}


class ProbeError(RuntimeError):
    pass


def _bank_targets(name: str) -> list[Path]:
    root = Path.home() / "Documents" / "StarCraft II" / "Banks"
    targets = [root / f"{name}.SC2Bank"]
    if root.is_dir():
        targets.extend(
            child / f"{name}.SC2Bank"
            for child in root.iterdir()
            if child.is_dir() and child.name.isdigit()
        )
    return targets


def clear_bank(name: str) -> None:
    root = ET.Element("Bank", version="1")
    for section_name in ("index", "request", "response"):
        ET.SubElement(root, "Section", name=section_name)
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    for target in _bank_targets(name):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\xef\xbb\xbf" + payload)


def _json_response(bank_name: str, request_id: str) -> dict[str, Any] | None:
    raw = read_bank(bank_name).get("response", {}).get(request_id)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"malformed Bank response {request_id}: {raw}") from exc
    if not isinstance(value, dict):
        raise ProbeError(f"non-object Bank response {request_id}")
    return value


def _unit_alive(unit: Any) -> bool:
    if hasattr(unit, "health") and float(unit.health) <= 0:
        return False
    return True


class DouQuquRuntimeProbe:
    def __init__(self, port: int, map_path: Path, out_dir: Path) -> None:
        self.port = port
        self.map_path = map_path.resolve()
        self.out_dir = out_dir.resolve()
        self.session_id = f"dou-ququ-runtime-{uuid.uuid4().hex[:12]}"
        self.sequence = 0
        self.ws: Any = None
        self.http: aiohttp.ClientSession | None = None
        self.unit_names: dict[int, str] = {}
        self.ability_names: dict[int, str] = {}
        self.ability_ids: dict[str, int] = {}
        self.calls: list[dict[str, Any]] = []
        self.checks: dict[str, dict[str, Any]] = {}

    async def send(self, request: sc_pb.Request, timeout: float = 30.0) -> sc_pb.Response:
        if self.ws is None:
            raise ProbeError("SC2 websocket is not connected")
        await self.ws.send_bytes(request.SerializeToString())
        raw = await asyncio.wait_for(self.ws.receive_bytes(), timeout=timeout)
        response = sc_pb.Response()
        response.ParseFromString(raw)
        if response.error:
            raise ProbeError(f"SC2 API error: {list(response.error)}")
        return response

    async def step(self, count: int = 16) -> None:
        await self.send(sc_pb.Request(step=sc_pb.RequestStep(count=max(1, int(count)))))

    async def create_and_join(self) -> None:
        # A fresh launcher session has no game to leave; SC2 reports that
        # normal state as an API error, so cleanup must be best-effort.
        try:
            await self.send(sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=10.0)
        except ProbeError as exc:
            if "A game has not been started yet" not in str(exc):
                raise
        await asyncio.sleep(0.5)
        setup = [
            sc_pb.PlayerSetup(type=1, race=1, player_name="ProbeP1"),
            sc_pb.PlayerSetup(type=2, race=1, difficulty=1, player_name="ProbeP2"),
        ]
        normalized = str(self.map_path).replace("\\", "/")
        response = await self.send(
            sc_pb.Request(
                create_game=sc_pb.RequestCreateGame(
                    local_map=sc_pb.LocalMap(map_path=normalized),
                    player_setup=setup,
                    realtime=False,
                )
            ),
            timeout=60.0,
        )
        if response.create_game.HasField("error"):
            raise ProbeError(f"CreateGame failed: {response.create_game.error_details}")
        joined = await self.send(
            sc_pb.Request(
                join_game=sc_pb.RequestJoinGame(
                    race=1,
                    options=sc_pb.InterfaceOptions(
                        raw=True,
                        score=True,
                        show_cloaked=True,
                        show_burrowed_shadows=True,
                        show_placeholders=True,
                    ),
                )
            ),
            timeout=30.0,
        )
        self.calls.append(
            {
                "operation": "CreateGame+JoinGame",
                "map": normalized,
                "player_id": int(joined.join_game.player_id),
            }
        )
        await self.step(64)

    async def load_data(self) -> None:
        response = await self.send(
            sc_pb.Request(data=sc_pb.RequestData(ability_id=True, unit_type_id=True)),
            timeout=60.0,
        )
        for entry in response.data.units:
            self.unit_names[int(entry.unit_id)] = str(entry.name)
        for entry in response.data.abilities:
            name = str(entry.link_name)
            self.ability_names[int(entry.ability_id)] = name
            self.ability_ids.setdefault(name, int(entry.ability_id))

    async def rpc(self, function_id: str, args: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        request_id = uuid.uuid4().hex[:12]
        request = RpcRequest(
            session_id=self.session_id,
            request_id=request_id,
            sequence=self.sequence,
            operation="function.invoke",
            args={"function_id": function_id, "args": args},
        )
        if not write_bank_request("GalaxyVibe", request_id, request):
            raise ProbeError(f"could not write Vibe request {function_id}")
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            response = _json_response("GalaxyVibe", request_id)
            if response is not None:
                error_code = response.get("error_code", "")
                payload = response.get("payload", {})
                record = {
                    "function_id": function_id,
                    "args": args,
                    "error_code": error_code,
                    "payload": payload,
                    "sequence": self.sequence,
                }
                self.calls.append(record)
                if response.get("kind") != "result" or error_code != "OK":
                    raise ProbeError(f"Vibe {function_id} failed: {error_code} {payload}; args={args}")
                return payload if isinstance(payload, dict) else {}
            await self.step(1)
            await asyncio.sleep(0.05)
        index = read_bank("GalaxyVibe").get("index", {})
        raise ProbeError(f"Vibe request timed out: {function_id}; index={index}")

    async def observe(self) -> dict[str, Any]:
        response = await self.send(sc_pb.Request(observation=sc_pb.RequestObservation()))
        observation = response.observation.observation
        raw = observation.raw_data
        units: list[dict[str, Any]] = []
        if raw is not None:
            for unit in raw.units:
                if not _unit_alive(unit):
                    continue
                units.append(
                    {
                        "tag": int(unit.tag),
                        "type_id": int(unit.unit_type),
                        "type": self.unit_names.get(int(unit.unit_type), f"unknown:{unit.unit_type}"),
                        "owner": int(unit.owner),
                        "x": round(float(unit.pos.x), 3),
                        "y": round(float(unit.pos.y), 3),
                        "health": round(float(getattr(unit, "health", 0.0)), 3),
                        "health_max": round(float(getattr(unit, "health_max", 0.0)), 3),
                        "energy": round(float(getattr(unit, "energy", 0.0)), 3),
                    }
                )
        minerals = None
        common = getattr(observation, "player_common", None)
        if common is not None:
            minerals = int(getattr(common, "minerals", 0))
        return {
            "game_loop": int(getattr(observation, "game_loop", 0)),
            "minerals": minerals,
            "units": units,
        }

    async def snapshot(self) -> dict[str, Any]:
        return {
            "observation": await self.observe(),
            "debug_bank": read_bank("CMRERebornDebug"),
        }

    async def spawn_group(self, unit_type: str, count: int, owner: int, x: float, y: float) -> list[int]:
        payload = await self.rpc(
            "vibe.unit.spawn_group",
            {"unit_type": unit_type, "count": count, "player": owner, "x": x, "y": y},
        )
        tags = payload.get("unit_tags", [])
        if not isinstance(tags, list) or len(tags) != count:
            raise ProbeError(f"spawn_group returned unexpected tags for {unit_type}: {payload}")
        await self.step(8)
        return [int(tag) for tag in tags]

    async def spawn_pairs(
        self,
        unit_type: str,
        count: int,
        owner: int,
        x: float,
        y: float,
        spacing: float,
    ) -> list[int]:
        tags: list[int] = []
        for index in range(count):
            tags.extend(await self.spawn_group(unit_type, 1, owner, x + index * spacing, y))
        return tags

    async def set_vital(self, tag: int, vital: str, value: float) -> None:
        await self.rpc("vibe.unit.set_vital", {"unit_tag": tag, "vital": vital, "value": value})

    async def attack(self, attacker: int, target: int) -> None:
        await self.rpc("vibe.unit.attack", {"attacker_tag": attacker, "target_tag": target})

    async def kill(self, tag: int) -> None:
        await self.rpc("vibe.unit.kill", {"unit_tag": tag})

    async def unit_ability(self, tag: int, ability: str) -> bool:
        payload = await self.rpc("vibe.unit.query_ability", {"unit_tag": tag, "ability": ability})
        return bool(payload.get("has_ability", False))

    async def issue_ability(self, tag: int, ability: str) -> dict[str, Any]:
        ability_id = self.ability_ids.get(ability)
        if ability_id is None:
            raise ProbeError(f"ability missing from RequestData: {ability}")
        response = await self.send(
            sc_pb.Request(
                action=sc_pb.RequestAction(
                    actions=[
                        sc_pb.Action(
                            action_raw=raw_pb2.ActionRaw(
                                unit_command=raw_pb2.ActionRawUnitCommand(
                                    ability_id=ability_id,
                                    unit_tags=[tag],
                                )
                            )
                        )
                    ]
                )
            )
        )
        await self.step(16)
        return {
            "ability": ability,
            "ability_id": ability_id,
            "action_result": [int(value) for value in response.action.result],
        }

    def counts(self, snapshot: dict[str, Any], owner: int, unit_type: str) -> int:
        return sum(
            item["owner"] == owner and item["type"] == unit_type
            for item in snapshot["observation"]["units"]
        )

    async def wait_for(self, predicate, *, steps: int = 80, step_count: int = 16) -> dict[str, Any]:
        last = await self.snapshot()
        for _ in range(steps):
            await self.step(step_count)
            await asyncio.sleep(0.02)
            last = await self.snapshot()
            if predicate(last):
                return last
        return last

    def marker_set(self, snapshot: dict[str, Any], marker: str) -> bool:
        return snapshot.get("debug_bank", {}).get("debug", {}).get(marker) == 1

    def record_check(self, name: str, passed: bool, **evidence: Any) -> None:
        self.checks[name] = {"passed": bool(passed), **evidence}

    async def run_checks(self) -> None:
        baseline = await self.snapshot()
        await self.rpc("vibe.test.ping", {"nonce": "dou-ququ-runtime"})

        reavers = await self.spawn_pairs("Reaver", 10, 1, 65.0, 70.0, 1.5)
        reaver_targets = await self.spawn_pairs("Marine", 10, 2, 95.0, 70.0, 1.5)
        for attacker, target in zip(reavers, reaver_targets):
            await self.attack(attacker, target)
        reaver_after = await self.wait_for(
            lambda snap: self.marker_set(snap, MARKERS["reaver"])
            or self.counts(snap, 1, "Zealot") > self.counts(baseline, 1, "Zealot"),
            steps=90,
            step_count=16,
        )
        zealot_delta = self.counts(reaver_after, 1, "Zealot") - self.counts(baseline, 1, "Zealot")
        self.record_check(
            "reaver_scarab",
            self.marker_set(reaver_after, MARKERS["reaver"]) and 1 <= zealot_delta <= 30,
            marker=self.marker_set(reaver_after, MARKERS["reaver"]),
            zealot_delta=zealot_delta,
            reaver_count=len(reavers),
            attachment_methods=[10, 11, 13, 14],
        )

        vulture = (await self.spawn_group("Vulture", 1, 1, 30.0, 30.0))[0]
        has_mines = await self.unit_ability(vulture, "VultureSpiderMines")
        has_refill = await self.unit_ability(vulture, "CRV_Vulture_MineRefill")
        if not has_refill:
            await self.rpc("vibe.unit.add_ability", {"unit_tag": vulture, "ability": "CRV_Vulture_MineRefill"})
        await self.rpc("vibe.player.set_resource", {"player": 1, "resource": "minerals", "value": 500})
        before_refill = await self.snapshot()
        refill_action = await self.issue_ability(vulture, "CRV_Vulture_MineRefill")
        refill_after = await self.wait_for(
            lambda snap: self.marker_set(snap, MARKERS["vulture_refill"]),
            steps=24,
            step_count=8,
        )
        minerals_before = before_refill["observation"]["minerals"]
        minerals_after = refill_after["observation"]["minerals"]
        refill_pass = self.marker_set(refill_after, MARKERS["vulture_refill"])
        if minerals_before is not None and minerals_after is not None:
            refill_pass = refill_pass and minerals_after == minerals_before - 50
        self.record_check(
            "vulture_refill",
            refill_pass and has_mines,
            has_mine_ability=has_mines,
            had_refill_ability=has_refill,
            refill_action=refill_action,
            minerals_before=minerals_before,
            minerals_after=minerals_after,
            marker=self.marker_set(refill_after, MARKERS["vulture_refill"]),
            expected_storage=5,
        )
        before_mines = self.counts(refill_after, 1, "SpiderMine")
        await self.kill(vulture)
        death_after = await self.wait_for(
            lambda snap: self.marker_set(snap, MARKERS["vulture_death"])
            and self.counts(snap, 1, "SpiderMine") >= before_mines + 3,
            steps=32,
            step_count=8,
        )
        self.record_check(
            "vulture_death_mines",
            self.marker_set(death_after, MARKERS["vulture_death"])
            and self.counts(death_after, 1, "SpiderMine") >= before_mines + 3,
            marker=self.marker_set(death_after, MARKERS["vulture_death"]),
            spider_mines_before=before_mines,
            spider_mines_after=self.counts(death_after, 1, "SpiderMine"),
        )

        banshee = (await self.spawn_group("InfestedBanshee", 1, 1, 55.0, 35.0))[0]
        await self.set_vital(banshee, "energy", 20.0)
        before_banshee = await self.snapshot()
        banshee_after = await self.wait_for(
            lambda snap: self.marker_set(snap, MARKERS["banshee"]),
            steps=24,
            step_count=16,
        )
        self.record_check(
            "infested_banshee_hatch",
            self.marker_set(banshee_after, MARKERS["banshee"])
            and self.counts(banshee_after, 1, "Marine") >= self.counts(before_banshee, 1, "Marine") + 1,
            marker=self.marker_set(banshee_after, MARKERS["banshee"]),
            marine_before=self.counts(before_banshee, 1, "Marine"),
            marine_after=self.counts(banshee_after, 1, "Marine"),
        )

        broodlords = await self.spawn_pairs("BroodLord", 12, 1, 45.0, 90.0, 1.5)
        brood_targets = await self.spawn_pairs("Overlord", 12, 2, 80.0, 90.0, 1.5)
        before_broodlord = await self.snapshot()
        for attacker, target in zip(broodlords, brood_targets):
            await self.attack(attacker, target)
        broodlord_after = await self.wait_for(
            lambda snap: self.marker_set(snap, MARKERS["broodlord"])
            or self.counts(snap, 1, "Baneling") > self.counts(before_broodlord, 1, "Baneling"),
            steps=90,
            step_count=16,
        )
        self.record_check(
            "broodlord_projectile",
            self.marker_set(broodlord_after, MARKERS["broodlord"])
            and self.counts(broodlord_after, 1, "Baneling") > self.counts(before_broodlord, 1, "Baneling"),
            marker=self.marker_set(broodlord_after, MARKERS["broodlord"]),
            baneling_before=self.counts(before_broodlord, 1, "Baneling"),
            baneling_after=self.counts(broodlord_after, 1, "Baneling"),
            projectile_unit="CRV_BroodLord_BanelingProjectile",
        )

        hydra = (await self.spawn_group("Hydralisk", 1, 1, 90.0, 30.0))[0]
        hydra_target = (await self.spawn_group("Marine", 1, 2, 108.0, 30.0))[0]
        await self.set_vital(hydra, "life", 20.0)
        await self.set_vital(hydra_target, "life", 1.0)
        before_hydra = await self.rpc("vibe.unit.query_attrs", {"unit_tag": hydra})
        await self.attack(hydra, hydra_target)
        hydra_after = await self.wait_for(
            lambda snap: self.marker_set(snap, MARKERS["hydralisk"]),
            steps=48,
            step_count=8,
        )
        after_hydra = await self.rpc("vibe.unit.query_attrs", {"unit_tag": hydra})
        self.record_check(
            "hydralisk_kill_heal",
            self.marker_set(hydra_after, MARKERS["hydralisk"])
            and float(after_hydra.get("life", 0.0)) > float(before_hydra.get("life", 0.0)),
            marker=self.marker_set(hydra_after, MARKERS["hydralisk"]),
            life_before=before_hydra.get("life"),
            life_after=after_hydra.get("life"),
        )

        kerrigan = (await self.spawn_group("K5Kerrigan", 1, 1, 90.0, 50.0))[0]
        kerrigan_target = (await self.spawn_group("Marine", 1, 2, 115.0, 50.0))[0]
        await self.set_vital(kerrigan_target, "life", 1.0)
        before_kerrigan = await self.snapshot()
        await self.attack(kerrigan, kerrigan_target)
        kerrigan_after = await self.wait_for(
            lambda snap: self.marker_set(snap, MARKERS["kerrigan"]),
            steps=64,
            step_count=8,
        )
        self.record_check(
            "kerrigan_broodlings",
            self.marker_set(kerrigan_after, MARKERS["kerrigan"])
            and self.counts(kerrigan_after, 1, "KerriganInfestBroodling")
            >= self.counts(before_kerrigan, 1, "KerriganInfestBroodling") + 2,
            marker=self.marker_set(kerrigan_after, MARKERS["kerrigan"]),
            broodlings_before=self.counts(before_kerrigan, 1, "KerriganInfestBroodling"),
            broodlings_after=self.counts(kerrigan_after, 1, "KerriganInfestBroodling"),
        )

    async def run(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schemaVersion": 1,
            "classification": "runtime",
            "mapLabel": "斗蛐蛐",
            "forbiddenMap": "亡者之夜",
            "map": str(self.map_path),
            "port": self.port,
            "sessionId": self.session_id,
            "checks": self.checks,
        }
        clear_bank("GalaxyVibe")
        clear_bank("CMRERebornDebug")
        if self.http is None:
            self.http = aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=None))
        try:
            async with self.http.ws_connect(f"ws://127.0.0.1:{self.port}/sc2api", max_msg_size=0) as ws:
                self.ws = ws
                ping = await self.send(sc_pb.Request(ping=sc_pb.RequestPing()))
                result["apiPing"] = not ping.error
                await self.create_and_join()
                await self.load_data()
                result["catalog"] = {
                    "unitTypeCount": len(self.unit_names),
                    "abilityCount": len(self.ability_names),
                    "requiredUnits": {
                        name: name in self.unit_names.values()
                        for name in (
                            "Reaver", "Vulture", "InfestedBanshee", "BroodLord",
                            "Hydralisk", "K5Kerrigan", "KerriganInfestBroodling", "Baneling",
                        )
                    },
                    "requiredAbilities": {
                        name: name in self.ability_ids
                        for name in ("CRV_Vulture_MineRefill", "VultureSpiderMines")
                    },
                }
                await self.run_checks()
                result["calls"] = self.calls
                result["checks"] = self.checks
                result["finalSnapshot"] = await self.snapshot()
        finally:
            self.ws = None
            if self.http is not None:
                await self.http.close()
                self.http = None
        result["verdict"] = {
            "allChecksPassed": bool(self.checks) and all(item["passed"] for item in self.checks.values()),
            "checkCount": len(self.checks),
            "passedCount": sum(item["passed"] for item in self.checks.values()),
        }
        result["verdict"]["overall"] = "PASS" if result["verdict"]["allChecksPassed"] else "FAIL"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "dou-ququ-runtime-evidence.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result


async def main_async(args: argparse.Namespace) -> int:
    result = await DouQuquRuntimeProbe(args.port, Path(args.map_path), Path(args.out_dir)).run()
    print(json.dumps(result["verdict"], ensure_ascii=False, indent=2))
    return 0 if result["verdict"]["overall"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--map-path", required=True)
    parser.add_argument("--out-dir", required=True)
    try:
        return asyncio.run(main_async(parser.parse_args()))
    except (OSError, ProbeError, aiohttp.ClientError) as exc:
        print(f"[dou-ququ-runtime] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
