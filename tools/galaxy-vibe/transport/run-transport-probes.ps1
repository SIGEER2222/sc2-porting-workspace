<#
.SYNOPSIS
    P0 传输闸门完整运行脚本：运行三种 transport probe 并聚合判定。

.DESCRIPTION
    依据 sc2-vibe完整实施计划.md P0 闸门要求：
      1. 运行 bank_probe.py（首选 transport）
      2. 运行 chat_probe.py（备用 transport）
      3. 运行 input_probe.py（最后回退）
      4. 聚合生成 transport-verdict.json
      5. 复核 GameLogs 是否有新增 ScriptError

    前置条件：
      - SC2 已通过 launch-cmre-alenger.ps1 启动并加载 GalaxyVibe 调试 mod
      - SC2API 端口（默认 5000）可连接

.PARAMETER Port
    SC2 API listen port. Default 5000.

.PARAMETER OutDir
    证据输出目录. Default artifacts/galaxy-vibe/p0-transport.

.EXAMPLE
    .\run-transport-probes.ps1 -Port 5000
#>
param(
    [int]$Port = 5000,
    [string]$OutDir = "artifacts/galaxy-vibe/p0-transport",
    [string]$MapPath = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$OutDir = Join-Path $repo $OutDir

Write-Host "=== P0 Transport Gate ===" -ForegroundColor Cyan
Write-Host "Repo: $repo"
Write-Host "OutDir: $OutDir"
Write-Host "SC2API Port: $Port"
if ($MapPath) { Write-Host "MapPath: $MapPath" }
Write-Host ""

# 确保输出目录存在
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

# Step 1: Bank probe
Write-Host "[1/4] Running Bank transport probe..." -ForegroundColor Yellow
$bankScript = Join-Path $repo "tools/galaxy-vibe/transport/bank_probe.py"
$bankArgs = @("--port", $Port, "--out-dir", $OutDir)
if ($MapPath) { $bankArgs += @("--map-path", $MapPath) }
& python $bankScript @bankArgs
$bankRc = $LASTEXITCODE
Write-Host "      Bank probe exit code: $bankRc"
Write-Host ""

# Step 2: Chat probe
Write-Host "[2/4] Running Chat transport probe..." -ForegroundColor Yellow
$chatScript = Join-Path $repo "tools/galaxy-vibe/transport/chat_probe.py"
& python $chatScript --port $Port --out-dir $OutDir
$chatRc = $LASTEXITCODE
Write-Host "      Chat probe exit code: $chatRc"
Write-Host ""

# Step 3: Input probe
Write-Host "[3/4] Running Input transport probe..." -ForegroundColor Yellow
$inputScript = Join-Path $repo "tools/galaxy-vibe/transport/input_probe.py"
& python $inputScript --out-dir $OutDir
$inputRc = $LASTEXITCODE
Write-Host "      Input probe exit code: $inputRc"
Write-Host ""

# Step 4: Aggregate verdict
Write-Host "[4/4] Aggregating transport verdict..." -ForegroundColor Yellow
$verdictScript = Join-Path $repo "tools/galaxy-vibe/transport/transport_verdict.py"
& python $verdictScript --out-dir $OutDir
$verdictRc = $LASTEXITCODE
Write-Host ""

# 复核 ScriptError
Write-Host "=== ScriptError 复核 ===" -ForegroundColor Cyan
$gameLogs = Join-Path $env:USERPROFILE "Documents\StarCraft II\GameLogs"
if (Test-Path $gameLogs) {
    $scriptErrors = Get-ChildItem -Path $gameLogs -Filter "ScriptError.*.txt" -ErrorAction SilentlyContinue
    if ($scriptErrors) {
        Write-Host "WARNING: 发现 $($scriptErrors.Count) 个 ScriptError 文件" -ForegroundColor Red
        $scriptErrors | Select-Object -First 5 | ForEach-Object { Write-Host "  $($_.Name)" }
    } else {
        Write-Host "OK: 无 ScriptError" -ForegroundColor Green
    }
} else {
    Write-Host "SKIP: GameLogs 目录不存在" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Verdict ===" -ForegroundColor Cyan
$verdictPath = Join-Path $OutDir "transport-verdict.json"
if (Test-Path $verdictPath) {
    $verdict = Get-Content $verdictPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "Overall: $($verdict.verdict)"
    Write-Host "Can proceed to P1: $($verdict.can_proceed_to_p1)"
    Write-Host "Selected transport: $($verdict.selected_transport)"
} else {
    Write-Host "ERROR: transport-verdict.json 未生成" -ForegroundColor Red
}

exit $verdictRc
