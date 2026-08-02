"""Stage 25 simulator contract for a P1 human / P2 AI ally."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.consumers.ally_ai import (  # noqa: E402
    ActionAdapter,
    AllyAction,
    AllyMode,
    AllyPolicy,
    PlayerCommandAdapter,
    PlayerSignalKind,
    validate_cooperative_roster,
    run_ally_scenario,
)
from vibe.defend_policy import DefendBasePolicy  # noqa: E402
from vibe.contracts import Observation  # noqa: E402
from vibe.simulator_session import SimulatorSession  # noqa: E402
from vibe.replay_player import load_replay, render_player_html  # noqa: E402
from vibe.map_replay import load_dead_of_night_map_cooperative_scenario  # noqa: E402


def _cooperative_scenario(seed: int = 42) -> dict:
    return {
        "schema_version": "m7",
        "name": "stage25-p1-human-p2-ai-ally",
        "players": [
            {"id": 1, "name": "Player", "race": "terran", "allies": [2], "is_ai": False},
            {"id": 2, "name": "AI Ally", "race": "terran", "allies": [1], "is_ai": True},
            {"id": 3, "name": "Enemy A", "race": "zerg", "allies": [], "is_ai": True},
            {"id": 4, "name": "Enemy B", "race": "zerg", "allies": [], "is_ai": True},
            {"id": 5, "name": "Enemy C", "race": "zerg", "allies": [], "is_ai": True},
        ],
        "spawns": [
            {"unit_type_id": "Marine", "owner_player_id": 1, "x": 0.0, "y": 0.0},
            {"unit_type_id": "Marine", "owner_player_id": 2, "x": 1.0, "y": 0.0},
            {"unit_type_id": "Marine", "owner_player_id": 2, "x": 1.0, "y": 1.0},
            {"unit_type_id": "Zergling", "owner_player_id": 3, "x": 5.0, "y": 0.0},
            {"unit_type_id": "Zergling", "owner_player_id": 4, "x": 50.0, "y": 50.0},
            {"unit_type_id": "Zergling", "owner_player_id": 5, "x": 60.0, "y": 60.0},
        ],
        "commands": [],
        "max_loops": 100,
        "seed": seed,
        "strict": True,
        "win_condition": "custom",
    }


class Stage25AiAllyCapabilityTests(unittest.TestCase):
    def test_native_policy_never_attacks_with_scv_or_mission_caster(self):
        policy = DefendBasePolicy(
            player_id=1,
            base_region=(0.0, 0.0, 6.0),
            support_range=10.0,
            command_interval=1,
            econ_interval=9999,
        )
        observation = Observation(
            loop=1,
            player_id=1,
            own_units=[
                {
                    "entity_id": 101,
                    "unit_type_id": "CoopCasterRaynor",
                    "owner": 1,
                    "x": 0.0,
                    "y": 0.0,
                    "health": 100 * 1024,
                    "max_health": 100 * 1024,
                },
                {
                    "entity_id": 102,
                    "unit_type_id": "SCV",
                    "owner": 1,
                    "x": 2.0,
                    "y": 0.0,
                    "health": 45 * 1024,
                    "max_health": 45 * 1024,
                },
            ],
            visible_enemies=[
                {
                    "entity_id": 201,
                    "unit_type_id": "Zergling",
                    "owner": 3,
                    "x": 1.0,
                    "y": 0.0,
                    "health": 35 * 1024,
                    "max_health": 35 * 1024,
                },
            ],
            resources={"minerals": 0, "vespene": 0, "supply_used": 2, "supply_cap": 15},
            mission={},
        )

        actions = policy.decide(observation, loop=1, resources=observation.resources)

        attacks = [action for action in actions if action.kind == "attack"]
        self.assertEqual(attacks, [])
        self.assertTrue(all(
            action.entity_id != 102 or action.kind in {"move", "hold", "gather", "build", "train"}
            for action in actions
        ))

    def test_p2_opening_builds_barracks_and_refinery_with_scvs(self):
        policy = DefendBasePolicy(
            player_id=2,
            base_region=(10.0, 10.0, 6.0),
            command_interval=1,
            econ_interval=1,
        )
        observation = Observation(
            loop=1,
            player_id=2,
            own_units=[
                {"entity_id": 201, "unit_type_id": "CommandCenter", "owner": 2,
                 "x": 10.0, "y": 10.0, "health": 1400 * 1024,
                 "max_health": 1400 * 1024},
                {"entity_id": 202, "unit_type_id": "SCV", "owner": 2,
                 "x": 8.0, "y": 10.0, "health": 45 * 1024,
                 "max_health": 45 * 1024},
                {"entity_id": 203, "unit_type_id": "SCV", "owner": 2,
                 "x": 8.0, "y": 11.0, "health": 45 * 1024,
                 "max_health": 45 * 1024},
            ],
            visible_enemies=[],
            resources={"minerals": 500, "vespene": 0, "supply_used": 3,
                       "supply_cap": 15,
                       "vespene_geysers": [{"entity_id": 900, "x": 14.0, "y": 13.0}]},
            mission={},
        )

        actions = policy.decide(observation, loop=1, resources=observation.resources)
        builds = [action for action in actions if action.kind == "build"]

        self.assertEqual({action.unit_type_id for action in builds}, {"Barracks", "Refinery"})
        self.assertEqual({action.entity_id for action in builds}, {202, 203})
        refinery = next(action for action in builds if action.unit_type_id == "Refinery")
        self.assertEqual(refinery.target_entity_id, 900)
        self.assertEqual((refinery.target_x, refinery.target_y), (14.0, 13.0))
        self.assertTrue(all(action.entity_id not in {202, 203} or action.kind == "build"
                            for action in actions if action.kind != "hold"))

    def test_p2_producer_trains_combat_unit_but_not_scv_as_attacker(self):
        policy = DefendBasePolicy(player_id=2, command_interval=1, econ_interval=1)
        observation = Observation(
            loop=1,
            player_id=2,
            own_units=[
                {"entity_id": 301, "unit_type_id": "CommandCenter", "owner": 2,
                 "x": 85.0, "y": 94.0, "health": 1400 * 1024,
                 "max_health": 1400 * 1024},
                {"entity_id": 302, "unit_type_id": "Barracks", "owner": 2,
                 "x": 90.0, "y": 94.0, "health": 800 * 1024,
                 "max_health": 800 * 1024},
                {"entity_id": 303, "unit_type_id": "SCV", "owner": 2,
                 "x": 82.0, "y": 94.0, "health": 45 * 1024,
                 "max_health": 45 * 1024},
            ],
            visible_enemies=[
                {"entity_id": 399, "unit_type_id": "Zergling", "owner": 3,
                 "x": 100.0, "y": 100.0, "health": 35 * 1024,
                 "max_health": 35 * 1024},
            ],
            resources={"minerals": 500, "vespene": 0, "supply_used": 3,
                       "supply_cap": 15},
            mission={},
        )

        actions = policy.decide(observation, loop=1, resources=observation.resources)
        train_actions = [action for action in actions if action.kind == "train"]
        self.assertTrue(any(action.entity_id == 302 and action.unit_type_id == "Marine"
                            for action in train_actions))
        self.assertFalse(any(action.kind == "attack" and action.entity_id == 303
                             for action in actions))

    def test_base_threat_pauses_economy_and_keeps_scv_non_combat(self):
        policy = DefendBasePolicy(player_id=2, command_interval=1, econ_interval=1)
        observation = Observation(
            loop=1,
            player_id=2,
            own_units=[
                {"entity_id": 401, "unit_type_id": "CommandCenter", "owner": 2,
                 "x": 85.0, "y": 94.0, "health": 1400 * 1024,
                 "max_health": 1400 * 1024},
                {"entity_id": 402, "unit_type_id": "SCV", "owner": 2,
                 "x": 84.0, "y": 94.0, "health": 45 * 1024,
                 "max_health": 45 * 1024},
            ],
            visible_enemies=[
                {"entity_id": 499, "unit_type_id": "Zergling", "owner": 3,
                 "x": 85.0, "y": 94.0, "health": 35 * 1024,
                 "max_health": 35 * 1024},
            ],
            resources={"minerals": 500, "vespene": 0, "supply_used": 2,
                       "supply_cap": 15},
            mission={},
        )

        actions = policy.decide(observation, loop=1, resources=observation.resources)

        self.assertEqual(
            [(action.entity_id, action.kind) for action in actions],
            [(402, "move")],
        )

    def test_completed_refinery_gets_three_scvs_and_remaining_workers_mine(self):
        policy = DefendBasePolicy(player_id=2, command_interval=1, econ_interval=1)
        workers = [
            {"entity_id": 500 + index, "unit_type_id": "SCV", "owner": 2,
             "x": 80.0 + index, "y": 94.0, "health": 45 * 1024,
             "max_health": 45 * 1024}
            for index in range(5)
        ]
        observation = Observation(
            loop=1,
            player_id=2,
            own_units=[
                {"entity_id": 501, "unit_type_id": "CommandCenter", "owner": 2,
                 "x": 85.0, "y": 94.0, "health": 1400 * 1024,
                 "max_health": 1400 * 1024},
                {"entity_id": 502, "unit_type_id": "Barracks", "owner": 2,
                 "x": 90.0, "y": 94.0, "health": 800 * 1024,
                 "max_health": 800 * 1024},
                {"entity_id": 503, "unit_type_id": "Refinery", "owner": 2,
                 "x": 82.0, "y": 99.0, "health": 500 * 1024,
                 "max_health": 500 * 1024},
                *workers,
            ],
            visible_enemies=[],
            resources={"minerals": 0, "vespene": 0, "supply_used": 7,
                       "supply_cap": 15},
            mission={},
        )

        actions = policy.decide(observation, loop=1, resources=observation.resources)
        gas = [action for action in actions if action.reason == "gather_gas"]
        minerals = [action for action in actions if action.reason == "gather_minerals"]

        self.assertEqual(len(gas), 3)
        self.assertEqual({action.target_entity_id for action in gas}, {503})
        self.assertEqual(len(minerals), 2)

    def test_missing_high_tech_producers_do_not_block_barracks_marine(self):
        policy = DefendBasePolicy(player_id=2, command_interval=1, econ_interval=1)
        observation = Observation(
            loop=1,
            player_id=2,
            own_units=[
                {"entity_id": 601, "unit_type_id": "CommandCenter", "owner": 2,
                 "x": 85.0, "y": 94.0, "health": 1400 * 1024,
                 "max_health": 1400 * 1024},
                {"entity_id": 602, "unit_type_id": "Barracks", "owner": 2,
                 "x": 90.0, "y": 94.0, "health": 800 * 1024,
                 "max_health": 800 * 1024},
                {"entity_id": 603, "unit_type_id": "Refinery", "owner": 2,
                 "x": 82.0, "y": 99.0, "health": 500 * 1024,
                 "max_health": 500 * 1024},
            ],
            visible_enemies=[],
            resources={"minerals": 1000, "vespene": 300, "supply_used": 3,
                       "supply_cap": 15},
            mission={},
        )

        actions = policy.decide(observation, loop=1, resources=observation.resources)

        self.assertTrue(any(
            action.kind == "train"
            and action.entity_id == 602
            and action.unit_type_id == "Marine"
            for action in actions
        ))

    def test_roster_requires_reciprocal_p1_p2_and_ai_identity(self):
        roster = validate_cooperative_roster(_cooperative_scenario())
        self.assertTrue(roster.valid, roster.issues)
        self.assertEqual(roster.ally_player_id, 2)
        self.assertEqual(roster.enemy_player_ids, (3, 4, 5))

        invalid = _cooperative_scenario()
        invalid["players"][0]["allies"] = []
        invalid_roster = validate_cooperative_roster(invalid)
        self.assertFalse(invalid_roster.valid)
        self.assertIn("leader_missing_ally_edge", invalid_roster.issues)

    def test_p2_observes_p1_as_ally_but_owns_only_p2_units(self):
        session = SimulatorSession()
        session.scenario_load(scenario_dict=_cooperative_scenario(), catalog="m7")
        session.scenario_reset()
        observation = Observation.from_world(session.world, 2)

        self.assertEqual({unit["owner"] for unit in observation.own_units}, {2})
        self.assertEqual({unit["owner"] for unit in observation.visible_allies}, {1})
        summary = {item["player_id"]: item for item in observation.alliance_summary}
        self.assertTrue(summary[1]["alive"])
        self.assertTrue(summary[2]["is_ai"])
        self.assertEqual(summary[2]["unit_count"], 2)
        self.assertFalse(any(item["player_id"] in {3, 4, 5} for item in summary.values()))

    def test_player_commands_are_authorized_deduplicated_and_acknowledged(self):
        adapter = PlayerCommandAdapter((1,))
        command = adapter.receive("!ally defend", source_player_id=1, loop=10, command_id="a")
        duplicate = adapter.receive("!ally defend", source_player_id=1, loop=10, command_id="a")
        rejected = adapter.receive("!ally attack", source_player_id=3, loop=10, command_id="b")
        self.assertEqual(command.kind, PlayerSignalKind.DEFEND)
        self.assertTrue(command.accepted)
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(rejected.accepted)

        policy = AllyPolicy(player_id=2, leader_entity_id=1, leader_player_id=1)
        notice = policy.receive_player_command("!ally defend", loop=10, command_id="p1-defend")
        self.assertTrue(notice.accepted)
        self.assertEqual(policy.mode, AllyMode.DEFEND_BASE)
        status = policy.receive_player_command("!ally status", loop=11, command_id="p1-status")
        self.assertIn("mode=defend_base", status.message)
        self.assertTrue(any("Acknowledged: defend." in item.message for item in policy.drain_notices()))

    def test_p2_action_issuer_and_friendly_fire_gate(self):
        session = SimulatorSession()
        session.scenario_load(scenario_dict=_cooperative_scenario(), catalog="m7")
        session.scenario_reset()
        adapter = ActionAdapter(session, latency_loops=0, controlled_player_id=2)
        p2_unit = next(unit.entity_id for unit in session.world.entities.values() if unit.owner_player_id == 2)
        p1_unit = next(unit.entity_id for unit in session.world.entities.values() if unit.owner_player_id == 1)

        with patch.object(session, "unit_order", wraps=session.unit_order) as order:
            adapter.issue([AllyAction(p2_unit, "move", target_x=3.0, target_y=3.0)], loop=0)
            moved = adapter.dispatch_due(0)
            order.assert_called_once()
            self.assertEqual(order.call_args.kwargs["issuer_player_id"], 2)
        self.assertTrue(moved[0].dispatched)

        adapter.issue([AllyAction(p2_unit, "attack", target_entity_id=p1_unit)], loop=1)
        blocked = adapter.dispatch_due(1)
        self.assertEqual(blocked[0].error, "friendly_fire_blocked")
        self.assertEqual(adapter.friendly_fire_rejections, 1)

    def test_p2_receives_commands_and_transitions_across_cooperative_modes(self):
        scenario = _cooperative_scenario()
        # Keep the threat in the map but outside initial vision so explicit
        # player commands can be observed without combat priority masking them.
        scenario["spawns"][3]["x"] = 20.0
        policy = AllyPolicy(
            player_id=2,
            leader_entity_id=1,
            leader_player_id=1,
            base_region=(0.0, 0.0, 2.0),
            support_range=8.0,
            command_interval=1,
        )
        result = run_ally_scenario(
            scenario,
            policy,
            ally_player_id=2,
            max_loops=40,
            latency_loops=0,
            require_cooperative_roster=True,
            player_commands=[
                {"loop": 0, "text": "!ally follow", "command_id": "follow"},
                {"loop": 8, "text": "!ally attack", "command_id": "attack"},
                {"loop": 16, "text": "!ally defend", "command_id": "defend"},
                {"loop": 24, "text": "!ally retreat", "command_id": "retreat"},
            ],
        )
        self.assertTrue(result.roster_ready, result.roster_issues)
        self.assertEqual(result.hidden_state_access_violations, 0)
        self.assertEqual(result.friendly_fire_rejections, 0)
        self.assertGreater(result.total_dispatched, 0)
        modes = {entry.split(":", 1)[0] for entry in result.mode_history}
        self.assertTrue({"follow", "assist_attack", "defend_base", "retreat"}.issubset(modes))
        self.assertTrue(any("Acknowledged: attack." in notice.message for notice in result.notices))
        self.assertTrue(all(
            action.entity_id in {2, 3}
            for decision in result.decisions
            for action in decision.actions
        ))

    def test_cooperative_replay_exports_p1_p2_timeline_and_html(self):
        scenario = _cooperative_scenario()
        with tempfile.TemporaryDirectory() as directory:
            replay_path = Path(directory) / "cooperative-replay.jsonl"
            html_path = Path(directory) / "full-map-player.html"
            policy = AllyPolicy(
                player_id=2,
                leader_entity_id=1,
                leader_player_id=1,
                base_region=(0.0, 0.0, 2.0),
                support_range=8.0,
                command_interval=1,
            )
            result = run_ally_scenario(
                scenario,
                policy,
                ally_player_id=2,
                max_loops=16,
                latency_loops=0,
                require_cooperative_roster=True,
                player_commands=[
                    {"loop": 0, "text": "!ally follow", "command_id": "follow"},
                    {"loop": 4, "text": "!ally defend", "command_id": "defend"},
                    {"loop": 8, "text": "!ally retreat", "command_id": "retreat"},
                ],
                replay_log_path=replay_path,
            )

            records = load_replay(replay_path)
            frames = [record for record in records if record.get("record_type") == "frame"]
            actions = [record for record in records if record.get("record_type") == "action"]
            self.assertTrue(replay_path.exists())
            self.assertEqual(result.replay_path, str(replay_path))
            self.assertEqual(result.replay_frame_count, len(frames))
            self.assertGreaterEqual(len(frames), 2)
            self.assertEqual(records[0]["record_type"], "header")
            self.assertEqual(records[0]["owner_roles"]["1"]["relation"], "leader")
            self.assertEqual(records[0]["owner_roles"]["2"]["relation"], "ally")
            self.assertTrue(any(action["kind"] == "player_command" for action in actions))
            self.assertTrue(any(
                action["kind"] == "ally_action"
                and action["owner"] == 2
                and action["issuer_player_id"] == 2
                for action in actions
            ))
            self.assertTrue(any(
                frame["context"]["visible_allies"]
                and all(unit["owner"] == 1 for unit in frame["context"]["visible_allies"])
                for frame in frames
            ))

            render_player_html(records, replay_path, html_path)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("P2 AI 盟友存活", html)
            self.assertIn("P1 指令 / P2 回执", html)
            self.assertIn('"relation":"ally"', html)
            self.assertIn('"kind":"player_command"', html)

    def test_map_derived_replay_matches_dead_of_night_objects_without_fixture_units(self):
        data, metadata = load_dead_of_night_map_cooperative_scenario()
        scenario = data.scenario
        self.assertEqual(metadata["source_kind"], "map_extractor")
        self.assertEqual(metadata["native_object_count"], 1319)
        self.assertEqual(metadata["native_spawn_count"], len(scenario["spawns"]))
        self.assertEqual(metadata["native_spawn_counts_by_owner"].get(1, 0), 0)
        self.assertEqual(metadata["native_spawn_counts_by_owner"].get(2, 0), 0)
        self.assertEqual(
            sorted(
                (marker["owner_player_id"], marker["x"], marker["y"])
                for marker in metadata["placement_markers"]
            ),
            [(1, 85.0, 94.0), (2, 76.0, 103.0)],
        )

        with tempfile.TemporaryDirectory() as directory:
            replay_path = Path(directory) / "dead-of-night-map-replay.jsonl"
            html_path = Path(directory) / "full-map-player.html"
            result = run_ally_scenario(
                scenario,
                AllyPolicy(
                    player_id=2,
                    leader_entity_id=0,
                    leader_player_id=1,
                    base_region=(85.0, 94.0, 15.0),
                    command_interval=1,
                ),
                ally_player_id=2,
                leader_player_id=1,
                max_loops=8,
                latency_loops=0,
                require_cooperative_roster=True,
                player_commands=[
                    {"loop": 0, "text": "!ally follow", "command_id": "map-follow"},
                    {"loop": 2, "text": "!ally attack", "command_id": "map-attack"},
                    {"loop": 4, "text": "!ally defend", "command_id": "map-defend"},
                    {"loop": 6, "text": "!ally status", "command_id": "map-status"},
                ],
                replay_log_path=replay_path,
            )
            records = load_replay(replay_path)
            header = records[0]
            frames = [record for record in records if record.get("record_type") == "frame"]
            actions = [record for record in records if record.get("record_type") == "action"]
            first = frames[0]
            first_entities = sorted(
                (entity for entities in first["entities_by_player"].values() for entity in entities),
                key=lambda entity: entity["id"],
            )
            actual = [
                (
                    entity["t"],
                    entity["p"],
                    round(entity.get("source_x", entity["x"]), 4),
                    round(entity.get("source_y", entity["y"]), 4),
                    entity.get("source_object_id"),
                    entity.get("source_unit_type_id"),
                    entity.get("resource_amount"),
                    entity.get("resource_remaining", 0),
                )
                for entity in first_entities
            ]
            expected = [
                (
                    spawn["unit_type_id"],
                    spawn["owner_player_id"],
                    round(spawn["x"], 4),
                    round(spawn["y"], 4),
                    spawn.get("source_object_id"),
                    spawn.get("source_unit_type_id"),
                    spawn.get("resource_amount"),
                    spawn.get("resource_amount") or 0,
                )
                for spawn in scenario["spawns"]
            ]

            self.assertTrue(result.roster_ready, result.roster_issues)
            self.assertEqual(header["map_metadata"]["source_kind"], "map_extractor")
            self.assertEqual(header["map_metadata"]["map_hash"], metadata["map_hash"])
            self.assertEqual(header["p1_native_spawn_count"], 0)
            self.assertEqual(header["p2_native_spawn_count"], 0)
            self.assertEqual(len(first_entities), 1308)
            self.assertEqual(actual, expected)
            self.assertNotIn(1, {entity["p"] for entity in first_entities})
            self.assertNotIn(2, {entity["p"] for entity in first_entities})
            self.assertEqual(
                {action["owner"] for action in actions if action["kind"] == "ally_action"},
                set(),
            )
            self.assertEqual(
                sum(1 for action in actions if action["kind"] == "player_command"),
                4,
            )
            self.assertTrue(all(action["accepted"] for action in actions if action["kind"] == "player_command"))

            render_player_html(records, replay_path, html_path)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("map_extractor", html)
            self.assertIn("原生对象/实体: 1319 / 1308", html)
            self.assertIn("原生 P2 单位: 0", html)


if __name__ == "__main__":
    unittest.main()
