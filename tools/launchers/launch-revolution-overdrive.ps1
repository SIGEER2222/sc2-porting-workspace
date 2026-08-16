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
    [switch]$SecondaryClient,
    [string]$DataDirOverride = "",
    [switch]$NoCheats,
    [string]$VoidCampaignSource = "",
    [switch]$ReplaceVoidCampaign,
    [string]$CampaignSourceRoot = "",
    [switch]$ReplaceCampaignDependencies,
    [int]$ReadyTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
# 强制 PowerShell 输出编码为 UTF-8，确保 Python 端能正确解码中文消息
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

if ($SecondaryClient -and $ListenPort -le 0) {
    throw "-SecondaryClient requires -ListenPort <port>"
}
if ($DataDirOverride -and -not $SecondaryClient) {
    throw "-DataDirOverride is reserved for -SecondaryClient"
}

# 全局异常 trap：将未捕获的终止错误通过 Write-Host 写入 stdout
trap {
    $exc = $_
    $msg = if ($null -ne $exc.Exception) { $exc.Exception.Message } else { "$exc" }
    Write-Host ""
    Write-Host "================================[ LAUNCHER ERROR ]================================"
    Write-Host "[trap] 启动器执行失败: $msg"
    if ($null -ne $exc.InvocationInfo) {
        $info = $exc.InvocationInfo
        Write-Host "[trap] 位置: 行 $($info.ScriptLineNumber), 列 $($info.OffsetInLine)"
    }
    Write-Host "================================[ LAUNCHER ERROR ]================================"
    Write-Error "Launcher failed: $msg" -ErrorAction Continue
    exit 1
}
$workspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$packageRoot = Join-Path $workspace "src\projects\revolution-overdrive-porting\packages"
$modRoot = Join-Path $packageRoot "Commander\Mods"
$assetModsRoot = Join-Path $workspace "assets\src\projects\revolution-overdrive-porting\packages\Commander\Mods"
$mapsRoot = Join-Path $packageRoot "Maps"
$evidenceRoot = Join-Path $workspace "artifacts\projects\revolution-overdrive-porting\stage03-commander-package\launcher"
$gameLogsRoot = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "StarCraft II\GameLogs"
$runtimeEvidenceRoot = Join-Path $workspace "artifacts\projects\revolution-overdrive-porting\stage07-commander-closure"

$factions = @{
    # The shared RO library listens for the English preset name, while the
    # Iron faction mod listens for its native bootstrap command as well.
    Iron = @("Iron", "gangtiezhiyi")
    Madness = @("Madness")
    Pirate = @("Pirate")
    Coverts = @("Coverts")
    Umojan = @("Umojan")
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

function Resolve-MapCommanderAdapter {
    param(
        [string]$MapStem,
        [string]$Faction
    )
    $configPath = Join-Path $workspace "src\projects\revolution-overdrive-porting\vibe\map_commander_adapters.json"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "Revolution Overdrive map adapter config not found: $configPath"
    }
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $commanderId = "RevolutionOverdrive$Faction"
    foreach ($rule in @($config.map_commander_rules)) {
        if ($MapStem -match [string]$rule.map_pattern -and $commanderId -match [string]$rule.commander_pattern) {
            return [ordered]@{
                config = $configPath
                commander = $commanderId
                rule = $rule
            }
        }
    }
    return [ordered]@{
        config = $configPath
        commander = $commanderId
        rule = $null
    }
}

function Apply-MapCommanderAdapter {
    param(
        [string]$MapPath,
        [string]$MapStem,
        [string]$Faction
    )
    $resolved = Resolve-MapCommanderAdapter -MapStem $MapStem -Faction $Faction
    $rule = $resolved.rule
    $record = [ordered]@{
        schemaVersion = 1
        classification = "static"
        config = $resolved.config
        commander = $resolved.commander
        map = $MapStem
        status = "no_matching_rule"
        replacements = @()
        protectedPlayers = @()
    }
    if ($null -eq $rule) { return $record }
    if ($null -ne $rule.map_unit_policy.protectedPlayers) {
        $record.protectedPlayers = @($rule.map_unit_policy.protectedPlayers)
    }
    $record.ruleId = [string]$rule.id
    $scriptPath = Join-Path $MapPath "MapScript.galaxy"
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Map adapter target script not found: $scriptPath"
    }
    $script = [System.IO.File]::ReadAllText($scriptPath)
    $replacementRecords = @()
    $eventReplacementRecords = @()
    $declaredReplacements = if ($null -ne $rule.unit_replacements) { @($rule.unit_replacements) } else { @() }
    foreach ($replacement in $declaredReplacements) {
        $from = [string]$replacement.from
        $to = [string]$replacement.to
        $source = $replacement.source
        if ($from -ne "SCV" -or $to -ne "1gangtiegongchengche" -or $MapStem -ne "thanson01.SC2Map" -or $Faction -ne "Iron") {
            throw "Unsupported Revolution pilot replacement: $MapStem/$Faction $from -> $to"
        }
        $unitDataPath = Join-Path $modRoot "1钢铁之翼.SC2Mod\Base.SC2Data\GameData\UnitData.xml"
        $unitPattern = '<CUnit id="' + [regex]::Escape($to) + '">'
        if (-not (Select-String -LiteralPath $unitDataPath -Pattern $unitPattern -Quiet)) {
            throw "Adapter target catalog unit is absent from 1钢铁之翼.SC2Mod: $to"
        }
        $needle = 'libNtve_gf_UnitCreateFacingPoint(1, "SCV", 0, 1, PointFromId(1940147643), PointFromId(1940147643));'
        $replacementText = 'libNtve_gf_UnitCreateFacingPoint(1, "1gangtiegongchengche", 0, 1, PointFromId(1940147643), PointFromId(1940147643));'
        $matches = [regex]::Matches($script, [regex]::Escape($needle)).Count
        if ($matches -ne 1) {
            throw "Expected exactly one thanson01 P1 SCV opening, found $matches"
        }
        $script = $script.Replace($needle, $replacementText)
        $replacementRecords += [ordered]@{
            from = $from
            to = $to
            players = @($replacement.players)
            source = [ordered]@{ file = [string]$source.file; line = [int]$source.line }
            matchCount = $matches
            status = "applied_to_staged_map"
        }
    }
    $declaredEventReplacements = if ($null -ne $rule.event_unit_replacements) {
        @($rule.event_unit_replacements.PSObject.Properties)
    } else {
        @()
    }
    foreach ($eventReplacement in $declaredEventReplacements) {
        $from = [string]$eventReplacement.Name
        $to = [string]$eventReplacement.Value
        if ($from -ne "CommandCenter" -or $to -ne "1gangtieyaosai" -or $MapStem -ne "thanson01.SC2Map" -or $Faction -ne "Iron") {
            throw "Unsupported Revolution event replacement: $MapStem/$Faction $from -> $to"
        }
        $unitDataPath = Join-Path $modRoot "1钢铁之翼.SC2Mod\Base.SC2Data\GameData\UnitData.xml"
        $unitPattern = '<CUnit id="' + [regex]::Escape($to) + '">'
        if (-not (Select-String -LiteralPath $unitDataPath -Pattern $unitPattern -Quiet)) {
            throw "Adapter target catalog unit is absent from 1钢铁之翼.SC2Mod: $to"
        }
        $eventPatches = @(
            [ordered]@{
                needle = '            libNtve_gf_RescueUnit(autoEAEE2387_var, gv_p1_USER, true);'
                variable = 'autoEAEE2387_var'
                sourceLine = 1743
            },
            [ordered]@{
                needle = '            libNtve_gf_RescueUnit(auto80E05334_var, gv_p1_USER, true);'
                variable = 'auto80E05334_var'
                sourceLine = 1778
            }
        )
        foreach ($eventPatch in $eventPatches) {
            $needle = [string]$eventPatch.needle
            $matches = [regex]::Matches($script, [regex]::Escape($needle)).Count
            if ($matches -ne 1) {
                throw "Expected exactly one thanson01 CommandCenter rescue at line $($eventPatch.sourceLine), found $matches"
            }
            $replacementText = @(
                $needle
                ('        if ((UnitGetType(' + [string]$eventPatch.variable + ') == "CommandCenter")) {')
                ('            libNtve_gf_ReplaceUnit(' + [string]$eventPatch.variable + ', "' + $to + '", libNtve_ge_ReplaceUnitOptions_OldUnitsRelative);')
                "        }"
            ) -join [Environment]::NewLine
            $script = $script.Replace($needle, $replacementText)
            $eventReplacementRecords += [ordered]@{
                from = $from
                to = $to
                event = "rescue_after"
                source = [ordered]@{
                    file = "Maps/thanson01.SC2Map/MapScript.galaxy"
                    line = [int]$eventPatch.sourceLine
                }
                matchCount = $matches
                status = "applied_to_staged_map"
            }
        }
    }
    if ($replacementRecords.Count -gt 0 -or $eventReplacementRecords.Count -gt 0) {
        $encoding = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($scriptPath, $script, $encoding)
    }
    if ($MapStem -eq "thanson01.SC2Map" -and $Faction -eq "Iron") {
        $lineBreak = [Environment]::NewLine
        $steelHeader = 'include "Lib1A1D096B_h"' + $lineBreak
        if (-not $script.Contains($steelHeader.TrimEnd())) {
            $includeNeedle = 'include "LibWCMI"' + $lineBreak
            if (-not $script.Contains($includeNeedle)) {
                throw "Expected thanson01 include block was not found for runtime bootstrap"
            }
            $script = $script.Replace($includeNeedle, $includeNeedle + $steelHeader)
        }
        $bootstrapMarker = '//--------------------------------------------------------------------------------------------------' + $lineBreak + '// Trigger Initialization'
        $bootstrapCode = @'
// Runtime commander bootstrap injected by the map adapter.
// It runs inside the game VM; no chat command or UI keystroke is required.
trigger gv_ro_iron_runtime_bootstrap;
bool gv_ro_iron_runtime_bootstrap_busy;
bool gv_ro_iron_runtime_bootstrap_tech_applied;

void gf_ro_iron_runtime_replace_p1_unit (unit lp_unit) {
    string lv_type;
    if (lp_unit == null || UnitGetOwner(lp_unit) != 1) {
        return;
    }
    lv_type = UnitGetType(lp_unit);
    if (lv_type == "SCV") {
        libNtve_gf_ReplaceUnit(lp_unit, "1gangtiegongchengche", libNtve_ge_ReplaceUnitOptions_OldUnitsRelative);
    }
    else if (lv_type == "CommandCenter" || lv_type == "OrbitalCommand" || lv_type == "PlanetaryFortress") {
        libNtve_gf_ReplaceUnit(lp_unit, "1gangtieyaosai", libNtve_ge_ReplaceUnitOptions_OldUnitsRelative);
    }
}

void gf_ro_iron_runtime_scan_p1 () {
    unitgroup lv_units;
    int lv_index;
    unit lv_unit;
    lv_units = UnitGroup(null, 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_index = UnitGroupCount(lv_units, c_unitCountAll);
    for (;; lv_index -= 1) {
        lv_unit = UnitGroupUnitFromEnd(lv_units, lv_index);
        if (lv_unit == null) {
            break;
        }
        gf_ro_iron_runtime_replace_p1_unit(lv_unit);
    }
}

bool gt_ro_iron_runtime_bootstrap_Func (bool testConds, bool runActions) {
    if (!runActions || gv_ro_iron_runtime_bootstrap_busy) {
        return true;
    }
    gv_ro_iron_runtime_bootstrap_busy = true;
    if (!gv_ro_iron_runtime_bootstrap_tech_applied) {
        lib1A1D096B_gf_E4B8BAE78EA9E5AEB6E58D87E7BAA7E992A2E99381E4B98BE7BFBCE585A8E7A791E68A80(1);
        gv_ro_iron_runtime_bootstrap_tech_applied = true;
    }
    if (EventUnit() != null) {
        gf_ro_iron_runtime_replace_p1_unit(EventUnit());
    }
    gf_ro_iron_runtime_scan_p1();
    gv_ro_iron_runtime_bootstrap_busy = false;
    return true;
}

void gt_ro_iron_runtime_bootstrap_Init () {
    gv_ro_iron_runtime_bootstrap = TriggerCreate("gt_ro_iron_runtime_bootstrap_Func");
    TriggerAddEventUnitCreated(gv_ro_iron_runtime_bootstrap, null, null, null);
    TriggerAddEventUnitChangeOwner(gv_ro_iron_runtime_bootstrap, null);
    TriggerAddEventTimePeriodic(gv_ro_iron_runtime_bootstrap, 0.25, c_timeGame);
}

'@
        if ($script.Contains($bootstrapMarker)) {
            $script = $script.Replace($bootstrapMarker, $bootstrapCode + $bootstrapMarker)
        } else {
            throw "Expected thanson01 trigger initialization marker was not found for runtime bootstrap"
        }
        $initNeedle = '    gt_VictoryCleanup_Init();' + $lineBreak
        if ([regex]::Matches($script, [regex]::Escape($initNeedle)).Count -ne 1) {
            throw "Expected exactly one thanson01 trigger initialization tail"
        }
        $script = $script.Replace($initNeedle, $initNeedle + '    gt_ro_iron_runtime_bootstrap_Init();' + $lineBreak)
        $record.runtimeBootstrap = [ordered]@{
            mode = "runtime_galaxy_bootstrap"
            manualChatRequired = $false
            source = "launcher-injected MapScript.galaxy"
            events = @("UnitCreated", "UnitChangeOwner", "TimePeriodic")
            player = 1
            replacements = [ordered]@{
                SCV = "1gangtiegongchengche"
                CommandCenter = "1gangtieyaosai"
                OrbitalCommand = "1gangtieyaosai"
                PlanetaryFortress = "1gangtieyaosai"
            }
            techFunction = "lib1A1D096B_gf_E4B8BAE78EA9E5AEB6E58D87E7BAA7E992A2E99381E4B98BE7BFBCE585A8E7A791E68A80(1)"
        }
        $encoding = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($scriptPath, $script, $encoding)
    }
    $record.status = if ($replacementRecords.Count -gt 0 -or $eventReplacementRecords.Count -gt 0) { "applied" } else { "matched_rule_without_replacements" }
    $record.replacements = @($replacementRecords)
    $record.eventReplacements = @($eventReplacementRecords)
    $record.selectionMode = if ($null -ne $rule.selection.mode) { [string]$rule.selection.mode } else { "manual_chat" }
    $record.manualChatRequired = if ($null -ne $rule.selection.manualChatRequired) { [bool]$rule.selection.manualChatRequired } else { $true }
    $record.selectionCommands = if ($null -ne $rule.selection.commands) { @($rule.selection.commands) } else { @() }
    return $record
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

function Test-ApiPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return ($task.Wait(1000) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-ApiStable {
    param([int]$Port, [int]$Seconds)
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not (Test-ApiPort -Port $Port)) { return $false }
        if (-not (Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue)) { return $false }
        Start-Sleep -Seconds 1
    }
    return $true
}

function Get-ApiOwnerPid {
    param([int]$Port)
    $connection = @(Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($connection.Count -eq 0) { return 0 }
    return [int]$connection[0].OwningProcess
}

function Send-FactionChat {
    param([string[]]$Chats)
    Add-Type -AssemblyName Microsoft.VisualBasic
    $process = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $process) { Write-Warning "SC2 process not found; faction bootstrap was not sent: $($Chats -join ', ')"; return $false }
    try { [Microsoft.VisualBasic.Interaction]::AppActivate($process.Id) | Out-Null } catch { Write-Warning "Could not focus SC2: $($_.Exception.Message)"; return $false }
    Start-Sleep -Milliseconds 500
    $shell = New-Object -ComObject WScript.Shell
    foreach ($chat in @($Chats)) {
        $shell.SendKeys("{ENTER}")
        Start-Sleep -Milliseconds 150
        $shell.SendKeys([string]$chat)
        Start-Sleep -Milliseconds 150
        $shell.SendKeys("{ENTER}")
        Start-Sleep -Milliseconds 250
    }
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
$mapAdapter = Apply-MapCommanderAdapter -MapPath $liveMap -MapStem $mapStem -Faction $Faction

$startedAt = Get-Date
$evidence = [ordered]@{
    schemaVersion = 1
    classification = "static"
    package = "revolution-overdrive"
    map = $mapStem
    faction = $Faction
    factionChat = if ($mapAdapter.selectionMode -eq "runtime_galaxy_bootstrap") { @() } else { @($factions[$Faction]) }
    factionSelectionCommands = if ($mapAdapter.selectionMode -eq "runtime_galaxy_bootstrap") { @() } else { @($factions[$Faction]) }
    sourceMap = "src/projects/revolution-overdrive-porting/packages/Maps/$mapStem"
    stagedMap = $liveMap
    stagedMods = $requiredMods
    assetMirror = "assets/src/projects/revolution-overdrive-porting/packages/Commander/Mods"
    assetOverlays = $assetOverlays
    mapAdapter = $mapAdapter
    campaignDependencies = $campaignDependencies
    voidCampaign = $campaignDependencies[0]
    noLaunch = [bool]$NoLaunch
    secondaryClient = [bool]$SecondaryClient
    dataDirOverride = $DataDirOverride
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
$runtimeMapDirectory = Join-Path $sc2Root "Maps\RevolutionOverdrive"
$runtimePackedMap = Join-Path $runtimeMapDirectory $packedMapName
New-Item -ItemType Directory -Force -Path $runtimeMapDirectory | Out-Null
Copy-Item -LiteralPath $packedMap -Destination $runtimePackedMap -Force
$evidence['runtimeMap'] = "Maps\RevolutionOverdrive\$packedMapName"
$evidence['runtimeMapLocalPath'] = $runtimePackedMap

# Runtime-verification mode (API / -ListenPort set) must NEVER kill or assume ownership of an
# externally-owned SC2 instance. If SC2 is already running here, we cannot prove it is ours, so we
# fail-closed: record the external owner evidence and exit nonzero instead of disrupting the user's
# session. (Plan risk rule: 不终止或接管外部 owner；保持 blocked 并等待独立窗口.)
# Non-API play mode (default, -run packedMap) keeps the prior relaunch-kill behavior, because the
# user has explicitly asked to (re)launch the map and expects the previous instance to be replaced.
if ($ListenPort -gt 0 -and -not $SecondaryClient) {
    $existingSc2 = @(Get-Process -Name "SC2_x64", "SC2Switcher_x64" -ErrorAction SilentlyContinue)
    if ($existingSc2.Count -gt 0) {
        $ownerInfo = $existingSc2 | ForEach-Object {
            [ordered]@{ pid = $_.Id; name = $_.Name; startTimeUtc = $_.StartTime.ToUniversalTime().ToString("o") }
        }
        New-Item -ItemType Directory -Force -Path $runtimeEvidenceRoot | Out-Null
        $blockedEvidence = [ordered]@{
            schemaVersion  = 1
            classification = "blocked"
            package        = "revolution-overdrive"
            map            = $mapStem
            reason         = "external_sc2_owner_detected"
            detail         = "Refusing to kill an externally-owned SC2 instance before API-mode launch. Free the runtime slot (close the external owner) and re-run for an independent window."
            existingProcesses = $ownerInfo
            detectedAtUtc  = (Get-Date).ToUniversalTime().ToString("o")
        }
        $blockedEvidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runtimeEvidenceRoot "launcher-runtime-blocked.json") -Encoding UTF8
        $evidence['runtimeWrapper'] = $blockedEvidence
        throw ("External SC2 owner detected (pids: $($existingSc2.Id -join ',')) before API-mode launch; refusing to kill it. " +
               "Free the slot and re-run for an independent window.")
    }
}

if (-not $SecondaryClient) {
    Get-Process -Name "SC2_x64", "SC2Switcher_x64" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
$args = if ($ListenPort -gt 0) {
    @("-listen", "127.0.0.1", "-port", "$ListenPort", "-debug")
} else {
    @("-run", $packedMap)
}
if ($ListenPort -gt 0) {
    $runtimeTempDir = Join-Path $env:TEMP "sc2-ro-$PID-$ListenPort"
    New-Item -ItemType Directory -Force -Path $runtimeTempDir | Out-Null
    $sc2DataDir = if ($DataDirOverride) { (Resolve-Path -LiteralPath $DataDirOverride).Path } else { $sc2Root }
    $args += @("-dataDir", ('"' + $sc2DataDir + '"'), "-tempDir", $runtimeTempDir)
    if ($SecondaryClient) {
        # A primary player session may own the fullscreen D3D device. Keep the
        # explicit parallel runtime windowed so it can start without taking it.
        $args += @("-displayMode", "0", "-windowWidth", "800", "-windowHeight", "600")
    }
    $evidence.runtimeIsolation = [ordered]@{
        secondaryClient = [bool]$SecondaryClient
        dataDir = $sc2DataDir
        tempDir = $runtimeTempDir
    }
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
    # SC2Switcher returns before its SC2 child is visible. Give that child a
    # bounded startup window instead of treating the first empty process query
    # as a failed launch.
    $startupDeadline = [DateTime]::UtcNow.AddSeconds([Math]::Min(30, $ReadyTimeoutSeconds))
    $sc2Observed = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Get-ChildItem -LiteralPath $gameLogsRoot -Recurse -File -Filter "*Alert*.txt" -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $startedAt }) { $evidence.ready = $true; break }
        if (Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue) {
            $sc2Observed = $true
        } elseif ($sc2Observed -or [DateTime]::UtcNow -ge $startupDeadline) {
            break
        }
        Start-Sleep -Seconds 1
    }
}
$evidence.scriptErrors = @(Get-NewScriptErrors -Since $startedAt | ForEach-Object { $_.FullName })
$evidence.scriptErrorFree = ($evidence.scriptErrors.Count -eq 0)
$evidence.apiOwnerPid = if ($ListenPort -gt 0) { Get-ApiOwnerPid -Port $ListenPort } else { 0 }
if ($evidence.ready -and -not $NoCheats -and $ListenPort -le 0 -and $mapAdapter.selectionMode -ne "runtime_galaxy_bootstrap") {
    Start-Sleep -Seconds 2
    $evidence.factionChatSent = Send-FactionChat -Chats $factions[$Faction]
    $evidence.factionSelectionMode = "launcher_bootstrap"
    $evidence.manualFactionInputRequired = $false
} elseif ($mapAdapter.selectionMode -eq "runtime_galaxy_bootstrap") {
    $evidence.factionChatSent = $false
    $evidence.factionSelectionMode = "runtime_galaxy_bootstrap"
    $evidence.manualFactionInputRequired = $false
} else {
    $evidence.factionChatSent = $false
}
$evidence.apiStable = if ($ListenPort -gt 0 -and $evidence.ready) { Wait-ApiStable -Port $ListenPort -Seconds 4 } else { $true }
$evidence.ready = ($evidence.ready -and $evidence.apiStable)
$evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runtimeEvidenceRoot "launcher-runtime.json") -Encoding UTF8
if (-not $evidence.ready) { throw "SC2 did not produce a ready signal within $ReadyTimeoutSeconds seconds." }
if (-not $evidence.scriptErrorFree) { throw "New ScriptError detected: $($evidence.scriptErrors -join ', ')" }
Write-Host "Revolution Overdrive ready: $mapStem / $Faction"
