"""Tests for SimulatorRlBackend protocol conformance and env loop (G1, G4).

Uses a mock session that bypasses ``Observation.from_world`` to avoid
the sc2_simulator dependency. Real-session integration is tracked as
ISSUE-004 in issues.json.
"""

from __future__ import annotations

import sys
import unittest
from typing import Any, Mapping
from unittest.mock import patch

_REPO_ROOT = r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
_NEURO_PATH = _REPO_ROOT + r"\src\projects\cmre-neuro-adapter"
_VIBE_PATH = _REPO_ROOT + r"\src\projects\cmre-porting"
for _p in (_NEURO_PATH, _VIBE_PATH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cmre_rl_training.backends import RlBackend
from cmre_rl_training.simulator_backend import SimulatorRlBackend


class MockObservation:
    """Mimics the Observation dataclass returned by ``Observation.from_world``."""

    def __init__(self, loop: int, player_id: int) -> None:
        self.loop = loop
        self.player_id = player_id
        self.own_units: list[dict] = []
        self.visible_enemies: list[dict] = []
        self.resources: dict = {"minerals": 100, "vespene": 0,
                                "supply_used": 5, "supply_cap": 11}
        self.mission: dict = {}


class MockRunResult:
    def __init__(self, loop: int) -> None:
        self.loop = loop


class MockEntity:
    def __init__(self, eid: int, utype: str, owner: int,
                 x: float, y: float, hp: float) -> None:
        self.entity_id = eid
        self.unit_type_id = utype
        self.owner_player_id = owner
        self.x = x
        self.y = y
        self.health = type("Val", (), {"raw": hp})()
        self.shields = type("Val", (), {"raw": 0})()
        self.energy = type("Val", (), {"raw": 0})()
        self.state = "idle"
        self.orders: list = []


class MockWorld:
    def __init__(self) -> None:
        self.clock = type("Clock", (), {"now": type("Loop", (), {"loop": 0})()})()
        self.entities: dict[int, MockEntity] = {}
        self.command_results: list = []


class MockSimulatorSession:
    """Minimal mock implementing the SimulatorSession surface."""

    def __init__(self) -> None:
        self.world = MockWorld()
        self.terminated = False
        self.end_reason = ""
        self._step = 0
        self._minerals = 100
        self._own = [
            {"entity_id": 1, "unit_type_id": "CommandCenter", "owner": 1,
             "x": 85, "y": 94, "health": 1500, "shields": 0, "energy": 0,
             "state": "idle", "orders": []},
            {"entity_id": 2, "unit_type_id": "SCV", "owner": 1,
             "x": 86, "y": 93, "health": 45, "shields": 0, "energy": 0,
             "state": "gathering", "orders": [{"kind": "gather"}]},
            {"entity_id": 3, "unit_type_id": "Marine", "owner": 1,
             "x": 87, "y": 92, "health": 45, "shields": 0, "energy": 0,
             "state": "idle", "orders": []},
        ]
        self._enemies: list[dict] = []

    def unit_order(self, entity_ids, kind, issuer_player_id,
                   target_entity_id=0, target_x=0.0, target_y=0.0,
                   unit_type_id="", ability_id=""):
        return {"loop": self._step, "message": "applied"}

    def unit_spawn(self, unit_type_id, owner_player_id, x, y):
        return {"loop": self._step}

    def unit_kill(self, entity_id):
        return {"loop": self._step}

    def player_set_resource(self, player_id, minerals=None, vespene=None):
        return {"loop": self._step}

    def scenario_step(self, loops=1):
        self._step += int(loops)
        self._minerals += 10
        self.world.clock.now.loop = self._step
        if self._step >= 5:
            self._enemies = [
                {"entity_id": 100, "unit_type_id": "Zergling", "owner": 3,
                 "x": 70, "y": 80, "health": 35, "shields": 0, "energy": 0,
                 "state": "moving", "orders": []},
            ]
        if self._step >= 10:
            self.terminated = True
            self.end_reason = "survive_loops"
        return MockRunResult(self._step)

    def query_mission(self):
        return {
            "phase": "victory" if self.terminated else "active",
            "night": 0 if self._step < 5 else 1,
            "wave": 0 if self._step < 3 else 1,
            "terminated": self.terminated,
            "end_reason": self.end_reason,
            "win_condition": "survive_loops",
            "progress": min(1.0, self._step / 10.0),
        }


def _mock_from_world(world: Any, player_id: int) -> MockObservation:
    """Replacement for ``Observation.from_world`` in tests."""

    session = getattr(world, "_session", None)
    if session is None:
        # Return a minimal observation
        obs = MockObservation(
            loop=getattr(world.clock.now, "loop", 0),
            player_id=player_id,
        )
        obs.own_units = []
        obs.visible_enemies = []
        obs.resources = {"minerals": 100, "vespene": 0,
                         "supply_used": 5, "supply_cap": 11}
        obs.mission = {}
        return obs

    obs = MockObservation(
        loop=session._step,
        player_id=player_id,
    )
    obs.own_units = list(session._own)
    obs.visible_enemies = list(session._enemies)
    obs.resources = {"minerals": session._minerals, "vespene": 0,
                     "supply_used": 5 + (1 if session._step >= 4 else 0),
                     "supply_cap": 11}
    obs.mission = {}
    return obs


class SimulatorRlBackendProtocolTests(unittest.TestCase):
    """G1: Protocol conformance."""

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_implements_rl_backend_protocol(self) -> None:
        session = MockSimulatorSession()
        session.world._session = session
        backend = SimulatorRlBackend(session)
        self.assertIsInstance(backend, RlBackend)

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_state_version_property(self) -> None:
        session = MockSimulatorSession()
        session.world._session = session
        backend = SimulatorRlBackend(session)
        self.assertIsInstance(backend.state_version, int)
        self.assertGreaterEqual(backend.state_version, 0)


class SimulatorRlBackendLoopTests(unittest.TestCase):
    """G4: Env loop with mock simulator session."""

    def _make_backend(self) -> SimulatorRlBackend:
        session = MockSimulatorSession()
        session.world._session = session
        return SimulatorRlBackend(session)

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_reset_returns_observation_dict(self) -> None:
        backend = self._make_backend()
        obs = backend.reset()
        self.assertIsInstance(obs, dict)
        self.assertIn("own_units", obs)
        self.assertIn("visible_enemies", obs)
        self.assertIn("resources", obs)
        self.assertIn("mission", obs)

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_step_returns_tuple(self) -> None:
        backend = self._make_backend()
        backend.reset()
        obs, terminated, info = backend.step("move_units", {
            "entity_ids": [3],
            "issuer_player_id": 1,
            "target_x": 70.0,
            "target_y": 80.0,
        })
        self.assertIsInstance(obs, dict)
        self.assertIsInstance(terminated, bool)
        self.assertIsInstance(info, dict)
        self.assertIn("success", info)

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_state_version_advances_on_step(self) -> None:
        backend = self._make_backend()
        backend.reset()
        v0 = backend.state_version
        backend.step("stop_units", {"entity_ids": [3], "issuer_player_id": 1})
        self.assertGreater(backend.state_version, v0)

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_terminates_after_max_steps(self) -> None:
        backend = self._make_backend()
        backend.reset()
        terminated = False
        for _ in range(15):
            _, terminated, _ = backend.step(
                "stop_units", {"entity_ids": [3], "issuer_player_id": 1}
            )
            if terminated:
                break
        self.assertTrue(terminated)

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_env_loop_with_cmre_rl_env(self) -> None:
        """Full CmreRLEnv + SimulatorRlBackend integration."""
        import numpy as np
        from cmre_rl_training.action_space import ACTION_INDEX
        from cmre_rl_training.env import CmreRLEnv

        backend = self._make_backend()
        env = CmreRLEnv(backend)

        obs = env.reset()
        self.assertIsInstance(obs, np.ndarray)

        mask = env.action_mask()
        self.assertEqual(len(mask), env.action_dim)

        terminated = False
        for _ in range(15):
            mask = env.action_mask()
            legal = [i for i, ok in enumerate(mask) if ok]
            if not legal:
                break
            action_name = [
                k for k, v in ACTION_INDEX.items() if v == legal[0]
            ][0]
            _, _, terminated, _ = env.step(action_name)
            if terminated:
                break

        self.assertTrue(terminated)


if __name__ == "__main__":
    unittest.main()
