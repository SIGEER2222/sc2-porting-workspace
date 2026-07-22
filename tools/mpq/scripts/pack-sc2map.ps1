# pack-sc2map.ps1 - 将目录打包为 SC2Map/SC2Mod 文件
# 用法: .\pack-sc2map.ps1 <input_dir> <output_map_path>
# 示例: .\pack-sc2map.ps1 "extracted_dir" "new_map.SC2Map"

param(
    [Parameter(Mandatory=$true)][string]$InputDir,
    [Parameter(Mandatory=$true)][string]$OutputPath
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$packPy = Join-Path $scriptDir "pack_mpq.py"

if (-not (Test-Path $packPy)) {
    Write-Error "pack_mpq.py not found at $packPy"
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

python $packPy $inputFull $outputFull

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