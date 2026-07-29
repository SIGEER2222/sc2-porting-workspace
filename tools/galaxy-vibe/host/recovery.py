"""Vibe Host 恢复模块 — Host 重启续接 + SC2 重启新 session。

依据 sc2-vibe完整实施计划.md P7 验收:
  - Host 重启可续接（已处理 request_id 不重复执行，pending 请求重发或显式失败）
  - SC2 重启产生新 session_id；旧 session 的请求被 Kernel 显式拒绝

实现策略:
  1. session_state.json 持久化到 artifacts/galaxy-vibe/<run_id>/session_state.json
     字段: session_id, started_at, last_sequence, processed_request_ids[], pending_request_ids[]
  2. 每次 RPC 成功 ack 后追加 processed_request_ids；超时/未确认的进 pending
  3. Host 重启时 load_session_state():
     - 同 session_id 续接：pending 请求重发；新请求用 last_sequence+1
     - SC2 不可达或 Kernel 拒绝旧 session_id → start_new_session()：分配新 session_id，
       显式拒绝旧 session 的 pending 请求（标记 verdict=abandoned）
  4. SC2 重启检测：ping 失败 N 次或 Kernel 返回 error_code=session_expired

调用方式:
  from recovery import SessionState, RecoveryManager
  mgr = RecoveryManager(state_dir)
  state = mgr.load_or_create(session_id=None)
  mgr.mark_processed(request_id)
  mgr.mark_pending(request_id)
  if sc2_unreachable:
      mgr.start_new_session(reason="sc2_restart")
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


SESSION_STATE_FILENAME = "session_state.json"
PROCESSED_LOG_FILENAME = "processed_requests.jsonl"
PENDING_LOG_FILENAME = "pending_requests.jsonl"


@dataclass
class SessionState:
    """持久化的 session 状态。"""
    session_id: str
    started_at: str
    last_sequence: int = 0
    processed_request_ids: list[str] = field(default_factory=list)
    pending_request_ids: list[str] = field(default_factory=list)
    abandoned_request_ids: list[str] = field(default_factory=list)
    sc2_restart_count: int = 0
    host_restart_count: int = 0
    last_active_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["last_active_at"] = d.get("last_active_at") or self.started_at
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        return cls(
            session_id=data["session_id"],
            started_at=data["started_at"],
            last_sequence=data.get("last_sequence", 0),
            processed_request_ids=list(data.get("processed_request_ids", [])),
            pending_request_ids=list(data.get("pending_request_ids", [])),
            abandoned_request_ids=list(data.get("abandoned_request_ids", [])),
            sc2_restart_count=data.get("sc2_restart_count", 0),
            host_restart_count=data.get("host_restart_count", 0),
            last_active_at=data.get("last_active_at", data.get("started_at", "")),
        )


class RecoveryManager:
    """管理 Host 重启续接和 SC2 重启新 session 的状态。"""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / SESSION_STATE_FILENAME
        self.processed_log = self.state_dir / PROCESSED_LOG_FILENAME
        self.pending_log = self.state_dir / PENDING_LOG_FILENAME
        self._state: Optional[SessionState] = None

    @property
    def state(self) -> SessionState:
        if self._state is None:
            raise RuntimeError("State not loaded. Call load_or_create() first.")
        return self._state

    def load_or_create(self, session_id: Optional[str] = None) -> SessionState:
        """加载已有状态（用于 Host 续接）或创建新状态。

        - session_id=None 且磁盘无 state：新建 session
        - session_id=None 且磁盘有 state：续接（host_restart_count += 1）
        - session_id=explicit：用指定 session_id 创建新状态
        """
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._state = SessionState.from_dict(data)
                self._state.host_restart_count += 1
                self._state.last_active_at = self._now()
                self._save()
                return self._state
            except (json.JSONDecodeError, KeyError) as e:
                # 状态文件损坏 → 备份并新建
                backup = self.state_path.with_suffix(".json.corrupt")
                try:
                    self.state_path.rename(backup)
                except OSError:
                    pass
                print(f"[recovery] state corrupted, renamed to {backup.name}: {e}")

        # 新建 session
        sid = session_id or self._generate_session_id()
        self._state = SessionState(
            session_id=sid,
            started_at=self._now(),
            last_active_at=self._now(),
        )
        self._save()
        return self._state

    def start_new_session(self, reason: str = "sc2_restart") -> SessionState:
        """SC2 重启或显式要求 → 放弃旧 session，创建新 session。

        旧 session 的 pending 请求标记为 abandoned（不重发，由上层决定如何处理）。
        """
        if self._state is not None:
            self._state.abandoned_request_ids.extend(self._state.pending_request_ids)
            self._state.pending_request_ids.clear()
            self._state.sc2_restart_count += 1
            self._save()

        old_sid = self._state.session_id if self._state else "(none)"
        new_sid = self._generate_session_id()
        self._state = SessionState(
            session_id=new_sid,
            started_at=self._now(),
            last_active_at=self._now(),
            sc2_restart_count=self._state.sc2_restart_count if self._state else 0,
            host_restart_count=self._state.host_restart_count if self._state else 0,
        )
        self._append_pending_log({
            "event": "session_rotated",
            "old_session_id": old_sid,
            "new_session_id": new_sid,
            "reason": reason,
            "ts": self._now(),
        })
        self._save()
        return self._state

    def next_sequence(self) -> int:
        """分配下一个 sequence 编号。"""
        self._state.last_sequence += 1
        self._state.last_active_at = self._now()
        self._save()
        return self._state.last_sequence

    def mark_processed(self, request_id: str, operation: str = "", verdict: str = "") -> None:
        """请求已被 Kernel 处理（ack/result），加入 processed 集合。"""
        if request_id in self._state.pending_request_ids:
            self._state.pending_request_ids.remove(request_id)
        if request_id not in self._state.processed_request_ids:
            self._state.processed_request_ids.append(request_id)
        self._state.last_active_at = self._now()
        self._append_processed_log({
            "request_id": request_id,
            "operation": operation,
            "verdict": verdict,
            "ts": self._now(),
        })
        self._save()

    def mark_pending(self, request_id: str, operation: str = "") -> None:
        """请求已发出但未确认 ack，加入 pending 集合。"""
        if request_id not in self._state.pending_request_ids:
            self._state.pending_request_ids.append(request_id)
        self._state.last_active_at = self._now()
        self._append_pending_log({
            "event": "pending_added",
            "request_id": request_id,
            "operation": operation,
            "ts": self._now(),
        })
        self._save()

    def is_processed(self, request_id: str) -> bool:
        """幂等检查：是否已处理过。"""
        return request_id in self._state.processed_request_ids

    def pending_count(self) -> int:
        return len(self._state.pending_request_ids)

    def summary(self) -> dict:
        """返回恢复摘要，供 evidence bundle 使用。"""
        s = self._state
        return {
            "session_id": s.session_id,
            "started_at": s.started_at,
            "last_active_at": s.last_active_at,
            "last_sequence": s.last_sequence,
            "processed_count": len(s.processed_request_ids),
            "pending_count": len(s.pending_request_ids),
            "abandoned_count": len(s.abandoned_request_ids),
            "sc2_restart_count": s.sc2_restart_count,
            "host_restart_count": s.host_restart_count,
        }

    # ---- 内部 ----

    def _save(self) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def _append_processed_log(self, entry: dict) -> None:
        with open(self.processed_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _append_pending_log(self, entry: dict) -> None:
        with open(self.pending_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())

    @staticmethod
    def _generate_session_id() -> str:
        return f"sess-{uuid.uuid4().hex[:12]}"


def detect_sc2_restart(prev_ping_ok: bool, current_ping_ok: bool, consecutive_failures: int, threshold: int = 3) -> bool:
    """启发式检测 SC2 是否重启。

    触发条件：之前 ping ok，现在连续 N 次 ping 失败。
    """
    if prev_ping_ok and not current_ping_ok and consecutive_failures >= threshold:
        return True
    return False
