"""Transport Verdict 聚合器 — P0 传输闸门最终判定。

汇总三种 transport probe 的结果，生成 transport-verdict.json：
  - BankReload（首选）
  - SC2API Chat（备用）
  - Input fallback（最后手段）

判定逻辑（依据计划）：
  - 没有任何通道通过则停止后续开发
  - 至少一个通道通过即继续 P1
  - 保存原始请求、Bank、API/输入日志、时间戳与 ScriptError 差异
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def check_script_errors() -> dict:
    """检查本次启动是否有新增 ScriptError。"""
    game_logs = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
    if not game_logs.exists():
        return {"checked": False, "reason": "GameLogs 目录不存在"}
    errors = list(game_logs.glob("ScriptError.*.txt"))
    return {
        "checked": True,
        "error_count": len(errors),
        "error_files": [p.name for p in errors[-5:]],  # 最近 5 个
        "no_new_errors": len(errors) == 0,
    }


def aggregate_verdict(out_dir: Path) -> dict:
    """聚合三种 transport probe 结果。"""
    bank_result_path = out_dir / "bank-probe-result.json"
    chat_result_path = out_dir / "chat-probe-result.json"
    input_result_path = out_dir / "input-probe-result.json"

    bank_result = json.loads(bank_result_path.read_text(encoding="utf-8")) if bank_result_path.exists() else None
    chat_result = json.loads(chat_result_path.read_text(encoding="utf-8")) if chat_result_path.exists() else None
    input_result = json.loads(input_result_path.read_text(encoding="utf-8")) if input_result_path.exists() else None

    script_errors = check_script_errors()

    # 判定：至少一个 transport 通过且无新 ScriptError
    bank_passed = bank_result and bank_result.get("verdict") == "passed"
    chat_passed = chat_result and chat_result.get("verdict") == "passed"
    input_passed = input_result and input_result.get("verdict") in ("passed", "degraded")

    any_passed = bool(bank_passed or chat_passed or input_passed)
    no_errors = script_errors.get("no_new_errors", False)

    overall = "passed" if (any_passed and no_errors) else "blocked"

    verdict = {
        "phase": "P0-transport",
        "timestamp": __import__("time").strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "transports": {
            "bank_reload": {
                "status": "passed" if bank_passed else "failed" if bank_result else "not_run",
                "preferred": True,
                "result": bank_result,
            },
            "sc2api_chat": {
                "status": "passed" if chat_passed else "failed" if chat_result else "not_run",
                "preferred": False,
                "result": chat_result,
            },
            "input_fallback": {
                "status": "passed" if input_passed else "failed" if input_result else "not_run",
                "preferred": False,
                "result": input_result,
            },
        },
        "script_errors": script_errors,
        "selected_transport": "bank_reload" if bank_passed else ("sc2api_chat" if chat_passed else ("input_fallback" if input_passed else None)),
        "verdict": overall,
        "can_proceed_to_p1": overall == "passed",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transport-verdict.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=str, default="artifacts/galaxy-vibe/p0-transport")
    args = parser.parse_args()
    result = aggregate_verdict(Path(args.out_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["verdict"] == "passed" else 1)
