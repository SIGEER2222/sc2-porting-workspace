"""RouteBBackend — route B 真机 RL 后端，把 gen 图 Bank RPC 建场接入 ``CmreRLEnv``。

这是 Module 4「接 PPO + 胜负终端」的关键拼图：

  · ``LiveRawSc2Session``（SC2 raw API）＝ step 级控制 / 观测（每步泵时钟 + 下发动作）。
  · ``VibeBankScenario``（Vibe Bank RPC）＝ episode 级建场（凭空造兵、摆敌我、清建交）。
  · 本模块把它们合成一个满足 ``RlBackend`` 协议的 env 后端，并补上**确定性胜负终端**：
    敌方作战单位数 == 0 → victory；己方作战单位数 == 0 → defeat。

为什么需要它
------------
离线 sim 的 ``end_reason`` 恒为 ``''``（仿真不产出胜负终端），导致终端胜负 credit 永远死、
reward 信号退化成常数，PPO 训出来 ≈ 随机（N5 hard 档铁证）。gen 图上的小规模对抗是
**真实会打的战斗**——Marine 互相开火，敌方打光就真的没敌人，于是「敌方全灭」成了
离线 sim 一直缺的那项 terminal，理论上能打破 hard ceiling。

动作接地（action grounding）
---------------------------
PPO 策略只输出 ``action_id``（19 个基本动作之一），不输出目标单位/坐标。gen 图每帧
只有少量单位，本后端负责把动作**接地**成 Bank/raw API 能执行的参数：

  · 复用 route B 已验证的目标选择逻辑（VIBE_BANK_010 修复后）：只挑真战斗单位当
    actor / target，过滤纯数字 ``unit_type_id`` 的地图哑元，取最近目标保证确定性。
  · 建图/产兵等对 gen 图无意义（无经济）的动作，安全退化成「朝最近敌人 attack_move /
    朝默认点 move」，保证 episode 始终在产生战斗、能正常终止，而不是站着不动。

可注入性（测试）
--------------
``session`` / ``scenario`` 可作为构造参数注入，使离线单测能用假后端验证逻辑而不必起 SC2。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .backends import RlBackend

NEUTRAL_OWNER = 9
DEFAULT_MAP = r"C:/tmp/VibeDeadOfNight-Gen.SC2Map"


# --------------------------------------------------------------------------
# 纯函数：单位计数 / 终端判定 / 动作接地
# 这些逻辑从 run_route_b_episode.py 抽出并固化为纯函数，便于离线单测、且与 route B
# 已验证的行为保持一致（VIBE_BANK_010：过滤哑元、取最近目标）。
# --------------------------------------------------------------------------

def _distance2(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    dx = float(a.get("x", 0.0)) - float(b.get("x", 0.0))
    dy = float(a.get("y", 0.0)) - float(b.get("y", 0.0))
    return dx * dx + dy * dy


def is_dummy(unit: Mapping[str, Any]) -> bool:
    """纯数字 ``unit_type_id`` = SC2 没解析出名字 = 地图家具/哑元，不可作战斗单位。"""

    return str(unit.get("unit_type_id", "")).strip().isdigit()


def own_units(obs: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [u for u in (obs.get("own_units") or []) if int(u.get("owner", 0)) == 1]


def enemy_units(
    obs: Mapping[str, Any], enemy_player: int = 2
) -> list[dict[str, Any]]:
    """只认属于场景敌方玩家的单位；中立地形物（owner 9）一律不算。"""

    return [
        u for u in (obs.get("visible_enemies") or obs.get("enemy_units") or [])
        if int(u.get("owner", 0)) == int(enemy_player)
    ]


def combat_actors(obs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """己方真战斗单位（排除哑元）。"""

    return [u for u in own_units(obs) if not is_dummy(u)]


def combat_targets(
    obs: Mapping[str, Any], enemy_player: int = 2
) -> list[dict[str, Any]]:
    """敌方真战斗单位（严格排除哑元，**不回退**）——用于**动作接地**。

    只读 ``visible_enemies``，不把盟友当目标。曾经这里写过 ``return combat or enemies``
    的"宁可打不动"回退，结果是真敌人死光后仍去攻击 (76,103) 那个 4051 哑元，
    raw API 回 ``NotSupported(2)``，白烧步数。没有真目标就该走位，不该乱打。
    """

    return [u for u in enemy_units(obs, enemy_player) if not is_dummy(u)]


def enemy_present(
    obs: Mapping[str, Any], enemy_player: int = 2
) -> list[dict[str, Any]]:
    """敌方玩家的**真战斗单位**——跨 ``visible_enemies`` 与 ``visible_allies`` 两个桶。

    为什么跨两个桶：设了建交后敌方在 ``visible_enemies``；**跳过建交**（反向对照
    ``--no-alliances``）时 gen 图默认双方为盟友，敌方单位落在 ``visible_allies`` 且
    ``owner==enemy_player``。终端判定必须把它们都算上，否则跳过建交会「看不到敌人」→
    误判 victory（反向对照假阴性）。

    为什么**绝不回退**（VIBE_BANK_014，真机实证）：gen 图给每个玩家都挂了一个
    ``unit_type_id=="4051"`` 的地图哑元（owner=2 那个在 (76,103)）。首版抄了
    ``combat_targets`` 的 ``return combat or enemies`` 回退，于是两个敌方 Marine 被打死后
    列表并不为空——回退把哑元顶了上来——敌方计数**永远停在 1**，``detect_terminal``
    永远等不到 0，victory 恒不触发。真机 run03 就是这么拿到 terminated=0/3 的：
    30 步全部打完、reward 有波动、PPO 也训了，唯独终端 credit 一次都没进账，
    等于把"离线 sim 缺胜负终端"这个根因原样搬到了真机上。回退语义只属于动作接地，
    绝不能进判定路径。
    """

    pool = (obs.get("visible_enemies") or []) + (obs.get("visible_allies") or [])
    return [
        u for u in pool
        if int(u.get("owner", 0)) == int(enemy_player) and not is_dummy(u)
    ]


def count_own_combat(obs: Mapping[str, Any]) -> int:
    return len(combat_actors(obs))


def count_enemy_combat(obs: Mapping[str, Any], enemy_player: int = 2) -> int:
    return len(enemy_present(obs, enemy_player))


def detect_terminal(
    obs: Mapping[str, Any], enemy_player: int = 2
) -> tuple[bool, str]:
    """确定性胜负终端：敌方作战单位归零 → victory；己方归零 → defeat。

    返回 ``(terminated, end_reason)``。``end_reason`` 用 ``"victory"`` / ``"defeat"``
    以便 ``reward.RewardTracker`` 直接识别（其 ``_VICTORY_REASONS`` 含 ``"victory"``，
    其余走 ``W_TERMINAL_DEFEAT``）。SC2 原生 ``player_result_*`` 命名不在其内，故这里
    归一化成稳定语义，避免赢了反被扣分。
    """

    own = count_own_combat(obs)
    enemy = count_enemy_combat(obs, enemy_player)
    if enemy <= 0:
        return True, "victory"
    if own <= 0:
        return True, "defeat"
    return False, ""


def ground_action(
    action_id: str,
    obs: Mapping[str, Any],
    step: int,
    enemy_player: int = 2,
) -> tuple[str, dict[str, Any]]:
    """把 PPO 输出的 ``action_id`` 接地成具体参数。

    规则（mirror route B ``choose_action``，但由策略决定动作种类而非启发式）：

      · ``attack_units`` + 有真敌人 → 取最近敌人当 target。
      · ``attack_move_units`` + 有真敌人 → 朝最近敌人坐标 attack_move。
      · ``move_units`` → 朝敌人质心走（无敌人则朝默认点 18,10）。
      · 其余（produce/build/research 等对 gen 图无意义）→ 安全退化成朝敌人
        attack_move / 朝默认点 move，保证 episode 在推进、能正常终止。
    """

    actors = combat_actors(obs)
    args: dict[str, Any] = {}
    actor: dict[str, Any] | None = None
    if actors:
        actor = actors[step % len(actors)]
        args["entity_ids"] = [int(actor["entity_id"])]

    enemies = combat_targets(obs, enemy_player)

    if action_id == "attack_units" and enemies:
        target = (
            min(enemies, key=lambda u: (_distance2(u, actor), int(u.get("entity_id") or 0)))
            if actor is not None else
            min(enemies, key=lambda u: int(u.get("entity_id") or 0))
        )
        return "attack_units", {**args, "target_entity_id": int(target.get("entity_id") or 0)}

    if action_id == "attack_move_units" and enemies:
        tgt = enemies[0]
        return "attack_move_units", {
            **args, "target_x": float(tgt.get("x", 18.0)),
            "target_y": float(tgt.get("y", 10.0)),
        }

    if action_id == "move_units":
        if enemies:
            cx = sum(float(e.get("x", 0.0)) for e in enemies) / len(enemies)
            cy = sum(float(e.get("y", 0.0)) for e in enemies) / len(enemies)
            return "move_units", {**args, "target_x": cx, "target_y": cy}
        return "move_units", {**args, "target_x": 18.0, "target_y": 10.0}

    # 兜底：建图/产兵等无法在 gen 图执行 → 朝敌人推进（仍有敌人）或去默认点。
    if enemies:
        tgt = enemies[0]
        return "attack_move_units", {
            **args, "target_x": float(tgt.get("x", 18.0)),
            "target_y": float(tgt.get("y", 10.0)),
        }
    return "move_units", {**args, "target_x": 18.0, "target_y": 10.0}


# --------------------------------------------------------------------------
# 后端
# --------------------------------------------------------------------------

class RouteBBackend(RlBackend):
    """route B 真机 env 后端：gen 图 + Bank RPC 建场 + 确定性胜负终端。

    Parameters
    ----------
    map_path, port
        SC2 API 模式实例地址与地图文件（gen 图）。
    own_count, enemy_count, enemy_player, own_xy, enemy_xy
        建场规格（mirror ``vibe_bank_scenario.DEFAULT_SCENARIO``）。
    step_mul, pump_step_mul
        每步推进帧数 / Bank 等待期间每轮泵时钟帧数（VIBE_BANK_008）。
    rpc_timeout, kernel_timeout
        Bank RPC / 内核注册等待超时。
    no_alliances
        反向对照用：跳过建交（episode 应 FAIL 在敌方未真正敌对）。
    session, scenario
        注入式依赖（离线测试用）。传了就跳过内部创建。
    """

    def __init__(
        self,
        *,
        map_path: str | Path = DEFAULT_MAP,
        port: int = 5000,
        own_count: int = 4,
        enemy_count: int = 2,
        enemy_player: int = 2,
        own_x: float = 10.0,
        own_y: float = 10.0,
        enemy_x: float = 18.0,
        enemy_y: float = 10.0,
        step_mul: int = 8,
        pump_step_mul: int = 4,
        rpc_timeout: float = 15.0,
        kernel_timeout: float = 90.0,
        min_success_rate: float = 0.0,
        between_episode_delay: float = 3.0,
        no_alliances: bool = False,
        fresh_bank: bool = True,
        session: Any | None = None,
        scenario: Any | None = None,
        protocol_root: str | Path | None = None,
    ) -> None:
        self.map_path = Path(map_path)
        self.port = int(port)
        self.own_count = int(own_count)
        self.enemy_count = int(enemy_count)
        self.enemy_player = int(enemy_player)
        self.own_x = float(own_x)
        self.own_y = float(own_y)
        self.enemy_x = float(enemy_x)
        self.enemy_y = float(enemy_y)
        self.step_mul = int(step_mul)
        self.pump_step_mul = int(pump_step_mul)
        self.rpc_timeout = float(rpc_timeout)
        self.kernel_timeout = float(kernel_timeout)
        self.min_success_rate = float(min_success_rate)
        # 让 SC2 释放上一局的 ws 槽 / bank 句柄再开新局；0 = 不等（测试用）。
        self.between_episode_delay = float(between_episode_delay)
        self.no_alliances = bool(no_alliances)
        self.fresh_bank = bool(fresh_bank)
        self.protocol_root = Path(protocol_root).resolve() if protocol_root else None

        self._session = session
        self._scenario = scenario
        self._owned_session = session is None
        self._owned_scenario = scenario is None
        self._episode_index = 0
        self._step_count = 0
        self._last_observation: dict[str, Any] | None = None
        self.last_verdict: dict[str, Any] = {}

    # -- RlBackend 协议 ----------------------------------------------------

    @property
    def state_version(self) -> int:
        return self._step_count

    def reset(self) -> dict[str, Any]:
        from .live_sc2_session import LiveRawSc2Session  # 延迟导入避免无 SC2 时拖累测试
        from .vibe_bank_scenario import (  # noqa: PLC0415
            ScenarioSpec,
            UnitPlacement,
            VibeBankScenario,
        )

        # --- episode 收尾：必须先离场再动 bank -------------------------------
        # 顺序铁律（VIBE_BANK_012）：`archive_bank()` 会**移动 bank 文件**，而 SC2 在
        # 对局中持有该文件句柄。在 in-game 状态下搬它，SC2 会拿着悬空句柄继续
        # BankLoad → 进程崩溃 → ws 掉链，表征成 `sc2_api_not_connected`（而且是在
        # 几十秒后的 set_hostile 泵时钟里才爆，离真正肇事点很远，极难归因）。
        # 基线 run_route_b_episode.py 之所以稳，正因为它在建会话之前就归档完了。
        # 多 episode 时同理：先 leave()（回菜单、释放句柄），再归档，再 CreateGame。
        #
        # 还有一条（VIBE_BANK_013）：``LiveRawSc2Session`` 是**一次性**的 ——
        # ``Sc2ApiClient.close()`` 不只关 ws，它还 ``loop.stop()`` + ``thread.join()``
        # 把自己的 asyncio 事件循环线程干掉。leave 之后再 ``connect()`` 就是往死掉的
        # loop 里投协程，``future.result()`` 永不返回 → ``TimeoutError`` +
        # "coroutine 'Sc2ApiClient._connect_with_retry' was never awaited"（指纹）。
        # 所以跨 episode 必须**重建 session**而非复用。注入的 session（测试）除外。
        if self._session is not None and self._episode_index > 0:
            try:
                self._session.leave()
            except Exception:  # noqa: BLE001
                pass
            if self._owned_session:  # 注入的 fake 不丢弃，否则测试失去可观测性
                self._session = None
                if self.between_episode_delay > 0:
                    time.sleep(self.between_episode_delay)

        # 每回合一个全新 VibeBankScenario：新对局 = 新内核 session，沿用旧实例会带着
        # 陈旧 `_sequence` 去对新内核，属自找的假阴性。
        # 注入的 scenario（测试用）永不替换，否则注入性被自己拆掉。
        if self._owned_scenario and (self._scenario is None or self._episode_index > 0):
            self._scenario = VibeBankScenario(
                session_id=f"route_b_rl_{int(time.time())}_{self._episode_index}")
        scenario = self._scenario
        if self.fresh_bank:
            self.last_verdict["fresh_bank_archived"] = scenario.archive_bank()

        if self._session is None:
            self._session = LiveRawSc2Session(
                self.map_path, port=self.port, realtime=False,
                protocol_root=self.protocol_root)
        session = self._session

        observation = dict(session.reset(self.map_path.name, 1))
        self._last_observation = observation

        scenario.set_pump(lambda: session.step(self.pump_step_mul))

        registration = scenario.wait_for_kernel(timeout=self.kernel_timeout)
        self.last_verdict["kernel_registered"] = bool(registration)

        spec = ScenarioSpec(
            name=f"skirmish-{self.own_count}v{self.enemy_count}-marines",
            placements=(
                UnitPlacement("Marine", self.own_count, self.own_x, self.own_y, player=1),
                UnitPlacement("Marine", self.enemy_count, self.enemy_x, self.enemy_y,
                              player=self.enemy_player),
            ),
        )
        build = scenario.build(spec, timeout=self.rpc_timeout,
                               set_alliances=not self.no_alliances)
        self.last_verdict["scenario_built"] = bool(build.get("ok"))

        # 推几帧让单位真正进场再观测，否则读到 spawn 前的快照。
        session.step(self.step_mul)
        observation = dict(session.observe())
        self._last_observation = observation
        self._step_count = 0
        self.last_verdict["reset"] = {
            "episode": self._episode_index,
            "loop": observation.get("loop"),
            "own": count_own_combat(observation),
            "enemy": count_enemy_combat(observation, self.enemy_player),
        }
        self._episode_index += 1
        return observation

    def step(
        self, action_id: str, args: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        if self._session is None or self._last_observation is None:
            raise RuntimeError("call reset() before step()")
        session = self._session

        args = dict(args or {})
        if not args:
            action_id, args = ground_action(
                action_id, self._last_observation, self._step_count, self.enemy_player)

        outcome = session.dispatch(action_id, args)
        session.step(self.step_mul)
        observation = dict(session.observe())
        self._last_observation = observation
        self._step_count += 1

        terminated, end_reason = detect_terminal(observation, self.enemy_player)
        mission = dict(observation.get("mission", {}))
        mission["terminated"] = terminated
        mission["end_reason"] = end_reason
        mission["phase"] = "terminal" if terminated else "active"
        observation["mission"] = mission

        info = {
            "action_id": action_id,
            "success": bool(outcome.get("success")),
            "results": outcome.get("results"),
            "own": count_own_combat(observation),
            "enemy": count_enemy_combat(observation, self.enemy_player),
            "end_reason": end_reason,
            "terminated": terminated,
            "step": self._step_count,
        }
        self.last_verdict["last_step"] = info
        return observation, terminated, info

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.leave()
            except Exception:  # noqa: BLE001
                pass
        self._session = None
        self._scenario = None


__all__ = [
    "RouteBBackend",
    "detect_terminal",
    "ground_action",
    "combat_actors",
    "combat_targets",
    "enemy_present",
    "enemy_units",
    "own_units",
    "count_own_combat",
    "count_enemy_combat",
]
