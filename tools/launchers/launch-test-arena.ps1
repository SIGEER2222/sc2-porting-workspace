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
    Write-Host "[2/3] -NoLaunch set, skipping SC2 start."
    exit 0
}

# ---- ARENA-007：预写 GalaxyVibe.SC2Bank ----
# 斗蛐蛐地图是 sandbox 地图，从未通过 GUI 打开过，Bank 授权可能为空路径导致
# `BankLoad("GalaxyVibe", 1)` 返回 null，Init / RegisterEntryPoints 全部静默 no-op。
# 修复：launch 前将正确 SC2 格式的 Bank（单引号、Value int 属性、空 request/response
# section、preload_marker 诊断键）写到以下全部位置，保证任何 Publisher/Author
# hash 下 Galaxy 都能找到匹配文件：
#   1. Banks root（Python 侧 read_bank / write_bank_request 的默认路径）
#   2. Banks/<1..16>/（所有可能的数字 ID 目录）
#   3. Banks 下已存在的所有数字子目录（Author hash 可能很大的数字）
Write-Host "[2/3] ARENA-007: 预写 GalaxyVibe.SC2Bank（SC2 格式 XML）..."
$banksRoot = Join-Path $env:USERPROFILE "Documents\StarCraft II\Banks"
$bankContent = @'
<?xml version='1.0' encoding='utf-8'?>
<Bank version='1'>
    <Section name='index'>
        <Key name='preload_marker'>
            <Value int='1'/>
        </Key>
    </Section>
    <Section name='request'>
    </Section>
    <Section name='response'>
    </Section>
</Bank>
'@
$written = 0
$bankByteCount = [System.Text.Encoding]::UTF8.GetBytes($bankContent).Length
function Write-BankIfDiff([string]$targetPath, [string]$content) {
    $dir = Split-Path -Parent $targetPath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $existing = if (Test-Path $targetPath) { [System.IO.File]::ReadAllText($targetPath, [System.Text.Encoding]::UTF8) } else { $null }
    if ($existing -ne $content) {
        # UTF-8 with BOM matches SC2 Bank disk format
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        [System.IO.File]::WriteAllText($targetPath, $content, $utf8Bom)
    }
    $script:written += 1
}
# 1) Banks root
Write-BankIfDiff (Join-Path $banksRoot "GalaxyVibe.SC2Bank") $bankContent
# 2) 已存在的数字 ID 子目录（例如 1、14）
Get-ChildItem -LiteralPath $banksRoot -Directory | Where-Object { $_.Name -match '^\d+$' } | ForEach-Object {
    Write-BankIfDiff (Join-Path $_.FullName "GalaxyVibe.SC2Bank") $bankContent
}
# 3) 1..16 全覆盖（斗蛐蛐地图的 Publisher hash 可能在其中任何一个）
foreach ($i in 1..16) {
    Write-BankIfDiff (Join-Path (Join-Path $banksRoot $i) "GalaxyVibe.SC2Bank") $bankContent
}
Write-Host "      Banks root: $banksRoot"
Write-Host "      Bank payload: ${bankByteCount} bytes, index/preload_marker=int:1"
Write-Host "      Locations written: $written"

Write-Host "[3/3] Launching SC2 via launch-galaxy-vibe.ps1 ..."
$launcher = Join-Path $repo "tools\galaxy-vibe\launch-galaxy-vibe.ps1"
if (-not (Test-Path $launcher)) { Write-Error "launch-galaxy-vibe.ps1 not found: $launcher" }
# Use named hashtable splatting to avoid positional-argument confusion
# (launch-galaxy-vibe.ps1's first param is [int]$Port, so array splatting would bind -Map to $Port).
# -ModPath with empty string explicitly = no mod (launch-galaxy-vibe.ps1 line 74 checks $PSBoundParameters.ContainsKey).
$defaultMod = Join-Path $repo "tools\galaxy-vibe\galaxy-debug-mod"
$lparams = @{
    Port     = $Port
    Map      = $outMap
    ModPath  = $defaultMod
    Python   = $Python
}
if ($AutoProbe) { $lparams["AutoProbe"] = $true }
if ($Repl)     { $lparams["Repl"]     = $true }
if ($Verify)   { $lparams["Verify"]   = $Verify }
& $launcher @lparams
exit $LASTEXITCODE
