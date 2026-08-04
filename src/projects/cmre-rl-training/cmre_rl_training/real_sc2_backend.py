"""RealSc2BackendAdapter: wrap a python-sc2 BotAI as an RlBackend.

This adapter bridges the RL pipeline (``CmreRLEnv``) and a live SC2 game
driven by ``python-sc2.BotAI``. It translates the 19 basic RL actions into
python-sc2 commands and reads the resulting observation.

The adapter is designed to work with any object exposing the BotAI surface
(``units``, ``state``, ``do_action``, ``do``). When python-sc2 is not
installed, a mock BotAI can be substituted for protocol/translation tests.

Note: Actual SC2 launch requires a launcher (see AGENTS.md SC2 launch rules).
This adapter handles only the in-game action translation loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping

from .action_space import ACTION_NAMES


class RealSc2BackendAdapter:
    """RlBackend adapter wrapping a python-sc2 BotAI instance.

    Parameters
    ----------
    bot
        A BotAI-like object with ``units``, ``state``, ``do_action``, ``do``.
    player_id
        The player perspective (default 1).
    map_name
        Map identifier for mission context (default "dead-of-night").
    """

    def __init__(
        self,
        bot: Any,
        *,
        player_id: int = 1,
        map_name: str = "dead-of-night",
    ) -> None:
        self._bot = bot
        self._player_id = int(player_id)
        self._map_name = str(map_name)
        self._state_version = 0
        self._action_translators: dict[str, Callable[[Mapping[str, Any]], None]] = {
            "move_units": self._translate_move,
            "stop_units": self._translate_stop,
            "hold_units": self._translate_hold,
            "patrol_units": self._translate_patrol,
            "attack_move_units": self._translate_attack_move,
            "attack_units": self._translate_attack,
            "gather_resources": self._translate_gather,
            "build_structure": self._translate_build,
            "produce_unit": self._translate_train,
            "research_upgrade": self._translate_research,
            "cast_point_ability": self._translate_cast_point,
            "cast_unit_ability": self._translate_cast_unit,
            "cast_no_target_ability": self._translate_cast_no_target,
            "repair_units": self._translate_repair,
            "morph_unit": self._translate_morph,
            "cancel_order": self._translate_cancel,
            "load_units": self._translate_load,
            "unload_units": self._translate_unload,
            "rally_producer": self._translate_rally,
        }
        if len(self._action_translators) != len(ACTION_NAMES):
            missing = set(ACTION_NAMES) - set(self._action_translators)
            raise RuntimeError(f"action_translator_missing:{missing}")

    @property
    def state_version(self) -> int:
        return int(self._state_version)

    def reset(self) -> dict[str, Any]:
        """Read the initial observation without issuing commands."""

        self._state_version = 0
        return self._read_observation()

    def step(
        self, action_id: str, args: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        """Translate and dispatch one action, then advance the game by one step."""

        translator = self._action_translators.get(action_id)
        if translator is None:
            raise ValueError(f"unknown_action:{action_id}")

        try:
            translator(dict(args))
        except Exception as exc:
            info: dict[str, Any] = {
                "action_id": action_id,
                "success": False,
                "error": str(exc),
                "state_version": self.state_version,
            }
            return self._read_observation(), False, info

        self._advance_game_loop()
        obs = self._read_observation()
        terminated = bool(obs.get("mission", {}).get("terminated", False))
        info = {
            "action_id": action_id,
            "success": True,
            "state_version": self.state_version,
        }
        return obs, terminated, info

    # -- Observation --------------------------------------------------------

    def _read_observation(self) -> dict[str, Any]:
        state = getattr(self._bot, "state", None)
        minerals = int(getattr(state, "minerals", 0)) if state else 0
        vespene = int(getattr(state, "vespene", 0)) if state else 0
        supply_used = int(getattr(state, "supply_used", 0)) if state else 0
        supply_cap = int(getattr(state, "supply_cap", 0)) if state else 0
        game_loop = int(getattr(state, "game_loop", self._state_version)) if state else self._state_version

        own_units = self._extract_own_units()
        visible_enemies = self._extract_enemy_units()

        return {
            "loop": game_loop,
            "player_id": self._player_id,
            "own_units": own_units,
            "visible_enemies": visible_enemies,
            "visible_allies": [],
            "resources": {
                "minerals": minerals,
                "vespene": vespene,
                "supply_used": supply_used,
                "supply_cap": supply_cap,
                "state_version": self._state_version,
            },
            "mission": {
                "phase": "active",
                "night": 0,
                "wave": 0,
                "terminated": False,
                "end_reason": "",
                "win_condition": "survive_loops",
                "progress": 0.0,
                "state_version": self._state_version,
            },
            "mineral_fields": [],
            "vespene_geysers": [],
            "tech": {"completed_upgrades": [], "researching": []},
        }

    def _extract_own_units(self) -> list[dict[str, Any]]:
        units_list = self._get_units_list()
        own = []
        for unit in units_list:
            owner = getattr(unit, "owner", self._player_id)
            if owner != self._player_id and owner != 1:
                continue
            tag = getattr(unit, "tag", 0)
            type_id = getattr(unit, "type_id", None)
            unit_type = getattr(type_id, "value", "Unknown") if type_id else "Unknown"
            pos = getattr(unit, "position", None)
            x = float(getattr(pos, "x", 0.0)) if pos else 0.0
            y = float(getattr(pos, "y", 0.0)) if pos else 0.0
            hp = float(getattr(unit, "health", 0.0) or 0.0)
            shields = float(getattr(unit, "shields", 0.0) or 0.0)
            energy = float(getattr(unit, "energy", 0.0) or 0.0)
            own.append({
                "entity_id": int(tag) if tag else 0,
                "unit_type_id": str(unit_type),
                "owner": int(owner),
                "x": x, "y": y,
                "health": hp, "shields": shields, "energy": energy,
                "state": "idle",
                "orders": list(getattr(unit, "orders", []) or []),
            })
        return own

    def _extract_enemy_units(self) -> list[dict[str, Any]]:
        return []

    def _get_units_list(self) -> list[Any]:
        units_obj = getattr(self._bot, "units", None)
        if units_obj is None:
            return []
        # Some mocks store units as a list attribute
        if hasattr(units_obj, "_units_list"):
            return units_obj._units_list  # type: ignore[no-any-return]
        if isinstance(units_obj, list):
            return units_obj
        # python-sc2 Units object is iterable
        try:
            return list(units_obj)
        except TypeError:
            return []

    def _advance_game_loop(self) -> None:
        self._state_version += 1
        advancer = getattr(self._bot, "_advance_step", None)
        if callable(advancer):
            advancer()

    # -- Action translators -------------------------------------------------

    def _resolve_units(self, args: Mapping[str, Any], *, prefer: str = "combat") -> list[Any]:
        """Resolve target units from args or fall back to a sensible default."""

        tags = args.get("entity_tags") or args.get("entity_ids")
        units_list = self._get_units_list()
        if tags:
            tag_set = set(int(t) for t in tags)
            return [u for u in units_list if int(getattr(u, "tag", 0)) in tag_set]
        # Default: pick combat units for combat actions, workers for worker actions
        if prefer == "worker":
            workers = getattr(self._bot.units, "workers", None) if hasattr(self._bot, "units") else None
            return list(workers or [])[:1]
        combat = getattr(self._bot.units, "combat_units", None) if hasattr(self._bot, "units") else None
        return list(combat or [])[:1]

    def _run_async(self, coro: Any) -> None:
        """Run an async do/do_action call synchronously."""

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an event loop; schedule but don't block
                asyncio.ensure_future(coro)
                return
            loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop in this thread — create one
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(coro)
            finally:
                loop.close()

    def _translate_move(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_x = float(args.get("target_x", 0.0))
        target_y = float(args.get("target_y", 0.0))
        for unit in units:
            cmd = type("MoveCmd", (), {
                "kind": "move",
                "unit_tag": getattr(unit, "tag", 0),
                "target": (target_x, target_y),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_stop(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        for unit in units:
            cmd = type("StopCmd", (), {
                "kind": "stop",
                "unit_tag": getattr(unit, "tag", 0),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_hold(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        for unit in units:
            cmd = type("HoldCmd", (), {
                "kind": "hold",
                "unit_tag": getattr(unit, "tag", 0),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_patrol(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_x = float(args.get("target_x", 0.0))
        target_y = float(args.get("target_y", 0.0))
        for unit in units:
            cmd = type("PatrolCmd", (), {
                "kind": "patrol",
                "unit_tag": getattr(unit, "tag", 0),
                "target": (target_x, target_y),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_attack_move(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_x = float(args.get("target_x", 0.0))
        target_y = float(args.get("target_y", 0.0))
        for unit in units:
            cmd = type("AttackMoveCmd", (), {
                "kind": "attack_move",
                "unit_tag": getattr(unit, "tag", 0),
                "target": (target_x, target_y),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_attack(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_tag = int(args.get("target_tag", 0))
        for unit in units:
            cmd = type("AttackCmd", (), {
                "kind": "attack",
                "unit_tag": getattr(unit, "tag", 0),
                "target_tag": target_tag,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_gather(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="worker")
        target_tag = int(args.get("target_tag", 0))
        for unit in units:
            cmd = type("GatherCmd", (), {
                "kind": "gather",
                "unit_tag": getattr(unit, "tag", 0),
                "target_tag": target_tag,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_build(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="worker")
        unit_type = str(args.get("unit_type", "SupplyDepot"))
        target_x = float(args.get("target_x", 0.0))
        target_y = float(args.get("target_y", 0.0))
        for unit in units:
            cmd = type("BuildCmd", (), {
                "kind": "build",
                "unit_tag": getattr(unit, "tag", 0),
                "unit_type": unit_type,
                "target": (target_x, target_y),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_train(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        unit_type = str(args.get("unit_type", "Marine"))
        for unit in units:
            cmd = type("TrainCmd", (), {
                "kind": "train",
                "unit_tag": getattr(unit, "tag", 0),
                "unit_type": unit_type,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_research(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        upgrade = str(args.get("upgrade", "TerranInfantryWeaponsLevel1"))
        for unit in units:
            cmd = type("ResearchCmd", (), {
                "kind": "research",
                "unit_tag": getattr(unit, "tag", 0),
                "upgrade": upgrade,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_cast_point(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_x = float(args.get("target_x", 0.0))
        target_y = float(args.get("target_y", 0.0))
        ability = str(args.get("ability", "Stimpack"))
        for unit in units:
            cmd = type("CastPointCmd", (), {
                "kind": "cast_point",
                "unit_tag": getattr(unit, "tag", 0),
                "ability": ability,
                "target": (target_x, target_y),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_cast_unit(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_tag = int(args.get("target_tag", 0))
        ability = str(args.get("ability", "Stimpack"))
        for unit in units:
            cmd = type("CastUnitCmd", (), {
                "kind": "cast_unit",
                "unit_tag": getattr(unit, "tag", 0),
                "ability": ability,
                "target_tag": target_tag,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_cast_no_target(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        ability = str(args.get("ability", "Stimpack"))
        for unit in units:
            cmd = type("CastNoTargetCmd", (), {
                "kind": "cast_no_target",
                "unit_tag": getattr(unit, "tag", 0),
                "ability": ability,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_repair(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="worker")
        target_tag = int(args.get("target_tag", 0))
        for unit in units:
            cmd = type("RepairCmd", (), {
                "kind": "repair",
                "unit_tag": getattr(unit, "tag", 0),
                "target_tag": target_tag,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_morph(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        unit_type = str(args.get("unit_type", "SiegeTankSieged"))
        for unit in units:
            cmd = type("MorphCmd", (), {
                "kind": "morph",
                "unit_tag": getattr(unit, "tag", 0),
                "unit_type": unit_type,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_cancel(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        for unit in units:
            cmd = type("CancelCmd", (), {
                "kind": "cancel",
                "unit_tag": getattr(unit, "tag", 0),
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_load(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_tag = int(args.get("target_tag", 0))
        for unit in units:
            cmd = type("LoadCmd", (), {
                "kind": "load",
                "unit_tag": getattr(unit, "tag", 0),
                "target_tag": target_tag,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_unload(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_tag = int(args.get("target_tag", 0))
        for unit in units:
            cmd = type("UnloadCmd", (), {
                "kind": "unload",
                "unit_tag": getattr(unit, "tag", 0),
                "target_tag": target_tag,
            })()
            self._run_async(self._bot.do_action(cmd))

    def _translate_rally(self, args: Mapping[str, Any]) -> None:
        units = self._resolve_units(args, prefer="combat")
        target_x = float(args.get("target_x", 0.0))
        target_y = float(args.get("target_y", 0.0))
        for unit in units:
            cmd = type("RallyCmd", (), {
                "kind": "rally",
                "unit_tag": getattr(unit, "tag", 0),
                "target": (target_x, target_y),
            })()
            self._run_async(self._bot.do_action(cmd))


__all__ = ["RealSc2BackendAdapter"]
