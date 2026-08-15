[CmdletBinding()]
param(
    [string]$Map = "artifacts/projects/cmre-porting/stage26-full-function-invoke/input-map-original.SC2Map",
    [int]$Port = 8769,
    [string]$Sc2Root = $env:SC2_ROOT,
    [string[]]$ModRoot = @(),
    [string]$Verify = "tools/cmre-webui/debug_map_smoke.vtest"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = (Get-Command python -ErrorAction Stop).Source
$script = Join-Path $PSScriptRoot "debug_map_runtime.py"
$args = @($script, "--map", $Map, "--port", "$Port", "--verify", $Verify)
if ($Sc2Root) { $args += @("--sc2-root", $Sc2Root) }
foreach ($root in $ModRoot) { $args += @("--mod-root", $root) }
Push-Location $repo
try {
    & $python @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
