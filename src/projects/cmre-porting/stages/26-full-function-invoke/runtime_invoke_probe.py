"""Stage 26 运行时验收探针 — 类型族抽样 + 只读普查 + ScriptError 门。

需要真实 SC2（approved launcher + 亡者之夜 staged map）。本机无 SC2 时使用
--plan-only 产出抽样/普查选择清单作为准备证据；有 SC2 时执行：

  1. 分档放量（配合 overlay -InvokeTier 100/1000/0，每档记录编译时间与体积）
  2. python runtime_invoke_probe.py --sample          # 类型族抽样
  3. python runtime_invoke_probe.py --census --budget 200 --timeout 3.0
  4. ScriptError 门：launcher 自带 Assert-CmreNoNewScriptErrors（同窗口零新增）

普查口径（如实分类，不伪装成功）：
  - 候选 = 返回非 void 且参数全为基础类型的生成函数（无法静态证明无副作用，
    报告中按名称前缀分类：Get/Query/Count/Has/Is 视为观察类，其余视为未知）；
  - 句柄/structref 参数族不进普查（必然依赖登记表，归入抽样）；
  - funcref 参数族仅用静态查值表收录值抽样，未收录值结构化拒绝。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))
sys.path.insert(0, str(ROOT / "tools" / "galaxy-vibe"))

PLAN_PATH = ROOT / "artifacts" / "projects" / "cmre-porting" / "stage26-full-function-invoke" / "invoke-plan.json"
ART_DIR = ROOT / "artifacts" / "projects" / "cmre-porting" / "stage26-full-function-invoke" / "runtime"

BASIC_TYPES = {"int", "fixed", "bool", "string", "text"}
OBSERVATIONAL_PREFIXES = ("Get", "Query", "Count", "Has", "Is", "Find", "Test")


def load_plan() -> dict:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def bare_name(name: str) -> str:
    # libXXXX_gf_Foo / libNtve_gf_Foo → Foo；其余原样
    if "_gf_" in name:
        return name.rsplit("_gf_", 1)[1]
    return name


def default_args(fn: dict) -> dict:
    args = {}
    for param in fn["params"]:
        arg = param["arg"]
        ptype = param["type"]
        if ptype == "int":
            args[arg] = 0
        elif ptype == "fixed":
            args[arg] = 0.0
        elif ptype == "bool":
            args[arg] = 0
        elif ptype == "string" or ptype == "text":
            args[arg] = ""
        elif ptype == "point":
            args[arg] = "xy:0.0,0.0"
        elif ptype == "unitgroup":
            args[arg] = "empty:"
        elif ptype == "playergroup":
            args[arg] = "all:"
        elif ptype == "region":
            args[arg] = "entire_map:"
        elif ptype == "timer":
            args[arg] = "create:"
        elif ptype == "unitfilter":
            args[arg] = "zero:"
        elif ptype == "color":
            args[arg] = "rgb:255,255,255"
        elif param["class"] == "funcref":
            args[arg] = "__FUNCREF_SAMPLE__"
        else:
            args[arg] = "id:1"
    return args


def build_type_family_samples(plan: dict) -> list[dict]:
    """每种参数/返回类型族至少 1 个代表函数（计划验收项 4.1）。"""
    samples: dict[str, dict] = {}

    def take(key: str, fn: dict) -> None:
        if key not in samples:
            samples[key] = {
                "family": key,
                "function_id": fn["function_id"],
                "galaxy_name": fn["name"],
                "args": default_args(fn),
            }

    funcref_candidates = plan["funcref_candidates"]
    for fn in plan["functions"]:
        take(f"return:{fn['return_class']}:{fn['return_type']}" if fn["return_class"] != "basic"
             else f"return:basic:{fn['return_type']}", fn)
        for param in fn["params"]:
            key = f"param:{param['class']}:{param['type']}"
            sample = samples.get(key)
            if sample is None:
                take(key, fn)
            if param["class"] == "funcref" and funcref_candidates:
                samples[key]["args"][param["arg"]] = funcref_candidates[0]
    return sorted(samples.values(), key=lambda item: item["family"])


def build_census_candidates(plan: dict, budget: int) -> list[dict]:
    """只读普查候选：返回非 void、参数全基础类型；观察类优先。"""
    candidates = []
    for fn in plan["functions"]:
        if fn["return_type"] == "void":
            continue
        if not all(p["type"] in BASIC_TYPES for p in fn["params"]):
            continue
        category = "observational" if bare_name(fn["name"]).startswith(OBSERVATIONAL_PREFIXES) else "unknown_side_effect"
        candidates.append({
            "function_id": fn["function_id"],
            "galaxy_name": fn["name"],
            "category": category,
            "args": default_args(fn),
        })
    candidates.sort(key=lambda item: (0 if item["category"] == "observational" else 1, item["function_id"]))
    return candidates[:budget]


def write_evidence(name: str, payload: dict) -> Path:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    path = ART_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def run_live(entries: list[dict], timeout: float) -> dict:
    from host.vibe_host import VibeHost  # noqa: E402

    host = VibeHost()
    host.start_session()
    results = []
    try:
        for entry in entries:
            started = time.perf_counter()
            response = host.invoke_function(entry["function_id"], entry["args"], timeout=timeout)
            results.append({
                **entry,
                "ok": response.is_ok,
                "error_code": response.error_code,
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "payload": response.payload if response.is_ok else {},
            })
    finally:
        host.close()
    summary = {
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "by_error_code": {},
    }
    for result in results:
        if not result["ok"]:
            summary["by_error_code"][result["error_code"]] = summary["by_error_code"].get(result["error_code"], 0) + 1
    return {"summary": summary, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 26 runtime invoke probe")
    parser.add_argument("--sample", action="store_true", help="执行类型族抽样")
    parser.add_argument("--census", action="store_true", help="执行只读普查")
    parser.add_argument("--plan-only", action="store_true", help="仅产出选择清单（无 SC2）")
    parser.add_argument("--budget", type=int, default=200, help="普查预算上限")
    parser.add_argument("--timeout", type=float, default=3.0, help="单次调用超时（秒）")
    options = parser.parse_args()

    plan = load_plan()
    samples = build_type_family_samples(plan)
    census = build_census_candidates(plan, options.budget)

    if options.plan_only or not (options.sample or options.census):
        path = write_evidence("probe-selection.json", {
            "stage": "26-full-function-invoke",
            "evidence_type": "runtime-preparation",
            "type_family_samples": samples,
            "census_budget": options.budget,
            "census_candidates": len(census),
            "census_observational": sum(1 for c in census if c["category"] == "observational"),
            "note": "live execution requires SC2 (approved launcher + staged 亡者之夜)",
        })
        print(f"selection evidence: {path}")
        print(f"type-family samples: {len(samples)}; census candidates: {len(census)}")
        return

    if options.sample:
        outcome = run_live(samples, options.timeout)
        path = write_evidence("type-family-sampling.json", outcome)
        print(f"type-family sampling: {path} ok={outcome['summary']['ok']}/{outcome['summary']['total']}")
    if options.census:
        outcome = run_live(census, options.timeout)
        path = write_evidence("readonly-census.json", outcome)
        print(f"readonly census: {path} ok={outcome['summary']['ok']}/{outcome['summary']['total']}")


if __name__ == "__main__":
    main()
