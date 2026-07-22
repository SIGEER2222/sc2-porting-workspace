"""Unit tests for sc2-observer.py: extract_events_from_observation and evaluate_verdict.

聚焦验证刚修复的两个 bug：
1. unit_created 必须通过前后帧 tag 对比识别，而不是"unit_snapshot 出现"（每帧都发，永真）。
2. evaluate_verdict 中的 unit_created 断言必须按 unit_type / owner / within 过滤。

用 dataclass 模拟 protobuf 观察对象，避免依赖真实 s2clientprotocol。
运行：python -m unittest test.test_sc2_observer -v  或  python test/test_sc2_observer.py
"""
import importlib.util
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# sc2-observer.py 文件名带连字符，不能用普通 import 加载，需用 importlib 按路径加载。
REPO_ROOT = Path(__file__).resolve().parents[1]
OBSERVER_PATH = REPO_ROOT / "tools" / "runtime-bridge" / "sc2-observer.py"
spec = importlib.util.spec_from_file_location("sc2_observer", OBSERVER_PATH)
sc2_observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc2_observer)


# ---------- 用 dataclass 模拟 protobuf Observation ----------


@dataclass
class FakeUnit:
    tag: int
    unit_type: int
    owner: int = 0


@dataclass
class FakePlayerCommon:
    minerals: int = 0
    vespene: int = 0
    food_used: int = 0
    food_cap: int = 0

    def HasField(self, name: str) -> bool:
        # protobuf HasField 语义：字段被显式设置时返回 True。这里用"非零"近似。
        if name == "minerals":
            return self.minerals != 0
        if name == "vespene":
            return self.vespene != 0
        return False


@dataclass
class FakeRaw:
    units: List[FakeUnit] = field(default_factory=list)


@dataclass
class FakeObservation:
    raw: FakeRaw = field(default_factory=FakeRaw)
    alerts: list = field(default_factory=list)


@dataclass
class FakeError:
    code: int
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class FakeObs:
    player_common: FakePlayerCommon = field(default_factory=FakePlayerCommon)
    observation: FakeObservation = field(default_factory=FakeObservation)
    errors: list = field(default_factory=list)
    game_status: int = 0
    _has_game_status: bool = False

    def HasField(self, name: str) -> bool:
        if name == "game_status":
            return self._has_game_status
        return False


def make_obs(
    units=None,
    minerals=0,
    gas=0,
    food_used=0,
    food_cap=0,
    errors=None,
    game_status=None,
):
    """构造一个 FakeObs，简化测试用例构造。"""
    obs = FakeObs()
    obs.player_common = FakePlayerCommon(minerals, gas, food_used, food_cap)
    obs.observation = FakeObservation(raw=FakeRaw(units=list(units or [])))
    obs.errors = list(errors or [])
    if game_status is not None:
        obs.game_status = game_status
        obs._has_game_status = True
    return obs


# ---------- extract_events_from_observation 测试 ----------


class TestExtractEventsUnitTracking(unittest.TestCase):
    """验证前后帧 tag 对比逻辑：这是修复 unit_created 永真 bug 的核心。"""

    def test_first_frame_all_units_are_created(self):
        """首帧 prev 为空，所有单位都应记为 unit_created。"""
        units = [FakeUnit(1, 188, 1), FakeUnit(2, 188, 1), FakeUnit(3, 59, 2)]
        obs = make_obs(units=units)
        prev_tags: set = set()
        prev_types: dict = {}
        events = sc2_observer.extract_events_from_observation(obs, 0, 0.0, prev_tags, prev_types)

        created = [e for e in events if e["type"] == "unit_created"]
        self.assertEqual(len(created), 3)
        # prev 状态应被更新为当前帧
        self.assertEqual(prev_tags, {1, 2, 3})
        self.assertEqual(prev_types, {1: 188, 2: 188, 3: 59})

    def test_second_frame_only_new_units_are_created(self):
        """第二帧只有新 tag 才报 unit_created，已存在的不再报。"""
        units = [FakeUnit(1, 188, 1), FakeUnit(2, 188, 1), FakeUnit(4, 73, 2)]
        obs = make_obs(units=units)
        prev_tags = {1, 2, 3}
        prev_types = {1: 188, 2: 188, 3: 59}
        events = sc2_observer.extract_events_from_observation(obs, 1, 0.1, prev_tags, prev_types)

        created = [e for e in events if e["type"] == "unit_created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["tag"], 4)
        self.assertEqual(created[0]["unit_type"], 73)
        self.assertEqual(created[0]["owner"], 2)

    def test_lost_units_are_reported(self):
        """之前有但当前没有的单位应报 unit_lost。"""
        units = [FakeUnit(1, 188, 1)]  # tag 2 和 3 消失
        obs = make_obs(units=units)
        prev_tags = {1, 2, 3}
        prev_types = {1: 188, 2: 188, 3: 59}
        events = sc2_observer.extract_events_from_observation(obs, 1, 0.1, prev_tags, prev_types)

        lost = sorted([e for e in events if e["type"] == "unit_lost"], key=lambda e: e["tag"])
        self.assertEqual(len(lost), 2)
        self.assertEqual(lost[0]["tag"], 2)
        self.assertEqual(lost[1]["tag"], 3)
        # unit_lost 应携带原 unit_type 便于追溯
        self.assertEqual(lost[1]["unit_type"], 59)

    def test_no_spurious_unit_snapshot(self):
        """确认不再有 unit_snapshot 事件类型（旧的每帧误报已移除）。"""
        units = [FakeUnit(1, 188, 1)]
        obs = make_obs(units=units)
        events = sc2_observer.extract_events_from_observation(obs, 0, 0.0, set(), {})
        snapshots = [e for e in events if e["type"] == "unit_snapshot"]
        self.assertEqual(snapshots, [], "unit_snapshot 应被移除，改为 unit_created/unit_lost")

    def test_prev_state_updates_across_frames(self):
        """连续三帧：T0 创建 a,b → T1 a 消失、c 创建 → T2 b,c 都还在、d 创建。"""
        prev_tags: set = set()
        prev_types: dict = {}

        # T0: a, b 出现
        obs0 = make_obs(units=[FakeUnit(10, 188, 1), FakeUnit(11, 73, 1)])
        e0 = sc2_observer.extract_events_from_observation(obs0, 0, 0.0, prev_tags, prev_types)
        self.assertEqual(len([e for e in e0 if e["type"] == "unit_created"]), 2)
        self.assertEqual(prev_tags, {10, 11})

        # T1: a 消失，c 出现
        obs1 = make_obs(units=[FakeUnit(11, 73, 1), FakeUnit(12, 59, 2)])
        e1 = sc2_observer.extract_events_from_observation(obs1, 1, 0.1, prev_tags, prev_types)
        created1 = [e for e in e1 if e["type"] == "unit_created"]
        lost1 = [e for e in e1 if e["type"] == "unit_lost"]
        self.assertEqual(len(created1), 1)
        self.assertEqual(created1[0]["tag"], 12)
        self.assertEqual(len(lost1), 1)
        self.assertEqual(lost1[0]["tag"], 10)
        self.assertEqual(prev_tags, {11, 12})

        # T2: d 出现，b,c 都还在
        obs2 = make_obs(units=[FakeUnit(11, 73, 1), FakeUnit(12, 59, 2), FakeUnit(13, 74, 1)])
        e2 = sc2_observer.extract_events_from_observation(obs2, 2, 0.2, prev_tags, prev_types)
        created2 = [e for e in e2 if e["type"] == "unit_created"]
        lost2 = [e for e in e2 if e["type"] == "unit_lost"]
        self.assertEqual(len(created2), 1)
        self.assertEqual(created2[0]["tag"], 13)
        self.assertEqual(lost2, [])


class TestExtractEventsOtherTypes(unittest.TestCase):
    """资源 / 游戏错误 / 游戏结束事件。"""

    def test_resource_event(self):
        obs = make_obs(minerals=100, gas=50, food_used=5, food_cap=10)
        events = sc2_observer.extract_events_from_observation(obs, 0, 0.0, set(), {})
        res = [e for e in events if e["type"] == "resource"]
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["minerals"], 100)
        self.assertEqual(res[0]["gas"], 50)
        self.assertEqual(res[0]["food_used"], 5)
        self.assertEqual(res[0]["food_cap"], 10)

    def test_no_resource_event_when_zero(self):
        """minerals=0, gas=0 时不应发 resource 事件（HasField 都返回 False）。"""
        obs = make_obs(minerals=0, gas=0)
        events = sc2_observer.extract_events_from_observation(obs, 0, 0.0, set(), {})
        res = [e for e in events if e["type"] == "resource"]
        self.assertEqual(res, [])

    def test_game_error_event(self):
        err = FakeError(code=1, message="ScriptError: invalid unit")
        obs = make_obs(errors=[err])
        events = sc2_observer.extract_events_from_observation(obs, 0, 0.0, set(), {})
        errs = [e for e in events if e["type"] == "game_error"]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["code"], 1)
        self.assertIn("ScriptError", errs[0]["message"])

    def test_game_ended_event(self):
        obs = make_obs(game_status=22)
        events = sc2_observer.extract_events_from_observation(obs, 0, 0.0, set(), {})
        ended = [e for e in events if e["type"] == "game_ended"]
        self.assertEqual(len(ended), 1)


# ---------- evaluate_verdict 测试 ----------


class TestEvaluateVerdictUnitCreated(unittest.TestCase):
    """验证 unit_created 断言按 unit_type / owner / within 过滤。"""

    def test_filter_by_unit_type_match(self):
        events = [
            {"type": "unit_created", "frame": 10, "unit_type": 188, "tag": 1, "owner": 1},
            {"type": "unit_created", "frame": 20, "unit_type": 73, "tag": 2, "owner": 1},
        ]
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "unit_created", "unit_type": 188}
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertTrue(v["expectations"][0]["passed"])
        self.assertTrue(v["overall_passed"])

    def test_filter_by_unit_type_no_match(self):
        events = [
            {"type": "unit_created", "frame": 10, "unit_type": 188, "tag": 1, "owner": 1},
        ]
        # 期望 Ghost(74)，实际只有 Marine(188)
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "unit_created", "unit_type": 74}
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["expectations"][0]["passed"])
        self.assertFalse(v["overall_passed"])

    def test_filter_by_owner(self):
        events = [
            {"type": "unit_created", "frame": 10, "unit_type": 188, "tag": 1, "owner": 1},
            {"type": "unit_created", "frame": 20, "unit_type": 188, "tag": 2, "owner": 2},
        ]
        # 期望 player 1 的 Marine
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "unit_created", "unit_type": 188, "from_player": 1}
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertTrue(v["expectations"][0]["passed"])
        self.assertEqual(v["expectations"][0]["evidence"][0]["owner"], 1)

    def test_filter_by_owner_no_match(self):
        events = [
            {"type": "unit_created", "frame": 10, "unit_type": 188, "tag": 1, "owner": 2},
        ]
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "unit_created", "unit_type": 188, "from_player": 1}
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["expectations"][0]["passed"])

    def test_filter_by_within(self):
        """事件在 frame 100，within=50 应不通过。"""
        events = [
            {"type": "unit_created", "frame": 100, "unit_type": 188, "tag": 1, "owner": 1},
        ]
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "unit_created", "unit_type": 188, "within": 50}
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["expectations"][0]["passed"])

    def test_no_unit_type_filter_matches_any_created(self):
        """不指定 unit_type 时，任意 unit_created 都算通过。"""
        events = [
            {"type": "unit_created", "frame": 5, "unit_type": 73, "tag": 1, "owner": 1},
        ]
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "unit_created"}
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertTrue(v["expectations"][0]["passed"])

    def test_unit_created_fails_when_only_resource_events(self):
        """只有 resource 事件、没有任何 unit_created 时应不通过。

        这正是原 bug 的回归测试：旧实现检查 unit_snapshot，每帧都发，导致
        即使没有单位创建也"通过"。新实现必须真正找不到 unit_created 才不通过。
        """
        events = [
            {"type": "resource", "frame": 0, "minerals": 100},
            {"type": "resource", "frame": 1, "minerals": 150},
        ]
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "unit_created", "unit_type": 188}
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["expectations"][0]["passed"])
        self.assertFalse(v["overall_passed"])


class TestEvaluateVerdictOtherTypes(unittest.TestCase):
    """no_script_error / game_ended / 未知类型。"""

    def test_no_script_error_pass(self):
        events = [{"type": "resource", "frame": 0}]
        scenario = {"id": "s1", "expectations": [{"id": "e1", "type": "no_script_error"}]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertTrue(v["overall_passed"])
        self.assertTrue(v["expectations"][0]["passed"])

    def test_no_script_error_fail(self):
        events = [
            {"type": "game_error", "frame": 5, "message": "ScriptError"},
            {"type": "game_error", "frame": 6, "message": "ScriptError: again"},
        ]
        scenario = {"id": "s1", "expectations": [{"id": "e1", "type": "no_script_error"}]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["overall_passed"])
        self.assertFalse(v["expectations"][0]["passed"])
        # evidence 应记录前 5 个错误
        self.assertEqual(len(v["expectations"][0]["evidence"]), 2)

    def test_game_ended_pass(self):
        events = [{"type": "game_ended", "frame": 100}]
        scenario = {"id": "s1", "expectations": [{"id": "e1", "type": "game_ended"}]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertTrue(v["overall_passed"])

    def test_game_ended_fail(self):
        events = [{"type": "resource", "frame": 50}]
        scenario = {"id": "s1", "expectations": [{"id": "e1", "type": "game_ended"}]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["overall_passed"])

    def test_unknown_expectation_type_fails(self):
        events = []
        scenario = {"id": "s1", "expectations": [{"id": "e1", "type": "unknown_thing"}]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["overall_passed"])
        self.assertFalse(v["expectations"][0]["passed"])
        self.assertIn("未知断言类型", v["expectations"][0]["evidence"][0]["message"])

    def test_multiple_expectations_partial(self):
        """多条 expectation 部分通过时 overall_passed 应为 False。"""
        events = [
            {"type": "unit_created", "frame": 5, "unit_type": 188, "tag": 1, "owner": 1},
        ]
        scenario = {"id": "s1", "expectations": [
            {"id": "e1", "type": "no_script_error"},  # pass
            {"id": "e2", "type": "unit_created", "unit_type": 188},  # pass
            {"id": "e3", "type": "game_ended"},  # fail
        ]}
        v = sc2_observer.evaluate_verdict(events, scenario)
        self.assertFalse(v["overall_passed"])
        self.assertTrue(v["expectations"][0]["passed"])
        self.assertTrue(v["expectations"][1]["passed"])
        self.assertFalse(v["expectations"][2]["passed"])


if __name__ == "__main__":
    unittest.main()
