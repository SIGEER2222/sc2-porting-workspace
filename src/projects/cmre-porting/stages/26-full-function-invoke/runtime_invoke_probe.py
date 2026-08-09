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


def open_host(map_path: str | None):
    """打开 VibeHost。给了 map_path 就由探针自己 CreateGame+JoinGame 把地图装进去。

    背景（2026-08-09 补齐）：探针原本只走 Bank RPC，默认「地图已被 launcher 装好」。
    但 launcher 的 API 模式（-DebugMode/-ApiMinimal）刻意停在 CreateGame 之前
    （见 launch-cmre-alenger.ps1 "Host must CreateGame + JoinGame"），
    于是 SC2 停在主菜单、gen.* 永远 FUNCTION_NOT_IN_MAP。补 --map 后探针自足。
    """
    from host.vibe_host import VibeHost  # noqa: E402

    host = VibeHost()
    host.start_session()
    if map_path:
        if not host.connect_sc2(map_path=map_path):
            host.close()
            raise RuntimeError(f"connect_sc2 失败（地图未装载）: {map_path}")
    return host


def run_live(entries: list[dict], timeout: float, host=None, guard=None) -> dict:
    """执行一批调用，全程由环境哨兵看着。

    2026-08-09 教训：上一轮 tier100 抽样跑出 `ok=0/53` 全超时，被当成「gen bundle
    把 MapScript 搞挂了」查了一整轮编译闭包 —— 真相是运行到第 1 个调用时真人局
    启动、把 API 实例挤掉了，53 条记录全是对着空气发的。证据本身是噪声，却长得
    和真故障一模一样。所以：**一旦哨兵报警就立刻停**，剩下的调用不再执行，
    并在证据里如实标记 `usable_for_acceptance=false`，绝不让噪声混进验收。
    """
    owns_host = host is None
    if owns_host:
        host = open_host(None)
    owns_guard = guard is None
    if owns_guard:
        from env_guard import EnvGuard  # noqa: E402

        guard = EnvGuard()
        guard.baseline()
    results = []
    aborted = None
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
            # 只在失败后查哨兵：成功本身就是环境健在的最强证据，没必要付枚举开销
            if not response.is_ok:
                tripped = guard.check()
                if tripped is not None:
                    aborted = {**tripped, "aborted_after": len(results), "planned": len(entries)}
                    break
    finally:
        if owns_host:
            host.close()
    summary = {
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "by_error_code": {},
    }
    for result in results:
        if not result["ok"]:
            summary["by_error_code"][result["error_code"]] = summary["by_error_code"].get(result["error_code"], 0) + 1
    env_verdict = guard.verdict(any_ok=summary["ok"] > 0)
    if aborted is not None:
        env_verdict = {**env_verdict, **aborted, "usable_for_acceptance": False}
    return {"summary": summary, "results": results, "env": env_verdict}


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 26 runtime invoke probe")
    parser.add_argument("--sample", action="store_true", help="执行类型族抽样")
    parser.add_argument("--census", action="store_true", help="执行只读普查")
    parser.add_argument("--plan-only", action="store_true", help="仅产出选择清单（无 SC2）")
    parser.add_argument("--budget", type=int, default=200, help="普查预算上限")
    parser.add_argument("--timeout", type=float, default=3.0, help="单次调用超时（秒）")
    parser.add_argument("--map", dest="map_path", default="",
                        help="staged live 地图路径；给了就由探针 CreateGame+JoinGame 装图")
    parser.add_argument("--tier", type=int, default=-1,
                        help="本次 run 对应的 -InvokeTier 档位（仅写入证据用于对账）")
    parser.add_argument("--suffix", default="", help="证据文件名后缀，用于分档留档不覆盖")
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

    suffix = f"-{options.suffix}" if options.suffix else ""
    run_meta = {
        "invoke_tier": options.tier,
        "map_path": options.map_path or None,
        "map_loaded_by_probe": bool(options.map_path),
        "timeout_s": options.timeout,
    }

    from env_guard import EnvGuard  # noqa: E402

    host = open_host(options.map_path or None)
    # 基线必须在装图之后取：CreateGame 期间 SC2 可能重启渲染子进程，
    # 装图前取基线会把正常的进程变动误判成 env_preempted。
    guard = EnvGuard()
    run_meta["env_baseline"] = guard.baseline()
    exit_code = 0
    try:
        if options.sample:
            outcome = run_live(samples, options.timeout, host=host, guard=guard)
            outcome["run"] = run_meta
            path = write_evidence(f"type-family-sampling{suffix}.json", outcome)
            exit_code |= _report("type-family sampling", path, outcome)
        if options.census:
            outcome = run_live(census, options.timeout, host=host, guard=guard)
            outcome["run"] = run_meta
            path = write_evidence(f"readonly-census{suffix}.json", outcome)
            exit_code |= _report("readonly census", path, outcome)
    finally:
        host.close()
    if exit_code:
        raise SystemExit(exit_code)


def _report(label: str, path: Path, outcome: dict) -> int:
    """打印结果并把「环境噪声」和「真失败」在退出码上分开。

    退出码 0=通过，1=真失败（代码问题，值得查），2=环境不可用（结果作废，重跑即可）。
    分开是为了让上层调度脚本能自动决定「重排档期」还是「叫人来看代码」，
    而不是一律当成失败去改代码 —— 那正是上一轮浪费掉的路。
    """
    summary = outcome["summary"]
    env = outcome.get("env", {})
    verdict = env.get("verdict", "unknown")
    usable = env.get("usable_for_acceptance", True)
    print(f"{label}: {path} ok={summary['ok']}/{summary['total']} env={verdict}")
    if not usable:
        print(f"  [ENV] {env.get('reason', '')} :: {env.get('hint', '')}")
        if "aborted_after" in env:
            print(f"  [ENV] 已在第 {env['aborted_after']}/{env['planned']} 项中止，"
                  f"剩余未执行（避免刷入噪声证据）")
        print("  [ENV] 本轮结果不可用于验收")
        return 2
    return 0 if summary["ok"] == summary["total"] else 1


if __name__ == "__main__":
    main()
