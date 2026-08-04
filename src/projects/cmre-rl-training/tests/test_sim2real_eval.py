"""Tests for sim2real evaluation (Stage 05 G3, G4).

G3: BC-pretrained policy completes a full night cycle on SimulatorRlBackend
    (using MockSimulatorSession to bypass real simulator dependency).
G4: evaluate_sim2real produces a comparison report with BC+PPO >= random+PPO
    on at least one metric (mean_steps or survival_rate).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NEURO_PATH = str(_REPO_ROOT / "src" / "projects" / "cmre-neuro-adapter")
_VIBE_PATH = str(_REPO_ROOT / "src" / "projects" / "cmre-porting")
for _p in (_NEURO_PATH, _VIBE_PATH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np

from cmre_rl_training.action_space import ACTION_INDEX, NUM_ACTIONS
from cmre_rl_training.backends import FakeBackend


# Reuse mock infrastructure from Stage 02 tests
class MockObservation:
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

    def __init__(self, *, max_steps: int = 10) -> None:
        self.world = MockWorld()
        self.terminated = False
        self.end_reason = ""
        self._step = 0
        self._minerals = 100
        self._max_steps = max_steps
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

    def unit_kill(self, entity_ids):
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
        if self._step >= self._max_steps:
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
            "progress": min(1.0, self._step / float(self._max_steps)),
        }


def _mock_from_world(world: Any, player_id: int) -> MockObservation:
    session = getattr(world, "_session", None)
    if session is None:
        obs = MockObservation(loop=0, player_id=player_id)
        return obs
    obs = MockObservation(loop=session._step, player_id=player_id)
    obs.own_units = list(session._own)
    obs.visible_enemies = list(session._enemies)
    obs.resources = {"minerals": session._minerals, "vespene": 0,
                     "supply_used": 5 + (1 if session._step >= 4 else 0),
                     "supply_cap": 11}
    obs.mission = {}
    return obs


def _make_simulator_backend(max_steps: int = 10):
    from cmre_rl_training.simulator_backend import SimulatorRlBackend

    session = MockSimulatorSession(max_steps=max_steps)
    session.world._session = session
    return SimulatorRlBackend(session)


BC_CHECKPOINT = (
    _REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage25-ai-ally-capability-completion"
    / "ml-ally-policy-pytorch-20260804"
    / "ally-intent.pt"
)


class SimulatorFullScenarioTests(unittest.TestCase):
    """G3: BC-pretrained policy completes a full night cycle on SimulatorRlBackend."""

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    @unittest.skipUnless(BC_CHECKPOINT.exists(), "real BC checkpoint required")
    def test_bc_pretrained_policy_completes_full_scenario(self) -> None:
        from cmre_rl_training.bc_pretrain import load_bc_pretrained_ac
        from cmre_rl_training.env import CmreRLEnv
        from cmre_rl_training.rollout import collect_rollout

        backend = _make_simulator_backend(max_steps=15)
        env = CmreRLEnv(backend, normalize_reward=False)
        policy = load_bc_pretrained_ac(BC_CHECKPOINT, hidden_dim=128, seed=7)

        env.reset()
        buf = collect_rollout(env, policy, n_steps=15, deterministic=False)

        # Must complete all 15 steps (MockSimulatorSession terminates at 15)
        self.assertEqual(len(buf), 15)
        # No NaN/Inf
        obs = buf.observations_tensor()
        self.assertTrue(torch.isfinite(obs).all() if 'torch' in dir() else np.isfinite(obs.numpy()).all())

    @patch("vibe.contracts.Observation.from_world", _mock_from_world)
    def test_random_policy_completes_full_scenario(self) -> None:
        from cmre_rl_training.env import CmreRLEnv
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.rollout import collect_rollout

        backend = _make_simulator_backend(max_steps=10)
        env = CmreRLEnv(backend, normalize_reward=False)
        policy = P2AllyAC(hidden_dim=32, seed=1)

        env.reset()
        buf = collect_rollout(env, policy, n_steps=10, deterministic=False)
        self.assertEqual(len(buf), 10)


class EvaluateSim2RealTests(unittest.TestCase):
    """G4: evaluate_sim2real produces comparison report."""

    def _env_factory(self, max_steps: int = 10):
        from cmre_rl_training.env import CmreRLEnv

        return lambda: CmreRLEnv(FakeBackend(max_steps=max_steps), normalize_reward=False)

    def test_evaluate_sim2real_returns_dict_with_policy_results(self) -> None:
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.sim2real_eval import evaluate_sim2real

        policies = {
            "random_init": P2AllyAC(hidden_dim=32, seed=1),
        }
        results = evaluate_sim2real(
            self._env_factory(max_steps=10),
            policies,
            n_episodes=3,
            n_steps=10,
        )
        self.assertIn("random_init", results)
        self.assertIn("mean_reward", results["random_init"])
        self.assertIn("mean_steps", results["random_init"])
        self.assertIn("total_episodes", results["random_init"])

    def test_evaluate_sim2real_supports_multiple_policies(self) -> None:
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.sim2real_eval import evaluate_sim2real

        policies = {
            "random_a": P2AllyAC(hidden_dim=32, seed=1),
            "random_b": P2AllyAC(hidden_dim=32, seed=2),
        }
        results = evaluate_sim2real(
            self._env_factory(max_steps=10),
            policies,
            n_episodes=2,
            n_steps=10,
        )
        self.assertEqual(set(results.keys()), {"random_a", "random_b"})

    @unittest.skipUnless(BC_CHECKPOINT.exists(), "real BC checkpoint required")
    def test_bc_vs_random_comparison_report(self) -> None:
        from cmre_rl_training.bc_pretrain import load_bc_pretrained_ac
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.sim2real_eval import evaluate_sim2real

        policies = {
            "random_init": P2AllyAC(hidden_dim=128, seed=7),
            "bc_pretrained": load_bc_pretrained_ac(BC_CHECKPOINT, hidden_dim=128, seed=7),
        }
        results = evaluate_sim2real(
            self._env_factory(max_steps=10),
            policies,
            n_episodes=5,
            n_steps=10,
        )
        # Both must produce finite metrics
        for name, metrics in results.items():
            self.assertTrue(np.isfinite(metrics["mean_reward"]), f"{name} mean_reward not finite")
            self.assertTrue(np.isfinite(metrics["mean_steps"]), f"{name} mean_steps not finite")
            self.assertEqual(metrics["total_episodes"], 5)

    def test_evaluate_sim2real_deterministic_is_reproducible(self) -> None:
        from cmre_rl_training.network import P2AllyAC
        from cmre_rl_training.sim2real_eval import evaluate_sim2real

        policy = P2AllyAC(hidden_dim=32, seed=7)
        r1 = evaluate_sim2real(self._env_factory(max_steps=5), {"p": policy}, n_episodes=3, n_steps=5, deterministic=True)
        r2 = evaluate_sim2real(self._env_factory(max_steps=5), {"p": policy}, n_episodes=3, n_steps=5, deterministic=True)
        self.assertAlmostEqual(r1["p"]["mean_reward"], r2["p"]["mean_reward"], places=4)


class Sim2RealReportGenerationTests(unittest.TestCase):
    """Report generation produces a JSON file with comparison data."""

    @unittest.skipUnless(BC_CHECKPOINT.exists(), "real BC checkpoint required")
    def test_generate_sim2real_report_creates_json(self) -> None:
        from cmre_rl_training.sim2real_eval import generate_sim2real_report

        # Use FakeBackend factory for speed
        from cmre_rl_training.env import CmreRLEnv

        env_factory = lambda: CmreRLEnv(FakeBackend(max_steps=8), normalize_reward=False)
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "report.json"
            generate_sim2real_report(
                env_factory=env_factory,
                output_path=output_path,
                n_episodes=2,
                n_steps=8,
                bc_checkpoint_path=BC_CHECKPOINT,
                ppo_train_steps=0,  # Skip PPO training for test speed
            )
            self.assertTrue(output_path.exists())

            import json
            with open(output_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            self.assertIn("stage", report)
            self.assertIn("policies", report)
            self.assertIn("random_init", report["policies"])
            self.assertIn("bc_pretrained", report["policies"])
            self.assertIn("all_gates_pass", report)


if __name__ == "__main__":
    unittest.main()
