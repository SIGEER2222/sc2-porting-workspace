#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_route_b_episode.py — route B 真机 episode 驱动：gen 图上的多步 RL 回合。

`tools/galaxy-vibe/route_b_rl_probe.py` 证明了单次 spawn→order→observe 能闭环；
本脚本证明**它能连续跑 N 步**，也就是 RL 真正需要的东西，并且走的是可复用组件而不是
一次性探针代码：

  · `cmre_rl_training.vibe_bank_scenario.VibeBankScenario` —— episode 级建场（Bank RPC）
  · `cmre_rl_training.live_sc2_session.LiveRawSc2Session` —— step 级控制/观测（raw API）

为什么不用移植图：见 vibe_bank_scenario 模块 docstring（同一根因的两个表征）。

判据
----
  ① kernel_registered      内核在 gen 图注册
  ② scenario_built         Bank RPC 把整个场景造出来（建交 + 每个 placement 都 OK）
  ③ own_units_observed     raw obs 独立确认己方单位数 == 期望
  ④ enemy_units_spawned    内核侧真值（无迷雾）确认敌方单位确实被造出来
  ⑤ enemy_units_observed   raw obs 独立确认敌方单位数 == 期望（RL 要有对手才有 reward）
  ⑥ enemy_not_ally         敌方单位没有落在 `visible_allies` 里（VIBE_BANK_009 反向防线）
  ⑦ action_success_rate    >= --min-success-rate（默认 0.8）
  ⑧ frames_advanced        游戏钟确实在推进（loop 单调增）——移植图正是死在这
  ⑨ script_errors == 0

④⑤⑥ 三条缺一不可：只有 ⑤ 会被中立地形物冒充（owner 9 的 Xel'Naga 塔/岩石曾
一度把判据刷绿）；只有 ④ 分不清"造出来了但看不见"；缺 ⑥ 则分不清"看得见但是盟友"
——gen 图剥离触发器栈后默认全员盟友，攻击指令会被引擎拒，reward 恒 0 却零报错。

⑦ 的失败**不一定是通道问题**：ep-alliance-02 曾稳定 0.5，根因是打了 gen 图自带的
非战斗哑元（`ActionResult.NotSupported`），通道 0 ScriptError 全程干净。诊断顺序
应为「先看 results 码、再看目标是谁、最后才怀疑 RPC」，见 `combat_targets`。

episode_pass = 全部为真。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
for extra in (PROJECT_ROOT, REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from cmre_rl_training.live_sc2_session import LiveRawSc2Session  # noqa: E402
from cmre_rl_training.vibe_bank_scenario import (  # noqa: E402
    ScenarioSpec,
    UnitPlacement,
    VibeBankScenario,
)

DEFAULT_MAP = r"C:/tmp/VibeDeadOfNight-Gen.SC2Map"
SCRIPT_ERROR_DIR = Path(os.path.expanduser("~")) / "Documents" / "StarCraft II" / "Logs"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def script_errors_since(since: float) -> list[str]:
    if not SCRIPT_ERROR_DIR.is_dir():
        return []
    hits = []
    for path in SCRIPT_ERROR_DIR.glob("**/ScriptError*.txt"):
        try:
            if path.stat().st_mtime >= since:
                hits.append(str(path))
        except OSError:
            pass
    return hits


# `parse_observation` 产出的键名是 own_units / visible_enemies。ep-0145 曾因驱动这边
# 写成 "enemy_units" 而恒读到 0，把"敌人没造出来"的锅扣给了 Bank RPC —— 实际上
# scenario_build 全 ok。键名对不上是最廉价也最恶心的假阴性来源，这里做显式解析。
ENEMY_KEYS = ("visible_enemies", "enemy_units")

# SC2 里 owner 9 是中立方（可摧毁岩石、瓦斯泉、Xel'Naga 塔这些地形物）。
# `parse_observation` 的分类规则是"不是我的、又不是矿/气，且 owner != 0 就算敌人"，
# 于是整张 gen 图的岩石都被算进 visible_enemies。ep-0200 就因此拿到过
# `enemy_units_observed=true` 的**假绿灯**：9 个"敌人"全是 owner=9 的石头，
# attack 命令还真被引擎接受了（ActionResult=1），可它打的是 100 格外的岩石。
# 判据必须锚定"场景里那个具体的敌方玩家"，不能锚定"非我方"。
NEUTRAL_OWNER = 9


def own_units(observation: dict[str, Any]) -> list[dict[str, Any]]:
    return list(observation.get("own_units", []) or [])


def _all_non_own(observation: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ENEMY_KEYS:
        values = observation.get(key)
        if values:
            return list(values)
    return []


def enemy_units(observation: dict[str, Any],
                enemy_player: int = 2) -> list[dict[str, Any]]:
    """只认属于场景敌方玩家的单位。中立地形物一律不算。"""

    return [u for u in _all_non_own(observation)
            if int(u.get("owner", 0)) == int(enemy_player)]


def neutral_units(observation: dict[str, Any]) -> list[dict[str, Any]]:
    return [u for u in _all_non_own(observation)
            if int(u.get("owner", 0)) == NEUTRAL_OWNER]


def combat_actors(observation: dict[str, Any],
                  unit_type: str = "Marine") -> list[dict[str, Any]]:
    """只挑我们自己造出来的作战单位当 actor。

    gen 图开局自带 1 个非战斗单位（obs 里 type 4051）。`_pick_actor` 的默认启发式
    会在观测顺序抖动时偶尔选中它，MOVE 命令随即被引擎拒绝 —— 表现为 action
    success_rate 在 0.67 上下无规律浮动，看着像"通道不稳"，其实是选错了执行者。
    显式锁定单位类型，动作成功率才是策略/通道的信号而不是噪声。
    """

    return [u for u in own_units(observation)
            if str(u.get("unit_type_id")) == unit_type]


def combat_targets(observation: dict[str, Any],
                   enemy_player: int = 2) -> list[dict[str, Any]]:
    """只挑真正可被攻击的敌方单位当 target。

    VIBE_BANK_010（2026-08-10 真机取证）：`combat_actors` 那个坑的**镜像版**，
    方向相反 —— 一个选错执行者，一个选错目标。gen 图开局双方各自带一个非战斗
    哑元（obs 里 `unit_type_id == "4051"`，位于出生点外的 (76,103)/(85,94)）。
    `enemy_units()` 把它一并返回，而 `choose_action` 原先取 `enemies[0]` ——
    取到哪个纯由 SC2 观测顺序抖动决定。命中哑元时引擎回
    `ActionResult.NotSupported(2)`，表现为 action_success_rate 在 0.5 上下
    无规律浮动（ep-alliance-02 实测 6/12），看着像"Bank RPC 通道不稳"，
    其实是对一个打不了的目标下了攻击指令 —— 通道本身干净、0 ScriptError。

    判据：`unit_type_id` 纯数字 = SC2 没解析出单位名 = 地图家具/哑元，不可攻击。
    真单位（Marine 等）一律有名字。全被过滤掉时回退原列表：宁可打不动，
    也不能静默退化成"没有敌人"（那会让判据 ⑤ 假绿）。
    """

    enemies = enemy_units(observation, enemy_player)
    combat = [u for u in enemies
              if not str(u.get("unit_type_id", "")).strip().isdigit()]
    return combat or enemies


def _distance2(a: dict[str, Any], b: dict[str, Any]) -> float:
    dx = float(a.get("x", 0.0)) - float(b.get("x", 0.0))
    dy = float(a.get("y", 0.0)) - float(b.get("y", 0.0))
    return dx * dx + dy * dy


def choose_action(observation: dict[str, Any], step: int,
                  enemy_player: int = 2) -> tuple[str, dict[str, Any]]:
    """极简策略：有敌人就打过去，没有就朝目标点走。

    这里刻意**不接 PPO checkpoint** —— 本脚本要证的是"环境能跑"，不是"策略好"。
    把两件事混在一起，环境故障会被误读成策略差（N5 hard 档就吃过这个亏）。
    """

    actors = combat_actors(observation)
    args: dict[str, Any] = {}
    actor: dict[str, Any] | None = None
    if actors:
        # 轮转执行者：既覆盖全部单位，又保持确定性（同一 step 序列可复现）
        actor = actors[step % len(actors)]
        args["entity_ids"] = [int(actor["entity_id"])]

    enemies = combat_targets(observation, enemy_player)
    if enemies:
        # 取最近目标而非 enemies[0]：观测顺序在 SC2 raw obs 里不保证稳定，
        # 按顺序取会让"打谁"随帧抖动，动作成功率就不再是通道/策略的信号。
        # 距离相同再按 entity_id 兜底，保证同一观测必得同一目标。
        if actor is not None:
            target = min(enemies,
                         key=lambda u: (_distance2(u, actor),
                                        int(u.get("entity_id") or 0)))
        else:
            target = min(enemies, key=lambda u: int(u.get("entity_id") or 0))
        tag = int(target.get("entity_id") or 0)
        if tag:
            return "attack_units", {**args, "target_entity_id": tag}
        return "attack_move_units", {**args,
                                     "target_x": float(target.get("x", 18.0)),
                                     "target_y": float(target.get("y", 10.0))}
    return "move_units", {**args, "target_x": 18.0, "target_y": 10.0}


OBS_BUCKETS = ("own_units", "visible_enemies", "visible_allies",
               "enemy_units", "mineral_fields", "vespene_geysers")


def obs_owner_histogram(observation: dict[str, Any]) -> dict[str, dict[str, int]]:
    """把每个观测桶里的 owner 分布摊开。

    诊断"我造的敌人去哪了"时，只看 visible_enemies 是不够的：如果 gen 图没跑过
    melee 的敌对关系初始化，玩家 2 的单位会被引擎判成 Ally，落进 visible_allies，
    于是"敌人不存在"和"敌人被分到别的桶"长得一模一样。摊开就没得赖。
    """

    out: dict[str, dict[str, int]] = {}
    for bucket in OBS_BUCKETS:
        units = observation.get(bucket) or []
        if not units:
            continue
        counts: dict[str, int] = {}
        for unit in units:
            key = f"owner{int(unit.get('owner', -1))}"
            counts[key] = counts.get(key, 0) + 1
        out[bucket] = counts
    return out


def _kernel_count(entry: dict[str, Any] | None) -> int:
    """从 `query.units` 的 payload 里抠出 count。取不到就返回 -1（而不是 0）。

    0 和"读不出来"必须区分：前者是"内核说没有"，后者是"我们没问明白"。
    混成同一个值，通道故障就会被当成场景故障。
    """

    if not entry or not entry.get("ok"):
        return -1
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return -1
    value = payload.get("value", payload)
    if isinstance(value, dict):
        for key in ("count", "units", "total"):
            if isinstance(value.get(key), (int, float)):
                return int(value[key])
            if isinstance(value.get(key), list):
                return len(value[key])
    if isinstance(value, list):
        return len(value)
    return -1


def unit_digest(units: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    return [{"tag": u.get("entity_id"), "type": u.get("unit_type_id"),
             "owner": u.get("owner"),
             "x": round(float(u.get("x", 0.0)), 1),
             "y": round(float(u.get("y", 0.0)), 1)}
            for u in units[:limit]]


def run_episode(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "probe": "route_b_episode",
        "generatedAt": utcnow(),
        "port": args.port,
        "map": args.map,
        "tag": args.tag,
        "steps_requested": args.steps,
        "verdict": {
            "kernel_registered": False, "scenario_built": False,
            "own_units_observed": False,
            # 内核侧真值（无战争迷雾）：敌方单位确实被造出来了
            "enemy_units_spawned": False,
            # raw obs 侧：确实看得见、能被 RL 当成对手
            "enemy_units_observed": False,
            # 反向防线：敌方玩家的单位不能出现在 visible_allies（见 VIBE_BANK_009）
            "enemy_not_ally": False,
            "action_success_rate_ok": False, "frames_advanced": False,
            "script_errors_clean": False, "episode_pass": False,
        },
        "errors": [],
    }
    window_start = time.time()

    spec = ScenarioSpec(
        name=f"skirmish-{args.own_count}v{args.enemy_count}-marines",
        placements=(
            UnitPlacement("Marine", args.own_count,
                          args.own_x, args.own_y, player=1),
            UnitPlacement("Marine", args.enemy_count,
                          args.enemy_x, args.enemy_y, player=args.enemy_player),
        ),
    )
    report["scenario"] = spec.name
    report["scenario_spec"] = [p.as_args() for p in spec.placements]

    scenario = VibeBankScenario(session_id=f"route_b_ep_{args.tag or 'x'}")
    if args.fresh_bank:
        report["fresh_bank_archived"] = scenario.archive_bank()

    session = LiveRawSc2Session(
        args.map, port=args.port, realtime=False,
        protocol_root=args.protocol_root or None)
    try:
        observation = dict(session.reset(Path(args.map).name, 1))
        report["reset"] = {"loop": observation.get("loop"),
                           "own": len(own_units(observation)),
                           "enemy": len(enemy_units(observation,
                                                    args.enemy_player)),
                           "neutral_ignored": len(neutral_units(observation)),
                           "own_digest": unit_digest(own_units(observation))}

        # VIBE_BANK_008：本会话是 realtime=False（RL 要确定性步进），游戏钟只在
        # `RequestStep` 时前进。内核 PollLoop 是 Galaxy 触发器，不推钟就永远拿不到
        # 执行片 —— Bank 里既不会出现注册标记、也不会有任何 response。ep-0110 就是
        # 这么"失败"的：0 ScriptError、registration={}，看着像地图没加载，其实是
        # 我们把游戏按在 loop=0 上等它自己动。所以 Bank 的每个等待循环都要泵时钟。
        scenario.set_pump(lambda: session.step(args.pump_step_mul))

        registration = scenario.wait_for_kernel(timeout=args.kernel_timeout)
        report["registration"] = registration
        report["verdict"]["kernel_registered"] = bool(registration)
        if not registration:
            report["errors"].append("kernel not registered on gen map")
            return report

        report["ping"] = scenario.ping()

        build = scenario.build(spec, timeout=args.rpc_timeout,
                               set_alliances=not args.no_alliances)
        report["scenario_build"] = build
        report["verdict"]["scenario_built"] = bool(build.get("ok"))
        if not build.get("ok"):
            report["errors"].append(f"scenario build failed: {build.get('failed')}")

        # spawn 后推几帧，让单位真正进场再观测（否则会读到 spawn 前的快照）
        session.step(args.step_mul)
        observation = dict(session.observe())
        own_seen = len(own_units(observation))
        enemy_seen = len(enemy_units(observation, args.enemy_player))
        neutral_seen = len(neutral_units(observation))
        report["post_spawn"] = {
            "loop": observation.get("loop"),
            "own": own_seen, "enemy": enemy_seen,
            # 中立地形物单独记账，防止它再被算进"敌人"里冒充 reward 源
            "neutral_ignored": neutral_seen,
            "expected_own": spec.own_units(),
            "expected_enemy": spec.enemy_units(),
            "own_digest": unit_digest(own_units(observation)),
            "enemy_digest": unit_digest(enemy_units(observation, args.enemy_player)),
            "neutral_digest": unit_digest(neutral_units(observation), limit=3),
            "owner_histogram": obs_owner_histogram(observation),
            "ally_digest": unit_digest(
                list(observation.get("visible_allies") or []), limit=6),
            "combat_actors": len(combat_actors(observation))}
        report["verdict"]["own_units_observed"] = own_seen >= spec.own_units()
        report["verdict"]["enemy_units_observed"] = enemy_seen >= spec.enemy_units()

        # 建交是否真的生效：敌方玩家的单位若还挂在 visible_allies，说明 alliance
        # 位没清干净（或只清了单向），此时攻击指令会被引擎拒、reward 恒 0。
        misfiled_allies = [
            u for u in (observation.get("visible_allies") or [])
            if int(u.get("owner", 0)) == int(args.enemy_player)]
        report["post_spawn"]["enemy_misfiled_as_ally"] = len(misfiled_allies)
        report["verdict"]["enemy_not_ally"] = not misfiled_allies
        if misfiled_allies:
            report["errors"].append(
                f"{len(misfiled_allies)} enemy-player units still classified as ally "
                f"— alliance not cleared (VIBE_BANK_009)")

        # 内核侧真值：raw obs 受战争迷雾限制，看不见不等于没造出来。两个来源都记，
        # 才能把"spawn 失败"和"视野不足"区分开——只看其中一个必然误判。
        #
        # VIBE_BANK_011：Bank 通道有损是固有特性（同实例 A/B 实测 ~1/12 timeout，
        # 见 vibe_bank_scenario.query_units）。单次 timeout 会把判据 ④ 误判成
        # "敌人没造出来"（ep-alliance-03 就这么红的，而 raw obs 同时看得见它们）。
        # 只对**传输失败**重试；读到了但数字不对一律照实判红，不重试。
        kernel_counts = {}
        for player in (1, args.enemy_player):
            probe = scenario.query_units(player=player, timeout=args.rpc_timeout,
                                         attempts=3)
            kernel_counts[player] = {
                "ok": bool(probe.get("ok")),
                "payload": probe.get("payload"),
                "transport_retries": probe.get("transport_retries", 0),
                "error": probe.get("error")}
        report["kernel_unit_counts"] = kernel_counts
        report["verdict"]["enemy_units_spawned"] = _kernel_count(
            kernel_counts.get(args.enemy_player)) >= spec.enemy_units()

        loops = [int(observation.get("loop", 0))]
        rollout = []
        for index in range(args.steps):
            action_id, action_args = choose_action(observation, index,
                                                   args.enemy_player)
            outcome = session.dispatch(action_id, action_args)
            session.step(args.step_mul)
            observation = dict(session.observe())
            loops.append(int(observation.get("loop", 0)))
            rollout.append({
                "step": index,
                "action_id": action_id,
                "success": bool(outcome.get("success")),
                # 失败时 `error` 常常是 None（response.error 为空），真正的原因藏在
                # ActionResult 码里。不记 results 就只能靠猜。
                "results": outcome.get("results"),
                "unit_tag": outcome.get("unit_tag"),
                "error": outcome.get("error"),
                "loop": observation.get("loop"),
                "own": len(own_units(observation)),
                "enemy": len(enemy_units(observation, args.enemy_player)),
            })
        report["rollout"] = rollout

        successes = sum(1 for r in rollout if r["success"])
        rate = successes / len(rollout) if rollout else 0.0
        report["action_stats"] = {
            "requests": len(rollout), "successes": successes,
            "success_rate": round(rate, 3),
            "errors": [r["error"] for r in rollout if r.get("error")][:10],
        }
        report["verdict"]["action_success_rate_ok"] = rate >= args.min_success_rate

        monotone = all(b >= a for a, b in zip(loops, loops[1:]))
        advanced = len(loops) > 1 and loops[-1] > loops[0]
        report["loops"] = {"first": loops[0], "last": loops[-1],
                           "monotone": monotone, "advanced": advanced}
        report["verdict"]["frames_advanced"] = bool(monotone and advanced)

    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        report["bank_stats"] = {k: v for k, v in scenario.stats.items() if k != "trace"}
        report["bank_trace"] = scenario.stats.get("trace", [])[-20:]
        try:
            session.leave()
        except Exception:  # noqa: BLE001
            pass

    errors = script_errors_since(window_start)
    report["script_errors"] = errors
    report["verdict"]["script_errors_clean"] = not errors

    v = report["verdict"]
    v["episode_pass"] = all([
        v["kernel_registered"], v["scenario_built"], v["own_units_observed"],
        v["enemy_units_spawned"], v["enemy_units_observed"], v["enemy_not_ally"],
        v["action_success_rate_ok"],
        v["frames_advanced"], v["script_errors_clean"]])
    if not v["episode_pass"]:
        v["failed"] = [k for k, ok in v.items()
                       if k != "episode_pass" and ok is False]
    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="route B 真机 episode：gen 图多步 RL 回合")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--tag", default="")
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--step-mul", type=int, default=8)
    # Bank 等待期间每轮推进的帧数（VIBE_BANK_008）。给小一点，让 PollLoop 有足够
    # 多次执行机会而不是一次跳过整个响应窗口。
    ap.add_argument("--pump-step-mul", type=int, default=4)
    ap.add_argument("--own-count", type=int, default=4)
    ap.add_argument("--enemy-count", type=int, default=2)
    ap.add_argument("--enemy-player", type=int, default=2)
    ap.add_argument("--own-x", type=float, default=10.0)
    ap.add_argument("--own-y", type=float, default=10.0)
    # 默认只隔 6 格：Marine 视野 9，确保敌人一定落在视野内。距离拉大就会分不清
    # "没造出来"和"看不见"。
    ap.add_argument("--enemy-x", type=float, default=16.0)
    ap.add_argument("--enemy-y", type=float, default=10.0)
    ap.add_argument("--rpc-timeout", type=float, default=15.0)
    ap.add_argument("--kernel-timeout", type=float, default=90.0)
    ap.add_argument("--min-success-rate", type=float, default=0.8)
    ap.add_argument("--protocol-root", default="")
    ap.add_argument("--fresh-bank", action="store_true")
    # 反向对照（negative control）：跳过建交，episode 必须 FAIL 在 enemy_not_ally。
    # 没有它，正向 PASS 无法排除"其实本来就敌对、我的建交是空操作"这种假阳性。
    # 铁律出处：函数重定义静默丢图那轮——正向绿而反向也绿 = 校验器根本没在测。
    ap.add_argument("--no-alliances", action="store_true",
                    help="negative control: skip PlayerSetAlliance clearing")
    ap.add_argument("--out", default="")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_episode(args)
    tag = f"-{args.tag}" if args.tag else ""
    out_path = Path(args.out) if args.out else (
        REPO_ROOT / "artifacts" / "galaxy-vibe" / f"route-b-episode{tag}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:6000])
    print(f"\n[route_b_episode] verdict -> {out_path}")
    return 0 if report["verdict"]["episode_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
