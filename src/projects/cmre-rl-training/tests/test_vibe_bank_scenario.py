"""route B episode 建场层的离线门禁。

这里刻意不碰 SC2：Bank 通道被替换成内存假件，专门压那些**真机上很贵、很难复现**的
路径 —— at-least-once 重发、请求丢失、场景残缺不静默通过。真机只负责证明"能跑"，
语义正确性应该在这里被钉死。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cmre_rl_training import vibe_bank_scenario as vbs  # noqa: E402


class FakeBank:
    """内存版 Bank：可配置"请求丢失"来模拟 VIBE_GEN_007 的有损覆盖写。"""

    def __init__(self, *, drop_first: int = 0, respond_after: int = 0) -> None:
        self.requests: dict[str, object] = {}
        self.responses: dict[str, str] = {}
        self.index: dict[str, str] = {}
        self.writes = 0
        self.drop_first = drop_first
        self.respond_after = respond_after
        self._seen_reads: dict[str, int] = {}

    # --- host API 形状 ---
    def read_bank(self, _name: str) -> dict:
        for rid in list(self.requests):
            self._seen_reads[rid] = self._seen_reads.get(rid, 0) + 1
            if self._seen_reads[rid] > self.respond_after and rid not in self.responses:
                self.responses[rid] = json.dumps({
                    "kind": "result", "request_id": rid, "error_code": "OK",
                    "payload": {"pong": True, "created": 3},
                })
        return {"index": dict(self.index), "response": dict(self.responses)}

    def write_bank_request(self, _name, rid, request, player=1) -> bool:  # noqa: ARG002
        self.writes += 1
        if self.drop_first > 0:
            self.drop_first -= 1
            return True  # 写"成功"但请求被有损通道吞掉
        self.requests[rid] = request
        return True

    def bank_request_landed(self, _name: str, rid: str) -> bool:
        return rid in self.requests


class DummyRpcRequest:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


@pytest.fixture
def fake_host(monkeypatch, tmp_path):
    bank = FakeBank()

    def _loader():
        return {
            "read_bank": bank.read_bank,
            "write_bank_request": bank.write_bank_request,
            "bank_request_landed": bank.bank_request_landed,
            "RpcRequest": DummyRpcRequest,
            "DEFAULT_BANK_DIR": tmp_path,
        }

    monkeypatch.setattr(vbs, "_load_host_api", _loader)
    return bank


def _scenario(bank_poll: float = 0.0) -> vbs.VibeBankScenario:
    return vbs.VibeBankScenario(poll_interval=bank_poll or 0.001,
                                reassert_seconds=0.002, default_timeout=2.0)


def test_unit_placement_serialises_all_args_as_strings():
    args = vbs.UnitPlacement("Marine", 4, 10.0, 12.5, player=2).as_args()
    assert args == {"count": "4", "player": "2", "unit_type": "Marine",
                    "x": "10.0", "y": "12.5"}
    assert all(isinstance(v, str) for v in args.values())


def test_default_scenario_has_both_sides():
    # RL 没有对手就没有 reward 梯度；默认场景必须自带敌人。
    assert vbs.DEFAULT_SCENARIO.own_units() > 0
    assert vbs.DEFAULT_SCENARIO.enemy_units() > 0


def test_call_returns_decoded_payload(fake_host):
    scenario = _scenario()
    result = scenario.call("system.ping", {})
    assert result["ok"] is True
    assert result["payload"]["pong"] is True
    assert scenario.stats["calls"] == 1
    assert scenario.stats["timeouts"] == 0


def test_call_reasserts_when_request_is_swallowed(fake_host):
    """VIBE_GEN_007：请求被有损通道吞掉时必须用同一个 rid 重发，而不是干等超时。"""

    fake_host.drop_first = 1
    scenario = _scenario()
    result = scenario.call("unit.spawn", {"count": "1"})
    assert result["ok"] is True
    assert result["reasserts"] >= 1, "被吞的请求没有触发重发"
    assert fake_host.writes >= 2


def test_call_times_out_without_response(fake_host, monkeypatch):
    monkeypatch.setattr(fake_host, "read_bank",
                        lambda _n: {"index": {}, "response": {}})
    scenario = vbs.VibeBankScenario(poll_interval=0.001, reassert_seconds=5.0,
                                    default_timeout=0.05)
    result = scenario.call("system.ping", {})
    assert result["ok"] is False
    assert result["error"] == "timeout"
    assert scenario.stats["timeouts"] == 1


def test_wait_for_kernel_requires_both_markers(fake_host, tmp_path):
    scenario = _scenario()
    (tmp_path / "GalaxyVibe.SC2Bank").write_text("x", encoding="utf-8")
    fake_host.index = {"kernel_initialized": "1"}
    seen = scenario.wait_for_kernel(timeout=0.05)
    assert seen == {"kernel_initialized": 1}

    fake_host.index = {"kernel_initialized": "1", "register_entrypoints_done": "1"}
    seen = scenario.wait_for_kernel(timeout=0.5)
    assert set(seen) == set(vbs.REG_MARKERS)


def test_wait_for_kernel_empty_when_bank_missing(fake_host):
    scenario = _scenario()
    assert scenario.wait_for_kernel(timeout=0.05) == {}


def test_build_reports_every_placement(fake_host):
    scenario = _scenario()
    outcome = scenario.build(vbs.DEFAULT_SCENARIO)
    assert outcome["ok"] is True
    assert len(outcome["placements"]) == len(vbs.DEFAULT_SCENARIO.placements)
    assert outcome["expected_own"] == vbs.DEFAULT_SCENARIO.own_units()
    assert outcome["expected_enemy"] == vbs.DEFAULT_SCENARIO.enemy_units()
    assert outcome["failed"] == []


def test_build_fails_loudly_on_partial_scenario(fake_host, monkeypatch):
    """场景残缺必须 ok=False —— 静默跳过会让 reward 悄悄失真，比直接失败难查得多。"""

    scenario = _scenario()
    seen = {"spawn": 0}
    original = scenario.call

    def flaky(operation, args=None, *, timeout=None):
        # 只打第 2 个 spawn，避免和建交调用的顺序耦合（顺序一变测试就假失败）
        if operation == "unit.spawn":
            seen["spawn"] += 1
            if seen["spawn"] == 2:
                return {"ok": False, "error": "timeout", "operation": operation}
        return original(operation, args, timeout=timeout)

    monkeypatch.setattr(scenario, "call", flaky)
    outcome = scenario.build(vbs.DEFAULT_SCENARIO)
    assert outcome["ok"] is False
    assert len(outcome["failed"]) == 1
    assert outcome["failed"][0]["error"] == "timeout"


# --------------------------------------------------------------------------
# VIBE_BANK_009：gen 图默认全员盟友，必须显式建交
# --------------------------------------------------------------------------

def test_build_sets_hostility_before_spawning(fake_host):
    """建交必须发生在 spawn 之前，否则首帧观测会读到"敌人是盟友"的中间态。"""

    scenario = _scenario()
    outcome = scenario.build(vbs.DEFAULT_SCENARIO)
    ops = [rec["operation"] for rec in scenario.stats["trace"]]
    assert ops.count("function.invoke") == 2, ops     # 双向各一次
    assert ops.index("function.invoke") < ops.index("unit.spawn"), ops
    assert outcome["alliances"][0]["pair"] == [1, 2]
    assert outcome["failed_alliances"] == []


def test_set_hostile_is_bidirectional(fake_host):
    """单向 ClearAlliance 会造出"A 打得了 B、B 打不了 A"的半敌对状态。

    这比全盟友更难查：episode 表面上能打起来，只是一方永远挨打不还手，
    reward 看着有信号、其实学到的是错的。
    """

    scenario = _scenario()
    result = scenario.set_hostile(1, 2)
    assert result["ok"] is True
    directions = {(c["source"], c["target"]) for c in result["calls"]}
    assert directions == {(1, 2), (2, 1)}


def test_hostile_pairs_default_to_all_distinct_players():
    spec = vbs.ScenarioSpec(
        name="3way",
        placements=(
            vbs.UnitPlacement("Marine", 1, 0.0, 0.0, player=1),
            vbs.UnitPlacement("Marine", 1, 5.0, 0.0, player=2),
            vbs.UnitPlacement("Marine", 1, 0.0, 5.0, player=3),
        ),
    )
    assert spec.players() == (1, 2, 3)
    assert spec.resolved_hostile_pairs() == ((1, 2), (1, 3), (2, 3))


def test_explicit_hostile_pairs_win_over_derivation():
    spec = vbs.ScenarioSpec(
        name="2v1",
        placements=(
            vbs.UnitPlacement("Marine", 1, 0.0, 0.0, player=1),
            vbs.UnitPlacement("Marine", 1, 5.0, 0.0, player=2),
            vbs.UnitPlacement("Marine", 1, 0.0, 5.0, player=3),
        ),
        hostile_pairs=((1, 3), (2, 3)),   # 1 与 2 保持盟友
    )
    assert spec.resolved_hostile_pairs() == ((1, 3), (2, 3))


def test_invoke_error_code_is_not_swallowed(fake_host, monkeypatch):
    """Bank「送到了」不等于函数「跑成功了」。

    内核把执行结果编码在 error_code 里；只看传输层的 ok 会把 INVALID_ARGS
    当成功——建交静默失败，episode 退化成双方站着不打，且零报错。
    """

    scenario = _scenario()

    def bad_response(_name):
        out = fake_host.read_bank(_name)
        out["response"] = {
            rid: json.dumps({"kind": "result", "request_id": rid,
                             "error_code": "INVALID_ARGS", "payload": {}})
            for rid in out["response"]}
        return out

    # 直接换 scenario 持有的引用：__init__ 时已经把 host API 抓成了实例属性，
    # 事后改 fake_host 的属性是打不中的（这本身就踩过一次）。
    monkeypatch.setattr(scenario, "_read_bank", bad_response)
    result = scenario.invoke("gen.9744", {"p0": 1, "p1": 2})
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGS"

    build = scenario.build(vbs.DEFAULT_SCENARIO)
    assert build["ok"] is False
    assert build["failed_alliances"], "建交失败必须让整个 build 失败"


def test_resolve_gen_function_id_prefers_registry(tmp_path):
    """编号写死会随重新生成漂移，且失效方式是"打到别的函数上"这种静默错。"""

    registry = tmp_path / "function-registry.json"
    registry.write_text(json.dumps({"functions": {
        "gen.4242": {"galaxy_name": "libCOTF_gf_ClearAlliance"},
        "gen.1": {"galaxy_name": "AIAbilityFixed"},
    }}), encoding="utf-8")
    fid, source = vbs.resolve_gen_function_id(
        "libCOTF_gf_ClearAlliance", "gen.9744", registry_path=registry)
    assert (fid, source) == ("gen.4242", "registry")


def test_resolve_gen_function_id_reports_fallback_reason(tmp_path):
    missing = tmp_path / "nope.json"
    fid, source = vbs.resolve_gen_function_id(
        "libCOTF_gf_ClearAlliance", "gen.9744", registry_path=missing)
    assert fid == "gen.9744"
    assert source.startswith("fallback:registry-unreadable")

    ambiguous = tmp_path / "dup.json"
    ambiguous.write_text(json.dumps({"functions": {
        "gen.1": {"galaxy_name": "dup"}, "gen.2": {"galaxy_name": "dup"}}}),
        encoding="utf-8")
    fid, source = vbs.resolve_gen_function_id(
        "dup", "gen.9744", registry_path=ambiguous)
    assert (fid, source) == ("gen.9744", "fallback:ambiguous:2")


def test_real_registry_resolves_clear_alliance():
    """真 registry 反查必须命中——命中不了说明依赖集漂移了，要在离线就炸出来。"""

    fid, source = vbs.resolve_gen_function_id(
        vbs.CLEAR_ALLIANCE_GALAXY_NAME, vbs.CLEAR_ALLIANCE_FALLBACK_ID)
    assert source == "registry", f"registry 反查失败({source})，gen 编号可能已漂移"
    assert fid == vbs.CLEAR_ALLIANCE_FALLBACK_ID, (
        f"registry 反查到 {fid}，与兜底常量 {vbs.CLEAR_ALLIANCE_FALLBACK_ID} 不一致，"
        "请同步更新常量")


def test_call_pumps_game_clock_every_poll(fake_host, monkeypatch):
    """VIBE_BANK_008：step 模式下不推游戏钟，内核 PollLoop 永远不执行。

    ep-0110 的真实失败就是这个：realtime=False 的会话被按在 loop=0 上，
    Bank 里既没有注册标记也没有 response，看着像"地图没加载"。
    """

    monkeypatch.setattr(fake_host, "read_bank",
                        lambda _n: {"index": {}, "response": {}})
    ticks = {"n": 0}
    scenario = vbs.VibeBankScenario(poll_interval=0.001, reassert_seconds=5.0,
                                    default_timeout=0.05,
                                    pump=lambda: ticks.__setitem__("n", ticks["n"] + 1))
    scenario.call("system.ping", {})
    assert ticks["n"] > 0, "等待期间一次都没推进游戏钟"
    assert scenario.stats["pumps"] == ticks["n"]


def test_wait_for_kernel_pumps_game_clock(fake_host):
    ticks = {"n": 0}
    scenario = vbs.VibeBankScenario(poll_interval=0.001,
                                    pump=lambda: ticks.__setitem__("n", ticks["n"] + 1))
    scenario.wait_for_kernel(timeout=0.05)
    assert ticks["n"] > 0


def test_pump_failure_escalates_instead_of_hanging(fake_host, monkeypatch):
    """会话断了就要立刻炸，不要把连接故障伪装成"Bank 超时"。"""

    monkeypatch.setattr(fake_host, "read_bank",
                        lambda _n: {"index": {}, "response": {}})

    def broken_pump():
        raise ConnectionResetError("ws closed")

    scenario = vbs.VibeBankScenario(poll_interval=0.001, reassert_seconds=5.0,
                                    default_timeout=30.0, pump=broken_pump,
                                    max_pump_failures=3)
    with pytest.raises(vbs.VibeBankError, match="pump failed"):
        scenario.call("system.ping", {})
    assert scenario.stats["pump_failures"] == 3


def test_pump_failure_streak_resets_on_success(fake_host):
    """偶发抖动不该被当成会话已死。"""

    fake_host.respond_after = 6  # 让响应晚点来，逼出若干轮 pump
    calls = {"n": 0}

    def flaky_pump():
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            raise TimeoutError("transient")

    scenario = vbs.VibeBankScenario(poll_interval=0.001, reassert_seconds=5.0,
                                    default_timeout=5.0, pump=flaky_pump,
                                    max_pump_failures=3)
    result = scenario.call("system.ping", {})  # 不应抛异常
    assert result["ok"] is True
    assert scenario.stats["pump_failures"] > 0


def test_archive_bank_moves_stale_file(fake_host, tmp_path):
    scenario = _scenario()
    bank = tmp_path / "GalaxyVibe.SC2Bank"
    bank.write_text("stale", encoding="utf-8")
    archived = scenario.archive_bank()
    assert archived is not None
    assert not bank.exists()
    assert Path(archived).exists()
    # 没有旧 bank 时不应该假装归档了什么
    assert scenario.archive_bank() is None


# --------------------------------------------------------------------------
# VIBE_BANK_011：内核真值查询的传输重试边界
# --------------------------------------------------------------------------

def test_query_units_retries_transport_failure(fake_host, monkeypatch):
    """通道 timeout 不等于「单位不存在」——重试一次就该拿到真值。

    ep-alliance-03 真机上判据 ④ 因单次 timeout 被误判红，而 raw obs 同时
    看得见那 2 个敌方 Marine。同实例 A/B 实测 p2 5/6 成功、成功时 count 恒真。
    """

    scenario = _scenario()
    calls = {"n": 0}
    real_call = scenario.call

    def flaky_call(operation, args=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "error": "timeout", "reasserts": 2}
        return real_call(operation, args, **kwargs)

    monkeypatch.setattr(scenario, "call", flaky_call)
    result = scenario.query_units(player=2, attempts=3)
    assert result["ok"] is True
    assert result["transport_retries"] == 1
    assert calls["n"] == 2, "拿到成功响应后必须立刻停手，不能把重试跑满"


def test_query_units_does_not_retry_a_successful_wrong_answer(fake_host,
                                                              monkeypatch):
    """只重传输失败。「读到了但数字不对」是真实场景故障，重试等于拆掉校验器。

    round22 血泪：以执行数为输入的次级判据插到根本判据前面，反向对照就再也
    抓不到假阳性。这里的对应形态是——如果对成功响应也重试，一个"敌人没造出来"
    的真故障会被反复重查直到某次数字凑巧对上。
    """

    scenario = _scenario()
    calls = {"n": 0}

    def wrong_but_successful(operation, args=None, **kwargs):  # noqa: ARG001
        calls["n"] += 1
        return {"ok": True, "payload": {"count": 0}, "raw": "{}"}

    monkeypatch.setattr(scenario, "call", wrong_but_successful)
    result = scenario.query_units(player=2, attempts=5)
    assert result["ok"] is True
    assert result["payload"]["count"] == 0
    assert calls["n"] == 1, "成功响应必须原样返回，哪怕数字是错的"


def test_query_units_reports_exhausted_retries(fake_host, monkeypatch):
    """重试跑满仍失败时，必须如实报失败 + 报重试次数，不能假装成功。"""

    scenario = _scenario()

    def always_timeout(operation, args=None, **kwargs):  # noqa: ARG001
        return {"ok": False, "error": "timeout"}

    monkeypatch.setattr(scenario, "call", always_timeout)
    result = scenario.query_units(player=2, attempts=3)
    assert result["ok"] is False
    assert result["transport_retries"] == 2


def test_query_units_defaults_to_single_attempt(fake_host, monkeypatch):
    """默认不重试：调用方必须显式声明它愿意为有损通道买单。"""

    scenario = _scenario()
    calls = {"n": 0}

    def always_timeout(operation, args=None, **kwargs):  # noqa: ARG001
        calls["n"] += 1
        return {"ok": False, "error": "timeout"}

    monkeypatch.setattr(scenario, "call", always_timeout)
    scenario.query_units(player=1)
    assert calls["n"] == 1
