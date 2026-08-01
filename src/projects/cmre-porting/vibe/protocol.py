#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 传输闸门 — 类型化 RPC 契约（离线可验核心）。

请求字段：protocol_version / session_id / request_id / sequence / operation / args /
          issued_at / checksum
响应：ack | result | error + 同一 ID + started_at / completed_at / error_code /
      payload / state_version

Kernel 保存当前 session 已处理 request_id：重复请求返回原结果且不重复产生副作用；
过期 session / 乱序 / 未知操作 / 越界参数 / 校验和错误必须显式拒绝。

MVP 操作白名单（仅这些可被 Kernel 执行，绝不提供任意 call FuncName）：
  system.ping, scenario.reset,
  function.invoke,
  unit.spawn / unit.kill / unit.set_vital,
  player.set_resource,
  query.units / query.unit / query.mission,
  visual.actor_tint / visual.actor_scale / visual.actor_opacity,
  assert.exists / assert.count / assert.equals / assert.range / assert.eventually / assert.not_exists

证据分类：本文件是确定性协议逻辑（static 验证）；真机 transport 的 ack/延迟/去重需在桌面 SC2 上实测。
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

PROTOCOL_VERSION = "vibe/1.0"


class ErrorCode(IntEnum):
    OK = 0
    UNKNOWN_OP = 1
    OUT_OF_RANGE = 2
    STALE_SESSION = 3
    OUT_OF_ORDER = 4
    BAD_CHECKSUM = 5
    EXEC_FAILED = 6
    FUNCTION_NOT_FOUND = 7
    INVALID_ARGS = 8


# 首个消费者（cmre-porting）内的预编译白名单；后续消费者可追加，但必须显式登记。
MVP_OPS = {
    "system.ping",
    "function.invoke",
    "scenario.reset",
    "unit.spawn",
    "unit.kill",
    "unit.set_vital",
    "player.set_resource",
    "query.units",
    "query.unit",
    "query.mission",
    "visual.actor_tint",
    "visual.actor_scale",
    "visual.actor_opacity",
    "assert.exists",
    "assert.count",
    "assert.equals",
    "assert.range",
    "assert.eventually",
    "assert.not_exists",
}


@dataclass
class Request:
    protocol_version: str
    session_id: str
    request_id: str
    sequence: int
    operation: str
    args: dict
    issued_at: float
    checksum: str


@dataclass
class Response:
    kind: str  # ack | result | error
    session_id: str
    request_id: str
    sequence: int
    operation: str
    started_at: float = 0.0
    completed_at: float = 0.0
    error_code: int = 0
    payload: dict = field(default_factory=dict)
    state_version: int = 0


def _checksum_source(req: Request) -> str:
    return "|".join(
        [
            req.protocol_version,
            req.session_id,
            req.request_id,
            str(req.sequence),
            req.operation,
            json.dumps(req.args, sort_keys=True),
            str(req.issued_at),
        ]
    )


def compute_checksum(req: Request) -> str:
    return hashlib.sha256(_checksum_source(req).encode("utf-8")).hexdigest()[:16]


def make_request(session_id, request_id, sequence, operation, args=None, issued_at=None) -> Request:
    issued_at = issued_at if issued_at is not None else time.time()
    args = args or {}
    req = Request(
        PROTOCOL_VERSION, session_id, request_id, sequence, operation, args, issued_at, ""
    )
    req.checksum = compute_checksum(req)
    return req


class SessionRegistry:
    """管理 session 与已处理 request_id：幂等 + 拒绝过期/乱序/未知/坏校验和。"""

    def __init__(self):
        self._sessions: dict[str, dict] = {}  # sid -> {last_seq, seen:set, open:bool}

    def open(self, session_id: str) -> None:
        self._sessions[session_id] = {"last_seq": 0, "seen": set(), "open": True}

    def close(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s:
            s["open"] = False

    def is_open(self, session_id: str) -> bool:
        return bool(self._sessions.get(session_id, {}).get("open", False))

    def validate(self, req: Request) -> ErrorCode:
        s = self._sessions.get(req.session_id)
        if s is None or not s["open"]:
            return ErrorCode.STALE_SESSION
        if req.checksum != compute_checksum(req):
            return ErrorCode.BAD_CHECKSUM
        if req.operation not in MVP_OPS:
            return ErrorCode.UNKNOWN_OP
        if req.sequence < s["last_seq"]:
            return ErrorCode.OUT_OF_ORDER
        return ErrorCode.OK

    def mark(self, req: Request) -> None:
        s = self._sessions[req.session_id]
        s["seen"].add(req.request_id)
        if req.sequence > s["last_seq"]:
            s["last_seq"] = req.sequence

    def seen(self, session_id: str, request_id: str) -> bool:
        s = self._sessions.get(session_id)
        return bool(s and request_id in s["seen"])
