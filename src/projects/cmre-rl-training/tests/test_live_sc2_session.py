"""Focused tests for the protocol-independent live SC2 bridge."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Mapping

from cmre_rl_training.action_space import ACTION_NAMES
from cmre_rl_training.action_grounding import ActionGrounder
from cmre_rl_training.env import CmreRLEnv
from cmre_rl_training.live_sc2_session import (
    LiveRawSc2Session,
    LiveSc2Error,
    RawActionError,
    build_raw_action,
    build_raw_action_spec,
    parse_observation_response,
    resolve_ability_and_target,
    unit_type_name,
    wrap_raw_action,
)
from cmre_rl_training.map_aware import MapAwareEnv, MapAwareP2AllyAC
from cmre_rl_training.map_profiles import MapProfileRegistry
from cmre_rl_training.raw_sc2_backend import RawSc2Backend
from cmre_rl_training.rollout import collect_rollout


OWN_UNITS = [
    {"entity_id": 10, "unit_type_id": "CommandCenter", "x": 85, "y": 94},
    {"entity_id": 11, "unit_type_id": "SCV", "x": 86, "y": 93},
    {"entity_id": 12, "unit_type_id": "Marine", "x": 87, "y": 92},
    {"entity_id": 13, "unit_type_id": "Medivac", "x": 88, "y": 91},
]
OBSERVATION = {
    "own_units": OWN_UNITS,
    "visible_enemies": [{"entity_id": 20, "unit_type_id": "Zergling", "x": 70, "y": 80}],
    "mineral_fields": [{"entity_id": 30, "unit_type_id": "MineralField", "x": 80, "y": 90}],
}


class _Point:
    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0

    def CopyFrom(self, value: object) -> None:
        self.x = float(getattr(value, "x"))
        self.y = float(getattr(value, "y"))


class _Command:
    def __init__(self, *, ability_id: int, unit_tags: list[int], queue_command: bool) -> None:
        self.ability_id = ability_id
        self.unit_tags = unit_tags
        self.queue_command = queue_command
        self.target_world_space_pos = _Point()
        self.target_unit_tag = 0


class _RawAction:
    def __init__(self, *, unit_command: _Command) -> None:
        self.unit_command = unit_command


class _RawPb:
    ActionRawUnitCommand = _Command
    ActionRaw = _RawAction


class _ScAction:
    def __init__(self, *, action_raw: _RawAction) -> None:
        self.action_raw = action_raw


class _ScPb:
    Action = _ScAction


class _CommonPb:
    Point2D = SimpleNamespace


class _FakeRequest:
    def __init__(self, **fields: object) -> None:
        self.kind = next(iter(fields))
        for name, value in fields.items():
            setattr(self, name, value)

    def WhichOneof(self, _name: str) -> str:
        return self.kind


class _FakeScPb:
    Request = _FakeRequest
    RequestJoinGame = SimpleNamespace
    InterfaceOptions = SimpleNamespace


class _RecordingSc2Client:
    def __init__(self, *, failures_before_success: int = 0) -> None:
        self.connected = False
        self.failures_before_success = int(failures_before_success)
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def connect(self) -> None:
        self.connected = True

    def send(self, request: _FakeRequest, **kwargs: Any) -> Any:
        self.requests.append((request.kind, kwargs))
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise LiveSc2Error("JoinGame_failed:[map_loading]")
        return SimpleNamespace(
            error=[],
            join_game=SimpleNamespace(player_id=1),
        )

    def close(self) -> None:
        self.connected = False


class _TerminalObservationResponse:
    def __init__(self, result: int) -> None:
        self.observation = SimpleNamespace(
            observation=SimpleNamespace(
                game_loop=32,
                raw_data=SimpleNamespace(units=[]),
                player_common=SimpleNamespace(
                    minerals=100,
                    vespene=0,
                    food_used=4,
                    food_cap=11,
                ),
            ),
            player_result=[SimpleNamespace(player_id=1, result=result)],
        )

    def HasField(self, name: str) -> bool:
        return name == "observation"


class _OfflineRawSession:
    def __init__(self) -> None:
        self.loop = 0
        self.dispatches: list[str] = []
        self.left = False

    def reset(self, map_name: str, player_id: int) -> Mapping[str, Any]:
        self.loop = 0
        return self._observation(map_name, player_id)

    def observe(self) -> Mapping[str, Any]:
        return self._observation("dead-of-night", 1)

    def dispatch(self, action_id: str, args: Mapping[str, Any]) -> Mapping[str, Any]:
        self.dispatches.append(action_id)
        return {"success": True, "result": 1}

    def step(self, step_mul: int) -> Mapping[str, Any]:
        self.loop += int(step_mul)
        return self._observation("dead-of-night", 1)

    def leave(self) -> None:
        self.left = True

    def _observation(self, map_name: str, player_id: int) -> dict[str, Any]:
        return {
            "loop": self.loop,
            "map_name": map_name,
            "player_id": player_id,
            "own_units": [
                {"entity_id": 1, "unit_type_id": "CommandCenter", "x": 85, "y": 94},
                {"entity_id": 2, "unit_type_id": "SCV", "x": 86, "y": 93},
                {"entity_id": 3, "unit_type_id": "Marine", "x": 87, "y": 92},
            ],
            "visible_enemies": [{"entity_id": 9, "unit_type_id": "Zergling", "x": 70, "y": 80}],
            "resources": {"minerals": 100, "supply_used": 4, "supply_cap": 11},
            "mission": {"terminated": False, "progress": self.loop / 100.0},
            "mineral_fields": [{"entity_id": 20, "unit_type_id": "MineralField", "x": 80, "y": 90}],
        }


class LiveActionSpecTests(unittest.TestCase):
    def test_direct_map_attach_skips_create_game(self) -> None:
        client = _RecordingSc2Client()
        session = LiveRawSc2Session(
            __file__,
            port=6003,
            join_existing=True,
            client=client,
        )
        session._sc_pb = _FakeScPb
        session._load_protocol = lambda: None
        session.observe = lambda: {"loop": 0, "player_id": 1}

        observation = session.reset("dead-of-night", 1)

        self.assertEqual(observation["player_id"], 1)
        self.assertTrue(client.connected)
        self.assertEqual([kind for kind, _ in client.requests], ["join_game"])
        self.assertTrue(client.requests[0][1]["retry_on_disconnect"])
        self.assertFalse(session.runtime_stats["create_game"])
        self.assertTrue(session.runtime_stats["join_game"])

    def test_direct_map_join_retries_transient_loading_error(self) -> None:
        client = _RecordingSc2Client(failures_before_success=1)
        session = LiveRawSc2Session(
            __file__,
            port=6003,
            join_existing=True,
            client=client,
        )
        session._sc_pb = _FakeScPb
        session._load_protocol = lambda: None
        session.observe = lambda: {"loop": 0, "player_id": 1}

        session.reset("dead-of-night", 1)

        self.assertEqual([kind for kind, _ in client.requests], ["join_game", "join_game"])
        self.assertEqual(session.runtime_stats["join_attempts"], 2)
        self.assertTrue(session.runtime_stats["join_game"])

    def test_player_result_becomes_terminal_mission_state(self) -> None:
        observation = parse_observation_response(
            _TerminalObservationResponse(1),
            player_id=1,
            map_name="dead-of-night",
            progress_loop_limit=100,
        )
        self.assertTrue(observation["mission"]["terminated"])
        self.assertEqual(observation["mission"]["end_reason"], "player_result_victory")
        self.assertEqual(observation["mission"]["win_condition"], "player_result")
        self.assertEqual(observation["player_result"][0]["result_name"], "victory")

    def test_catalog_ids_are_normalized_for_policy_contract(self) -> None:
        self.assertEqual(unit_type_name(45), "SCV")
        self.assertEqual(unit_type_name(48), "Marine")
        self.assertEqual(unit_type_name(54), "Medivac")
        self.assertEqual(unit_type_name(21), "Barracks")
        self.assertEqual(unit_type_name(999999), "999999")
        self.assertEqual(unit_type_name("Marine"), "Marine")

    def test_all_policy_actions_have_a_transport_resolution(self) -> None:
        action_args = {
            "move_units": {"target_x": 70, "target_y": 80},
            "patrol_units": {"target_x": 70, "target_y": 80},
            "attack_move_units": {"target_x": 70, "target_y": 80},
            "attack_units": {"target_entity_id": 20},
            "gather_resources": {"target_entity_id": 30},
            "repair_units": {"target_entity_id": 11},
            "cast_unit_ability": {"target_entity_id": 11},
            "cast_point_ability": {"target_x": 70, "target_y": 80},
            "rally_producer": {"target_x": 70, "target_y": 80},
        }
        for action in ACTION_NAMES:
            with self.subTest(action=action):
                spec = build_raw_action_spec(
                    action,
                    action_args.get(action, {}),
                    OWN_UNITS,
                    observation=OBSERVATION,
                )
                self.assertGreater(spec.ability_id, 0)
                self.assertIn(spec.target_type, {"none", "point", "unit"})
                self.assertGreater(spec.unit_tag, 0)

    def test_canonical_action_grounder_args_select_real_tags(self) -> None:
        spec = build_raw_action_spec(
            "attack_units",
            {"entity_ids": [12], "target_entity_id": 20},
            OWN_UNITS,
            observation=OBSERVATION,
        )
        self.assertEqual(spec.unit_tag, 12)
        self.assertEqual(spec.target_unit_tag, 20)
        self.assertEqual(spec.ability_id, 3674)

    def test_raw_action_builder_preserves_point_and_unit_targets(self) -> None:
        point_spec = build_raw_action_spec(
            "move_units",
            {"entity_ids": [12], "target_x": 71.5, "target_y": 81.5},
            OWN_UNITS,
            observation=OBSERVATION,
        )
        point_action = build_raw_action(point_spec, _RawPb, _CommonPb)
        self.assertEqual(point_action.unit_command.unit_tags, [12])
        self.assertEqual(point_action.unit_command.target_world_space_pos.x, 71.5)
        self.assertEqual(point_action.unit_command.target_world_space_pos.y, 81.5)

        unit_spec = build_raw_action_spec(
            "attack_units",
            {"entity_ids": [12], "target_entity_id": 20},
            OWN_UNITS,
            observation=OBSERVATION,
        )
        unit_action = build_raw_action(unit_spec, _RawPb, _CommonPb)
        self.assertEqual(unit_action.unit_command.target_unit_tag, 20)

    def test_raw_action_is_wrapped_in_sc2api_action_envelope(self) -> None:
        raw_action = build_raw_action(
            build_raw_action_spec(
                "move_units",
                {"entity_ids": [12], "target_x": 71.5, "target_y": 81.5},
                OWN_UNITS,
                observation=OBSERVATION,
            ),
            _RawPb,
            _CommonPb,
        )
        envelope = wrap_raw_action(raw_action, _ScPb)
        self.assertIs(envelope.action_raw, raw_action)

    def test_missing_target_is_truthful(self) -> None:
        with self.assertRaises(RawActionError):
            build_raw_action_spec("attack_units", {}, OWN_UNITS, observation={"visible_enemies": []})

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaises(RawActionError):
            resolve_ability_and_target("not_an_action", {})


class OfflineLiveBridgeTests(unittest.TestCase):
    def test_raw_backend_to_map_aware_rollout_is_finite(self) -> None:
        session = _OfflineRawSession()
        profile = MapProfileRegistry().resolve("dead-of-night")
        backend = RawSc2Backend(session, map_name="dead-of-night", step_mul=8)
        base_env = CmreRLEnv(backend, normalize_reward=False)
        env = MapAwareEnv(base_env, profile)
        policy = MapAwareP2AllyAC(hidden_dim=16, context_dim=profile.context_dim)
        buffer = collect_rollout(
            env,
            policy,
            n_steps=2,
            deterministic=True,
            action_builder=ActionGrounder(profile).ground,
        )
        self.assertEqual(len(buffer), 2)
        self.assertEqual(env.observation_dim, 57)
        self.assertGreaterEqual(len(session.dispatches), 1)
        self.assertTrue(session.loop > 0)
        self.assertTrue(session.dispatches)
        backend.close()
        self.assertTrue(session.left)


if __name__ == "__main__":
    unittest.main()
