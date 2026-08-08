"""Stage 08 bounded native runtime probe: thorner03 P2 (gv_p02_TYCHUS) handover.

What this probe proves
----------------------
The static trace (p2_contract_trace.py) states the map's own contract:

  * P2 owns zero units at map start.
  * `gv_odin = UnitFromId(2)` (MapScript.galaxy:616) is pre-placed, hidden
    (`ShowHideUnit(UnitFromId(2), false)`, :4800) and invulnerable
    (`MakeUnitInvulnerable(UnitFromId(2), true)`, :4129).
  * A `TychusCommando` entering `RegionFromId(24)` fires
    `gt_VictoryWarehouseDudesKilled` (:1141 condition at :1153, event at :1177).
  * That trigger runs `gt_MidQ` (:1169) -> `gt_MidCleanup` (:5182), which calls
    `libNtve_gf_RescueUnit(UnitFromId(2), gv_p02_TYCHUS, true)` (:5389).
  * `gt_OdinGoGoGo` then drives P2 through `AIAttackWave*` (:1983-:1986).

So the runtime question is narrow and falsifiable:

  Given only the map's own documented precondition is met, does the *map* --
  not the adapter -- transfer the Odin to player 2 and drive it with scripted AI?

Method / honesty constraints
----------------------------
* No map edits, no Catalog edits, no adapter changes.
* No units are ever created for player 2.
* No debug API, cheat, unit creation, map edit, or generic melee AI is used.
  The probe only issues native player-1 actions and records observations.

Usage
-----
  python p2_handover_probe.py --port <port> --map-path <abs path> --out-dir <dir>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import socket
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402
import aiohttp  # noqa: E402

STATUS_NAMES = {1: "launched", 2: "init_game", 3: "in_game", 4: "in_replay", 5: "ended", 6: "quit"}

P1_USER = 1
P2_TYCHUS = 2
P4_ELITEGUARD = 4

GATE_UNIT_TYPE = "TychusCommando"
REGION24_CENTER = (89.1628, 41.6557)
REGION24_RADIUS = 1.1206

ABIL_MOVE = 16
ABIL_ATTACK = 23

# Escort waypoints from the P1 start pocket toward the Region 24 beacon.
ESCORT_WAYPOINTS = [
    (65.0, 22.0),
    (70.0, 27.0),
    (75.0, 31.0),
    (80.0, 33.0),
    (84.5, 36.0),
    (87.5, 39.0),
    REGION24_CENTER,
]

async def send_recv(ws, req: sc_pb.Request, timeout: float = 30.0) -> sc_pb.Response:
    await ws.send_bytes(req.SerializeToString())
    raw = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    resp = sc_pb.Response()
    resp.ParseFromString(raw)
    return resp


async def wait_for_port(host: str, port: int, max_attempts: int = 120) -> bool:
    for i in range(max_attempts):
        try:
            with socket.create_connection((host, port), timeout=1.0):
                print(f"  port {host}:{port} reachable (attempt {i + 1})", file=sys.stderr)
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            await asyncio.sleep(1.0)
    return False


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Census:
    """One observation snapshot, reduced to the facts the P2 verdict depends on."""

    def __init__(self, label: str, obs, unit_names: dict[int, str]):
        o = obs.observation
        self.label = label
        self.game_loop = o.game_loop
        self.units: list[dict[str, Any]] = []
        for u in o.raw_data.units:
            self.units.append(
                {
                    "tag": u.tag,
                    "type": unit_names.get(u.unit_type, f"unknown_{u.unit_type}"),
                    "owner": u.owner,
                    "alliance": u.alliance,
                    "x": round(u.pos.x, 3),
                    "y": round(u.pos.y, 3),
                    "health": round(u.health, 1),
                    "health_max": round(u.health_max, 1),
                    "display_type": u.display_type,
                    "orders": [int(od.ability_id) for od in u.orders],
                }
            )
        self.player_result = [
            {"player_id": r.player_id, "result": r.result} for r in obs.player_result
        ]

    @property
    def p2_units(self) -> list[dict[str, Any]]:
        return [u for u in self.units if u["owner"] == P2_TYCHUS]

    @property
    def p1_units(self) -> list[dict[str, Any]]:
        return [u for u in self.units if u["owner"] == P1_USER]

    @property
    def odin_units(self) -> list[dict[str, Any]]:
        return [u for u in self.units if "odin" in u["type"].lower()]

    def tychus(self) -> dict[str, Any] | None:
        live = [
            u
            for u in self.units
            if u["type"] == GATE_UNIT_TYPE and u["owner"] == P1_USER and u["health"] > 0
        ]
        return live[0] if live else None

    def to_json(self, include_units: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "label": self.label,
            "game_loop": self.game_loop,
            "total_units": len(self.units),
            "p1_owned_count": len(self.p1_units),
            "p2_owned_count": len(self.p2_units),
            "p2_owned_units": self.p2_units,
            "odin_units": self.odin_units,
            "tychus": self.tychus(),
            "player_result": self.player_result,
        }
        if include_units:
            d["units"] = self.units
        return d


async def observe(ws, label: str, unit_names: dict[int, str]) -> Census:
    resp = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
    return Census(label, resp.observation, unit_names)


async def issue(ws, ability_id: int, tags: list[int], target: tuple[float, float]) -> dict:
    if not tags:
        return {"ability_id": ability_id, "skipped": "no_tags"}
    req = sc_pb.Request(action=sc_pb.RequestAction())
    a = req.action.actions.add()
    cmd = a.action_raw.unit_command
    cmd.ability_id = ability_id
    cmd.target_world_space_pos.x = target[0]
    cmd.target_world_space_pos.y = target[1]
    cmd.unit_tags.extend(tags)
    cmd.queue_command = False
    resp = await send_recv(ws, req)
    return {
        "ability_id": ability_id,
        "unit_count": len(tags),
        "target": list(target),
        "results": [int(r) for r in resp.action.result],
        "errors": list(resp.error),
    }


async def create_and_join(ws, map_path: str) -> dict:
    candidates = [map_path, f"Maps\\{Path(map_path).name}", Path(map_path).name]
    lifecycle: dict[str, Any] = {}
    created = False
    for cand in candidates:
        req = sc_pb.Request(
            create_game=sc_pb.RequestCreateGame(
                local_map=sc_pb.LocalMap(map_path=cand), realtime=True
            )
        )
        p = req.create_game.player_setup.add()
        p.type = 1  # Participant
        p.race = 1  # Terran
        resp = await send_recv(ws, req, timeout=120.0)
        nested = resp.create_game.error if resp.create_game.HasField("error") else 0
        lifecycle["create_game"] = {
            "map_path_used": cand,
            "status": int(resp.status),
            "status_name": STATUS_NAMES.get(int(resp.status), "?"),
            "errors": list(resp.error),
            "nested_error": int(nested),
            "nested_error_detail": resp.create_game.error_details,
        }
        print(f"  create_game({cand!r}) -> status={lifecycle['create_game']['status_name']} nested={nested}", file=sys.stderr)
        if nested == 0 and not resp.error:
            created = True
            break
    if not created:
        raise RuntimeError(f"create_game failed: {lifecycle.get('create_game')}")

    join = sc_pb.Request(
        join_game=sc_pb.RequestJoinGame(
            race=1,
            options=sc_pb.InterfaceOptions(
                raw=True,
                score=True,
                show_cloaked=True,
                show_burrowed_shadows=True,
                raw_affects_selection=False,
                raw_crop_to_playable_area=False,
                show_placeholders=True,
            ),
        )
    )
    resp = await send_recv(ws, join, timeout=120.0)
    lifecycle["join_game"] = {
        "status": int(resp.status),
        "status_name": STATUS_NAMES.get(int(resp.status), "?"),
        "errors": list(resp.error),
        "player_id": resp.join_game.player_id,
        "nested_error_detail": resp.join_game.error_details,
    }
    print(f"  join_game -> status={lifecycle['join_game']['status_name']} player_id={resp.join_game.player_id}", file=sys.stderr)
    if resp.error:
        raise RuntimeError(f"join_game failed: {list(resp.error)}")
    return lifecycle


async def run_probe(ws, map_path: str) -> dict:
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "classification": "runtime",
        "stage": "08-ai-ally-native-closure",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "map": Path(map_path).name,
        "method": "native_map_precondition_then_owner_census",
        "map_edits": False,
        "adapter_created_p2_units": False,
        "generic_melee_ai_injected": False,
        "debug_apis_used": [],
        "gate": {
            "trigger": "gt_VictoryWarehouseDudesKilled",
            "event": "TriggerAddEventUnitRegion(RegionFromId(24), enter)",
            "condition": 'UnitGetType(EventUnit()) == "TychusCommando"',
            "region24_center": list(REGION24_CENTER),
            "region24_radius": REGION24_RADIUS,
            "handover_call": "libNtve_gf_RescueUnit(UnitFromId(2), gv_p02_TYCHUS, true)",
        },
        "actions": [],
        "timeline": [],
    }

    resp = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
    result["ping"] = {
        "game_version": resp.ping.game_version,
        "base_build": resp.ping.base_build,
        "status": int(resp.status),
        "status_name": STATUS_NAMES.get(int(resp.status), "?"),
    }
    print(f"  ping: {resp.ping.game_version} base_build={resp.ping.base_build}", file=sys.stderr)

    result["lifecycle"] = await create_and_join(ws, map_path)

    # Catalog
    resp = await send_recv(ws, sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True, ability_id=True)), timeout=90.0)
    unit_names = {u.unit_id: u.name for u in resp.data.units}
    result["lifecycle"]["catalog"] = {"units": len(unit_names), "abilities": len(resp.data.abilities)}
    print(f"  catalog: units={len(unit_names)} abilities={len(resp.data.abilities)}", file=sys.stderr)
    if not unit_names:
        raise RuntimeError("catalog empty - refusing to record any AI ally assertion")

    # Let the map's own StartingUnits triggers run.
    await asyncio.sleep(6.0)

    baseline = await observe(ws, "baseline_pre_precondition", unit_names)
    result["baseline"] = baseline.to_json(include_units=True)
    print(
        f"  baseline loop={baseline.game_loop} total={len(baseline.units)} "
        f"p1={len(baseline.p1_units)} p2={len(baseline.p2_units)} odin={len(baseline.odin_units)}",
        file=sys.stderr,
    )
    if not baseline.units:
        raise RuntimeError("empty unit observation - refusing to record any AI ally assertion")

    # ---- Phase A: escort the map's own Tychus into Region 24 ----
    gate_reached = False
    gate_method = None
    wp_index = 0
    deadline = time.time() + 200.0
    last_order = 0.0
    while time.time() < deadline:
        census = await observe(ws, "escort", unit_names)
        ty = census.tychus()
        entry = {
            "phase": "escort",
            "game_loop": census.game_loop,
            "tychus": ty,
            "p2_owned_count": len(census.p2_units),
            "waypoint_index": wp_index,
        }
        result["timeline"].append(entry)
        if census.p2_units:
            gate_reached = True
            gate_method = "escort_native_tychus"
            break
        if ty is not None:
            d = dist((ty["x"], ty["y"]), REGION24_CENTER)
            entry["dist_to_region24"] = round(d, 3)
            if d <= REGION24_RADIUS:
                gate_reached = True
                gate_method = "escort_native_tychus"
                print(f"  Tychus inside Region 24 at loop {census.game_loop}", file=sys.stderr)
                break
            # Advance waypoint when close enough.
            while wp_index < len(ESCORT_WAYPOINTS) - 1 and dist((ty["x"], ty["y"]), ESCORT_WAYPOINTS[wp_index]) < 4.0:
                wp_index += 1
            if time.time() - last_order > 3.0:
                wp = ESCORT_WAYPOINTS[wp_index]
                squad = [u["tag"] for u in census.p1_units if u["health"] > 0 and u["type"] != GATE_UNIT_TYPE]
                result["actions"].append(await issue(ws, ABIL_ATTACK, squad, wp))
                result["actions"].append(await issue(ws, ABIL_MOVE, [ty["tag"]], wp))
                last_order = time.time()
                print(f"    loop={census.game_loop} tychus=({ty['x']},{ty['y']}) d={d:.1f} -> wp{wp_index}{wp}", file=sys.stderr)
        else:
            entry["note"] = "no live player-1 TychusCommando"
            print(f"    loop={census.game_loop} no live Tychus", file=sys.stderr)
            break
        await asyncio.sleep(2.0)

    result["gate_reached"] = gate_reached
    result["gate_method"] = gate_method

    # ---- Phase C: watch for the map's own handover (MidQ runs a cinematic first) ----
    handover_seen = False
    first_handover: dict[str, Any] | None = None
    watch_deadline = time.time() + (240.0 if gate_reached else 30.0)
    while time.time() < watch_deadline:
        census = await observe(ws, "handover_watch", unit_names)
        entry = {
            "phase": "handover_watch",
            "game_loop": census.game_loop,
            "p2_owned_count": len(census.p2_units),
            "p2_owned_units": census.p2_units,
            "odin_units": census.odin_units,
        }
        result["timeline"].append(entry)
        if census.p2_units:
            handover_seen = True
            first_handover = census.to_json(include_units=True)
            print(f"  P2 OWNS {len(census.p2_units)} unit(s) at loop {census.game_loop}", file=sys.stderr)
            break
        await asyncio.sleep(3.0)

    result["handover_observed"] = handover_seen
    if first_handover:
        result["handover_census"] = first_handover
        # Give the scripted AI a moment, then confirm P2 is actually being driven.
        await asyncio.sleep(12.0)
        after = await observe(ws, "post_handover_ai", unit_names)
        result["post_handover_census"] = after.to_json(include_units=True)
        result["p2_has_active_orders"] = any(u["orders"] for u in after.p2_units)

    final = await observe(ws, "final", unit_names)
    result["final"] = final.to_json(include_units=True)

    if handover_seen:
        result["verdict"] = "passed_native_p2_handover_observed"
    elif gate_reached:
        result["verdict"] = "blocked_precondition_met_but_no_p2_handover"
    else:
        result["verdict"] = "blocked_precondition_not_reached"
    return result


async def main_async(port: int, map_path: str, out_dir: Path) -> int:
    url = f"ws://127.0.0.1:{port}/sc2api"
    print(f"Stage 08 P2 handover probe\n  url={url}\n  map={map_path}", file=sys.stderr)
    if not await wait_for_port("127.0.0.1", port):
        print(f"  ERROR: port {port} never became reachable", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "p2-handover-probe.json"

    session = ws = None
    for attempt in range(20):
        try:
            session = aiohttp.ClientSession()
            ws = await session.ws_connect(url, max_msg_size=0)
            print(f"  websocket connected (attempt {attempt + 1})", file=sys.stderr)
            break
        except Exception as e:  # noqa: BLE001
            if session:
                await session.close()
            session = ws = None
            print(f"    ws attempt {attempt + 1} failed: {e}", file=sys.stderr)
            await asyncio.sleep(2.0)
    if ws is None:
        return 2

    result: dict[str, Any]
    try:
        result = await run_probe(ws, map_path)
    except Exception as e:  # noqa: BLE001
        import traceback

        trace_text = traceback.format_exc()
        traceback.print_exc()
        result = {
            "schemaVersion": 1,
            "classification": "runtime",
            "stage": "08-ai-ally-native-closure",
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "map": Path(map_path).name,
            "verdict": "error",
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__,
            "traceback": trace_text,
        }
    finally:
        try:
            await ws.close()
        finally:
            if session:
                await session.close()

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}", file=sys.stderr)
    print(f"verdict = {result.get('verdict')}", file=sys.stderr)
    print(f"gate_reached = {result.get('gate_reached')} via {result.get('gate_method')}", file=sys.stderr)
    print(f"handover_observed = {result.get('handover_observed')}", file=sys.stderr)
    return 0 if result.get("verdict", "").startswith("passed") else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--map-path", type=str, required=True)
    ap.add_argument("--out-dir", type=str, required=True)
    a = ap.parse_args()
    return asyncio.run(main_async(a.port, a.map_path, Path(a.out_dir)))


if __name__ == "__main__":
    sys.exit(main())
