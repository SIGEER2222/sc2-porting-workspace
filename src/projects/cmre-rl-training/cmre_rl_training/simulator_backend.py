"""SimulatorRlBackend: wrap SimulatorSessionBackend for the RL env.

Adapts the existing ``SimulatorSessionBackend`` (from ``cmre_neuro_adapter``)
to the ``RlBackend`` protocol so ``CmreRLEnv`` can drive the deterministic
simulator without knowing its internals.

The backend produces raw observation dicts (not ``PublicMissionContext``) so
that fields like ``mineral_fields`` and ``tech`` survive for the encoder.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from .backends import RlBackend


class SimulatorRlBackend:
    """RL backend backed by ``SimulatorSessionBackend``.

    Parameters
    ----------
    session
        A ``SimulatorSession`` instance (from ``vibe.simulator_session``).
    action_operations
        Mapping from action name to simulator operation. Defaults to
        ``basic_action_operations()`` from ``cmre_neuro_adapter``.
    player_id
        The player perspective to observe.
    map_name
        Map identifier for context projection.
    """

    def __init__(
        self,
        session: Any,
        *,
        action_operations: Mapping[str, str] | None = None,
        player_id: int = 1,
        map_name: str = "dead-of-night",
    ) -> None:
        # Lazy import to avoid hard dependency when only FakeBackend is used
        from cmre_neuro_adapter.neuro.basic_actions import (
            basic_action_operations,
        )
        from cmre_neuro_adapter.neuro.simulator_transport import (
            SimulatorSessionBackend,
            SimulatorTransport,
        )

        ops = dict(action_operations or basic_action_operations())
        self._session = session
        self._player_id = player_id
        self._map_name = map_name
        self._backend = SimulatorSessionBackend(
            session, action_operations=ops
        )
        self._transport = SimulatorTransport(
            self._backend,
            action_operations=ops,
            player_id=player_id,
            map_name=map_name,
        )

    @property
    def state_version(self) -> int:
        return self._backend.state_version

    def reset(self) -> dict[str, Any]:
        """Return the initial observation after scenario reset.

        Assumes the session has already been loaded and reset by the caller.
        Only reads the first observation.
        """

        return self._read_observation()

    def step(
        self, action_id: str, args: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        """Dispatch one action and advance the simulator by one step."""

        from cmre_neuro_adapter.neuro.actions import ActionCommand

        action_args = dict(args)
        if "issuer_player_id" not in action_args:
            action_args["issuer_player_id"] = self._player_id
        if "entity_ids" not in action_args:
            # Default to all own units if not specified
            obs = self._read_observation()
            own = obs.get("own_units", [])
            action_args["entity_ids"] = [u["entity_id"] for u in own[:1]]

        command = ActionCommand(
            action_id=f"rl-{action_id}-{int(time.time() * 1000)}",
            name=action_id,
            args=action_args,
            received_at=time.time(),
        )

        result = self._transport.dispatch(command)
        # Advance simulator by one step
        self._backend.execute("scenario.step", {"loops": 1})

        obs = self._read_observation()
        terminated = bool(obs.get("mission", {}).get("terminated", False))
        info: dict[str, Any] = {
            "action_id": action_id,
            "success": result.success,
            "message": result.message,
            "operation": result.operation,
            "state_version": self.state_version,
        }
        return obs, terminated, info

    def _read_observation(self) -> dict[str, Any]:
        """Read observation from backend and enrich with encoder-required fields."""

        raw = self._backend.observe(self._player_id)
        # SimulatorSessionBackend.observe returns:
        # {loop, player_id, own_units, visible_enemies, resources, mission}
        # Add fields the encoder expects with defaults
        return {
            "loop": raw.get("loop", 0),
            "player_id": raw.get("player_id", self._player_id),
            "own_units": list(raw.get("own_units", [])),
            "visible_enemies": list(raw.get("visible_enemies", [])),
            "visible_allies": [],
            "resources": dict(raw.get("resources", {})),
            "mission": dict(raw.get("mission", {})),
            "mineral_fields": [],
            "vespene_geysers": [],
            "tech": {"completed_upgrades": [], "researching": []},
        }


__all__ = ["SimulatorRlBackend"]
