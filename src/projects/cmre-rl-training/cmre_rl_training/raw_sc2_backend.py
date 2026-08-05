"""Backend contract for a real SC2 raw-protocol session.

The session owns websocket/protobuf lifecycle. This adapter owns only the RL
contract and observation normalization, so simulator and raw runtime use the
same policy-facing shape without fabricating game progress.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from .action_grounding import ActionGrounder
from .backends import RlBackend


@runtime_checkable
class RawSc2Session(Protocol):
    """Blocking bridge around Create/Join/Observe/Action/Step/Leave."""

    def reset(self, map_name: str, player_id: int) -> Mapping[str, Any] | None: ...

    def observe(self) -> Mapping[str, Any]: ...

    def dispatch(self, action_id: str, args: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def step(self, step_mul: int) -> Mapping[str, Any] | None: ...

    def leave(self) -> None: ...


class RawSc2Backend:
    """Expose a raw SC2 session through the existing synchronous RlBackend API."""

    def __init__(
        self,
        session: RawSc2Session,
        *,
        map_name: str,
        player_id: int = 1,
        step_mul: int = 8,
        grounder: ActionGrounder | None = None,
    ) -> None:
        if not isinstance(session, RawSc2Session):
            raise TypeError("session does not implement RawSc2Session")
        if not map_name.strip():
            raise ValueError("map_name must not be empty")
        if step_mul < 1:
            raise ValueError("step_mul must be >= 1")
        self.session = session
        self.map_name = map_name.strip()
        self.player_id = int(player_id)
        self.step_mul = int(step_mul)
        self.grounder = grounder
        self._observation: dict[str, Any] | None = None
        self._state_version = 0

    @property
    def state_version(self) -> int:
        return self._state_version

    def reset(self) -> dict[str, Any]:
        raw = self.session.reset(self.map_name, self.player_id)
        if raw is None:
            raw = self.session.observe()
        self._observation = normalize_raw_observation(raw, self.map_name, self.player_id)
        self._state_version = int(self._observation["loop"])
        return dict(self._observation)

    def step(
        self,
        action_id: str,
        args: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        if self._observation is None:
            raise RuntimeError("call reset() before step()")
        action_args = dict(args or {})
        if not action_args and self.grounder is not None:
            action_args = self.grounder.ground(action_id, self._observation)
        dispatch_result = dict(self.session.dispatch(action_id, action_args))
        advanced = self.session.step(self.step_mul)
        raw_observation = advanced if isinstance(advanced, Mapping) else self.session.observe()
        observation = normalize_raw_observation(raw_observation, self.map_name, self.player_id)
        next_version = int(observation["loop"])
        if next_version < self._state_version:
            raise RuntimeError(f"raw_sc2_state_regressed:{next_version}<{self._state_version}")
        self._state_version = next_version
        self._observation = observation
        mission = dict(observation.get("mission", {}))
        terminated = bool(mission.get("terminated", False) or observation.get("player_result"))
        info = {
            "action_id": action_id,
            "success": bool(dispatch_result.get("success", False)),
            "action_result": dispatch_result,
            "action_errors": list(observation.get("action_errors", [])),
            "state_version": self._state_version,
            "map_name": self.map_name,
        }
        return dict(observation), terminated, info

    def close(self) -> None:
        self.session.leave()


def normalize_raw_observation(
    raw: Mapping[str, Any],
    map_name: str,
    player_id: int,
) -> dict[str, Any]:
    """Normalize a client mapping without dropping real visible state."""

    if not isinstance(raw, Mapping):
        raise TypeError("raw SC2 observation must be an object")
    loop = _non_negative_int(raw.get("loop", raw.get("state_version", 0)), "loop")
    resources = dict(raw.get("resources", {})) if isinstance(raw.get("resources", {}), Mapping) else {}
    resources.setdefault("minerals", raw.get("minerals", 0))
    resources.setdefault("vespene", raw.get("vespene", 0))
    resources.setdefault("supply_used", raw.get("supply_used", 0))
    resources.setdefault("supply_cap", raw.get("supply_cap", 0))
    resources["state_version"] = loop
    mission = dict(raw.get("mission", {})) if isinstance(raw.get("mission", {}), Mapping) else {}
    player_result = raw.get("player_result", ())
    if player_result:
        mission["terminated"] = True
        mission.setdefault("end_reason", "player_result")
    mission.setdefault("phase", "active")
    mission.setdefault("night", 0)
    mission.setdefault("wave", 0)
    mission.setdefault("terminated", False)
    mission.setdefault("end_reason", "")
    mission.setdefault("win_condition", "unknown")
    mission.setdefault("progress", 0.0)
    mission["state_version"] = loop
    return {
        "loop": loop,
        "player_id": _non_negative_int(raw.get("player_id", player_id), "player_id"),
        "map_name": str(raw.get("map_name", raw.get("map", map_name))) or map_name,
        "own_units": _list_of_mappings(raw.get("own_units", ())),
        "visible_enemies": _list_of_mappings(raw.get("visible_enemies", ())),
        "visible_allies": _list_of_mappings(raw.get("visible_allies", ())),
        "resources": resources,
        "mission": mission,
        "mineral_fields": _list_of_mappings(raw.get("mineral_fields", ())),
        "vespene_geysers": _list_of_mappings(raw.get("vespene_geysers", ())),
        "tech": dict(raw.get("tech", {})) if isinstance(raw.get("tech", {}), Mapping) else {},
        "action_errors": list(raw.get("action_errors", ())),
        "player_result": list(player_result) if isinstance(player_result, (list, tuple)) else player_result,
        "strategic_points": _list_of_mappings(raw.get("strategic_points", ())),
    }


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _non_negative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return int(value)


__all__ = [
    "RawSc2Backend",
    "RawSc2Session",
    "normalize_raw_observation",
]
