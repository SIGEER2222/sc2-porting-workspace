#!/usr/bin/env python3
"""Vibe 动态诊断脚本：跑期望值表，输出 PASS/FAIL 报告。

流程：reset → set_level(可选) → spawn → query_unit_tags → query_unit_attrs → assert。
全部走 VibeHost Bank RPC，不直接调 SC2 API。

用法:
    python vibe-diagnose.py --map <map_path> --scenario <expectation.json> [--port 8119]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VIBE_ROOT = REPO_ROOT / "tools" / "galaxy-vibe"
sys.path.insert(0, str(VIBE_ROOT))

from host.vibe_host import VibeHost, RpcResponse  # noqa: E402


def evaluate_assert(actual: dict, expected: dict) -> tuple[bool, dict]:
    """评估断言。expected 格式: {"armor": "== 3", "tech_tree_unlocked": true}。
    返回 (is_pass, details)。
    """
    details = {}
    all_pass = True
    for key, cond in expected.items():
        act_val = actual.get(key)
        ok = False
        if isinstance(cond, bool):
            # 兼容 0/1 与 True/False
            ok = (act_val == cond) or (act_val == (1 if cond else 0))
        elif isinstance(cond, str) and cond.startswith(("==", "!=", ">", "<", ">=", "<=")):
            op = cond.split()[0]
            try:
                target = float(cond.split()[1])
                act_num = float(act_val) if act_val is not None and act_val != "unavailable" else None
            except (ValueError, IndexError):
                act_num = None
                target = None
            if act_num is None:
                ok = False
            elif op == "==":
                ok = act_num == target
            elif op == "!=":
                ok = act_num != target
            elif op == ">":
                ok = act_num > target
            elif op == "<":
                ok = act_num < target
            elif op == ">=":
                ok = act_num >= target
            elif op == "<=":
                ok = act_num <= target
        else:
            ok = (act_val == cond)
        details[key] = {"actual": act_val, "expected": cond}
        if not ok:
            all_pass = False
    return all_pass, details


def run_scenario(host: VibeHost, scenario: dict, map_path: str) -> dict:
    """跑一个期望值表场景，返回报告 dict。"""
    checks_result = []
    for check in scenario.get("checks", []):
        name = check["name"]
        record = {
            "name": name, "status": "PASS", "actual": {},
            "expected": check.get("assert", {}),
            "error_code": "OK", "notes": "",
        }

        # a. reset
        host.reset_scenario()

        # b. set_level（可选）
        if check.get("upgrade"):
            resp = host.upgrade_set_level(
                player=check["player"], upgrade=check["upgrade"],
                level=check.get("upgrade_level", 1))
            if not resp.is_ok:
                record["status"] = "ERROR"
                record["error_code"] = resp.error_code
                record["notes"] = f"upgrade.set_level 失败: {resp.error_code}"
                checks_result.append(record)
                continue

        # c. spawn
        spawn_at = check.get("spawn_at", [0, 0])
        resp = host.spawn_units(
            unit_type=check["unit_type"], count=1, player=check["player"],
            x=float(spawn_at[0]), y=float(spawn_at[1]))
        if not resp.is_ok:
            record["status"] = "ERROR"
            record["error_code"] = resp.error_code
            record["notes"] = f"unit.spawn 失败: {resp.error_code}"
            checks_result.append(record)
            continue

        # d. query_unit_tags 拿 spawned unit 的 tag
        resp = host.query_unit_tags(player=check["player"], unit_type=check["unit_type"])
        if not resp.is_ok or not resp.payload.get("tags"):
            record["status"] = "ERROR"
            record["error_code"] = resp.error_code
            record["notes"] = "query.unit_tags 无 tag 返回"
            checks_result.append(record)
            continue
        unit_tag = resp.payload["tags"][0]

        # e. query_unit_attrs
        attrs_resp = host.query_unit_attrs(unit_tag=unit_tag)
        if not attrs_resp.is_ok:
            record["status"] = "ERROR"
            record["error_code"] = attrs_resp.error_code
            record["notes"] = f"query.unit_attrs 失败: {attrs_resp.error_code}"
            checks_result.append(record)
            continue
        actual = dict(attrs_resp.payload)

        # e2. tech_tree_check（可选，若 assert 含 tech_tree_unlocked）
        if "tech_tree_unlocked" in check.get("assert", {}):
            tech_resp = host.tech_tree_check(player=check["player"], upgrade=check["upgrade"])
            if tech_resp.is_ok:
                actual["tech_tree_unlocked"] = tech_resp.payload.get("unlocked", 0)
            else:
                actual["tech_tree_unlocked"] = 0

        # f. evaluate assert
        is_pass, _details = evaluate_assert(actual, check.get("assert", {}))
        record["actual"] = actual
        record["status"] = "PASS" if is_pass else "FAIL"
        # 预期失败路径处理
        if check.get("expect_status") == "FAIL" and record["status"] == "FAIL":
            record["status"] = "PASS"
            record["notes"] = "预期失败路径，FAIL 已正确触发"
        checks_result.append(record)

    summary = {
        "total": len(checks_result),
        "pass": sum(1 for c in checks_result if c["status"] == "PASS"),
        "fail": sum(1 for c in checks_result if c["status"] == "FAIL"),
        "error": sum(1 for c in checks_result if c["status"] == "ERROR"),
    }
    return {
        "schemaVersion": 1,
        "scenario": scenario.get("scenario", "unknown"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "map": map_path,
        "summary": summary,
        "checks": checks_result,
    }


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    """写 report.json + report.md。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    s = report["summary"]
    lines = [
        f"# Vibe 诊断报告 — {report['scenario']}",
        "",
        f"- 地图: `{report['map']}`",
        f"- 时间: {report['timestamp']}",
        f"- 总计: {s['total']}  PASS: {s['pass']}  FAIL: {s['fail']}  ERROR: {s['error']}",
        "",
        "| check | status | actual | expected | notes |",
        "|---|---|---|---|---|",
    ]
    for c in report["checks"]:
        act = json.dumps(c["actual"], ensure_ascii=False)
        exp = json.dumps(c["expected"], ensure_ascii=False)
        lines.append(f"| {c['name']} | {c['status']} | {act} | {exp} | {c['notes']} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Vibe 动态诊断脚本")
    parser.add_argument("--map", required=True, help="SC2 可见的本地地图路径")
    parser.add_argument("--scenario", required=True, help="期望值表 JSON 路径")
    parser.add_argument("--port", type=int, default=8119, help="SC2 API 端口")
    parser.add_argument("--out", default="", help="报告输出目录（默认 artifacts/vibe-diagnose/<ts>）")
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else REPO_ROOT / "artifacts" / "vibe-diagnose" / ts

    host = VibeHost(sc2_port=args.port)
    if not host.start_session():
        print("[diagnose] start_session 失败", file=sys.stderr)
        return 2
    if not host.connect_sc2(map_path=args.map):
        print("[diagnose] connect_sc2 失败", file=sys.stderr)
        return 2

    print(f"[diagnose] 跑场景: {scenario.get('scenario', 'unknown')}")
    report = run_scenario(host, scenario, args.map)
    json_path, md_path = write_report(report, out_dir)
    host.close()

    s = report["summary"]
    print(f"[diagnose] 完成: total={s['total']} pass={s['pass']} fail={s['fail']} error={s['error']}")
    print(f"[diagnose] 报告: {json_path}")
    print(f"[diagnose] 报告: {md_path}")
    return 0 if s["fail"] == 0 and s["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
