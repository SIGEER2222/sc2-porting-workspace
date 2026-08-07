<#
.SYNOPSIS
    Stage and launch the owned Revolution Overdrive commander/map package.

.DESCRIPTION
    This launcher owns orchestration only. It copies the verified package closure into the SC2
    install, launches through SC2Switcher, and records staging/runtime evidence. Mission scripts,
    alliance initialization, objectives, and rewards remain inside the selected map.
#>
[CmdletBinding()]
param(
    [string]$MapName = "traynor01.SC2Map",
    [ValidateSet("Iron", "Madness", "Pirate", "Coverts", "Umojan")]
    [string]$Faction = "Iron",
    [string]$Sc2Root = "",
    [int]$ListenPort = 0,
    [switch]$NoLaunch,
    [switch]$NoCheats,
    [string]$VoidCampaignSource = "",
    [switch]$ReplaceVoidCampaign,
    [string]$CampaignSourceRoot = "",
    [switch]$ReplaceCampaignDependencies,
    [int]$ReadyTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$packageRoot = Join-Path $workspace "src\projects\revolution-overdrive-porting\packages"
$modRoot = Join-Path $packageRoot "Commander\Mods"
$assetModsRoot = Join-Path $workspace "assets\src\projects\revolution-overdrive-porting\packages\Commander\Mods"
$mapsRoot = Join-Path $packageRoot "Maps"
$evidenceRoot = Join-Path $workspace "artifacts\projects\revolution-overdrive-porting\stage03-commander-package\launcher"
$gameLogsRoot = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "StarCraft II\GameLogs"
$runtimeEvidenceRoot = Join-Path $workspace "artifacts\projects\revolution-overdrive-porting\stage07-commander-closure"

$factions = @{
    Iron = "Iron"
    Madness = "Madness"
    Pirate = "Pirate"
    Coverts = "Coverts"
    Umojan = "Umojan"
}
$requiredMods = @(
    "RevolutionOverdrive.SC2Mod",
    "1钢铁之翼.SC2Mod",
    "33克哈.SC2Mod",
    "9海盗2333.SC2Mod",
    "通用效果.SC2Mod",
    "CovertOps.SC2Mod",
    "SCORE-Other.SC2Mod",
    "Umojan.SC2Mod"
)

function Resolve-Sc2Root {
    param([string]$Requested)
    if ($Requested) { return (Resolve-Path -LiteralPath $Requested).Path }
    $candidates = @(
        $env:SC2_ROOT,
        "E:\SC2\SC2new\StarCraft II",
        "C:\Program Files (x86)\StarCraft II",
        "C:\Program Files\StarCraft II"
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "Support64\SC2Switcher_x64.exe")) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "SC2 installation not found. Pass -Sc2Root or set SC2_ROOT."
}

function Copy-OwnedDirectory {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) { throw "Package directory not found: $Source" }
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Copy-DirectoryOverlay {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Asset overlay directory not found: $Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($item in @(Get-ChildItem -LiteralPath $Source -Force)) {
        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            Copy-DirectoryOverlay -Source $item.FullName -Destination $target
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

function Get-DirectoryManifest {
    param([string]$Source)
    $resolvedSource = (Resolve-Path -LiteralPath $Source).Path
    $records = @(
        Get-ChildItem -LiteralPath $resolvedSource -Recurse -File |
            Sort-Object FullName |
            ForEach-Object {
                $relative = $_.FullName.Substring($resolvedSource.Length).TrimStart('\').Replace('\', '/')
                $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
                [ordered]@{ path = $relative; bytes = $_.Length; sha256 = $hash }
            }
    )
    $lines = @($records | ForEach-Object { "$($_.path)|$($_.bytes)|$($_.sha256)" }) -join "`n"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($lines))).Replace("-", "")
    } finally {
        $sha.Dispose()
    }
    return [ordered]@{
        fileCount = $records.Count
        totalBytes = [int64](($records | ForEach-Object { [int64]$_['bytes'] } | Measure-Object -Sum).Sum)
        manifestSha256 = $digest
    }
}

function Get-NewScriptErrors {
    param([datetime]$Since)
    if (-not (Test-Path -LiteralPath $gameLogsRoot)) { return @() }
    return @(Get-ChildItem -LiteralPath $gameLogsRoot -Recurse -File -Filter "*ScriptError*.txt" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $Since -and $_.Length -gt 0 })
}

function Pack-OwnedMap {
    param([string]$Source, [string]$Destination)
    $packer = Join-Path $workspace "tools\mpq\scripts\pack_stormlib.py"
    if (-not (Test-Path -LiteralPath $packer -PathType Leaf)) {
        throw "Map packer not found: $packer"
    }
    $stormlib = Join-Path $workspace "artifacts\stormlib-v9.40\x64\StormLib.dll"
    if (-not (Test-Path -LiteralPath $stormlib -PathType Leaf)) {
        $stormlib = Join-Path $workspace "artifacts\stormlib-v9.40\Win32\StormLib.dll"
    }
    if (-not (Test-Path -LiteralPath $stormlib -PathType Leaf)) {
        throw "StormLib.dll not found under artifacts\stormlib-v9.40\"
    }
    $python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }
    & $python $packer $Source $Destination --stormlib $stormlib | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        throw "Map packing failed for $Source"
    }
    return [string](Resolve-Path -LiteralPath $Destination).Path
}

function Wait-ApiReady {
    param([int]$Port, [int]$TimeoutSeconds)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $task = $client.ConnectAsync("127.0.0.1", $Port)
            if ($task.Wait(1000) -and $client.Connected) { return $true }
        } catch {}
        finally { $client.Dispose() }
        if (-not (Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue)) { return $false }
    }
    return $false
}

function Send-FactionChat {
    param([string]$Chat)
    Add-Type -AssemblyName Microsoft.VisualBasic
    $process = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $process) { Write-Warning "SC2 process not found; faction chat was not sent: $Chat"; return $false }
    try { [Microsoft.VisualBasic.Interaction]::AppActivate($process.Id) | Out-Null } catch { Write-Warning "Could not focus SC2: $($_.Exception.Message)"; return $false }
    Start-Sleep -Milliseconds 500
    $shell = New-Object -ComObject WScript.Shell
    $shell.SendKeys("{ENTER}")
    Start-Sleep -Milliseconds 150
    $shell.SendKeys($Chat)
    Start-Sleep -Milliseconds 150
    $shell.SendKeys("{ENTER}")
    return $true
}

$sc2Root = Resolve-Sc2Root -Requested $Sc2Root
$switcher = Join-Path $sc2Root "Support64\SC2Switcher_x64.exe"
$mapStem = if ($MapName.EndsWith(".SC2Map", [StringComparison]::OrdinalIgnoreCase)) { $MapName } else { "$MapName.SC2Map" }
$mapSource = Join-Path $mapsRoot $mapStem
if (-not (Test-Path -LiteralPath $mapSource -PathType Container)) { throw "Owned map not found: $mapStem" }
$assetMirrorAvailable = Test-Path -LiteralPath $assetModsRoot -PathType Container
if (-not $assetMirrorAvailable) {
    throw "RO asset mirror not found: $assetModsRoot"
}
foreach ($mod in $requiredMods) {
    if (-not (Test-Path -LiteralPath (Join-Path $modRoot $mod) -PathType Container)) { throw "Owned Mod not found: $mod" }
}

$liveMods = Join-Path $sc2Root "Mods"
$liveMap = Join-Path $sc2Root ("Maps\RevolutionOverdrive\" + $mapStem)
$campaignsRoot = Join-Path $sc2Root "Campaigns"
$resolvedCampaignSourceRoot = ""
if ($CampaignSourceRoot) {
    if (-not (Test-Path -LiteralPath $CampaignSourceRoot -PathType Container)) {
        throw "Campaign source root directory not found: $CampaignSourceRoot"
    }
    $resolvedCampaignSourceRoot = (Resolve-Path -LiteralPath $CampaignSourceRoot).Path
} elseif ($VoidCampaignSource) {
    if (-not (Test-Path -LiteralPath $VoidCampaignSource -PathType Container)) {
        throw "Void Campaign source directory not found: $VoidCampaignSource"
    }
    $resolvedCampaignSourceRoot = Split-Path -Parent (Resolve-Path -LiteralPath $VoidCampaignSource).Path
}

$campaignDependencies = @()
foreach ($campaignName in @("Void.SC2Campaign", "Liberty.SC2Campaign", "Swarm.SC2Campaign")) {
    $target = Join-Path $campaignsRoot $campaignName
    $source = if ($campaignName -eq "Void.SC2Campaign" -and $VoidCampaignSource) {
        (Resolve-Path -LiteralPath $VoidCampaignSource).Path
    } elseif ($resolvedCampaignSourceRoot) {
        Join-Path $resolvedCampaignSourceRoot $campaignName
    } else {
        ""
    }
    $presentBefore = Test-Path -LiteralPath $target -PathType Container
    $campaign = [ordered]@{
        required = $true
        target = ("Campaigns/" + $campaignName)
        source = "installed"
        presentBefore = $presentBefore
        presentAfter = $false
    }
    $shouldReplace = ($ReplaceCampaignDependencies -or ($campaignName -eq "Void.SC2Campaign" -and $ReplaceVoidCampaign))
    if ((-not $presentBefore -or $shouldReplace) -and -not [string]::IsNullOrWhiteSpace($source)) {
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "Required campaign source directory not found: $source"
        }
        $campaign.source = "explicit-local-official-data-mirror"
        $campaign.sourceManifest = Get-DirectoryManifest -Source $source
        Copy-OwnedDirectory -Source $source -Destination $target
    }
    $presentAfter = Test-Path -LiteralPath $target -PathType Container
    $campaign['presentAfter'] = $presentAfter
    if (-not $presentAfter) {
        throw "Required $($campaign['target']) is absent. Pass -CampaignSourceRoot with the official campaign mirror."
    }
    $campaignDependencies += $campaign
}
$assetOverlays = @()
foreach ($mod in $requiredMods) {
    $ownedModSource = Join-Path $modRoot $mod
    $liveModDestination = Join-Path $liveMods $mod
    Copy-OwnedDirectory -Source $ownedModSource -Destination $liveModDestination
    $assetModSource = Join-Path $assetModsRoot $mod
    if (Test-Path -LiteralPath $assetModSource -PathType Container) {
        Copy-DirectoryOverlay -Source $assetModSource -Destination $liveModDestination
        $assetOverlays += [ordered]@{
            mod = $mod
            present = $true
            manifest = Get-DirectoryManifest -Source $assetModSource
        }
    } else {
        $assetOverlays += [ordered]@{
            mod = $mod
            present = $false
        }
    }
}
Copy-OwnedDirectory -Source $mapSource -Destination $liveMap

$startedAt = Get-Date
$evidence = [ordered]@{
    schemaVersion = 1
    classification = "static"
    package = "revolution-overdrive"
    map = $mapStem
    faction = $Faction
    factionChat = $factions[$Faction]
    sourceMap = "src/projects/revolution-overdrive-porting/packages/Maps/$mapStem"
    stagedMap = $liveMap
    stagedMods = $requiredMods
    assetMirror = "assets/src/projects/revolution-overdrive-porting/packages/Commander/Mods"
    assetOverlays = $assetOverlays
    campaignDependencies = $campaignDependencies
    voidCampaign = $campaignDependencies[0]
    noLaunch = [bool]$NoLaunch
    listenPort = $ListenPort
    startedAtUtc = $startedAt.ToUniversalTime().ToString("o")
}
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
if ($NoLaunch) {
    $evidence | Add-Member -NotePropertyName status -NotePropertyValue "staged"
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidenceRoot "last-run.json") -Encoding UTF8
    Write-Host "Revolution Overdrive staged: $mapStem / $Faction"
    Write-Host "Staged map: $liveMap"
    exit 0
}

New-Item -ItemType Directory -Force -Path $runtimeEvidenceRoot | Out-Null

$packedMapName = ([System.IO.Path]::GetFileNameWithoutExtension($mapStem) + ".stage07.packed.SC2Map")
$packedMap = Pack-OwnedMap -Source $liveMap -Destination (Join-Path $runtimeEvidenceRoot $packedMapName)
$evidence['packedMap'] = $packedMap

Get-Process -Name "SC2_x64", "SC2Switcher_x64" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$args = if ($ListenPort -gt 0) {
    @("-listen", "127.0.0.1", "-port", "$ListenPort", "-debug")
} else {
    @("-run", $packedMap)
}
Write-Host "Launching SC2 through SC2Switcher_x64.exe: $($args -join ' ')"
$process = Start-Process -FilePath $switcher -ArgumentList $args -WorkingDirectory $sc2Root -PassThru
$evidence.classification = "runtime"
$evidence.status = "launched"
$evidence.launcherPid = $process.Id
$evidence.ready = $false
$evidence.scriptErrors = @()
if ($ListenPort -gt 0) {
    $evidence.ready = Wait-ApiReady -Port $ListenPort -TimeoutSeconds $ReadyTimeoutSeconds
} else {
    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Get-ChildItem -LiteralPath $gameLogsRoot -Recurse -File -Filter "*Alert*.txt" -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $startedAt }) { $evidence.ready = $true; break }
        if (-not (Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Seconds 1
    }
}
$evidence.scriptErrors = @(Get-NewScriptErrors -Since $startedAt | ForEach-Object { $_.FullName })
$evidence.scriptErrorFree = ($evidence.scriptErrors.Count -eq 0)
if ($evidence.ready -and -not $NoCheats -and $ListenPort -le 0) {
    Start-Sleep -Seconds 2
    $evidence.factionChatSent = Send-FactionChat -Chat $factions[$Faction]
} else { $evidence.factionChatSent = $false }
$evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runtimeEvidenceRoot "launcher-runtime.json") -Encoding UTF8
if (-not $evidence.ready) { throw "SC2 did not produce a ready signal within $ReadyTimeoutSeconds seconds." }
if (-not $evidence.scriptErrorFree) { throw "New ScriptError detected: $($evidence.scriptErrors -join ', ')" }
Write-Host "Revolution Overdrive ready: $mapStem / $Faction"
