<#
.SYNOPSIS
    Start the CMRE WebUI.

.DESCRIPTION
    Runs the standard-library Python WebUI server from the repository root.
    The server stays in the foreground so Ctrl+C stops it cleanly.

.PARAMETER Port
    HTTP port. Default: 8767.

.PARAMETER BindAddress
    Address to bind. Default: 127.0.0.1.

.PARAMETER Python
    Python command or executable path. Default: py.

.PARAMETER PythonVersion
    Version passed to the Windows Python launcher when -Python is py.
    Default: 3.13. Pass an empty string to use the launcher's default.

.PARAMETER NoBrowser
    Do not open the WebUI in the default browser.

.EXAMPLE
    .\start-webui.ps1

.EXAMPLE
    .\start-webui.ps1 -Port 8768 -NoBrowser
#>
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8767,

    [string]$BindAddress = "127.0.0.1",

    [string]$Python = "py",

    [string]$PythonVersion = "3.13",

    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$server = Join-Path $PSScriptRoot "server.py"

if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
    throw "WebUI server not found: $server"
}

$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "Python command not found: $Python"
}

Set-Location -LiteralPath $repo

$pythonArgs = @()
$pythonName = [System.IO.Path]::GetFileNameWithoutExtension($Python)
if ($pythonName -ieq "py" -and $PythonVersion) {
    $pythonArgs += "-$PythonVersion"
}

$pythonArgs += @(
    $server,
    "--host", $BindAddress,
    "--port", [string]$Port
)
if ($NoBrowser) {
    $pythonArgs += "--no-browser"
}

Write-Host "Starting CMRE WebUI at http://${BindAddress}:${Port}"
Write-Host "Press Ctrl+C to stop."

& $Python @pythonArgs
exit $LASTEXITCODE
