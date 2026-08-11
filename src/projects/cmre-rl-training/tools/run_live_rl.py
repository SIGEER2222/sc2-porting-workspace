"""Run a bounded map-aware PPO rollout against real SC2.

This entrypoint owns only orchestration. SC2 is always started through the
registered launcher; the live session and RL environment stay reusable from
tests and other runners.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "src" / "projects" / "cmre-rl-training"
CMRE_PORTING_SRC = REPO_ROOT / "src" / "projects" / "cmre-porting"
CMRE_NEURO_SRC = REPO_ROOT / "src" / "projects" / "cmre-neuro-adapter"
PROTOCOL_ROOT = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"

for path in (PROJECT_ROOT, CMRE_PORTING_SRC, CMRE_NEURO_SRC, PROTOCOL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from cmre_rl_training.action_grounding import ActionGrounder  # noqa: E402
from cmre_rl_training.action_metrics import (  # noqa: E402
    summarize_action_trace,
    summarize_rollout_actions,
)
from cmre_rl_training.commander_profile import (  # noqa: E402
    build_commander_profile,
    commander_report_fields,
    read_launch_profile_bank,
    validate_commander_profile,
)
from cmre_rl_training.env import CmreRLEnv  # noqa: E402
from cmre_rl_training.live_sc2_session import LiveRawSc2Session  # noqa: E402
from cmre_rl_training.map_aware import (  # noqa: E402
    MapAwareEnv,
    load_map_aware_checkpoint,
    save_map_aware_checkpoint,
)
from cmre_rl_training.map_profiles import MapProfileRegistry  # noqa: E402
from cmre_rl_training.ppo import PPOTrainer  # noqa: E402
from cmre_rl_training.raw_sc2_backend import RawSc2Backend  # noqa: E402
from cmre_rl_training.rollout import collect_rollout  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run map-aware PPO on real SC2 through the approved launcher")
    parser.add_argument("--map-name", default="dead-of-night")
    parser.add_argument("--launcher-map-name", default="亡者之夜.SC2Map")
    parser.add_argument(
        "--map-path",
        # Overlay-packed map (md5 ccc74e2c6fff5b1914d196b5867705c5, 3328542 B),
        # built 20260810 by packing the approved launcher's fully-overlayed staging
        # directory (initialization gate + observer bridge + preselected commander).
        #
        # Three-way A/B on identical code/params, map as the only variable:
        #   OVERLAY_20260810   census verdict=faction_initialised,
        #                      commander_economy_online=true, supply 15/15,
        #                      15 SCV + CommandCenter, 535 minerals,
        #                      terminal_evidence_reachable=true, reward_sum=+2577.95
        #   GAMEPLAY_OK_20260731  census verdict=faction_initialised but
        #                      supply_cap=0 (commander economy never comes online):
        #                      Marine + placeholder 4051 only, reward_sum=-587.65
        #   亡者之夜_live_packed.SC2Map (20260809-23:33 repack)
        #                      census verdict=player_faction_uninitialised,
        #                      own=1 (placeholder 4051), 0 minerals, 0/512 successes
        #
        # The pre-overlay artifacts predate the 20260809 observer/init-gate overlay,
        # so the CMRE commander-init trigger chain never fires under them
        # (debug bank initialization_gate_started stays 0). Do not switch the default
        # back without re-running the faction census A/B *and* the bank snapshot.
        default="artifacts/live-maps/亡者之夜_live_packed_OVERLAY_20260810.SC2Map",
        help="Packed .SC2Map used as the runtime map artifact",
    )
    parser.add_argument(
        "--checkpoint",
        default="artifacts/projects/cmre-rl-training/multi-map-training/map-aware-policy.pt",
        help="Map-aware checkpoint produced by train_multi_map.py",
    )
    parser.add_argument("--port", type=int, default=5952)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--step-mul", type=int, default=8)
    parser.add_argument("--commander", default="TerranRaynor")
    parser.add_argument("--commander-level", type=int, default=15,
                        help="Declared commander level (default: max level 15)")
    parser.add_argument("--commander-mastery", default="full",
                        help="Declared mastery allocation (default: full)")
    parser.add_argument(
        "--mastery-layout",
        default="30,30,30,30,30,30",
        help="Six launcher mastery slots (default: all slots at 30)",
    )
    parser.add_argument("--commander-evidence", default=None,
                        help="Path to a bank/JSON evidence file proving in-game commander level/mastery")
    parser.add_argument("--commander-enforce", dest="commander_enforce", action="store_true", default=True,
                        help="Block the run when the max-level/full-mastery gate fails (default)")
    parser.add_argument("--no-commander-enforce", dest="commander_enforce", action="store_false",
                        help="Allow a diagnostic run without commander gate enforcement")
    parser.add_argument("--launcher-suffix", default="rl-bridge")
    parser.add_argument("--output", default=None, help="Runtime report path")
    parser.add_argument("--protocol-root", default=str(PROTOCOL_ROOT))
    parser.add_argument("--skip-launch", action="store_true", help="Use an already running API")
    parser.add_argument("--api-ready-timeout", type=float, default=300.0,
                        help="Seconds to wait for the SC2 API to answer a real handshake+Ping")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--train", action="store_true", help="Apply one PPO update to the live rollout")
    parser.add_argument("--stop-on-terminal", action="store_true", help="Stop at the first mission terminal event")
    parser.add_argument(
        "--require-terminal",
        action="store_true",
        help=(
            "Declare that this run exists to produce terminal evidence. "
            "Exhausting the step budget without a player_result is then a gate "
            "failure instead of a pass. Stage 6 must always set this."
        ),
    )
    parser.add_argument(
        "--require-faction",
        action="store_true",
        help=(
            "Abort before the rollout if the API observation shows player 1 owns "
            "no units / no supply at step 0. Implied by --require-terminal. The "
            "Galaxy initialization markers do not check this."
        ),
    )
    parser.add_argument("--save-replay", action="store_true", help="Save the native SC2 replay before leaving")
    parser.add_argument("--variant", default="checkpoint", help="Evaluation variant label")
    parser.add_argument("--ppo-epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    return parser


def resolve_repo_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_powershell_executable() -> str:
    """Use the PowerShell edition that can execute the approved launcher."""

    for name in ("pwsh", "powershell"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    return "powershell"


def parse_mastery_layout(raw: str) -> list[int]:
    """Parse the six launcher mastery slots and reject ambiguous profiles."""

    parts = [part.strip() for part in str(raw).split(",")]
    if len(parts) != 6 or any(part == "" for part in parts):
        raise ValueError("mastery_layout_must_have_six_slots")
    values: list[int] = []
    for part in parts:
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(f"mastery_layout_value_not_int:{part}") from exc
        if value < 0 or value > 30:
            raise ValueError(f"mastery_layout_value_out_of_range:{value}")
        values.append(value)
    return values


def mastery_layout_gate(raw: str) -> dict[str, Any]:
    """Return fail-closed evidence for the launcher's full-mastery profile."""

    try:
        values = parse_mastery_layout(raw)
    except ValueError as exc:
        return {
            "layout": str(raw),
            "values": None,
            "full": False,
            "reasons": [str(exc)],
        }
    full = all(value == 30 for value in values)
    return {
        "layout": str(raw),
        "values": values,
        "full": full,
        "reasons": [] if full else ["mastery layout is not full 30/30/30/30/30/30"],
    }


def probe_sc2_api(port: int, *, timeout_seconds: float = 10.0) -> tuple[bool, str]:
    """Handshake with ws://127.0.0.1:<port>/sc2api and answer a Ping.

    A bare TCP connect is NOT a readiness signal: SC2 opens the listening socket
    well before the /sc2api websocket handler is installed, so a TCP-only probe
    reports ready while every ws_connect still fails with ServerDisconnectedError.
    This probe only returns True once the protocol actually answers.
    """

    async def _probe() -> tuple[bool, str]:
        import aiohttp
        from s2clientprotocol import sc2api_pb2 as sc_pb

        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(sock_connect=timeout_seconds, sock_read=timeout_seconds)
        )
        try:
            websocket = await session.ws_connect(
                f"ws://127.0.0.1:{int(port)}/sc2api",
                max_msg_size=0,
                autoclose=False,
                autoping=False,
            )
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
            await session.close()
            return False, f"{type(exc).__name__}: {exc}"
        try:
            request = sc_pb.Request()
            request.ping.SetInParent()
            await websocket.send_bytes(request.SerializeToString())
            message = await asyncio.wait_for(websocket.receive(), timeout=timeout_seconds)
            if message.type != aiohttp.WSMsgType.BINARY:
                return False, f"non_binary_ping_response:{message.type}"
            response = sc_pb.Response()
            response.ParseFromString(bytes(message.data))
            return True, f"game_version={response.ping.game_version} status={response.status}"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            try:
                await websocket.close()
            finally:
                await session.close()

    try:
        return asyncio.run(_probe())
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _census_snapshot(observation: dict[str, Any]) -> dict[str, Any]:
    own_units = list(observation.get("own_units") or [])
    resources = dict(observation.get("resources") or {})
    type_counts: dict[str, int] = {}
    for unit in own_units:
        name = str(unit.get("unit_type_id") or unit.get("unit_type_int") or "unknown")
        type_counts[name] = type_counts.get(name, 0) + 1
    return {
        "loop": int(observation.get("loop", 0)),
        "own_unit_count": len(own_units),
        "own_unit_types": dict(sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "visible_enemy_count": len(observation.get("visible_enemies") or []),
        "visible_ally_count": len(observation.get("visible_allies") or []),
        "minerals": int(resources.get("minerals", 0)),
        "vespene": int(resources.get("vespene", 0)),
        "supply_used": int(resources.get("supply_used", 0)),
        "supply_cap": int(resources.get("supply_cap", 0)),
    }


class CensusPeakTracker:
    """Remember the best economy state the run ever reached.

    ``build_runtime_census`` originally sampled two points only (loop 0 and the
    final loop). That cannot distinguish "the commander economy never came
    online" from "it came online and was then destroyed": both end at
    ``supply_cap == 0`` with a couple of leftover units. The 20260810 192k-loop
    run was mislabelled ``partial_faction`` for exactly this reason, while the
    same artifact had reported ``faction_initialised`` on a short run.

    A high-water mark makes the two states separable, which matters because
    they have opposite meanings: the first is a broken artifact, the second is
    a real match the policy lost.
    """

    def __init__(self) -> None:
        self.max_supply_cap = 0
        self.max_own_unit_count = 0
        self.loop_at_max_supply_cap: int | None = None
        self.samples = 0

    def observe(self, observation: Mapping[str, Any] | None) -> None:
        if not isinstance(observation, Mapping):
            return
        self.samples += 1
        resources = observation.get("resources")
        resources = resources if isinstance(resources, Mapping) else {}
        try:
            supply_cap = int(resources.get("supply_cap", 0) or 0)
        except (TypeError, ValueError):
            supply_cap = 0
        own_units = observation.get("own_units") or []
        try:
            own_unit_count = len(own_units)
        except TypeError:
            own_unit_count = 0
        if supply_cap > self.max_supply_cap:
            self.max_supply_cap = supply_cap
            try:
                self.loop_at_max_supply_cap = int(observation.get("loop", 0) or 0)
            except (TypeError, ValueError):
                self.loop_at_max_supply_cap = None
        self.max_own_unit_count = max(self.max_own_unit_count, own_unit_count)

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "max_supply_cap": self.max_supply_cap,
            "max_own_unit_count": self.max_own_unit_count,
            "loop_at_max_supply_cap": self.loop_at_max_supply_cap,
        }


def build_runtime_census(
    initial: dict[str, Any],
    final: dict[str, Any],
    peak: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record what the player actually owns, not just whether frames advanced.

    A CMRE launcher map can join, advance loops and answer observations while the
    campaign trigger stack has never handed the player a real faction. Capturing
    the census makes that failure legible instead of surfacing as an unexplained
    "0 successful actions".

    Three states are distinguished, because they gate different things:

    ``player_faction_uninitialised``
        One placeholder unit, no economy. Every order returns NotSupported/Error.
        Nothing can be evaluated on this artifact.

    ``partial_faction:units_without_commander_economy``
        Controllable units exist and orders succeed, but ``supply_cap == 0`` and
        production never comes online. This is enough for Stage-5 action
        evidence and structurally *cannot* reach a mission ``player_result``,
        so it must never be used to chase a Stage-6 victory.

    ``faction_initialised``
        Real commander economy (``supply_cap > 0``): the only state where a
        long-horizon terminal run is meaningful.
    """

    start = _census_snapshot(initial)
    end = _census_snapshot(final)
    peak_fields = dict(peak) if isinstance(peak, Mapping) else {}
    try:
        peak_supply_cap = int(peak_fields.get("max_supply_cap", 0) or 0)
    except (TypeError, ValueError):
        peak_supply_cap = 0
    commander_economy_online = bool(end["supply_cap"] > 0)
    # The peak never contradicts the endpoints: take the best of what we saw.
    commander_economy_ever_online = bool(
        commander_economy_online
        or start["supply_cap"] > 0
        or peak_supply_cap > 0
    )
    economy_collapsed = bool(commander_economy_ever_online and not commander_economy_online)
    has_controllable_surface = bool(end["own_unit_count"] > 1 or end["minerals"] > 0)
    mission_started = bool(commander_economy_ever_online or has_controllable_surface)

    if commander_economy_online:
        verdict = "faction_initialised"
    elif economy_collapsed:
        verdict = "economy_lost:commander_economy_came_online_then_collapsed"
    elif has_controllable_surface:
        verdict = "partial_faction:units_without_commander_economy"
    else:
        verdict = "player_faction_uninitialised:launcher_map_never_entered_gameplay"

    census = {
        "initial": start,
        "final": end,
        "mission_actually_started": mission_started,
        "commander_economy_online": commander_economy_online,
        # "Ever online" is the structural precondition for a player_result:
        # an artifact that never hands the player an economy cannot reach one.
        # Losing the economy mid-match is a *match* outcome, not a broken
        # artifact, so the two must not share a label.
        "commander_economy_ever_online": commander_economy_ever_online,
        "economy_collapsed": economy_collapsed,
        # A run whose player never received a commander economy can never
        # produce a real player_result, so Stage 6 must not be attempted on
        # such an artifact.
        "terminal_evidence_reachable": commander_economy_ever_online,
        "verdict": verdict,
    }
    if peak_fields:
        census["peak"] = dict(peak_fields)
    return census


def wait_for_api(
    port: int,
    *,
    timeout_seconds: float = 300.0,
    launcher_process: subprocess.Popen[bytes] | None = None,
) -> bool:
    """Wait until the SC2 API protocol actually answers, not just until TCP listens."""

    deadline = time.monotonic() + float(timeout_seconds)
    last_detail = "not_attempted"
    while time.monotonic() < deadline:
        if launcher_process is not None and launcher_process.poll() is not None:
            print(f"[wait_for_api] launcher exited early: {last_detail}", flush=True)
            return False
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=2.0):
                pass
        except OSError as exc:
            last_detail = f"tcp:{exc}"
            time.sleep(1.0)
            continue
        ready, detail = probe_sc2_api(port)
        last_detail = detail
        if ready:
            print(f"[wait_for_api] sc2 api ready on {port}: {detail}", flush=True)
            return True
        time.sleep(1.0)
    print(f"[wait_for_api] timed out on {port}: {last_detail}", flush=True)
    return False


DEBUG_BANK_NAME = "CMRERebornDebug.SC2Bank"
LAUNCH_PROFILE_BANK_NAME = "CMCoopLaunchProfile.SC2Bank"

# The CMRE commander initialization chain, in the order the map writes it.
INITIALIZATION_BANK_KEYS = (
    "stage16_before_vibe",
    "stage16_after_vibe",
    "map_init_entered",
    "preselected_commander_startup",
    "startup_dev_begin",
    "startup_dev_finish",
    "initialization_gate_started",
    "initialization_building_ready_p1",
    "initialization_building_ready_p2",
    "initialization_units_ready_p1",
    "initialization_units_ready_p2",
    "initialization_complete",
    "reborn_adapter_initialized",
)

_BANK_KEY_PATTERN = re.compile(
    r'<Key\s+name="([^"]+)"[^>]*>\s*<Value[^>]*?(?:int|string|text|fixed)="([^"]*)"',
    re.IGNORECASE,
)


def sc2_bank_root() -> Path:
    return Path.home() / "Documents" / "StarCraft II" / "Banks"


def parse_debug_bank(path: Path) -> dict[str, str]:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return {}
    return dict(_BANK_KEY_PATTERN.findall(text))


# ``Documents/StarCraft II/Banks`` contains pathologically self-nested
# ``.runtime-lab-backup-<epoch>/.runtime-lab-backup-<epoch>/...`` directories
# left behind by an earlier lab harness. A plain ``Path.glob("**/...")`` walks
# into them, blows past MAX_PATH and raises ``FileNotFoundError: [WinError 3]``,
# which is exactly how the first Stage 6 terminal run lost its bank snapshot
# (``initialization_bank: {"error": ...}``) even though the run itself was fine.
# Snapshotting must never be able to fail because of an unrelated directory, so
# the scan prunes these prefixes and is depth bounded.
BANK_SCAN_EXCLUDED_PREFIXES: tuple[str, ...] = (".runtime-lab-backup",)
BANK_SCAN_MAX_DEPTH = 4


def iter_debug_banks(
    root: Path,
    *,
    bank_name: str = DEBUG_BANK_NAME,
    excluded_prefixes: tuple[str, ...] = BANK_SCAN_EXCLUDED_PREFIXES,
    max_depth: int = BANK_SCAN_MAX_DEPTH,
) -> list[Path]:
    """Find debug banks under ``root`` without walking into cursed backups."""

    if not root.is_dir():
        return []
    found: list[Path] = []
    for current, directories, files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        if depth >= max_depth:
            directories[:] = []
        else:
            directories[:] = [
                name
                for name in directories
                if not name.startswith(excluded_prefixes)
            ]
        if bank_name in files:
            found.append(current_path / bank_name)
    return sorted(found)


def snapshot_initialization_banks(output_dir: Path, *, banks_root: Path | None = None) -> dict[str, Any]:
    """Copy the CMRE debug banks next to the report and read the init markers.

    Why this has to happen per run: the approved launcher resets
    ``CMRERebornDebug.SC2Bank`` on every launch, so the file only ever holds the
    state of the run that just finished and the *next* launch destroys it. The
    8192-step evidence had to be copied by hand, and the first proof that
    ``initialization_gate_started`` can be non-zero was overwritten minutes
    later by the following launch. Snapshotting here turns the single
    acceptance signal for the CMRE commander init chain (EVAL-009) into a
    durable per-run artifact instead of a transient one.

    ``Banks/<account>/CMRERebornDebug.SC2Bank`` copies stay zeroed - the running
    map writes the root ``Banks/CMRERebornDebug.SC2Bank``. Every copy is
    captured and the markers are merged with ``max`` so an account-scoped write
    is not silently missed if that ever changes.
    """

    root = banks_root if banks_root is not None else sc2_bank_root()
    destination = output_dir / "banks"
    sources = iter_debug_banks(root)
    copied: list[str] = []
    merged: dict[str, int] = {key: 0 for key in INITIALIZATION_BANK_KEYS}
    by_source: dict[str, dict[str, str]] = {}
    for source in sources:
        relative = source.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, target)
        except OSError:
            continue
        try:
            copied.append(str(target.relative_to(REPO_ROOT)))
        except ValueError:
            copied.append(str(target))
        values = parse_debug_bank(source)
        by_source[str(relative).replace("\\", "/")] = {
            key: values[key] for key in INITIALIZATION_BANK_KEYS if key in values
        }
        for key in INITIALIZATION_BANK_KEYS:
            raw = values.get(key)
            if raw is None:
                continue
            try:
                merged[key] = max(merged[key], int(raw))
            except ValueError:
                continue
    gate_started = merged.get("initialization_gate_started", 0)
    return {
        "banks_root": str(root),
        "snapshots": copied,
        "keys": merged,
        "by_source": by_source,
        "initialization_gate_started": gate_started,
        "initialization_complete": merged.get("initialization_complete", 0),
        # EVAL-009 acceptance signal: the gate writes this marker the instant it
        # runs, so a zero here means the chain never entered, not that it failed
        # a condition.
        "commander_init_chain_fired": gate_started != 0,
    }


def snapshot_commander_launch_profile(
    output_dir: Path,
    *,
    player: int = 1,
    banks_root: Path | None = None,
    fresh_since: float | None = None,
) -> dict[str, Any]:
    """Copy and parse the launch-profile bank for commander level evidence.

    A stale CMCoopLaunchProfile.SC2Bank is worse than no proof: it can describe
    an earlier run and silently turn the current launch into a false pass. When
    fresh_since is provided, only banks modified inside the current run window
    can become the selected evidence.
    """

    root = banks_root if banks_root is not None else sc2_bank_root()
    destination = output_dir / "banks"
    sources = iter_debug_banks(root, bank_name=LAUNCH_PROFILE_BANK_NAME)
    copied: list[str] = []
    by_source: dict[str, dict[str, Any]] = {}
    selected: dict[str, Any] | None = None

    for source in sources:
        relative = source.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, target)
        except OSError:
            continue

        try:
            snapshot_path = str(target.relative_to(REPO_ROOT))
        except ValueError:
            snapshot_path = str(target)
        copied.append(snapshot_path)

        try:
            modified_epoch = float(source.stat().st_mtime)
        except OSError:
            modified_epoch = 0.0
        fresh = fresh_since is None or modified_epoch >= float(fresh_since)
        entry: dict[str, Any] = {
            "snapshot": snapshot_path,
            "modified_epoch": modified_epoch,
            "fresh": bool(fresh),
        }
        try:
            evidence = read_launch_profile_bank(source, player=player)
            evidence["source_path"] = str(source)
            evidence["snapshot"] = snapshot_path
            evidence["modified_epoch"] = modified_epoch
            entry["evidence"] = evidence
            if fresh and selected is None:
                selected = evidence
        except Exception as exc:  # noqa: BLE001 - a bad bank is report evidence
            entry["error"] = f"{type(exc).__name__}: {exc}"
        by_source[str(relative).replace("\\", "/")] = entry

    result: dict[str, Any] = {
        "banks_root": str(root),
        "bank_name": LAUNCH_PROFILE_BANK_NAME,
        "player": int(player),
        "fresh_since_epoch": fresh_since,
        "snapshots": copied,
        "by_source": by_source,
        "fresh_selected": selected is not None,
    }
    if selected is not None:
        result["selected"] = selected
    return result


def apply_commander_report(
    report: dict[str, Any],
    profile: Any,
    validation: Mapping[str, Any],
    mastery_gate: Mapping[str, Any],
) -> None:
    block = commander_report_fields(profile, validation)
    block["commander_mastery_layout"] = mastery_gate["layout"]
    block["commander_mastery_values"] = mastery_gate["values"]
    block["commander_full_mastery_layout_passed"] = mastery_gate["full"]
    report["commander"] = block


def terminal_gate_failures(
    report: Mapping[str, Any], *, require_terminal: bool
) -> list[str]:
    """Name why a terminal-evidence run failed to produce terminal evidence.

    Stage 6's rule is "do not convert timeout/cutoff into victory". The runtime
    gate used to accept ``steps_collected == max_steps`` OR ``terminal_observed``
    as interchangeable, so a run that merely exhausted its budget reported
    ``status=passed`` with ``terminal_observed=false``. ``--stop-on-terminal``
    only *permits* an early exit; it never asserted one happened. This makes the
    demand explicit and fail-closed, and names the structural cause when the
    census already knows one.
    """

    if not require_terminal or report.get("terminal_observed"):
        return []
    census = report.get("runtime_census")
    census = census if isinstance(census, Mapping) else {}
    if census and not census.get("terminal_evidence_reachable", True):
        return [f"terminal_not_observed:evidence_unreachable:{census.get('verdict')}"]
    if census.get("economy_collapsed"):
        return ["terminal_not_observed:commander_economy_collapsed"]
    return ["terminal_not_observed"]


class FactionPreconditionAbort(RuntimeError):
    """Raised to skip a rollout that would run against an empty faction."""


def faction_precondition_failures(
    initial_observation: Mapping[str, Any] | None, *, require_faction: bool
) -> list[str]:
    """Refuse to start a terminal-evidence rollout on an empty faction.

    The Galaxy-side initialization gate cannot be trusted for this. It writes
    ``initialization_building_ready_p1`` / ``initialization_units_ready_p1`` /
    ``initialization_complete`` in one unconditional block the moment
    ``gf_CmreOnDemandInitializationReady()`` returns true, and that helper
    *skips* every P1 ownership check when the launch profile omits
    ``CreateStartingUnitsP1`` / ``EnsurePreventDefeatP1`` - which the RL harness
    never sets. Four "ready" markers are therefore four restatements of one
    boolean that asserted nothing about P1. Stage 6 attempt 3 ran 192,000 loops
    against a player owning zero units with all four markers green.

    The API's own view of ``player_id`` is the independent witness the Galaxy
    markers are not, so the precondition is evaluated host-side from the first
    observation. Fail closed and fail *early*: an empty faction can neither
    produce (no victory) nor lose its PreventDefeat unit (no defeat), so the
    rollout is 20 wasted minutes of an exclusive real-machine slot.
    """

    if not require_faction:
        return []
    snapshot = _census_snapshot(initial_observation or {})
    failures: list[str] = []
    if snapshot["supply_cap"] <= 0:
        failures.append(
            "faction_not_initialised:supply_cap=0_at_rollout_start"
            "(galaxy_init_markers_are_not_evidence)"
        )
    if snapshot["own_unit_count"] <= 0:
        failures.append("faction_not_initialised:own_unit_count=0_at_rollout_start")
    return failures


def commander_gate_state(report: Mapping[str, Any]) -> tuple[bool, bool]:
    """Return ``(evaluated, passed)`` for the commander max-level gate.

    Fail closed. The original inline check read
    ``report.get("commander", {}).get("commander_max_level_gate_passed", True)``,
    so any report that never populated ``report["commander"]`` - for instance
    because the rollout ended before the commander block was written - made
    ``--commander-enforce`` silently vacuous. A gate that cannot fail is not a
    gate, it is decoration.

    ``evaluated`` is returned separately so "we checked and it failed" is never
    laundered into "we never checked", which are different defects with
    different fixes.
    """

    fields = report.get("commander")
    if not isinstance(fields, dict) or "commander_max_level_gate_passed" not in fields:
        return False, False
    return True, bool(fields["commander_max_level_gate_passed"])


def launch_approved_launcher(args: argparse.Namespace, output_dir: Path) -> tuple[subprocess.Popen[bytes], Any]:
    launcher = REPO_ROOT / "tools" / "launchers" / "launch-cmre-alenger.ps1"
    launcher_log = output_dir / "launcher.log"
    launcher_err = output_dir / "launcher.err.log"
    command = [
        resolve_powershell_executable(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher),
        "-MapName",
        args.launcher_map_name,
        "-Commander",
        args.commander,
        "-ListenPort",
        str(args.port),
        # The launcher applies these values through its profile/bank overlay.
        # Keep the request explicit so a visible run cannot silently fall back
        # to a saved underleveled commander profile.
        "-EnableBuffPatch",
        "-Masteries",
        str(args.mastery_layout),
        # Plain API mode (no -DirectMapApi): the launcher brings SC2 to the main
        # menu, and LiveRawSc2Session.reset() loads the *packed* RL map via
        # CreateGame(local_map=map_data). This guarantees the runtime map equals
        # the policy's packed map (N5b map-path mismatch fix): previously
        # -DirectMapApi made SC2Switcher load the *source* 亡者之夜.SC2Map while
        # the session held the packed map with join_existing=True, so the runtime
        # map never matched the policy -> CreateGame ScriptError / silent mismatch.
        "-KeepAlive",
    ]
    stdout = launcher_log.open("wb")
    stderr = launcher_err.open("wb")
    process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=stdout, stderr=stderr)
    return process, (stdout, stderr)


def stop_launcher(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except OSError:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def sc2_process_snapshot() -> dict[int, str]:
    """Return current SC2 process IDs and paths without assuming ownership."""

    command = (
        "Get-CimInstance Win32_Process -Filter \"Name='SC2_x64.exe'\" | "
        "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}
        payload = json.loads(completed.stdout)
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return {}
    rows = payload if isinstance(payload, list) else [payload]
    result: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        path = str(row.get("ExecutablePath") or "")
        if pid > 0:
            result[pid] = path
    return result


def stop_owned_sc2_processes(baseline_pids: set[int]) -> list[int]:
    """Stop only SC2 processes created after this runner's baseline snapshot."""

    stopped: list[int] = []
    for pid, path in sc2_process_snapshot().items():
        normalized = path.replace("/", "\\").lower()
        if pid in baseline_pids or not normalized.endswith("\\sc2_x64.exe"):
            continue
        if "\\starcraft ii\\versions\\" not in normalized:
            continue
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        stopped.append(pid)
    return stopped


def script_error_verdict(start_epoch: float) -> dict[str, Any]:
    logs_dir = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
    if not logs_dir.is_dir():
        return {"checked": False, "has_new_errors": False, "reason": "GameLogs directory not found"}
    errors: list[dict[str, Any]] = []
    for path in logs_dir.glob("*ScriptError*.txt"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= start_epoch:
            errors.append({"file": path.name, "size": stat.st_size, "mtime": stat.st_mtime})
    return {
        "checked": True,
        "has_new_errors": bool(errors),
        "count": len(errors),
        "errors": errors,
        "window_start_epoch": start_epoch,
    }


def default_output_path(map_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "artifacts" / "stage-10-runtime-policy-eval" / f"{stamp}-{map_name}" / "live-rl-report.json"


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_steps < 1:
        raise ValueError("--max-steps must be >= 1")
    if args.step_mul < 1:
        raise ValueError("--step-mul must be >= 1")
    if args.ppo_epochs < 1 or args.batch_size < 1:
        raise ValueError("--ppo-epochs and --batch-size must be >= 1")

    report_path = resolve_repo_path(args.output) if args.output else default_output_path(args.map_name)
    report_path = report_path.resolve()
    output_dir = report_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = resolve_repo_path(args.checkpoint).resolve()
    map_path = resolve_repo_path(args.map_path).resolve()
    start_epoch = time.time()
    launcher_process: subprocess.Popen[bytes] | None = None
    launcher_handles: Any = None
    baseline_sc2_pids = sc2_process_snapshot()
    session: LiveRawSc2Session | None = None
    base_env: CmreRLEnv | None = None
    report: dict[str, Any] = {
        "schema": "cmre-live-rl-bridge.v1",
        "status": "failed",
        "evidence_class": "runtime",
        "map_name": args.map_name,
        "map_path": str(map_path.relative_to(REPO_ROOT) if map_path.is_relative_to(REPO_ROOT) else map_path.name),
        "checkpoint": str(checkpoint_path.relative_to(REPO_ROOT) if checkpoint_path.is_relative_to(REPO_ROOT) else checkpoint_path.name),
        "config": {
            "port": args.port,
            "max_steps": args.max_steps,
            "step_mul": args.step_mul,
            "commander": args.commander,
            "commander_level": args.commander_level,
            "commander_mastery": args.commander_mastery,
            "mastery_layout": args.mastery_layout,
            "commander_enforce": bool(getattr(args, "commander_enforce", True)),
            "deterministic": bool(args.deterministic),
            "train": bool(args.train),
            "stop_on_terminal": bool(args.stop_on_terminal),
            "save_replay": bool(args.save_replay),
            "variant": str(args.variant),
        },
        "launcher_started": False,
        "direct_map_api": False,
        "map_entry": "create_game",
        "api_ready": False,
        "create_game": False,
        "join_game": False,
        "frame_advancement": False,
        "action_results_observed": False,
        "training_update_applied": False,
        "reward_basis": "observation-derived runtime proxy; no mission terminal claim",
        "report_path": str(report_path.relative_to(REPO_ROOT) if report_path.is_relative_to(REPO_ROOT) else report_path),
    }

    # Fail closed before acquiring an SC2 runtime lease. The default is max
    # level/full mastery; an explicitly underleveled profile is invalid ML
    # evidence and must not launch a visible game.
    commander_validation: dict[str, Any] | None = None
    mastery_gate = mastery_layout_gate(args.mastery_layout)
    try:
        commander_profile = build_commander_profile(
            args.commander,
            level=args.commander_level,
            mastery=args.commander_mastery,
            evidence_path=args.commander_evidence,
        )
        commander_validation = validate_commander_profile(commander_profile)
        if not mastery_gate["full"]:
            commander_validation["passed"] = False
            commander_validation["reasons"].extend(mastery_gate["reasons"])
            commander_validation["mastery_ok"] = False
        apply_commander_report(report, commander_profile, commander_validation, mastery_gate)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["blocked_reason"] = "commander_profile_invalid"
        report["evidence_class"] = "static-config"
        report["script_error_verdict"] = {"checked": False, "has_new_errors": False, "reason": "preflight"}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    if getattr(args, "commander_enforce", True) and not commander_validation["passed"]:
        report["status"] = "blocked"
        report["evidence_class"] = "static-config"
        report["blocked_reason"] = "commander_max_level_gate_failed"
        report["runtime_gate"] = False
        report["runtime_gate_failures"] = list(commander_validation["reasons"])
        report["script_error_verdict"] = {"checked": False, "has_new_errors": False, "reason": "preflight"}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    try:
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f"map_aware_checkpoint_not_found:{checkpoint_path}")
        if not map_path.is_file():
            raise FileNotFoundError(f"packed_map_not_found:{map_path}")

        if not args.skip_launch:
            try:
                with socket.create_connection(("127.0.0.1", int(args.port)), timeout=1.0):
                    raise RuntimeError(f"sc2_api_port_already_in_use:{args.port}")
            except OSError:
                pass
            launcher_process, launcher_handles = launch_approved_launcher(args, output_dir)
            report["launcher_started"] = True
            report["launcher_pid"] = launcher_process.pid
        report["api_ready"] = wait_for_api(
            args.port,
            timeout_seconds=float(args.api_ready_timeout),
            launcher_process=launcher_process,
        )
        report["api_ready_basis"] = "sc2api_websocket_handshake_and_ping"
        if not report["api_ready"]:
            if launcher_process is not None and launcher_process.poll() is not None:
                report["launcher_exit_code"] = launcher_process.returncode
                raise RuntimeError(f"approved_launcher_exited:{launcher_process.returncode}")
            raise RuntimeError(f"sc2_api_not_ready:{args.port}")

        session = LiveRawSc2Session(
            map_path,
            port=args.port,
            protocol_root=resolve_repo_path(args.protocol_root),
            progress_loop_limit=max(args.max_steps * args.step_mul, 1),
            # The API becomes ready before map-start triggers create player
            # units. Advance once after JoinGame so the faction gate observes
            # the launched match rather than the empty loop-0 lobby state.
            initialization_step_loops=max(64, int(args.step_mul)),
            # create_game loads the *packed* map bytes passed via map_path, so the
            # runtime map always matches the policy's packed map (N5b fix).
            join_existing=False,
        )
        backend = RawSc2Backend(session, map_name=args.map_name, player_id=1, step_mul=args.step_mul)
        base_env = CmreRLEnv(backend, normalize_reward=False)
        profile = MapProfileRegistry().resolve(args.map_name)
        env = MapAwareEnv(base_env, profile)
        policy = load_map_aware_checkpoint(checkpoint_path, device="cpu")
        policy.eval()
        grounder = ActionGrounder(profile, player_id=1)
        # CreateGame + JoinGame must happen before this gate. Reuse this vector
        # for collection so a terminal run does not create a second game.
        initial_vector = env.reset()
        initial_observation = getattr(session, "_last_observation", None) or {}
        loop_start = int(initial_observation.get("loop", 0))

        # The grounder is called once per candidate action per step with the
        # raw observation, which makes it the cheapest honest sampling point
        # for the economy high-water mark. Wrapping keeps collect_rollout and
        # ActionGrounder untouched.
        peak_tracker = CensusPeakTracker()
        peak_tracker.observe(initial_observation)

        # Fail closed *before* burning the exclusive real-machine slot.
        require_faction = bool(
            getattr(args, "require_faction", False)
            or getattr(args, "require_terminal", False)
        )
        faction_failures = faction_precondition_failures(
            initial_observation, require_faction=require_faction
        )
        if faction_failures:
            report.update({
                "player_id": session.player_id,
                "steps_collected": 0,
                "loop_start": loop_start,
                "loop_end": loop_start,
                "aborted_before_rollout": True,
                "faction_precondition_failures": list(faction_failures),
                "runtime_census": build_runtime_census(
                    initial_observation, initial_observation, peak=peak_tracker.as_dict()
                ),
            })
            print(
                "faction precondition failed, rollout skipped: "
                + "; ".join(faction_failures)
            )
            raise FactionPreconditionAbort("; ".join(faction_failures))

        def _grounding_probe(action_id: str, observation: Any) -> dict[str, Any]:
            peak_tracker.observe(observation)
            return grounder.ground(action_id, observation)

        buffer = collect_rollout(
            env,
            policy,
            n_steps=args.max_steps,
            deterministic=args.deterministic,
            device="cpu",
            action_builder=_grounding_probe,
            auto_reset_on_terminal=not args.stop_on_terminal,
            initial_observation=initial_vector,
        )
        rewards = [float(step.reward) for step in getattr(buffer, "_steps", ())]
        actions = [int(step.action.flatten()[0]) for step in getattr(buffer, "_steps", ())]
        final_observation = getattr(session, "_last_observation", None) or {}
        report.update({
            "player_id": session.player_id,
            "steps_collected": len(buffer),
            "loop_start": loop_start,
            "loop_end": int(final_observation.get("loop", 0)),
            "reward_sum": float(sum(rewards)),
            "reward_mean": float(np.mean(rewards)) if rewards else 0.0,
            "action_indices": actions,
            "policy_config": policy.config(),
            "feature_dim": int(env.observation_dim),
        })
        if args.stop_on_terminal and bool(final_observation.get("mission", {}).get("terminated", False)):
            report["reward_basis"] = "mission-owned player_result terminal + observation-derived dense signals"
        peak_tracker.observe(final_observation)
        report["runtime_census"] = build_runtime_census(
            initial_observation, final_observation, peak=peak_tracker.as_dict()
        )
        # Action distribution + illegal-action metrics (plan Stage 3 / 5).
        action_metrics = summarize_rollout_actions(buffer)
        report["action_metrics"] = action_metrics
        report["action_distribution"] = action_metrics["action_distribution"]
        report["action_distribution_normalized"] = action_metrics["action_distribution_normalized"]
        report["illegal_action_count"] = action_metrics["illegal_action_count"]
        report["illegal_action_rate"] = action_metrics["illegal_action_rate"]
        report["distinct_actions_used"] = action_metrics["distinct_actions_used"]
        report["action_entropy_nats"] = action_metrics["action_entropy_nats"]
        if args.save_replay:
            replay_data = session.save_replay()
            replay_path = output_dir / "live-replay.SC2Replay"
            replay_path.write_bytes(replay_data)
            report["replay_path"] = str(replay_path.relative_to(REPO_ROOT))
        if args.train:
            trainer = PPOTrainer(policy, epochs=args.ppo_epochs, batch_size=args.batch_size)
            metrics = trainer.train(buffer)
            live_checkpoint = output_dir / "live-map-aware-policy.pt"
            save_map_aware_checkpoint(
                policy,
                live_checkpoint,
                training={"source": "real-sc2-bounded-rollout", "steps": len(buffer), "ppo": metrics},
            )
            report["training_update_applied"] = True
            report["ppo_metrics"] = metrics
            report["live_checkpoint"] = str(live_checkpoint.relative_to(REPO_ROOT))
    except FactionPreconditionAbort as exc:
        # Not a crash: a deliberate fail-closed refusal to evaluate an artifact
        # that cannot produce the evidence the run was launched to produce.
        report["error"] = f"FactionPreconditionAbort: {exc}"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if session is not None:
            report["runtime_stats"] = dict(session.runtime_stats)
            report["create_game"] = bool(session.runtime_stats.get("create_game"))
            report["join_game"] = bool(session.runtime_stats.get("join_game"))
            report["action_results_observed"] = bool(session.runtime_stats.get("action_results"))
            report["action_successes"] = int(session.runtime_stats.get("action_successes", 0))
            report["frame_advancement"] = bool(session.runtime_stats.get("requested_step_loops", 0) > 0)
            report["action_trace"] = list(session.runtime_stats.get("action_trace", []))
            report["runtime_action_summary"] = summarize_action_trace(report["action_trace"])
            report["terminal_results"] = list(session.runtime_stats.get("terminal_results", []))
            report["terminal_observed"] = bool(report["terminal_results"])
            report["replay_saved"] = bool(session.runtime_stats.get("save_replay", False))
            try:
                session.leave()
            except Exception as exc:
                report["leave_error"] = f"{type(exc).__name__}: {exc}"
        # Snapshot before the launcher dies: the next launch resets the bank.
        try:
            report["initialization_bank"] = snapshot_initialization_banks(output_dir)
        except Exception as exc:  # noqa: BLE001 - evidence capture must never fail a run
            report["initialization_bank"] = {"error": f"{type(exc).__name__}: {exc}"}
        try:
            launch_profile_bank = snapshot_commander_launch_profile(
                output_dir,
                player=1,
                fresh_since=start_epoch,
            )
            report["commander_launch_profile_bank"] = launch_profile_bank
            selected_bank = launch_profile_bank.get("selected")
            if isinstance(selected_bank, dict) and selected_bank.get("source_path"):
                bank_profile = build_commander_profile(
                    args.commander,
                    level=args.commander_level,
                    mastery=args.commander_mastery,
                    evidence_path=selected_bank["source_path"],
                )
                bank_validation = validate_commander_profile(bank_profile)
                if not mastery_gate["full"]:
                    bank_validation["passed"] = False
                    bank_validation["reasons"].extend(mastery_gate["reasons"])
                    bank_validation["mastery_ok"] = False
                apply_commander_report(report, bank_profile, bank_validation, mastery_gate)
                report["commander"]["commander_launch_profile_bank_fresh"] = True
            else:
                report.setdefault("commander", {})["commander_launch_profile_bank_fresh"] = False
        except Exception as exc:  # noqa: BLE001 - evidence capture must never fail a run
            report["commander_launch_profile_bank"] = {"error": f"{type(exc).__name__}: {exc}"}
            report.setdefault("commander", {})["commander_launch_profile_bank_fresh"] = False
        stop_launcher(launcher_process)
        if not args.skip_launch:
            report["owned_sc2_pids_stopped"] = stop_owned_sc2_processes(set(baseline_sc2_pids))
        if launcher_handles is not None:
            for handle in launcher_handles:
                handle.close()
        report["script_error_verdict"] = script_error_verdict(start_epoch)
        # A bare "action_successes > 0" cannot tell a working agent from one
        # whose orders the engine rejects 99% of the time, so publish the rate
        # next to it (plan Stage 7 field: runtime action success rate).
        _runtime_stats = report.get("runtime_stats") or {}
        _action_requests = int(_runtime_stats.get("action_requests") or 0)
        _action_successes = int(report.get("action_successes") or 0)
        report["runtime_action_success_rate"] = (
            float(_action_successes) / float(_action_requests) if _action_requests else 0.0
        )
        if "runtime_action_summary" not in report:
            report["runtime_action_summary"] = summarize_action_trace(report.get("action_trace", []))
        report["runtime_illegal_action_rate"] = float(
            report["runtime_action_summary"].get("illegal_action_rate", 0.0)
        )
        _result_codes: dict[str, int] = {}
        for _code in _runtime_stats.get("action_results") or []:
            _key = str(_code)
            _result_codes[_key] = _result_codes.get(_key, 0) + 1
        report["runtime_action_result_distribution"] = dict(
            sorted(_result_codes.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        terminal_failures = terminal_gate_failures(
            report, require_terminal=bool(getattr(args, "require_terminal", False))
        )
        required_runtime = (
            report.get("api_ready")
            and (report.get("create_game") or report.get("direct_map_api"))
            and report.get("join_game")
            and report.get("frame_advancement")
            and report.get("action_results_observed")
            and int(report.get("action_successes", 0)) > 0
            and not terminal_failures
            and (
                int(report.get("steps_collected", 0)) == int(args.max_steps)
                or (args.stop_on_terminal and report.get("terminal_observed"))
            )
        )
        report["runtime_gate"] = bool(required_runtime)
        # Every blocked verdict must name its cause: an unexplained "blocked" is
        # indistinguishable from a broken checker (round22 lesson).
        gate_failures: list[str] = []
        if not report.get("api_ready"):
            gate_failures.append("api_not_ready")
        if not (report.get("create_game") or report.get("direct_map_api")):
            gate_failures.append("create_game_failed")
        if not report.get("join_game"):
            gate_failures.append("join_game_failed")
        if not report.get("frame_advancement"):
            gate_failures.append("no_frame_advancement")
        if not report.get("action_results_observed"):
            gate_failures.append("no_action_results")
        if int(report.get("action_successes", 0)) <= 0:
            census = report.get("runtime_census") or {}
            if census and not census.get("mission_actually_started", True):
                gate_failures.append("zero_action_successes:player_faction_uninitialised")
            else:
                gate_failures.append("zero_action_successes")
        if not (
            int(report.get("steps_collected") or 0) == int(args.max_steps)
            or (args.stop_on_terminal and report.get("terminal_observed"))
        ):
            gate_failures.append("step_budget_not_met")
        gate_failures.extend(terminal_failures)
        # An early faction abort must survive the gate recomputation, otherwise
        # the report would blame "step_budget_not_met" for a run that was
        # deliberately never started.
        gate_failures.extend(report.get("faction_precondition_failures") or [])
        report["runtime_gate_failures"] = gate_failures
        commander_evaluated, commander_gate_passed = commander_gate_state(report)
        if report.get("error"):
            report["status"] = "failed"
        elif report["script_error_verdict"].get("has_new_errors"):
            report["status"] = "blocked"
            report["blocked_reason"] = "new_script_errors_detected"
        elif args.commander_enforce and not commander_gate_passed:
            report["status"] = "blocked"
            report["blocked_reason"] = (
                "commander_max_level_gate_failed"
                if commander_evaluated
                else "commander_max_level_gate_not_evaluated"
            )
        elif not required_runtime:
            report["status"] = "blocked"
            report["blocked_reason"] = "runtime_gate_failed:" + ",".join(gate_failures or ["unknown"])
        else:
            report["status"] = "passed"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_live(args)
    print(json.dumps({
        "status": report.get("status"),
        "report": report.get("report_path"),
        "api_ready": report.get("api_ready"),
        "create_game": report.get("create_game"),
        "direct_map_api": report.get("direct_map_api"),
        "map_entry": report.get("map_entry"),
        "join_game": report.get("join_game"),
        "frame_advancement": report.get("frame_advancement"),
        "action_results_observed": report.get("action_results_observed"),
        "terminal_observed": report.get("terminal_observed", False),
        "replay_saved": report.get("replay_saved", False),
        # A 0.83%-success rollout used to be indistinguishable from a healthy
        # one in this summary, because illegal_action_rate measures mask
        # compliance and not whether the engine accepted the order.
        "runtime_action_success_rate": report.get("runtime_action_success_rate"),
        "script_errors": report.get("script_error_verdict", {}).get("has_new_errors"),
        # Surfaced so a Stage-6 victory attempt is never launched blind against an
        # artifact whose player never receives a commander economy.
        "census_verdict": (report.get("runtime_census") or {}).get("verdict"),
        "terminal_evidence_reachable": (report.get("runtime_census") or {}).get(
            "terminal_evidence_reachable"
        ),
        "economy_collapsed": (report.get("runtime_census") or {}).get("economy_collapsed"),
        "runtime_gate_failures": report.get("runtime_gate_failures"),
    }, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
