<#
.SYNOPSIS
  SC2 Vibe 框架统一入口（P7 交付物）

.DESCRIPTION
  依据 sc2-vibe完整实施计划.md，统一入口 vibe.ps1 probe|hot|verify|rebuild|run-task|bundle|soak|cleanup

  - probe     : P0 传输闸门验证（运行 transport/run-transport-probes.ps1）
  - hot       : P1-P3 热循环执行（spawn 3 Marine + 视觉/状态断言）
  - verify    : P2 断言运行（运行 10 个确定性场景）
  - rebuild   : P4 冷循环重建（变更分类器 + 静态校验 + 场景重建）
  - run-task  : P5 意图入口（task.json classifier + 3 轮修正）
  - bundle    : P7 单命令生成完整证据包
  - soak      : P7 30 分钟/200 请求稳定性测试
  - cleanup   : P7 资源/Bank/日志/进程清理
  - validate  : 静态自检（schema/Python 语法/Galaxy 语法）

.PARAMETER Command
  要执行的子命令。

.PARAMETER Consumer
  消费者 ID（dead-of-night / keha-rift），默认 dead-of-night。

.PARAMETER RunId
  run ID（用于产物目录命名），未指定时自动生成时间戳 ID。

.EXAMPLE
  .\vibe.ps1 probe
  .\vibe.ps1 hot -Consumer dead-of-night
  .\vibe.ps1 bundle -RunId 20260729-220000
  .\vibe.ps1 soak -TargetRequests 200 -DurationSec 1800
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('probe', 'hot', 'verify', 'rebuild', 'run-task', 'bundle', 'soak', 'cleanup', 'validate', 'help')]
    [string]$Command,

    [string]$Consumer = "dead-of-night",
    [string]$RunId,
    [int]$Sc2Port = 5000,
    [int]$TargetRequests = 200,
    [double]$DurationSec = 1800.0,
    [switch]$DryRun,
    [string]$MapPath = ""
)

$ErrorActionPreference = "Stop"
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# 兼容 vendored s2clientprotocol 的 protobuf 版本（P7-ENV-001 workaround）
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = "python"

$ScriptRoot = $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptRoot)  # sc2-porting-workspace
$ArtifactsRoot = Join-Path $RepoRoot "artifacts\galaxy-vibe"
$ConsumersRoot = Join-Path $ScriptRoot "consumers"

if (-not $RunId) {
    $RunId = Get-Date -Format "yyyyMMdd-HHmmss"
}

$RunDir = Join-Path $ArtifactsRoot "run-$RunId"
$BundlesDir = Join-Path $ArtifactsRoot "bundles"

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
    Write-Host "  RunId: $RunId" -ForegroundColor DarkGray
    Write-Host "  Consumer: $Consumer" -ForegroundColor DarkGray
    Write-Host "  RunDir: $RunDir" -ForegroundColor DarkGray
}

function Get-PythonExe {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
    return $py
}

function Invoke-Python {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @()
    )
    if ($DryRun) {
        Write-Host "[DRY-RUN] python `"$ScriptPath`" $($Arguments -join ' ')" -ForegroundColor Yellow
        return
    }
    $python = Get-PythonExe
    if (-not $python) {
        throw "未找到 python / python3"
    }
    & $python.Source $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python 脚本退出码 ${LASTEXITCODE}: $ScriptPath"
    }
}

function Invoke-PowerShellScript {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @()
    )
    if ($DryRun) {
        Write-Host "[DRY-RUN] powershell `"$ScriptPath`" $($Arguments -join ' ')" -ForegroundColor Yellow
        return
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "PowerShell 脚本退出码 ${LASTEXITCODE}: $ScriptPath"
    }
}

function Test-Prerequisites {
    if (-not (Test-Path $ScriptRoot)) {
        throw "galaxy-vibe 根目录不存在: $ScriptRoot"
    }
    if (-not (Test-Path $ArtifactsRoot)) {
        New-Item -ItemType Directory -Path $ArtifactsRoot -Force | Out-Null
    }
}

function Get-ConsumerConfig {
    param([string]$ConsumerId)
    $consumerFile = Join-Path $ConsumersRoot "$ConsumerId\consumer.json"
    if (-not (Test-Path $consumerFile)) {
        throw "消费者配置不存在: $consumerFile"
    }
    return Get-Content $consumerFile -Raw -Encoding UTF8 | ConvertFrom-Json
}

# ============== 子命令实现 ==============

function Invoke-Probe {
    Write-Header "P0 — 传输闸门验证"
    $probeScript = Join-Path $ScriptRoot "transport\run-transport-probes.ps1"
    if (-not (Test-Path $probeScript)) {
        throw "传输探针脚本不存在: $probeScript"
    }
    $probeArgs = @("-Port", $Sc2Port)
    if ($MapPath) { $probeArgs += @("-MapPath", $MapPath) }
    Invoke-PowerShellScript -ScriptPath $probeScript -Arguments $probeArgs
    Write-Host "P0 探针完成，verdict: $RunDir\transport-verdict.json" -ForegroundColor Green
}

function Invoke-Hot {
    Write-Header "P1-P3 — 热循环执行"
    $config = Get-ConsumerConfig -ConsumerId $Consumer
    Write-Host "消费者: $($config.consumer_id) | 地图: $($config.map) | 指挥官: $($config.commander)"
    $adapterScript = Join-Path $ScriptRoot "consumers\shared\adapter.py"
    if (-not (Test-Path $adapterScript)) {
        throw "adapter 脚本不存在: $adapterScript"
    }
    $consumerFile = Join-Path $ConsumersRoot "$Consumer\consumer.json"
    Invoke-Python -ScriptPath $adapterScript -Arguments @(
        "--consumer-json", $consumerFile,
        "--sc2-port", $Sc2Port,
        "--mode", "hot",
        "--run-dir", $RunDir
    )
    Write-Host "热循环执行完成，证据见: $RunDir" -ForegroundColor Green
}

function Invoke-Verify {
    Write-Header "P2 — 断言运行（10 场景）"
    $runnerScript = Join-Path $ScriptRoot "observer\assertion_runner.py"
    if (-not (Test-Path $runnerScript)) {
        throw "断言 runner 脚本不存在: $runnerScript"
    }
    $scenariosDir = Join-Path $ScriptRoot "observer\scenarios"
    if (-not (Test-Path $scenariosDir)) {
        Write-Host "警告：scenarios 目录不存在，仅运行内置场景" -ForegroundColor Yellow
    }
    Invoke-Python -ScriptPath $runnerScript -Arguments @(
        "--sc2-port", $Sc2Port,
        "--run-dir", $RunDir
    )
    Write-Host "断言运行完成，verdict: $RunDir\verdict.json" -ForegroundColor Green
}

function Invoke-Rebuild {
    Write-Header "P4 — 冷循环重建"
    $orchestratorScript = Join-Path $ScriptRoot "cold\orchestrator.py"
    if (-not (Test-Path $orchestratorScript)) {
        throw "冷循环 orchestrator 脚本不存在: $orchestratorScript"
    }
    $consumerFile = Join-Path $ConsumersRoot "$Consumer\consumer.json"
    Invoke-Python -ScriptPath $orchestratorScript -Arguments @(
        "--consumer-json", $consumerFile,
        "--run-dir", $RunDir,
        "--sc2-port", $Sc2Port
    )
    Write-Host "冷循环重建完成，manifest: $RunDir\cold-manifest.json" -ForegroundColor Green
}

function Invoke-RunTask {
    Write-Header "P5 — 意图入口（task.json classifier + 3 轮修正）"
    $classifierScript = Join-Path $ScriptRoot "host\classifier.py"
    $correctionScript = Join-Path $ScriptRoot "host\correction.py"
    if (-not (Test-Path $classifierScript) -or -not (Test-Path $correctionScript)) {
        throw "classifier/correction 脚本不存在"
    }
    $consumerFile = Join-Path $ConsumersRoot "$Consumer\consumer.json"
    Invoke-Python -ScriptPath $classifierScript -Arguments @(
        "--consumer-json", $consumerFile,
        "--run-dir", $RunDir,
        "--sc2-port", $Sc2Port
    )
    Write-Host "意图入口执行完成，task: $RunDir\task-result.json" -ForegroundColor Green
}

function Invoke-Bundle {
    Write-Header "P7 — 单命令生成完整证据包"
    $bundleScript = Join-Path $ScriptRoot "evidence_bundle.py"
    if (-not (Test-Path $bundleScript)) {
        throw "证据包生成脚本不存在: $bundleScript"
    }
    # 阶段状态（基于已存在的 run-* 目录中的报告文件判定）
    $phaseStatus = @{}
    foreach ($phase in @("p0", "p1", "p2", "p3", "p4", "p5", "p6", "p7")) {
        $marker = Join-Path $RunDir "$phase-result.json"
        if (Test-Path $marker) {
            $phaseStatus[$phase] = "passed"
        } else {
            $phaseStatus[$phase] = "unknown"
        }
    }
    $phaseStatusJson = $phaseStatus | ConvertTo-Json -Compress
    Invoke-Python -ScriptPath $bundleScript -Arguments @(
        "--run-id", $RunId,
        "--out-dir", $BundlesDir,
        "--artifacts-dir", $ArtifactsRoot,
        "--phase-status", $phaseStatusJson
    )
    Write-Host "证据包生成完成: $BundlesDir\bundle-$RunId" -ForegroundColor Green
}

function Invoke-Soak {
    Write-Header "P7 — 30 分钟/$TargetRequests 请求稳定性测试"
    Write-Host "目标: $TargetRequests 请求 或 $DurationSec 秒（先到者为准）"
    $soakScript = Join-Path $ScriptRoot "host\soak.py"
    if (-not (Test-Path $soakScript)) {
        throw "soak 脚本不存在: $soakScript"
    }
    # 通过 Python 入口驱动 soak runner（脚本入口在 soak.py 内部 SoakRunner）
    # 这里提供一个简化驱动：直接 python -c 调用 SoakRunner
    $driverCode = @"
import sys, json
from pathlib import Path
sys.path.insert(0, r"$ScriptRoot\host")
from vibe_host import VibeHost
from performance import PerformanceTracker
from recovery import RecoveryManager
from soak import SoakRunner

host = VibeHost(sc2_port=$Sc2Port)
host.start_session()
tracker = PerformanceTracker()
recovery = RecoveryManager(Path(r"$RunDir"))
recovery.load_or_create(session_id=host.session_id)
runner = SoakRunner(
    host=host,
    tracker=tracker,
    recovery=recovery,
    log_path=Path(r"$RunDir\soak-requests.ndjson"),
)
report = runner.run(target_requests=$TargetRequests, duration_sec=$DurationSec)
report.save(Path(r"$RunDir\soak-report.json"))
tracker.compute_report().save(Path(r"$RunDir\performance-report.json"))
print(json.dumps({"stopped_reason": report.stopped_reason, "actual": report.actual_requests, "passes": report.passes}, ensure_ascii=False))
"@
    if ($DryRun) {
        Write-Host "[DRY-RUN] soak runner (code length: $($driverCode.Length))" -ForegroundColor Yellow
        return
    }
    $python = Get-PythonExe
    if (-not $python) {
        throw "未找到 python"
    }
    $driverCode | & $python.Source -
    if ($LASTEXITCODE -ne 0) {
        throw "soak 退出码 $LASTEXITCODE"
    }
    Write-Host "soak 完成，报告: $RunDir\soak-report.json" -ForegroundColor Green
}

function Invoke-Cleanup {
    Write-Header "P7 — 资源/Bank/日志/进程清理"
    $cleanupScript = Join-Path $ScriptRoot "host\cleanup.py"
    if (-not (Test-Path $cleanupScript)) {
        throw "cleanup 脚本不存在: $cleanupScript"
    }
    $driverCode = @"
import sys, json
from pathlib import Path
sys.path.insert(0, r"$ScriptRoot\host")
from cleanup import CleanupManager

mgr = CleanupManager(base_dir=Path(r"$ArtifactsRoot"), keep_recent=10)
report = mgr.run()
mgr.save_report(report, Path(r"$ArtifactsRoot\cleanup-report.json"))
print(json.dumps({
    "archived_banks": len(report.archived_banks),
    "archived_logs": len(report.archived_logs),
    "archived_screenshots": len(report.archived_screenshots),
    "removed_locks": len(report.removed_locks),
    "orphan_sc2_pids": len(report.orphan_sc2_pids),
    "errors": len(report.errors),
}, ensure_ascii=False))
"@
    if ($DryRun) {
        Write-Host "[DRY-RUN] cleanup runner" -ForegroundColor Yellow
        return
    }
    $python = Get-PythonExe
    if (-not $python) {
        throw "未找到 python"
    }
    $driverCode | & $python.Source -
    if ($LASTEXITCODE -ne 0) {
        throw "cleanup 退出码 $LASTEXITCODE"
    }
    Write-Host "清理完成，报告: $ArtifactsRoot\cleanup-report.json" -ForegroundColor Green
}

function Invoke-Validate {
    Write-Header "静态自检（schema/Python/Galaxy）"
    $validateScript = Join-Path $ScriptRoot "run-all-validation.ps1"
    if (-not (Test-Path $validateScript)) {
        throw "验证脚本不存在: $validateScript"
    }
    Invoke-PowerShellScript -ScriptPath $validateScript
    Write-Host "静态自检完成" -ForegroundColor Green
}

function Show-Help {
    Write-Host "SC2 Vibe 统一入口" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "用法: vibe.ps1 <command> [options]"
    Write-Host ""
    Write-Host "命令:"
    Write-Host "  probe     P0 传输闸门验证"
    Write-Host "  hot       P1-P3 热循环执行"
    Write-Host "  verify    P2 断言运行（10 场景）"
    Write-Host "  rebuild   P4 冷循环重建"
    Write-Host "  run-task  P5 意图入口（classifier + 3 轮修正）"
    Write-Host "  bundle    P7 单命令生成完整证据包"
    Write-Host "  soak      P7 30min/200请求稳定性测试"
    Write-Host "  cleanup   P7 资源/Bank/日志/进程清理"
    Write-Host "  validate  静态自检（schema/Python/Galaxy）"
    Write-Host "  help      显示此帮助"
    Write-Host ""
    Write-Host "选项:"
    Write-Host "  -Consumer <id>     消费者 ID（dead-of-night / keha-rift）"
    Write-Host "  -RunId <id>        run ID（默认时间戳）"
    Write-Host "  -Sc2Port <port>    SC2 API 端口（默认 5000）"
    Write-Host "  -TargetRequests <n>  soak 目标请求数（默认 200）"
    Write-Host "  -DurationSec <sec>   soak 持续秒数（默认 1800）"
    Write-Host "  -DryRun            仅打印命令不执行"
}

# ============== 主分发 ==============

Test-Prerequisites

switch ($Command) {
    'probe'     { Invoke-Probe }
    'hot'       { Invoke-Hot }
    'verify'    { Invoke-Verify }
    'rebuild'   { Invoke-Rebuild }
    'run-task'  { Invoke-RunTask }
    'bundle'    { Invoke-Bundle }
    'soak'      { Invoke-Soak }
    'cleanup'   { Invoke-Cleanup }
    'validate'  { Invoke-Validate }
    'help'      { Show-Help }
    default     { Show-Help }
}

Write-Host ""
Write-Host "vibe.ps1 $Command 完成 (RunId=$RunId)" -ForegroundColor Green
