<#
.SYNOPSIS
    Select and launch a registered CMRE map with a configured commander.

.DESCRIPTION
    Maps come from the CMRE porting project's source package manifest. Commanders come from the
    existing CMRE launcher configuration, which remains the authority for dependency wiring.
    Use -DryRun to inspect the exact selection without changing the live SC2 installation.
#>
[CmdletBinding()]
param(
    [string]$MapName,
    [string]$Commander,
    [switch]$List,
    [switch]$DryRun,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$Sc2Root = Split-Path -Parent $WorkspaceRoot
$LegacyRoot = Join-Path $Sc2Root "合作指挥官-起义狂潮"
$ProjectRoot = Join-Path $WorkspaceRoot "projects\cmre-porting"
$PackageManifestPath = Join-Path $ProjectRoot "manifests\source-packages.json"
$LauncherConfigPath = Join-Path $LegacyRoot "Shared\Launcher\cmre-dependencies.json"
$AlengerConfigPath = Join-Path $LegacyRoot "Shared\Launcher\alenger-mods.json"
$LauncherPath = Join-Path $LegacyRoot "scripts\cmre\launch-cmre.ps1"
$TestLockPath = Join-Path $LegacyRoot "scripts\sc2-launcher\test-lock.ps1"
$LegacyMapsRoot = Join-Path $LegacyRoot "Maps\CMRE"

foreach ($path in @($PackageManifestPath, $LauncherConfigPath, $AlengerConfigPath, $LauncherPath, $TestLockPath, $LegacyMapsRoot)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required path not found: $path"
    }
}

$packages = (Get-Content -Raw -LiteralPath $PackageManifestPath | ConvertFrom-Json).packages
$maps = @(
    $packages |
        Where-Object {
            $_.kind -eq "map" -and
            $_.source.path -match '^Maps/.+\.SC2Map$'
        } |
        ForEach-Object { Split-Path -Leaf $_.source.path } |
        Where-Object { Test-Path -LiteralPath (Join-Path $LegacyMapsRoot $_) } |
        Sort-Object -Unique
)
$commanders = @(
    @((Get-Content -Raw -LiteralPath $LauncherConfigPath | ConvertFrom-Json).validCommanders) +
    @((Get-Content -Raw -LiteralPath $AlengerConfigPath | ConvertFrom-Json).commanderToAlenger.PSObject.Properties.Name | ForEach-Object { "Terran$_" }) |
        Sort-Object -Unique
)

if ($maps.Count -eq 0) {
    throw "No registered CMRE maps are available under $LegacyMapsRoot"
}
if ($commanders.Count -eq 0) {
    throw "No CMRE commanders are configured by $LauncherConfigPath"
}

function Select-Choice {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Choices
    )

    Write-Host ""
    Write-Host "${Label}:"
    for ($index = 0; $index -lt $Choices.Count; $index++) {
        Write-Host ("  [{0}] {1}" -f ($index + 1), $Choices[$index])
    }

    while ($true) {
        $answer = Read-Host "Enter a number or exact value"
        $number = 0
        if ([int]::TryParse($answer, [ref]$number) -and $number -ge 1 -and $number -le $Choices.Count) {
            return $Choices[$number - 1]
        }
        if ($Choices -ccontains $answer) {
            return $answer
        }
        Write-Warning "Choose a listed number or exact value."
    }
}

if ($List) {
    [PSCustomObject]@{
        Maps = $maps
        Commanders = $commanders
        Launcher = $LauncherPath
    } | ConvertTo-Json -Depth 3
    exit 0
}

if ([string]::IsNullOrWhiteSpace($MapName)) {
    $MapName = Select-Choice -Label "Registered CMRE maps" -Choices $maps
}
if ([string]::IsNullOrWhiteSpace($Commander)) {
    $Commander = Select-Choice -Label "Configured commanders" -Choices $commanders
}

if ($maps -cnotcontains $MapName) {
    throw "Map is not a registered, available CMRE map: $MapName"
}
if ($commanders -cnotcontains $Commander) {
    throw "Commander is not configured for the CMRE launcher: $Commander"
}

$isAlenger = $Commander -match '^(Terran|Zerg|Protoss)Alenger\d+$'
$selectedLauncher = if ($isAlenger) { Join-Path $PSScriptRoot "launch-cmre-alenger.ps1" } else { $LauncherPath }
$launcherArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $selectedLauncher,
    "-Commander", $Commander,
    "-MapName", $MapName
)
if ($DryRun) {
    $launcherArguments += "-DryRun"
}
if ($NoLaunch) {
    $launcherArguments += "-NoLaunch"
}

Write-Host "Selected CMRE composition"
Write-Host "  Map: $MapName"
Write-Host "  Commander: $Commander"
Write-Host "  Mode: $(if ($DryRun) { 'dry run' } elseif ($NoLaunch) { 'stage only' } else { 'launch and wait for readiness' })"

if ($DryRun) {
    $result = Start-Process -FilePath "pwsh" -ArgumentList $launcherArguments -Wait -PassThru -NoNewWindow
    exit $result.ExitCode
}

$usesOwnLock = $isAlenger
if ($usesOwnLock) {
    $result = Start-Process -FilePath "pwsh" -ArgumentList $launcherArguments -Wait -PassThru -NoNewWindow
    exit $result.ExitCode
}

. $TestLockPath
$lock = $null
try {
    $lock = Acquire-TestLock -TestType "cmre_selected_composition" -MapName $MapName -Commander $Commander
    $result = Start-Process -FilePath "pwsh" -ArgumentList $launcherArguments -Wait -PassThru -NoNewWindow
    exit $result.ExitCode
}
finally {
    if ($lock) {
        Release-TestLock -LockContext $lock
    }
}
