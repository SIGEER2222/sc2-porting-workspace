"""Offline status snapshot for the SC2 Vibe workflow.

This checker is intentionally static/offline: it does not launch SC2, does not
send SC2API requests, and does not mutate maps or mods. It answers whether the
local workflow surface is assembled enough to support the intended Vibe loop:
intent -> scenario -> simulator / Galaxy runtime -> assertions -> evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable


REQUIRED_SKILLS = (
    "galaxy-language-fundamentals",
    "galaxy-triggers-and-functions",
    "galaxy-units-and-groups",
    "galaxy-debug-data-catalog",
    "galaxy-game-systems",
    "sc2-units-reference",
    "sc2data-units-abilities",
    "sc2data-effects-weapons",
    "vibe-operator-workflow",
)


@dataclass
class Check:
    id: str
    status: str
    detail: str
    evidence_type: str = "static"
    path: str | None = None


@dataclass
class Lane:
    id: str
    status: str
    summary: str
    checks: list[Check]


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def path_check(root: Path, check_id: str, path: str, required: bool = True, detail: str = "") -> Check:
    p = root / path
    exists = p.exists()
    status = "pass" if exists else ("fail" if required else "warn")
    if not detail:
        detail = "present" if exists else "missing"
    return Check(check_id, status, detail, path=path)


def path_label(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def aggregate(checks: Iterable[Check]) -> str:
    statuses = [c.status for c in checks]
    if any(s == "fail" for s in statuses):
        return "fail"
    if any(s == "warn" for s in statuses):
        return "warn"
    return "pass"


def simulator_lane(root: Path) -> Lane:
    checks: list[Check] = [
        path_check(root, "simulator.src", "reference/sc2-ally-bot/src/sc2_simulator", True),
        path_check(root, "simulator.tests", "reference/sc2-ally-bot/tests/sc2_simulator", True),
        path_check(root, "simulator.stage09", "src/projects/cmre-porting/stages/09-sim-semantic-completion/result.json", True),
        path_check(root, "simulator.stage10.coverage", "artifacts/projects/cmre-porting/stage10-post-acceptance-hardening/catalog-coverage-report.json", False),
    ]
    try:
        sys.path.insert(0, str(root / "reference/sc2-ally-bot/src"))
        from sc2_simulator.catalog.m7_units import m7_catalog  # type: ignore

        cat = m7_catalog()
        checks.append(Check(
            "simulator.import.m7_catalog",
            "pass",
            f"m7 catalog import ok; units={len(cat.units)}; upgrades={len(cat.upgrades)}; schema={cat.schema_version}",
        ))
    except Exception as exc:
        checks.append(Check("simulator.import.m7_catalog", "fail", f"import failed: {exc!r}"))
    return Lane(
        "simulator",
        aggregate(checks),
        "Headless deterministic rules runtime and regression surface.",
        checks,
    )


def project_vibe_lane(root: Path) -> Lane:
    required = [
        ("vibe.contracts", "src/projects/cmre-porting/vibe/contracts.py"),
        ("vibe.protocol", "src/projects/cmre-porting/vibe/protocol.py"),
        ("vibe.simulator_transport", "src/projects/cmre-porting/vibe/simulator_transport.py"),
        ("vibe.simulator_session", "src/projects/cmre-porting/vibe/simulator_session.py"),
        ("vibe.vibe_host", "src/projects/cmre-porting/vibe/vibe_host.py"),
        ("vibe.gate_verification", "src/projects/cmre-porting/vibe/gate_verification.py"),
        ("vibe.task_runner", "src/projects/cmre-porting/vibe/task_runner.py"),
        ("vibe.task_manifest", "src/projects/cmre-porting/vibe/task_manifest.py"),
        ("vibe.defend_policy", "src/projects/cmre-porting/vibe/defend_policy.py"),
        ("vibe.live_runner", "src/projects/cmre-porting/vibe/run_dead_of_night_live.py"),
    ]
    checks = [path_check(root, cid, p, True) for cid, p in required]
    for consumer in ("ally_ai", "mission_wave", "mod_dev", "tactical"):
        checks.append(path_check(root, f"vibe.consumer.{consumer}", f"src/projects/cmre-porting/vibe/consumers/{consumer}.py", True))
    return Lane(
        "project_vibe",
        aggregate(checks),
        "Project-owned intent, scenario, transport, consumer, and live-runner layer.",
        checks,
    )


def galaxy_runtime_lane(root: Path) -> Lane:
    required = [
        ("galaxy.entry.vibe_ps1", "tools/galaxy-vibe/vibe.ps1"),
        ("galaxy.repl", "tools/galaxy-vibe/galaxy_repl.py"),
        ("galaxy.kernel", "tools/galaxy-vibe/kernel/LibVibeKernel.galaxy"),
        ("galaxy.kernel.header", "tools/galaxy-vibe/kernel/LibVibeKernel_h.galaxy"),
        ("galaxy.schema.rpc", "tools/galaxy-vibe/schema/rpc-schema.json"),
        ("galaxy.schema.response", "tools/galaxy-vibe/schema/rpc-response-schema.json"),
        ("galaxy.observer", "tools/galaxy-vibe/observer/assertion_runner.py"),
        ("galaxy.visual", "tools/galaxy-vibe/visual_loop.py"),
        ("galaxy.cold_cycle", "tools/galaxy-vibe/cold_cycle.py"),
        ("galaxy.bundle", "tools/galaxy-vibe/evidence_bundle.py"),
        ("galaxy.validation", "tools/galaxy-vibe/run-all-validation.ps1"),
    ]
    checks = [path_check(root, cid, p, True) for cid, p in required]
    return Lane(
        "galaxy_runtime",
        aggregate(checks),
        "Hot/cold Galaxy Vibe runtime, REPL, assertion, visual, and evidence tooling.",
        checks,
    )


def parser_lane(root: Path) -> Lane:
    checks = [
        path_check(root, "parser.galaxy_toolkit", "reference/sc2-galaxy-toolkit", False, "registered read-only galaxy parser/toolkit source"),
        path_check(root, "parser.legacy_toolkit", "../合作指挥官-起义狂潮/scripts/sc2-editor-toolkit", False, "legacy dependency/catalog toolkit source"),
        path_check(root, "parser.map_extractor", "src/projects/cmre-porting/vibe/map_extractor.py", True, "project-side map extraction adapter"),
        path_check(root, "parser.static_validator", "tools/galaxy-vibe/cold/static_validator.py", True, "cold-loop static validator"),
    ]
    toolkit_present = (root / "reference/sc2-galaxy-toolkit").exists()
    checks.append(Check(
        "parser.classification",
        "pass" if toolkit_present else "warn",
        "present: registered read-only Galaxy toolkit is available"
        if toolkit_present
        else "degraded: registered Galaxy toolkit is absent; project map_extractor/static_validator remain available",
        evidence_type="static",
        path="reference/sc2-galaxy-toolkit",
    ))
    return Lane(
        "galaxy_parser",
        aggregate(checks),
        "Static Galaxy/catalog parsing and validation inputs for map-to-scenario extraction.",
        checks,
    )


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def runtime_vibe_lane(root: Path, artifacts_dir: Path | None = None) -> Lane:
    stage_root = artifacts_dir or (root / "artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack")
    summary_path = stage_root / "runtime-summary.json"
    assertions_path = stage_root / "assert-results.json"
    summary_label = path_label(root, summary_path)
    assertions_label = path_label(root, assertions_path)
    checks = [
        path_check(root, "runtime_vibe.launcher", "tools/galaxy-vibe/launch-galaxy-vibe.ps1", True),
        path_check(root, "runtime_vibe.script_error", "tools/galaxy-vibe/script_error_check.py", True),
        path_check(root, "runtime_vibe.summary", summary_label, True),
        path_check(root, "runtime_vibe.assertions", assertions_label, True),
    ]
    summary = _read_json(summary_path)
    if summary is None:
        checks.append(Check(
            "runtime_vibe.verdict",
            "fail",
            "runtime-summary.json is missing or invalid",
            evidence_type="runtime",
            path=summary_label,
        ))
    else:
        passed = (
            summary.get("status") == "PASS"
            and bool(summary.get("assert", {}).get("all_passed"))
            and int(summary.get("assert", {}).get("total", 0)) > 0
            and not bool(summary.get("script_error", {}).get("has_new_errors"))
        )
        checks.append(Check(
            "runtime_vibe.verdict",
            "pass" if passed else "fail",
            f"run={summary.get('run_id')}; status={summary.get('status')}; "
            f"assertions={summary.get('assert', {}).get('passed', 0)}/"
            f"{summary.get('assert', {}).get('total', 0)}; "
            f"script_errors={summary.get('script_error', {}).get('count', 0)}",
            evidence_type="runtime",
            path=summary_label,
        ))
    return Lane(
        "runtime_vibe",
        aggregate(checks),
        "Verified SC2 runtime contract, assertions, frame advance, and ScriptError gate.",
        checks,
    )


def evidence_bundle_lane(root: Path, bundle_file: Path | None = None) -> Lane:
    bundle_path_obj = bundle_file or (root / "artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/evidence-bundle.json")
    bundle_path = path_label(root, bundle_path_obj)
    bundle_check_id = "evidence_bundle.operator" if bundle_file else "evidence_bundle.stage13"
    checks = [
        path_check(root, "evidence_bundle.tool", "tools/galaxy-vibe/evidence_bundle.py", True),
        path_check(root, bundle_check_id, bundle_path, True),
    ]
    bundle = _read_json(bundle_path_obj)
    if bundle is None:
        checks.append(Check("evidence_bundle.verdict", "fail", "evidence bundle is missing or invalid", evidence_type="runtime", path=bundle_path))
    else:
        bundle_status = str(bundle.get("overall_status", "")).lower()
        status = "pass" if bundle_status in ("pass", "passed") else ("warn" if bundle_status == "carried-forward" else "fail")
        checks.append(Check(
            "evidence_bundle.verdict",
            status,
            f"overall_status={bundle.get('overall_status')}; items={len(bundle.get('items', []))}",
            evidence_type="runtime",
            path=bundle_path,
        ))
    return Lane(
        "evidence_bundle",
        aggregate(checks),
        "Evidence package connects manifest, launcher, assertions, ScriptError, and verdict outputs.",
        checks,
    )


def skills_lane(root: Path) -> Lane:
    skills_root = root / ".agents/skills"
    checks = [path_check(root, "skills.root", ".agents/skills", True)]
    present = set()
    if skills_root.exists():
        for skill_md in skills_root.glob("*/SKILL.md"):
            present.add(skill_md.parent.name)
    for skill in REQUIRED_SKILLS:
        status = "pass" if skill in present else "warn"
        checks.append(Check(
            f"skills.required.{skill}",
            status,
            "present" if status == "pass" else "missing required workflow guidance skill",
            path=f".agents/skills/{skill}/SKILL.md",
        ))
    checks.append(Check("skills.count", "pass", f"local skills discovered={len(present)}"))
    return Lane(
        "skills",
        aggregate(checks),
        "Repo-local Galaxy, SC2Data, and unit-reference guidance used by the workflow.",
        checks,
    )


def launcher_lane(root: Path) -> Lane:
    checks = [
        path_check(root, "launcher.dir", "tools/launchers", False, "SC2 launchers directory"),
        path_check(root, "launcher.galaxy_vibe", "tools/galaxy-vibe/launch-galaxy-vibe.ps1", True),
        path_check(root, "launcher.live_probe", "tools/launchers/run-live-runtime-probe.ps1", False),
        path_check(root, "launcher.script_error_check", "tools/galaxy-vibe/script_error_check.py", True),
    ]
    return Lane(
        "launchers",
        aggregate(checks),
        "Compliant SC2 startup and ScriptError verification surfaces.",
        checks,
    )


def build_report(
    root: Path,
    runtime_artifacts_dir: Path | None = None,
    evidence_bundle_file: Path | None = None,
) -> dict:
    lanes = [
        simulator_lane(root),
        project_vibe_lane(root),
        galaxy_runtime_lane(root),
        parser_lane(root),
        skills_lane(root),
        runtime_vibe_lane(root, runtime_artifacts_dir),
        evidence_bundle_lane(root, evidence_bundle_file),
        launcher_lane(root),
    ]
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for lane in lanes:
        counts[lane.status] += 1
    overall = "fail" if counts["fail"] else ("warn" if counts["warn"] else "pass")
    return {
        "schemaVersion": 1,
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "evidence_type": "static+runtime" if runtime_artifacts_dir or evidence_bundle_file else "static",
        "repo_root": str(root),
        "purpose": "SC2 Vibe workflow convergence status: simulator + Galaxy parser/runtime + skills + launchers.",
        "active_stage": (_read_json(root / "src/projects/cmre-porting/project.json") or {}).get("currentStage"),
        "overall": overall,
        "lane_counts": counts,
        "lanes": [asdict(lane) for lane in lanes],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline SC2 Vibe workflow status snapshot")
    parser.add_argument("--repo-root", default="", help="Repository root; defaults to script-relative root")
    parser.add_argument("--out", default="", help="Optional JSON output path")
    parser.add_argument("--runtime-artifacts-dir", default="", help="Override runtime evidence directory for this operator run")
    parser.add_argument("--evidence-bundle", default="", help="Override evidence-bundle.json for this operator run")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_script()
    runtime_artifacts_dir = Path(args.runtime_artifacts_dir).resolve() if args.runtime_artifacts_dir else None
    evidence_bundle_file = Path(args.evidence_bundle).resolve() if args.evidence_bundle else None
    report = build_report(root, runtime_artifacts_dir, evidence_bundle_file)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"SC2 Vibe workflow status: {report['overall']}")
        for lane in report["lanes"]:
            print(f"- {lane['id']}: {lane['status']} - {lane['summary']}")

    if report["overall"] == "fail":
        return 1
    if args.strict and report["overall"] == "warn":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
