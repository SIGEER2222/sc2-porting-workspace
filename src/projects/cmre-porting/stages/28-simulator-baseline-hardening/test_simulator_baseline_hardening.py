"""Stage 28 simulator baseline hardening regressions."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe import run_cmre_map_matrix  # noqa: E402
from vibe.cmre_map_catalog import build_cooperative_map_scenario  # noqa: E402
from vibe.consumers.ally_ai import AllyAction, run_ally_scenario  # noqa: E402


@dataclass(frozen=True)
class _Objective:
    id: str
    label: str


@dataclass(frozen=True)
class _Geometry:
    base_position: tuple[float, float]
    expansion_position: tuple[float, float]
    attack_points: tuple[tuple[float, float], ...]
    scout_route: tuple[tuple[float, float], ...]
    build_offsets: tuple[tuple[float, float], ...]
    evidence: dict[str, str]


class _FakePolicy:
    action_reason_counts = {"stage28_probe": 1}
    phase_history = ["stage28_probe"]


class _Mode:
    value = "attack"


class _SingleAttackPolicy:
    player_id = 2
    mode = _Mode()
    mode_history = ["attack"]

    def __init__(self) -> None:
        self._issued = False

    def receive_player_command(self, *_args, **_kwargs):
        return None

    def decide(self, obs, loop: int):
        if self._issued or not obs.visible_enemies:
            return []
        marine = next(
            unit for unit in obs.own_units
            if unit.get("unit_type_id") == "Marine"
        )
        target = obs.visible_enemies[0]
        self._issued = True
        return [
            AllyAction(
                entity_id=int(marine["entity_id"]),
                kind="attack",
                target_entity_id=int(target["entity_id"]),
                reason="stage28_issuer_probe",
            )
        ]

    def oscillation_score(self) -> int:
        return 0

    def drain_notices(self) -> list:
        return []


class Stage28SimulatorBaselineHardeningTests(unittest.TestCase):
    def test_map_probe_classifies_full_game_as_adapter_clearance_only(self):
        scenario = {
            "schema_version": "m7",
            "name": "cmre-map-stage28-probe",
            "map_name": "stage28-probe",
            "players": [],
            "spawns": [
                {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
                {"unit_type_id": "Marine", "owner_player_id": 2, "x": 1.0, "y": 0.0},
            ],
            "_map_metadata": {
                "map_path": "src/projects/cmre-porting/packages/Maps/stage28.SC2Map",
                "map_hash": "stage28-hash",
                "native_object_count": 1,
                "native_spawn_count": 2,
                "simulator_transformation_audit": {
                    "claim": "deterministic simulator adapter clearance only; no native SC2 mission completion"
                },
            },
        }
        profile = SimpleNamespace(
            archetype="probe",
            features=("economy",),
            objectives=(_Objective("clear", "Clear enemies"),),
        )
        geometry = _Geometry(
            base_position=(10.0, 10.0),
            expansion_position=(12.0, 12.0),
            attack_points=((20.0, 20.0),),
            scout_route=((15.0, 15.0),),
            build_offsets=((1.0, 1.0),),
            evidence={"p2_base": "test"},
        )
        fake_result = SimpleNamespace(
            action_kind_counts={"attack": 1, "gather": 1},
            action_actor_type_counts={"Marine": 1},
            attack_actor_type_counts={"Marine": 1},
            worker_attack_action_count=0,
            end_loop=8,
            end_reason="enemy_elimination",
            roster_ready=True,
            total_dispatched=2,
            hidden_state_access_violations=0,
            friendly_fire_rejections=0,
            total_dispatch_errors=0,
            deadlock_detected=False,
            command_storm_detected=False,
            final_enemy_units_by_type={},
            final_units_by_type={"Marine": 1},
            final_resources={"minerals": 50},
            final_tech={"completed_upgrades": [], "researching": []},
            error_breakdown={},
            replay_frame_count=0,
        )

        with (
            patch.object(
                run_cmre_map_matrix,
                "build_cooperative_map_scenario",
                return_value=(SimpleNamespace(scenario=scenario, regions={}), profile, geometry),
            ),
            patch.object(run_cmre_map_matrix, "LadderAI", return_value=_FakePolicy()),
            patch.object(run_cmre_map_matrix, "run_ally_scenario", return_value=fake_result),
        ):
            summary = run_cmre_map_matrix.run_map_probe(
                Path("stage28.SC2Map"),
                full_game=True,
                output_dir=None,
            )

        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["result_category"], "adapter_clearance")
        self.assertEqual(summary["probe_status"], "ADAPTER_CLEARANCE_PASS")
        self.assertNotEqual(summary["probe_status"], "FULL_GAME_PASS")
        self.assertEqual(
            summary["claim_status"],
            "simulator_adapter_clearance_not_native_runtime",
        )
        self.assertIn("native SC2 mission completion not exercised", summary["runtime_claim"])
        self.assertEqual(summary["action_actor_type_counts"], {"Marine": 1})
        self.assertEqual(summary["attack_actor_type_counts"], {"Marine": 1})
        self.assertEqual(summary["worker_attack_action_count"], 0)
        self.assertIn("claim", summary["simulator_transformation_audit"])

    def test_map_catalog_exposes_transformation_audit(self):
        map_path = REPO_ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps" / "亡者之夜.SC2Map"
        data, _profile, _geometry = build_cooperative_map_scenario(
            map_path,
            max_enemy_per_player=1,
            stage_enemies_for_full_game=True,
        )
        audit = data.scenario["_map_metadata"]["simulator_transformation_audit"]

        self.assertEqual(
            audit["claim"],
            "deterministic simulator adapter clearance only; no native SC2 mission completion",
        )
        self.assertGreater(audit["source_static"]["native_object_count"], 0)
        self.assertGreater(audit["adapter_transforms"]["starting_force_injected"], 0)
        self.assertIsInstance(audit["adapter_transforms"]["resource_normalized_from"], list)
        self.assertTrue(audit["simulator_only"]["enemy_staged_for_full_game"])

    def test_ally_actions_and_replay_record_issuer_unit_types(self):
        scenario = {
            "schema_version": "m7",
            "name": "stage28 issuer audit",
            "players": [
                {"id": 1, "name": "P1", "race": "terran", "allies": [2], "is_ai": False},
                {"id": 2, "name": "P2", "race": "terran", "allies": [1], "is_ai": True},
                {"id": 3, "name": "Enemy", "race": "zerg", "allies": [], "is_ai": True},
            ],
            "spawns": [
                {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
                {"unit_type_id": "Marine", "owner_player_id": 2, "x": 1.0, "y": 0.0},
                {"unit_type_id": "SCV", "owner_player_id": 2, "x": 2.0, "y": 0.0},
                {"unit_type_id": "Zergling", "owner_player_id": 3, "x": 3.0, "y": 0.0},
            ],
            "commands": [],
            "max_loops": 8,
            "seed": 42,
            "strict": True,
            "win_condition": "custom",
            "_cooperative_enemy_player_ids": [3],
        }
        with tempfile.TemporaryDirectory(prefix="stage28-issuer-") as directory:
            replay_path = Path(directory) / "replay.jsonl"
            result = run_ally_scenario(
                scenario,
                _SingleAttackPolicy(),
                ally_player_id=2,
                leader_player_id=1,
                max_loops=8,
                latency_loops=0,
                replay_log_path=replay_path,
                replay_log_interval=1,
            )
            records = [
                json.loads(line)
                for line in replay_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(result.attack_actor_type_counts, {"Marine": 1})
        self.assertEqual(result.action_actor_type_counts.get("Marine"), 1)
        self.assertEqual(result.worker_attack_action_count, 0)
        queued = next(record for record in records if record.get("kind") == "ally_action")
        dispatch = next(
            event
            for record in records
            for event in record.get("events", [])
            if event.get("kind") == "p2_dispatch"
        )
        self.assertEqual(queued["arguments"]["issuer_unit_type"], "Marine")
        self.assertEqual(dispatch["issuer_unit_type"], "Marine")


if __name__ == "__main__":
    unittest.main()
