"""State Observer — P2 状态观察器。

依据 sc2-vibe完整实施计划.md:
  - 输出单位、玩家、任务、资源、位置、生命、行为、订单及场景版本的结构化快照
  - 每条断言可追到 request 和采样时间

通过 VibeHost 发送 query.* 请求采集状态，构建符合 snapshot-schema.json 的快照。
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.vibe_host import VibeHost, RpcResponse  # noqa: E402


@dataclass
class Snapshot:
    """状态快照。"""
    snapshot_id: str
    session_id: str
    request_id: str
    sampled_at: str
    mission_time: float
    state_version: int
    players: list[dict[str, Any]] = field(default_factory=list)
    units: list[dict[str, Any]] = field(default_factory=list)
    unit_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "sampled_at": self.sampled_at,
            "mission_time": self.mission_time,
            "state_version": self.state_version,
            "players": self.players,
            "units": self.units,
            "unit_counts": self.unit_counts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        return cls(
            snapshot_id=data["snapshot_id"],
            session_id=data["session_id"],
            request_id=data.get("request_id", ""),
            sampled_at=data["sampled_at"],
            mission_time=data["mission_time"],
            state_version=data["state_version"],
            players=data.get("players", []),
            units=data.get("units", []),
            unit_counts=data.get("unit_counts", {}),
        )


class StateObserver:
    """状态观察器：通过 VibeHost 采集游戏状态快照。"""

    def __init__(self, host: VibeHost, artifacts_dir: Optional[Path] = None):
        self.host = host
        self.artifacts_dir = artifacts_dir or (REPO_ROOT / "artifacts" / "galaxy-vibe" / "p2-assertion")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots: list[Snapshot] = []

    def capture(self, request_id: str = "") -> Snapshot:
        """采集当前状态快照。"""
        if not request_id:
            request_id = f"snap-{uuid.uuid4().hex[:8]}"

        # 1. 查询任务状态（含所有玩家资源）
        mission_resp = self.host.query_mission()
        mission_data = mission_resp.payload if mission_resp.is_ok else {}

        # 2. 查询所有活跃玩家的单位
        active_players = mission_data.get("active_players", [1])
        unit_counts: dict[str, dict[str, int]] = {}
        units: list[dict[str, Any]] = []

        for pid in active_players:
            # 查询该玩家所有单位（unit_type="" 表示所有）
            units_resp = self.host.query_units(player=pid, unit_type="")
            if units_resp.is_ok:
                count = units_resp.payload.get("count", 0)
                unit_counts[str(pid)] = {"_total": count}
            else:
                unit_counts[str(pid)] = {"_total": 0}

        # 3. 构建玩家信息
        players = []
        for pid in active_players:
            players.append({
                "player_id": pid,
                "active": True,
                "minerals": mission_data.get(f"p{pid}_minerals", 0) if pid == 1 else 0,
                "vespene": mission_data.get(f"p{pid}_vespene", 0) if pid == 1 else 0,
                "supply_used": mission_data.get(f"p{pid}_supply_used", 0) if pid == 1 else 0,
                "supply_cap": mission_data.get(f"p{pid}_supply_cap", 0) if pid == 1 else 0,
            })

        snapshot = Snapshot(
            snapshot_id=f"snap-{uuid.uuid4().hex[:12]}",
            session_id=self.host.session_id,
            request_id=request_id,
            sampled_at=time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            mission_time=mission_data.get("mission_time", 0.0),
            state_version=mission_resp.state_version,
            players=players,
            units=units,
            unit_counts=unit_counts,
        )
        self.snapshots.append(snapshot)
        return snapshot

    def capture_for_request(self, request_id: str) -> Snapshot:
        """为指定 request 采集快照（用于断言追溯）。"""
        return self.capture(request_id=request_id)

    def save_snapshot(self, snapshot: Snapshot) -> Path:
        """保存快照到 artifacts。"""
        path = self.artifacts_dir / f"{snapshot.snapshot_id}.json"
        path.write_text(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def get_field(self, snapshot: Snapshot, path: str) -> Any:
        """从快照中提取字段值（支持点分路径）。"""
        parts = path.split(".")
        current: Any = snapshot.to_dict()
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        return current

    def get_unit_count(self, snapshot: Snapshot, player: int, unit_type: str = "") -> int:
        """获取快照中指定玩家/单位的数量。"""
        pid_str = str(player)
        if pid_str not in snapshot.unit_counts:
            return 0
        if unit_type == "":
            return snapshot.unit_counts[pid_str].get("_total", 0)
        return snapshot.unit_counts[pid_str].get(unit_type, 0)
