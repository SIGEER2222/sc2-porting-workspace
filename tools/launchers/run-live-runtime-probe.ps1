<#
.SYNOPSIS
    Live SC2 runtime-unit-detection probe harness.

.DESCRIPTION
    Launches StarCraft II (via the Blizzard Switcher, matching the repo's existing
    launcher pattern) with a local test map AND the SC2 API enabled (-listenPort),
    then runs tools/runtime-bridge/sc2-observer.py to passively read real-time
    player units and assert them against a scenario.

    This is the "live" validation layer for the galaxy-units-and-groups skill:
    the blank_test_neuro map spawns a Marine for player 1 at init, and the observer
    must see a unit_created event owned by player 1.

    NOTE (sandbox limitation): in a headless/sandboxed environment the Blizzard
    Switcher may drop -listenPort (SC2 only binds its default service port and the
    /sc2api websocket never comes up), and launching SC2_x64.exe directly exits with
    code -2001 (it requires the Blizzard launcher/agent). On a real desktop where
    SC2 launches normally, this harness works as written.

.PARAMETER Port
    SC2 API listen port. Default 5000.

.PARAMETER Map
    Absolute or repo-relative path to the .SC2Map to load as a local game.
    Default: artifacts/runtime/cmre/blank_test_neuro.SC2Map

.PARAMETER Duration
    How long (seconds) the observer collects events. Default 30.

.PARAMETER Python
    Python interpreter that has 'aiohttp' and can import the vendored s2clientprotocol.
    Default: python (from PATH).

.EXAMPLE
    .\run-live-runtime-probe.ps1 -Port 5000
#>
param(
    [int]$Port = 5000,
    [string]$Map = "",
    [int]$Duration = 30,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot ".." "..")).Path
if (-not $Map) { $Map = Join-Path $repo "artifacts/runtime/cmre/blank_test_neuro.SC2Map" }
# Resolve the Blizzard Switcher from common SC2 install locations.
$switcher = $null
$candidates = @(
    "E:\SC2\SC2new\StarCraft II\Support64\SC2Switcher_x64.exe",
    "C:\Program Files (x86)\StarCraft II\Support64\SC2Switcher_x64.exe",
    "$env:PROGRAMFILES\StarCraft II\Support64\SC2Switcher_x64.exe",
    "${env:PROGRAMFILES(X86)}\StarCraft II\Support64\SC2Switcher_x64.exe"
)
foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $switcher = $c; break } }
if (-not $switcher) { Write-Error "Could not locate SC2Switcher_x64.exe. Set its path explicitly or install StarCraft II." }
$observer = Join-Path $repo "tools/runtime-bridge/sc2-observer.py"
$scenario = Join-Path $repo "src/projects/cmre-porting/evidence/runtime/live/scenario.json"
$outDir   = Join-Path $repo "src/projects/cmre-porting/evidence/runtime/live"

if (-not (Test-Path $Map))     { Write-Error "Map not found: $Map" }
if (-not (Test-Path $observer)){ Write-Error "Observer not found: $observer" }
if (-not (Test-Path $scenario)){ Write-Error "Scenario not found: $scenario" }

# Runtime-verification (API) mode must NEVER kill or assume ownership of an
# externally-owned (or lingering) SC2 instance. If SC2 is already running here,
# we cannot prove it is ours, so we fail-closed: record the external owner
# evidence and exit nonzero instead of disrupting the user's session.
# (Plan risk rule: 不终止或接管外部 owner；保持 blocked 并等待独立窗口. Module 7.5.)
Write-Host "[1/4] Checking for an existing SC2 instance ..."
$existingSc2 = @(Get-Process -Name "SC2_x64","SC2Switcher_x64" -ErrorAction SilentlyContinue)
if ($existingSc2.Count -gt 0) {
    $runtimeEvidenceRoot = Join-Path $repo "artifacts/runtime"
    if (-not (Test-Path -LiteralPath $runtimeEvidenceRoot)) {
        New-Item -ItemType Directory -Path $runtimeEvidenceRoot -Force | Out-Null
    }
    $blockedEvidence = [ordered]@{
        classification = "blocked"
        reason         = "external_sc2_owner_detected"
        detector       = "run-live-runtime-probe.ps1"
        pids           = @($existingSc2 | ForEach-Object { $_.Id })
        port           = $Port
        detail         = "Refusing to kill an externally-owned (or lingering) SC2 instance before the live runtime-unit probe. Free the runtime slot (close the external owner) and re-run for an independent window."
        recordedAt     = (Get-Date -Format "o")
    }
    $blockedEvidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runtimeEvidenceRoot "launcher-runtime-blocked.json") -Encoding UTF8
    throw ("External SC2 owner detected (pids: $($existingSc2.Id -join ',')) before live runtime-unit probe; refusing to kill it. Free the runtime slot and re-run for an independent window.")
}
# No SC2 running -> safe to launch our own isolated instance for the probe.

Write-Host "[2/4] Launching SC2 (Switcher) with map + API on port $Port ..."
$args = @($Map, "-listenPort", "$Port", "-displayMode", "0", "-windowWidth", "800", "-windowHeight", "600", "-novid")
Write-Host "      $switcher $($args -join ' ')"
$launched = Start-Process -FilePath $switcher -ArgumentList $args -PassThru
Write-Host "      Switcher PID=$($launched.Id)"

$opened = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        if ($ar.AsyncWaitHandle.WaitOne(1500) -and $c.Connected) { $c.EndConnect($ar); $c.Close(); Write-Host "      API port $Port OPEN (~$([int]($i*2))s)"; $opened = $true; break }
        else { $c.Close() }
    } catch {}
    if (-not (Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue)) { Write-Host "      SC2_x64 exited before port opened (attempt $i)"; break }
}
if (-not $opened) {
    Write-Error "SC2 API port $Port never opened. On a normal desktop this means SC2 failed to start the /sc2api server (check GameLogs). In a sandbox the Switcher may drop -listenPort."
}

Write-Host "[3/4] Running observer (duration ${Duration}s) ..."
& $Python $observer --port $Port --duration $Duration --scenario $scenario --out-dir $outDir
$rc = $LASTEXITCODE

Write-Host "[4/4] Verdict:"
$verdictPath = Join-Path $outDir "verdict.json"
if (Test-Path $verdictPath) {
    Get-Content $verdictPath -Raw -Encoding UTF8
} else {
    Write-Host "      (no verdict.json produced; observer exit code=$rc)"
}
Write-Host ""
Write-Host "Done. Events: $(Join-Path $outDir 'events.ndjson')"
exit $rc
