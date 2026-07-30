"""Shared Consumer Adapter — P6 共享消费者适配层。

抽取共享 Kernel/Host 后，两个消费者通过此适配层使用同一套框架。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.vibe_host import VibeHost  # noqa: E402
from observer.assertion_runner import AssertionRunner  # noqa: E402


@dataclass
class ConsumerConfig:
    """消费者配置。"""
    consumer_id: str
    map: str
    commander: str
    launcher: str
    recipe: dict[str, Any]

    @classmethod
    def from_json(cls, path: Path) -> "ConsumerConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            consumer_id=data["consumer_id"],
            map=data["map"],
            commander=data["commander"],
            launcher=data["launcher"],
            recipe=data.get("recipe", {}),
        )


class ConsumerAdapter:
    """共享消费者适配器。

    通过 consumer.json 参数化，让同一套 Kernel/Host 服务于不同地图。
    """

    def __init__(self, config: ConsumerConfig, sc2_port: int = 5000):
        self.config = config
        self.host = VibeHost(sc2_port=sc2_port)
        self.runner: Optional[AssertionRunner] = None

    def connect(self) -> bool:
        """连接 SC2。"""
        if not self.host.connect_sc2():
            return False
        self.host.start_session()
        self.runner = AssertionRunner(self.host)
        return True

    def run_recipe(self) -> dict[str, Any]:
        """运行 consumer 的 recipe。"""
        if self.runner is None:
            return {"verdict": "failed", "error": "未连接"}
        return self.runner.run_recipe(self.config.recipe)

    def close(self) -> None:
        self.host.close()


def load_consumer(consumer_dir: str) -> ConsumerConfig:
    """加载消费者配置。"""
    path = REPO_ROOT / "tools" / "galaxy-vibe" / "consumers" / consumer_dir / "consumer.json"
    return ConsumerConfig.from_json(path)
