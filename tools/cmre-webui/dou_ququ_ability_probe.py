#!/usr/bin/env python3
"""Runtime probe for the user-provided Dou Ququ map.

The source map is never edited. ``prepare`` creates an artifacts-only staging
copy and adds a deterministic hidden-SCV setup used by ``run``. ``run`` then
uses SC2 API raw actions to distinguish catalog visibility, accepted commands,
and the map-owned ``fangzhidanwei`` effect.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
from s2clientprotocol import query_pb2  # noqa: E402
from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

from stage_map_vm_runtime import DEFAULT_DISPATCH, stage_map  # noqa: E402

PACKER = REPO_ROOT / "tools" / "mpq" / "scripts" / "pack-sc2map.ps1"
CUSTOM_ABILITIES = ["fangzhidanwei", "heal", *(f"BeamCaster{i}" for i in range(1, 12))]
ACTION_RESULT_NAMES = {1: "Success", 2: "NotSupported", 3: "Error"}
PROBE_MARKER = "// DOU_QUQU_ABILITY_PROBE_STAGING"
SETUP_FUNCTION = f"""
{PROBE_MARKER}
void douQuquAbilityProbeSetup() {{
    lllzbD(false, true);
    libNtve_gf_ShowHideUnit(lllkDt, true);
    UnitAbilityAdd(lllkDt, \"heal\");
    UnitAbilityAdd(lllkDt, \"BeamCaster1\");
    UnitAbilityAdd(lllkDt, \"BeamCaster2\");
    UnitAbilityAdd(lllkDt, \"BeamCaster3\");
    UnitAbilityAdd(lllkDt, \"BeamCaster4\");
    UnitAbilityAdd(lllkDt, \"BeamCaster5\");
    UnitAbilityAdd(lllkDt, \"BeamCaster6\");
    UnitAbilityAdd(lllkDt, \"BeamCaster7\");
    UnitAbilityAdd(lllkDt, \"BeamCaster8\");
    UnitAbilityAdd(lllkDt, \"BeamCaster9\");
    UnitAbilityAdd(lllkDt, \"BeamCaster10\");
    UnitAbilityAdd(lllkDt, \"BeamCaster11\");
    libNtve_gf_SetDialogItemEditorValue(lllbOS, \"Marine\", PlayerGroupAll());
}}
""".strip()


class ProbeError(RuntimeError):
    pass


def _inject_probe_setup(map_script: Path) -> None:
    text = map_script.read_text(encoding="utf-8-sig")
    if PROBE_MARKER in text:
        raise ProbeError(f"probe setup already present: {map_script}")
    init = re.search(r"void InitMap\s*\(\s*\)\s*\{(?P<body>.*?)\}\s*$", text, re.DOTALL)
    if init is None:
        raise ProbeError(f"terminal InitMap not found: {map_script}")
    body = init.group("body")
    if re.search(r"lllnIs\s*\(\s*\)\s*;", body) is None:
        raise ProbeError("unexpected InitMap bootstrap; refusing to guess injection point")
    patched_body = re.sub(
        r"lllnIs\s*\(\s*\)\s*;",
        "lllnIs();douQuquAbilityProbeSetup();",
        body,
        count=1,
    )
    patched_init = text[init.start() : init.end()].replace(body, patched_body, 1)
    text = text[: init.start()] + SETUP_FUNCTION + "\n" + patched_init + text[init.end() :]
    map_script.write_text(text, encoding="utf-8", newline="\n")


def prepare_map(source: Path, staged_dir: Path, packed_map: Path) -> dict[str, Any]:
    staged_dir = staged_dir.resolve()
    packed_map = packed_map.resolve()
    result = stage_map(source.resolve(), staged_dir, dispatch_source=DEFAULT_DISPATCH, replace=True)
    _inject_probe_setup(staged_dir / "MapScript.galaxy")
    packed_map.parent.mkdir(parents=True, exist_ok=True)
    if packed_map.exists():
        packed_map.unlink()
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PACKER),
            str(staged_dir),
            str(packed_map),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not packed_map.is_file():
        raise ProbeError(
            "SC2Map packing failed: "
            + (completed.stdout + "\n" + completed.stderr).strip()[-3000:]
        )
    manifest = {
        "schemaVersion": 1,
        "classification": "runtime-preparation",
        "mapLabel": "斗蛐蛐",
        "forbiddenMap": "亡者之夜",
        "sourceMap": str(source.resolve()),
        "stagedDirectory": str(staged_dir),
        "packedMap": str(packed_map),
        "probeSetup": PROBE_MARKER,
        "customAbilities": CUSTOM_ABILITIES,
        "packStdout": completed.stdout[-2000:],
    }
    manifest_path = packed_map.parent / "dou-ququ-ability-probe-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


async def send_recv(ws, request: sc_pb.Request, timeout: float = 120.0) -> sc_pb.Response:
    await ws.send_bytes(request.SerializeToString())
    raw = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    response = sc_pb.Response()
    response.ParseFromString(raw)
    return response


async def create_and_join(ws, map_path: Path) -> dict[str, Any]:
    map_data = map_path.read_bytes()
    create = sc_pb.Request(
        create_game=sc_pb.RequestCreateGame(
            local_map=sc_pb.LocalMap(map_data=map_data), realtime=False
        )
    )
    player = create.create_game.player_setup.add()
    player.type = 1
    player.race = 1
    response = await send_recv(ws, create)
    if response.create_game.HasField("error") or response.error:
        raise ProbeError(f"CreateGame failed: {response.create_game.error_details} {list(response.error)}")
    join = sc_pb.Request(
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
    )
    response = await send_recv(ws, join)
    if response.error:
        raise ProbeError(f"JoinGame failed: {list(response.error)}")
    return {"player_id": int(response.join_game.player_id)}


async def step(ws, count: int = 8) -> None:
    response = await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=count)), timeout=30.0)
    if response.error:
        raise ProbeError(f"RequestStep failed: {list(response.error)}")


def _catalog(response: sc_pb.Response) -> tuple[dict[int, str], dict[int, str], dict[tuple[str, int], int]]:
    abilities: dict[int, str] = {}
    by_name_index: dict[tuple[str, int], int] = {}
    units: dict[int, str] = {}
    for entry in response.data.abilities:
        aid = int(entry.ability_id)
        abilities[aid] = entry.link_name
        by_name_index[(entry.link_name, int(entry.link_index))] = aid
    for entry in response.data.units:
        units[int(entry.unit_id)] = entry.name
    return abilities, units, by_name_index


def _snapshot(response: sc_pb.Response, unit_names: dict[int, str]) -> dict[str, Any]:
    observation = response.observation.observation
    units = []
    for unit in observation.raw_data.units:
        units.append(
            {
                "tag": int(unit.tag),
                "type_id": int(unit.unit_type),
                "type": unit_names.get(int(unit.unit_type), f"unknown:{unit.unit_type}"),
                "owner": int(unit.owner),
                "x": round(unit.pos.x, 3),
                "y": round(unit.pos.y, 3),
                "health": round(unit.health, 2),
                "orders": [int(order.ability_id) for order in unit.orders],
            }
        )
    return {"game_loop": int(observation.game_loop), "units": units}


async def observe(ws, unit_names: dict[int, str]) -> dict[str, Any]:
    return _snapshot(await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation())), unit_names)


async def wait_for_scv(ws, unit_names: dict[int, str], attempts: int = 30) -> tuple[dict[str, Any], int]:
    last = {"game_loop": 0, "units": []}
    for _ in range(attempts):
        await step(ws)
        await asyncio.sleep(0.15)
        last = await observe(ws, unit_names)
        scvs = [u for u in last["units"] if u["type"] == "SCV" and u["owner"] == 1]
        if scvs:
            return last, int(scvs[0]["tag"])
    raise ProbeError(f"probe SCV not observed: {last}")


async def query_available(ws, tag: int) -> list[int]:
    request = sc_pb.Request(
        query=query_pb2.RequestQuery(
            abilities=[query_pb2.RequestQueryAvailableAbilities(unit_tag=tag)]
        )
    )
    response = await send_recv(ws, request)
    if not response.query.abilities:
        return []
    return [int(item.ability_id) for item in response.query.abilities[0].abilities]


async def issue_ability(ws, ability_id: int, tag: int, target: tuple[float, float]) -> dict[str, Any]:
    request = sc_pb.Request(action=sc_pb.RequestAction())
    action = request.action.actions.add()
    command = action.action_raw.unit_command
    command.ability_id = ability_id
    command.unit_tags.append(tag)
    command.target_world_space_pos.x = target[0]
    command.target_world_space_pos.y = target[1]
    response = await send_recv(ws, request)
    results = [int(value) for value in response.action.result]
    return {
        "ability_id": ability_id,
        "target": list(target),
        "response_results": results,
        "response_result_names": [ACTION_RESULT_NAMES.get(value, f"Result:{value}") for value in results],
        "transport_errors": list(response.error),
        "accepted": not response.error and (not results or any(value == 1 for value in results)),
    }


async def run_probe(port: int, map_path: Path, out_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "classification": "runtime",
        "mapLabel": "斗蛐蛐",
        "forbiddenMap": "亡者之夜",
        "map": str(map_path.resolve()),
        "port": port,
        "customAbilities": CUSTOM_ABILITIES,
        "lifecycle": {},
        "actions": [],
    }
    async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=None)) as session:
        async with session.ws_connect(f"ws://127.0.0.1:{port}/sc2api", max_msg_size=0) as ws:
            ping = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
            result["lifecycle"]["ping"] = not ping.error
            result["lifecycle"]["createJoin"] = await create_and_join(ws, map_path)
            data = await send_recv(ws, sc_pb.Request(data=sc_pb.RequestData(ability_id=True, unit_type_id=True)), timeout=120.0)
            ability_names, unit_names, by_name_index = _catalog(data)
            result["catalog"] = {
                "abilityCount": len(ability_names),
                "unitTypeCount": len(unit_names),
                "custom": {
                    name: {"ability_id": by_name_index.get((name, 0)), "link_index": 0}
                    for name in CUSTOM_ABILITIES
                },
            }
            baseline, scv_tag = await wait_for_scv(ws, unit_names)
            result["setup"] = {"scvTag": scv_tag, "baseline": baseline}
            available = await query_available(ws, scv_tag)
            result["availableAbilities"] = [
                {"ability_id": aid, "name": ability_names.get(aid, f"unknown:{aid}")}
                for aid in available
                if ability_names.get(aid) in CUSTOM_ABILITIES
            ]
            target = (64.0, 64.0)
            for name in CUSTOM_ABILITIES:
                aid = by_name_index.get((name, 0))
                if aid is None:
                    result["actions"].append({"name": name, "status": "missing_catalog_id"})
                    continue
                action = await issue_ability(ws, aid, scv_tag, target)
                result["actions"].append({"name": name, **action})
                await step(ws, 8)
                await asyncio.sleep(0.15)
            final = await observe(ws, unit_names)
            result["final"] = final
            before_marines = sum(u["type"] == "Marine" and u["owner"] == 1 for u in baseline["units"])
            after_marines = sum(u["type"] == "Marine" and u["owner"] == 1 for u in final["units"])
            result["effectChecks"] = {
                "fangzhidanweiMarineDelta": after_marines - before_marines,
                "fangzhidanweiObserved": after_marines > before_marines,
            }
    result["verdict"] = {
        "mapLoaded": bool(result["lifecycle"].get("createJoin")),
        "scvObserved": "scvTag" in result.get("setup", {}),
        "customAbilityCatalogComplete": all(
            item.get("ability_id") is not None for item in result["catalog"]["custom"].values()
        ),
        "customAbilityRuntimeVisible": {
            name: any(item["name"] == name for item in result["availableAbilities"])
            for name in CUSTOM_ABILITIES
        },
        "fangzhidanweiEffectObserved": result["effectChecks"]["fangzhidanweiObserved"],
        "acceptedActionCount": sum(1 for item in result["actions"] if item.get("accepted")),
        "actionCount": len(CUSTOM_ABILITIES),
    }
    result["verdict"]["unsupportedActionNames"] = [
        item["name"] for item in result["actions"] if item.get("accepted") is False
    ]
    result["verdict"]["allCustomActionsAccepted"] = (
        result["verdict"]["acceptedActionCount"] == len(CUSTOM_ABILITIES)
    )
    result["verdict"]["overall"] = (
        "PASS"
        if result["verdict"]["mapLoaded"]
        and result["verdict"]["scvObserved"]
        and result["verdict"]["customAbilityCatalogComplete"]
        and result["verdict"]["allCustomActionsAccepted"]
        and result["verdict"]["fangzhidanweiEffectObserved"]
        else "PASS_WITH_GAP"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "dou-ququ-custom-ability-runtime.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--staged-dir", required=True)
    prepare.add_argument("--packed-map", required=True)
    run = sub.add_parser("run")
    run.add_argument("--port", type=int, required=True)
    run.add_argument("--map-path", required=True)
    run.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(json.dumps(prepare_map(Path(args.source), Path(args.staged_dir), Path(args.packed_map)), ensure_ascii=False, indent=2))
            return 0
        result = asyncio.run(run_probe(args.port, Path(args.map_path), Path(args.out_dir)))
        print(json.dumps(result["verdict"], ensure_ascii=False, indent=2))
        return 0 if result["verdict"]["overall"] == "PASS" else 1
    except (OSError, ProbeError, subprocess.SubprocessError) as exc:
        print(f"[dou-ququ-probe] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
