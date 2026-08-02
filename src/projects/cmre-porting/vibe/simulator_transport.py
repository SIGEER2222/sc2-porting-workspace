"""SimulatorTransport —— 包装 SimulatorSession + protocol.SessionRegistry，实现 Transport.send。

复用 ``protocol.py`` 的 RPC schema（Request/Response/ErrorCode/SessionRegistry/checksum）。
操作白名单改为 simulator-first §4.5 集合（替换原 MVP_OPS 中面向真机 SC2 的 visual.* 等）。

P1 闸门：
- 20 顺序 ping 全 ack
- 5 重复 request_id 仅执行一次
- 5 非法请求零状态变化
- 关闭 session 拒绝旧请求
- 同 task/catalog/seed/版本同结果同 trace 哈希
"""

from __future__ import annotations

import json
import time
from typing import Optional

from . import protocol
from .function_registry import FunctionRegistryError, invoke_registered_function, normalize_request_args
from .simulator_session import KernelError, SimulatorSession

# simulator-first 操作白名单（§4.5）
SIM_OPS = {
    "system.ping",
    "function.invoke",
    "scenario.load", "scenario.reset", "scenario.step", "scenario.run", "scenario.pause",
    "unit.spawn", "unit.kill", "unit.set_vital", "unit.order",
    "player.set_resource",
    "query.units", "query.unit", "query.player", "query.mission",
    "snapshot.create", "snapshot.restore", "snapshot.compare",
    "assert.exists", "assert.not_exists", "assert.count",
    "assert.equals", "assert.range", "assert.eventually",
}


class SimulatorTransport:
    """以 SimulatorSession 为后端的本地 transport。"""

    name = "simulator"

    def __init__(self):
        self.registry = protocol.SessionRegistry()
        self.session: Optional[SimulatorSession] = None
        self.cache: dict[tuple, protocol.Response] = {}
        self.executed = 0
        self.dup_suppressed = 0
        self.illegal_rejected = 0
        self.latencies_ms: list[float] = []

    def open_session(self, session_id: str) -> None:
        self.registry.open(session_id)
        self.session = SimulatorSession()

    def close_session(self, session_id: str) -> None:
        self.registry.close(session_id)

    def send(self, req: protocol.Request) -> protocol.Response:
        """处理一个请求。返回 Response。实现幂等 + session/校验/操作/序号校验。"""
        started = time.time()
        key = (req.session_id, req.request_id)
        # 1) 先做 session/checksum/op/sequence 校验（过期 session 旧请求必须拒绝）
        code = self._validate(req)
        if code != protocol.ErrorCode.OK:
            if code in (protocol.ErrorCode.UNKNOWN_OP,):
                self.illegal_rejected += 1
            resp = protocol.Response(
                "error", req.session_id, req.request_id, req.sequence, req.operation,
                started, time.time(), int(code), {"reason": code.name}, 0,
            )
            self.cache.setdefault(key, resp)
            return resp
        # 2) 幂等：已见 request_id 返回原结果，不重复执行
        if key in self.cache:
            self.dup_suppressed += 1
            return self.cache[key]
        # 3) 执行
        try:
            payload = self._dispatch(req)
            state_version = self.session.world.clock.now.loop if (self.session and self.session.world) else 0
            resp = protocol.Response(
                "result", req.session_id, req.request_id, req.sequence, req.operation,
                started, time.time(), 0, payload, state_version,
            )
        except KernelError as e:
            resp = protocol.Response(
                "error", req.session_id, req.request_id, req.sequence, req.operation,
                started, time.time(), int(e.code), {"reason": e.detail}, 0,
            )
        except Exception as e:  # noqa: BLE001
            resp = protocol.Response(
                "error", req.session_id, req.request_id, req.sequence, req.operation,
                started, time.time(), int(protocol.ErrorCode.EXEC_FAILED),
                {"reason": "exec_failed", "detail": str(e)}, 0,
            )
        self.executed += 1
        self.latencies_ms.append((resp.completed_at - resp.started_at) * 1000.0)
        self.cache[key] = resp
        self.registry.mark(req)
        return resp

    def _validate(self, req: protocol.Request) -> protocol.ErrorCode:
        s = self.registry._sessions.get(req.session_id)  # noqa: SLF001
        if s is None or not s["open"]:
            return protocol.ErrorCode.STALE_SESSION
        if req.checksum != protocol.compute_checksum(req):
            return protocol.ErrorCode.BAD_CHECKSUM
        if req.operation not in SIM_OPS:
            return protocol.ErrorCode.UNKNOWN_OP
        if req.sequence < s["last_seq"]:
            return protocol.ErrorCode.OUT_OF_ORDER
        return protocol.ErrorCode.OK

    def _dispatch(self, req: protocol.Request) -> dict:
        op = req.operation
        a = req.args
        s = self.session
        assert s is not None
        if op == "system.ping":
            return s.ping()
        if op == "function.invoke":
            try:
                function_id, call_args = normalize_request_args(a)
                return self._dispatch_function(function_id, call_args)
            except FunctionRegistryError as e:
                code = getattr(protocol.ErrorCode, e.code, protocol.ErrorCode.INVALID_ARGS)
                raise KernelError(int(code), e.detail) from e
        if op == "scenario.load":
            return s.scenario_load(a.get("scenario_path"), a.get("scenario_dict"), a.get("catalog"))
        if op == "scenario.reset":
            return s.scenario_reset()
        if op == "scenario.step":
            return {"loop": s.scenario_step(int(a.get("loops", 1))).loop,
                    "terminated": s.terminated, "end_reason": getattr(s, "end_reason", "")}
        if op == "scenario.run":
            return s.scenario_run(a.get("max_loops"))
        if op == "scenario.pause":
            return s.scenario_pause()
        if op == "unit.spawn":
            return s.unit_spawn(a["unit_type_id"], int(a["owner_player_id"]), float(a["x"]), float(a["y"]))
        if op == "unit.kill":
            return s.unit_kill(int(a["entity_id"]))
        if op == "unit.set_vital":
            return s.unit_set_vital(int(a["entity_id"]), a.get("health"), a.get("shields"), a.get("energy"))
        if op == "unit.order":
            return s.unit_order(a["entity_ids"], a["kind"], int(a["issuer_player_id"]),
                                int(a.get("target_entity_id", 0)), float(a.get("target_x", 0.0)),
                                float(a.get("target_y", 0.0)), a.get("unit_type_id", ""), a.get("ability_id", ""))
        if op == "player.set_resource":
            return s.player_set_resource(int(a["player_id"]), a.get("minerals"), a.get("vespene"))
        if op == "query.units":
            return s.query_units(a.get("owner_player_id"))
        if op == "query.unit":
            return s.query_unit(int(a["entity_id"]))
        if op == "query.player":
            return s.query_player(int(a["player_id"]))
        if op == "query.mission":
            return s.query_mission()
        if op == "snapshot.create":
            return s.snapshot_create(a["name"])
        if op == "snapshot.restore":
            return s.snapshot_restore(a["name"])
        if op == "snapshot.compare":
            return s.snapshot_compare(a["name_a"], a["name_b"])
        if op == "assert.exists":
            return _assert_to_dict(s.assert_exists(int(a["entity_id"])))
        if op == "assert.not_exists":
            return _assert_to_dict(s.assert_not_exists(int(a["entity_id"])))
        if op == "assert.count":
            return _assert_to_dict(s.assert_count(a.get("owner_player_id"), int(a["expected"]), a.get("unit_type_id")))
        if op == "assert.equals":
            return _assert_to_dict(s.assert_equals(int(a["entity_id"]), a["field"], float(a["expected"])))
        if op == "assert.range":
            return _assert_to_dict(s.assert_range(int(a["entity_id"]), a["field"], float(a["low"]), float(a["high"])))
        if op == "assert.eventually":
            return _assert_to_dict(s.assert_eventually(a["check"], int(a.get("max_loops", 1000)), **a.get("kwargs", {})))
        raise KernelError(int(protocol.ErrorCode.UNKNOWN_OP), f"未分发操作: {op}")

    def _dispatch_function(self, function_id: str, args: dict) -> dict:
        """Explicit function-id map; never replace this with reflection."""
        s = self.session
        assert s is not None
        if function_id == "vibe.test.ping":
            return invoke_registered_function(function_id, args)
        if function_id == "vibe.player.set_resource":
            resource = args["resource"]
            value = args["value"]
            s.player_set_resource(
                args["player"],
                minerals=value if resource == "minerals" else None,
                vespene=value if resource == "vespene" else None,
            )
            return {"function_id": function_id, "player": args["player"],
                    "resource": resource, "value": value}
        if function_id == "vibe.unit.spawn":
            first_tag = 0
            created = 0
            for _ in range(args["count"]):
                result = s.unit_spawn(args["unit_type"], args["player"], args["x"], args["y"])
                if first_tag == 0:
                    first_tag = result["entity_id"]
                created += 1
            return {"function_id": function_id, "created": created, "unit_tag": first_tag,
                    "unit_type": args["unit_type"], "player": args["player"]}
        if function_id == "vibe.query.units":
            player = args["player"] or None
            result = s.query_units(player)
            unit_type = args["unit_type"]
            # Function-level unit queries expose live units; the lower-level
            # query.units operation still returns dead entities for diagnostics.
            units = [u for u in result["units"] if u.get("state") != "dead"]
            if unit_type:
                units = [u for u in units if u.get("unit_type_id") == unit_type]
            return {"function_id": function_id, "count": len(units),
                    "unit_type": unit_type, "player": args["player"]}
        if function_id == "vibe.unit.kill":
            s.unit_kill(args["unit_tag"])
            return {"function_id": function_id, "unit_tag": args["unit_tag"], "killed": True}
        if function_id == "vibe.unit.attack":
            world = s.world
            assert world is not None
            attacker = world.get_entity(args["attacker_tag"])
            if attacker is None or not attacker.is_alive:
                raise KernelError(int(protocol.ErrorCode.INVALID_ARGS), "attacker_not_found")
            target = world.get_entity(args["target_tag"])
            if target is None or not target.is_alive:
                raise KernelError(int(protocol.ErrorCode.INVALID_ARGS), "target_not_found_or_stale")
            if target.owner_player_id <= 0:
                raise KernelError(int(protocol.ErrorCode.INVALID_ARGS), "target_neutral")
            if not world.players.is_enemy(attacker.owner_player_id, target.owner_player_id):
                raise KernelError(int(protocol.ErrorCode.INVALID_ARGS), "target_ally")
            s.unit_order(
                [attacker.entity_id], "attack_unit", attacker.owner_player_id,
                target_entity_id=target.entity_id,
            )
            return {
                "function_id": function_id,
                "attacker_tag": attacker.entity_id,
                "target_tag": target.entity_id,
                "target_owner": target.owner_player_id,
                "target_type": target.unit_type_id,
                "issued": True,
            }
        if function_id == "vibe.query.structures":
            return {
                "function_id": function_id,
                **s.query_structures(args["owner_player"], args["unit_type"]),
            }
        raise KernelError(int(protocol.ErrorCode.FUNCTION_NOT_FOUND), str(function_id))


def _assert_to_dict(r) -> dict:
    return {"ok": r.ok, "detail": r.detail, "actual": r.actual, "expected": r.expected}


# ---------------------------------------------------------------------------
# P1 闸门自测
# ---------------------------------------------------------------------------

def p1_selftest() -> dict:
    """P1 闸门：20 ping ack / 重复 ID 去重 / 非法零副作用 / session 恢复 / 确定性 trace 哈希。

    确定性：同一 task+catalog+seed 跑两次，trace 哈希必须相同。
    """
    t = SimulatorTransport()
    sid = "sess-p1"
    t.open_session(sid)
    seq = 0
    # 20 顺序 ping
    for i in range(20):
        seq += 1
        r = t.send(protocol.make_request(sid, f"ping-{i}", seq, "system.ping"))
        assert r.kind == "result" and r.error_code == 0, f"ping {i} failed: {r.payload}"
    # 5 重复 ID
    for _ in range(5):
        seq += 1
        t.send(protocol.make_request(sid, "ping-0", seq, "system.ping"))
    # 5 非法操作
    for i in range(5):
        seq += 1
        t.send(protocol.make_request(sid, f"illegal-{i}", seq, "unit.unknown_op"))
    # session 恢复
    t.close_session(sid)
    seq += 1
    r = t.send(protocol.make_request(sid, "ping-0", seq, "system.ping"))
    recovery_ok = r.error_code == int(protocol.ErrorCode.STALE_SESSION)

    # 确定性：跑两次手写场景，trace 哈希必须相同
    det_ok, det_detail = _determinism_check()

    import statistics
    p95 = round(statistics.quantiles(t.latencies_ms, n=20)[-1], 3) if t.latencies_ms else 0.0
    checks = {
        "20_ping_ack": t.executed >= 20,
        "dup_once": t.executed == 20 and t.dup_suppressed == 5,
        "illegal_zero_sideeffect": t.illegal_rejected == 5,
        "p95_le_2s": p95 <= 2000.0,
        "session_recovery": recovery_ok,
        "determinism_trace_hash": det_ok,
    }
    return {"passed": all(checks.values()), "checks": checks,
            "metrics": {"executed": t.executed, "dup_suppressed": t.dup_suppressed,
                        "illegal_rejected": t.illegal_rejected, "p95_ms": p95,
                        "determinism_detail": det_detail}}


def _determinism_check() -> tuple[bool, str]:
    """同 task/catalog/seed 跑两次，trace 哈希必须相同。"""
    from .contracts import load_scenario, run_scenario
    # 用现有 marine_vs_zergling 场景（确定性基准）
    sc = load_scenario("reference/sc2-ally-bot/scenarios/sc2-simulator/marine_vs_zergling.json")
    w1, _ = run_scenario(sc)
    from sc2_simulator.reporting.trace import trace_hash
    h1 = trace_hash(w1)
    w2, _ = run_scenario(sc)
    h2 = trace_hash(w2)
    return h1 == h2, f"h1={h1[:12]} h2={h2[:12]} equal={h1 == h2}"


if __name__ == "__main__":
    import sys
    result = p1_selftest()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["passed"] else 1)
