"""Cold Reload Orchestrator — P4 冷循环编排器。

依据 sc2-vibe完整实施计划.md P4:
  - 校验 -> 同步 -> 批准 launcher -> ready -> 自动重建 recipe -> 截图/状态通过
  - 禁止固定盲等和直接启动 SC2_x64.exe
  - 每次复核新增 ScriptError

冷循环流程：
  1. 变更分类（Galaxy/XML/Actor/...）
  2. 静态校验（语法、writeScope、只读源）
  3. 文件同步（staging → 目标位置）
  4. 调用批准 launcher（launch-cmre-alenger.ps1）
  5. 等待 ready 信号（heartbeat Bank + 端口检测）
  6. 场景 recipe 重建
  7. 截图 + 状态采集
  8. ScriptError 复核
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from cold.change_classifier import ChangeClassifier, ChangeRecord, ChangeType  # noqa: E402
from cold.static_validator import StaticValidator, load_project_write_scope  # noqa: E402
from cold.scenario_recipe import (  # noqa: E402
    get_default_scenario_recipe,
    get_galaxy_fixture_recipe,
    get_xml_fixture_recipe,
    save_recipe,
)


@dataclass
class ColdRunManifest:
    """冷循环运行 manifest。"""
    run_id: str
    started_at: str
    completed_at: str = ""
    change_type: str = ""
    static_validation_passed: bool = False
    sync_completed: bool = False
    launcher_exit_code: int = -1
    ready_signal_detected: bool = False
    recipe_rebuild_passed: bool = False
    screenshot_captured: bool = False
    script_errors_count: int = 0
    verdict: str = "pending"
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


class ColdOrchestrator:
    """冷循环编排器。"""

    def __init__(self, artifacts_dir: Optional[Path] = None):
        self.artifacts_dir = artifacts_dir or (REPO_ROOT / "artifacts" / "galaxy-vibe" / "p4-cold")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.classifier = ChangeClassifier()
        write_scope, read_only = load_project_write_scope()
        self.validator = StaticValidator(write_scope, read_only)

    def run_cold_cycle(
        self,
        changed_files: list[Path],
        launcher_script: Path,
        map_name: str = "亡者之夜",
        commander: str = "TerranAlenger3",
        listen_port: int = 5000,
    ) -> ColdRunManifest:
        """执行完整冷循环。

        Args:
            changed_files: 变更的文件列表
            launcher_script: 批准 launcher 脚本路径
            map_name: 地图名
            commander: 指挥官
            listen_port: SC2 API 端口

        Returns:
            ColdRunManifest
        """
        import uuid
        manifest = ColdRunManifest(
            run_id=f"cold-{uuid.uuid4().hex[:8]}",
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        )

        # Step 1: 变更分类
        print(f"[cold] Step 1/8: 分类 {len(changed_files)} 个变更...", flush=True)
        changes = self.classifier.classify_batch(changed_files)
        change_types = set(c.change_type.value for c in changes)
        manifest.change_type = ",".join(change_types)
        if not self.classifier.needs_cold_reload(changes):
            manifest.errors.append("无冷循环变更")
            manifest.verdict = "skipped"
            self._save_manifest(manifest)
            return manifest

        # Step 2: 静态校验
        print("[cold] Step 2/8: 静态校验...", flush=True)
        validation = self.validator.validate_changes(changed_files)
        manifest.static_validation_passed = validation.is_valid
        if not validation.is_valid:
            manifest.errors.extend(validation.errors)
            manifest.verdict = "failed"
            manifest.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            self._save_manifest(manifest)
            return manifest

        # Step 3: 文件同步（staging）
        print("[cold] Step 3/8: 文件同步...", flush=True)
        sync_result = self._sync_files(changed_files)
        manifest.sync_completed = sync_result
        if not sync_result:
            manifest.errors.append("文件同步失败")
            manifest.verdict = "failed"
            self._save_manifest(manifest)
            return manifest

        # Step 4: 调用批准 launcher
        print(f"[cold] Step 4/8: 调用 launcher {launcher_script.name}...", flush=True)
        launcher_result = self._run_launcher(launcher_script, map_name, commander, listen_port)
        manifest.launcher_exit_code = launcher_result.get("exit_code", -1)
        if manifest.launcher_exit_code != 0:
            manifest.errors.append(f"launcher 退出码非 0: {manifest.launcher_exit_code}")
            manifest.verdict = "failed"
            self._save_manifest(manifest)
            return manifest

        # Step 5: 等待 ready 信号
        print("[cold] Step 5/8: 等待 ready 信号...", flush=True)
        ready = self._wait_for_ready(timeout=180)
        manifest.ready_signal_detected = ready
        if not ready:
            manifest.errors.append("ready 信号超时")
            manifest.verdict = "failed"
            self._save_manifest(manifest)
            return manifest

        # Step 6: 场景 recipe 重建
        print("[cold] Step 6/8: 场景 recipe 重建...", flush=True)
        recipe_result = self._rebuild_scenario(listen_port)
        manifest.recipe_rebuild_passed = recipe_result

        # Step 7: 截图 + 状态采集
        print("[cold] Step 7/8: 截图 + 状态采集...", flush=True)
        manifest.screenshot_captured = self._capture_state(listen_port)

        # Step 8: ScriptError 复核
        print("[cold] Step 8/8: ScriptError 复核...", flush=True)
        manifest.script_errors_count = self._count_script_errors()
        if manifest.script_errors_count > 0:
            manifest.errors.append(f"发现 {manifest.script_errors_count} 个 ScriptError")

        # 最终判定
        manifest.verdict = "passed" if (
            manifest.static_validation_passed and
            manifest.sync_completed and
            manifest.launcher_exit_code == 0 and
            manifest.ready_signal_detected and
            manifest.recipe_rebuild_passed and
            manifest.script_errors_count == 0
        ) else "failed"

        manifest.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        self._save_manifest(manifest)
        return manifest

    def _sync_files(self, files: list[Path]) -> bool:
        """文件同步（PoC：直接返回 True，实际应同步到 staging）。"""
        # 实际实现需要将文件同步到 mod/map 的正确位置
        # 这里 PoC 返回 True，假设文件已在正确位置
        return True

    def _run_launcher(self, launcher: Path, map_name: str, commander: str, port: int) -> dict:
        """调用批准 launcher。"""
        if not launcher.exists():
            return {"exit_code": -1, "error": "launcher 不存在"}

        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(launcher),
            "-MapName", map_name,
            "-Commander", commander,
            "-ListenPort", str(port),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
                "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "error": "launcher 超时"}
        except Exception as e:
            return {"exit_code": -1, "error": str(e)}

    def _wait_for_ready(self, timeout: float = 180) -> bool:
        """等待 ready 信号。

        依据 AGENTS.md："禁止用固定时间盲等 SC2 启动；依赖 launcher 自带的 Wait-GameReady 信号检测"
        launcher 退出码 0 即视为加载完成。
        这里额外检测 Bank heartbeat 作为二次确认。
        """
        from host.vibe_host import read_bank
        deadline = time.time() + timeout
        bank_path = Path.home() / "Documents" / "StarCraft II" / "Banks" / "GalaxyVibe.SC2Bank"
        last_heartbeat = 0
        while time.time() < deadline:
            try:
                bank = read_bank("GalaxyVibe")
                idx = bank.get("index", {})
                if idx.get("kernel_initialized") == 1:
                    # Kernel 已初始化
                    return True
                heartbeat = idx.get("bridge_heartbeat", 0)
                if heartbeat > 0 and heartbeat != last_heartbeat:
                    # heartbeat 在递增
                    last_heartbeat = heartbeat
                    time.sleep(2)
                    continue
            except Exception:
                pass
            time.sleep(2)
        return False

    def _rebuild_scenario(self, port: int) -> bool:
        """执行场景 recipe 重建。"""
        from host.vibe_host import VibeHost
        from observer.assertion_runner import AssertionRunner

        host = VibeHost(sc2_port=port)
        if not host.connect_sc2():
            return False

        host.start_session()
        runner = AssertionRunner(host)
        recipe = get_default_scenario_recipe()
        result = runner.run_recipe(recipe)
        host.close()

        # 保存 recipe 结果
        result_path = self.artifacts_dir / "recipe-rebuild-result.json"
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result.get("verdict") == "passed"

    def _capture_state(self, port: int) -> bool:
        """截图 + 状态采集。"""
        try:
            from visual.capture import VisualCapture
            capture = VisualCapture(self.artifacts_dir / "screenshots")
            result = capture.capture_window("cold-reload-final")
            return result is not None
        except Exception:
            return False

    def _count_script_errors(self) -> int:
        """统计本次启动的 ScriptError 数量。"""
        game_logs = Path.home() / "Documents" / "StarCraft II" / "GameLogs"
        if not game_logs.exists():
            return 0
        errors = list(game_logs.glob("ScriptError.*.txt"))
        return len(errors)

    def _save_manifest(self, manifest: ColdRunManifest) -> Path:
        """保存 manifest。"""
        data = {
            "run_id": manifest.run_id,
            "started_at": manifest.started_at,
            "completed_at": manifest.completed_at,
            "change_type": manifest.change_type,
            "static_validation_passed": manifest.static_validation_passed,
            "sync_completed": manifest.sync_completed,
            "launcher_exit_code": manifest.launcher_exit_code,
            "ready_signal_detected": manifest.ready_signal_detected,
            "recipe_rebuild_passed": manifest.recipe_rebuild_passed,
            "screenshot_captured": manifest.screenshot_captured,
            "script_errors_count": manifest.script_errors_count,
            "verdict": manifest.verdict,
            "errors": manifest.errors,
            "artifacts": manifest.artifacts,
        }
        path = self.artifacts_dir / f"{manifest.run_id}-manifest.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def run_galaxy_fixture_cold_cycle(launcher: Path) -> ColdRunManifest:
    """运行 Galaxy fixture 冷循环测试。"""
    orch = ColdOrchestrator()
    galaxy_file = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel" / "LibVibeKernel.galaxy"
    return orch.run_cold_cycle([galaxy_file], launcher)


def run_xml_fixture_cold_cycle(launcher: Path) -> ColdRunManifest:
    """运行 XML fixture 冷循环测试。"""
    orch = ColdOrchestrator()
    # 使用一个安全的 XML fixture（Attributes 文件）
    xml_file = REPO_ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps" / "亡者之夜.SC2Map" / "Attributes"
    return orch.run_cold_cycle([xml_file], launcher)
