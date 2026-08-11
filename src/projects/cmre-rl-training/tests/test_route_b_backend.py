"""route B 后端离线单测：纯函数 + 注入式 fake 后端（不起 SC2）。

覆盖 Module 4「接 PPO + 胜负终端」的新逻辑：
  · ``detect_terminal`` 胜负判定（含跳过建交的反向对照不假胜）。
  · ``ground_action`` 动作接地（攻击/移动/兜底）。
  · ``RouteBBackend`` 在注入 fake session/scenario 下 reset/step 闭环、episode 以
    victory 终止。

不依赖 SC2 可执行文件或 torch；纯 python 即可跑。
"""
from __future__ import annotations

import unittest
from typing import Any

from cmre_rl_training.route_b_backend import (
    RouteBBackend,
    combat_actors,
    combat_targets,
    count_enemy_combat,
    count_own_combat,
    detect_terminal,
    enemy_present,
    ground_action,
)


def _marine(tag: int, owner: int, x: float = 10.0, y: float = 10.0) -> dict[str, Any]:
    return {
        "entity_id": tag, "unit_type_id": "Marine", "owner": owner,
        "x": x, "y": y, "health": 45,
    }


def _dummy(tag: int, owner: int) -> dict[str, Any]:
    # 纯数字 unit_type_id → 哑元，不计入战斗单位。
    return {"entity_id": tag, "unit_type_id": "4051", "owner": owner, "x": 5, "y": 5}


def _obs(own: list[dict], enemies: list[dict], allies: list[dict] | None = None) -> dict:
    return {
        "loop": 1, "own_units": own,
        "visible_enemies": enemies, "visible_allies": allies or [],
        "mission": {"end_reason": "", "terminated": False},
    }


class TerminalDetectionTests(unittest.TestCase):
    def test_victory_when_enemy_wiped(self):
        obs = _obs([_marine(1, 1), _marine(2, 1)], enemies=[])
        term, reason = detect_terminal(obs, 2)
        self.assertTrue(term)
        self.assertEqual(reason, "victory")

    def test_defeat_when_own_wiped(self):
        obs = _obs([], enemies=[_marine(100, 2)])
        term, reason = detect_terminal(obs, 2)
        self.assertTrue(term)
        self.assertEqual(reason, "defeat")

    def test_active_while_both_alive(self):
        obs = _obs([_marine(1, 1)], enemies=[_marine(100, 2)])
        term, reason = detect_terminal(obs, 2)
        self.assertFalse(term)
        self.assertEqual(reason, "")

    def test_dummy_units_excluded(self):
        # 双方各带一个哑元，真战斗单位还在 → 不终止。
        obs = _obs([_marine(1, 1), _dummy(9, 1)], enemies=[_dummy(90, 2), _marine(100, 2)])
        self.assertEqual(count_own_combat(obs), 1)
        self.assertEqual(count_enemy_combat(obs, 2), 1)
        term, _ = detect_terminal(obs, 2)
        self.assertFalse(term)

    def test_neutral_owner_not_enemy(self):
        # owner 9 中立地形物不得算敌方。
        obs = _obs([_marine(1, 1)], enemies=[_marine(100, 9)])
        self.assertEqual(count_enemy_combat(obs, 2), 0)

    def test_no_alliance_negative_control_not_false_victory(self):
        # 跳过建交：敌方单位落在 visible_allies 且 owner==2。必须仍被算作存在，
        # 否则反向对照会误判 victory。
        obs = _obs([_marine(1, 1)], enemies=[], allies=[_marine(100, 2)])
        self.assertEqual(count_enemy_combat(obs, 2), 1)
        self.assertGreater(len(enemy_present(obs, 2)), 0)
        term, _ = detect_terminal(obs, 2)
        self.assertFalse(term, "反向对照：跳过建交不应假胜")


class GroundingTests(unittest.TestCase):
    def _scene(self):
        own = [_marine(1, 1, 10, 10), _marine(2, 1, 11, 10)]
        enemies = [_marine(100, 2, 18, 10), _marine(101, 2, 19, 10)]
        return _obs(own, enemies), own, enemies

    def test_attack_units_grounds_nearest_target(self):
        obs, own, enemies = self._scene()
        action_id, args = ground_action("attack_units", obs, 0, 2)
        self.assertEqual(action_id, "attack_units")
        self.assertIn("entity_ids", args)
        self.assertIn("target_entity_id", args)
        # 目标应在敌方集合里。
        self.assertIn(args["target_entity_id"], {100, 101})

    def test_attack_move_grounds_point(self):
        obs, _, _ = self._scene()
        action_id, args = ground_action("attack_move_units", obs, 0, 2)
        self.assertEqual(action_id, "attack_move_units")
        self.assertIn("target_x", args)

    def test_move_grounds_toward_enemy(self):
        obs, _, _ = self._scene()
        action_id, args = ground_action("move_units", obs, 0, 2)
        self.assertEqual(action_id, "move_units")
        # 朝敌人质心（~18,10）而非默认点。
        self.assertAlmostEqual(args["target_x"], 18.5, delta=0.6)

    def test_unexecutable_action_falls_back_to_combat(self):
        # produce_unit / build_structure 在 gen 图无意义 → 安全退化成推进/移动。
        obs, _, _ = self._scene()
        for bad in ("produce_unit", "build_structure", "research_upgrade"):
            action_id, args = ground_action(bad, obs, 0, 2)
            self.assertIn(action_id, ("attack_move_units", "move_units"))
            self.assertIn("target_x", args)

    def test_move_when_no_enemy(self):
        obs = _obs([_marine(1, 1)], enemies=[])
        action_id, args = ground_action("move_units", obs, 0, 2)
        self.assertEqual(action_id, "move_units")
        self.assertEqual((args["target_x"], args["target_y"]), (18.0, 10.0))


class FakeSession:
    """注入式假 session：按预录帧推进，不连 SC2。"""

    def __init__(self, frames: list[dict], trace: list[str] | None = None) -> None:
        self.frames = frames
        self.index = 0
        self.actions: list[tuple[str, dict]] = []
        self.left = False
        self.leave_count = 0
        self.reset_count = 0
        self.trace = trace if trace is not None else []

    def reset(self, map_name: str, player: int) -> dict:
        self.index = 0
        self.reset_count += 1
        self.trace.append("session.reset")
        return dict(self.frames[0])

    def step(self, step_mul: int) -> None:
        if self.index < len(self.frames) - 1:
            self.index += 1

    def observe(self) -> dict:
        return dict(self.frames[self.index])

    def dispatch(self, action_id: str, args: dict) -> dict:
        self.actions.append((action_id, dict(args)))
        return {"success": True, "translated": True, "action_id": action_id,
                "results": [1]}

    def leave(self) -> None:
        self.left = True
        self.leave_count += 1
        self.trace.append("session.leave")


class FakeScenario:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.built = False
        self.archived = False
        self.archive_count = 0
        self.pumped = False
        self.trace = trace if trace is not None else []

    def archive_bank(self):
        self.archived = True
        self.archive_count += 1
        self.trace.append("scenario.archive_bank")
        return None

    def set_pump(self, pump):
        self.pumped = True

    def wait_for_kernel(self, timeout=60.0):
        return {"kernel_initialized": 1, "register_entrypoints_done": 1}

    def build(self, spec, timeout=None, set_alliances=True):
        self.built = True
        return {"ok": True, "scenario": spec.name}

    @property
    def stats(self):
        return {}


class RouteBBackendWiringTests(unittest.TestCase):
    def _frames_normal(self) -> list[dict]:
        # index0=pre, index1=4v2, index2=4v1, index3=4v0(victory)
        f1 = _obs([_marine(1, 1), _marine(2, 1), _marine(3, 1), _marine(4, 1)],
                  enemies=[_marine(100, 2, 18, 10), _marine(101, 2, 19, 10)])
        f2 = _obs([_marine(1, 1), _marine(2, 1), _marine(3, 1), _marine(4, 1)],
                  enemies=[_marine(100, 2, 18, 10)])
        f3 = _obs([_marine(1, 1), _marine(2, 1), _marine(3, 1), _marine(4, 1)],
                  enemies=[])
        return [dict(f1), dict(f1), dict(f2), dict(f3)]

    def _frames_no_alliance(self) -> list[dict]:
        # 敌方在 visible_allies，无 combat → 永不靠计数终止。
        f = _obs([_marine(1, 1), _marine(2, 1)],
                 enemies=[], allies=[_marine(100, 2, 18, 10), _marine(101, 2, 19, 10)])
        return [dict(f), dict(f), dict(f), dict(f)]

    def test_reset_builds_and_step_reaches_victory(self):
        backend = RouteBBackend(
            own_count=4, enemy_count=2, fresh_bank=False,
            session=FakeSession(self._frames_normal()),
            scenario=FakeScenario())
        obs = backend.reset()
        self.assertTrue(backend.last_verdict["scenario_built"])
        self.assertEqual(count_own_combat(obs), 4)

        steps = 0
        last = None
        while steps < 8:
            obs, terminated, info = backend.step("attack_units", {})
            steps += 1
            last = (terminated, info)
            if terminated:
                break
        self.assertTrue(last[0], "episode 应以 victory 终止")
        self.assertEqual(last[1]["end_reason"], "victory")
        # 接地确实生成了带目标的攻击指令。
        self.assertTrue(any(a == "attack_units" for a, _ in backend._session.actions))
        backend.close()

    def test_no_alliance_negative_control_not_false_victory(self):
        backend = RouteBBackend(
            own_count=2, enemy_count=2, fresh_bank=False, no_alliances=True,
            session=FakeSession(self._frames_no_alliance()),
            scenario=FakeScenario())
        backend.reset()
        seen_victory = False
        for _ in range(6):
            _, terminated, info = backend.step("attack_move_units", {})
            if terminated and info.get("end_reason") == "victory":
                seen_victory = True
                break
        self.assertFalse(seen_victory, "反向对照（跳过建交）不应假胜")
        backend.close()


class DummyFloorRegressionTests(unittest.TestCase):
    """VIBE_BANK_014 回归：地图哑元不得在敌方计数上顶出一个"永不归零"的地板。

    真机 gen 图给每个玩家挂了 ``unit_type_id=="4051"`` 的地图家具（owner=2 那个在
    (76,103)）。首版 ``enemy_present`` 抄了动作接地的 ``return combat or enemies``
    回退，两个敌方 Marine 被打死后回退把哑元顶上来 → 敌方数恒 =1 → victory 恒不触发。
    run03 真机表征：30 步跑满、reward 有波动、PPO 正常更新，但 terminated=0/3 ——
    也就是把"缺胜负终端"这个根因原封不动搬到了真机。用真机实测形状钉死。
    """

    def test_enemy_dummy_only_counts_as_zero(self):
        obs = _obs([_marine(1, 1), _dummy(9, 1)], enemies=[_dummy(50, 2)])
        self.assertEqual(count_enemy_combat(obs), 0,
                         "只剩地图哑元时敌方战斗单位数必须为 0")
        terminated, reason = detect_terminal(obs)
        self.assertTrue(terminated)
        self.assertEqual(reason, "victory")

    def test_real_marine_plus_dummy_counts_only_marine(self):
        obs = _obs([_marine(1, 1)],
                   enemies=[_dummy(50, 2), _marine(100, 2, 18, 10)])
        self.assertEqual(count_enemy_combat(obs), 1)
        self.assertFalse(detect_terminal(obs)[0])

    def test_grounding_never_targets_dummy(self):
        obs = _obs([_marine(1, 1)], enemies=[_dummy(50, 2)])
        action_id, args = ground_action("attack_units", obs, 0)
        self.assertNotEqual(action_id, "attack_units",
                            "没有真目标时不应下 attack_units（raw API 会回 NotSupported）")
        self.assertEqual(combat_targets(obs), [])

    def test_own_dummy_only_counts_as_defeat(self):
        obs = _obs([_dummy(9, 1)], enemies=[_marine(100, 2, 18, 10)])
        self.assertEqual(count_own_combat(obs), 0)
        self.assertEqual(detect_terminal(obs), (True, "defeat"))


class BankArchiveOrderingTests(unittest.TestCase):
    """VIBE_BANK_012 回归：bank 归档必须发生在 SC2 进对局之前。

    真机血泪：首版把 ``archive_bank()`` 放在 ``session.reset()`` 之后，等于在 SC2
    持有 bank 文件句柄时把文件搬走。SC2 拿悬空句柄继续 BankLoad → 进程崩溃 → ws 掉链，
    但异常直到几十秒后 ``set_hostile`` 泵时钟才抛出（``sc2_api_not_connected``），
    离肇事点极远，纯靠日志几乎归因不到。所以把「顺序」本身固化成断言。
    """

    def _frames(self) -> list[dict]:
        f = _obs([_marine(1, 1), _marine(2, 1)],
                 enemies=[_marine(100, 2, 18, 10)])
        return [dict(f)] * 4

    def test_archive_bank_precedes_game_create(self):
        trace: list[str] = []
        backend = RouteBBackend(
            fresh_bank=True,
            session=FakeSession(self._frames(), trace=trace),
            scenario=FakeScenario(trace=trace))
        backend.reset()
        self.assertIn("scenario.archive_bank", trace)
        self.assertIn("session.reset", trace)
        self.assertLess(
            trace.index("scenario.archive_bank"), trace.index("session.reset"),
            f"archive_bank 必须在 CreateGame 之前，实际顺序={trace}")
        backend.close()

    def test_second_episode_leaves_before_archiving(self):
        trace: list[str] = []
        session = FakeSession(self._frames(), trace=trace)
        backend = RouteBBackend(
            fresh_bank=True, session=session, scenario=FakeScenario(trace=trace))
        backend.reset()
        trace.clear()
        backend.reset()  # 第二个 episode
        self.assertEqual(
            trace[:3], ["session.leave", "scenario.archive_bank", "session.reset"],
            f"第二 episode 顺序应为 leave→archive→create，实际={trace}")
        backend.close()

    def test_no_fresh_bank_skips_archive(self):
        trace: list[str] = []
        backend = RouteBBackend(
            fresh_bank=False,
            session=FakeSession(self._frames(), trace=trace),
            scenario=FakeScenario(trace=trace))
        backend.reset()
        self.assertNotIn("scenario.archive_bank", trace)
        backend.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
