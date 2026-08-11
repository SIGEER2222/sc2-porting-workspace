#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_route_b_episode 的目标/执行者选择回归测试。

为什么值得单测：ep-alliance-02 真机跑出 action_success_rate=0.5，第一反应是
"Bank RPC 通道不稳"，实际是 `choose_action` 取 `enemies[0]` 打到了 gen 图自带的
非战斗哑元（`ActionResult.NotSupported`）。这类"看着像基础设施故障、其实是选择
逻辑"的 bug 只能在真机上暴露，代价极高 —— 必须用离线断言钉死，别再靠真机复现。

驱动脚本在 tools/ 下且不是包，用 importlib 按路径加载。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "tools" / "run_route_b_episode.py"


def _load_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("_route_b_episode", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rb():
    return _load_module()


def _unit(entity_id, owner, unit_type, x, y):
    return {"entity_id": entity_id, "owner": owner,
            "unit_type_id": unit_type, "x": x, "y": y}


# gen 图实测形态（ep-alliance-02 的 post_spawn digest）：
#   己方 3 Marine + 1 个 type "4051" 哑元；敌方 2 Marine + 1 个 "4051" 哑元。
def _observation(enemy_first: bool = True):
    dummy = _unit(4356833281, 2, "4051", 76.0, 103.0)
    m1 = _unit(4434690049, 2, "Marine", 16.0, 9.5)
    m2 = _unit(4434952193, 2, "Marine", 16.0, 10.3)
    enemies = [dummy, m1, m2] if enemy_first else [m2, m1, dummy]
    return {
        "own_units": [
            _unit(4434165761, 1, "Marine", 9.5, 10.0),
            _unit(4433641473, 1, "Marine", 9.9, 9.3),
            _unit(4331143169, 1, "4051", 85.0, 94.0),
        ],
        "visible_enemies": enemies,
        "visible_allies": [],
    }


class TestCombatTargets:
    def test_numeric_type_dummy_is_filtered_out(self, rb):
        """type 纯数字 = SC2 没解析出名字 = 地图家具，不能当攻击目标。"""
        targets = rb.combat_targets(_observation(), enemy_player=2)
        assert [t["entity_id"] for t in targets] == [4434690049, 4434952193]

    def test_enemy_units_still_returns_everything(self, rb):
        """过滤只发生在 combat_targets，enemy_units 保持"敌方真值"语义。

        判据 ⑤（enemy_units_observed）依赖它数敌人，不能被战斗过滤污染。
        """
        assert len(rb.enemy_units(_observation(), enemy_player=2)) == 3

    def test_falls_back_when_everything_filtered(self, rb):
        """全是哑元时回退原列表——宁可打不动，也不能静默变成"没有敌人"。

        静默清空会让 choose_action 退化成 move_units，判据 ⑦ 反而变绿，
        把"敌人不可攻击"这条真信息藏起来。
        """
        obs = {"own_units": [], "visible_enemies": [_unit(1, 2, "4051", 1.0, 1.0)]}
        assert len(rb.combat_targets(obs, enemy_player=2)) == 1


class TestChooseAction:
    def test_never_targets_the_dummy(self, rb):
        for step in range(6):
            action, args = rb.choose_action(_observation(), step, enemy_player=2)
            assert action == "attack_units"
            assert args["target_entity_id"] != 4356833281

    def test_target_is_independent_of_observation_order(self, rb):
        """同一战场、不同观测顺序，必须选出同一个目标。

        这是 0.5 成功率的直接根因：raw obs 的单位顺序不保证稳定，
        按顺序取目标等于让"打谁"随帧抖动。
        """
        for step in range(4):
            _, a = rb.choose_action(_observation(enemy_first=True), step, 2)
            _, b = rb.choose_action(_observation(enemy_first=False), step, 2)
            assert a["target_entity_id"] == b["target_entity_id"]

    def test_picks_nearest_enemy_to_the_acting_unit(self, rb):
        obs = {
            "own_units": [_unit(100, 1, "Marine", 0.0, 0.0)],
            "visible_enemies": [
                _unit(200, 2, "Marine", 50.0, 50.0),
                _unit(201, 2, "Marine", 1.0, 1.0),
            ],
        }
        _, args = rb.choose_action(obs, 0, enemy_player=2)
        assert args["target_entity_id"] == 201

    def test_actor_is_a_combat_unit_not_the_dummy(self, rb):
        for step in range(6):
            _, args = rb.choose_action(_observation(), step, enemy_player=2)
            assert args["entity_ids"] == [4434165761] or \
                   args["entity_ids"] == [4433641473]

    def test_no_enemies_falls_back_to_move(self, rb):
        obs = {"own_units": [_unit(100, 1, "Marine", 0.0, 0.0)],
               "visible_enemies": []}
        action, args = rb.choose_action(obs, 0, enemy_player=2)
        assert action == "move_units"
        assert args["entity_ids"] == [100]
