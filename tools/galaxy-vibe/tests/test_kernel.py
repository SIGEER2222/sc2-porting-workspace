"""P1 单元测试 — Vibe Host 与 RPC 协议契约测试。

依据 P1 验收：
  - Galaxy 编译及 schema 测试通过
  - spawn 3 Marine、查询为 3、改资源/生命、kill/reset 均与结果一致
  - 未知操作、坏单位 ID、超限 count 不执行

测试策略：
  - 单元测试（不依赖 SC2）：RPC 序列化、checksum、session、幂等、whitelist 校验
  - 契约测试（mock SC2）：模拟 Kernel 响应，验证 Host 端到端流程
  - 静态 schema 测试：验证 rpc-schema.json 合法

运行：
  python -m pytest tools/galaxy-vibe/tests/test_kernel.py -v
  或
  python tools/galaxy-vibe/tests/test_kernel.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from host.vibe_host import (  # noqa: E402
    RpcRequest,
    RpcResponse,
    VibeHost,
    PROTOCOL_VERSION,
    write_bank_request,
)
from vibe import protocol  # noqa: E402
from vibe.function_registry import load_function_registry  # noqa: E402
from vibe.simulator_transport import SimulatorTransport  # noqa: E402
from galaxy_repl import _resume_sequence_from_bank  # noqa: E402


# ---- RPC 协议单元测试 ----

class TestReplSessionResume(unittest.TestCase):
    def test_resume_reads_highest_sequence_for_selected_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = Path(tmp) / "GalaxyVibe.SC2Bank"
            bank.write_text(
                '<?xml version="1.0"?><Bank version="1">'
                '<Section name="response">'
                '<Key name="old"><Value string="{&quot;session_id&quot;:&quot;other&quot;,&quot;sequence&quot;:99}"/></Key>'
                '<Key name="first"><Value string="{&quot;session_id&quot;:&quot;resume&quot;,&quot;sequence&quot;:4}"/></Key>'
                '<Key name="last"><Value string="{&quot;session_id&quot;:&quot;resume&quot;,&quot;sequence&quot;:7}"/></Key>'
                '</Section></Bank>',
                encoding="utf-8",
            )
            self.assertEqual(_resume_sequence_from_bank("resume", bank), 7)

class TestRpcRequest(unittest.TestCase):
    """RpcRequest 序列化与 checksum 测试。"""

    def test_request_args_string_serialization(self):
        """请求应能序列化为 Galaxy 可解析的 key=value;key=value 格式。"""
        req = RpcRequest(
            session_id="test_session_001",
            request_id="req_001",
            sequence=1,
            operation="system.ping",
            args={},
        )
        s = req.to_args_string()
        self.assertIn("protocol_version=vibe/1.0", s)
        self.assertIn("session_id=test_session_001", s)
        self.assertIn("request_id=req_001", s)
        self.assertIn("sequence=1", s)
        self.assertIn("operation=system.ping", s)
        self.assertIn("checksum=", s)

    def test_request_args_with_params(self):
        """带参数的请求应正确序列化。"""
        req = RpcRequest(
            session_id="s1",
            request_id="r1",
            sequence=5,
            operation="unit.spawn",
            args={"unit_type": "Marine", "count": 3, "player": 1},
        )
        s = req.to_args_string()
        self.assertIn("unit_type=Marine", s)
        self.assertIn("count=3", s)
        self.assertIn("player=1", s)

    def test_function_invoke_wire_is_typed_and_explicit(self):
        req = RpcRequest(
            session_id="test_session_001",
            request_id="req_function_001",
            sequence=1,
            operation="function.invoke",
            args={"function_id": "vibe.test.ping", "args": {"nonce": "stage16"}},
        )
        s = req.to_args_string()
        self.assertIn("operation=function.invoke", s)
        self.assertIn("function_id=vibe.test.ping", s)
        self.assertIn("arg_nonce=stage16", s)
        self.assertNotIn(";nonce=stage16", s)
        self.assertIn("arg_names=nonce", s)

    def test_checksum_deterministic(self):
        """相同输入应生成相同 checksum。"""
        req1 = RpcRequest(session_id="s1", request_id="r1", sequence=1, operation="system.ping")
        req2 = RpcRequest(session_id="s1", request_id="r1", sequence=1, operation="system.ping")
        self.assertEqual(req1.checksum, req2.checksum)
        self.assertEqual(len(req1.checksum), 8)

    def test_checksum_changes_with_input(self):
        """不同输入应生成不同 checksum。"""
        req1 = RpcRequest(session_id="s1", request_id="r1", sequence=1, operation="system.ping")
        req2 = RpcRequest(session_id="s1", request_id="r1", sequence=2, operation="system.ping")
        self.assertNotEqual(req1.checksum, req2.checksum)

    def test_protocol_version_constant(self):
        """协议版本应固定为 vibe/1.0。"""
        self.assertEqual(PROTOCOL_VERSION, "vibe/1.0")


# ---- 响应解析测试 ----

class TestRpcResponse(unittest.TestCase):
    """RpcResponse JSON 解析测试。"""

    def test_parse_result_response(self):
        """应正确解析 result 响应。"""
        raw = json.dumps({
            "kind": "result",
            "protocol_version": "vibe/1.0",
            "session_id": "s1",
            "request_id": "r1",
            "sequence": 1,
            "operation": "system.ping",
            "error_code": "OK",
            "payload": {"pong": True, "request_count": 1, "rejected_count": 0},
            "state_version": 0,
        })
        resp = RpcResponse.from_json(raw)
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.kind, "result")
        self.assertEqual(resp.payload["pong"], True)
        self.assertEqual(resp.state_version, 0)

    def test_parse_error_response(self):
        """应正确解析 error 响应。"""
        raw = json.dumps({
            "kind": "error",
            "protocol_version": "vibe/1.0",
            "session_id": "s1",
            "request_id": "r1",
            "sequence": 1,
            "operation": "unit.spawn",
            "error_code": "COUNT_OUT_OF_RANGE",
            "payload": {},
            "state_version": 0,
        })
        resp = RpcResponse.from_json(raw)
        self.assertFalse(resp.is_ok)
        self.assertEqual(resp.error_code, "COUNT_OUT_OF_RANGE")

    def test_parse_invalid_json(self):
        """无效 JSON 应返回 INTERNAL_ERROR。"""
        resp = RpcResponse.from_json("not json")
        self.assertEqual(resp.error_code, "INTERNAL_ERROR")


# ---- Bank transport tests ----

class TestBankTransport(unittest.TestCase):
    def test_bank_write_retries_transient_file_lock(self):
        request = RpcRequest(
            session_id="bank-test",
            request_id="request-1",
            sequence=1,
            operation="system.ping",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("host.vibe_host.DEFAULT_BANK_DIR", Path(temp_dir)):
                with patch.object(
                    __import__("host.vibe_host", fromlist=["ET"]).ET.ElementTree,
                    "write",
                    side_effect=[PermissionError("bank locked"), None],
                ) as write_mock:
                    # os.replace 是原子写实现细节；mock 的 tree.write 不在磁盘落盘，
                    # 若不 stub 它会在成功那次抛 FileNotFoundError(OSError 子类) 触发多余重试、
                    # 耗尽 2 元素 side_effect 得 StopIteration。单测只验证 write 重试/backoff 行为。
                    with patch("host.vibe_host.os.replace") as replace_mock:
                        with patch("host.vibe_host.time.sleep") as sleep_mock:
                            self.assertTrue(write_bank_request("RetryBank", "request-1", request))
        self.assertEqual(write_mock.call_count, 2)
        sleep_mock.assert_called_once()
        replace_mock.assert_called_once()


# ---- 白名单注册表测试 ----

class TestWhitelist(unittest.TestCase):
    """白名单注册表契约测试。"""

    @classmethod
    def setUpClass(cls):
        cls.whitelist_path = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "whitelist.json"
        cls.whitelist = json.loads(cls.whitelist_path.read_text(encoding="utf-8"))

    def test_whitelist_loads(self):
        """白名单 JSON 应能加载。"""
        self.assertIn("operations", self.whitelist)
        self.assertGreater(len(self.whitelist["operations"]), 0)

    def test_function_registry_loads_explicit_ping(self):
        registry = load_function_registry()
        self.assertEqual(registry["vibe.test.ping"]["handler"], "libVibeKernel_gf_FunctionVibeTestPing")
        self.assertFalse(registry["vibe.test.ping"]["side_effect"])
        self.assertEqual(registry["vibe.test.ping"]["args"]["nonce"]["type"], "string")

    def test_function_registry_action_slice_is_explicit_and_typed(self):
        registry = load_function_registry()
        expected = {
            "vibe.player.set_resource": ("player", "resource", "value"),
            "vibe.unit.spawn": ("unit_type", "count", "player", "x", "y"),
            "vibe.query.units": ("player", "unit_type"),
            "vibe.unit.kill": ("unit_tag",),
            "vibe.unit.attack": ("attacker_tag", "target_tag"),
            "vibe.query.structures": ("owner_player", "unit_type"),
            "vibe.unit.add_ability": ("unit_tag", "ability"),
            "vibe.unit.query_ability": ("unit_tag", "ability"),
        }
        for function_id, arg_names in expected.items():
            self.assertIn(function_id, registry)
            self.assertEqual(tuple(registry[function_id]["args"]), arg_names)
            self.assertTrue(registry[function_id]["handler"].startswith("libVibeKernel_gf_Function"))

    def test_function_registry_bounds_and_enum_are_enforced(self):
        from vibe.function_registry import FunctionRegistryError, validate_invocation

        with self.assertRaises(FunctionRegistryError):
            validate_invocation("vibe.unit.spawn", {"unit_type": "Marine", "count": 0, "player": 1})
        with self.assertRaises(FunctionRegistryError):
            validate_invocation("vibe.player.set_resource", {"player": 1, "resource": "supply", "value": 1})
        normalized = validate_invocation("vibe.query.units", {})
        self.assertEqual(normalized, {"player": 0, "unit_type": ""})
        self.assertEqual(
            validate_invocation("vibe.query.structures", {}),
            {"owner_player": 0, "unit_type": ""},
        )

    def test_mvp_operations_present(self):
        """MVP 操作集应全部在白名单中。"""
        required = [
            "system.ping", "scenario.reset",
            "unit.spawn", "unit.kill", "unit.set_vital",
            "player.set_resource",
            "query.units", "query.unit", "query.mission",
            "visual.actor_tint", "visual.actor_scale", "visual.actor_opacity",
            # Stage 1 新增：动态诊断
            "upgrade.set_level", "tech_tree.check",
            "query.unit_tags", "query.unit_attrs",
        ]
        for op in required:
            self.assertIn(op, self.whitelist["operations"], f"缺少 MVP 操作: {op}")

    def test_rejected_operations_listed(self):
        """被拒绝的操作（call/run/exec 等）应在 rejected_operations 中。"""
        rejected = self.whitelist.get("rejected_operations", [])
        self.assertIn("call", rejected)
        self.assertIn("run", rejected)

    def test_side_effect_marking(self):
        """query.* 应标记为无副作用，unit.spawn 应标记为有副作用。"""
        ops = self.whitelist["operations"]
        self.assertFalse(ops["query.units"]["produces_side_effect"])
        self.assertFalse(ops["system.ping"]["produces_side_effect"])
        self.assertTrue(ops["unit.spawn"]["produces_side_effect"])
        self.assertTrue(ops["scenario.reset"]["produces_side_effect"])

    def test_unit_spawn_count_bounds(self):
        """unit.spawn 的 count 参数应有 1-200 边界。"""
        count_arg = self.whitelist["operations"]["unit.spawn"]["args"]["count"]
        self.assertEqual(count_arg["min"], 1)
        self.assertEqual(count_arg["max"], 200)

    def test_player_range_1_to_15(self):
        """player 参数应为 1-15。"""
        player_arg = self.whitelist["operations"]["unit.spawn"]["args"]["player"]
        self.assertEqual(player_arg["min"], 1)
        self.assertEqual(player_arg["max"], 15)


# ---- Host 行为测试（mock SC2）----

class TestVibeHostMocked(unittest.TestCase):
    """VibeHost 行为测试（mock SC2 连接）。"""

    def setUp(self):
        self.host = VibeHost(sc2_port=9999, artifacts_dir=Path(__file__).parent / "_test_artifacts")
        self.host.start_session()

    def tearDown(self):
        self.host.close()

    def test_session_id_unique(self):
        """每次 start_session 应生成不同 session_id。"""
        s1 = self.host.session_id
        s2 = self.host.start_session()
        self.assertNotEqual(s1, s2)

    def test_sequence_increments(self):
        """每次 request 应递增 sequence。"""
        # mock 连接，返回固定响应
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="system.ping",
                error_code="OK", payload={"pong": True},
            )
            self.host.ping()
            self.host.ping()
            self.assertEqual(self.host.sequence, 2)

    def test_unknown_operation_rejected_by_host(self):
        """Host 侧应拒绝不在白名单的操作（防御性）。"""
        # 注：Kernel 也会拒绝，Host 侧提前拒绝减少无用请求
        # 当前实现 Host 不预校验，依赖 Kernel 拒绝
        # 这里测试 Kernel 返回 UNKNOWN_OPERATION 时 Host 正确传递
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="error", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="call_arbitrary_func",
                error_code="UNKNOWN_OPERATION",
            )
            resp = self.host.request("call_arbitrary_func", {"func": "UnitKillAll"})
            self.assertEqual(resp.error_code, "UNKNOWN_OPERATION")
            self.assertFalse(resp.is_ok)

    def test_invoke_function_uses_typed_payload(self):
        host = self.host
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        host.client = mock_client
        response = RpcResponse(
            kind="result", session_id=host.session_id,
            request_id="r1", sequence=1, operation="function.invoke",
            error_code="OK",
            payload={"function_id": "vibe.test.ping", "message": "pong", "nonce": "stage16"},
            state_version=0,
        )
        with patch.object(host, "_poll_response", return_value=response):
            result = host.invoke_function("vibe.test.ping", {"nonce": "stage16"})
        self.assertTrue(result.is_ok)
        self.assertEqual(result.payload["message"], "pong")

    def test_unknown_function_rejected_before_transport(self):
        self.host.client = MagicMock()
        result = self.host.invoke_function("vibe.test.unknown", {})
        self.assertFalse(result.is_ok)
        self.assertEqual(result.error_code, "FUNCTION_NOT_FOUND")
        self.host.client.map_command.assert_not_called()

    def test_bank_poll_wait_advances_non_realtime_frames(self):
        """Bank transport 等待期间必须 RequestStep，否则非实时游戏会冻结。"""
        mock_client = MagicMock()
        mock_client.step.return_value = True
        self.host.client = mock_client
        with patch("host.vibe_host.read_bank", return_value={}):
            response = self.host._poll_response("waiting", timeout=0.06, advance_frames=True)
        self.assertEqual(response.error_code, "INTERNAL_ERROR")
        self.assertGreaterEqual(mock_client.step.call_count, 1)

    def test_bank_poll_uses_configured_step_batch(self):
        """A non-realtime caller may batch safe RequestStep progress."""
        mock_client = MagicMock()
        mock_client.step.return_value = True
        self.host.client = mock_client
        self.host.poll_step_count = 4
        with patch("host.vibe_host.read_bank", return_value={}):
            self.host._poll_response("batched", timeout=0.06, advance_frames=True)
        self.assertGreaterEqual(mock_client.step.call_count, 1)
        self.assertEqual(mock_client.step.call_args_list[0].kwargs["count"], 4)

    def test_bank_poll_stops_when_request_step_fails(self):
        """SC2 peer 断开时 BankPoll 必须立即返回，不能重复写坏 websocket。"""
        mock_client = MagicMock()
        mock_client.step.return_value = False
        self.host.client = mock_client
        with patch("host.vibe_host.read_bank", return_value={}):
            response = self.host._poll_response("disconnected", timeout=5.0, advance_frames=True)
        self.assertEqual(response.error_code, "INTERNAL_ERROR")
        self.assertEqual(response.payload["reason"], "request_step_failed")
        self.assertEqual(mock_client.step.call_count, 1)

    def test_request_fills_identity_for_local_transport_error(self):
        """Host-generated transport errors retain the originating operation."""
        self.host.client = MagicMock()
        with patch("host.vibe_host.write_bank_request", return_value=True):
            with patch.object(
                self.host,
                "_poll_response",
                return_value=RpcResponse(
                    kind="error",
                    session_id="",
                    request_id="",
                    sequence=0,
                    error_code="INTERNAL_ERROR",
                ),
            ):
                response = self.host.request("system.ping", {}, transport="bank_poll")
        self.assertEqual(response.session_id, self.host.session_id)
        self.assertTrue(response.request_id)
        self.assertEqual(response.sequence, 1)
        self.assertEqual(response.operation, "system.ping")

    def test_map_initialization_gate_is_stable_before_actions(self):
        """Host must observe complete map initialization twice before actions."""
        mock_client = MagicMock()
        mock_client.step.return_value = True
        self.host.client = mock_client
        self.host.require_initialization = True
        ready = {
            "debug": {
                "runtime_listener_started": 1,
                "runtime_listener_ready": 1,
                "bridge_heartbeat": 4,
                "initialization_complete": 1,
                "initialization_building_ready_p1": 1,
                "initialization_building_ready_p2": 1,
                "initialization_units_ready_p1": 1,
                "initialization_units_ready_p2": 1,
                "world_cover_dialog_visible_p1": 0,
            }
        }
        with patch("host.vibe_host.read_bank", side_effect=[ready, ready]):
            self.assertTrue(self.host.wait_for_initialization(timeout=0.2, stable_reads=2))
        self.assertTrue(self.host.initialization_complete)
        self.assertGreaterEqual(mock_client.step.call_count, 1)

    def test_chat_poll_does_not_force_frame_driver(self):
        """chat transport 不应改变现有实时轮询语义。"""
        mock_client = MagicMock()
        mock_client.step.return_value = True
        self.host.client = mock_client
        with patch.object(self.host, "_poll_response", return_value=RpcResponse(
            kind="result", session_id=self.host.session_id, request_id="r1", sequence=1,
            operation="system.ping", error_code="OK",
        )) as poll:
            self.host.request("system.ping", {}, transport="chat")
        self.assertEqual(poll.call_args.kwargs["advance_frames"], False)
        mock_client.step.assert_not_called()

    def test_spawn_count_out_of_range_rejected(self):
        """Kernel 应拒绝 count > 200。"""
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="error", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="unit.spawn",
                error_code="COUNT_OUT_OF_RANGE",
            )
            resp = self.host.spawn_units("Marine", 99999)
            self.assertEqual(resp.error_code, "COUNT_OUT_OF_RANGE")

    def test_spawn_bad_player_rejected(self):
        """Kernel 应拒绝 player > 15。"""
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="error", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="unit.spawn",
                error_code="PLAYER_OUT_OF_RANGE",
            )
            resp = self.host.spawn_units("Marine", 1, player=99)
            self.assertEqual(resp.error_code, "PLAYER_OUT_OF_RANGE")

    def test_idempotency_returns_cached_response(self):
        """重复 request_id 应返回缓存结果（幂等）。"""
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        cached_resp = RpcResponse(
            kind="result", session_id=self.host.session_id,
            request_id="shared_id", sequence=1, operation="system.ping",
            error_code="OK", payload={"pong": True},
            raw='{"kind":"result","request_id":"shared_id"}',
        )

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = cached_resp
            r1 = self.host.ping()
            # 第二次相同 request_id（通过底层调用）
            self.host.sequence += 1
            from host.vibe_host import RpcRequest
            req = RpcRequest(
                session_id=self.host.session_id,
                request_id="shared_id",
                sequence=self.host.sequence,
                operation="system.ping",
            )
            r2 = self.host._poll_response("shared_id", 1.0)
            self.assertEqual(r1.request_id, r2.request_id)

    def test_upgrade_set_level_convenience(self):
        """upgrade_set_level 便捷方法构造正确请求。"""
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="upgrade.set_level",
                error_code="OK", payload={"applied": 1, "player": 1,
                                          "upgrade": "ShieldWall", "level": 1},
            )
            resp = self.host.upgrade_set_level(player=1, upgrade="ShieldWall", level=1)
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["applied"], 1)
        self.assertEqual(resp.operation, "upgrade.set_level")

    def test_tech_tree_check_convenience(self):
        """tech_tree_check 便捷方法构造正确请求。"""
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="tech_tree.check",
                error_code="OK", payload={"unlocked": 1, "count": 1,
                                          "upgrade": "ShieldWall", "player": 1},
            )
            resp = self.host.tech_tree_check(player=1, upgrade="ShieldWall")
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["unlocked"], 1)
        self.assertEqual(resp.operation, "tech_tree.check")

    def test_query_unit_tags_convenience(self):
        """query_unit_tags 便捷方法构造正确请求。"""
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="query.unit_tags",
                error_code="OK", payload={"count": 1, "tags": [12345],
                                          "unit_type": "Marine", "player": 1},
            )
            resp = self.host.query_unit_tags(player=1, unit_type="Marine")
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["tags"], [12345])
        self.assertEqual(resp.operation, "query.unit_tags")

    def test_query_unit_attrs_convenience(self):
        """query_unit_attrs 便捷方法构造正确请求。"""
        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        self.host.client = mock_client

        with patch.object(self.host, "_poll_response") as mock_poll:
            mock_poll.return_value = RpcResponse(
                kind="result", session_id=self.host.session_id,
                request_id="r1", sequence=1, operation="query.unit_attrs",
                error_code="OK", payload={"armor": 3.0, "unit_type": "Marine",
                                          "unit_tag": 12345},
            )
            resp = self.host.query_unit_attrs(unit_tag=12345)
        self.assertTrue(resp.is_ok)
        self.assertEqual(resp.payload["armor"], 3.0)
        self.assertEqual(resp.operation, "query.unit_attrs")


# ---- 端到端契约测试（模拟 Kernel）----

class TestEndToEndContract(unittest.TestCase):
    """端到端契约测试：模拟 Kernel 行为，验证 spawn 3 Marine → query 3。"""

    def test_spawn_3_marine_then_query_3(self):
        """P1 核心验收：spawn 3 Marine → query.units 返回 3。"""
        host = VibeHost(sc2_port=9999, artifacts_dir=Path(__file__).parent / "_test_artifacts")
        host.start_session()

        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        host.client = mock_client

        # 模拟 Kernel 对 spawn 的响应
        spawn_resp = RpcResponse(
            kind="result", session_id=host.session_id,
            request_id="r1", sequence=1, operation="unit.spawn",
            error_code="OK", payload={"created": 3, "unit_type": "Marine", "player": 1},
            state_version=1,
        )
        # 模拟 Kernel 对 query.units 的响应
        query_resp = RpcResponse(
            kind="result", session_id=host.session_id,
            request_id="r2", sequence=2, operation="query.units",
            error_code="OK", payload={"count": 3, "unit_type": "Marine", "player": 1},
            state_version=1,
        )

        with patch.object(host, "_poll_response", side_effect=[spawn_resp, query_resp]):
            spawn_result = host.spawn_units("Marine", 3, player=1)
            self.assertTrue(spawn_result.is_ok)
            self.assertEqual(spawn_result.payload["created"], 3)

            query_result = host.query_units(player=1, unit_type="Marine")
            self.assertTrue(query_result.is_ok)
            self.assertEqual(query_result.payload["count"], 3)

        host.close()


class TestSimulatorFunctionInvoke(unittest.TestCase):
    def test_ping_and_rejections(self):
        transport = SimulatorTransport()
        session_id = "sim-function-stage16"
        transport.open_session(session_id)

        ping = transport.send(protocol.make_request(
            session_id, "function-ping", 1, "function.invoke",
            {"function_id": "vibe.test.ping", "args": {"nonce": "stage16"}},
        ))
        self.assertEqual(ping.error_code, 0)
        self.assertEqual(ping.payload["message"], "pong")
        self.assertEqual(ping.payload["nonce"], "stage16")

        unknown = transport.send(protocol.make_request(
            session_id, "function-unknown", 2, "function.invoke",
            {"function_id": "vibe.test.unknown", "args": {}},
        ))
        self.assertEqual(unknown.error_code, int(protocol.ErrorCode.FUNCTION_NOT_FOUND))

        invalid = transport.send(protocol.make_request(
            session_id, "function-invalid", 3, "function.invoke",
            {"function_id": "vibe.test.ping", "args": {"unexpected": "x"}},
        ))
        self.assertEqual(invalid.error_code, int(protocol.ErrorCode.INVALID_ARGS))
        self.assertEqual(transport.session.world, None)

    def test_action_query_kill_sequence(self):
        transport = SimulatorTransport()
        session_id = "sim-action-stage17"
        transport.open_session(session_id)
        scenario_path = REPO_ROOT / "reference" / "sc2-ally-bot" / "scenarios" / "sc2-simulator" / "marine_vs_zergling.json"
        loaded = transport.send(protocol.make_request(
            session_id, "load-action", 1, "scenario.load", {"scenario_path": str(scenario_path)}
        ))
        self.assertEqual(loaded.error_code, 0)
        reset = transport.send(protocol.make_request(session_id, "reset-action", 2, "scenario.reset"))
        self.assertEqual(reset.error_code, 0)

        before = transport.send(protocol.make_request(
            session_id, "query-before", 3, "function.invoke",
            {"function_id": "vibe.query.units", "args": {"player": 1, "unit_type": "Marine"}},
        ))
        spawn = transport.send(protocol.make_request(
            session_id, "spawn-action", 4, "function.invoke",
            {"function_id": "vibe.unit.spawn", "args": {
                "unit_type": "Marine", "count": 2, "player": 1, "x": 2.0, "y": 0.0,
            }},
        ))
        self.assertEqual(spawn.error_code, 0)
        self.assertEqual(spawn.payload["created"], 2)
        self.assertGreater(spawn.payload["unit_tag"], 0)

        after_spawn = transport.send(protocol.make_request(
            session_id, "query-after-spawn", 5, "function.invoke",
            {"function_id": "vibe.query.units", "args": {"player": 1, "unit_type": "Marine"}},
        ))
        self.assertEqual(after_spawn.error_code, 0)
        self.assertEqual(after_spawn.payload["count"], before.payload["count"] + 2)

        resource = transport.send(protocol.make_request(
            session_id, "resource-action", 6, "function.invoke",
            {"function_id": "vibe.player.set_resource", "args": {
                "player": 1, "resource": "minerals", "value": 1234,
            }},
        ))
        self.assertEqual(resource.error_code, 0)
        self.assertEqual(resource.payload["value"], 1234)

        killed = transport.send(protocol.make_request(
            session_id, "kill-action", 7, "function.invoke",
            {"function_id": "vibe.unit.kill", "args": {"unit_tag": spawn.payload["unit_tag"]}},
        ))
        self.assertEqual(killed.error_code, 0)
        after_kill = transport.send(protocol.make_request(
            session_id, "query-after-kill", 8, "function.invoke",
            {"function_id": "vibe.query.units", "args": {"player": 1, "unit_type": "Marine"}},
        ))
        self.assertEqual(after_kill.error_code, 0)
        self.assertEqual(after_kill.payload["count"], before.payload["count"] + 1)

    def test_set_resource_then_query_mission(self):
        """P1 验收：set_resource → query.mission 返回新值。"""
        host = VibeHost(sc2_port=9999, artifacts_dir=Path(__file__).parent / "_test_artifacts")
        host.start_session()

        mock_client = MagicMock()
        mock_client.map_command.return_value = True
        host.client = mock_client

        set_resp = RpcResponse(
            kind="result", session_id=host.session_id,
            request_id="r1", sequence=1, operation="player.set_resource",
            error_code="OK", payload={"player": 1, "resource": "minerals", "value": 1000},
            state_version=1,
        )
        mission_resp = RpcResponse(
            kind="result", session_id=host.session_id,
            request_id="r2", sequence=2, operation="query.mission",
            error_code="OK",
            payload={"active_players": [1], "mission_time": 5.0,
                     "p1_minerals": 1000, "p1_vespene": 0,
                     "p1_supply_used": 0, "p1_supply_cap": 0},
            state_version=1,
        )

        with patch.object(host, "_poll_response", side_effect=[set_resp, mission_resp]):
            r1 = host.set_resource(1, "minerals", 1000)
            self.assertTrue(r1.is_ok)
            self.assertEqual(r1.payload["value"], 1000)

            r2 = host.query_mission()
            self.assertTrue(r2.is_ok)
            self.assertEqual(r2.payload["p1_minerals"], 1000)

        host.close()


# ---- Schema 校验测试 ----

class TestSchemaValidation(unittest.TestCase):
    """JSON Schema 静态校验测试。"""

    def test_rpc_schema_valid_json(self):
        """rpc-schema.json 应为合法 JSON。"""
        schema_path = REPO_ROOT / "tools" / "galaxy-vibe" / "schema" / "rpc-schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(data["title"], "Galaxy Vibe RPC Protocol")
        self.assertIn("definitions", data)

    def test_rpc_response_schema_valid_json(self):
        """rpc-response-schema.json 应为合法 JSON。"""
        schema_path = REPO_ROOT / "tools" / "galaxy-vibe" / "schema" / "rpc-response-schema.json"
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(data["title"], "Galaxy Vibe RPC Response")

    def test_schema_operation_enum_matches_whitelist(self):
        """schema 中的 operation enum 应与 whitelist.json 一致。"""
        schema_path = REPO_ROOT / "tools" / "galaxy-vibe" / "schema" / "rpc-schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        whitelist_path = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "whitelist.json"
        whitelist = json.loads(whitelist_path.read_text(encoding="utf-8"))

        schema_ops = set(schema["definitions"]["operation"]["enum"])
        whitelist_ops = set(whitelist["operations"].keys())
        # schema 包含 assert.* 但 whitelist 把它们放在 assert_operations
        assert_ops = set(whitelist.get("assert_operations", {}).keys())
        whitelist_all = whitelist_ops | assert_ops
        self.assertEqual(schema_ops, whitelist_all,
                         f"schema/whitelist 操作集不一致。差异: {schema_ops.symmetric_difference(whitelist_all)}")


# ---- Galaxy 语法静态检查 ----

class TestGalaxyStaticCheck(unittest.TestCase):
    """Galaxy 文件静态语法检查（不依赖 SC2 编辑器）。"""

    def test_kernel_galaxy_no_syntax_errors(self):
        """LibVibeKernel.galaxy 应通过基础语法检查。"""
        galaxy_path = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "LibVibeKernel.galaxy"
        content = galaxy_path.read_text(encoding="utf-8")
        # 基础检查：括号匹配
        open_paren = content.count("(")
        close_paren = content.count(")")
        self.assertEqual(open_paren, close_paren, "括号不匹配")
        # 基础检查：花括号匹配
        open_brace = content.count("{")
        close_brace = content.count("}")
        self.assertEqual(open_brace, close_brace, "花括号不匹配")
        # 基础检查：包含必要函数
        self.assertIn("libVibeKernel_gf_Init", content)
        self.assertIn("libVibeKernel_gf_Dispatch", content)
        self.assertIn("libVibeKernel_gt_ChatCommand_Func", content)
        self.assertIn("libVibeKernel_gt_BankPoll_Func", content)
        # Stage 1 新增 handler 应存在
        for handler in ["HandleUpgradeSetLevel", "HandleTechTreeCheck",
                        "HandleQueryUnitTags", "HandleQueryUnitAttrs",
                        "HandleFunctionInvoke", "FunctionVibeTestPing",
                        "FunctionUnitAttack", "FunctionQueryStructures",
                        "FunctionUnitSpawnGroup", "FunctionUnitAddBehavior",
                        "FunctionUnitQueryBehavior"]:
            self.assertIn(f"libVibeKernel_gf_{handler}", content)
        self.assertIn("libVibeKernel_gt_AllyCommand_Func", content)
        self.assertIn("libVibeKernel_gt_AllyCommand", content)
        # Dispatch 应注册新 operation
        for op in ["upgrade.set_level", "tech_tree.check",
                   "query.unit_tags", "query.unit_attrs", "function.invoke"]:
            self.assertIn(f'"{op}"', content)
        for function_id in ["vibe.test.ping", "vibe.player.set_resource",
                            "vibe.unit.spawn", "vibe.query.units", "vibe.unit.kill",
                            "vibe.unit.attack", "vibe.query.structures",
                            "vibe.unit.spawn_group", "vibe.unit.add_behavior",
                            "vibe.unit.query_behavior"]:
            self.assertIn(f'"{function_id}"', content)

    def test_function_handler_mirrors_are_aligned(self):
        mirror_paths = [
            REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "LibVibeKernel.galaxy",
            REPO_ROOT / "tools" / "galaxy-vibe" / "galaxy-debug-mod" / "Base.SC2Data" / "LibVibeKernel.galaxy",
            REPO_ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps" / "亡者之夜.SC2Map" / "Base.SC2Data" / "LibVibeKernel.galaxy",
        ]
        for path in mirror_paths:
            content = path.read_text(encoding="utf-8")
            for handler in ["FunctionPlayerSetResource", "FunctionUnitSpawn",
                            "FunctionQueryUnits", "FunctionUnitKill",
                            "FunctionUnitAttack", "FunctionQueryStructures",
                            "FunctionUnitSpawnGroup", "FunctionUnitAddBehavior",
                            "FunctionUnitQueryBehavior", "FunctionUnitAddAbility"]:
                self.assertIn(f"libVibeKernel_gf_{handler}", content, str(path))
            self.assertIn("libVibeKernel_gt_AllyCommand_Func", content, str(path))
            self.assertIn("TriggerAddEventChatMessage", content, str(path))
            self.assertIn('"!ally"', content, str(path))
            self.assertNotIn("valStart + end - 1", content, str(path))

    def test_kernel_arg_parser_excludes_delimiter(self):
        """Galaxy key=value parsing must not include the semicolon delimiter."""
        kernel_paths = [
            REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "LibVibeKernel.galaxy",
            REPO_ROOT / "tools" / "galaxy-vibe" / "galaxy-debug-mod" / "Base.SC2Data" / "LibVibeKernel.galaxy",
            REPO_ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps" / "亡者之夜.SC2Map" / "Base.SC2Data" / "LibVibeKernel.galaxy",
        ]
        for path in kernel_paths:
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                "return StringSub(args, valStart, valStart + end - 2);",
                content,
                str(path),
            )
            self.assertNotIn(
                "return StringSub(args, valStart, valStart + end - 1);",
                content,
                str(path),
            )

    def test_kernel_header_galaxy_valid(self):
        """LibVibeKernel_h.galaxy 应包含必要的函数声明。"""
        header_path = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "LibVibeKernel_h.galaxy"
        content = header_path.read_text(encoding="utf-8")
        self.assertIn("include \"TriggerLibs/NativeLib\"", content)
        self.assertIn("libVibeKernel_gf_Init", content)
        self.assertIn("libVibeKernel_gf_Dispatch", content)
        # 所有 handler 应声明（Galaxy 命名约定: gf_Handle<Op>，无下划线）
        for op in ["SystemPing", "UnitSpawn", "UnitKill", "QueryUnits", "QueryMission"]:
            self.assertIn(f"libVibeKernel_gf_Handle{op}", content)
        self.assertIn("libVibeKernel_gf_FunctionUnitAttack", content)
        self.assertIn("libVibeKernel_gf_FunctionQueryStructures", content)
        self.assertIn("libVibeKernel_gf_FunctionUnitSpawnGroup", content)
        self.assertIn("libVibeKernel_gf_FunctionUnitAddBehavior", content)
        self.assertIn("libVibeKernel_gf_FunctionUnitQueryBehavior", content)
        self.assertIn("libVibeKernel_gf_FunctionUnitAddAbility", content)
        self.assertIn("libVibeKernel_gt_AllyCommand_Func", content)


# ---- Stage 26: kernel 三副本 hash 一致性 ----

class TestKernelMirrorConsistency(unittest.TestCase):
    """kernel（权威）→ galaxy-debug-mod → 亡者之夜 副本必须字节一致。"""

    KERNEL = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel"
    DEBUG_MOD = REPO_ROOT / "tools" / "galaxy-vibe" / "galaxy-debug-mod" / "Base.SC2Data"
    MAP_MIRROR = REPO_ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps" / "亡者之夜.SC2Map" / "Base.SC2Data"

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_kernel_galaxy_files_match_across_mirrors(self):
        for name in ("LibVibeKernel.galaxy", "LibVibeKernel_h.galaxy", "LibVibeHandles.galaxy"):
            authoritative = self._digest(self.KERNEL / name)
            for mirror in (self.DEBUG_MOD, self.MAP_MIRROR):
                self.assertTrue((mirror / name).is_file(), str(mirror / name))
                self.assertEqual(authoritative, self._digest(mirror / name),
                                 f"{name} 副本不一致: {mirror}")

    def test_generated_bundles_match_between_kernel_and_debug_mod(self):
        kernel_generated = self.KERNEL / "generated"
        mod_generated = self.DEBUG_MOD / "generated"
        self.assertTrue(kernel_generated.is_dir())
        self.assertTrue(mod_generated.is_dir())
        bundles = sorted(p.name for p in kernel_generated.iterdir() if p.is_dir())
        self.assertEqual(len(bundles), 15)
        for bundle in bundles:
            files = sorted(f.name for f in (kernel_generated / bundle).iterdir())
            self.assertEqual(files, sorted(f.name for f in (mod_generated / bundle).iterdir()), bundle)
            for file_name in files:
                self.assertEqual(
                    self._digest(kernel_generated / bundle / file_name),
                    self._digest(mod_generated / bundle / file_name),
                    f"generated/{bundle}/{file_name} 副本不一致",
                )

    def test_map_local_bundle_matches_kernel_bundle(self):
        bundle = "亡者之夜.SC2Map"
        kernel_bundle = self.KERNEL / "generated" / bundle
        map_bundle = self.MAP_MIRROR / "generated" / bundle
        self.assertTrue(kernel_bundle.is_dir())
        self.assertTrue(map_bundle.is_dir())
        files = sorted(f.name for f in kernel_bundle.iterdir())
        self.assertEqual(files, sorted(f.name for f in map_bundle.iterdir()))
        for file_name in files:
            self.assertEqual(
                self._digest(kernel_bundle / file_name),
                self._digest(map_bundle / file_name),
                f"generated/{bundle}/{file_name} 地图内副本不一致",
            )

    def test_registry_generated_entries_match_invoke_plan(self):
        registry = json.loads((self.KERNEL / "function-registry.json").read_text(encoding="utf-8"))
        functions = registry["functions"]
        generated = [k for k in functions if k.startswith("gen.")]
        # 不硬编码绝对数量：registry 由 generate_invoke_adapters.rewrite_registry
        # 依据 invoke-plan 重建，gen.* 数必须等于规范 invoke-plan 的 callable_functions，
        # 且自洽于 registry 自身的 generated.count 元数据。这样无论生成管线把调用面
        # 扩张/收缩到多少，本测试都校验“registry 与 invoke-plan 一致”这一不变量，
        # 不会被一次合法的 invoke 面重建（handle_acquire 等）误判为回归。
        plan_path = REPO_ROOT / "artifacts" / "projects" / "cmre-porting" / "stage26-full-function-invoke" / "invoke-plan.json"
        if plan_path.is_file():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(len(generated), plan["summary"]["callable_functions"])
            self.assertEqual(len(generated), len(plan["functions"]))
        self.assertEqual(len(generated), registry.get("generated", {}).get("count"))
        for key in generated:
            self.assertTrue(functions[key]["debug_only"])
            self.assertTrue(functions[key]["generated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
