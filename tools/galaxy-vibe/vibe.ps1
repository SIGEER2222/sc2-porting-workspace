<#
.SYNOPSIS
  SC2 Vibe 框架统一入口（P7 交付物）

.DESCRIPTION
  依据 sc2-vibe完整实施计划.md，统一入口 vibe.ps1 workflow|status|manifest|probe|hot|verify|rebuild|run-task|bundle|soak|cleanup

  - status    : 离线工作流状态汇总（simulator/Galaxy/parser/skills/runtime）
  - manifest  : 静态地图提取 → 统一 Vibe task/scenario manifest + simulator smoke
  - probe     : P0 传输闸门验证（运行 transport/run-transport-probes.ps1）
  - hot       : P1-P3 热循环执行（spawn 3 Marine + 视觉/状态断言）
  - verify    : P2 断言运行（运行 10 个确定性场景）
  - rebuild   : P4 冷循环重建（变更分类器 + 静态校验 + 场景重建）
  - run-task  : P5 意图入口（task.json classifier + 3 轮修正）
  - bundle    : P7 单命令生成完整证据包
  - soak      : P7 30 分钟/200 请求稳定性测试
  - cleanup   : P7 资源/Bank/日志/进程清理
  - validate  : 静态自检（schema/Python 语法/Galaxy 语法）
  - workflow  : Stage 14 operator workflow（manifest + status + evidence，可选 live）

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
    [ValidateSet('workflow', 'status', 'manifest', 'probe', 'hot', 'verify', 'rebuild', 'run-task', 'bundle', 'soak', 'cleanup', 'validate', 'stage-loop', 'help')]
    [string]$Command,

    [string]$Consumer = "dead-of-night",
    [string]$RunId,
    [int]$Sc2Port = 5000,
    [int]$TargetRequests = 200,
    [double]$DurationSec = 1800.0,
    [int]$MaxIterations = 3,
    [int]$LiveTimeoutSec = 300,
    [switch]$DryRun,
    [switch]$Live,
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

function Invoke-Status {
    param(
        [string]$OutputFile = "",
        [string]$RuntimeArtifactsDir = "",
        [string]$EvidenceBundleFile = ""
    )
    Write-Header "Vibe 工作流状态"
    $statusScript = Join-Path $ScriptRoot "workflow_status.py"
    if (-not (Test-Path $statusScript)) {
        throw "workflow status 脚本不存在: $statusScript"
    }
    $outDir = Join-Path $RepoRoot "artifacts\projects\cmre-porting\stage14-vibe-operator-workflow"
    if (-not (Test-Path $outDir)) {
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    }
    $outFile = if ($OutputFile) { $OutputFile } else { Join-Path $outDir "workflow-status.json" }
    $statusArgs = @(
        "--repo-root", $RepoRoot,
        "--out", $outFile
    )
    if ($RuntimeArtifactsDir) {
        $statusArgs += @("--runtime-artifacts-dir", $RuntimeArtifactsDir)
    }
    if ($EvidenceBundleFile) {
        $statusArgs += @("--evidence-bundle", $EvidenceBundleFile)
    }
    Invoke-Python -ScriptPath $statusScript -Arguments $statusArgs
    Write-Host "工作流状态已写入: $outFile" -ForegroundColor Green
}

function Invoke-Workflow {
    Write-Header "Stage 14 — Vibe operator workflow"
    $stage14Root = Join-Path $RepoRoot "artifacts\projects\cmre-porting\stage14-vibe-operator-workflow"
    $statusFile = Join-Path $stage14Root "workflow-status.json"
    $bundleOut = Join-Path $stage14Root "bundles"
    $stage13Artifacts = Join-Path $RepoRoot "artifacts\projects\cmre-porting\stage13-vibe-runtime-evidence-pack"
    New-Item -ItemType Directory -Force -Path $stage14Root, $bundleOut | Out-Null

    Invoke-Manifest

    $liveStatus = "carried-forward"
    $liveArtifactDir = $stage13Artifacts
    $liveAttemptsPath = Join-Path $stage14Root "live-attempts.json"
    $liveAttempts = @()
    if ($Live) {
        $stageHarness = Join-Path $RepoRoot "src\projects\cmre-porting\stages\13-vibe-runtime-evidence-pack\run-stage13-runtime-evidence.ps1"
        if (-not (Test-Path $stageHarness)) {
            throw "Stage 13 runtime harness 不存在: $stageHarness"
        }

        $attemptRoot = Join-Path (Join-Path $stage14Root "live-attempts") $RunId
        New-Item -ItemType Directory -Force -Path $attemptRoot | Out-Null
        $ports = @($Sc2Port, ($Sc2Port + 1))
        $lastAttemptDir = $stage13Artifacts
        foreach ($port in $ports) {
            $attemptId = "$RunId-port$port"
            $attemptDir = Join-Path $attemptRoot "port-$port"
            $lastAttemptDir = $attemptDir
            $attemptStarted = Get-Date
            $attemptExit = -1
            $attemptRunId = $attemptId

            # Each retry gets its own harness run id and snapshot. A failed port
            # must remain inspectable without replacing the last passing bundle.
            if (Test-Path -LiteralPath $attemptDir) {
                Remove-Item -LiteralPath $attemptDir -Recurse -Force
            }
            New-Item -ItemType Directory -Force -Path $attemptDir | Out-Null
            $harnessTimedOut = $false
            $harnessStdout = Join-Path $attemptDir "harness-stdout.txt"
            $harnessStderr = Join-Path $attemptDir "harness-stderr.txt"
            $reusablePackedMap = Join-Path $stage13Artifacts "runtime-map\DeadOfNight.packed.SC2Map"
            if ($DryRun) {
                Write-Host "[DRY-RUN] powershell `"$stageHarness`" -RunId $attemptRunId -Port $port" -ForegroundColor Yellow
            } else {
                $staleSummaryPath = Join-Path $stage13Artifacts "runtime-summary.json"
                if (Test-Path -LiteralPath $staleSummaryPath) {
                    Remove-Item -LiteralPath $staleSummaryPath -Force
                }
                $harnessArgs = @(
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", $stageHarness,
                    "-RunId", $attemptRunId,
                    "-Port", "$port"
                )
                if (Test-Path -LiteralPath $reusablePackedMap) {
                    # Reusing the verified packed input avoids trying to replace a
                    # map still held by a prior SC2 process before the launcher
                    # gets a chance to clean that process up.
                    $harnessArgs += @("-Map", $reusablePackedMap)
                }
                $harnessProc = Start-Process -FilePath "powershell" -ArgumentList $harnessArgs -PassThru -NoNewWindow `
                    -RedirectStandardOutput $harnessStdout -RedirectStandardError $harnessStderr
                $deadline = (Get-Date).AddSeconds([Math]::Max(30, $LiveTimeoutSec))
                while ($true) {
                    $harnessProc.Refresh()
                    if ($harnessProc.HasExited) {
                        $harnessProc.WaitForExit()
                        $attemptExit = $harnessProc.ExitCode
                        break
                    }
                    if ((Get-Date) -ge $deadline) {
                        $harnessTimedOut = $true
                        Stop-Process -Id $harnessProc.Id -Force -ErrorAction SilentlyContinue
                        $attemptExit = 124
                        break
                    }
                    Start-Sleep -Seconds 2
                }
            }

            if (Test-Path -LiteralPath $stage13Artifacts) {
                foreach ($entry in Get-ChildItem -LiteralPath $stage13Artifacts -Force) {
                    if ($entry.PSIsContainer -and $entry.Name -ne "runtime-map") {
                        continue
                    }
                    Copy-Item -LiteralPath $entry.FullName -Destination $attemptDir -Recurse -Force
                }
            }

            # The Stage 13 harness normally copies these files after the launcher
            # exits. If its packaging tail stalls, preserve the same current-run
            # outputs directly from the generic Galaxy Vibe evidence directory.
            foreach ($name in @("assert-results.json", "script-error-verdict.json", "vibe-verdict.json")) {
                $source = Join-Path $ArtifactsRoot $name
                if (Test-Path -LiteralPath $source) {
                    Copy-Item -LiteralPath $source -Destination (Join-Path $attemptDir $name) -Force
                }
            }
            if (Test-Path -LiteralPath $reusablePackedMap) {
                foreach ($name in @("pack-sc2map-exit.json", "pack-sc2map-stdout.txt", "pack-sc2map-stderr.txt")) {
                    $stalePackEvidence = Join-Path $attemptDir $name
                    if (Test-Path -LiteralPath $stalePackEvidence) {
                        Remove-Item -LiteralPath $stalePackEvidence -Force
                    }
                }
            }
            $staleStage13ScriptError = Join-Path $attemptDir "script-error-verdict-stage13.json"
            if (Test-Path -LiteralPath $staleStage13ScriptError) {
                Remove-Item -LiteralPath $staleStage13ScriptError -Force
            }
            $launchMarker = Join-Path $env:USERPROFILE "Documents\StarCraft II\galaxy-vibe-launch.json"
            if (Test-Path -LiteralPath $launchMarker) {
                Copy-Item -LiteralPath $launchMarker -Destination (Join-Path $attemptDir "galaxy-vibe-launch.json") -Force
            }
            foreach ($name in @("launcher-stdout.txt", "launcher-stderr.txt")) {
                $source = Join-Path $stage13Artifacts $name
                if (Test-Path -LiteralPath $source) {
                    Copy-Item -LiteralPath $source -Destination (Join-Path $attemptDir $name) -Force
                }
            }

            $summary = $null
            $attemptSummaryPath = Join-Path $attemptDir "runtime-summary.json"
            if (-not $DryRun -and (Test-Path -LiteralPath $attemptSummaryPath)) {
                try {
                    $summary = Get-Content -Raw -LiteralPath $attemptSummaryPath -Encoding UTF8 | ConvertFrom-Json
                } catch {
                    $summary = $null
                }
            }
            if (-not $DryRun -and -not $summary) {
                $assertPath = Join-Path $attemptDir "assert-results.json"
                $scriptErrorPath = Join-Path $attemptDir "script-error-verdict.json"
                $vibePath = Join-Path $attemptDir "vibe-verdict.json"
                $stdoutPath = Join-Path $attemptDir "launcher-stdout.txt"
                $assert = $null
                $scriptError = $null
                $vibe = $null
                foreach ($pair in @(
                    @($assertPath, "assert"),
                    @($scriptErrorPath, "scriptError"),
                    @($vibePath, "vibe")
                )) {
                    if (Test-Path -LiteralPath $pair[0]) {
                        try {
                            $value = Get-Content -Raw -LiteralPath $pair[0] -Encoding UTF8 | ConvertFrom-Json
                            Set-Variable -Name $pair[1] -Value $value
                        } catch { }
                    }
                }
                $stdoutText = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -Raw -LiteralPath $stdoutPath } else { "" }
                $currentLauncherEvidence = (Test-Path -LiteralPath $stdoutPath) -and ((Get-Item -LiteralPath $stdoutPath).LastWriteTime -ge $attemptStarted)
                $currentAssertEvidence = (Test-Path -LiteralPath $assertPath) -and ((Get-Item -LiteralPath $assertPath).LastWriteTime -ge $attemptStarted)
                $currentScriptErrorEvidence = (Test-Path -LiteralPath $scriptErrorPath) -and ((Get-Item -LiteralPath $scriptErrorPath).LastWriteTime -ge $attemptStarted)
                $currentVibeEvidence = (Test-Path -LiteralPath $vibePath) -and ((Get-Item -LiteralPath $vibePath).LastWriteTime -ge $attemptStarted)
                $runtimePass = $currentLauncherEvidence -and $currentAssertEvidence -and $currentScriptErrorEvidence -and $currentVibeEvidence -and
                    $assert -and ([int]$assert.total -gt 0) -and [bool]$assert.all_passed -and
                    $scriptError -and -not [bool]$scriptError.has_new_errors -and
                    $vibe -and [bool]$vibe.passed -and ($stdoutText -match "VERDICT exit code=0")
                $summary = [ordered]@{
                    schemaVersion = 1
                    run_id = $attemptRunId
                    status = if ($runtimePass) { "PASS" } else { "failed" }
                    evidence_type = "runtime"
                    reason = if ($runtimePass -and $harnessTimedOut) { "launcher/runtime verdict passed; Stage 13 packaging tail exceeded operator timeout" } elseif (-not $runtimePass) { "current launcher/assertion evidence did not satisfy runtime PASS" } else { "" }
                    operator_harness = @{
                        exit_code = $attemptExit
                        timed_out = $harnessTimedOut
                        timeout_seconds = [Math]::Max(30, $LiveTimeoutSec)
                    }
                    launcher = @{
                        exit_code = if ($runtimePass) { 0 } else { $attemptExit }
                        stdout = "artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/$RunId/port-$port/launcher-stdout.txt"
                        stderr = "artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/$RunId/port-$port/launcher-stderr.txt"
                    }
                    assert = $assert
                    script_error = $scriptError
                    vibe_verdict = $vibe
                    inputs = @{
                        runtime_scenario = "artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/$RunId/port-$port/runtime-scenario.vtest"
                        source_map = "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map"
                    }
                }
                $summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $attemptSummaryPath -Encoding UTF8
            }
            $summaryStatus = if ($DryRun) { "dry-run" } elseif ($summary) { [string]$summary.status } else { "missing" }
            if ($summary) {
                $launcherExitPath = Join-Path $attemptDir "launcher-exit.json"
                @{
                    schemaVersion = 1
                    run_id = $attemptRunId
                    exit_code = if ($summaryStatus -eq "PASS") { 0 } else { $attemptExit }
                    started_at = $attemptStarted.ToString("o")
                    finished_at = (Get-Date).ToString("o")
                    map = "artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/runtime-map/DeadOfNight.packed.SC2Map"
                    verify = "artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/$RunId/port-$port/runtime-scenario.vtest"
                    stdout = "artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/$RunId/port-$port/launcher-stdout.txt"
                    stderr = "artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/$RunId/port-$port/launcher-stderr.txt"
                } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $launcherExitPath -Encoding UTF8
            }
            $attemptStatus = if ($summaryStatus -eq "PASS") { "passed" } elseif ($summaryStatus -eq "blocked-runtime-unavailable") { "blocked" } else { "failed" }
            $attemptRecord = [ordered]@{
                attempt = $liveAttempts.Count + 1
                run_id = $attemptRunId
                port = $port
                started_at = $attemptStarted.ToString("o")
                finished_at = (Get-Date).ToString("o")
                exit_code = $attemptExit
                status = $attemptStatus
                runtime_summary_status = $summaryStatus
                harness_timed_out = $harnessTimedOut
                artifact_dir = ($attemptDir.Substring($RepoRoot.Length).TrimStart('\') -replace '\\', '/')
            }
            $liveAttempts += $attemptRecord

            if ($summaryStatus -eq "PASS") {
                $liveStatus = "passed"
                $liveArtifactDir = $attemptDir
                break
            }
        }
        ConvertTo-Json -InputObject @($liveAttempts) -Depth 8 | Set-Content -LiteralPath $liveAttemptsPath -Encoding UTF8
        if ($liveStatus -ne "passed") {
            $liveArtifactDir = $lastAttemptDir
        }
    }

    if (-not $Live) {
        $stage13SummaryPath = Join-Path $stage13Artifacts "runtime-summary.json"
        $stage13IsPass = $false
        if (Test-Path -LiteralPath $stage13SummaryPath) {
            try {
                $stage13IsPass = ((Get-Content -Raw -LiteralPath $stage13SummaryPath -Encoding UTF8 | ConvertFrom-Json).status -eq "PASS")
            } catch { }
        }
        if (-not $stage13IsPass) {
            $carriedForward = Get-ChildItem -LiteralPath (Join-Path $stage14Root "live-attempts") -Filter "runtime-summary.json" -Recurse -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending |
                ForEach-Object {
                    try {
                        $candidate = Get-Content -Raw -LiteralPath $_.FullName -Encoding UTF8 | ConvertFrom-Json
                        if ($candidate.status -eq "PASS") {
                            return $_.Directory.FullName
                        }
                    } catch { }
                } | Select-Object -First 1
            if ($carriedForward) {
                $liveArtifactDir = [string]$carriedForward
                $liveStatus = "carried-forward"
            }
        }
    }

    $bundleScript = Join-Path $ScriptRoot "evidence_bundle.py"
    if (-not (Test-Path $bundleScript)) {
        throw "证据包生成脚本不存在: $bundleScript"
    }
    $runtimeSummaryPath = Join-Path $liveArtifactDir "runtime-summary.json"
    $runtimeEvidenceStatus = "warn"
    if (Test-Path $runtimeSummaryPath) {
        $runtimeSummary = Get-Content -Raw -LiteralPath $runtimeSummaryPath -Encoding UTF8 | ConvertFrom-Json
        if ($runtimeSummary.status -eq "PASS") {
            $runtimeEvidenceStatus = "passed"
        } elseif ($runtimeSummary.status -eq "blocked-runtime-unavailable") {
            $runtimeEvidenceStatus = "blocked"
        } else {
            $runtimeEvidenceStatus = "failed"
        }
    }
    $phaseStatusFile = Join-Path $stage14Root "phase-status.json"
    @{
        manifest = "passed"
        simulator = "passed"
        workflow_status = "passed"
        runtime_evidence = $runtimeEvidenceStatus
        evidence = "passed"
        runtime_execution = $liveStatus
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $phaseStatusFile -Encoding UTF8
    $bundleRunId = if ($RunId) { $RunId } else { "stage14-workflow" }
    $bundleArtifactsDir = $liveArtifactDir
    Invoke-Python -ScriptPath $bundleScript -Arguments @(
        "--run-id", $bundleRunId,
        "--out-dir", $bundleOut,
        "--artifacts-dir", $bundleArtifactsDir,
        "--phase-status-file", $phaseStatusFile
    )

    $bundleEvidenceFile = Join-Path (Join-Path $bundleOut "bundle-$bundleRunId") "evidence-bundle.json"
    $statusRuntimeDir = ""
    if ((Test-Path -LiteralPath (Join-Path $liveArtifactDir "runtime-summary.json")) -and
        ([System.IO.Path]::GetFullPath($liveArtifactDir) -ne [System.IO.Path]::GetFullPath($stage13Artifacts))) {
        $statusRuntimeDir = $liveArtifactDir
    }
    Invoke-Status -OutputFile $statusFile -RuntimeArtifactsDir $statusRuntimeDir -EvidenceBundleFile $bundleEvidenceFile
    $status = Get-Content -Raw -LiteralPath $statusFile -Encoding UTF8 | ConvertFrom-Json
    Write-Host "OPERATOR WORKFLOW: status=$($status.overall); pass=$($status.lane_counts.pass), warn=$($status.lane_counts.warn), fail=$($status.lane_counts.fail)" -ForegroundColor Green
    Write-Host "  status: $statusFile"
    Write-Host "  bundle: $bundleOut\bundle-$bundleRunId"
    if ($Live) {
        Write-Host "  live attempts: $liveAttemptsPath"
        Write-Host "  live execution: $liveStatus"
    }
    if ($status.overall -eq "fail") {
        throw "operator workflow status contains failed lanes"
    }
    if ($Live -and $liveStatus -ne "passed") {
        throw "live runtime attempts did not produce a PASS evidence summary"
    }
}

function Invoke-Manifest {
    Write-Header "Vibe task manifest"
    $manifestScript = Join-Path $RepoRoot "src\projects\cmre-porting\vibe\task_manifest.py"
    if (-not (Test-Path $manifestScript)) {
        throw "task manifest 脚本不存在: $manifestScript"
    }
    $outDir = Join-Path $RepoRoot "artifacts\projects\cmre-porting\stage12-vibe-task-manifest"
    if (-not (Test-Path $outDir)) {
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    }
    $args = @(
        "--out-dir", $outDir,
        "--manifest-id", "dead-of-night-vibe",
        "--run-simulator-smoke"
    )
    if ($MapPath) {
        $args += @("--map-dir", $MapPath)
    }
    Invoke-Python -ScriptPath $manifestScript -Arguments $args
    Write-Host "task manifest 已写入: $outDir\manifest.json" -ForegroundColor Green
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

function Invoke-StageLoop {
    Write-Header "Stage loop — 执行→自审→重试/推进"
    $loopScript = Join-Path $RepoRoot "src\projects\cmre-porting\stages\13-vibe-runtime-evidence-pack\run-stage-loop.ps1"
    if (-not (Test-Path $loopScript)) {
        throw "Stage loop 脚本不存在: $loopScript"
    }
    $args = @(
        "-RunId", $RunId,
        "-MaxIterations", "$MaxIterations",
        "-Port", "$Sc2Port"
    )
    if ($MapPath) {
        $args += @("-Map", $MapPath)
    }
    if ($DryRun) {
        $args += "-DryRun"
    }
    Invoke-PowerShellScript -ScriptPath $loopScript -Arguments $args
    Write-Host "Stage loop 完成，证据见: artifacts\projects\cmre-porting\stage13-vibe-runtime-evidence-pack" -ForegroundColor Green
}

function Show-Help {
    Write-Host "SC2 Vibe 统一入口" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "用法: vibe.ps1 <command> [options]"
    Write-Host ""
    Write-Host "命令:"
    Write-Host "  workflow  Stage 14 operator workflow（manifest + status + evidence）"
    Write-Host "  status    离线工作流状态汇总"
    Write-Host "  manifest  静态地图提取→统一 task/scenario manifest"
    Write-Host "  probe     P0 传输闸门验证"
    Write-Host "  hot       P1-P3 热循环执行"
    Write-Host "  verify    P2 断言运行（10 场景）"
    Write-Host "  rebuild   P4 冷循环重建"
    Write-Host "  run-task  P5 意图入口（classifier + 3 轮修正）"
    Write-Host "  bundle    P7 单命令生成完整证据包"
    Write-Host "  soak      P7 30min/200请求稳定性测试"
    Write-Host "  cleanup   P7 资源/Bank/日志/进程清理"
    Write-Host "  validate  静态自检（schema/Python/Galaxy）"
    Write-Host "  stage-loop 执行当前阶段，完成后自审；通过则准备下一阶段"
    Write-Host "  help      显示此帮助"
    Write-Host ""
    Write-Host "选项:"
    Write-Host "  -Consumer <id>     消费者 ID（dead-of-night / keha-rift）"
    Write-Host "  -RunId <id>        run ID（默认时间戳）"
    Write-Host "  -Sc2Port <port>    SC2 API 端口（默认 5000）"
    Write-Host "  -TargetRequests <n>  soak 目标请求数（默认 200）"
    Write-Host "  -DurationSec <sec>   soak 持续秒数（默认 1800）"
    Write-Host "  -MaxIterations <n>   stage-loop 最大自审迭代次数（默认 3）"
    Write-Host "  -LiveTimeoutSec <sec> workflow 单次 runtime harness 超时（默认 300）"
    Write-Host "  -DryRun            仅打印命令不执行"
    Write-Host "  -Live              workflow 命令中额外执行合规 SC2 runtime harness"
    Write-Host "  -MapPath <path>     manifest/probe 使用的地图路径"
}

# ============== 主分发 ==============

Test-Prerequisites

switch ($Command) {
    'workflow'  { Invoke-Workflow }
    'status'    { Invoke-Status }
    'manifest'  { Invoke-Manifest }
    'probe'     { Invoke-Probe }
    'hot'       { Invoke-Hot }
    'verify'    { Invoke-Verify }
    'rebuild'   { Invoke-Rebuild }
    'run-task'  { Invoke-RunTask }
    'bundle'    { Invoke-Bundle }
    'soak'      { Invoke-Soak }
    'cleanup'   { Invoke-Cleanup }
    'validate'  { Invoke-Validate }
    'stage-loop' { Invoke-StageLoop }
    'help'      { Show-Help }
    default     { Show-Help }
}

Write-Host ""
Write-Host "vibe.ps1 $Command 完成 (RunId=$RunId)" -ForegroundColor Green
