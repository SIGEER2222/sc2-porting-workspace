<#
.SYNOPSIS
    Launch SC2 with the Galaxy Vibe debug mod + SC2 API, then run the P0 transport probe.

.DESCRIPTION
    Mounts tools/galaxy-vibe/galaxy-debug-mod as a -mod, starts a test map with -listen/-port,
    waits for the /sc2api port, then (with -AutoProbe) runs tools/galaxy-vibe/transport_probe.py.

    Sandbox note: in a headless/sandboxed environment the Switcher may drop -listen/-port and the
    /sc2api websocket never comes up (see tools/launchers/run-live-runtime-probe.ps1). Run on a
    real desktop where SC2 launches normally.

.PARAMETER Port
    SC2 API listen port. Default 5000.

.PARAMETER Map
    Test map to load. Default: artifacts/runtime/cmre/blank_test_neuro.SC2Map

.PARAMETER ModPath
    Debug mod folder (.SC2Mod). Default: tools/galaxy-vibe/galaxy-debug-mod

.PARAMETER AutoProbe
    After SC2 is up, automatically run transport_probe.py.

.PARAMETER Repl
    After SC2 is up, launch the P1 interactive REPL (galaxy_repl.py) in the foreground.

.PARAMETER Verify
    One-shot verification: launch SC2, run <scenario> via --assert-file, then run the
    ScriptError gate and summarize into a single PASS/FAIL verdict (exit code 0/1).
    Example: .\launch-galaxy-vibe.ps1 -Verify tools/galaxy-vibe/examples/my_test.vtest

.PARAMETER Visual
    P3 视觉闭环开关（仅真机桌面有效）。在 -Verify 链尾追加 visual_loop 实时采集，判定
    "场景稳定"并写 visual-verdict.json，由 summarize 一并收口。沙箱无 mss 会自动跳过。
    配合 -VisualRoi / -VisualThreshold / -VisualSteady 调参。

.PARAMETER VisualRoi
    P3 采集 ROI，格式 x,y,w,h（像素）。默认全屏。

.PARAMETER VisualThreshold
    P3 稳态阈值（ROI 内平均像素差 <= 此值视为稳态帧）。默认 8.0。

.PARAMETER VisualSteady
    P3 判定稳定所需的连续稳态帧数。默认 3。

.PARAMETER Python
    Python interpreter with aiohttp + vendored s2clientprotocol. Default: python

.EXAMPLE
    .\launch-galaxy-vibe.ps1 -Repl
.EXAMPLE
    .\launch-galaxy-vibe.ps1 -AutoProbe
.EXAMPLE
    .\launch-galaxy-vibe.ps1 -Verify tools/galaxy-vibe/examples/my_test.vtest -Visual -VisualRoi "100,80,800,600"
#>
param(
    [int]$Port = 5000,
    [string]$Map = "",
    [string]$ModPath = "",
    [switch]$AutoProbe,
    [switch]$Repl,
    [string]$Verify = "",
    [switch]$Visual,
    [string]$VisualRoi = "",
    [double]$VisualThreshold = 8.0,
    [int]$VisualSteady = 3,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Map)     { $Map = Join-Path $repo "artifacts/runtime/cmre/blank_test_neuro.SC2Map" }
# 只有未传 -ModPath 参数时才用默认 mod；传 -ModPath "" 表示不挂载 mod
if (-not $PSBoundParameters.ContainsKey('ModPath')) { $ModPath = Join-Path $repo "tools/galaxy-vibe/galaxy-debug-mod" }

$switcher = $null
$candidates = @(
    "E:\SC2\SC2new\StarCraft II\Support64\SC2Switcher_x64.exe",
    "C:\Program Files (x86)\StarCraft II\Support64\SC2Switcher_x64.exe",
    "$env:PROGRAMFILES\StarCraft II\Support64\SC2Switcher_x64.exe",
    "${env:PROGRAMFILES(X86)}\StarCraft II\Support64\SC2Switcher_x64.exe"
)
foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $switcher = $c; break } }
if (-not $switcher) { Write-Error "Could not locate SC2Switcher_x64.exe. Install StarCraft II or set its path." }

if (-not (Test-Path $Map))     { Write-Error "Map not found: $Map" }
# ModPath 为空字符串时跳过检查（表示不挂载 mod）
if ($ModPath -and -not (Test-Path $ModPath)) { Write-Error "Debug mod not found: $ModPath" }

Write-Host "[1/4] Killing any running SC2 ..."
Get-Process -Name "SC2_x64", "SC2Switcher_x64" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "[2/4] Launching SC2 (Switcher) with debug mod + API on port $Port ..."
# 正确参数格式：-listen <host> -port <port> -debug（SC2 静默忽略 -listenPort）
# 窗口化启动（-displayMode 0 + 窗口尺寸）是首帧崩溃(SIGEER B97563 / ACCESS_VIOLATION 0x40)的根本修复：
# 全屏 SC2 会抢独占 D3D9 设备，与已运行实例/显示器冲突导致 "Lost D3D9 device" → 重置失败 → 读空指针崩溃。
# 窗口化使用非独占设备，稳定。之前为"修黑屏"误删 -displayMode 0 是回归，现已恢复。
# API 模式下不传 map 作为位置参数（Switcher 不会自动加载地图到 in_game 状态），
# 让客户端用 CreateGame + JoinGame 推进到 in_game（与 launch-cmre-alenger.ps1 设计一致）
$args = @("-listen", "127.0.0.1", "-port", "$Port", "-debug", "-displayMode", "0", "-windowwidth", "1280", "-windowheight", "720")
# 只有 ModPath 非空时才挂载 mod（避免 mod 冲突导致 SC2 退出）
if ($ModPath) { $args += @("-mod", "$ModPath") }
Write-Host "      $switcher $($args -join ' ')"
Write-Host "      Map (for client CreateGame): $Map"
# WorkingDirectory 必须设为 SC2 安装根目录，否则 SC2 可能回退到默认端口 6119
$sc2Root = Split-Path -Parent (Split-Path -Parent $switcher)
$launched = Start-Process -FilePath $switcher -ArgumentList $args -PassThru -WorkingDirectory $sc2Root
Write-Host "      Switcher PID=$($launched.Id) WorkingDir=$sc2Root"

# 阶段 1：等待 SC2_x64 进程出现（Switcher 启动 SC2_x64 需要 patch 检查 + auth，可能 30-60s）
$sc2Proc = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    $sc2Proc = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
    if ($sc2Proc) { Write-Host "      SC2_x64 PID=$($sc2Proc.Id) appeared (~$([int]($i * 2))s)"; break }
}
if (-not $sc2Proc) {
    Write-Error "SC2_x64.exe never started within 120s. Check GameLogs for crash; Switcher may have failed auth."
}

# 阶段 2：等待 API 端口开放（SC2_x64 启动后还需要加载 mod/资源，可能 30-90s）
$opened = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        if ($ar.AsyncWaitHandle.WaitOne(1500) -and $c.Connected) { $c.EndConnect($ar); $c.Close(); Write-Host "      API port $Port OPEN (~$([int]($i * 2))s after SC2_x64 appeared)"; $opened = $true; break }
        else { $c.Close() }
    }
    catch { }
    # 如果 SC2_x64 进程消失了（不是 Switcher），说明崩溃了
    if (-not (Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue)) { Write-Host "      SC2_x64 exited before port opened (crash?)"; break }
}
if (-not $opened) {
    Write-Error "SC2 API port $Port never opened. On a normal desktop check GameLogs; in a sandbox the Switcher may drop -listen/-port."
}

# 写启动标记，供 tools/galaxy-vibe/script_error_check.py 判定"本次启动以来"的新增 ScriptError
$markerDir = Join-Path $env:USERPROFILE "Documents\StarCraft II"
if (-not (Test-Path $markerDir)) { New-Item -ItemType Directory -Path $markerDir -Force | Out-Null }
$markerPath = Join-Path $markerDir "galaxy-vibe-launch.json"
$epoch = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
@{
    launched_at      = $epoch
    launched_at_iso  = ([DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"))
    port             = $Port
    map              = $Map
    mod              = $ModPath
} | ConvertTo-Json | Set-Content -Path $markerPath -Encoding UTF8
Write-Host "      Wrote launch marker -> $markerPath (launched_at=$epoch)"

if ($Verify) {
    Write-Host "[3/4] Running scenario asserts (assert-file: $Verify) ..."
    $replScript = Join-Path $repo "tools/galaxy-vibe/galaxy_repl.py"
    & $Python $replScript --port $Port --map $Map --assert-file $Verify
    $assertRc = $LASTEXITCODE
    Write-Host "      assert exit code=$assertRc"
    Write-Host "[4/4] ScriptError gate + (optional P3 visual) + summarize -> vibe-verdict.json"
    $checker = Join-Path $repo "tools/galaxy-vibe/script_error_check.py"
    & $Python $checker
    $seRc = $LASTEXITCODE

    if ($Visual) {
        Write-Host "      [P3] Visual loop: capturing live window (mss) ..."
        $vloop = Join-Path $repo "tools/galaxy-vibe/visual_loop.py"
        $vArgs = @("--capture-loop", "--adapter", "mss", "--threshold", "$VisualThreshold", "--steady", "$VisualSteady")
        if ($VisualRoi) { $vArgs += @("--roi", $VisualRoi) }
        & $Python $vloop @vArgs
        $visRc = $LASTEXITCODE
        Write-Host "      visual exit code=$visRc (sandbox w/o mss -> skipped, no verdict)"
    }

    $summ = Join-Path $repo "tools/galaxy-vibe/summarize_verdict.py"
    & $Python $summ
    $finalRc = $LASTEXITCODE
    if ($assertRc -ne 0 -and $finalRc -eq 0) {
        Write-Host "      overriding final verdict: assert runner failed before/while writing assertions" -ForegroundColor Yellow
        $finalRc = $assertRc
    }
    if ($seRc -ne 0 -and $finalRc -eq 0) {
        Write-Host "      overriding final verdict: ScriptError gate failed" -ForegroundColor Yellow
        $finalRc = $seRc
    }
    Write-Host "VERDICT exit code=$finalRc (assert_rc=$assertRc, scripterror_rc=$seRc)"
    exit $finalRc
}

if ($AutoProbe) {
    Write-Host "[3/4] Running P0 transport probe ..."
    $probe = Join-Path $repo "tools/galaxy-vibe/transport_probe.py"
    & $Python $probe --port $Port --out-dir (Join-Path $repo "artifacts/galaxy-vibe")
    Write-Host "[4/4] Probe exit code=$LASTEXITCODE"
}

if ($Repl) {
    Write-Host "[3/4] Launching P1 Vibe REPL ..."
    $replScript = Join-Path $repo "tools/galaxy-vibe/galaxy_repl.py"
    & $Python $replScript --port $Port --map $Map
    Write-Host "[4/4] REPL exited."
    exit $LASTEXITCODE
}

Write-Host "[3/4] SC2 is running with debug mod. In another shell run:"
Write-Host "      python tools/galaxy-vibe/galaxy_repl.py --port $Port      # P1 交互 REPL"
Write-Host "      python tools/galaxy-vibe/transport_probe.py --port $Port  # P0 传输探针"
Write-Host "[4/4] Done. After testing, check GameLogs for new ScriptError.*.txt."
