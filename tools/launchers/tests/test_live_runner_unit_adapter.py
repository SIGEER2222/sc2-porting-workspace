import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

from vibe import run_dead_of_night_live as runner
from vibe.defend_policy import DefendAction
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


def test_live_ally_command_is_a_p1_team_chat_message():
    action = runner.build_ally_chat_action("!ally defend stage25-test")

    assert action.HasField("action_chat")
    assert action.action_chat.channel == runner.sc_pb.ActionChat.Team
    assert action.action_chat.message == "!ally defend stage25-test"
