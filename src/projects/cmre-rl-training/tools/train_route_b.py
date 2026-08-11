#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_route_b.py — route B 真机 PPO：在 gen 图上训「交战→灭敌」策略。

把 Module 4 的路线 B 接到 PPO：``RouteBBackend`` 用 Bank RPC 在 gen 图上建小规模对抗场，
``CmreRLEnv`` 套上 ``RewardTracker``（敌方数下降 + 己方存活的密集 reward + 胜负终端 credit），
``PPOTrainer`` 跑 clipped-surrogate 更新。目标是拿到离线 sim 缺的那项**胜负终端**，
破 hard ceiling（离线 sim 的 ``end_reason`` 恒 ``''``，终端 credit 死、reward 退化成常数）。

本脚本是**端到端烟囱**：少量 episode 就能跑通「建场→多步交互→buffer 填满→PPO 更新→
episode 以 victory/defeat 终止」整条链，用于证明 route B → PPO 在真机上闭环（而非追求收敛）。
真机线需要独占的 SC2 API 窗口（5000 + 单 ws 槽），被占用时由调用方先释放。

用法
----
  python tools/train_route_b.py --port 5000 --episodes 4 --max-steps 40
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
# 脚本位于 cmre-rl-training/tools/，故含 cmre_rl_training 包的目录是 parents[1]。
# `vibe`（network.py 依赖，PEP 420 命名空间包）在同级项目 cmre-porting 下。
# 注意：不要靠 PYTHONPATH 传 —— Git Bash 的 $PWD 是 POSIX 路径且用 ':' 分隔，
# Windows Python 两样都认不了，会静默变成 ModuleNotFoundError。这里自解析绝对路径。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CMRE_PORTING = PROJECT_ROOT.parent / "cmre-porting"
DEFAULT_PROTOCOL_ROOT = (
    PROJECT_ROOT.parents[1] / "reference" / "SC2-Neuro-API-Integration")
REPO_ROOT = PROJECT_ROOT.parents[2]
# live_lock 在 tools/galaxy-vibe/：真机资源互斥锁，防止两个会话同抢 :5000 / 同一个
# GalaxyVibe.SC2Bank。这里**硬 import**，不做 try/except 降级 —— 能被静默跳过的
# 锁等于没有锁（同"校验器自身要有校验器"）。
for extra in (str(PROJECT_ROOT), str(CMRE_PORTING),
              str(REPO_ROOT / "tools" / "galaxy-vibe")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from live_lock import add_lock_args, acquire_from_args, LiveLockBusy  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402

from cmre_rl_training.action_space import ACTION_NAMES, NUM_ACTIONS  # noqa: E402
from cmre_rl_training.env import CmreRLEnv  # noqa: E402
from cmre_rl_training.network import P2AllyAC  # noqa: E402
from cmre_rl_training.ppo import PPOTrainer, RolloutBuffer  # noqa: E402
from cmre_rl_training.route_b_backend import RouteBBackend  # noqa: E402

DEFAULT_MAP = r"C:/tmp/VibeDeadOfNight-Gen.SC2Map"


def run(args: argparse.Namespace) -> dict[str, Any]:
    backend = RouteBBackend(
        map_path=args.map, port=args.port,
        own_count=args.own_count, enemy_count=args.enemy_count,
        enemy_player=args.enemy_player,
        step_mul=args.step_mul, pump_step_mul=args.pump_step_mul,
        rpc_timeout=args.rpc_timeout, kernel_timeout=args.kernel_timeout,
        no_alliances=args.no_alliances,
        fresh_bank=not args.no_fresh_bank,
        protocol_root=args.protocol_root or None,
    )
    env = CmreRLEnv(backend, normalize_reward=not args.no_norm)

    policy = P2AllyAC(hidden_dim=args.hidden_dim, num_actions=NUM_ACTIONS)
    # 若给出 BC checkpoint，warm-start 共享 trunk（可选）。
    if args.bc_checkpoint:
        from cmre_rl_training.network import load_bc_checkpoint_into_ac  # noqa: PLC0415
        policy = load_bc_checkpoint_into_ac(policy, args.bc_checkpoint)
    policy.train()

    trainer = PPOTrainer(
        policy, lr=args.lr, clip=args.clip, gamma=args.gamma, lam=args.lam,
        epochs=args.epochs, batch_size=args.batch_size, ent_coef=args.ent_coef,
        vf_coef=args.vf_coef, max_grad_norm=args.max_grad_norm,
        normalize_advantages=True, normalize_returns=True, ent_floor=args.ent_floor,
    )

    buffer = RolloutBuffer(
        capacity=max(1, args.episodes * args.max_steps),
        obs_dim=env.observation_dim, action_dim=1, mask_dim=NUM_ACTIONS)

    run_report: dict[str, Any] = {
        "schemaVersion": 1, "probe": "route_b_ppo", "generatedAt": _utcnow(),
        "map": str(args.map), "port": args.port,
        "episodes_requested": args.episodes, "max_steps": args.max_steps,
        "obs_dim": env.observation_dim, "action_dim": NUM_ACTIONS,
        "episodes": [], "train_metrics": [], "errors": [],
    }
    start = time.time()

    try:
        for ep in range(args.episodes):
            _flush_report(args, run_report)  # 崩了也要留下现场，别让证据随异常蒸发
            try:
                obs = env.reset()
            except Exception as exc:  # noqa: BLE001
                # 真机 episode 建场是有损的（VIBE_BANK_011）。**只记录不吞掉**：
                # 错误进 errors[]、计入 verdict，绝不静默重试。连续两次失败即中止，
                # 避免把系统性故障刷成"偶发"。
                run_report["errors"].append(f"episode {ep} reset failed: {exc!r}")
                if len(run_report["errors"]) >= 2:
                    break
                continue
            done = False
            step = 0
            ep_info: dict[str, Any] = {
                "episode": ep, "steps": 0, "terminated": False,
                "end_reason": "", "total_reward": 0.0,
                "wins": 0, "losses": 0,
                # 单位数轨迹是「敌人确实被打死了」的唯一硬证据；只有标量 reward
                # 的话，敌方计数卡在哑元地板上也看不出来（run03 的教训）。
                "trace": [],
            }
            while not done and step < args.max_steps:
                mask = env.action_mask()
                obs_t = torch.as_tensor(np.asarray(obs, dtype=np.float32)).unsqueeze(0)
                mask_t = torch.as_tensor(np.asarray(mask, dtype=bool)).unsqueeze(0)
                with torch.no_grad():
                    logits, value = policy(obs_t, mask_t)
                    logits = torch.where(
                        torch.isfinite(logits), logits, torch.full_like(logits, -1e9))
                    dist = torch.distributions.Categorical(logits=logits)
                    action = dist.sample()
                    logprob = dist.log_prob(action)
                action_id = ACTION_NAMES[int(action)]
                obs2, reward, terminated, info = env.step(action_id, {})
                buffer.store(
                    obs=np.asarray(obs, dtype=np.float32),
                    action=action.detach().numpy(),
                    logprob=logprob.detach().numpy(),
                    value=value.detach().numpy(),
                    reward=float(reward), done=bool(terminated),
                    mask=np.asarray(mask, dtype=bool),
                )
                ep_info["total_reward"] += float(reward)
                ep_info["trace"].append({
                    "s": step, "a": action_id,
                    "own": info.get("own"), "enemy": info.get("enemy"),
                    "ok": info.get("success"), "r": round(float(reward), 3),
                })
                obs = obs2
                done = bool(terminated)
                step += 1
                if terminated:
                    ep_info["terminated"] = True
                    ep_info["end_reason"] = info.get("end_reason", "")
                    if info.get("end_reason") == "victory":
                        ep_info["wins"] += 1
                    elif info.get("end_reason") == "defeat":
                        ep_info["losses"] += 1
            ep_info["steps"] = step
            run_report["episodes"].append(ep_info)

            # 收集满一窗或最后一轮 → 跑 PPO 更新。
            if len(buffer) >= buffer.capacity or ep == args.episodes - 1:
                if len(buffer) > 0:
                    metrics = trainer.train(buffer)
                    buffer.clear()
                    run_report["train_metrics"].append({
                        "after_episode": ep, **metrics,
                        "buffer_used": len(buffer) if False else None,
                    })
    finally:
        backend.close()

    run_report["elapsed_seconds"] = round(time.time() - start, 1)
    run_report["wins"] = sum(e["wins"] for e in run_report["episodes"])
    run_report["losses"] = sum(e["losses"] for e in run_report["episodes"])
    run_report["terminated_episodes"] = sum(
        1 for e in run_report["episodes"] if e["terminated"])
    run_report["episode_errors"] = len(run_report["errors"])

    # 保存 checkpoint（仅当确有训练发生）。
    if args.out and run_report["train_metrics"]:
        from cmre_rl_training.network import save_rl_checkpoint  # noqa: PLC0415
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        saved = save_rl_checkpoint(
            policy, out_path,
            training={"run_report": "route_b_ppo_smoke"})
        run_report["checkpoint"] = str(saved)

    return run_report


def _flush_report(args: argparse.Namespace, report: dict[str, Any]) -> None:
    """把当前 run_report 落盘。真机线常在中途炸，报告只在成功路径写 = 丢失现场。"""

    path = getattr(args, "report", "")
    if not path:
        return
    rp = Path(path)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _utcnow() -> str:
    from datetime import datetime, timezone  # local import 避免顶部重排
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="route B 真机 PPO 烟囱测试")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--episodes", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--own-count", type=int, default=4)
    ap.add_argument("--enemy-count", type=int, default=2)
    ap.add_argument("--enemy-player", type=int, default=2)
    ap.add_argument("--step-mul", type=int, default=8)
    ap.add_argument("--pump-step-mul", type=int, default=4)
    ap.add_argument("--rpc-timeout", type=float, default=15.0)
    ap.add_argument("--kernel-timeout", type=float, default=90.0)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--gamma", type=float, default=0.99)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--ent-coef", type=float, default=0.01)
    ap.add_argument("--vf-coef", type=float, default=0.5)
    ap.add_argument("--max-grad-norm", type=float, default=0.5)
    ap.add_argument("--ent-floor", type=float, default=0.0)
    ap.add_argument("--no-norm", action="store_true", help="关闭 reward 归一化")
    ap.add_argument("--no-fresh-bank", action="store_true", help="不归档旧 bank")
    ap.add_argument("--bc-checkpoint", default="")
    ap.add_argument("--protocol-root", default=str(DEFAULT_PROTOCOL_ROOT),
                    help="SC2 protobuf 协议根目录（LiveRawSc2Session 用）")
    ap.add_argument("--no-alliances", action="store_true",
                    help="反向对照：跳过建交（episode 应 FAIL 在非敌对）")
    ap.add_argument("--out",
                    default=str(PROJECT_ROOT / "artifacts" / "route_b_ppo"
                                / "rl_checkpoint.pt"))
    ap.add_argument("--report", default="", help="把 run_report 落成 JSON 文件")
    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    add_lock_args(parser)
    args = parser.parse_args(argv)

    lock = None
    try:
        lock = acquire_from_args(args, "train_route_b",
                                 note=f"episodes={args.episodes}")
    except LiveLockBusy as exc:
        print(f"[live-lock] {exc}", file=sys.stderr)
        print(json.dumps({"error": "live_lock_busy", "holder": exc.holder_info},
                         ensure_ascii=False, indent=2))
        return 3

    drift = None
    try:
        report = run(args)
    finally:
        if lock is not None:
            # 先取环境指纹再释放：SC2 若在本轮中途被别人重启过，这一轮的
            # 观测/动作是断裂的，报告不能装作没事（见 plan-0310 §2.5）。
            drift = lock.env_drift()
            lock.release()
    if drift:
        report["env_drift"] = drift
        print(f"[live-lock] WARNING 环境漂移，本轮数据不连续：{drift}",
              file=sys.stderr)
    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:8000])
    closed = (
        report["terminated_episodes"] > 0
        and any(m.get("total_loss") is not None for m in report["train_metrics"])
    )
    print(f"\n[train_route_b] closed={closed} "
          f"wins={report['wins']} losses={report['losses']} "
          f"terminated={report['terminated_episodes']}/{report['episodes_requested']} "
          f"episode_errors={report.get('episode_errors', 0)}")
    return 0 if closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
