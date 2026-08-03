[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$MapName, [Parameter(Mandatory = $true)][string]$Commander, [switch]$DryRun, [switch]$NoLaunch, [int]$ListenPort = 0, [string]$LegacyRootOverride = "", [int]$Mode = 1, [int]$DifficultyBase = 0, [int]$DifficultyPlus = 0, [string]$Enemy = "", [string]$Mutators = "", [string]$ChaosMutators = "", [string]$VoicePack = "", [string]$ExtraMods = "", [switch]$SkipCountdown, [switch]$ApiMinimal, [switch]$DirectMapApi, [switch]$ShowSelectionUI, [switch]$EnableReborn, [string]$RebornCommander = "", [int]$RebornDifficulty = 5, [int]$RebornSpeed = 5, [switch]$PlayerMode, [switch]$DebugMode, [string]$Buffs = "", [string]$Masteries = "", [string]$BuffExtras = "", [switch]$EnableBuffPatch, [string]$MapCopySuffix = "", [switch]$KeepAlive, [string]$VibeKernelOverride = "", [switch]$SecondaryClient, [switch]$ReuseStagedMap, [string]$DataDirOverride = "")
# -MapCopySuffix: 可选的地图副本后缀，用于避免多会话同时操作同一 live 地图导致 DocumentInfo 冲突。
# 例如 -MapCopySuffix "reborn" 会使用 Maps\亡者之夜.SC2Map.reborn\ 作为 live 地图。
# 不指定时使用原始路径（向后兼容）。
$ErrorActionPreference = "Stop"
# 模式校验：PlayerMode 和 DebugMode 互斥；DebugMode 自动启用 ApiMinimal 并要求 ListenPort
if ($PlayerMode -and $DebugMode) { throw "-PlayerMode 和 -DebugMode 互斥，不能同时使用" }
if ($DebugMode) {
    if ($ListenPort -le 0) { throw "-DebugMode 必须配合 -ListenPort <port> 使用" }
    $ApiMinimal = $true
    Write-Host "DebugMode: 自动启用 ApiMinimal，SC2 窗口将最小化，launcher 退出时自动关闭 SC2"
}
if ($DirectMapApi) {
    if ($ListenPort -le 0) { throw "-DirectMapApi 必须配合 -ListenPort <port> 使用" }
    if ($DebugMode -or $ApiMinimal) { throw "-DirectMapApi cannot be combined with -DebugMode or -ApiMinimal" }
    if ($SecondaryClient) { throw "-DirectMapApi does not support -SecondaryClient" }
    Write-Host "DirectMapApi: direct map bootstrap plus SC2 API attach mode enabled"
}
if ($SecondaryClient) {
    if (-not $DebugMode -or $ListenPort -le 0) {
        throw "-SecondaryClient requires -DebugMode -ListenPort <port>"
    }
    Write-Host "SecondaryClient: explicit second SC2 participant client mode enabled"
}
if ($ReuseStagedMap) {
    if ([string]::IsNullOrWhiteSpace($MapCopySuffix)) {
        throw "-ReuseStagedMap requires -MapCopySuffix <existing-suffix>"
    }
    Write-Host "ReuseStagedMap: existing map copy will be read without restaging"
}
if ($DataDirOverride -ne "" -and -not $SecondaryClient) {
    throw "-DataDirOverride is reserved for -SecondaryClient"
}
$WorkspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Sc2WorkspaceRoot = Split-Path -Parent $WorkspaceRoot
if ($LegacyRootOverride) {
    $LegacyRoot = $LegacyRootOverride
} else {
    # CMRE 框架运行时已迁入 SC2VibeTools/cmre-runtime（原 合作指挥官-起义狂潮 仓库已归档）
    $LegacyRoot = Join-Path $Sc2WorkspaceRoot "cmre-runtime"
}
$AlengerPackagesRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\packages"
$Sc2Root = "E:\SC2\SC2new\StarCraft II"
$script:LauncherScriptsRoot = Join-Path $LegacyRoot "scripts\sc2-launcher"
. (Join-Path $script:LauncherScriptsRoot "common.ps1")
. (Join-Path $script:LauncherScriptsRoot "mod-sync.ps1")
. (Join-Path $script:LauncherScriptsRoot "map-sync.ps1")
. (Join-Path $script:LauncherScriptsRoot "document-dependencies.ps1")
. (Join-Path $script:LauncherScriptsRoot "test-lock.ps1")
. (Join-Path $LegacyRoot "scripts\commander-power-metadata.ps1")
. (Join-Path $LegacyRoot "scripts\sc2\campaignxcore-bank.ps1")
. (Join-Path $PSScriptRoot "lib\cmre-on-demand-overlay.ps1")
. (Join-Path $PSScriptRoot "lib\cmre-core-runtime-overlay.ps1")

$script:Sc2RuntimeMutexName = if ($SecondaryClient) {
    "Global\SC2VibeTools-SC2Runtime-Secondary-$ListenPort"
} else {
    "Global\SC2VibeTools-SC2Runtime"
}
$script:Sc2RuntimeLeasePath = Join-Path $WorkspaceRoot "artifacts\runtime\sc2-runtime-lease.json"

function Convert-TestCommanderToCommanderPowerKey {
    param([string]$Commander)
    return (Convert-CommanderPowerCommanderToBankKey -Commander $Commander -WorkspaceRoot $LegacyRoot)
}
$cmre = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "src\config\cmre-alenger-dependencies.json") -Raw | ConvertFrom-Json
$alenger = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "src\config\alenger-mods.json") -Raw | ConvertFrom-Json
# 加载地图需求声明（map-requirements.json）：地图声明硬性需求（PreventDefeat、起始单位），
# 由 launcher 读取并通知 mod adapter 中间层执行
$mapRequirements = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "src\config\map-requirements.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$mapRequirementKey = $MapName
if (-not ($mapRequirements.maps.PSObject.Properties.Name -contains $mapRequirementKey)) {
    $mapRequirementKey = '_default'
}
$mapRequirement = $mapRequirements.maps.$mapRequirementKey
$mapPreventDefeatPlayers = @()
$mapStartingUnitsPlayers = @()
if ($mapRequirement.preventDefeat.required) { $mapPreventDefeatPlayers = @($mapRequirement.preventDefeat.players) }
if ($mapRequirement.startingUnits.required) { $mapStartingUnitsPlayers = @($mapRequirement.startingUnits.players) }
Write-Host "Map requirements ($MapName): preventDefeat=$($mapRequirement.preventDefeat.required) players=$($mapPreventDefeatPlayers -join ','); startingUnits=$($mapRequirement.startingUnits.required) players=$($mapStartingUnitsPlayers -join ',')"
$isAlengerCommander = $false
# alengerId 始终是 alenger-mods.json 中 commanderToAlenger / commanderProfiles 的命名键
# （如 TalDarim、Empire）。WebUI 传入的 runtime_commander 形如 ProtossAlenger4，
# 需要通过 alengerIdToName 映射回命名键。
$alengerId = ''
$alengerNames = 'SteelWall|Behemoth|Empire|TalDarim|Abathur|Khalai|Zagara|Pirate|Amon|Community|Ranger|Purifier'
# -EnableReborn 模式下若指定了 -RebornCommander，强制走 Reborn 路径（else 分支），
# 避免 Alenger mod（如 ZagaraAlenger + ZagaraAlengerAdapter）与 Reborn mod 同时加载
# 导致 catalog/galaxy 冲突卡死（实测 Zagara 走 Alenger 路径会 600s 超时无 ScriptError）。
# 其他 Alenger commander（Abathur/Mengsk/Stukov 等）在 Reborn 模式下也应走 Reborn 路径，
# 保持与 Reborn mod 的兼容性。
if (-not ($EnableReborn -and $RebornCommander -ne "") -and $Commander -match "^(Terran|Zerg|Protoss)?($alengerNames)$") {
    $isAlengerCommander = $true
    $alengerId = $Matches[2]
    if ($alenger.commanderToAlenger.PSObject.Properties.Name -notcontains $alengerId) { throw "No on-demand package mapping for $Commander" }
} elseif ($Commander -match '^(Terran|Zerg|Protoss)?(Alenger\d+)$') {
    # WebUI / commander-power-metadata.json 使用 RaceAlengerN（如 ProtossAlenger4）作为 runtime_commander。
    # 通过 alengerIdToName 把 AlengerN 映射为命名键（如 Alenger4 → TalDarim）。
    $alengerNumberKey = $Matches[2]
    if ($alenger.PSObject.Properties.Name -notcontains 'alengerIdToName' -or
        $alenger.alengerIdToName.PSObject.Properties.Name -notcontains $alengerNumberKey) {
        throw "No alengerIdToName mapping for $Commander (key: $alengerNumberKey)"
    }
    $alengerId = $alenger.alengerIdToName.$alengerNumberKey
    $isAlengerCommander = $true
    Write-Host "Mapped $Commander -> $alengerId via alengerIdToName"
    if ($alenger.commanderToAlenger.PSObject.Properties.Name -notcontains $alengerId) { throw "No on-demand package mapping for $Commander (resolved: $alengerId)" }
} else {
    $validOfficial = @('Raynor','Nova','Swann','Mengsk','Tychus','Kerrigan','Abathur','Stukov','Zagara','Stetmann','Dehaka','Artanis','Vorazun','Karax','Alarak','Fenix','Zeratul','Talandar','Horner','MiraHan','Han','Horu')
    # Reborn 专属指挥官（不在原版 official 列表中），仅在 -EnableReborn 时接受
    $validReborn = @('Izsha','Karass','Naktul','Narud','Tosh','Urun','Warfield')
    if ($Commander -match '^(Terran|Zerg|Protoss)([A-Za-z]+)$') {
        $cmdrName = $Matches[2]
        if ($validOfficial -contains $cmdrName) {
            $alengerId = $cmdrName
        } elseif ($EnableReborn -and $validReborn -contains $cmdrName) {
            $alengerId = $cmdrName
            Write-Host "Reborn-specific commander accepted: $Commander"
        } else {
            throw "Commander must be a configured Alenger or official commander ID: $Commander"
        }
    } else {
        throw "Commander must be a valid runtime ID (Terran/Zerg/Protoss prefix or AlengerN): $Commander"
    }
}
# 读取指挥官 profile（如果存在）：用于参数化 adapter galaxy 文件、起始单位、vanilla 移除列表
$profile = $null
if ($alenger.PSObject.Properties.Name -contains 'commanderProfiles' -and
    $alenger.commanderProfiles.PSObject.Properties.Name -contains $alengerId) {
    $profile = $alenger.commanderProfiles.$alengerId
    Write-Host "Loaded commander profile for ${alengerId}: startingStructure=$($profile.startingStructure), startingWorker=$($profile.startingWorker)"
}
# 默认值仅用于启动 profile 的兼容字段。亡者之夜使用 CMRE 原生起始单位，
# 不允许通用层移除或重建地图起始建筑。
$adapterLibPrefix = 'A3ADAPTER'
$adapterFiles = @("LibA3ADAPTER_h.galaxy", "LibA3ADAPTER.galaxy", "LibA3ADAPTER_Catalog.galaxy")
$adapterModName = 'Alenger3Adapter'
$startingStructure = 'CommandCenter'
$startingWorker = 'SCV'
$workerCount = 5
$vanillaRemovals = @()
if ($profile) {
    # 注意：PowerShell if(@()) 返回 $false，所以空数组需要用 null 检查
    if ($null -ne $profile.adapterLibPrefix -and $profile.adapterLibPrefix -ne '') { $adapterLibPrefix = $profile.adapterLibPrefix }
    if ($null -ne $profile.adapterFiles) { $adapterFiles = @($profile.adapterFiles) }
    if ($null -ne $profile.adapterModName -and $profile.adapterModName -ne '') { $adapterModName = $profile.adapterModName }
    if ($null -ne $profile.startingStructure -and $profile.startingStructure -ne '') { $startingStructure = $profile.startingStructure }
    if ($null -ne $profile.startingWorker -and $profile.startingWorker -ne '') { $startingWorker = $profile.startingWorker }
    if ($null -ne $profile.workerCount) { $workerCount = [int]$profile.workerCount }
    if ($null -ne $profile.vanillaRemovals) { $vanillaRemovals = @($profile.vanillaRemovals) }
}
# 通用层：根据 $Commander 前缀（Zerg/Terran/Protoss）确定 race
# $commanderRace 始终赋值（无论 Alenger 还是 Reborn 模式），用于：
#   1. Reborn 模式下覆盖起始单位为原版单位 ID
#   2. galaxy 注入解锁逻辑时判断是否调用 UnlockAllZergUnits
# Alenger 自定义单位如 6fuhuachang 在 Reborn mod 中不存在，Reborn 模式必须用原版 ID
$commanderRace = ''
if ($Commander -match '^Zerg') {
    $commanderRace = 'Zerg'
} elseif ($Commander -match '^Terran') {
    $commanderRace = 'Terran'
} elseif ($Commander -match '^Protoss') {
    $commanderRace = 'Protoss'
}
if ($EnableReborn -and $RebornCommander -ne "") {
    if ($commanderRace -eq 'Zerg') {
        $startingStructure = 'Hatchery'
        $startingWorker = 'Drone'
    } elseif ($commanderRace -eq 'Terran') {
        $startingStructure = 'CommandCenter'
        $startingWorker = 'SCV'
    } elseif ($commanderRace -eq 'Protoss') {
        $startingStructure = 'Nexus'
        $startingWorker = 'Probe'
    }
    Write-Host "Reborn mode: startingStructure=$startingStructure, startingWorker=$startingWorker commanderRace=$commanderRace (race-based vanilla units)"
} elseif ($commanderRace) {
    Write-Host "Alenger mode with Reborn library: commanderRace=$commanderRace (for Zerg unit unlock injection)"
}
$mapSource = Join-Path $LegacyRoot "Maps\CMRE\$MapName"
if (-not (Test-Path -LiteralPath $mapSource)) { throw "CMRE map source not found: $mapSource" }
$commanderSelectionDisabled = $MapName -eq "亡者之夜.SC2Map"
if ($commanderSelectionDisabled -and $ShowSelectionUI) {
    throw "-ShowSelectionUI is disabled for ${MapName}: the map-owned startup code permanently bypasses commander selection"
}
if ($isAlengerCommander) {
    $selectedMods = @($alenger.commanderToAlenger.$alengerId)
} else {
    $selectedMods = @()
    $cmdrUnitsMod = Get-CommanderUnitsModName -Commander $Commander
    if ($cmdrUnitsMod) {
        # 只有当 mod 实际存在时才加入依赖列表。commander-units-mapping.json 列出了所有原版
        # 指挥官的预期 mod 名，但本地只解包了 Dehaka 和 Swann（其他指挥官的 unit 数据
        # 已经包含在 CoreRuntime 或 CMRE 核心 mod 中），所以这里跳过不存在的 mod 以避免
        # DocumentInfo 引用不存在的依赖导致 SC2 加载失败。
        $cmdrUnitsModPath = Join-Path $AlengerPackagesRoot "Mods\Commanders\$cmdrUnitsMod.SC2Mod"
        if (Test-Path -LiteralPath $cmdrUnitsModPath) {
            $selectedMods += $cmdrUnitsMod
            Write-Host "Official commander: adding CommanderUnits mod: $cmdrUnitsMod"
        } else {
            Write-Host "Official commander: CommanderUnits mod not found, skipping: $cmdrUnitsMod"
        }
    }
}
$dependencies = @($cmre.baseDependencyPaths) + @($cmre.commanderBaseDependencyPaths) + @($selectedMods | ForEach-Object { "file:Mods/Commanders/$_.SC2Mod" })
if ($ExtraMods -ne "") {
    $extraList = $ExtraMods.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
    $selectedSet = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($m in $selectedMods) { [void]$selectedSet.Add($m) }
    $dedupedExtra = @($extraList | Where-Object { -not $selectedSet.Contains($_) })
    if ($dedupedExtra.Count -lt $extraList.Count) {
        $skipped = @($extraList | Where-Object { $selectedSet.Contains($_) })
        Write-Host "Extra mods (skipped duplicates already in commander loadout): $($skipped -join ', ')"
    }
    foreach ($mod in $dedupedExtra) { $dependencies += "file:Mods/Commanders/$mod.SC2Mod" }
    if ($dedupedExtra.Count -gt 0) {
        Write-Host "Extra mods: $($dedupedExtra -join ', ')"
    }
} else {
    $dedupedExtra = @()
}
# -EnableReborn: 可选加载 reborn mod 包（5 个 mod + SwarmStory 战役依赖）。
# reborn mod 存放在 cmre-runtime/Mods/reborn/ 下，主 mod 的 DocumentInfo 已改写
# 子 mod 路径为 Mods/reborn/...，SwarmStory 战役包已部署到 SC2 安装目录 Campaigns/。
# -RebornCommander: 指定重生虫心指挥官名称（Abathur/Dehaka/Izsha/Karass/Kerrigan/Mengsk/
# Naktul/Narud/Raynor/Stukov/Tosh/Urun/Warfield/Zagara/Zeratul/Random），启用后会预写
# cryswarmcoop.SC2Bank 银行，让重生虫心 mod 自动选择指定指挥官并执行 SwarmSetup 流程。
if ($EnableReborn) {
    if ($cmre.PSObject.Properties.Name -notcontains 'optionalPackageModDependencyPaths') {
        throw "optionalPackageModDependencyPaths not declared in cmre-alenger-dependencies.json"
    }
    $dependencies += @($cmre.optionalPackageModDependencyPaths)
    Write-Host "Reborn mods enabled: adding $($cmre.optionalPackageModDependencyPaths.Count) optional dependencies"
    if ($RebornCommander -ne "") {
        Write-Host "Reborn commander preset: $RebornCommander (Difficulty=$RebornDifficulty, Speed=$RebornSpeed)"
    }
} elseif ($RebornCommander -ne "") {
    throw "-RebornCommander requires -EnableReborn to load reborn mod packages."
}
Write-Host "CMRE Alenger selection: $MapName x $Commander"
Write-Host "On-demand packages: $($selectedMods -join ', ')"
if ($DryRun) { $dependencies | ForEach-Object { Write-Host "  $_" }; exit 0 }

function Enable-CmreSavedProfileStartup {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath,
        [Parameter(Mandatory = $true)][string]$Commander,
        [switch]$SkipCountdown,
        [switch]$ApiMinimal,
        [switch]$SkipPause,
        [switch]$Headless,
        [switch]$KeepPlayer1Vanilla
    )
    Install-CmreSavedProfileStartupOverlay -MapPath $MapPath -Commander $Commander -SkipCountdown:$SkipCountdown -ApiMinimal:$ApiMinimal -SkipPause:$SkipPause -Headless:$Headless -KeepPlayer1Vanilla:$KeepPlayer1Vanilla
}
function Patch-RebornK5KerriganSpawn {
    <#
    .SYNOPSIS
      Patch Reborn mod 的 Lib48DF4533.galaxy，在 SwarmSetup 触发前为 coop_group 中
      每个玩家创建临时 K5Kerrigan 英雄单位。
    .DESCRIPTION
      Reborn 的 CommanderStart 期望玩家已有 K5Kerrigan 单位（来自战役），会将其
      替换为对应指挥官的特有单位（Abathur→HunterKiller, Raynor→WarPig x2, 等）。
      但 CMRE/Empire 体系不创建 K5Kerrigan，导致替换逻辑跳过，无 Reborn 单位出现。
      本函数在 SwarmSetup 触发点之前注入创建 K5Kerrigan 的 galaxy 代码。
    #>
    param([Parameter(Mandatory = $true)][string]$ModsRoot)

    $libPath = Join-Path $ModsRoot "reborn\crys_the_swarm_reborn.SC2Mod\Base.SC2Data\Lib48DF4533.galaxy"
    if (-not (Test-Path -LiteralPath $libPath)) {
        Write-Host "Patch-RebornK5KerriganSpawn: Reborn mod not found, skipping (EnableReborn=$EnableReborn)"
        return
    }

    # 读取字节并显式剥离可能的 UTF-8 BOM。早期版本的 patch 函数曾用 [System.Text.Encoding]::UTF8
    # 写入（带 BOM），导致 galaxy 编译器报 "触发器库无法初始化：lib48DF4533_InitLib (无法找到函数)"。
    # 现在改为字节级读写，确保任何情况下都不会写入 BOM。
    $bytes = [System.IO.File]::ReadAllBytes($libPath)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        Write-Host "Patch-RebornK5KerriganSpawn: stripping existing UTF-8 BOM (this was the root cause of lib48DF4533_InitLib compile failure)"
        $bytes = $bytes[3..($bytes.Length - 1)]
    }
    $content = [System.Text.Encoding]::UTF8.GetString($bytes)

    # 在 SwarmSetup_Func 中 CommanderStart 调用前注入 K5Kerrigan 创建代码。
    # 不在 Initialization_Func 中注入，因为那可能导致库编译顺序问题。
    $marker = '    TriggerExecute(lib48DF4533_gt_CommanderStart, false, false);'
    if (-not $content.Contains($marker)) {
        Write-Host "Patch-RebornK5KerriganSpawn: CommanderStart trigger marker not found, skipping"
        return
    }

    # 2026-07-29: 移除 K5Kerrigan 注入逻辑（用户要求"不需要 k5keerigen"）。
    # 只保留 BOM 剥离 + 清理旧注入（保证幂等，避免残留 K5Kerrigan 代码导致编译错误）。
    $oldPatchPattern = '(?ms)    // CMRE_PATCH_K5KERRIGAN_SPAWN[^\r\n]*\r?\n.*?libNtve_gf_CreateUnitsWithDefaultFacing\(1, "K5Kerrigan".*?\}\r?\n'
    $strippedCount = ([regex]::Matches($content, $oldPatchPattern)).Count
    if ($strippedCount -gt 0) {
        $content = [regex]::Replace($content, $oldPatchPattern, '')
        Write-Host "Patch-RebornK5KerriganSpawn: stripped $strippedCount old K5Kerrigan patch block(s) (disabled by user request)"
    } else {
        Write-Host "Patch-RebornK5KerriganSpawn: no old K5Kerrigan patch found, BOM stripped only (injection disabled)"
    }

    # 写回时显式用 BOM-less UTF8 编码转换为字节，再用 WriteAllBytes 写入（绕过 WriteAllText
    # 在某些 PowerShell 版本中可能默认带 BOM 的行为）。
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $outBytes = $utf8NoBom.GetBytes($content)
    [System.IO.File]::WriteAllBytes($libPath, $outBytes)
}

function Patch-RebornBankAuthorization {
    <#
    .SYNOPSIS
      将 cryswarmcoop 银行加入地图的 BankList.xml，让 Reborn galaxy 代码能通过
      BankLoad("cryswarmcoop", player) 读取预写的指挥官选择。
    .DESCRIPTION
      SC2 的 BankLoad 要求地图在 BankList.xml 中显式声明授权的银行名和玩家号。
      CMRE 地图原本只授权 COCampaign/CMCoopLaunchProfile/CMCoopGameHistory/NeuroIntegration，
      不包含 cryswarmcoop。Reborn 的 CommanderStart_Func 调用 BankLoad("cryswarmcoop", p)
      时返回 null，导致 BankValueGetAsString 读取 Commander 值为空字符串，
      所有指挥官分支（Abathur/Kerrigan/Zagara 等）都不匹配，K5Kerrigan 替换被跳过。
      本函数在地图 BankList.xml 中追加 cryswarmcoop 的 Player=1 和 Player=2 授权。
    #>
    param([Parameter(Mandatory = $true)][string]$MapPath)

    $bankListPath = Join-Path $MapPath "BankList.xml"
    if (-not (Test-Path -LiteralPath $bankListPath)) {
        Write-Host "Patch-RebornBankAuthorization: BankList.xml not found at $bankListPath, skipping"
        return
    }

    # 字节级读取并剥离可能的 BOM
    $bytes = [System.IO.File]::ReadAllBytes($bankListPath)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $bytes = $bytes[3..($bytes.Length - 1)]
    }
    $content = [System.Text.Encoding]::UTF8.GetString($bytes)

    # 幂等检查：已包含 cryswarmcoop 则跳过 cryswarmcoop 注入（但仍可能需要注入 CMRERebornDebug）
    $needCryswarmcoop = -not $content.Contains('Name="cryswarmcoop"')
    $needDebugBank = -not $content.Contains('Name="CMRERebornDebug"')

    if (-not $needCryswarmcoop -and -not $needDebugBank) {
        Write-Host "Patch-RebornBankAuthorization: cryswarmcoop + CMRERebornDebug already authorized, skipping"
        return
    }

    # 在 </BankList> 前追加授权
    # Reborn galaxy 代码中 coop_group 包含 Player 1（始终）和 Player 14（当 PlayerType(14)==c_playerTypeUser）
    # 同时也授权 Player 2 以兼容 CMRE 的 player slot 配置
    $insertion = ''
    if ($needCryswarmcoop) {
        $insertion += '  <Bank Name="cryswarmcoop" Player="1" />' + "`r`n" +
                      '  <Bank Name="cryswarmcoop" Player="2" />' + "`r`n" +
                      '  <Bank Name="cryswarmcoop" Player="14" />' + "`r`n"
    }
    if ($needDebugBank) {
        # CMRERebornDebug: 调试银行，用于在 galaxy 代码中写入运行时证据（K5Kerrigan 创建计数等）
        $insertion += '  <Bank Name="CMRERebornDebug" Player="1" />' + "`r`n" +
                      '  <Bank Name="CMRERebornDebug" Player="2" />' + "`r`n" +
                      '  <Bank Name="CMRERebornDebug" Player="14" />' + "`r`n"
    }
    $closingTag = '</BankList>'
    if (-not $content.Contains($closingTag)) {
        Write-Host "Patch-RebornBankAuthorization: </BankList> closing tag not found, skipping"
        return
    }
    $content = $content.Replace($closingTag, $insertion + $closingTag)

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $outBytes = $utf8NoBom.GetBytes($content)
    [System.IO.File]::WriteAllBytes($bankListPath, $outBytes)
    $added = @()
    if ($needCryswarmcoop) { $added += 'cryswarmcoop' }
    if ($needDebugBank) { $added += 'CMRERebornDebug' }
    Write-Host "Patch-RebornBankAuthorization: added $($added -join ', ') to BankList.xml"

    # Pre-create empty CMRERebornDebug bank files so BankLoad succeeds on first run.
    # SC2's BankLoad returns null if the bank file doesn't exist on disk, even when authorized in BankList.xml.
    $banksRoot = Join-Path $env:USERPROFILE "Documents\StarCraft II\Banks"
    $debugBankXml = '<?xml version="1.0" encoding="utf-8"?>' + "`r`n" + '<Bank version="1">' + "`r`n" + '</Bank>'
    $debugBankBytes = $utf8NoBom.GetBytes($debugBankXml)
    foreach ($p in @('', '1', '14')) {
        $dir = Join-Path $banksRoot $p
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
        $bankFile = Join-Path $dir 'CMRERebornDebug.SC2Bank'
        if (-not (Test-Path -LiteralPath $bankFile)) {
            [System.IO.File]::WriteAllBytes($bankFile, $debugBankBytes)
            Write-Host "Patch-RebornBankAuthorization: pre-created empty CMRERebornDebug.SC2Bank at $bankFile"
        }
    }
}

function Patch-RebornLibraryInit {
    <#
    .SYNOPSIS
      将 Reborn galaxy 库及其依赖复制到地图目录，并在 MapScript.galaxy 中注入
      include 与 InitLib 调用，让 Reborn 的 Lib48DF4533 库在地图加载时被初始化。
    .DESCRIPTION
      根本原因：MapScript.galaxy 的 InitLibs() 没有调用 lib48DF4533_InitLib()，
      所以 Reborn 整个 galaxy 库（含 CommanderStart/SwarmSetup/16 个指挥官子触发器）
      从未执行，K5Kerrigan 创建和单位替换都不生效。

      Lib48DF4533.galaxy include 了：
        - TriggerLibs/NativeLib      (core.sc2mod, 已自动加载)
        - TriggerLibs/LibertyLib     (liberty.sc2mod, 已自动加载)
        - TriggerLibs/SwarmCampaignLib (SwarmStory.SC2Campaign, 需复制)
        - Lib281DEC45                (swarmstoryutil.sc2mod, 需复制)
        - Lib114935F5                (sibirens_sundries_swarm_reborn.SC2Mod, 已通过 DocumentInfo 依赖加载)
        - Lib48DF4533_h              (自身头文件)

      SwarmCampaignLib.galaxy 又 include 了：
        - TriggerLibs/SwarmLib       (swarm.sc2mod, 已自动加载)
        - TriggerLibs/SwarmCampaignLib_h

      所以需要复制的文件：
        地图 Base.SC2Data/ 目录:
          - Lib48DF4533.galaxy, Lib48DF4533_h.galaxy  (来自 reborn mod)
          - Lib281DEC45.galaxy, Lib281DEC45_h.galaxy  (来自 swarmstoryutil.sc2mod)
        地图 Base.SC2Data/TriggerLibs/ 目录:
          - SwarmCampaignLib.galaxy, SwarmCampaignLib_h.galaxy  (来自 SwarmStory.SC2Campaign)

      然后在 MapScript.galaxy 中注入：
        include "Lib48DF4533"        (在 include 块中)
        lib48DF4533_InitLib();       (在 InitLibs() 末尾)
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Sc2Root,
        [Parameter(Mandatory = $true)][string]$MapPath
    )

    $baseData = Join-Path $MapPath "Base.SC2Data"
    if (-not (Test-Path -LiteralPath $baseData)) { throw "Map Base.SC2Data not found: $baseData" }

    # === 1. 复制 Lib48DF4533 + Lib281DEC45 到地图 Base.SC2Data 根目录 ===
    $rebornModLib = Join-Path $Sc2Root "Mods\reborn\crys_the_swarm_reborn.SC2Mod\Base.SC2Data"
    $swarmStoryUtilLib = Join-Path $Sc2Root "Campaigns\swarmstoryutil.sc2mod\base.sc2data"
    $filesToRoot = @(
        @{ Src = Join-Path $rebornModLib "Lib48DF4533.galaxy";     Dst = "Lib48DF4533.galaxy" },
        @{ Src = Join-Path $rebornModLib "Lib48DF4533_h.galaxy";   Dst = "Lib48DF4533_h.galaxy" },
        @{ Src = Join-Path $swarmStoryUtilLib "Lib281DEC45.galaxy";   Dst = "Lib281DEC45.galaxy" },
        @{ Src = Join-Path $swarmStoryUtilLib "Lib281DEC45_h.galaxy"; Dst = "Lib281DEC45_h.galaxy" }
    )
    foreach ($f in $filesToRoot) {
        if (-not (Test-Path -LiteralPath $f.Src)) { throw "Patch-RebornLibraryInit: source not found: $($f.Src)" }
        [System.IO.File]::Copy($f.Src, (Join-Path $baseData $f.Dst), $true)
    }
    Write-Host "Patch-RebornLibraryInit: copied $($filesToRoot.Count) lib files to Base.SC2Data"

    # === 2. 复制 SwarmCampaignLib 到地图 Base.SC2Data/TriggerLibs/ ===
    $triggerLibsDir = Join-Path $baseData "TriggerLibs"
    [System.IO.Directory]::CreateDirectory($triggerLibsDir) | Out-Null
    $swarmStoryLib = Join-Path $Sc2Root "Campaigns\SwarmStory.SC2Campaign\base.sc2data\TriggerLibs"
    $filesToTriggerLibs = @(
        @{ Src = Join-Path $swarmStoryLib "SwarmCampaignLib.galaxy";   Dst = "SwarmCampaignLib.galaxy" },
        @{ Src = Join-Path $swarmStoryLib "SwarmCampaignLib_h.galaxy"; Dst = "SwarmCampaignLib_h.galaxy" }
    )
    foreach ($f in $filesToTriggerLibs) {
        if (-not (Test-Path -LiteralPath $f.Src)) { throw "Patch-RebornLibraryInit: source not found: $($f.Src)" }
        [System.IO.File]::Copy($f.Src, (Join-Path $triggerLibsDir $f.Dst), $true)
    }
    Write-Host "Patch-RebornLibraryInit: copied $($filesToTriggerLibs.Count) lib files to Base.SC2Data/TriggerLibs"

    # === 3. 重新应用 K5Kerrigan spawn patch（因为刚复制的 Lib48DF4533.galaxy 是未 patch 的原始版本）===
    # 注意：Patch-RebornK5KerriganSpawn 修改的是 mod 源文件（Mods/reborn/.../Lib48DF4533.galaxy），
    # 但我们刚把原始文件复制到了地图目录。所以需要在地图副本上重新应用 K5Kerrigan spawn patch。
    $libPath = Join-Path $baseData "Lib48DF4533.galaxy"
    $bytes = [System.IO.File]::ReadAllBytes($libPath)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $bytes = $bytes[3..($bytes.Length - 1)]
    }
    $content = [System.Text.Encoding]::UTF8.GetString($bytes)

    # === 注入 include "LibMapModBridge_h" 和 "LibRebornAdapter_h" 到 Lib48DF4533.galaxy ===
    # 原因：lib48DF4533_InitLib() 中注入了对 libMapModBridge_InitLib() 和
    # libRebornAdapter_gf_InitializeBeforeSwarmSetup() 的调用，必须在 Lib48DF4533.galaxy
    # 中 include 这些头文件才能编译通过。
    if (-not ($content -match '(?m)^include "LibMapModBridge_h"')) {
        # 找到现有的 include "Lib48DF4533_h" 行，在其后插入
        if ($content -match '(?m)^include "Lib48DF4533_h"') {
            $replacementInclude = '$1' + "`r`n" + 'include "LibMapModBridge_h"' + "`r`n" + 'include "LibRebornAdapter_h"'
            $content = $content -replace '(?m)^(include "Lib48DF4533_h")', $replacementInclude
        } else {
            # fallback：在文件开头插入
            $content = 'include "LibMapModBridge_h"' + "`r`n" + 'include "LibRebornAdapter_h"' + "`r`n" + $content
        }
        Write-Host "Patch-RebornLibraryInit: injected include ""LibMapModBridge_h"" + ""LibRebornAdapter_h"" into Lib48DF4533.galaxy"
    }

    $marker = '    TriggerExecute(lib48DF4533_gt_CommanderStart, false, false);'
    if (-not $content.Contains($marker)) {
        throw "Patch-RebornLibraryInit: CommanderStart trigger marker not found in map copy of Lib48DF4533.galaxy"
    }

    # Strip any existing CMRE_PATCH_K5KERRIGAN_SPAWN block (V1 or any version) to ensure idempotent re-patch.
    # The regex matches the patch marker comment block plus the K5Kerrigan creation lines, preserving the
    # original TriggerExecute marker line so we can re-inject cleanly.
    $oldPatchPattern = '(?ms)    // CMRE_PATCH_K5KERRIGAN_SPAWN[^\r\n]*\r?\n.*?libNtve_gf_CreateUnitsWithDefaultFacing\(1, "K5Kerrigan".*?\}\r?\n'
    $strippedCount = ([regex]::Matches($content, $oldPatchPattern)).Count
    if ($strippedCount -gt 0) {
        $content = [regex]::Replace($content, $oldPatchPattern, '')
        Write-Host "Patch-RebornLibraryInit: stripped $strippedCount old K5Kerrigan patch block(s) before re-applying"
    }

    # 2026-07-29: 移除 K5Kerrigan 注入（用户要求"不需要 k5keerigen"）。
    # 保留 CommanderStart marker 行不注入任何 K5Kerrigan 创建代码。
    # CommanderStart 仍会执行，但找不到 K5Kerrigan 会跳过替换逻辑。
    Write-Host "Patch-RebornLibraryInit: K5Kerrigan injection skipped (disabled by user request)"

    # === 3b. 在 lib48DF4533_InitLib() 末尾注入 SwarmSetup 直接触发 ===
    # 根因：lib48DF4533_gt_Initialization_Func 中有两处 Wait(1.0, c_timeGame)（行 4620/4684），
    # 若游戏处于 pause 状态（CMRE 框架 GameSetMissionTimePaused(true)），Wait 永不返回，
    # 导致 Initialization_Func 永远执行不到 TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false)。
    # 结果：K5Kerrigan spawn + CommanderStart 替换逻辑（Abathur→HunterKiller 等）从未执行。
    # 修复：在 lib48DF4533_InitLib() 末尾（lib48DF4533_InitTriggers() 之后）直接异步触发 SwarmSetup。
    # 此时 SwarmSetup trigger 已通过 InitTriggers() 创建，TriggerExecute 不会阻塞 InitLib。
    # 幂等性：SwarmSetup_Func 末尾有 TriggerEnable(TriggerGetCurrent(), false)，重复触发会被跳过。
    $initLibMarker = '    lib48DF4533_InitTriggers();'
    $initLibMarkerCount = ([regex]::Matches($content, [regex]::Escape($initLibMarker))).Count
    if ($initLibMarkerCount -eq 0) {
        throw "Patch-RebornLibraryInit: lib48DF4533_InitTriggers() marker not found in Lib48DF4533.galaxy"
    }
    # 检查是否已注入黑屏修复（幂等）—— 旧版注入只有 SwarmSetup 触发，没有黑屏修复，
    # 必须用 black_screen_fix 标记做幂等检查，并在重新注入前移除旧块。
    $initLibInjectMarker = '// CMRE_PATCH_SWARMSETUP_DIRECT_TRIGGER'
    $blackScreenFixMarker = '// CMRE_PATCH_BLACK_SCREEN_FIX'
    $rebornAdapterMarker = '// CMRE_PATCH_REBORN_ADAPTER'
    if (-not $content.Contains($rebornAdapterMarker)) {
        # 移除旧版注入块（从 CMRE_PATCH_SWARMSETUP_DIRECT_TRIGGER 到 gt_DisableArmySelectPoll_Init();）
        # 保证重新注入最新代码（含 Reborn adapter 调用）
        $oldPatchPattern = '(?m)^    // CMRE_PATCH_SWARMSETUP_DIRECT_TRIGGER[\s\S]*?    gt_DisableArmySelectPoll_Init\(\);\r?\n'
        $content = [regex]::Replace($content, $oldPatchPattern, '')
        # 根据地图需求声明计算参数
        $ensureP1PreventDefeat = ($mapPreventDefeatPlayers -contains 1).ToString().ToLower()
        $ensureP2PreventDefeat = ($mapPreventDefeatPlayers -contains 2).ToString().ToLower()
        $createP1StartingUnits = ($mapStartingUnitsPlayers -contains 1).ToString().ToLower()
        $createP2StartingUnits = ($mapStartingUnitsPlayers -contains 2).ToString().ToLower()
        $initLibInjectBlock = @"
    $initLibInjectMarker
    // 直接异步触发 SwarmSetup，绕过 Initialization_Func 中的 Wait 卡死问题。
    // SwarmSetup 会执行 CommanderStart（指挥官单位替换）+ UnitUnlocks。
    // 2026-07-29: 移除 K5Kerrigan 创建（用户要求"不需要 k5keerigen"）。
    BankLoad("CMRERebornDebug", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "initlib_patch_ran", 1);
    BankSave(BankLastCreated());
    // === 修复黑屏（2026-07-28 真因定位）：CMRE 框架的 CC_DevStartupBegin 在
    //   SkipCountdown 模式下调用 GameSetMissionTimePaused(true) + ShowHideWorldCover(true)
    //   进入黑屏+暂停状态，但 CC_DevStartupFinish 通过 commander selection 关闭事件触发，
    //   SkipCountdown 模式下 commander selection 未启动（line 4823-4824 直接 return），
    //   DevStartupFinish 永远不会被调用，导致黑屏 + SwarmSetup 内部 Wait(c_timeGame) 永不返回。
    //   这里在 SwarmSetup 触发之前手动恢复：解除暂停 + 显示世界，让 SwarmSetup 内部的
    //   Wait(c_timeGame) 能正常返回，玩家也能看到游戏画面。
    // CMRE_PATCH_BLACK_SCREEN_FIX
    GameSetMissionTimePaused(false);
    AITimePause(false);
    UnitPauseAll(false);
    libCOOC_gf_ShowHideWorldCover(false, 0.0, 1);
    if ((PlayerType(14) == c_playerTypeUser)) {
        libCOOC_gf_ShowHideWorldCover(false, 0.0, 14);
    }
    libNtve_gf_HideGameUI(true, PlayerGroupAll()); // true=显示UI（HideGameUI 函数名反直觉：lp_showHide=true 显示, false 隐藏）
    BankLoad("CMRERebornDebug", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "black_screen_fix_ran", 1);
    BankSave(BankLastCreated());
    // === 调用 Reborn mod adapter 中间层（在 SwarmSetup 之前）===
    // 参数来自 map-requirements.json（地图声明需求）+ commander profile（mod 个性化）
    // adapter 内部调用通用 LibMapModBridge API 完成基地创建和 PreventDefeat 保障
    // CMRE_PATCH_REBORN_ADAPTER
    libMapModBridge_InitLib();
    libRebornAdapter_gf_InitializeBeforeSwarmSetup(
        "$startingStructure", "$startingWorker", $workerCount,
        $ensureP1PreventDefeat, $ensureP2PreventDefeat,
        $createP1StartingUnits, $createP2StartingUnits);
    TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false);
    // === 解锁所有 Zerg 单位（仅 Zerg 指挥官）===
    // CMRE_PATCH_ZERG_UNIT_UNLOCK
    // 原因：UnitUnlocks_Func 依赖 libSwaC_gf_CurrentMap()=='ZXXx' 或 BankKeyExists('Maps','XXX')，
    // 在 CMRE 合作地图上这些条件都不满足，导致除 Zergling/SpineCrawler/SporeCrawler 外
    // 的所有单位/建筑都被 TechTreeUnitAllow(false) 禁用，Larva 也丢失 morph 能力。
    // 修复：SwarmSetup 触发后强制调用 TechTreeUnitAllow(true) 解锁所有 Zerg 单位/建筑。
    // 注意：必须在 SwarmSetup 之后调用，否则 UnitUnlocks_Func 中的 false 会覆盖此处的 true。
    if ("$commanderRace" == "Zerg") {
        libRebornAdapter_gf_UnlockAllZergUnits(1);
        libRebornAdapter_gf_UnlockAllZergUnits(2);
    }
    // === 公共层：注册 DisableArmySelect 定时补加触发器 ===
    // 在 InitLib 末尾注册（而非 SwarmSetup_Func），因为 Galaxy 不支持函数向前引用，
    // gt_DisableArmySelectPoll_Init 定义在文件末尾，只有 InitLib（也在文件末尾）才能引用到。
    gt_DisableArmySelectPoll_Init();
"@

        # === 3c. 在 SwarmSetup_Func 末尾（return true 之前）注入深度调试代码 ===
        # 根因：InitLib 中 Wait 会阻塞库初始化，导致进程退出前深度调试代码未执行。
        # 改在 SwarmSetup_Func 末尾注入，SwarmSetup 执行完所有逻辑后立即写入调试银行。
        # SwarmSetup_Func 中有 Wait(1.0, c_timeGame) 调用，但在 InitLib 中直接
        # TriggerExecute(SwarmSetup) 时游戏尚未暂停，Wait 能正常返回。
        $swarmSetupEndMarker = '    TriggerExecute(lib48DF4533_gt_AllySettings, true, false);
    return true;'
        if (-not $content.Contains($swarmSetupEndMarker)) {
            throw "Patch-RebornLibraryInit: SwarmSetup_Func end marker not found"
        }
        $deepDebugBlock = @"
    // CMRE_PATCH_SWARMSETUP_DEEP_DEBUG
    // SwarmSetup 执行完所有逻辑后：
    // 1. 基地+工蜂创建已移至通用层 gt_CommanderStartingUnits_Func（Map Init + 5s Wait）
    // 2. 验证 HunterKiller 的 5 个 Abathur 特有技能（UnitAbilityExists）
    // 3. 写入深度调试银行作为运行时信源
    // 基地替换由通用层统一处理（各 mod 通过 commander profile 个性化），不再在此处创建
    // === 公共层：给所有单位动态添加移除部队选择技能（抽离自眼虫）===
    // DisableArmySelect 的注册调用不在此处，而在 lib48DF4533_InitLib() 末尾，
    // 因为 Galaxy 不支持函数向前引用（gt_DisableArmySelectPoll_Init 定义在文件末尾）。
    // === 黑屏修复已在 lib48DF4533_InitLib() 末尾完成（SwarmSetup 触发之前）：
    //   解除 GameSetMissionTimePaused + ShowHideWorldCover(false)，确保 SwarmSetup
    //   内部的 Wait(c_timeGame) 能正常返回。这里不再重复修复，直接写入调试银行。
    BankLoad("CMRERebornDebug", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "deep_debug_ran", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "abathur_upgrade_count", TechTreeUpgradeCount(1, "Abathur", c_techCountCompleteOnly));
    BankValueSetFromInt(BankLastCreated(), "debug", "k5kerrigan_p1_after_swarmsetup", UnitGroupCount(UnitGroup("K5Kerrigan", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    // 通用替换单位检测：覆盖所有 15 个 Reborn 指挥官的 K5Kerrigan 替换目标
    // 信源：Lib48DF4533.galaxy CommanderStart_Func line 5016-5178
    // 每个指挥官对应一种或多种替换单位，运行时只会有其中之一（或 Kerrigan 不替换）
    BankValueSetFromInt(BankLastCreated(), "debug", "warpig_p1_count", UnitGroupCount(UnitGroup("WarPig", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_p1_count", UnitGroupCount(UnitGroup("HunterKiller", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "hydraliskimpaler_p1_count", UnitGroupCount(UnitGroup("HydraliskImpaler", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    // 14 个未测指挥官的替换单位检测（2026-07-27 批量验证）
    BankValueSetFromInt(BankLastCreated(), "debug", "primalhydralisk2_p1_count", UnitGroupCount(UnitGroup("PrimalHydralisk2", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "primaligniter_p1_count", UnitGroupCount(UnitGroup("PrimalIgniter", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "siqueen_p1_count", UnitGroupCount(UnitGroup("SIQueen", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "higharchontemplar_p1_count", UnitGroupCount(UnitGroup("HighArchonTemplar", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "queen_p1_count", UnitGroupCount(UnitGroup("Queen", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "revenantgun_p1_count", UnitGroupCount(UnitGroup("RevenantGun", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "infestedmarine_p1_count", UnitGroupCount(UnitGroup("InfestedMarine", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "witch_p1_count", UnitGroupCount(UnitGroup("Witch", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "huntress_p1_count", UnitGroupCount(UnitGroup("Huntress", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "grizzly_p1_count", UnitGroupCount(UnitGroup("Grizzly", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "mengskmarauder_p1_count", UnitGroupCount(UnitGroup("MengskMarauder", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "infestedabomination_p1_count", UnitGroupCount(UnitGroup("InfestedAbomination", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "stalkershakuras_p1_count", UnitGroupCount(UnitGroup("StalkerShakuras", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "zerg_p1_total_units", UnitGroupCount(UnitGroup(null, 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0), c_unitCountAlive));
    // 虫族建筑验证
    BankValueSetFromInt(BankLastCreated(), "debug", "hatchery_p1_count", UnitGroupCount(UnitGroup("Hatchery", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "spawningpool_p1_count", UnitGroupCount(UnitGroup("SpawningPool", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "roachwarren_p1_count", UnitGroupCount(UnitGroup("RoachWarren", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "hydraliskden_p1_count", UnitGroupCount(UnitGroup("HydraliskDen", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankValueSetFromInt(BankLastCreated(), "debug", "drone_p1_count", UnitGroupCount(UnitGroup("Drone", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    // HunterKiller 技能验证（Abathur 特有 5 个技能）
    // Galaxy 不支持 ?: 三元表达式，必须用 if/else 语句块
    // 用 UnitGroupUnitFromEnd 取 HydraliskImpaler 群组中倒数第 1 个单位作为 HunterKiller 替身
    if (UnitAbilityExists(UnitGroupUnitFromEnd(UnitGroup("HydraliskImpaler", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), 1), "HydraliskBroodlings")) {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_broodlings", 1);
    } else {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_broodlings", 0);
    }
    if (UnitAbilityExists(UnitGroupUnitFromEnd(UnitGroup("HydraliskImpaler", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), 1), "HydraliskCripple")) {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_cripple", 1);
    } else {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_cripple", 0);
    }
    if (UnitAbilityExists(UnitGroupUnitFromEnd(UnitGroup("HydraliskImpaler", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), 1), "HydraliskMechanical")) {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_mechanical", 1);
    } else {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_mechanical", 0);
    }
    if (UnitAbilityExists(UnitGroupUnitFromEnd(UnitGroup("HydraliskImpaler", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), 1), "HydraliskMelee")) {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_melee", 1);
    } else {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_melee", 0);
    }
    if (UnitAbilityExists(UnitGroupUnitFromEnd(UnitGroup("HydraliskImpaler", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), 1), "HydraliskRange")) {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_range", 1);
    } else {
        BankValueSetFromInt(BankLastCreated(), "debug", "hunterkiller_has_range", 0);
    }
    if (TriggerIsEnabled(lib48DF4533_gt_AbathurAbilities) == true) {
        BankValueSetFromInt(BankLastCreated(), "debug", "abathur_abilities_trigger_enabled", 1);
    } else {
        BankValueSetFromInt(BankLastCreated(), "debug", "abathur_abilities_trigger_enabled", 0);
    }
    // === Zerg 单位解锁（SwarmSetup 末尾，UnitUnlocks_Func 之后）===
    // CMRE_PATCH_ZERG_UNIT_UNLOCK_IN_SWARMSETUP
    // 原因：UnitUnlocks_Func 在 SwarmSetup 中被调用，会根据地图 ID/Bank 进度
    // 禁用大部分 Zerg 单位（TechTreeUnitAllow(false)），导致 Larva 丢失 morph 能力。
    // 之前在 InitLib 中 SwarmSetup 触发后立即调用 UnlockAllZergUnits，但
    // TriggerExecute(SwarmSetup, false, false) 是异步的，UnlockAllZergUnits
    // 在 UnitUnlocks_Func 之前执行，被其 false 覆盖。
    // 修复：将 UnlockAllZergUnits 移到 SwarmSetup_Func 末尾（UnitUnlocks_Func 之后），
    // 确保解锁操作不会被覆盖。
    if ("$commanderRace" == "Zerg") {
        libRebornAdapter_gf_UnlockAllZergUnits(1);
        libRebornAdapter_gf_UnlockAllZergUnits(2);
        // === Zerg 起始建筑创建（UnlockAllZergUnits 之后）===
        // CMRE 合作地图不放置 melee 起始建筑（SpawningPool/RoachWarren 等），
        // Reborn mod 自身也不创建（依赖地图预置）。
        // 没有这些建筑，Larva 即使解锁了单位也无法变异（morph 需要前置建筑存在）。
        libRebornAdapter_gf_CreateZergStartingBuildings(1);
        libRebornAdapter_gf_CreateZergStartingBuildings(2);
        // === 强制启用 Larva 变异按钮 ===
        // UnitCreate 创建的建筑可能不被 HaveSpawningPool 等需求验证器识别，
        // 导致 LarvaTrainSwarm2 的 Suppressed 按钮全部隐藏。
        // 使用 CatalogFieldValueSet 清除 Requirements 和 State，让按钮无条件显示。
        libRebornAdapter_gf_ForceEnableLarvaMorphButtons(1);
        libRebornAdapter_gf_ForceEnableLarvaMorphButtons(2);
    }
    BankSave(BankLastCreated());
    return true;
"@
        $content = $content.Replace($swarmSetupEndMarker, $deepDebugBlock)
        Write-Host "Patch-RebornLibraryInit: injected deep debug code at end of SwarmSetup_Func"

        # 只替换最后一次出现的 initLibMarker（即 InitLib 函数中的那个，不是 InitTriggers 函数定义）
        $content = [regex]::Replace($content, [regex]::Escape($initLibMarker) + '\s*\r?\n}', $initLibMarker + "`r`n" + $initLibInjectBlock + "`r`n}")
        Write-Host "Patch-RebornLibraryInit: injected direct K5Kerrigan spawn + SwarmSetup trigger + black screen fix into lib48DF4533_InitLib()"
    } else {
        Write-Host "Patch-RebornLibraryInit: black screen fix already injected, skipping"
    }

    # === 3d. 在 lib48DF4533_InitLib() 函数之前注入 DisableArmySelect 定时补加触发器函数定义 ===
    # 任务2 完善：初始化时只能给已存在单位补加能力，新创建的单位（训练/变异/召唤）需要持续补加。
    # 该触发器每 2 秒扫描所有玩家的活体单位，给未携带 DisableArmySelect 的单位补加。
    # 注意：Galaxy 不支持函数向前引用，函数定义必须在调用之前。
    # lib48DF4533_InitLib() 在文件末尾，在其中调用 gt_DisableArmySelectPoll_Init()，
    # 所以函数定义必须注入到 InitLib 之前。
    $pollFuncBlock = @"

// CMRE_PATCH_DISABLEARMYSELECT_POLL: 公共层定时补加 DisableArmySelect 能力
// 抽离自眼虫（Overseer）的 DisableArmySelect，让所有单位都能脱离部队选择。
trigger gt_DisableArmySelectPoll;

bool gt_DisableArmySelectPoll_Func(bool testConds, bool runActions) {
    int lv_player;
    unitgroup lv_group;
    int lv_count;
    int lv_i;
    unit lv_u;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    for (lv_player = 1; lv_player <= 15; lv_player += 1) {
        lv_group = UnitGroup(null, lv_player, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
        lv_count = UnitGroupCount(lv_group, c_unitCountAlive);
        for (lv_i = 1; lv_i <= lv_count; lv_i += 1) {
            lv_u = UnitGroupUnit(lv_group, lv_i);
            if (lv_u != null) {
                if (!UnitAbilityExists(lv_u, "DisableArmySelect")) {
                    UnitAbilityAdd(lv_u, "DisableArmySelect");
                }
            }
        }
    }
    return true;
}

void gt_DisableArmySelectPoll_Init() {
    gt_DisableArmySelectPoll = TriggerCreate("gt_DisableArmySelectPoll_Func");
    TriggerAddEventTimePeriodic(gt_DisableArmySelectPoll, 2.0, c_timeGame);
}
"@
    $initLibFuncMarker = 'void lib48DF4533_InitLib () {'
    if (-not $content.Contains('void gt_DisableArmySelectPoll_Init()')) {
        $pollFuncBlockNormalized = $pollFuncBlock -replace "`r`n", "`n" -replace "`n", "`r`n"
        if ($content.Contains($initLibFuncMarker)) {
            $content = $content.Replace($initLibFuncMarker, $pollFuncBlockNormalized + "`r`n" + $initLibFuncMarker)
            Write-Host "Patch-RebornLibraryInit: injected DisableArmySelect poll trigger function before lib48DF4533_InitLib()"
        } else {
            $content = $content + $pollFuncBlockNormalized
            Write-Host "Patch-RebornLibraryInit: appended DisableArmySelect poll trigger function to end of Lib48DF4533.galaxy (InitLib marker not found)"
        }
    }

    # === 3e. 修复 PingController_Func 的 EventUnit() 触发器错误 ===
    # 根因：lib48DF4533_gt_PingController_Func 注册的是 TriggerAddEventPing（玩家小地图 ping 事件），
    # 但条件检查中调用了 EventUnit()。Ping 事件只提供 EventPingPoint()，不提供 EventUnit()，
    # 引擎在初始化触发器时即报错"事件响应函数'EventUnit'没有匹配的事件"。
    # 修复：触发器已通过 TriggerAddEventPing(trig, 1) 限定为 player 1，条件检查冗余且无效，
    # 直接跳过（if (false)），保留 Actions 部分的 EventPingPoint() 功能。
    $pingControllerAnchor = '    if (testConds) {
        if (!((UnitGetOwner(EventUnit()) == 1))) {
            return false;
        }
    }'
    $pingControllerPatch = '    if (testConds) {
        if (false) { // CMRE patch: Ping event has no EventUnit(), trigger registered for player 1 only
            return false;
        }
    }'
    if ($content.Contains('lib48DF4533_gt_PingController_Func')) {
        if (-not $content.Contains($pingControllerPatch)) {
            if ($content.Contains($pingControllerAnchor)) {
                $content = $content.Replace($pingControllerAnchor, $pingControllerPatch)
                Write-Host "Patch-RebornLibraryInit: patched PingController_Func EventUnit() error"
            } else {
                Write-Host "Patch-RebornLibraryInit: WARNING - PingController_Func anchor not found, EventUnit patch skipped" -ForegroundColor Yellow
            }
        } else {
            Write-Host "Patch-RebornLibraryInit: PingController patch already applied, skipping"
        }
    }

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $outBytes = $utf8NoBom.GetBytes($content)
    [System.IO.File]::WriteAllBytes($libPath, $outBytes)

    # === 4. 在 MapScript.galaxy 中注入 include "Lib48DF4533" 和 lib48DF4533_InitLib() ===
    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    if (-not (Test-Path -LiteralPath $mapScriptPath)) { throw "Patch-RebornLibraryInit: MapScript.galaxy not found: $mapScriptPath" }
    $mapBytes = [System.IO.File]::ReadAllBytes($mapScriptPath)
    if ($mapBytes.Length -ge 3 -and $mapBytes[0] -eq 0xEF -and $mapBytes[1] -eq 0xBB -and $mapBytes[2] -eq 0xBF) {
        $mapBytes = $mapBytes[3..($mapBytes.Length - 1)]
    }
    $mapScript = [System.Text.Encoding]::UTF8.GetString($mapBytes)

    # 注入 include "Lib281DEC45" 和 "Lib48DF4533"（在最后一个 include 之后）
    # 根因：之前正则 (?m)^include "[^"]+"[^\r\n]*$ 未匹配到现有 include 块，导致 include "Lib48DF4533"
    # 被错误地插入到文件开头（第 1 行），而 NativeLib/LibertyLib/SwarmLib 在第 9-11 行才 include。
    # Galaxy 编译器按 include 顺序解析符号，Lib48DF4533 在 NativeLib 之前 include 会导致
    # libNtve_InitVariables() 等调用因 NativeLib 尚未声明而编译失败，整个 Lib48DF4533 库被跳过。
    # 同时 Lib48DF4533 依赖 Lib281DEC45（swarmstoryutil），也必须先 include Lib281DEC45。
    # 修复：先剥离任何已注入的 include "Lib48DF4533" / "Lib281DEC45"，然后统一在最后一个
    # 现有 include 之后按正确顺序插入 include "Lib281DEC45" 和 include "Lib48DF4533"。
    $mapScript = [regex]::Replace($mapScript, '(?m)^include "Lib48DF4533"\s*\r?\n', '')
    $mapScript = [regex]::Replace($mapScript, '(?m)^include "Lib281DEC45"\s*\r?\n', '')
    $mapScript = [regex]::Replace($mapScript, '(?m)^include "LibMapModBridge"\s*\r?\n', '')
    $mapScript = [regex]::Replace($mapScript, '(?m)^include "LibRebornAdapter"\s*\r?\n', '')
    if (-not ($mapScript -match '(?m)^include "Lib48DF4533"')) {
        $includeMatches = [regex]::Matches($mapScript, '(?m)^[ \t]*include "[^"]+"[^\r\n]*')
        if ($includeMatches.Count -gt 0) {
            $lastInclude = $includeMatches[$includeMatches.Count - 1]
            $insertPos = $lastInclude.Index + $lastInclude.Length
            # include 顺序：Lib281DEC45 → Lib48DF4533（Reborn 库实现） → LibMapModBridge（通用中间层实现） → LibRebornAdapter（Reborn adapter 实现）
            # MapScript.galaxy include 的是实现文件（不带 _h 后缀），不是头文件
            # adapter 必须在 bridge 之后，因为 adapter 依赖 bridge 的 API 声明
            $newIncludes = "`r`n" + 'include "Lib281DEC45"' + "`r`n" + 'include "Lib48DF4533"' + "`r`n" + 'include "LibMapModBridge"' + "`r`n" + 'include "LibRebornAdapter"'
            $mapScript = $mapScript.Substring(0, $insertPos) + $newIncludes + $mapScript.Substring($insertPos)
            Write-Host "Patch-RebornLibraryInit: injected include ""Lib281DEC45"" + ""Lib48DF4533"" + ""LibMapModBridge"" + ""LibRebornAdapter"" after last existing include"
        } else {
            # 罕见：地图没有 include 语句，在文件开头插入
            $mapScript = 'include "Lib281DEC45"' + "`r`n" + 'include "Lib48DF4533"' + "`r`n" + 'include "LibMapModBridge"' + "`r`n" + 'include "LibRebornAdapter"' + "`r`n" + $mapScript
            Write-Host "Patch-RebornLibraryInit: no existing include found, prepended Lib281DEC45 + Lib48DF4533 + LibMapModBridge + LibRebornAdapter at file start"
        }
    }

    # 注入 lib281DEC45_InitLib() 和 lib48DF4533_InitLib() 到 InitLibs() 末尾
    # 顺序：lib281DEC45_InitLib() 必须在 lib48DF4533_InitLib() 之前（依赖关系）
    # 注意：正则必须只匹配 InitLibs() 函数体内的实际调用，不能匹配注释中的文本
    # （MapScript.galaxy 可能在注释中提到 lib48DF4533_InitLib()，导致误判已注入）
    $initLibsPattern = '(?s)void InitLibs \(\) \{(.*?)\}'
    $initLibsMatch = [regex]::Match($mapScript, $initLibsPattern)
    if (-not $initLibsMatch.Success) {
        throw "Patch-RebornLibraryInit: InitLibs() function not found in MapScript.galaxy"
    }
    $initLibsBody = $initLibsMatch.Groups[1].Value
    $has4845 = $initLibsBody -match '(?m)^    lib48DF4533_InitLib\s*\(\s*\)\s*;'
    $has281 = $initLibsBody -match '(?m)^    lib281DEC45_InitLib\s*\(\s*\)\s*;'
    if (-not $has4845) {
        # lib48DF4533_InitLib 未注入，需要注入 lib281 + lib4845
        $initCalls = [regex]::Matches($initLibsBody, '(?m)^    lib\w+_InitLib\(\);[^\r\n]*')
        if ($initCalls.Count -gt 0) {
            $lastCall = $initCalls[$initCalls.Count - 1]
            $absStart = $initLibsMatch.Groups[1].Index + $lastCall.Index
            $absEnd = $absStart + $lastCall.Length
            $newCall = $lastCall.Value + "`r`n    lib281DEC45_InitLib();" + "`r`n    lib48DF4533_InitLib();"
            $mapScript = $mapScript.Substring(0, $absStart) + $newCall + $mapScript.Substring($absEnd)
            Write-Host "Patch-RebornLibraryInit: injected lib281DEC45_InitLib() + lib48DF4533_InitLib() into InitLibs()"
        } else {
            # fallback: 直接在 InitLibs 的 } 前插入
            $closingBrace = $initLibsMatch.Value.LastIndexOf('}')
            if ($closingBrace -le 0) {
                throw "Patch-RebornLibraryInit: InitLibs() closing brace not found"
            }
            $absPos = $initLibsMatch.Index + $closingBrace
            $mapScript = $mapScript.Substring(0, $absPos) + "    lib281DEC45_InitLib();" + "`r`n    lib48DF4533_InitLib();" + "`r`n" + $mapScript.Substring($absPos)
            Write-Host "Patch-RebornLibraryInit: injected lib281DEC45_InitLib() + lib48DF4533_InitLib() before InitLibs closing brace"
        }
    } elseif (-not $has281) {
        # lib4845 已注入但 lib281 缺失，在 lib4845 调用前补上 lib281
        $lib281Replacement = '    lib281DEC45_InitLib();' + "`r`n" + '$1'
        $mapScript = $mapScript -replace '(?m)^(    lib48DF4533_InitLib\(\);)', $lib281Replacement
        Write-Host "Patch-RebornLibraryInit: added missing lib281DEC45_InitLib() before lib48DF4533_InitLib()"
    } else {
        Write-Host "Patch-RebornLibraryInit: lib281DEC45_InitLib() + lib48DF4533_InitLib() already present in InitLibs()"
    }

    $mapOutBytes = $utf8NoBom.GetBytes($mapScript)
    [System.IO.File]::WriteAllBytes($mapScriptPath, $mapOutBytes)
    Write-Host "Patch-RebornLibraryInit: MapScript.galaxy patched successfully"
}

function Install-CmreGalaxyHostOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$ModsRoot,
        [Parameter(Mandatory = $true)][string]$MapPath
    )

    # CMRE and StarCoop both expose LibCO* paths. The map-level copy keeps every
    # CMRE library header and implementation from the same build revision.
    $sourceRoot = Join-Path $ModsRoot "CMRE\CMRE_Core_Triggers.SC2Mod\Base.SC2Data"
    $destinationRoot = Join-Path $MapPath "Base.SC2Data"
    $libraries = Get-ChildItem -LiteralPath $sourceRoot -File -Filter "Lib*.galaxy" | Sort-Object Name
    if ($libraries.Count -eq 0) { throw "CMRE Galaxy host libraries not found: $sourceRoot" }

    [System.IO.Directory]::CreateDirectory($destinationRoot) | Out-Null
    foreach ($library in $libraries) {
        [System.IO.File]::Copy($library.FullName, (Join-Path $destinationRoot $library.Name), $true)
    }

    if ($isAlengerCommander -and $adapterFiles.Count -gt 0) {
        $adapterRoot = Join-Path $ModsRoot "Commanders\$adapterModName.SC2Mod\Base.SC2Data"
        foreach ($name in $adapterFiles) {
            $src = Join-Path $adapterRoot $name
            if (-not (Test-Path -LiteralPath $src)) { throw "$adapterModName galaxy file not found: $src" }
            [System.IO.File]::Copy($src, (Join-Path $destinationRoot $name), $true)
        }
    }

    # RuntimeProbe galaxy files intentionally NOT copied: RuntimeProbe is
    # deprecated as runtime evidence (see docs/deprecated-runtime-probe.md).
    # Runtime evidence must come from sc2-observer.py over the SC2 API
    # websocket (-ListenPort <port>), not from map-side Bank publishing.

    $required = @("LibCOOC_h.galaxy", "LibCOOC.galaxy", "LibCOMI_h.galaxy", "LibCOMI.galaxy")
    if ($isAlengerCommander) {
        $required += $adapterFiles
    }
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $destinationRoot $name))) {
            throw "CMRE Galaxy host overlay is incomplete: $name"
        }
    }
    if ($isAlengerCommander) {
        Write-Host "CMRE Galaxy host overlay: $($libraries.Count) CMRE + $($adapterFiles.Count) $adapterModName files"
    } else {
        Write-Host "CMRE Galaxy host overlay: $($libraries.Count) CMRE files (official commander, no adapter)"
    }
}

function Install-CmreDynamicObserver {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    Install-CmreObserverOverlay -WorkspaceRoot $WorkspaceRoot -MapPath $MapPath -MapName $MapName -IsAlengerCommander $isAlengerCommander -AdapterLibPrefix $adapterLibPrefix -AdapterFiles $adapterFiles -EnableReborn $EnableReborn -RebornCommander $RebornCommander -VibeKernelOverride $VibeKernelOverride
}
function Patch-CmreCoreRuntimeErrors {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    Install-CmreCoreRuntimeErrorOverlay -MapPath $MapPath
}
function Write-CmreLaunchProfile {
    $banksRoot = "C:\Users\22448\Documents\StarCraft II\Banks"
    [System.IO.Directory]::CreateDirectory($banksRoot) | Out-Null
    $doc = [xml]'<Bank version="1"><Section name="CMUI|LaunchProfile" /></Bank>'
    # ModeInstance 必须与 Mode 一致，否则 CMRE 在读取侧会用 ModeInstance 推导模式
    # （CMUIX_LaunchProfileModeIndex）。1=Standard / 2=MutatorChallenges / 3=CustomMutators，
    # 与 CMUIX_LaunchProfileModeInstance 的映射完全对应。
    $modeInstance = switch ($Mode) {
        2 { "MutatorChallenges" }
        3 { "CustomMutators" }
        default { "Standard" }
    }
    # The map requirement is authoritative for API-mode starting state. A map
    # may disable the commander-selection UI while still needing an explicit
    # P1 base/workers after CreateGame; those are separate concerns. P2 is
    # intentionally not synthesized here when the map does not declare it:
    # the Dead of Night Computer ally glue owns P2's native melee opening.
    $createStartingUnitsP1 = if ($mapStartingUnitsPlayers -contains 1) { "1" } else { "0" }
    $createStartingUnitsP2 = if ($mapStartingUnitsPlayers -contains 2) { "1" } else { "0" }
    $ensurePreventDefeatP1 = if ($mapPreventDefeatPlayers -contains 1) { "1" } else { "0" }
    $ensurePreventDefeatP2 = if ($mapPreventDefeatPlayers -contains 2) { "1" } else { "0" }
    $rebornStartingUnitsHandled = if ($EnableReborn -and $RebornCommander -ne "") { "1" } else { "0" }
    $values = [ordered]@{
        Valid = @("int", "1"); Version = @("int", "1");
        CreatedAt = @("int", [string][int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds());
        TimeoutSeconds = @("int", "600");
        Mode = @("int", [string]$Mode);
        ModeInstance = @("string", $modeInstance);
        DifficultyBase = @("int", [string]$DifficultyBase);
        DifficultyPlus = @("int", [string]$DifficultyPlus);
        TargetMission = @("string", "AC_MeinhoffDayNight");
        TargetMap = @("string", "AC_MeinhoffDayNight");
        'Player|1|Commander' = @("string", $Commander);
        'Player|2|Commander' = @("string", $Commander);
        StartingStructure = @("string", $startingStructure);
        StartingWorker = @("string", $startingWorker);
        WorkerCount = @("int", [string]$workerCount);
        CreateStartingUnitsP1 = @("int", $createStartingUnitsP1);
        CreateStartingUnitsP2 = @("int", $createStartingUnitsP2);
        EnsurePreventDefeatP1 = @("int", $ensurePreventDefeatP1);
        EnsurePreventDefeatP2 = @("int", $ensurePreventDefeatP2);
        RebornStartingUnitsHandled = @("int", $rebornStartingUnitsHandled);
        CommanderRace = @("string", $commanderRace);
        VanillaRemovalCount = @("int", [string]$vanillaRemovals.Count)
    }
    for ($vr = 0; $vr -lt $vanillaRemovals.Count; $vr++) {
        $values["VanillaRemoval|$($vr + 1)|Type"] = @("string", [string]$vanillaRemovals[$vr])
    }
    if ($Enemy -ne "") { $values['Enemy'] = @("string", $Enemy) }
    # 解析 Mutators 参数：逗号分隔的 id 列表，可选 ":enhanced" 后缀
    # 示例: "Avenger,Barrier:enhanced,Blizzard"
    if ($Mutators -ne "") {
        # 注意：管道在单元素时会展平为标量，必须用 @() 强制为数组，
        # 否则 $mutatorList[0] 会变成字符串索引返回首个字符（如 "L" 而非 "LazyWorkers"）。
        $mutatorList = @($Mutators -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
        $values['MutatorCount'] = @("int", [string]$mutatorList.Count)
        for ($i = 0; $i -lt $mutatorList.Count; $i++) {
            $parts = $mutatorList[$i] -split ':'
            $mutId = $parts[0].Trim()
            $enhanced = if ($parts.Length -gt 1 -and $parts[1].Trim() -eq "enhanced") { "1" } else { "0" }
            $values["Mutator|$($i + 1)|Id"] = @("string", $mutId)
            $values["Mutator|$($i + 1)|Enhanced"] = @("int", $enhanced)
        }
    }
    # 自定义模式由 CMRE 的混沌因子运行时读取 Chaos|N|Id；强化状态在该模式无定义。
    if ($ChaosMutators -ne "") {
        $chaosList = @($ChaosMutators -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
        $values['ChaosCount'] = @("int", [string]$chaosList.Count)
        for ($i = 0; $i -lt $chaosList.Count; $i++) {
            $values["Chaos|$($i + 1)|Id"] = @("string", $chaosList[$i])
        }
    }
    # CMRE 只会从启动档案读取玩家语音配置，且要求档案被锁定并标记为已保存。
    if ($VoicePack -ne "") {
        $values['ProfileConfigLocked'] = @("int", "1")
        $values['Player|1|CustomizationSaved'] = @("int", "1")
        $values['Player|2|CustomizationSaved'] = @("int", "1")
        $values['Player|1|VoicePack'] = @("string", $VoicePack)
        $values['Player|2|VoicePack'] = @("string", $VoicePack)
    }
    # Buff 补丁：仅当 -EnableBuffPatch 启用时写入。
    # - Buffs: 逗号分隔的 "P1,P2,P3" 子集，编码为 bitmask (P1=1, P2=2, P3=4)
    # - Masteries: 逗号分隔的 6 个 0..30 整数，覆盖原版精通设置
    # galaxy 端通过 CMUIX_LaunchProfileApplyBuffs 读取并应用 supplement upgrade，
    # 精通点数由 CMUIX_LaunchProfileApplyCommanderCustomization 的 mastery 循环读取
    # （Player|N|Mastery|slot|Id + Value，slot 为 1..6 1-indexed）。
    if ($EnableBuffPatch) {
        $bonusMask = 0
        if ($Buffs -match "P1") { $bonusMask += 1 }
        if ($Buffs -match "P2") { $bonusMask += 2 }
        if ($Buffs -match "P3") { $bonusMask += 4 }
        # CustomizationSaved 必须为 1，否则 CMUIX_LaunchProfileApplyCommanderCustomization
        # 会在入口处 return，mastery 与 prestige 都不会被应用。
        $values['ProfileConfigLocked'] = @("int", "1")
        $values['Player|1|CustomizationSaved'] = @("int", "1")
        $values['Player|2|CustomizationSaved'] = @("int", "1")
        $values['Player|1|EnableBuffPatch'] = @("int", "1")
        $values['Player|2|EnableBuffPatch'] = @("int", "1")
        $values['Player|1|PrestigeBonusMask'] = @("int", [string]$bonusMask)
        $values['Player|2|PrestigeBonusMask'] = @("int", [string]$bonusMask)
        Write-Host "BuffPatch: enabled, PrestigeBonusMask=$bonusMask (Buffs='$Buffs')"

        # 精通点数覆盖：从 commander-power-metadata.json 读取 6 个 mastery id，
        # 写入 Player|N|Mastery|slot|Id/Value（slot 1..6 1-indexed）+ MasteryCount + MasteryLevel。
        # galaxy 端 CMUIX_LaunchProfileApplyCommanderCustomization 会读取这些字段并调用
        # libCOOC_gf_CC_PlayerMasteryUpgradeLevelSet 应用精通。
        $masteryRecord = Resolve-CommanderPowerCommanderRecord -Commander $Commander -WorkspaceRoot $LegacyRoot
        $masteryIds = @()
        if ($null -ne $masteryRecord -and $null -ne $masteryRecord.masteries) {
            $masteryIds = @($masteryRecord.masteries | ForEach-Object { [string]$_.id })
        }
        if ($masteryIds.Count -eq 6) {
            $masteryValues = @(30, 30, 30, 30, 30, 30)
            if ($Masteries -ne "") {
                $parsed = @($Masteries -split ',' | ForEach-Object { [int]$_.Trim() })
                for ($i = 0; $i -lt 6 -and $i -lt $parsed.Count; $i++) {
                    $masteryValues[$i] = $parsed[$i]
                }
            }
            $values['Player|1|MasteryCount'] = @("int", "6")
            $values['Player|2|MasteryCount'] = @("int", "6")
            $values['Player|1|MasteryLevel'] = @("int", "180")
            $values['Player|2|MasteryLevel'] = @("int", "180")
            for ($i = 0; $i -lt 6; $i++) {
                $slot = $i + 1
                $values["Player|1|Mastery|$slot|Id"] = @("string", $masteryIds[$i])
                $values["Player|2|Mastery|$slot|Id"] = @("string", $masteryIds[$i])
                $values["Player|1|Mastery|$slot|Value"] = @("int", [string]$masteryValues[$i])
                $values["Player|2|Mastery|$slot|Value"] = @("int", [string]$masteryValues[$i])
            }
            Write-Host "BuffPatch: masteries=$($masteryValues -join ',') ids=$($masteryIds -join ',')"
        } else {
            Write-Host "BuffPatch: WARN commander '$Commander' has $($masteryIds.Count) masteries in metadata, expected 6; skipping mastery override"
        }

        # BuffExtras: 逗号分隔的 3 个整数（P1mask,P2mask,P3mask），每个是该威望下 extra 子选项的 bitmask。
        # 例如 "1,0,0" 表示 P1 的 extra[0] 勾选，P2/P3 无 extras 勾选。
        $extraMasks = @(0, 0, 0)
        if ($BuffExtras -ne "") {
            $parsed = @($BuffExtras -split ',' | ForEach-Object { [int]$_.Trim() })
            for ($i = 0; $i -lt 3 -and $i -lt $parsed.Count; $i++) {
                $extraMasks[$i] = $parsed[$i]
            }
        }
        for ($slot = 1; $slot -le 3; $slot++) {
            $mask = $extraMasks[$slot - 1]
            $values["Player|1|PrestigeExtrasMaskP$slot"] = @("int", [string]$mask)
            $values["Player|2|PrestigeExtrasMaskP$slot"] = @("int", [string]$mask)
        }
        Write-Host "BuffPatch: extras=$($extraMasks -join ',') (BuffExtras='$BuffExtras')"
    } else {
        $values['Player|1|EnableBuffPatch'] = @("int", "0")
        $values['Player|2|EnableBuffPatch'] = @("int", "0")
    }
    foreach ($entry in $values.GetEnumerator()) {
        $key = $doc.CreateElement("Key"); $key.SetAttribute("name", $entry.Key)
        $value = $doc.CreateElement("Value"); $value.SetAttribute($entry.Value[0], $entry.Value[1])
        $key.AppendChild($value) | Out-Null; $doc.Bank.Section.AppendChild($key) | Out-Null
    }
    $settings = [System.Xml.XmlWriterSettings]::new(); $settings.Indent = $true; $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.Xml.XmlWriter]::Create((Join-Path $banksRoot "CMCoopLaunchProfile.SC2Bank"), $settings)
    try { $doc.Save($writer) } finally { $writer.Dispose() }
    Write-Host "CMCoopLaunchProfile 银行已写入: Mode=$Mode, DifficultyBase=$DifficultyBase, DifficultyPlus=$DifficultyPlus, Enemy='$Enemy', Mutators='$Mutators', ChaosMutators='$ChaosMutators', VoicePack='$VoicePack'"
}

function Set-RebornCommander {
    param(
        [Parameter(Mandatory = $true)][string]$Commander,
        [int]$Difficulty = 5,
        [int]$Speed = 5,
        [switch]$UnlockAllMaps
    )
    # 白名单与 lib48DF4533_gt_CommanderStart_Func 的 14 个指挥官 + Random 一致
    $validCommanders = @(
        "Abathur","Dehaka","Izsha","Karass","Kerrigan","Mengsk","Naktul","Narud",
        "Raynor","Stukov","Tosh","Urun","Warfield","Zagara","Zeratul","Random"
    )
    if ($validCommanders -notcontains $Commander) {
        throw "Invalid Reborn commander: $Commander. Valid: $($validCommanders -join ', ')"
    }
    if ($Difficulty -lt 1 -or $Difficulty -gt 5) {
        throw "Reborn Difficulty must be 1..5 (1=Easy, 2=Normal, 3=Hard, 4=Expert, 5=Expert+)"
    }
    if ($Speed -lt 1 -or $Speed -gt 5) {
        throw "Reborn Speed must be 1..5 (1=Slower, 2=Slow, 3=Normal, 4=Fast, 5=Faster)"
    }
    $banksRoot = "C:\Users\22448\Documents\StarCraft II\Banks"
    [System.IO.Directory]::CreateDirectory($banksRoot) | Out-Null
    # Evolutions 默认值：取每个字段 if-else 顺序的第一个选项。
    # 仅 Zerg 系指挥官（Abathur/Izsha/Kerrigan/Naktul/Zagara/Tosh/Random）会读取 Evolutions；
    # 其他指挥官（Dehaka/Karass/Mengsk/Narud/Stukov/Urun/Warfield/Zeratul）走 Commander 替换路径，忽略此节。
    $evolutions = [ordered]@{
        "Zergling"        = "Raptorling"
        "Baneling"        = "Hunter"
        "Roach"           = "Corpser"
        "Hydralisk"       = "Impaler"
        "Mutalisk"        = "Char"
        "Swarm Host"      = "Carrion"
        "Ultralisk"       = "Indra"
        "Monstrous Flier" = "Brood Lord"
        "Caster"          = "Infestor"
    }
    # Maps 节：8 个虫群战役地图，全部 flag=1 解锁全部单位科技树。
    # 对应关系（lib48DF4533_gf_IsUnitUnlocked）：
    #   Harvest of Screams → Roach, Shoot the Messenger → Hydralisk,
    #   Waking the Ancient → Mutalisk, The Crucible → Swarm Host,
    #   Domination → Baneling, With Friends Like These → Heavy Air,
    #   Infested → Caster, Hand of Darkness → Ultralisk
    $maps = @(
        "Harvest of Screams",
        "Shoot the Messenger",
        "Waking the Ancient",
        "The Crucible",
        "Domination",
        "With Friends Like These",
        "Infested",
        "Hand of Darkness"
    )
    $doc = [xml]'<Bank version="1" />'
    # Section Commanders
    $secCmd = $doc.CreateElement("Section"); $secCmd.SetAttribute("name", "Commanders")
    $keyCmd = $doc.CreateElement("Key"); $keyCmd.SetAttribute("name", "Commander")
    $valCmd = $doc.CreateElement("Value"); $valCmd.SetAttribute("string", $Commander)
    $keyCmd.AppendChild($valCmd) | Out-Null; $secCmd.AppendChild($keyCmd) | Out-Null
    $doc.Bank.AppendChild($secCmd) | Out-Null
    # Section Settings
    $secSet = $doc.CreateElement("Section"); $secSet.SetAttribute("name", "Settings")
    foreach ($entry in @(
        @("Difficulty", "int", [string]$Difficulty),
        @("Speed", "int", [string]$Speed),
        @("Story", "int", "0")
    )) {
        $k = $doc.CreateElement("Key"); $k.SetAttribute("name", $entry[0])
        $v = $doc.CreateElement("Value"); $v.SetAttribute($entry[1], $entry[2])
        $k.AppendChild($v) | Out-Null; $secSet.AppendChild($k) | Out-Null
    }
    $doc.Bank.AppendChild($secSet) | Out-Null
    # Section Evolutions
    $secEvo = $doc.CreateElement("Section"); $secEvo.SetAttribute("name", "Evolutions")
    foreach ($e in $evolutions.GetEnumerator()) {
        $k = $doc.CreateElement("Key"); $k.SetAttribute("name", $e.Key)
        $v = $doc.CreateElement("Value"); $v.SetAttribute("string", $e.Value)
        $k.AppendChild($v) | Out-Null; $secEvo.AppendChild($k) | Out-Null
    }
    $doc.Bank.AppendChild($secEvo) | Out-Null
    # Section Maps (optional)
    if ($UnlockAllMaps) {
        $secMap = $doc.CreateElement("Section"); $secMap.SetAttribute("name", "Maps")
        foreach ($m in $maps) {
            $k = $doc.CreateElement("Key"); $k.SetAttribute("name", $m)
            $v = $doc.CreateElement("Value"); $v.SetAttribute("flag", "1")
            $k.AppendChild($v) | Out-Null; $secMap.AppendChild($k) | Out-Null
        }
        $doc.Bank.AppendChild($secMap) | Out-Null
    }
    $settings = [System.Xml.XmlWriterSettings]::new(); $settings.Indent = $true; $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    # SC2 银行路径规则：Banks\<PlayerID>\<BankName>.SC2Bank（PlayerID 子目录优先），
    # 部分历史版本也接受 Banks\<BankName>.SC2Bank（根目录）。
    # 为兼容两种路径，同时写入根目录、Banks\1\（P1）、Banks\14\（P14）三个位置。
    # Reborn 的 coop_group 同时包含 P1 和 P14（当 P14 是 user 玩家时），
    # CommanderStart_Func 会为每个玩家 BankLoad("cryswarmcoop", playerId) 并读取 Commander 值。
    # 注意：必须用 string 类型写入 Commander 值，因为 Reborn 用 BankValueGetAsString 读取，
    # 旧版 text 类型会被读取为空字符串。
    $bankTargets = @(
        (Join-Path $banksRoot "cryswarmcoop.SC2Bank"),
        (Join-Path $banksRoot "1\cryswarmcoop.SC2Bank"),
        (Join-Path $banksRoot "14\cryswarmcoop.SC2Bank")
    )
    foreach ($bankPath in $bankTargets) {
        $parentDir = Split-Path -Parent $bankPath
        if ($parentDir -and -not (Test-Path $parentDir)) { [System.IO.Directory]::CreateDirectory($parentDir) | Out-Null }
        $writer = [System.Xml.XmlWriter]::Create($bankPath, $settings)
        try { $doc.Save($writer) } finally { $writer.Dispose() }
    }
    Write-Host "cryswarmcoop 银行已写入: Commander=$Commander, Difficulty=$Difficulty, Speed=$Speed, UnlockAllMaps=$([bool]$UnlockAllMaps) (root + P1 + P14)"
}

function Get-CmreRuntimeBankPaths {
    $banksRoot = Join-Path $env:USERPROFILE "Documents\StarCraft II\Banks"
    return @(
        (Join-Path $banksRoot "CMRERebornDebug.SC2Bank"),
        (Join-Path $banksRoot "1\CMRERebornDebug.SC2Bank"),
        (Join-Path $banksRoot "2\CMRERebornDebug.SC2Bank"),
        (Join-Path $banksRoot "14\CMRERebornDebug.SC2Bank")
    )
}

function Set-CmreRuntimeBankInt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][int]$Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) { [System.IO.Directory]::CreateDirectory($parent) | Out-Null }
    [xml]$doc = if (Test-Path -LiteralPath $Path) {
        Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    } else {
        '<Bank version="1" />'
    }
    if ($null -eq $doc.Bank) {
        $doc = [xml]'<Bank version="1" />'
    }
    $section = @($doc.Bank.Section | Where-Object { $_.name -eq "debug" } | Select-Object -First 1)
    if ($section.Count -eq 0) {
        $sectionNode = $doc.CreateElement("Section")
        $sectionNode.SetAttribute("name", "debug")
        $doc.Bank.AppendChild($sectionNode) | Out-Null
    } else {
        $sectionNode = $section[0]
    }
    $keyNode = @($sectionNode.Key | Where-Object { $_.name -eq $Key } | Select-Object -First 1)
    if ($keyNode.Count -eq 0) {
        $keyElement = $doc.CreateElement("Key")
        $keyElement.SetAttribute("name", $Key)
        $sectionNode.AppendChild($keyElement) | Out-Null
    } else {
        $keyElement = $keyNode[0]
    }
    $valueElement = @($keyElement.Value | Select-Object -First 1)
    if ($valueElement.Count -eq 0) {
        $valueNode = $doc.CreateElement("Value")
        $keyElement.AppendChild($valueNode) | Out-Null
    } else {
        $valueNode = $valueElement[0]
    }
    $valueNode.RemoveAllAttributes()
    $valueNode.SetAttribute("int", [string]$Value)
    $settings = [System.Xml.XmlWriterSettings]::new()
    $settings.Indent = $true
    $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.Xml.XmlWriter]::Create($Path, $settings)
    try { $doc.Save($writer) } finally { $writer.Dispose() }
}

function Reset-CmreRuntimeListenerBank {
    foreach ($path in Get-CmreRuntimeBankPaths) {
        foreach ($key in @(
            "runtime_listener_started", "runtime_listener_ready", "bridge_heartbeat_started",
            "bridge_heartbeat", "world_cover_dialog_visible_p1", "startup_load_allied",
            "startup_map_init", "startup_dev_begin", "startup_custom_launch",
            "startup_dev_finish", "triggers_customscript_entered", "headless_startup_entered",
            "map_init_entered", "stage16_before_vibe", "stage16_after_vibe",
            "initialization_gate_started", "initialization_complete",
            "initialization_building_ready_p1", "initialization_building_ready_p2",
            "initialization_units_ready_p1", "initialization_units_ready_p2",
            "bridge_starting_units_created_p1", "bridge_starting_units_created_p2",
            "bridge_prevent_defeat_p1", "bridge_prevent_defeat_p2",
            "bridge_prevent_defeat_created_p1", "bridge_prevent_defeat_created_p2",
            "reborn_adapter_initialized",
            "zerg_starting_buildings_created_p1", "zerg_starting_buildings_created_p2"
        )) {
            Set-CmreRuntimeBankInt -Path $path -Key $key -Value 0
        }
    }
    Write-Host "CMRE runtime listener bank reset"
}

function Get-CmreRuntimeBankInt {
    param([Parameter(Mandatory = $true)][string]$Key)
    foreach ($path in Get-CmreRuntimeBankPaths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        try {
            $bankXml = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
            $pattern = '<Key\s+name="' + [regex]::Escape($Key) + '">\s*<Value\s+int="(-?\d+)"'
            if ($bankXml -match $pattern) { return [int]$Matches[1] }
        } catch { }
    }
    return $null
}

function Get-CmreNewScriptErrorFiles {
    param([Parameter(Mandatory = $true)][datetime]$Since)
    $gameLogsDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "StarCraft II\GameLogs"
    if (-not (Test-Path -LiteralPath $gameLogsDir)) { return @() }
    $threshold = $Since.AddSeconds(-2)
    return @(Get-ChildItem -LiteralPath $gameLogsDir -Recurse -File -Filter "*ScriptError*.txt" -ErrorAction SilentlyContinue |
        Where-Object { $_.CreationTime -ge $threshold -or $_.LastWriteTime -ge $threshold } |
        Sort-Object LastWriteTime)
}

function Get-CmreNewAlertFiles {
    param([Parameter(Mandatory = $true)][datetime]$Since)
    $gameLogsDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "StarCraft II\GameLogs"
    if (-not (Test-Path -LiteralPath $gameLogsDir)) { return @() }
    $threshold = $Since.AddSeconds(-2)
    return @(Get-ChildItem -LiteralPath $gameLogsDir -Recurse -File -Filter "*Alert*.txt" -ErrorAction SilentlyContinue |
        Where-Object { $_.CreationTime -ge $threshold -or $_.LastWriteTime -ge $threshold } |
        Sort-Object LastWriteTime)
}

function Wait-CmreGameLogMapLoadSignal {
    param(
        [Parameter(Mandatory = $true)][datetime]$Since,
        [int]$TimeoutSeconds = 180
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $alerts = @(Get-CmreNewAlertFiles -Since $Since)
        if ($alerts.Count -gt 0) {
            Write-Host "GameLogs map-load gate: Alerts file created: $($alerts[0].FullName)"
            return "Alert"
        }
        $scriptErrors = @(Get-CmreNewScriptErrorFiles -Since $Since)
        if ($scriptErrors.Count -gt 0) {
            Write-Host "GameLogs map-load gate: ScriptError file created: $($scriptErrors[0].FullName)"
            return "ScriptError"
        }
        Start-Sleep -Seconds 1
    }
    throw "GameLogs map-load gate failed: no new *Alert*.txt or *ScriptError*.txt within $TimeoutSeconds seconds."
}

function Assert-CmreNoNewScriptErrors {
    param([Parameter(Mandatory = $true)][datetime]$Since)
    $errors = @(Get-CmreNewScriptErrorFiles -Since $Since | Where-Object { $_.Length -gt 0 })
    if ($errors.Count -gt 0) {
        $first = $errors[0]
        $preview = ""
        try { $preview = (Get-Content -LiteralPath $first.FullName -Raw -ErrorAction Stop).Trim() } catch { }
        if ($preview.Length -gt 800) { $preview = $preview.Substring(0, 800) + "..." }
        throw ("New non-empty ScriptError detected after launch: " + $first.FullName + [Environment]::NewLine + $preview)
    }
    Write-Host "ScriptError gate: no new non-empty *ScriptError*.txt files"
}

function Wait-CmreRuntimeListener {
    param([int]$TimeoutSeconds = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $firstHeartbeat = $null
    while ((Get-Date) -lt $deadline) {
        $started = Get-CmreRuntimeBankInt -Key "runtime_listener_started"
        $ready = Get-CmreRuntimeBankInt -Key "runtime_listener_ready"
        $heartbeat = Get-CmreRuntimeBankInt -Key "bridge_heartbeat"
        $worldCoverVisible = Get-CmreRuntimeBankInt -Key "world_cover_dialog_visible_p1"
        $initializationComplete = Get-CmreRuntimeBankInt -Key "initialization_complete"
        $buildingReadyP1 = Get-CmreRuntimeBankInt -Key "initialization_building_ready_p1"
        $buildingReadyP2 = Get-CmreRuntimeBankInt -Key "initialization_building_ready_p2"
        $unitsReadyP1 = Get-CmreRuntimeBankInt -Key "initialization_units_ready_p1"
        $unitsReadyP2 = Get-CmreRuntimeBankInt -Key "initialization_units_ready_p2"
        $initializationReady = ($initializationComplete -gt 0) -and
            ($buildingReadyP1 -gt 0) -and ($buildingReadyP2 -gt 0) -and
            ($unitsReadyP1 -gt 0) -and ($unitsReadyP2 -gt 0)
        if (($started -gt 0) -and ($ready -gt 0) -and ($heartbeat -gt 0) -and $initializationReady) {
            if ($null -eq $firstHeartbeat) {
                $firstHeartbeat = $heartbeat
                Start-Sleep -Seconds 3
                continue
            }
            if ($heartbeat -gt $firstHeartbeat) {
                if ($worldCoverVisible -eq 1) {
                    throw "Runtime listener heartbeat is active, but world cover dialog is still visible; likely black screen."
                }
                Write-Host "Runtime listener gate: ready after complete map initialization; heartbeat $firstHeartbeat -> $heartbeat"
                return
            }
        } else {
            $firstHeartbeat = $null
        }
        Start-Sleep -Seconds 1
    }
    throw "Runtime listener gate failed: complete initialization marker/building/unit checks plus increasing bridge_heartbeat were not observed within $TimeoutSeconds seconds."
}

$script:Sc2RuntimeLeasePath = [System.IO.Path]::GetFullPath($script:Sc2RuntimeLeasePath)

function Get-Sc2RuntimeLease {
    if (-not [System.IO.File]::Exists($script:Sc2RuntimeLeasePath)) { return $null }
    try {
        return [System.IO.File]::ReadAllText($script:Sc2RuntimeLeasePath) | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Write-Sc2RuntimeLease {
    param(
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$OwnerSession,
        [int]$RuntimePid = 0,
        [int]$Port = 0
    )
    $leaseParent = Split-Path -Parent $script:Sc2RuntimeLeasePath
    [System.IO.Directory]::CreateDirectory($leaseParent) | Out-Null
    $lease = [ordered]@{
        schemaVersion = 1
        ownerPid = [int]$PID
        ownerSessionId = $OwnerSession
        runtimePid = [int]$RuntimePid
        port = [int]$Port
        state = $State
        mapName = $MapName
        commander = $Commander
        launcher = $MyInvocation.PSCommandPath
        startedAt = [DateTimeOffset]::Now.ToString("o")
        heartbeatAt = [DateTimeOffset]::Now.ToString("o")
    }
    $existing = Get-Sc2RuntimeLease
    if ($null -ne $existing -and $existing.ownerSessionId -eq $OwnerSession) {
        $lease.startedAt = $existing.startedAt
    }
    $tmp = Join-Path $leaseParent (".sc2-runtime-lease.$PID.$([Guid]::NewGuid().ToString('N')).tmp")
    try {
        [System.IO.File]::WriteAllText($tmp, ($lease | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
        if ([System.IO.File]::Exists($script:Sc2RuntimeLeasePath)) {
            # Windows PowerShell/.NET does not expose the newer three-argument
            # File.Move overload. Move-Item provides the required overwrite
            # behavior while keeping the temporary file in the lease directory.
            Move-Item -LiteralPath $tmp -Destination $script:Sc2RuntimeLeasePath -Force
        } else {
            [System.IO.File]::Move($tmp, $script:Sc2RuntimeLeasePath)
        }
    } finally {
        if ([System.IO.File]::Exists($tmp)) { [System.IO.File]::Delete($tmp) }
    }
}

function Remove-Sc2RuntimeLease {
    param([string]$OwnerSession = "", [switch]$Force)
    $existing = Get-Sc2RuntimeLease
    if ($null -eq $existing) { return }
    if (-not $Force -and $OwnerSession -ne $existing.ownerSessionId) { return }
    try { [System.IO.File]::Delete($script:Sc2RuntimeLeasePath) } catch { }
}

function Get-Sc2RuntimeProcesses {
    $names = @("SC2_x64", "SC2", "StarCraft II", "SC2Switcher_x64", "SC2Switcher")
    $processes = foreach ($name in $names) {
        @(Get-Process -Name $name -ErrorAction SilentlyContinue)
    }
    return @($processes | Sort-Object Id -Unique)
}

function Get-Sc2GameProcesses {
    return @(Get-Sc2RuntimeProcesses | Where-Object { $_.ProcessName -notmatch "Switcher" })
}

function Format-Sc2RuntimeBusyMessage {
    param([object[]]$Processes, $Lease)
    $ownerPid = "unknown"
    $ownerPort = "unknown"
    $ownerSession = "unknown"
    if ($null -ne $Lease) {
        if ($Lease.ownerPid) { $ownerPid = $Lease.ownerPid }
        if ($Lease.runtimePid -and $Lease.runtimePid -gt 0) { $ownerPid = $Lease.runtimePid }
        if ($Lease.port -and $Lease.port -gt 0) { $ownerPort = $Lease.port }
        if ($Lease.ownerSessionId) { $ownerSession = $Lease.ownerSessionId }
    }
    if ($ownerPid -eq "unknown" -and @($Processes).Count -gt 0) {
        $ownerPid = (@($Processes)[0]).Id
    }
    return "SC2_RUNTIME_BUSY`nowner_pid=$ownerPid`nowner_port=$ownerPort`nowner_session=$ownerSession"
}

function Wait-Sc2RuntimeProcess {
    param(
        [Parameter(Mandatory = $true)][int]$RuntimePid,
        [Parameter(Mandatory = $true)]$LockContext,
        [Parameter(Mandatory = $true)][string]$OwnerSession,
        [int]$Port = 0
    )
    Write-Host "SC2 runtime lease: KeepAlive holds the global lease while PID=$RuntimePid is alive"
    while ($null -ne (Get-Process -Id $RuntimePid -ErrorAction SilentlyContinue)) {
        try { Renew-TestLock -LockContext $LockContext -AdditionalSeconds 300 | Out-Null } catch { }
        Write-Sc2RuntimeLease -State "keepalive" -OwnerSession $OwnerSession -RuntimePid $RuntimePid -Port $Port
        Start-Sleep -Seconds 5
    }
    Write-Host "SC2 runtime lease: PID=$RuntimePid exited; releasing the global lease"
}

function Wait-Sc2SecondaryRuntimeProcess {
    param(
        [Parameter(Mandatory = $true)][int]$RuntimePid
    )
    Write-Host "SC2 secondary client: KeepAlive holds PID=$RuntimePid without replacing the primary runtime lease"
    while ($null -ne (Get-Process -Id $RuntimePid -ErrorAction SilentlyContinue)) {
        Start-Sleep -Seconds 5
    }
    Write-Host "SC2 secondary client: PID=$RuntimePid exited; releasing the secondary test lock"
}

$lock = $null
$sc2RuntimeMutex = $null
$sc2RuntimeMutexAcquired = $false
$sc2RuntimeLeaseSession = ""
$runtimePid = 0
$runtimeReady = $false
$debugPidFile = Join-Path $env:TEMP "cmre-debug-sc2-$PID.pid"
try {
    $sc2RuntimeMutex = [System.Threading.Mutex]::new($false, $script:Sc2RuntimeMutexName)
    try {
        $sc2RuntimeMutexAcquired = $sc2RuntimeMutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $sc2RuntimeMutexAcquired = $true
        Write-Host "SC2 runtime lease: recovered an abandoned global mutex" -ForegroundColor Yellow
    }
    if (-not $sc2RuntimeMutexAcquired) {
        throw (Format-Sc2RuntimeBusyMessage -Processes @(Get-Sc2RuntimeProcesses) -Lease (Get-Sc2RuntimeLease))
    }

    if ($ReuseStagedMap) {
        $liveMap = Join-Path (Join-Path $Sc2Root "Maps\$MapCopySuffix") $MapName
        if (-not (Test-Path -LiteralPath $liveMap -PathType Container)) {
            throw "-ReuseStagedMap requires an existing staged map directory: $liveMap"
        }
        Write-Host "Reusing existing staged map: $liveMap"
    }
    if (-not $SecondaryClient -and -not $ReuseStagedMap) {
        $lock = Acquire-TestLock -TestType "cmre_alenger" -MapName $MapName -Commander $Commander
    }

    if ($PlayerMode) {
        # PlayerMode and DebugMode share the same preflight: a launcher never kills
        # a runtime that may belong to another AI session or to the human player.
        Write-Host "SC2 runtime lease: PlayerMode requested; existing runtime will be rejected, never killed"
    }
    if (-not $NoLaunch -and -not $SecondaryClient) {
        $existing = @(Get-Sc2RuntimeProcesses)
        if ($existing.Count -gt 0) {
            throw (Format-Sc2RuntimeBusyMessage -Processes $existing -Lease (Get-Sc2RuntimeLease))
        }
    }
    $sc2RuntimeLeaseSession = if ($lock) { [string]$lock.session_id } elseif ($SecondaryClient) { "secondary-$PID-$ListenPort" } else { "reuse-primary-$PID-$ListenPort" }
    if (-not $SecondaryClient) {
        Write-Sc2RuntimeLease -State "staging" -OwnerSession $sc2RuntimeLeaseSession -Port $ListenPort
    }
    if (Test-Path $debugPidFile) { Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue }
    if (-not $SecondaryClient) { Clear-GameLogs }
    if (-not $ReuseStagedMap) {
    # A secondary SC2 client reuses the primary client's already-synchronized
    # installation.  Touching shared mod files here can race the primary
    # process and is unnecessary because the secondary client only joins the
    # game created by P1.
    if (-not $SecondaryClient) {
    Sync-ModSet -ModRelPaths $cmre.baseMods -ProjRoot $LegacyRoot -Sc2Root $Sc2Root
    # basePackageMods: 来自 packages 目录的基础 mod（如 CMRE_BuffPatch），与 baseMods 互补
    if ($cmre.PSObject.Properties.Name -contains 'basePackageMods' -and @($cmre.basePackageMods).Count -gt 0) {
        Sync-ModSet -ModRelPaths $cmre.basePackageMods -ProjRoot $AlengerPackagesRoot -Sc2Root $Sc2Root
    }
    if (@($cmre.commanderBaseMods).Count -gt 0) {
        Sync-ModSet -ModRelPaths $cmre.commanderBaseMods -ProjRoot $AlengerPackagesRoot -Sc2Root $Sc2Root
    }
    if ($cmre.PSObject.Properties.Name -contains 'extraPackageMods' -and @($cmre.extraPackageMods).Count -gt 0) {
        Sync-ModSet -ModRelPaths $cmre.extraPackageMods -ProjRoot $AlengerPackagesRoot -Sc2Root $Sc2Root
    }
    if ($cmre.PSObject.Properties.Name -contains 'extraFileMods' -and @($cmre.extraFileMods).Count -gt 0) {
        foreach ($entry in $cmre.extraFileMods) {
            $src = Join-Path $LegacyRoot "Mods\$($entry.src -replace '/', '\')"
            $dst = Join-Path $Sc2Root "Mods\$($entry.dst -replace '/', '\')"
            $dstParent = Split-Path $dst -Parent
            if (-not (Test-Path $dstParent)) {
                [System.IO.Directory]::CreateDirectory($dstParent) | Out-Null
            }
            if (Test-Path $src) {
                [System.IO.File]::Copy($src, $dst, $true)
                Write-Host "SYNC (extra file): $($entry.dst)"
            } else {
                Write-Host "WARN: extra file source not found: $src"
            }
        }
    }
    if ($selectedMods.Count -gt 0) {
        Sync-ModSet -ModRelPaths @($selectedMods | ForEach-Object { "Commanders\$_.SC2Mod" }) -ProjRoot $AlengerPackagesRoot -Sc2Root $Sc2Root
    }
    if ($dedupedExtra.Count -gt 0) {
        Sync-ModSet -ModRelPaths @($dedupedExtra | ForEach-Object { "Commanders\$_.SC2Mod" }) -ProjRoot $AlengerPackagesRoot -Sc2Root $Sc2Root
    }
    # -EnableReborn: 同步 5 个 reborn mod 到 SC2 安装目录 Mods/reborn/。
    # ProjRoot 是 LegacyRoot（cmre-runtime），因为 reborn mod 存放在 cmre-runtime/Mods/reborn/。
    # SwarmStory 战役包（swarmstory.sc2campaign + swarmstoryutil.sc2mod）需已部署到
    # SC2 安装目录 Campaigns/ 下，否则主 mod 的战役依赖无法解析。
    if ($EnableReborn) {
        if ($cmre.PSObject.Properties.Name -notcontains 'optionalPackageMods') {
            throw "optionalPackageMods not declared in cmre-alenger-dependencies.json"
        }
        Sync-ModSet -ModRelPaths $cmre.optionalPackageMods -ProjRoot $LegacyRoot -Sc2Root $Sc2Root
        # 校验 SwarmStory 战役依赖是否已部署
        $swarmStoryCampaignPath = Join-Path $Sc2Root "Campaigns\swarmstory.sc2campaign"
        $swarmStoryUtilPath = Join-Path $Sc2Root "Campaigns\swarmstoryutil.sc2mod"
        if (-not (Test-Path -LiteralPath $swarmStoryCampaignPath)) {
            throw "SwarmStory campaign not found: $swarmStoryCampaignPath (required by reborn main mod)"
        }
        if (-not (Test-Path -LiteralPath $swarmStoryUtilPath)) {
            throw "swarmstoryutil.sc2mod not found: $swarmStoryUtilPath (required by reborn main mod)"
        }
        Write-Host "Reborn mods synced to: $($Sc2Root)\Mods\reborn\"
    }
    # Remove StarCoop dependency from 7vs1 mods: CMRE provides its own LibCOOC,
    # and StarCoop causes signature conflicts ("函数同此前的定义不匹配") plus
    # "模块或地图关联内容已不可用" since bnet:Co-op Mission is not available in
    # custom game mode. Patch BOTH DocumentInfo (XML) and DocumentHeader (binary).
    $starCoopDepMarker = 'bnet:Co-op Mission/0.0/999,file:Mods/StarCoop/StarCoop.SC2Mod'
    $starCoopBytes = [System.Text.Encoding]::UTF8.GetBytes($starCoopDepMarker)
    $modsToPatchStarCoop = @()
    $modsToPatchStarCoop += @($cmre.commanderBaseMods | ForEach-Object { Join-Path $Sc2Root "Mods\$_" })
    if ($cmre.PSObject.Properties.Name -contains 'extraPackageMods') {
        $modsToPatchStarCoop += @($cmre.extraPackageMods | ForEach-Object { Join-Path $Sc2Root "Mods\$_" })
    }
    $modsToPatchStarCoop += @($selectedMods | ForEach-Object { Join-Path $Sc2Root "Mods\Commanders\$_.SC2Mod" })
    $modsToPatchStarCoop += @($dedupedExtra | ForEach-Object { Join-Path $Sc2Root "Mods\Commanders\$_.SC2Mod" })
    $starCoopRemovedCount = 0
    foreach ($modDir in $modsToPatchStarCoop) {
        if (-not (Test-Path $modDir)) { continue }
        $modPatched = $false
        # Patch DocumentInfo (XML)
        $infoPath = Join-Path $modDir "DocumentInfo"
        if (Test-Path $infoPath) {
            $infoContent = [System.IO.File]::ReadAllText($infoPath, [System.Text.Encoding]::UTF8)
            if ($infoContent.Contains($starCoopDepMarker)) {
                $starCoopRegex = '\s*<Value>bnet:Co-op Mission/0\.0/999,file:Mods/StarCoop/StarCoop\.SC2Mod</Value>'
                $patchedInfo = [regex]::Replace($infoContent, $starCoopRegex, '')
                [System.IO.File]::WriteAllText($infoPath, $patchedInfo, (New-Object System.Text.UTF8Encoding $true))
                $modPatched = $true
            }
        }
        # Patch DocumentHeader (binary) - always use direct byte-level removal for reliability
        $headerPath = Join-Path $modDir "DocumentHeader"
        if (Test-Path $headerPath) {
            [byte[]]$headerBytes = [System.IO.File]::ReadAllBytes($headerPath)
            $foundIdx = -1
            for ($bi = 0; $bi -le $headerBytes.Length - $starCoopBytes.Length; $bi++) {
                $match = $true
                for ($bj = 0; $bj -lt $starCoopBytes.Length; $bj++) {
                    if ($headerBytes[$bi + $bj] -ne $starCoopBytes[$bj]) { $match = $false; break }
                }
                if ($match) { $foundIdx = $bi; break }
            }
            if ($foundIdx -ge 0) {
                $removeStart = $foundIdx
                if ($removeStart -gt 0 -and $headerBytes[$removeStart - 1] -eq 0) { $removeStart-- }
                $afterStart = $foundIdx + $starCoopBytes.Length
                $newLen = $removeStart + ($headerBytes.Length - $afterStart)
                $newBytes = New-Object byte[] $newLen
                [Array]::Copy($headerBytes, 0, $newBytes, 0, $removeStart)
                [Array]::Copy($headerBytes, $afterStart, $newBytes, $removeStart, $headerBytes.Length - $afterStart)
                [System.IO.File]::WriteAllBytes($headerPath, $newBytes)
                $modPatched = $true
            }
        }
        if ($modPatched) { $starCoopRemovedCount++ }
    }
    if ($starCoopRemovedCount -gt 0) {
        Write-Host "StarCoop dependency removed from $starCoopRemovedCount Commanders mod(s)"
    }
    }
    # MapCopySuffix: 使用独立的 live 地图副本，避免多会话同时操作同一地图导致 DocumentInfo 冲突。
    # 例如 -MapCopySuffix "reborn" → Maps\reborn\亡者之夜.SC2Map\
    # 注意：SC2 要求地图目录名以 .SC2Map 结尾，所以后缀作为子目录而非文件名扩展。
    if ($MapCopySuffix -ne "") {
        $liveMapDir = Join-Path $Sc2Root "Maps\$MapCopySuffix"
        if (-not (Test-Path -LiteralPath $liveMapDir)) { [System.IO.Directory]::CreateDirectory($liveMapDir) | Out-Null }
        $liveMap = Join-Path $liveMapDir $MapName
        Write-Host "Using isolated map copy: $MapCopySuffix\$MapName"
    } else {
        $liveMap = Join-Path $Sc2Root "Maps\$MapName"
    }
    if (Test-Path -LiteralPath $liveMap) { [System.IO.Directory]::Delete($liveMap, $true) }
    [System.IO.Directory]::CreateDirectory($liveMap) | Out-Null
    robocopy $mapSource $liveMap /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    Install-CmreGalaxyHostOverlay -ModsRoot (Join-Path $Sc2Root "Mods") -MapPath $liveMap
    if ($ShowSelectionUI -and -not $commanderSelectionDisabled) {
        # ShowSelectionUI: 不 patch LibCOOC.galaxy，保留 CMRE 原生启动流程。
        # 仅对仍保留原生选择流程的其他 CMRE 地图开放。
        Write-Host "CMRE ShowSelectionUI: skipping saved-profile startup patch, selection UI will be shown"
    } elseif ($commanderSelectionDisabled) {
        # 亡者之夜的选择界面属于不再使用的地图启动代码：staged map 必须删除该分支，
        # 不能依赖 LaunchProfile bank 或调用方参数避免误入。
        Write-Host "CMRE map policy: commander selection code disabled for $MapName; forcing headless startup"
        Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -ApiMinimal:$ApiMinimal -SkipCountdown:$SkipCountdown -SkipPause:$SkipPause -Headless
    } elseif ($ApiMinimal) {
        # ApiMinimal: API 客户端负责 CreateGame+JoinGame，但 staged map 仍强制使用
        # 预设 commander 并移除 selection fallback，避免进入地图后回到选择界面。
        Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -ApiMinimal -Headless
    } elseif ($SkipCountdown) {
        # 显式 SkipCountdown：客户端用 CreateGame+JoinGame 推进状态；仍走 headless startup。
        Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -SkipCountdown -Headless
    } else {
        # 默认模式：注入 commander 设置并直接调用 CMUIX_ReadyBeginCountdown，
        # 让启动直接进入地图；只有显式 -ShowSelectionUI 才保留指挥官选择界面。
        # 之前把 -ListenPort > 0 合并到 SkipCountdown 分支是错误的：ReadyBeginCountdown 被跳过
        # 导致 SC2 永远卡在 Launched，GameInfo/Step 全部报 "Not in a game"。
        # 2026-07-25 修复：API 模式（-ListenPort > 0）加 -SkipPause，跳过
        # DevStartupBegin 开头的 GameSetMissionTimePaused/AITimePause/UnitPauseAll，
        # 这三个调用会把游戏暂停，但不会影响 API 状态（状态由 CreateGame/JoinGame 控制）。
        if ($ListenPort -gt 0 -and -not $DirectMapApi) {
            # API 模式：P1 和 P2 都设置指挥官（CMRE 正常逻辑）。
            # CMRE galaxy 触发器强制 P1=Participant（API 加入位置），P2=Computer（AI 队友）。
            # API 以 P1 身份加入，操作 P1 的指挥官单位（type_4390/4386 CC / type_4382 SCV）。
            # 这才是 CMRE 的"玩家队友"角色——有指挥官的单位，而非 vanilla 单位。
            # ability ID 使用 CMRE 自定义值（17428/17514 训练 SCV，16/17/18 建造建筑）。
            Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -SkipPause -Headless
        } else {
            Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -Headless
        }
    }
    # Install-CmreDynamicObserver 必须始终调用：
    #   - 注入 gt_Alenger3StartingUnits_Init（创建 5 个 3diguolaogong 工人 + 前哨基地）
    #   - 注入 libA3ADAPTER_InitLib（科技树解锁）
    #   - 移除 vanilla 单位（CommandCenterRaynor/SCVRaynor 等）
    # API 模式下 NeuroIntegration Bank 不会被读取（数据通过 SC2 API 读取），
    # 但 libEFA54406_gf_Publish 已有 null guard（LibPortingObserver.galaxy:5），
    # 且实际崩溃根因是 -listen 与地图路径互斥，与 NeuroIntegration 注入无关。
    Install-CmreDynamicObserver -MapPath $liveMap
    Patch-CmreCoreRuntimeErrors -MapPath $liveMap
    # Reborn 模式：三层 patch 确保 Reborn galaxy 库能被初始化并执行指挥官替换逻辑。
    # 1. Patch-RebornK5KerriganSpawn: 修改 mod 源文件，注入 K5Kerrigan 创建代码（保留用于源同步）
    # 2. Patch-RebornBankAuthorization: 授权地图 BankList.xml 加载 cryswarmcoop 银行
    # 3. Patch-RebornLibraryInit: 复制 Reborn 依赖的 galaxy 库到地图目录，并在 MapScript.galaxy
    #    中注入 include "Lib48DF4533" 和 lib48DF4533_InitLib() 调用（根本修复）
    if ($EnableReborn) {
        Patch-RebornK5KerriganSpawn -ModsRoot (Join-Path $Sc2Root "Mods")
        Patch-RebornBankAuthorization -MapPath $liveMap
        Patch-RebornLibraryInit -Sc2Root $Sc2Root -MapPath $liveMap
    }
    Set-MapDependencies -MapPath $liveMap -Dependencies $dependencies
    $roundtrip = Test-DocumentDependencyRoundtrip -HeaderPath (Join-Path $liveMap "DocumentHeader") -InfoPath (Join-Path $liveMap "DocumentInfo")
    if (-not $roundtrip.Valid) { throw "Document dependency roundtrip failed: $($roundtrip.Errors -join '; ')" }
    # CampaignXCore 银行映射仅覆盖官方/Alenger 指挥官；Reborn 专属指挥官（Izsha/Karass/
    # Naktul/Narud/Tosh/Urun/Warfield）不在映射表中，跳过成就银行写入而非抛异常中断。
    if (-not $SecondaryClient) {
        try {
            Set-CampaignXCorePrimaryCommander -SelectedCommanders @($Commander)
            Set-CampaignXCoreTestRunId -RunId "CMREAlenger"
        } catch {
            Write-Host "WARN: CampaignXCore mapping skipped for $Commander (non-fatal for Reborn commanders): $_"
        }
    } else {
        Write-Host "SecondaryClient: skipping shared CampaignXCore bank writes"
    }
    # Reborn 模式：预写 cryswarmcoop.SC2Bank，让重生虫心 mod 读取指定指挥官并自动执行 SwarmSetup。
    # 必须在 -EnableReborn 模式下使用，且 RebornCommander 必须是重生虫心支持的指挥官名称。
    if ($EnableReborn -and $RebornCommander -ne "") {
        Set-RebornCommander -Commander $RebornCommander -Difficulty $RebornDifficulty -Speed $RebornSpeed -UnlockAllMaps
    }
    if ($ShowSelectionUI -and -not $commanderSelectionDisabled -and -not $SecondaryClient) {
        # 删除已有的 LaunchProfile 银行文件，确保 CMRE 不会自动应用已保存的配置，
        # 而是显示指挥官选择界面。
        $bankPath = "C:\Users\22448\Documents\StarCraft II\Banks\CMCoopLaunchProfile.SC2Bank"
        if (Test-Path -LiteralPath $bankPath) {
            [System.IO.File]::Delete($bankPath)
            Write-Host "CMRE ShowSelectionUI: deleted existing CMCoopLaunchProfile.SC2Bank to force selection UI"
        }
    } elseif (-not $SecondaryClient) {
        Write-CmreLaunchProfile
    } else {
        Write-Host "SecondaryClient: skipping shared CMRE launch profile bank write"
    }
    }
    if ($NoLaunch) { Write-Host "CMRE Alenger composition staged: $liveMap"; exit 0 }
    $existing = @(Get-Sc2RuntimeProcesses)
    if ($existing.Count -gt 0 -and -not $SecondaryClient) {
        throw (Format-Sc2RuntimeBusyMessage -Processes $existing -Lease (Get-Sc2RuntimeLease))
    }
    if ($MapCopySuffix -ne "" -and $ListenPort -le 0) {
        throw "-MapCopySuffix is for staging/API isolation only in this launcher. Direct SC2 map launch must use Maps\\$MapName so GameLogs emits the Alerts/ScriptError load signal; omit -MapCopySuffix for WebUI/player launch."
    }
    if (-not $SecondaryClient) {
        Reset-CmreRuntimeListenerBank
    } else {
        Write-Host "SecondaryClient: skipping shared runtime listener bank reset"
    }
    $switcher = Join-Path $Sc2Root "Support64\SC2Switcher_x64.exe"
    if ($ListenPort -gt 0) {
        if ($DirectMapApi) {
            # DirectMapApi is the runtime bridge for maps whose InitMap graph
            # is only executed by the Switcher direct-map path. The API is
            # attached to that already-loaded game so a client can observe it
            # with --join-existing; CreateGame is intentionally not used.
            $argList = @("`"$liveMap`"", "-listen", "127.0.0.1", "-port", "$ListenPort", "-debug")
            Write-Host "SC2 direct-map + API mode: launching SC2Switcher_x64.exe $($argList -join ' ')"
            $launchStartedAt = Get-Date
            Start-Process -FilePath $switcher -ArgumentList $argList -WorkingDirectory (Split-Path -Parent $switcher)
            Wait-CmreGameLogMapLoadSignal -Since $launchStartedAt -TimeoutSeconds 180 | Out-Null
            Assert-CmreNoNewScriptErrors -Since $launchStartedAt
            Write-Host "SC2 direct-map + API mode: polling TCP 127.0.0.1:$ListenPort until listening (max 120s)..."
            $deadline = (Get-Date).AddSeconds(120)
            $listening = $false
            while ((Get-Date) -lt $deadline) {
                $sc2Processes = @(Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue)
                if ($sc2Processes.Count -eq 0) {
                    Start-Sleep -Seconds 2
                    continue
                }
                try {
                    $tcp = New-Object System.Net.Sockets.TcpClient
                    $iar = $tcp.BeginConnect("127.0.0.1", $ListenPort, $null, $null)
                    $ok = $iar.AsyncWaitHandle.WaitOne(800)
                    if ($ok -and $tcp.Connected) {
                        $tcp.EndConnect($iar)
                        $tcp.Close()
                        $listening = $true
                        break
                    }
                    $tcp.Close()
                } catch { }
                Start-Sleep -Seconds 2
            }
            if (-not $listening) {
                $stillRunning = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
                if ($null -eq $stillRunning) {
                    throw "SC2 direct-map + API mode: SC2_x64.exe exited before API port $ListenPort opened"
                }
                throw "SC2 direct-map + API mode: API port $ListenPort did not open within 120s"
            }
            Write-Host "SC2 direct-map + API mode: API listening on 127.0.0.1:$ListenPort"
            Wait-CmreRuntimeListener -TimeoutSeconds 120
            Assert-CmreNoNewScriptErrors -Since $launchStartedAt
            $runtimeReady = $true
            $runtimeProcess = @(Get-Sc2GameProcesses | Select-Object -First 1)
            if ($runtimeProcess.Count -gt 0) {
                $runtimePid = [int]$runtimeProcess[0].Id
                Write-Sc2RuntimeLease -State "ready" -OwnerSession $sc2RuntimeLeaseSession -RuntimePid $runtimePid -Port $ListenPort
            }
            Write-Host "SC2 direct-map + API mode: map is ready; Host must attach with --join-existing"
        } else {
        # API 模式：用 SC2Switcher -listen <host> -port <port> 启动 SC2。
        # 关键（Base97425 实机验证 2026-07-25）：
        #   - SC2 静默忽略 -listenPort，必须用 -listen/-port 格式
        #   - SC2_x64.exe 直接启动会崩溃（Battle.net auth broker missing），必须通过 Switcher
        #   - 工作目录必须是 SC2 安装根目录，否则 SC2 回退到 6119
        #   - 不用 -e <map>：让 SC2 停在主菜单（launched 状态），客户端用 CreateGame + JoinGame
        #     加载地图并推进到 in_game。galaxy 触发器只在 in_game 状态下才执行。
        #   - 之前用 -e <map> 的方案失败：SC2 加载地图后 API 状态停在 Launched，
        #     不经过 CreateGame/JoinGame 无法进入 in_game（s2client-proto 状态机）。
        #   - 不用 Wait-GameReady：它检测 Switcher 进程，而 Switcher 启动 SC2_x64 后
        #     会退出，被误判为"Game process exited (crash)"。改用端口轮询。
        if ($ApiMinimal) {
            # ApiMinimal 模式：不传 -e <map>，SC2 停在主菜单，客户端用 CreateGame 加载地图。
            # 与默认 API 模式的区别：ApiMinimal 在 DevStartupBegin 直接 return，不执行
            # commander 设置和 CustomStartupLaunch，仅用于 P11 catalog 验证。
            # -debug：启用 DebugCommand（DebugCreateUnit/AllResources/FastBuild 等），API 模式下必须，
            #         否则 RequestDebug 会被 SC2 静默忽略（单位生成、作弊等全部无效）。
            $argList = @("-listen","127.0.0.1","-port","$ListenPort","-debug")
            Write-Host "SC2 API mode (ApiMinimal): launching SC2Switcher with -listen 127.0.0.1 -port $ListenPort -debug (no -e, client uses CreateGame)"
            Write-Host "SC2 API will listen on 127.0.0.1:$ListenPort"
            Write-Host "Working directory: $Sc2Root"
            Write-Host "Live map staged at: $liveMap (client loads it via CreateGame + map_data)"
        } else {
            # 默认 API 模式：不传 -e <map>，SC2 停在主菜单（Launched 状态）。
            # 客户端用 CreateGame + JoinGame 加载地图并推进到 in_game。
            # SkipPause 补丁已在上方应用（注释暂停调用，保留 commander 设置）。
            # 之前用 -e <map> 的方案失败：SC2 加载地图后 API 状态卡在 Launched，
            # 不经过 CreateGame/JoinGame 无法进入 in_game，GameInfo/Step 全部报
            # "Not in a game"。详见 s2client-proto protocol.md 状态机。
            # -debug：启用 DebugCommand（DebugCreateUnit/AllResources/FastBuild 等），API 模式下必须，
            #         否则 RequestDebug 会被 SC2 静默忽略（单位生成、作弊等全部无效）。
            $argList = @("-listen","127.0.0.1","-port","$ListenPort","-debug")
            Write-Host "SC2 API mode: launching SC2Switcher with -listen 127.0.0.1 -port $ListenPort -debug (no -e, client uses CreateGame+JoinGame)"
            Write-Host "SC2 API will listen on 127.0.0.1:$ListenPort"
            Write-Host "Working directory: $Sc2Root"
            Write-Host "Live map staged at: $liveMap (client loads it via CreateGame + map_data)"
        }
        # Multiple native participant clients must not share SC2's default temp
        # directory. python-sc2 creates one per SC2Process; mirror that contract
        # here while keeping the approved Switcher launch path.
        $runtimeTempDir = Join-Path $env:TEMP "sc2-vibe-$PID-$ListenPort"
        New-Item -ItemType Directory -Force -Path $runtimeTempDir | Out-Null
        # Match python-sc2's explicit installation data root as well. The
        # embedded quotes are required because the Windows install path has a
        # space and Start-Process joins ArgumentList before launching Switcher.
        $sc2DataDir = if ($DataDirOverride -ne "") { $DataDirOverride } else { $Sc2Root }
        if (-not (Test-Path -LiteralPath $sc2DataDir -PathType Container)) {
            throw "SC2 data directory does not exist: $sc2DataDir"
        }
        $sc2DataDirArg = '"' + $sc2DataDir + '"'
        $argList += @("-dataDir", $sc2DataDirArg, "-tempDir", $runtimeTempDir)
        Write-Host "SC2 runtime data directory: $sc2DataDir"
        Write-Host "SC2 runtime temp directory: $runtimeTempDir"
        $launchStartedAt = Get-Date
        Start-Process -FilePath $switcher -ArgumentList $argList -WorkingDirectory $Sc2Root
        # API 模式下轮询 TCP 端口，直到 SC2 API 监听就绪（最多等 120s）。
        Write-Host "SC2 API mode: polling TCP 127.0.0.1:$ListenPort until listening (max 120s)..."
        $deadline = (Get-Date).AddSeconds(120)
        $listening = $false
        while ((Get-Date) -lt $deadline) {
            $sc2Processes = @(Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue)
            if ($sc2Processes.Count -eq 0) {
                Start-Sleep -Seconds 2
                continue
            }
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $iar = $tcp.BeginConnect("127.0.0.1", $ListenPort, $null, $null)
                $ok = $iar.AsyncWaitHandle.WaitOne(800)
                if ($ok -and $tcp.Connected) {
                    $tcp.EndConnect($iar)
                    $tcp.Close()
                    # Multiple participant clients may be alive at once. Resolve
                    # the process that owns this API port instead of coercing the
                    # complete SC2 process list to an Int32.
                    $portOwner = @(Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1) | Select-Object -First 1
                    if ($null -eq $portOwner) {
                        throw "SC2 API port $ListenPort connected but has no owning process"
                    }
                    $ownerPid = @($portOwner.OwningProcess) | Select-Object -First 1
                    if ($null -eq $ownerPid) {
                        throw "SC2 API port $ListenPort has no scalar owning process id"
                    }
                    $proc = @(Get-Process -Id ([int]$ownerPid) -ErrorAction Stop) | Select-Object -First 1
                    $listening = $true
                    break
                }
                $tcp.Close()
            } catch { }
            Start-Sleep -Seconds 2
        }
        if (-not $listening) {
            $stillRunning = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
            if ($null -eq $stillRunning) {
                throw "SC2 API mode: SC2_x64.exe exited before API port $ListenPort opened (crash or auth broker missing). Check GameLogs."
            } else {
                throw "SC2 API mode: SC2_x64.exe is running but API port $ListenPort did not open within 120s."
            }
        }
        Write-Host "SC2 API mode: API listening on 127.0.0.1:$ListenPort (SC2_x64 PID=$($proc.Id))"
        $runtimePid = [int]$proc.Id
        if (-not $SecondaryClient) {
            Write-Sc2RuntimeLease -State "api_listening" -OwnerSession $sc2RuntimeLeaseSession -RuntimePid $runtimePid -Port $ListenPort
        }
        # DebugMode：记录 PID 到文件（用于退出时按 PID 关闭，避免误杀玩家游戏）+ 最小化窗口
        if ($DebugMode) {
            Set-Content -Path $debugPidFile -Value $proc.Id -Encoding UTF8
            Write-Host "DebugMode: SC2 PID $($proc.Id) 写入 $debugPidFile"
            # 最小化 SC2 窗口（Win32 API ShowWindowAsync, SW_MINIMIZE=6）
            try {
                $signature = '[DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);'
                $win32Type = Add-Type -MemberDefinition $signature -Name "Win32ShowWindowAsync" -Namespace Win32Functions -PassThru
                $minDeadline = (Get-Date).AddSeconds(30)
                $minimized = $false
                while ((Get-Date) -lt $minDeadline) {
                    $sc2Proc = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
                    if ($sc2Proc -and $sc2Proc.MainWindowHandle -ne [IntPtr]::Zero) {
                        $win32Type::ShowWindowAsync($sc2Proc.MainWindowHandle, 6) | Out-Null
                        Write-Host "DebugMode: SC2 窗口已最小化"
                        $minimized = $true
                        break
                    }
                    Start-Sleep -Milliseconds 500
                }
                if (-not $minimized) { Write-Host "DebugMode: SC2 窗口最小化超时（非致命）" }
            } catch {
                Write-Host "DebugMode: 最小化窗口失败（非致命）: $_"
            }
        }
        # 给地图加载额外宽限时间：端口监听后 galaxy 触发器仍在执行（CMUIX_ReadyBeginCountdown 倒计时）。
        # 轮询 GameLogs 是否出现 ScriptError 或地图加载完成信号（Alerts.txt）。
        $gameLogsDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "StarCraft II\GameLogs"
        $latestDir = Get-ChildItem -LiteralPath $gameLogsDir -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -ne $latestDir) {
            $deadline2 = (Get-Date).AddSeconds(60)
            while ((Get-Date) -lt $deadline2) {
                $scriptErr = Get-ChildItem -LiteralPath $latestDir.FullName -Filter "*ScriptError*.txt" -ErrorAction SilentlyContinue
                if ($null -ne $scriptErr -and $scriptErr.Count -gt 0) {
                    Write-Host "SC2 API mode: ScriptError detected, map load likely failed: $($scriptErr[0].FullName)"
                    break
                }
                $alerts = Get-ChildItem -LiteralPath $latestDir.FullName -Filter "Alerts*.txt" -ErrorAction SilentlyContinue
                if ($null -ne $alerts -and $alerts.Count -gt 0) {
                    $alertsContent = Get-Content $alerts[0].FullName -Raw -ErrorAction SilentlyContinue
                    if ($alertsContent -match 'GameStart|MapLoad|UILoad|loading complete') {
                        Write-Host "SC2 API mode: map load signal detected in Alerts.txt"
                        break
                    }
                }
                Start-Sleep -Seconds 2
            }
        }
        Write-Host "SC2 API mode: ready, client can connect with CreateGame + JoinGame"
        Assert-CmreNoNewScriptErrors -Since $launchStartedAt
        $runtimeReady = $true
        if (-not $SecondaryClient) {
            Write-Sc2RuntimeLease -State "ready" -OwnerSession $sc2RuntimeLeaseSession -RuntimePid $runtimePid -Port $ListenPort
        }
        # API mode intentionally stops before CreateGame + JoinGame. Galaxy map
        # initialization cannot run until the Host loads the map, so the Host's
        # wait_for_initialization gate owns the post-join readiness check.
        Write-Host "SC2 API mode: launcher gate complete; Host must CreateGame + JoinGame and wait for full map initialization before actions"
        }
    } else {
        # 普通/WebUI 模式：沿用已验证的 CMRE baseline，地图路径作为 Switcher 位置参数。
        # 是否真正加载地图由本次 GameLogs 新增 *Alert*.txt / *ScriptError*.txt 判定。
        $argList = "`"$liveMap`""
        Write-Host "SC2 direct-map mode: launching SC2Switcher_x64.exe $argList"
        $launchStartedAt = Get-Date
        Start-Process -FilePath $switcher -ArgumentList $argList -WorkingDirectory (Split-Path -Parent $switcher)
        Wait-CmreGameLogMapLoadSignal -Since $launchStartedAt -TimeoutSeconds 180 | Out-Null
        Assert-CmreNoNewScriptErrors -Since $launchStartedAt
        Wait-CmreRuntimeListener -TimeoutSeconds 120
        Assert-CmreNoNewScriptErrors -Since $launchStartedAt
        $runtimeReady = $true
        $runtimeProcess = @(Get-Sc2GameProcesses | Select-Object -First 1)
        if ($runtimeProcess.Count -gt 0) {
            $runtimePid = [int]$runtimeProcess[0].Id
            if (-not $SecondaryClient) {
                Write-Sc2RuntimeLease -State "ready" -OwnerSession $sc2RuntimeLeaseSession -RuntimePid $runtimePid -Port 0
            }
        }
    }

    # === 黑屏检测（基于心跳 + 世界覆盖层状态）===
    # 原理：LibMapModBridge 心跳触发器每 2s 递增 bridge_heartbeat 银行值
    # 判定逻辑：
    #   - 心跳递增 + world_cover_dialog_visible_p1=0 → 正常
    #   - 心跳递增 + world_cover_dialog_visible_p1=1 → 黑屏（世界覆盖层可见）
    #   - 心跳不变 → 脚本卡住（可能崩溃或死锁）
    if ($EnableReborn -and $RebornCommander -ne "") {
        Write-Host ""
        Write-Host "=== Black Screen Detection ==="
        $bankPath = Join-Path $env:USERPROFILE "Documents\StarCraft II\Banks\CMRERebornDebug.SC2Bank"
        $heartbeatBefore = -1
        $heartbeatAfter = -1
        $worldCoverVisible = -1
        if (Test-Path -LiteralPath $bankPath) {
            # 读取第一次心跳
            $bankXml = [System.IO.File]::ReadAllText($bankPath, [System.Text.Encoding]::UTF8)
            if ($bankXml -match '<Key name="bridge_heartbeat">\s*<Value int="(\d+)"') { $heartbeatBefore = [int]$Matches[1] }
            if ($bankXml -match '<Key name="world_cover_dialog_visible_p1">\s*<Value int="(\d+)"') { $worldCoverVisible = [int]$Matches[1] }
            Write-Host "Heartbeat (before): $heartbeatBefore"
            Write-Host "World cover visible: $worldCoverVisible"
            # 等待 5 秒，让心跳递增
            Write-Host "Waiting 5s for heartbeat increment..."
            Start-Sleep -Seconds 5
            # 读取第二次心跳
            $bankXml = [System.IO.File]::ReadAllText($bankPath, [System.Text.Encoding]::UTF8)
            if ($bankXml -match '<Key name="bridge_heartbeat">\s*<Value int="(\d+)"') { $heartbeatAfter = [int]$Matches[1] }
            Write-Host "Heartbeat (after):  $heartbeatAfter"
            # 判定
            $heartbeatDelta = $heartbeatAfter - $heartbeatBefore
            Write-Host "Heartbeat delta:    $heartbeatDelta"
            if ($heartbeatBefore -lt 0 -or $heartbeatAfter -lt 0) {
                Write-Host "WARNING: bridge_heartbeat not found in bank - adapter may not have run" -ForegroundColor Yellow
            } elseif ($heartbeatDelta -le 0) {
                Write-Host "ERROR: Heartbeat not incrementing - Galaxy script may be stuck or crashed" -ForegroundColor Red
            } elseif ($worldCoverVisible -eq 1) {
                Write-Host "ERROR: BLACK SCREEN DETECTED - world cover dialog is visible (heartbeat running but UI hidden)" -ForegroundColor Red
            } else {
                Write-Host "OK: No black screen detected (heartbeat incrementing, world cover hidden)" -ForegroundColor Green
            }
        } else {
            Write-Host "WARNING: Bank file not found: $bankPath" -ForegroundColor Yellow
        }
        Write-Host ""
    }
} finally {
    # DebugMode 默认只关闭本次 launcher 记录的 PID；绝不按进程名杀别人的 SC2。
    # -KeepAlive 期间 launcher 自身持续持有 named mutex，避免留下无人保护的 runtime。
    if ($KeepAlive -and $runtimeReady -and $runtimePid -gt 0) {
        if ($SecondaryClient) {
            Wait-Sc2SecondaryRuntimeProcess -RuntimePid $runtimePid
        } else {
            Wait-Sc2RuntimeProcess -RuntimePid $runtimePid -LockContext $lock -OwnerSession $sc2RuntimeLeaseSession -Port $ListenPort
        }
    }
    if ($DebugMode -and -not $KeepAlive -and (Test-Path $debugPidFile)) {
        $debugPid = Get-Content $debugPidFile -ErrorAction SilentlyContinue
        if ($debugPid) {
            Write-Host "DebugMode: 退出时关闭 SC2 (PID=$debugPid)"
            Stop-Process -Id $debugPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
    }
    if ($sc2RuntimeLeaseSession -and -not $SecondaryClient) {
        $liveRuntime = @(Get-Sc2GameProcesses)
        if ($liveRuntime.Count -gt 0 -and ($runtimeReady -or $runtimePid -gt 0) -and -not $KeepAlive) {
            if ($runtimePid -le 0) { $runtimePid = [int]$liveRuntime[0].Id }
            try { Write-Sc2RuntimeLease -State "detached" -OwnerSession $sc2RuntimeLeaseSession -RuntimePid $runtimePid -Port $ListenPort } catch { }
        } else {
            Remove-Sc2RuntimeLease -OwnerSession $sc2RuntimeLeaseSession
        }
    }
    if ($null -ne $lock) { Release-TestLock -LockContext $lock }
    if ($sc2RuntimeMutexAcquired -and $null -ne $sc2RuntimeMutex) {
        try { $sc2RuntimeMutex.ReleaseMutex() } catch { }
    }
    if ($null -ne $sc2RuntimeMutex) { $sc2RuntimeMutex.Dispose() }
}
