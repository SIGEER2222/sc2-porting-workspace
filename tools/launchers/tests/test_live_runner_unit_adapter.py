import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

from vibe import run_dead_of_night_live as runner
from vibe.defend_policy import DefendAction
from vibe.replay_player import load_replay, render_player_html
from s2clientprotocol import raw_pb2


def _unit(unit_type: int, *, owner: int = 1, alliance: int = 1, tag: int = 1):
    unit = raw_pb2.Unit(
        unit_type=unit_type,
        owner=owner,
        alliance=alliance,
        tag=tag,
        health=100,
        health_max=100,
    )
    unit.pos.x = 10.0
    unit.pos.y = 20.0
    return unit


def test_live_unit_adapter_maps_empire_units_and_filters_hero_placement():
    worker = runner._unit_brief_from_sc2(_unit(4382, tag=11), player_id=1)
    town_hall = runner._unit_brief_from_sc2(_unit(4390, tag=12), player_id=1)
    hero_placement = runner._unit_brief_from_sc2(_unit(4051, tag=13), player_id=1)

    assert worker["unit_type_id"] == "SCV"
    assert worker["unit_type_int"] == 4382
    assert town_hall["unit_type_id"] == "CommandCenter"
    assert town_hall["unit_type_int"] == 4390
    assert hero_placement is None


def test_live_unit_adapter_preserves_construction_and_order_target_state():
    barracks = _unit(100, tag=21)
    barracks.build_progress = 0.5
    order = barracks.orders.add(ability_id=1, progress=0.25, target_unit_tag=77)

    brief = runner._unit_brief_from_sc2(barracks, player_id=1)

    assert brief["build_progress"] == 0.5
    assert brief["orders"][0]["target_unit_tag"] == 77
    assert brief["orders"][0]["progress"] == 0.25


def test_live_action_adapter_uses_empire_gather_and_train_abilities():
    gather = runner.build_action(
        DefendAction(entity_id=11, kind="gather", target_entity_id=99),
        player_id=1,
        source_unit_type_int=4382,
    )
    train_scv = runner.build_action(
        DefendAction(entity_id=12, kind="train", unit_type_id="SCV"),
        player_id=1,
        source_unit_type_int=4390,
    )

    assert gather is not None
    assert gather.action_raw.unit_command.ability_id == 1
    assert gather.action_raw.unit_command.target_unit_tag == 99
    assert train_scv is not None
    assert train_scv.action_raw.unit_command.ability_id == 17443

    build_barracks = runner.build_action(
        DefendAction(
            entity_id=11,
            kind="build",
            unit_type_id="Barracks",
            target_x=15.0,
            target_y=20.0,
        ),
        player_id=2,
        source_unit_type_int=4382,
    )
    assert build_barracks is not None
    assert build_barracks.action_raw.unit_command.ability_id == 321
    assert build_barracks.action_raw.unit_command.target_world_space_pos.x == 15.0

    build_refinery = runner.build_action(
        DefendAction(
            entity_id=11,
            kind="build",
            unit_type_id="Refinery",
            target_entity_id=77,
            target_x=15.0,
            target_y=20.0,
        ),
        player_id=2,
        source_unit_type_int=4382,
    )
    assert build_refinery is not None
    assert build_refinery.action_raw.unit_command.target_unit_tag == 77


def test_live_ally_command_is_a_p1_team_chat_message():
    action = runner.build_ally_chat_action("!ally defend stage25-test")

    assert action.HasField("action_chat")
    assert action.action_chat.channel == runner.sc_pb.ActionChat.Team
    assert action.action_chat.message == "!ally defend stage25-test"


def test_live_roster_requires_p1_and_p2_participants():
    assert runner._has_p1_p2_participant_roster({
        "1": {"type": 1},
        "2": {"type": 1},
    })
    assert not runner._has_p1_p2_participant_roster({
        "1": {"type": 1},
        "2": {"type": 2},
    })


def test_live_observation_keeps_p1_as_p2_visible_ally():
    response = runner.sc_pb.Response()
    observation = response.observation.observation
    observation.game_loop = 10
    observation.player_common.food_cap = 15
    observation.player_common.food_used = 2
    own = observation.raw_data.units.add(
        unit_type=4382, owner=2, alliance=1, tag=11, health=45, health_max=45
    )
    own.pos.x = 10.0
    own.pos.y = 20.0
    ally = observation.raw_data.units.add(
        unit_type=4382, owner=1, alliance=2, tag=12, health=45, health_max=45
    )
    ally.pos.x = 11.0
    ally.pos.y = 20.0
    enemy = observation.raw_data.units.add(
        unit_type=4382, owner=3, alliance=4, tag=13, health=45, health_max=45
    )
    enemy.pos.x = 30.0
    enemy.pos.y = 20.0

    live = runner.build_observation(response, player_id=2)

    assert [unit["owner"] for unit in live.own_units] == [2]
    assert [unit["owner"] for unit in live.visible_allies] == [1]
    assert [unit["owner"] for unit in live.visible_enemies] == [3]
    assert live.visible_allies[0]["alliance"] == 2


def test_live_trace_indexes_owned_refinery_as_gas_target():
    observation = runner.LiveObservation(
        loop=1,
        player_id=2,
        own_units=[
            {"entity_id": 11, "owner": 2, "unit_type_id": "SCV"},
            {"entity_id": 12, "owner": 2, "unit_type_id": "Refinery"},
        ],
        visible_enemies=[],
        resources={},
        mission={},
        mineral_fields=[
            {"entity_id": 99, "owner": 0, "unit_type_id": "MineralField"},
        ],
    )

    targets = runner._target_state_by_tag(observation)

    assert targets[12]["unit_type_id"] == "Refinery"
    assert targets[12]["owner"] == 2
    assert targets[99]["unit_type_id"] == "MineralField"


def test_live_replay_frame_exports_current_entities_for_html_playback(tmp_path):
    observation = runner.LiveObservation(
        loop=100,
        player_id=2,
        own_units=[{
            "entity_id": 201,
            "owner": 2,
            "unit_type_id": "Marine",
            "x": 76.0,
            "y": 103.0,
            "health": 46080,
        }],
        visible_allies=[{
            "entity_id": 101,
            "owner": 1,
            "unit_type_id": "CommandCenter",
            "x": 85.0,
            "y": 94.0,
            "health": 1433600,
        }],
        visible_enemies=[{
            "entity_id": 501,
            "owner": 5,
            "unit_type_id": "InfestedCivilian",
            "x": 120.0,
            "y": 120.0,
            "health": 25600,
        }],
        resources={"minerals": 50, "vespene": 0, "supply_used": 1, "supply_cap": 15},
        mission={"win_condition": "live_sc2"},
        mineral_fields=[{
            "entity_id": 901,
            "owner": 0,
            "unit_type_id": "MineralField",
            "x": 70.0,
            "y": 110.0,
            "health": 1536000,
        }],
    )
    stream = io.StringIO()
    runner._write_replay_frame(stream, observation.loop, observation, 3, [])
    frame = json.loads(stream.getvalue())

    assert frame["record_type"] == "frame"
    assert frame["p1_alive"] == 1
    assert frame["p2_alive"] == 1
    assert frame["enemy_alive"] == 1
    assert {"0", "1", "2", "5"} <= set(frame["entities_by_player"])
    assert frame["entities_by_player"]["2"][0]["x"] == 76.0
    assert frame["entities_by_player"]["2"][0]["alive"] is True

    replay = tmp_path / "live-replay.jsonl"
    replay.write_text(
        json.dumps({
            "record_type": "header",
            "map_metadata": runner.LIVE_MAP_METADATA,
            "owner_roles": {
                "1": {"relation": "leader", "name": "P1 玩家"},
                "2": {"relation": "ally", "name": "P2 AI 盟友"},
                "5": {"relation": "enemy", "name": "P5 敌军"},
            },
        }, ensure_ascii=False)
        + "\n"
        + stream.getvalue(),
        encoding="utf-8",
    )
    html = tmp_path / "full-map-player.html"
    render_player_html(load_replay(replay), replay, html)
    html_text = html.read_text(encoding="utf-8")
    assert "P2 AI 盟友" in html_text
    assert "entities_by_player" in html_text
