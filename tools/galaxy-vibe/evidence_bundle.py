"""Vibe 证据包生成器 — 单命令收集完整证据，生成 evidence-bundle.json + manifest.json。

依据 sc2-vibe完整实施计划.md P7 验收:
  - 一条命令生成完整证据包
  - 阶段 log 记录命令与 static/runtime/visual/inference 证据，满足 Completion Gate

证据收集范围:
  - static: schema 文件、Kernel Galaxy 源码、whitelist.json、tests
  - runtime: requests.ndjson、session_state.json、Bank 副本、GameLogs ScriptError 差异
  - visual: before/after/failed/reset PNG + manifest
  - inference: 静态自检结果、soak report、performance report、cleanup report

调用方式:
  python tools/galaxy-vibe/evidence_bundle.py --run-id <id> --out-dir <path>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
GALAXY_VIBE_ROOT = Path(__file__).resolve().parent


@dataclass
class EvidenceItem:
    """单条证据条目。"""
    category: str  # static | runtime | visual | inference
    name: str
    source_path: str
    sha256: str = ""
    size_bytes: int = 0
    copied_to: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceBundle:
    """完整证据包。"""
    run_id: str
    generated_at: str
    bundle_dir: str
    items: list[EvidenceItem] = field(default_factory=list)
    phase_status: dict = field(default_factory=dict)
    overall_status: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "bundle_dir": self.bundle_dir,
            "overall_status": self.overall_status,
            "phase_status": self.phase_status,
            "items": [item.to_dict() for item in self.items],
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


class EvidenceBundler:
    """收集并归档单次 run 的全部证据。"""

    # 关键 static 证据（相对 galaxy-vibe 根目录）
    STATIC_PATHS = [
        ("rpc-schema", "schema/rpc-schema.json"),
        ("rpc-response-schema", "schema/rpc-response-schema.json"),
        ("kernel-galaxy", "kernel/LibVibeKernel.galaxy"),
        ("kernel-header", "kernel/LibVibeKernel_h.galaxy"),
        ("whitelist", "kernel/whitelist.json"),
        ("test-kernel", "tests/test_kernel.py"),
    ]

    # Root-level artifacts from a stage output directory. Stage 13 uses this path
    # so the bundle can include launcher/assertion/ScriptError evidence instead
    # of only collecting generic artifacts/galaxy-vibe/run-* files.
    ROOT_ARTIFACTS = [
        ("runtime-summary", "runtime-summary.json", "runtime"),
        ("launcher-exit", "launcher-exit.json", "runtime"),
        ("launcher-stdout", "launcher-stdout.txt", "runtime"),
        ("launcher-stderr", "launcher-stderr.txt", "runtime"),
        ("assert-results", "assert-results.json", "runtime"),
        ("script-error-verdict", "script-error-verdict.json", "runtime"),
        ("script-error-verdict-stage13", "script-error-verdict-stage13.json", "runtime"),
        ("vibe-verdict", "vibe-verdict.json", "runtime"),
        ("visual-verdict", "visual-verdict.json", "visual"),
        ("pack-sc2map-exit", "pack-sc2map-exit.json", "static"),
        ("pack-sc2map-stdout", "pack-sc2map-stdout.txt", "static"),
        ("pack-sc2map-stderr", "pack-sc2map-stderr.txt", "static"),
        ("stage12-manifest", "stage12-manifest.json", "static"),
        ("stage12-summary", "stage12-summary.json", "static"),
        ("stage12-task-live", "stage12-task.live.json", "static"),
        ("stage12-runtime-recipe", "stage12-runtime-recipe.json", "static"),
        ("stage12-scenario-vtest", "stage12-scenario.vtest", "static"),
        ("runtime-scenario-vtest", "runtime-scenario.vtest", "runtime"),
    ]

    def __init__(
        self,
        run_id: str,
        out_dir: Path,
        artifacts_dir: Optional[Path] = None,
        gamelogs_dir: Optional[Path] = None,
    ):
        self.run_id = run_id
        self.out_dir = Path(out_dir)
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else (REPO_ROOT / "artifacts" / "galaxy-vibe")
        self.gamelogs_dir = Path(gamelogs_dir) if gamelogs_dir else Path.home() / "Documents" / "StarCraft II" / "GameLogs"
        self.bundle_root = self.out_dir / f"bundle-{run_id}"

    def build(self, phase_status: Optional[dict] = None) -> EvidenceBundle:
        """收集所有证据并构建 bundle。"""
        self.bundle_root.mkdir(parents=True, exist_ok=True)
        items: list[EvidenceItem] = []

        # 1. static 证据
        for name, rel in self.STATIC_PATHS:
            src = GALAXY_VIBE_ROOT / rel
            self._collect_file(items, "static", name, src)

        # 2. stage/root 证据（Stage 13 等阶段目录的顶层报告）
        for name, rel, category in self.ROOT_ARTIFACTS:
            self._collect_file(items, category, name, self.artifacts_dir / rel)

        # 3. runtime 证据（artifacts 下的 run-* 目录、bank、session state）
        run_dir = self.artifacts_dir / f"run-{self.run_id}"
        if run_dir.exists():
            for f in run_dir.glob("**/*"):
                if f.is_file():
                    self._collect_file(items, "runtime", f"run/{f.relative_to(run_dir)}", f)

        # 4. ScriptError 差异（来自 GameLogs）
        if self.gamelogs_dir.exists():
            for f in self.gamelogs_dir.glob("ScriptError.*.txt"):
                # 仅收集最近 24h 内的
                mtime = f.stat().st_mtime
                if time.time() - mtime < 86400:
                    self._collect_file(items, "runtime", f"gamelogs/{f.name}", f)

        # 5. visual 证据
        visual_dir = self.artifacts_dir / "visual"
        if visual_dir.exists():
            for f in visual_dir.glob("*.png"):
                self._collect_file(items, "visual", f"visual/{f.name}", f)
            manifest = visual_dir / "manifest.json"
            if manifest.exists():
                self._collect_file(items, "visual", "visual/manifest.json", manifest)

        # 6. inference 证据（soak / perf / cleanup 报告）
        for name in ("soak-report.json", "performance-report.json", "cleanup-report.json", "transport-verdict.json"):
            p = self.artifacts_dir / name
            if p.exists():
                self._collect_file(items, "inference", name, p)

        # 阶段状态
        phase_status = phase_status or {}
        values = [v for v in phase_status.values() if isinstance(v, str)]
        if not values:
            overall = "unknown"
        elif any(v in ("fail", "failed") for v in values):
            overall = "failed"
        elif all(v == "passed" for v in values):
            overall = "passed"
        elif any(v == "carried-forward" for v in values):
            overall = "carried-forward"
        else:
            overall = "unknown"

        bundle = EvidenceBundle(
            run_id=self.run_id,
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
            bundle_dir=str(self.bundle_root),
            items=items,
            phase_status=phase_status,
            overall_status=overall,
        )

        # 写 manifest + bundle.json
        self._write_manifest(items)
        bundle_path = self.bundle_root / "evidence-bundle.json"
        bundle.save(bundle_path)

        # 写 README
        self._write_readme(bundle)
        return bundle

    def _collect_file(self, items: list[EvidenceItem], category: str, name: str, src: Path) -> None:
        if not src.exists() or not src.is_file():
            return
        try:
            data = src.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
        except OSError:
            sha = ""
            data = b""

        # 复制到 bundle（保留相对结构）
        target_subdir = self.bundle_root / category
        target_subdir.mkdir(parents=True, exist_ok=True)
        target_name = src.name
        target_path = target_subdir / target_name
        # 避免重名覆盖：附加 sha 前 8 位
        if target_path.exists():
            target_path = target_subdir / f"{src.stem}-{sha[:8]}{src.suffix}"
        try:
            shutil.copy2(str(src), str(target_path))
        except OSError:
            pass

        items.append(EvidenceItem(
            category=category,
            name=name,
            source_path=str(src),
            sha256=sha,
            size_bytes=len(data),
            copied_to=str(target_path),
        ))

    def _write_manifest(self, items: list[EvidenceItem]) -> None:
        manifest_path = self.bundle_root / "manifest.json"
        manifest = {
            "run_id": self.run_id,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
            "total_items": len(items),
            "by_category": {
                cat: sum(1 for it in items if it.category == cat)
                for cat in ("static", "runtime", "visual", "inference")
            },
            "sha256_map": {it.name: it.sha256 for it in items},
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_readme(self, bundle: EvidenceBundle) -> None:
        readme_path = self.bundle_root / "README.md"
        lines = [
            f"# Evidence Bundle — {self.run_id}",
            "",
            f"- Generated: {bundle.generated_at}",
            f"- Overall: {bundle.overall_status}",
            f"- Total items: {len(bundle.items)}",
            "",
            "## Phase Status",
            "",
        ]
        for k, v in bundle.phase_status.items():
            lines.append(f"- {k}: {v}")
        lines.extend(["", "## Items", "", "| Category | Name | SHA256 (前16) | Size |", "|---|---|---|---|"])
        for it in bundle.items:
            lines.append(f"| {it.category} | {it.name} | `{it.sha256[:16]}` | {it.size_bytes} B |")
        readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="SC2 Vibe 证据包生成器")
    parser.add_argument("--run-id", required=True, help="run ID（用于目录命名）")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认 artifacts/galaxy-vibe/bundles/）")
    parser.add_argument("--artifacts-dir", default=None, help="runtime/visual/inference 证据根目录")
    parser.add_argument("--gamelogs-dir", default=None, help="SC2 GameLogs 目录（ScriptError 差异）")
    parser.add_argument("--phase-status", default=None, help="JSON 字符串：阶段状态映射")
    parser.add_argument("--phase-status-file", default=None, help="UTF-8 JSON 文件：阶段状态映射")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else (REPO_ROOT / "artifacts" / "galaxy-vibe" / "bundles")
    artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else None
    gamelogs_dir = Path(args.gamelogs_dir) if args.gamelogs_dir else None

    phase_status = {}
    if args.phase_status_file:
        try:
            phase_status = json.loads(
                Path(args.phase_status_file).read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError) as e:
            print(f"警告：--phase-status-file JSON 解析失败: {e}", file=sys.stderr)
    elif args.phase_status:
        try:
            phase_status = json.loads(args.phase_status)
        except json.JSONDecodeError as e:
            print(f"警告：--phase-status JSON 解析失败: {e}", file=sys.stderr)

    bundler = EvidenceBundler(
        run_id=args.run_id,
        out_dir=out_dir,
        artifacts_dir=artifacts_dir,
        gamelogs_dir=gamelogs_dir,
    )
    bundle = bundler.build(phase_status=phase_status)
    print(f"证据包已生成: {bundle.bundle_dir}")
    print(f"  条目数: {len(bundle.items)}")
    print(f"  overall_status: {bundle.overall_status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
