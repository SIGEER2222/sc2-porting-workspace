# pack-sc2map.ps1 - 将目录打包为 SC2Map/SC2Mod 文件
# 用法: .\pack-sc2map.ps1 <input_dir> <output_map_path>
# 示例: .\pack-sc2map.ps1 "extracted_dir" "new_map.SC2Map"

param(
    [Parameter(Mandatory=$true)][string]$InputDir,
    [Parameter(Mandatory=$true)][string]$OutputPath
)

$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $PSCommandPath }
if (-not $scriptDir) { $scriptDir = "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\mpq\scripts" }
# 使用 StormLib 原生打包器（pack_stormlib.py），而非手写的 pack_mpq.py。
# pack_mpq.py 产生的 MPQ 格式 SC2 引擎无法正确解析（CreateGame 成功但 JoinGame 报"无法打开地图"）。
# StormLib 是 Blizzard MPQ 格式的参考实现，与 SC2 自身的 MPQ 读取器同源。
$packPy = Join-Path $scriptDir "pack_stormlib.py"

if (-not (Test-Path $packPy)) {
    Write-Error "pack_stormlib.py not found at $packPy"
    exit 1
}

# 查找 StormLib.dll（优先 x64）
# $scriptDir = .../sc2-porting-workspace/tools/mpq/scripts
# 2026-08-09 修复：原写死"上溯 4 级到 SC2VibeTools 根"，但 artifacts/ 实际位于
# sc2-porting-workspace 内（上溯 3 级）→ 一律 MISS，打包整链不可用。
# 改为按候选根依次探测，两种布局都能工作。
$repoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $scriptDir))   # sc2-porting-workspace
$outerRoot = Split-Path -Parent $repoRoot                                            # SC2VibeTools
$stormlibDll = $null
foreach ($root in @($repoRoot, $outerRoot)) {
    foreach ($arch in @("x64", "Win32")) {
        $candidate = Join-Path $root "artifacts\stormlib-v9.40\$arch\StormLib.dll"
        if (Test-Path $candidate) { $stormlibDll = $candidate; break }
    }
    if ($stormlibDll) { break }
}
if (-not $stormlibDll) {
    Write-Error "StormLib.dll not found under artifacts\stormlib-v9.40\ (searched: $repoRoot, $outerRoot)"
    exit 1
}

if (-not (Test-Path $InputDir)) {
    Write-Error "Input directory not found: $InputDir"
    exit 1
}

$inputFull = (Resolve-Path $InputDir).Path
$outputFull = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)

# Remove existing output file if it exists
if (Test-Path $outputFull) {
    Remove-Item $outputFull -Force -ErrorAction SilentlyContinue
}

Write-Host "Packing $inputFull -> $outputFull"

python $packPy $inputFull $outputFull --stormlib $stormlibDll

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pack failed (exit code $LASTEXITCODE)"
    exit 1
}

if (-not (Test-Path $outputFull)) {
    Write-Error "Output file was not created: $outputFull"
    exit 1
}

$size = (Get-Item $outputFull).Length
Write-Host "Pack complete. Output: $outputFull ($size bytes)"