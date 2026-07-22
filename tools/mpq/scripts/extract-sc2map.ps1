# extract-sc2map.ps1 - 解包 SC2Map/SC2Mod 文件
# 用法: .\extract-sc2map.ps1 <map_path> <output_dir> [filter]
# 示例: .\extract-sc2map.ps1 "map.SC2Map" "out" "*.xml"
#       .\extract-sc2map.ps1 "map.SC2Mod" "out" "*"
#
# 默认使用 MPQEditor，失败时自动降级到 mpyq (Python)。
# 路径含特殊字符（如 ~~）时建议直接用 extract_mpq.py。

param(
    [Parameter(Mandatory=$true)][string]$MapPath,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [string]$Filter = "*",
    [switch]$UseMpyq  # 强制使用 mpyq
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillDir = Split-Path -Parent $scriptDir
$mpqEditor = Join-Path $skillDir "MPQEditor.exe"
$mpyqPy = Join-Path $scriptDir "extract_mpq.py"

if (-not (Test-Path $MapPath)) {
    Write-Error "Map file not found: $MapPath"
    exit 1
}

# Ensure output directory exists
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# Resolve full paths (使用 .NET 避免特殊字符问题)
$mapPathFull = (Get-Item $MapPath).FullName
$outputFull = (Get-Item $OutputDir).FullName

Write-Host "Extracting: $mapPathFull -> $outputFull (filter: $Filter)"

$success = $false

# 方法1: MPQEditor (默认)
if (-not $UseMpyq -and (Test-Path $mpqEditor)) {
    Write-Host "Using MPQEditor..."
    $result = & $mpqEditor /extract $mapPathFull $Filter $outputFull /fp 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        $fileCount = (Get-ChildItem $outputFull -Recurse -File).Count
        Write-Host "MPQEditor: $fileCount files extracted"
        $success = $true
    } else {
        Write-Warning "MPQEditor failed (exit $exitCode), falling back to mpyq..."
    }
}

# 方法2: mpyq (备选或强制)
if (-not $success) {
    if (-not (Test-Path $mpyqPy)) {
        Write-Error "extract_mpq.py not found at $mpyqPy"
        exit 1
    }
    Write-Host "Using mpyq (Python)..."
    python $mpyqPy $mapPathFull $outputFull $Filter
    if ($LASTEXITCODE -eq 0) {
        $success = $true
    } else {
        Write-Error "mpyq extraction failed (exit $LASTEXITCODE)"
        exit 1
    }
}

if ($success) {
    $fileCount = (Get-ChildItem $outputFull -Recurse -File).Count
    Write-Host "Extraction complete. $fileCount files extracted to $outputFull"
}
