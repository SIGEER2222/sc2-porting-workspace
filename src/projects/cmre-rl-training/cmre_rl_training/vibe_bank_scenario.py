"""vibe_bank_scenario — 用 Vibe Bank RPC 在 gen 图上搭 RL episode 场景（route B）。

为什么需要它
------------
route B 拍板（2026-08-09）：RL 环境从移植图 `亡者之夜_live_packed.SC2Map` 切到已
live-green 的 gen 图 `VibeDeadOfNight-Gen.SC2Map`。移植图完整保留 CMRE launcher +
战役触发器栈、**从未真正开局**（内核注册标记写在 init 首个 `Wait` 之前所以有，
PollLoop 依赖 `Wait` 后游戏钟推进所以死）——「RPC 全 timeout」与「阵营未初始化
own=1/minerals=0/enemy=0」是同一根因的两个表征。gen 图已剥离触发器栈、立即真 in_game，
代价是**玩家开局什么都没有**，raw API 无兵可指挥（`no_own_units`）。

所以分工是明确的：

  · 本模块（Bank RPC）＝ **episode 级建场**：凭空造兵、摆敌我、设血量。
    raw API 做不到这些（它只能指挥已存在的单位）。
  · `live_sc2_session.LiveRawSc2Session`（SC2 raw API）＝ **step 级控制/观测**。
    Bank 通道有损且慢（单次 RPC 秒级、需 at-least-once 重发），绝不能当每步动作面。

铁律
----
· VIBE_KERNEL_003：Bank handle 绝不跨帧缓存，每次重新读盘。
· VIBE_GEN_007：Bank 通道有损（Host 与 Galaxy 都全量覆盖写、无锁），请求可能在
  内核 `ReloadBank()` 与 `BankSave()` 之间被整份抹掉。故所有调用都是 at-least-once：
  请求从盘上消失且仍无 response 就用**同一个 rid** 重发，内核靠 `lastPolledRequestId`
  去重，重复投递语义安全。
· **VIBE_BANK_008（step 模式必须泵时钟）**：内核 PollLoop 是 Galaxy 触发器，只在
  游戏钟推进时拿到执行片。raw API `realtime=False`（RL 要的确定性步进模式）下，
  不调 `RequestStep` 游戏钟就**根本不走**——此时 Bank 里永远不会出现注册标记，
  也永远不会有 response，表现成「0 ScriptError 但 RPC 全 timeout」，极易被误判成
  「地图没加载」或「内核编译失败」。故 step 模式下每一次 Bank 等待循环都必须带
  `pump` 回调推进游戏钟。realtime=True 时游戏钟自走，pump 传 None 即可。
· **VIBE_BANK_009（gen 图没有敌我关系，必须显式建交）**：gen 图剥离了触发器栈才换来
  「立即真 in_game」，但 melee 的**敌对关系初始化也一并被剥掉了**——玩家2 对玩家1
  默认是「盟友」。表现极具欺骗性：Bank `query.units` 数得出敌方单位（造得出）、
  raw obs 里也看得见（不是迷雾问题），但它们落在 `visible_allies` 而不是
  `visible_enemies`，`alliance` 字段是 2(Ally) 不是 4(Enemy)，攻击指令会被引擎拒。
  所以 `build()` 必须先建交再 spawn。手段是 generated-invoke `libCOTF_gf_ClearAlliance`
  （把两个玩家之间 10 个 alliance 位全部清 false = 互为敌人），**双向各调一次**。
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "VibeBankError",
    "UnitPlacement",
    "ScenarioSpec",
    "VibeBankScenario",
    "DEFAULT_SCENARIO",
    "resolve_gen_function_id",
]

REG_MARKERS = ("kernel_initialized", "register_entrypoints_done")
DEFAULT_BANK_NAME = "GalaxyVibe"

# 见 VIBE_BANK_009。把 A 对 B 的全部 alliance 位清 false，双向调用即互为敌人。
CLEAR_ALLIANCE_GALAXY_NAME = "libCOTF_gf_ClearAlliance"
# 兜底编号：registry 读不到时才用。写死编号会随重新生成漂移，故优先按 galaxy_name 反查。
CLEAR_ALLIANCE_FALLBACK_ID = "gen.9744"


def resolve_gen_function_id(
    galaxy_name: str,
    fallback: str,
    *,
    registry_path: Path | None = None,
) -> tuple[str, str]:
    """按 Galaxy 函数名从 function-registry 反查 `gen.<n>` 编号。

    为什么不直接写死编号：gen 适配器编号是**生成产物**，依赖集一变就整体漂移。
    写死编号的失效方式极其阴险——编号仍然合法、调用仍然返回 OK，只是打到了
    另一个函数上，静默改错了游戏状态。按名字反查则要么命中要么显式退化。

    返回 `(function_id, source)`，source ∈ {registry, fallback:<reason>}。
    """

    if registry_path is None:
        registry_path = (Path(__file__).resolve().parents[4]
                         / "tools" / "galaxy-vibe" / "kernel"
                         / "function-registry.json")
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        functions = data.get("functions") or {}
    except (OSError, ValueError) as exc:
        return fallback, f"fallback:registry-unreadable:{type(exc).__name__}"
    hits = [op for op, meta in functions.items()
            if isinstance(meta, Mapping) and meta.get("galaxy_name") == galaxy_name]
    if len(hits) == 1:
        return hits[0], "registry"
    if not hits:
        return fallback, "fallback:not-in-registry"
    return fallback, f"fallback:ambiguous:{len(hits)}"


class VibeBankError(RuntimeError):
    """Bank RPC 通道故障（未注册 / 超时 / 写盘失败）。"""


def _load_host_api() -> Any:
    """延迟导入 galaxy-vibe host 层，避免 import 期就绑死仓库布局。"""

    repo_root = Path(__file__).resolve().parents[4]
    vibe_root = repo_root / "tools" / "galaxy-vibe"
    if not vibe_root.is_dir():  # pragma: no cover - 布局漂移时显式失败
        raise VibeBankError(f"galaxy-vibe tools not found at {vibe_root}")
    if str(vibe_root) not in sys.path:
        sys.path.insert(0, str(vibe_root))
    from host.vibe_host import (  # noqa: PLC0415
        DEFAULT_BANK_DIR,
        RpcRequest,
        bank_request_landed,
        read_bank,
        write_bank_request,
    )

    return {
        "read_bank": read_bank,
        "write_bank_request": write_bank_request,
        "bank_request_landed": bank_request_landed,
        "RpcRequest": RpcRequest,
        "DEFAULT_BANK_DIR": DEFAULT_BANK_DIR,
    }


@dataclass(frozen=True)
class UnitPlacement:
    """一批同类单位的落点。"""

    unit_type: str
    count: int
    x: float
    y: float
    player: int = 1

    def as_args(self) -> dict[str, str]:
        return {
            "count": str(int(self.count)),
            "player": str(int(self.player)),
            "unit_type": str(self.unit_type),
            "x": str(float(self.x)),
            "y": str(float(self.y)),
        }


@dataclass(frozen=True)
class ScenarioSpec:
    """一个可复现的 episode 起始场景。

    `name` 进 evidence，`placements` 顺序即 spawn 顺序（确定性，便于回放对齐）。
    """

    name: str
    placements: Sequence[UnitPlacement] = field(default_factory=tuple)
    # 空 = 由 placements 里出现过的玩家自动推导出全部无序对（见 hostile_pairs()）。
    # 显式给值只在需要"三方里某两方保持中立"这类场景时才用。
    hostile_pairs: Sequence[tuple[int, int]] = field(default_factory=tuple)

    def own_units(self, player: int = 1) -> int:
        return sum(p.count for p in self.placements if p.player == player)

    def enemy_units(self, player: int = 1) -> int:
        return sum(p.count for p in self.placements if p.player != player)

    def players(self) -> tuple[int, ...]:
        """placements 中出现过的玩家，按首次出现顺序去重（保持确定性）。"""

        seen: list[int] = []
        for placement in self.placements:
            if placement.player not in seen:
                seen.append(placement.player)
        return tuple(seen)

    def resolved_hostile_pairs(self) -> tuple[tuple[int, int], ...]:
        """要建立敌对的玩家对（见 VIBE_BANK_009）。

        默认「场上任意两个不同玩家互为敌人」——RL 对抗场景里这就是想要的语义，
        而且比默认盟友安全得多：漏建交会让 episode 静默退化成「双方站着不打」，
        reward 全 0 却看不出任何报错。
        """

        if self.hostile_pairs:
            return tuple((int(a), int(b)) for a, b in self.hostile_pairs)
        players = self.players()
        return tuple((players[i], players[j])
                     for i in range(len(players))
                     for j in range(i + 1, len(players)))


# 默认小规模对抗场景：己方 4 Marine vs 敌方 2 Marine，间隔 8 格，
# 足够产生接战/走位/损失，又不至于一帧内打完导致 reward 信号退化成常数。
DEFAULT_SCENARIO = ScenarioSpec(
    name="skirmish-4v2-marines",
    placements=(
        UnitPlacement("Marine", 4, 10.0, 10.0, player=1),
        UnitPlacement("Marine", 2, 18.0, 10.0, player=2),
    ),
)


class VibeBankScenario:
    """gen 图上的 episode 建场器（同步接口，可直接嵌进 RL env.reset）。"""

    def __init__(
        self,
        *,
        bank_name: str = DEFAULT_BANK_NAME,
        session_id: str = "rl_scenario",
        default_timeout: float = 15.0,
        reassert_seconds: float = 2.0,
        poll_interval: float = 0.1,
        pump: Callable[[], None] | None = None,
        max_pump_failures: int = 5,
    ) -> None:
        api = _load_host_api()
        self._read_bank = api["read_bank"]
        self._write_bank_request = api["write_bank_request"]
        self._bank_request_landed = api["bank_request_landed"]
        self._RpcRequest = api["RpcRequest"]
        self._bank_dir = api["DEFAULT_BANK_DIR"]
        self.bank_name = bank_name
        self.session_id = session_id
        self.default_timeout = float(default_timeout)
        self.reassert_seconds = float(reassert_seconds)
        self.poll_interval = float(poll_interval)
        self._pump = pump
        self._max_pump_failures = int(max_pump_failures)
        self._sequence = 0
        self.stats: dict[str, Any] = {
            "calls": 0, "timeouts": 0, "reasserts": 0,
            "pumps": 0, "pump_failures": 0, "trace": []}

    # ---------------- 游戏钟 ----------------

    def set_pump(self, pump: Callable[[], None] | None) -> None:
        """挂上游戏钟推进回调（见 VIBE_BANK_008）。

        典型用法：`scenario.set_pump(lambda: session.step(step_mul))`。
        realtime=True 的会话不需要它。
        """

        self._pump = pump

    def _tick(self, interval: float) -> None:
        """等待循环的一格：先推进游戏钟，再睡。

        pump 抛错不吞——连续失败超过阈值就抛 `VibeBankError`。若静默忽略，
        会话已断的情况会退化成「等满整个 timeout 再报超时」，把连接故障
        伪装成通道故障，正是最难查的那类误报。
        """

        if self._pump is None:
            time.sleep(interval)
            return
        try:
            self._pump()
            self.stats["pumps"] += 1
            self._pump_failure_streak = 0
        except Exception as exc:  # noqa: BLE001
            self.stats["pump_failures"] += 1
            streak = getattr(self, "_pump_failure_streak", 0) + 1
            self._pump_failure_streak = streak
            if streak >= self._max_pump_failures:
                raise VibeBankError(
                    f"game clock pump failed {streak}x in a row: "
                    f"{type(exc).__name__}: {exc}") from exc
            time.sleep(interval)

    # ---------------- 内核就绪 ----------------

    @property
    def bank_path(self) -> Path:
        return Path(self._bank_dir) / f"{self.bank_name}.SC2Bank"

    def archive_bank(self) -> str | None:
        """把旧 Bank 移走。让 `kernel_initialized` 成为"本次加载确实跑了内核"的
        无歧义证据 —— 它是持久 key，会跨地图加载残留，不清就可能假阳性。"""

        bp = self.bank_path
        if not bp.exists():
            return None
        archived = bp.with_suffix(f".SC2Bank.stale-{int(time.time())}")
        bp.replace(archived)
        return str(archived)

    def wait_for_kernel(self, *, timeout: float = 60.0) -> dict[str, int]:
        """轮询 Bank 注册标记。返回已见到的标记；空 dict 表示内核没起来。"""

        seen: dict[str, int] = {}
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if self.bank_path.exists():
                index = self._read_bank(self.bank_name).get("index", {})
                for marker in REG_MARKERS:
                    value = index.get(marker)
                    if value is not None and str(value).strip() in {"1", "1.0"}:
                        seen[marker] = 1
            if len(seen) == len(REG_MARKERS):
                break
            if seen and time.time() > deadline - 0.5:
                break
            self._tick(self.poll_interval * 2)
        return seen

    # ---------------- RPC ----------------

    def call(
        self,
        operation: str,
        args: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """一次 at-least-once Bank RPC。见模块 docstring 的 VIBE_GEN_007。"""

        timeout = self.default_timeout if timeout is None else float(timeout)
        self._sequence += 1
        rid = (f"rl_{operation.replace('.', '_')}_"
               f"{int(time.time() * 1000)}_{os.getpid()}_{self._sequence}")
        request = self._RpcRequest(
            session_id=self.session_id, request_id=rid, sequence=self._sequence,
            operation=operation, args=dict(args or {}))
        if not self._write_bank_request(self.bank_name, rid, request, player=1):
            raise VibeBankError(f"write_bank_request failed for {operation}")

        started = time.time()
        last_assert = started
        reasserts = 0
        while time.time() - started < timeout:
            raw = self._read_bank(self.bank_name).get("response", {}).get(rid)
            if raw:
                self.stats["calls"] += 1
                self.stats["reasserts"] += reasserts
                record = {"operation": operation, "rid": rid, "ok": True,
                          "latency": round(time.time() - started, 3),
                          "reasserts": reasserts}
                self.stats["trace"].append(record)
                return {"ok": True, "raw": raw, "payload": _decode_payload(raw),
                        **record}
            now = time.time()
            if now - last_assert >= self.reassert_seconds:
                last_assert = now
                if not self._bank_request_landed(self.bank_name, rid):
                    self._write_bank_request(self.bank_name, rid, request, player=1)
                    reasserts += 1
            self._tick(self.poll_interval)

        self.stats["calls"] += 1
        self.stats["timeouts"] += 1
        self.stats["reasserts"] += reasserts
        record = {"operation": operation, "rid": rid, "ok": False,
                  "error": "timeout", "reasserts": reasserts}
        self.stats["trace"].append(record)
        return {"ok": False, **record}

    def ping(self, *, timeout: float = 8.0) -> bool:
        result = self.call("system.ping", {}, timeout=timeout)
        return bool(result.get("ok") and '"pong":true' in result.get("raw", ""))

    def spawn(self, placement: UnitPlacement, *,
              timeout: float | None = None) -> dict[str, Any]:
        return self.call("unit.spawn", placement.as_args(), timeout=timeout)

    def query_units(self, *, player: int = 1, unit_type: str = "Marine",
                    timeout: float | None = None,
                    attempts: int = 1) -> dict[str, Any]:
        """查内核侧单位真值（无战争迷雾）。

        `attempts>1` 时对**传输失败**重试。VIBE_BANK_011（2026-08-10 同实例 A/B
        实测，`out/probe_query_player_ab.py`）：Bank 通道有损是固有特性而非缺陷
        —— 12 次交错查询里 p1 6/6、p2 5/6，失败的那次是 timeout，成功时 count
        恒为真值（p1=4 / p2=2）；p1 也出现过 4.3s / 2 reasserts 的抖动。所以
        「单次 timeout」不能推出「单位不存在」，ep-alliance-03 的判据 ④ 就是
        这么被误判红的（raw obs 同时看得见那 2 个敌方 Marine）。

        铁律：**只对传输失败重试，绝不对"读到了但数字不对"重试**。后者是真实
        场景故障，重试等于把校验器自己拆掉（round22 血泪：恒绿的校验器等于
        没有校验器）。因此这里只在 `ok=False` 时再来一次。
        """

        last: dict[str, Any] = {}
        for i in range(max(1, attempts)):
            last = self.call("query.units",
                             {"player": str(player), "unit_type": unit_type},
                             timeout=timeout)
            if last.get("ok"):
                if i:
                    last["transport_retries"] = i
                return last
        last["transport_retries"] = max(1, attempts) - 1
        return last

    # ---------------- generated-invoke ----------------

    def invoke(self, function_id: str, args: Mapping[str, Any] | None = None, *,
               timeout: float | None = None) -> dict[str, Any]:
        """调一个 `gen.<n>` 生成适配器。"""

        result = self.call(
            "function.invoke",
            {"function_id": function_id, "args": dict(args or {})},
            timeout=timeout)
        # Bank 通道「送到了」不等于「函数跑成功了」——内核会把执行结果编码进
        # error_code。只看 ok 会把 INVALID_ARGS 之类当成功，必须拆开看。
        if result.get("ok"):
            try:
                parsed = json.loads(result.get("raw") or "{}")
            except ValueError:
                parsed = {}
            code = parsed.get("error_code")
            result["error_code"] = code
            result["ok"] = (code == "OK")
            if code != "OK":
                result["error"] = f"invoke_error_code={code}"
        return result

    def set_hostile(self, player_a: int, player_b: int, *,
                    timeout: float | None = None) -> dict[str, Any]:
        """让两个玩家互为敌人（见 VIBE_BANK_009）。

        `ClearAlliance` 是**单向**的（只清 source→target 的位），只调一次会造出
        「A 打得了 B、B 打不了 A」的半敌对状态，是比全盟友更难查的坑。故双向各调一次。
        """

        fid, source = self._clear_alliance_id()
        calls = []
        for src, dst in ((player_a, player_b), (player_b, player_a)):
            outcome = self.invoke(fid, {"p0": int(src), "p1": int(dst)},
                                  timeout=timeout)
            calls.append({
                "source": int(src), "target": int(dst),
                "ok": bool(outcome.get("ok")),
                "error_code": outcome.get("error_code"),
                "error": outcome.get("error"),
                "latency": outcome.get("latency"),
            })
        return {
            "ok": all(c["ok"] for c in calls),
            "pair": [int(player_a), int(player_b)],
            "function_id": fid,
            "function_id_source": source,
            "calls": calls,
        }

    def _clear_alliance_id(self) -> tuple[str, str]:
        cached = getattr(self, "_clear_alliance_cache", None)
        if cached is None:
            cached = resolve_gen_function_id(
                CLEAR_ALLIANCE_GALAXY_NAME, CLEAR_ALLIANCE_FALLBACK_ID)
            self._clear_alliance_cache = cached
        return cached

    # ---------------- episode 建场 ----------------

    def build(self, spec: ScenarioSpec = DEFAULT_SCENARIO, *,
              timeout: float | None = None,
              set_alliances: bool = True) -> dict[str, Any]:
        """先建交、再按 spec 顺序 spawn 出整个场景。

        建交放在 spawn 之前：alliance 是玩家级属性、立即生效，先设好就不会有
        「单位出生时是盟友、下一帧才变敌人」的中间态污染首帧观测。

        任一步失败都**不静默跳过** —— 场景残缺会让 reward 悄悄失真，
        比直接失败难查得多。返回 `ok=False` 并带上失败明细，由调用方决定重试或中止。
        """

        alliances: list[dict[str, Any]] = []
        if set_alliances:
            for player_a, player_b in spec.resolved_hostile_pairs():
                alliances.append(self.set_hostile(player_a, player_b,
                                                  timeout=timeout))

        results: list[dict[str, Any]] = []
        for placement in spec.placements:
            outcome = self.spawn(placement, timeout=timeout)
            results.append({
                "unit_type": placement.unit_type, "count": placement.count,
                "player": placement.player, "x": placement.x, "y": placement.y,
                "ok": bool(outcome.get("ok")),
                "latency": outcome.get("latency"),
                "reasserts": outcome.get("reasserts"),
                "error": outcome.get("error"),
            })
        failed = [r for r in results if not r["ok"]]
        failed_alliances = [a for a in alliances if not a["ok"]]
        return {
            "ok": not failed and not failed_alliances,
            "scenario": spec.name,
            "expected_own": spec.own_units(),
            "expected_enemy": spec.enemy_units(),
            "alliances": alliances,
            "failed_alliances": failed_alliances,
            "placements": results,
            "failed": failed,
        }


def _decode_payload(raw: str) -> Any:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    payload = parsed.get("payload") if isinstance(parsed, dict) else None
    if isinstance(payload, dict) and isinstance(payload.get("value"), str):
        try:
            payload = {**payload, "value": json.loads(payload["value"])}
        except (TypeError, ValueError):
            pass
    return payload
