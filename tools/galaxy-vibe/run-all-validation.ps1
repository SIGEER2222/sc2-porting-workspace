<#
.SYNOPSIS
  SC2 Vibe 框架静态自检 — 不依赖 SC2 运行时。

.DESCRIPTION
  依据 sc2-vibe完整实施计划.md "写完代码再统一验证" 策略:
  1. JSON schema 文件语法校验
  2. Python 模块 py_compile 语法校验
  3. Galaxy 文件头/include 校验（不调用 s2disas）
  4. 必需文件清单校验
  5. whitelist.json 与 kernel Galaxy 操作名一致性
  6. consumer.json 配置校验
  7. P0-P7 阶段交付物清单校验

  不启动 SC2，不发送任何 RPC；退出码 0=通过，非 0=有错误。

.EXAMPLE
  .\run-all-validation.ps1
  .\run-all-validation.ps1 -Verbose
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

$ScriptRoot = $PSScriptRoot
$StageDir = Split-Path -Parent $ScriptRoot
while (-not (Test-Path (Join-Path $StageDir "project.json")) -and $StageDir.Length -gt 3) {
    $StageDir = Split-Path -Parent $StageDir
}

$report = [ordered]@{
    ran_at        = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss+08:00")
    total_checks  = 0
    passed        = 0
    failed        = 0
    warnings      = 0
    checks        = @()
    overall       = "unknown"
}

function Add-Check {
    param(
        [string]$Category,
        [string]$Name,
        [string]$Status,  # passed | failed | warning
        [string]$Detail = ""
    )
    $report.total_checks++
    if ($Status -eq "passed") { $report.passed++ }
    elseif ($Status -eq "failed") { $report.failed++ }
    elseif ($Status -eq "warning") { $report.warnings++ }
    $report.checks += [ordered]@{
        category = $Category
        name = $Name
        status = $Status
        detail = $Detail
    }
    if ($Status -eq "failed") {
        Write-Host "  [FAIL] $Category / $Name : $Detail" -ForegroundColor Red
    } elseif ($Status -eq "warning") {
        Write-Host "  [WARN] $Category / $Name : $Detail" -ForegroundColor Yellow
    } else {
        Write-Host "  [PASS] $Category / $Name" -ForegroundColor Green
    }
}

function Test-JsonFile {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path $Path)) {
        Add-Check "json" $Name "failed" "文件不存在: $Path"
        return $null
    }
    try {
        $content = Get-Content $Path -Raw -Encoding UTF8
        $null = $content | ConvertFrom-Json
        Add-Check "json" $Name "passed"
        return $content
    } catch {
        Add-Check "json" $Name "failed" "JSON 解析错误: $_"
        return $null
    }
}

function Get-PythonExe {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
    return $py
}

function Test-PythonFile {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path $Path)) {
        Add-Check "python" $Name "failed" "文件不存在: $Path"
        return
    }
    $python = Get-PythonExe
    if (-not $python) {
        Add-Check "python" $Name "warning" "未找到 python，跳过语法校验"
        return
    }
    & $python.Source -m py_compile $Path 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Add-Check "python" $Name "passed"
    } else {
        Add-Check "python" $Name "failed" "py_compile 退出码 $LASTEXITCODE"
    }
}

function Test-GalaxyFile {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path $Path)) {
        Add-Check "galaxy" $Name "failed" "文件不存在: $Path"
        return
    }
    $content = Get-Content $Path -Raw -Encoding UTF8
    # 基本 include / 函数声明检查
    if ($content -notmatch 'include\s+"') {
        Add-Check "galaxy" $Name "warning" "未发现 include 指令"
    } elseif ($content -match 'void\s+\w+\s*\(') {
        Add-Check "galaxy" $Name "passed"
    } else {
        Add-Check "galaxy" $Name "warning" "未发现函数定义"
    }
}

function Test-FileExists {
    param([string]$Path, [string]$Name)
    if (Test-Path $Path) {
        Add-Check "files" $Name "passed"
    } else {
        Add-Check "files" $Name "failed" "缺失: $Path"
    }
}

# ============== 主流程 ==============

Write-Host "=== SC2 Vibe 静态自检 ===" -ForegroundColor Cyan
Write-Host "  galaxy-vibe root: $ScriptRoot"

# 1. JSON schema 校验
Write-Host "`n[1/7] JSON schema 校验" -ForegroundColor DarkCyan
$jsonFiles = @(
    @("schema\rpc-schema.json", "rpc-schema"),
    @("schema\rpc-response-schema.json", "rpc-response-schema"),
    @("kernel\whitelist.json", "whitelist"),
    @("observer\snapshot.schema.json", "snapshot-schema"),
    @("consumers\dead-of-night\consumer.json", "consumer-dead-of-night"),
    @("consumers\keha-rift\consumer.json", "consumer-keha-rift"),
    @("consumers\shared\extraction-manifest.json", "extraction-manifest")
)
$jsonContents = @{}
foreach ($f in $jsonFiles) {
    $path = Join-Path $ScriptRoot $f[0]
    $content = Test-JsonFile -Path $path -Name $f[1]
    if ($content) { $jsonContents[$f[1]] = $content }
}

# 2. Python 语法校验
Write-Host "`n[2/7] Python 语法校验" -ForegroundColor DarkCyan
$pyFiles = @(
    @("host\vibe_host.py", "vibe_host"),
    @("host\classifier.py", "classifier"),
    @("host\correction.py", "correction"),
    @("host\recovery.py", "recovery"),
    @("host\cleanup.py", "cleanup"),
    @("host\performance.py", "performance"),
    @("host\soak.py", "soak"),
    @("observer\state_observer.py", "state_observer"),
    @("observer\assertion_runner.py", "assertion_runner"),
    @("visual\capture.py", "capture"),
    @("visual\roi_evaluator.py", "roi_evaluator"),
    @("visual\stabilize.py", "stabilize"),
    @("cold\orchestrator.py", "cold-orchestrator"),
    @("cold\change_classifier.py", "cold-change-classifier"),
    @("cold\static_validator.py", "cold-static-validator"),
    @("cold\scenario_recipe.py", "cold-scenario-recipe"),
    @("transport\bank_probe.py", "bank-probe"),
    @("transport\chat_probe.py", "chat-probe"),
    @("transport\input_probe.py", "input-probe"),
    @("transport\transport_verdict.py", "transport-verdict"),
    @("consumers\shared\adapter.py", "shared-adapter"),
    @("tests\test_kernel.py", "test-kernel"),
    @("evidence_bundle.py", "evidence_bundle")
)
foreach ($f in $pyFiles) {
    $path = Join-Path $ScriptRoot $f[0]
    Test-PythonFile -Path $path -Name $f[1]
}

# 3. Galaxy 文件校验
Write-Host "`n[3/7] Galaxy 文件校验" -ForegroundColor DarkCyan
$galaxyFiles = @(
    @("kernel\LibVibeKernel.galaxy", "LibVibeKernel"),
    @("kernel\LibVibeKernel_h.galaxy", "LibVibeKernel_h")
)
foreach ($f in $galaxyFiles) {
    $path = Join-Path $ScriptRoot $f[0]
    Test-GalaxyFile -Path $path -Name $f[1]
}

# 4. 必需文件清单
Write-Host "`n[4/7] 必需文件清单" -ForegroundColor DarkCyan
$requiredFiles = @(
    @("vibe.ps1", "vibe.ps1 统一入口"),
    @("run-all-validation.ps1", "run-all-validation.ps1 验证脚本"),
    @("transport\run-transport-probes.ps1", "P0 传输探针脚本"),
    @("tests\test_kernel.py", "P1 单元测试"),
    @("evidence_bundle.py", "P7 证据包生成器")
)
foreach ($f in $requiredFiles) {
    $path = Join-Path $ScriptRoot $f[0]
    Test-FileExists -Path $path -Name $f[1]
}

# 5. whitelist.json 与 kernel Galaxy 一致性
Write-Host "`n[5/7] whitelist/kernel 一致性" -ForegroundColor DarkCyan
if ($jsonContents.ContainsKey("whitelist")) {
    try {
        $wl = $jsonContents["whitelist"] | ConvertFrom-Json
        $whitelistOps = @()
        if ($wl.operations) {
            $whitelistOps = $wl.operations | ForEach-Object { $_.name }
        } elseif ($wl.PSObject.Properties.Name -contains "operations") {
            $whitelistOps = $wl.operations.name
        }
        $kernelPath = Join-Path $ScriptRoot "kernel\LibVibeKernel.galaxy"
        if (Test-Path $kernelPath) {
            $kernelContent = Get-Content $kernelPath -Raw -Encoding UTF8
            $missingInKernel = @()
            foreach ($op in $whitelistOps) {
                if ($kernelContent -notlike "*$op*") {
                    $missingInKernel += $op
                }
            }
            if ($missingInKernel.Count -eq 0) {
                Add-Check "consistency" "whitelist-vs-kernel" "passed" "$($whitelistOps.Count) 个操作均在 kernel 中存在"
            } else {
                Add-Check "consistency" "whitelist-vs-kernel" "failed" "kernel 缺失操作: $($missingInKernel -join ', ')"
            }
        } else {
            Add-Check "consistency" "whitelist-vs-kernel" "warning" "kernel 文件不存在，跳过"
        }
    } catch {
        Add-Check "consistency" "whitelist-vs-kernel" "failed" "解析 whitelist.json 失败: $_"
    }
} else {
    Add-Check "consistency" "whitelist-vs-kernel" "warning" "whitelist.json 未读取，跳过"
}

# 6. consumer.json 配置校验
Write-Host "`n[6/7] consumer.json 配置" -ForegroundColor DarkCyan
foreach ($consumerName in @("dead-of-night", "keha-rift")) {
    $key = "consumer-$consumerName"
    if ($jsonContents.ContainsKey($key)) {
        try {
            $cfg = $jsonContents[$key] | ConvertFrom-Json
            $requiredFields = @("consumer_id", "map", "commander", "launcher", "recipe")
            $missing = @()
            foreach ($fld in $requiredFields) {
                if (-not ($cfg.PSObject.Properties.Name -contains $fld)) {
                    $missing += $fld
                }
            }
            if ($missing.Count -eq 0) {
                Add-Check "consumer" "$consumerName-config" "passed"
            } else {
                Add-Check "consumer" "$consumerName-config" "failed" "缺失字段: $($missing -join ', ')"
            }
        } catch {
            Add-Check "consumer" "$consumerName-config" "failed" "解析错误: $_"
        }
    }
}

# 7. P0-P7 交付物清单
Write-Host "`n[7/7] P0-P7 交付物清单" -ForegroundColor DarkCyan
$phaseDeliverables = [ordered]@{
    p0 = @("schema\rpc-schema.json", "schema\rpc-response-schema.json", "transport\bank_probe.py", "transport\chat_probe.py", "transport\input_probe.py")
    p1 = @("kernel\LibVibeKernel.galaxy", "kernel\whitelist.json", "tests\test_kernel.py")
    p2 = @("observer\state_observer.py", "observer\assertion_runner.py", "observer\snapshot.schema.json")
    p3 = @("visual\capture.py", "visual\roi_evaluator.py", "visual\stabilize.py")
    p4 = @("cold\orchestrator.py", "cold\change_classifier.py", "cold\static_validator.py")
    p5 = @("host\classifier.py", "host\correction.py")
    p6 = @("consumers\keha-rift\consumer.json", "consumers\shared\adapter.py", "consumers\shared\extraction-manifest.json")
    p7 = @("host\recovery.py", "host\cleanup.py", "host\performance.py", "host\soak.py", "vibe.ps1", "evidence_bundle.py")
}
foreach ($phase in $phaseDeliverables.Keys) {
    $missing = @()
    foreach ($rel in $phaseDeliverables[$phase]) {
        $p = Join-Path $ScriptRoot $rel
        if (-not (Test-Path $p)) { $missing += $rel }
    }
    if ($missing.Count -eq 0) {
        Add-Check "phases" "deliverables-$phase" "passed"
    } else {
        Add-Check "phases" "deliverables-$phase" "failed" "缺失: $($missing -join ', ')"
    }
}

# 总结
Write-Host "`n=== 总结 ===" -ForegroundColor Cyan
Write-Host "  总检查: $($report.total_checks)"
Write-Host "  通过: $($report.passed)" -ForegroundColor Green
$failedColor = "Gray"
if ($report.failed -gt 0) { $failedColor = "Red" }
Write-Host "  失败: $($report.failed)" -ForegroundColor $failedColor
Write-Host "  警告: $($report.warnings)" -ForegroundColor Yellow

if ($report.failed -eq 0) {
    $report.overall = "passed"
    if ($report.warnings -gt 0) {
        $report.overall = "passed_with_warnings"
    }
} else {
    $report.overall = "failed"
}

# 写入报告文件
$artifactsDir = Join-Path (Split-Path -Parent (Split-Path -Parent $ScriptRoot)) "artifacts\galaxy-vibe"
if (-not (Test-Path $artifactsDir)) {
    New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
}
$reportPath = Join-Path $artifactsDir "static-validation-report.json"
$report | ConvertTo-Json -Depth 10 | Out-File -FilePath $reportPath -Encoding utf8
Write-Host "  报告: $reportPath" -ForegroundColor DarkGray

if ($report.failed -gt 0) {
    exit 1
}
exit 0
