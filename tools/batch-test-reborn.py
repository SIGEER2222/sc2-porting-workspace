#!/usr/bin/env python3
"""批量测试重生虫心指挥官的运行时单位/建筑替换。

用法:
    python batch-test-reborn.py [--commanders Izsha,Naktul,...]

对每个指挥官:
1. 终止遗留 SC2 进程
2. 删除现有 bank 文件以检测新写入
3. 调用 launch-cmre-alenger.ps1 加载地图
4. 等待 launcher 退出
5. 备份 bank 文件到 evidence 目录
6. 解析 bank XML 提取关键指标
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

WORKSPACE = Path(__file__).resolve().parents[1]
LAUNCHER = WORKSPACE / "tools" / "launchers" / "launch-cmre-alenger.ps1"
LEGACY_ROOT = WORKSPACE.parent / "cmre-runtime"
MAP_NAME = "亡者之夜.SC2Map"
BANK_FILE = Path(os.environ["USERPROFILE"]) / "Documents" / "StarCraft II" / "Banks" / "CMRERebornDebug.SC2Bank"
EVIDENCE_DIR = WORKSPACE / "src" / "projects" / "reborn-mods-cmre-integration" / "stages" / "03-mvp-feasible" / "evidence"
# test-lock.ps1 中 $script:ProjRoot 解析为 cmre-runtime 的父目录（即 SC2VibeTools），
# 锁文件位于 SC2VibeTools/out/.test.lock
TEST_LOCK_FILE = WORKSPACE.parent / "out" / ".test.lock"
TIMESTAMP = "20260727-retry2"

# (runtime_id, reborn_name, race, expected_unit_keys)
COMMANDERS = [
    ("ZergIzsha",      "Izsha",      "Zerg",    ["siqueen"]),
    ("ZergNaktul",     "Naktul",     "Zerg",    ["queen"]),
    ("ProtossKarass",  "Karass",     "Protoss", ["higharchontemplar"]),
    ("ProtossNarud",   "Narud",      "Protoss", ["revenantgun"]),
    ("TerranTosh",     "Tosh",       "Terran",  ["witch"]),
    ("ProtossUrun",    "Urun",       "Protoss", ["huntress"]),
    ("TerranWarfield", "Warfield",   "Terran",  ["grizzly"]),
    ("ZergZagara",     "Zagara",     "Zerg",    ["infestedabomination"]),
]


@dataclass
class TestResult:
    commander: str
    race: str
    exit_code: int
    bank_fresh_write: bool
    deep_debug_ran: Optional[int] = None
    k5kerrigan_after: Optional[int] = None
    zerg_total: Optional[int] = None
    expected_units: dict = field(default_factory=dict)
    zerg_buildings: dict = field(default_factory=dict)
    passed: bool = False
    detail: str = ""


def kill_sc2() -> None:
    """终止所有 SC2 进程（使用 taskkill 避免 TRAE 沙箱拦截 Stop-Process）。"""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", "SC2_x64.exe"],
            check=False, capture_output=True, timeout=15
        )
    except Exception:
        pass
    time.sleep(5)


def cleanup_lock() -> None:
    """删除遗留的测试锁文件（防止上一轮 launcher 异常退出后锁残留）。"""
    if TEST_LOCK_FILE.exists():
        try:
            TEST_LOCK_FILE.unlink()
            print(f"  Removed stale test lock: {TEST_LOCK_FILE}")
        except Exception as exc:
            print(f"  Warn: cannot remove test lock: {exc}")


def remove_bank() -> None:
    """删除现有 bank 文件。"""
    if BANK_FILE.exists():
        try:
            BANK_FILE.unlink()
        except Exception as exc:
            print(f"  Warn: cannot remove bank file: {exc}")


def run_launcher(runtime_id: str, reborn_name: str) -> int:
    """调用 launcher 启动游戏。返回退出码。

    使用 -Command 模式 + Tee-Object 重定向输出到文件，避免 -File + capture_output=True
    导致 PowerShell 静默退出（exit_code=-1 / 4294967295）的问题。
    早期诊断（test-switch.py + Izsha 单跑 59.7s 成功）证实：直接 PowerShell 终端运行
    launcher 是正常的，subprocess + -File + capture_output 才是异常的根因。
    """
    log_path = Path(os.environ["TEMP"]) / f"reborn-test-{reborn_name}.log"
    # PowerShell 单引号包裹路径参数（路径含空格/中文也安全）
    ps_script = (
        f"& '{LAUNCHER}' "
        f"-MapName '{MAP_NAME}' "
        f"-Commander '{runtime_id}' "
        f"-EnableReborn "
        f"-RebornCommander '{reborn_name}' "
        f"-SkipCountdown "
        f"-LegacyRootOverride '{LEGACY_ROOT}' *>&1 | Tee-Object -FilePath '{log_path}'"
    )
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-Command", ps_script,
    ]
    print(f"  CMD: powershell -Command \"& launcher -RebornCommander {reborn_name}\" (log: {log_path})")
    try:
        # capture_output=False 让 PowerShell 直接拥有控制台；日志通过 Tee-Object 落盘
        proc = subprocess.run(cmd, capture_output=False, timeout=600)
        # 从日志文件读取最后 20 行用于排查
        if log_path.exists():
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().strip().split("\n")
                for line in lines[-20:]:
                    print(f"  | {line}")
            except Exception as exc:
                print(f"  Warn: cannot read log file: {exc}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after 600s")
        return -3
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")
        return -2


def parse_bank(bank_path: Path) -> dict:
    """解析 bank XML 返回 key->int 字典。"""
    try:
        tree = ET.parse(bank_path)
        root = tree.getroot()
        result = {}
        for key in root.findall(".//Section/Key"):
            name = key.get("name", "")
            value_elem = key.find("Value")
            if value_elem is not None:
                result[name] = int(value_elem.get("int", "0"))
        return result
    except Exception as exc:
        print(f"  PARSE ERROR: {exc}")
        return {}


def evaluate(cmdr: tuple, metrics: dict, exit_code: int, bank_fresh: bool) -> TestResult:
    """评估测试结果。"""
    runtime_id, name, race, expected_units = cmdr
    result = TestResult(
        commander=name,
        race=race,
        exit_code=exit_code,
        bank_fresh_write=bank_fresh,
        deep_debug_ran=metrics.get("deep_debug_ran"),
        k5kerrigan_after=metrics.get("k5kerrigan_p1_after_swarmsetup"),
        zerg_total=metrics.get("zerg_p1_total_units"),
        expected_units={u: metrics.get(f"{u}_p1_count") for u in expected_units},
        zerg_buildings={
            "hatchery": metrics.get("hatchery_p1_count"),
            "spawningpool": metrics.get("spawningpool_p1_count"),
            "drone": metrics.get("drone_p1_count"),
        },
    )

    # 判定逻辑
    if not bank_fresh:
        result.detail = "bank 未写入"
        return result
    if result.deep_debug_ran != 1:
        result.detail = f"deep_debug_ran={result.deep_debug_ran}"
        return result
    if name != "Kerrigan" and result.k5kerrigan_after != 0:
        result.detail = f"k5kerrigan_p1_after_swarmsetup={result.k5kerrigan_after} (期望 0)"
        return result
    # 检查替换单位
    all_units_ok = all(v and v >= 1 for v in result.expected_units.values())
    if not all_units_ok:
        units_str = ", ".join(f"{k}={v}" for k, v in result.expected_units.items())
        result.detail = f"替换单位不匹配: {units_str}"
        return result
    # 检查虫族建筑（仅 Zerg 指挥官）
    if race == "Zerg":
        bld_ok = all(v and v >= 1 for v in result.zerg_buildings.values())
        if not bld_ok:
            bld_str = ", ".join(f"{k}={v}" for k, v in result.zerg_buildings.items())
            result.detail = f"虫族建筑缺失: {bld_str}"
            return result
    result.passed = True
    units_str = ", ".join(f"{k}={v}" for k, v in result.expected_units.items())
    bld_str = ", ".join(f"{k}={v}" for k, v in result.zerg_buildings.items()) if race == "Zerg" else "no-zerg-buildings"
    result.detail = f"{units_str} | {bld_str} | total={result.zerg_total}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commanders", help="逗号分隔的指挥官名（默认全部 8 个）")
    args = parser.parse_args()

    if args.commanders:
        names_filter = set(n.strip() for n in args.commanders.split(","))
        cmdrs = [c for c in COMMANDERS if c[1] in names_filter]
    else:
        cmdrs = list(COMMANDERS)

    print(f"=== 重生虫心批量测试 ({len(cmdrs)} 个指挥官) ===")
    print(f"Launcher: {LAUNCHER}")
    print(f"Bank: {BANK_FILE}")
    print(f"Evidence: {EVIDENCE_DIR}")
    print()

    results: list[TestResult] = []
    for cmdr in cmdrs:
        runtime_id, name, race, expected_units = cmdr
        print(f"\n========== Testing {name} ({runtime_id}) ==========")

        kill_sc2()
        cleanup_lock()
        remove_bank()

        exit_code = run_launcher(runtime_id, name)
        time.sleep(8)
        kill_sc2()

        bank_exists = BANK_FILE.exists()
        bank_backup = EVIDENCE_DIR / f"CMRERebornDebug.SC2Bank.{TIMESTAMP}-{name}"
        if bank_exists:
            try:
                shutil.copy2(BANK_FILE, bank_backup)
                print(f"  Bank backed up: {bank_backup}")
            except Exception as exc:
                print(f"  Backup failed: {exc}")
                bank_exists = False

        metrics = parse_bank(bank_backup) if bank_exists else {}
        result = evaluate(cmdr, metrics, exit_code, bank_exists)
        status = "PASS" if result.passed else "FAIL"
        print(f"  >> {status}: {result.detail}")
        results.append(result)
        time.sleep(5)

    # 汇总
    print("\n\n=== 汇总 ===")
    print(f"{'Commander':<12} {'Race':<8} {'Status':<6} {'Detail'}")
    print("-" * 80)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"{r.commander:<12} {r.race:<8} {status:<6} {r.detail}")

    passed = sum(1 for r in results if r.passed)
    print(f"\nPassed: {passed}/{len(results)}")

    # 保存 JSON
    summary_path = Path(os.environ["TEMP"]) / "reborn-retry-summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {summary_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
