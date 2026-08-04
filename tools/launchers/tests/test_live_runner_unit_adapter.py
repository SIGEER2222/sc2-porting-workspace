import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

from vibe import run_dead_of_night_live as runner
from vibe.defend_policy import DefendAction
from vibe.ml.model import P2AllyPolicyNet, save_checkpoint
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


def test_live_action_adapter_uses_runtime_empire_catalog_for_custom_commands():
    runtime_catalog = {
        ("3jianzao1", 3): 6003,
        ("3xunlian1", 0): 6004,
    }
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
        runtime_ability_catalog=runtime_catalog,
    )
    train_scv = runner.build_action(
        DefendAction(entity_id=12, kind="train", unit_type_id="SCV"),
        player_id=2,
        source_unit_type_int=4390,
        runtime_ability_catalog=runtime_catalog,
    )

    assert build_barracks is not None
    assert build_barracks.action_raw.unit_command.ability_id == 6003
    assert train_scv is not None
    assert train_scv.action_raw.unit_command.ability_id == 6004


def test_ally_chat_tactical_group_excludes_workers_and_structures():
    overlay_root = (
        ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger"
    )
    for name in ("map-glue.generic.galaxy", "map-glue.dead-of-night.galaxy"):
        source = (overlay_root / name).read_text(encoding="utf-8")
        assert "p2CombatUnits = UnitGroup(null, 2" in source
        assert (
            "(1 << c_targetFilterWorker) | (1 << c_targetFilterStructure)"
            in source
        )
        assert "UnitGroupIssueOrder(p2CombatUnits" in source
        assert "No combat units available; workers remain mining." in source


def test_shared_kernel_accepts_only_explicit_p2_model_transport():
    kernel = (
        ROOT / "tools" / "galaxy-vibe" / "kernel" / "LibVibeKernel.galaxy"
    ).read_text(encoding="utf-8")

    assert "libVibeKernel_gf_ProcessModelAllyCommand" in kernel
    assert 'pendingAllyPlayer == 2' in kernel
    assert 'pendingAllySource == "ml_policy"' in kernel
    assert 'last_issuer_player_id", 2' in kernel
    assert "p2CombatUnits = UnitGroup(null, 2" in kernel
    assert "c_targetFilterWorker) | (1 << c_targetFilterStructure)" in kernel


def test_live_ally_command_is_a_p1_team_chat_message():
    action = runner.build_ally_chat_action("!ally defend stage25-test")

    assert action.HasField("action_chat")
    assert action.action_chat.channel == runner.sc_pb.ActionChat.Team
    assert action.action_chat.message == "!ally defend stage25-test"


def test_live_api_ally_command_is_mirrored_to_p1_bank_bridge(tmp_path):
    bank = tmp_path / "GalaxyVibe.SC2Bank"
    bank.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Bank version="1"><Section name="ally" /></Bank>',
        encoding="utf-8",
    )

    ok, error = runner._queue_runtime_ally_command(
        "!ally attack stage25-bank-bridge",
        bank_path=bank,
    )

    assert ok is True
    assert error == ""
    root = runner.ET.parse(bank).getroot()
    section = next(item for item in root.findall("Section") if item.get("name") == "ally")
    values = {
        key.get("name"): key.find("Value").attrib
        for key in section.findall("Key")
    }
    assert values["pending_command"] == {"string": "!ally attack stage25-bank-bridge"}
    assert values["pending_player_id"] == {"int": "1"}
    assert values["pending_source"] == {"string": "p1_chat"}


def test_live_model_command_is_explicitly_p2_owned_and_provenanced(tmp_path):
    bank = tmp_path / "GalaxyVibe.SC2Bank"
    bank.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Bank version="1"><Section name="ally" /></Bank>',
        encoding="utf-8",
    )

    ok, error = runner._queue_runtime_ally_command(
        "!ally attack ml:22:1",
        bank_path=bank,
        issuer_player_id=runner.P2_PLAYER_ID,
        source="ml_policy",
        model_schema="cmre-ally-intent-pytorch.v2",
        model_hash="checkpoint-hash",
        decision_id="ml:22:1",
    )

    assert ok is True
    assert error == ""
    root = runner.ET.parse(bank).getroot()
    section = next(item for item in root.findall("Section") if item.get("name") == "ally")
    values = {
        key.get("name"): key.find("Value").attrib
        for key in section.findall("Key")
    }
    assert values["pending_player_id"] == {"int": "2"}
    assert values["pending_source"] == {"string": "ml_policy"}
    assert values["pending_model_schema"] == {"string": "cmre-ally-intent-pytorch.v2"}
    assert values["pending_model_hash"] == {"string": "checkpoint-hash"}
    assert values["pending_decision_id"] == {"string": "ml:22:1"}


def test_live_model_bridge_acknowledges_only_matching_galaxy_result():
    trace = [
        {
            "message": "!ally attack ml:22:1",
            "bridge_queued": True,
            "acknowledged": False,
        },
        {
            "message": "!ally defend ml:22:2",
            "bridge_queued": True,
            "acknowledged": False,
        },
    ]

    runner._ack_mode_model_decisions(
        trace,
        {"last_command": "!ally attack ml:22:1", "last_result": "attack_issued"},
        current_loop=64,
    )

    assert trace[0]["acknowledged"] is True
    assert trace[0]["ack_loop"] == 64
    assert trace[0]["ack_result"] == "attack_issued"
    assert trace[1]["acknowledged"] is False


def test_live_runner_loads_only_versioned_pytorch_intent_checkpoint(tmp_path):
    checkpoint = save_checkpoint(
        P2AllyPolicyNet(hidden_dim=24, seed=7),
        tmp_path / "ally-intent.pt",
    )

    model, summary = runner.load_p2_intent_model(checkpoint)

    assert model.config()["input_dim"] == 49
    assert summary["backend"] == "pytorch"
    assert summary["schema"] == "cmre-ally-intent-pytorch.v2"
    assert summary["feature_schema"] == "cmre-ally-observation.v2"
    assert summary["controller_player_id"] == runner.P2_PLAYER_ID
    assert summary["checkpoint_sha256"]


def test_p2_policy_observation_reorients_only_public_units():
    observation = runner.LiveObservation(
        loop=22,
        player_id=runner.P1_PLAYER_ID,
        own_units=[{"entity_id": 11, "owner": 1, "unit_type_id": "Marine", "x": 1.0, "y": 1.0}],
        visible_allies=[{"entity_id": 22, "owner": 2, "unit_type_id": "Marine", "x": 2.0, "y": 2.0}],
        visible_enemies=[{"entity_id": 33, "owner": 3, "unit_type_id": "Zergling", "x": 3.0, "y": 3.0}],
        resources={"minerals": 500, "vespene": 100},
        mission={"stage": "opening"},
    )

    p2_view = runner.build_p2_policy_observation(observation)

    assert p2_view.player_id == runner.P2_PLAYER_ID
    assert [unit["owner"] for unit in p2_view.own_units] == [2]
    assert [unit["owner"] for unit in p2_view.visible_allies] == [1]
    assert [unit["owner"] for unit in p2_view.visible_enemies] == [3]
    assert p2_view.resources["source"] == "not_visible_from_p1"


def test_live_roster_requires_p1_and_p2_participants():
    assert runner._has_p1_p2_participant_roster({
        "1": {"type": 1},
        "2": {"type": 1},
    })
    assert not runner._has_p1_p2_participant_roster({
        "1": {"type": 1},
        "2": {"type": 2},
    })


def test_live_replay_metadata_resolves_the_runtime_map_catalog_entry():
    metadata = runner._resolve_runtime_map_metadata(
        "artifacts/runtime/keha-rift.packed.SC2Map",
        "[CM] 克哈裂痕",
    )

    assert metadata["map_name"] == "克哈裂痕"
    assert metadata["runtime_game_info_map_name"] == "[CM] 克哈裂痕"
    assert metadata["runtime_source_map_resolved"] is True
    assert metadata["source_kind"] == "cmre_map_catalog"
    assert metadata["map_hash"]
    assert metadata["native_object_count"] > 0
    assert metadata["geometry"]["leader_position"] == (46.0, 41.0)


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
    assert live.resources["state_version"] == 10


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
