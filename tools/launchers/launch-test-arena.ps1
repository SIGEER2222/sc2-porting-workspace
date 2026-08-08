<#
.SYNOPSIS
    Debug arena map test launcher (test-arena project).

.DESCRIPTION
    Packs the unpacked debug-arena map into a .SC2Map, then calls launch-galaxy-vibe.ps1
    to start SC2 + API. Standalone map, no commander mod (-ModPath "").
    Launcher only orchestrates (pack + call); no embedded Galaxy/patch code.
    Note: map directory name contains CJK chars; to avoid PS 5.x GBK/UTF-8 BOM issues
    we resolve the map dir dynamically via Get-ChildItem instead of hardcoding its name.

.PARAMETER Port
    SC2 API listen port. Default 5000.

.PARAMETER AutoProbe
    After SC2 is up, run transport_probe.py (P0 transport-layer check: kernel_initialized).

.PARAMETER Repl
    After SC2 is up, enter P1 interactive REPL (galaxy_repl.py).

.PARAMETER Verify
    One-shot verification: launch SC2 + run <scenario> + ScriptError gate + PASS/FAIL.

.PARAMETER NoLaunch
    Pack only, do not start SC2 (for static validation of the pack pipeline).

.PARAMETER Python
    Python interpreter. Default python.

.EXAMPLE
    .\launch-test-arena.ps1 -NoLaunch           # pack only, validate injected map packs cleanly
    .\launch-test-arena.ps1 -AutoProbe          # pack + launch + P0 transport probe
#>
param(
    [int]$Port = 5000,
    [switch]$AutoProbe,
    [switch]$Repl,
    [string]$Verify = "",
    [switch]$NoLaunch,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# Resolve map dir dynamically (name has CJK; avoid hardcoding to dodge PS5 GBK/BOM issues)
$mapsRoot = Join-Path $repo "src\projects\test-arena\packages\Maps"
if (-not (Test-Path -LiteralPath $mapsRoot)) { Write-Error "Maps root not found: $mapsRoot" }
$mapDir = $null
Get-ChildItem -LiteralPath $mapsRoot -Directory | Where-Object { $_.Name -like "*.SC2Map" } | Select-Object -First 1 | ForEach-Object { $mapDir = $_.FullName }
if (-not $mapDir) { Write-Error "No *.SC2Map directory found under $mapsRoot" }

$outDir = Join-Path $repo "artifacts\projects\test-arena\stage01"
$outMap = Join-Path $outDir "test-arena.SC2Map"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

Write-Host "[1/2] Packing debug arena map ..."
Write-Host "      src: $mapDir"
# Call pack_stormlib.py directly (pack-sc2map.ps1 has a workspaceRoot path bug:
# it goes up 4 levels to SC2VibeTools instead of 3 to sc2-porting-workspace).
$packPy = Join-Path $repo "tools\mpq\scripts\pack_stormlib.py"
if (-not (Test-Path $packPy)) { Write-Error "pack_stormlib.py not found: $packPy" }
$stormlibDll = Join-Path $repo "artifacts\stormlib-v9.40\x64\StormLib.dll"
if (-not (Test-Path $stormlibDll)) {
    $stormlibDll = Join-Path $repo "artifacts\stormlib-v9.40\Win32\StormLib.dll"
}
if (-not (Test-Path $stormlibDll)) { Write-Error "StormLib.dll not found under artifacts\stormlib-v9.40\" }
python $packPy $mapDir $outMap --stormlib $stormlibDll
if ($LASTEXITCODE -ne 0) { Write-Error "Pack failed (exit $LASTEXITCODE)" }
Write-Host "      out: $outMap ($([math]::Round((Get-Item $outMap).Length/1MB,2)) MB)"

if ($NoLaunch) {
    Write-Host "[2/2] -NoLaunch set, skipping SC2 start."
    exit 0
}

Write-Host "[2/2] Launching SC2 via launch-galaxy-vibe.ps1 (no mod) ..."
$launcher = Join-Path $repo "tools\galaxy-vibe\launch-galaxy-vibe.ps1"
if (-not (Test-Path $launcher)) { Write-Error "launch-galaxy-vibe.ps1 not found: $launcher" }
# Use named hashtable splatting to avoid positional-argument confusion
# (launch-galaxy-vibe.ps1's first param is [int]$Port, so array splatting would bind -Map to $Port).
# -ModPath with empty string explicitly = no mod (launch-galaxy-vibe.ps1 line 74 checks $PSBoundParameters.ContainsKey).
$lparams = @{
    Port     = $Port
    Map      = $outMap
    ModPath  = ""
    Python   = $Python
}
if ($AutoProbe) { $lparams["AutoProbe"] = $true }
if ($Repl)     { $lparams["Repl"]     = $true }
if ($Verify)   { $lparams["Verify"]   = $Verify }
& $launcher @lparams
exit $LASTEXITCODE
