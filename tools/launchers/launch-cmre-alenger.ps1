[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$MapName, [Parameter(Mandatory = $true)][string]$Commander, [switch]$DryRun, [switch]$NoLaunch, [int]$ListenPort = 0, [string]$LegacyRootOverride = "", [int]$Mode = 1, [int]$DifficultyBase = 0, [int]$DifficultyPlus = 0, [string]$Enemy = "", [string]$Mutators = "", [string]$ChaosMutators = "", [string]$VoicePack = "", [string]$ExtraMods = "", [switch]$SkipCountdown, [switch]$ApiMinimal, [switch]$ShowSelectionUI, [switch]$EnableReborn, [string]$RebornCommander = "", [int]$RebornDifficulty = 5, [int]$RebornSpeed = 5, [switch]$PlayerMode, [switch]$DebugMode, [string]$Buffs = "", [string]$Masteries = "", [string]$BuffExtras = "", [switch]$EnableBuffPatch, [string]$MapCopySuffix = "")
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

function Convert-TestCommanderToCommanderPowerKey {
    param([string]$Commander)
    return (Convert-CommanderPowerCommanderToBankKey -Commander $Commander -WorkspaceRoot $LegacyRoot)
}
$cmre = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "src\config\cmre-alenger-dependencies.json") -Raw | ConvertFrom-Json
$alenger = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "src\config\alenger-mods.json") -Raw | ConvertFrom-Json
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
# 默认值（Alenger3 兼容路径）：保留旧的硬编码行为
$adapterLibPrefix = 'A3ADAPTER'
$adapterFiles = @("LibA3ADAPTER_h.galaxy", "LibA3ADAPTER.galaxy", "LibA3ADAPTER_Catalog.galaxy")
$adapterModName = 'Alenger3Adapter'
$startingStructure = '3diguoqianshaojidi'
$startingWorker = '3diguolaogong'
$workerCount = 5
$vanillaRemovals = @('CommandCenterRaynor', 'SCVRaynor', 'MarineRaynor', 'RaynorCommando', 'CoopCasterRaynor', 'CommandCenter', 'SCV')
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
$mapSource = Join-Path $LegacyRoot "Maps\CMRE\$MapName"
if (-not (Test-Path -LiteralPath $mapSource)) { throw "CMRE map source not found: $mapSource" }
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
        [switch]$KeepPlayer1Vanilla
    )
    # Patch the map-level LibCOOC.galaxy (copied by Install-CmreGalaxyHostOverlay)
    # instead of the mod-source copy. The mod source is overwritten by Sync-ModSet
    # (robocopy /MIR) on every launch, which silently dropped the previous patch.
    # Patching the map copy after the host overlay guarantees the edit survives.
    $path = Join-Path $MapPath "Base.SC2Data\LibCOOC.galaxy"
    if (-not (Test-Path -LiteralPath $path)) { throw "Map-level LibCOOC.galaxy not found: $path" }
    $content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    # CMUIX_StartupApplySavedConfiguration() shows the commander selection UI when
    # CMUIX_LaunchProfileTryLoadForStartupAll() returns false. Bypass that call
    # entirely: manually run the core init steps, pre-set the requested commander
    # for players 1 and 2, then drive CMUIX_ReadyBeginCountdown() so its finish
    # handler emits CU_CommChoiceEventClosed and finalizes the commander state.
    $startupPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        Wait\(1\.0, c_timeReal\);\r?\n        CMUIX_ReadyBeginCountdown\(\);\r?\n        return ;\r?\n    \}'
    $startupFallbackPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        TriggerSendEvent\("CU_CommChoiceEventClosed"\);\r?\n        return ;\r?\n    \}'
    $replacementBody = @"
    if ((CMUIX_CoreReady == false)) { CMUIX_CoreInit(); }
    CMUIX_StartupLoadPersistentProfiles();
    CMUIX_HistoryPrunePendingRecordsAll();
    CMUIX_LaunchProfileOpenBank(1);
    if (BankLastCreated() != null) {
        BankValueSetFromInt(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "CreatedAt", DateTimeToInt(CurrentDateTimeGet()));
        BankValueSetFromString(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "TargetMission", CMUIX_MapSelectionCurrentMapInstance());
        BankValueSetFromString(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "TargetMap", CMUIX_MapSelectionCurrentMapInstance());
        BankSave(BankLastCreated());
        if (CMUIX_LaunchProfileValidForStartup(BankLastCreated()) == true) {
            CMUIX_LaunchProfileApply(BankLastCreated());
        }
    }
"@
    # KeepPlayer1Vanilla: 跳过 P1 的指挥官设置，让 P1 保留 vanilla 单位（type_18 CC / type_45 SCV）。
    # 用于 API 模式：API 以 P1 身份加入（P1=Participant），操作 vanilla 单位用标准 ability ID 训练/建造。
    # P2 仍然设置指挥官（被 galaxy 触发器替换为指挥官单位），由 AI 控制。
    if (-not $KeepPlayer1Vanilla) {
        $replacementBody += @"
    libCOTF_gv_sELECTED_Commander[1] = "$Commander";
    libCOTF_gv_sELECTED_Commander_Random[1] = false;
    libCOOC_gf_CC_PlayerCommanderSet(1, "$Commander");
    libCOUI_gv_cU_CommanderSelection[1] = "$Commander";
    libCOUI_gv_cU_CommanderSelect_PlayerReady[1] = true;
    libCOUI_gf_CU_CommanderFinalizeStates(1);
"@
    } else {
        Write-Host "DEBUG Enable-CmreSavedProfileStartup: KeepPlayer1Vanilla — skipping P1 commander setup (P1 keeps vanilla units for API control)"
    }
    $replacementBody += @"
    libCOTF_gv_sELECTED_Commander[2] = "$Commander";
    libCOTF_gv_sELECTED_Commander_Random[2] = false;
    libCOOC_gf_CC_PlayerCommanderSet(2, "$Commander");
    libCOUI_gv_cU_CommanderSelection[2] = "$Commander";
    libCOUI_gv_cU_CommanderSelect_PlayerReady[2] = true;
    libCOUI_gf_CU_CommanderFinalizeStates(2);
"@
    if ($ApiMinimal) {
        # ApiMinimal: skip all galaxy startup patches (CustomStartupBegin pause,
        # ReadyBeginCountdown, etc.). SC2 stays at main menu (Launched) after
        # CreateGame. The client uses realtime=true + Step/Observation to advance
        # to in_game (see Sc2Api.RealProfile.CreateAndJoinGameAsync).
        Write-Host "ApiMinimal: skipping galaxy startup patches (client drives CreateGame+JoinGame)"
        return
    }

    if ($SkipPause) {
        # CustomStartupBegin runs before DevStartupBegin and pauses the mission
        # before SC2API can complete JoinGame. Patch both sites as one API-mode
        # invariant; leaving this earlier pause intact keeps the API in Launched.
        $customStartupPausePattern = '(?m)(void libCOOC_gf_CC_CustomStartupBegin \(\) \{[\s\S]*?    // Implementation\r?\n)    GameSetMissionTimePaused\(true\);\r?\n    AITimePause\(true\);\r?\n    UnitPauseAll\(true\);'
        $customStartupPauseReplacement = '$1' + [string]::Join([Environment]::NewLine, @(
            '    // API mode (SkipPause): do not pause before SC2API JoinGame',
            '    // GameSetMissionTimePaused(true); -- skipped',
            '    // AITimePause(true); -- skipped',
            '    // UnitPauseAll(true); -- skipped'
        ))
        if ([regex]::IsMatch($content, $customStartupPausePattern)) {
            $content = [regex]::Replace($content, $customStartupPausePattern, $customStartupPauseReplacement, 1)
            Write-Host "DEBUG Enable-CmreSavedProfileStartup: CustomStartupBegin pause skipped"
        } elseif ([regex]::IsMatch($content, 'CustomStartupBegin[\s\S]*?API mode \(SkipPause\)', [System.Text.RegularExpressions.RegexOptions]::Singleline)) {
            Write-Host "DEBUG Enable-CmreSavedProfileStartup: CustomStartupBegin already API-patched"
        } else {
            throw "CustomStartupBegin pause anchor not found"
        }

        # SkipPause: 跳过 DevStartupBegin 开头的三个暂停调用（GameSetMissionTimePaused /
        # AITimePause / UnitPauseAll），但保留后续的 commander 设置和
        # CU_CommChoiceEventClosed 事件触发。与 ApiMinimal 的区别：
        # ApiMinimal 在暂停调用处直接 return，跳过所有 commander 设置；
        # SkipPause 只注释掉暂停调用，让函数体继续执行到 commander 设置块。
        # 用于默认 API 模式（-ListenPort > 0）：SC2 不传 -e <map>，停在主菜单。
        # 客户端用 CreateGame + JoinGame 加载地图并推进到 in_game，galaxy 触发器
        # 执行，DevStartupBegin 不暂停游戏，commander 设置完成后发射
        # CU_CommChoiceEventClosed，游戏正常进入 in_game。
        $skipPausePattern = '(?m)^    // Implementation\r?\n    GameSetMissionTimePaused\(true\);\r?\n    AITimePause\(true\);\r?\n    UnitPauseAll\(true\);'
        $skipPauseReplacement = [string]::Join([Environment]::NewLine, @(
            '    // Implementation',
            '    // API mode (SkipPause): skip game pause to allow in_game transition',
            '    // GameSetMissionTimePaused(true); -- skipped',
            '    // AITimePause(true); -- skipped',
            '    // UnitPauseAll(true); -- skipped'
        ))
        if ([regex]::IsMatch($content, $skipPausePattern)) {
            $content = [regex]::Replace($content, $skipPausePattern, $skipPauseReplacement, 1)
            Write-Host "DEBUG Enable-CmreSavedProfileStartup: SkipPause applied (pause calls commented out)"
        } elseif ([regex]::IsMatch($content, 'API mode \(SkipPause\)')) {
            Write-Host "DEBUG Enable-CmreSavedProfileStartup: SkipPause already applied, skipping"
        } else {
            # 检查是否已经被 ApiMinimal patch 过（ApiMinimal 也替换了暂停调用）
            if ([regex]::IsMatch($content, 'ApiMinimal: skip pause')) {
                Write-Host "DEBUG Enable-CmreSavedProfileStartup: ApiMinimal already patched pause calls, SkipPause redundant"
            } else {
                throw "SkipPause pattern not found in libCOOC_gf_CC_DevStartupBegin (expected GameSetMissionTimePaused/AITimePause/UnitPauseAll)"
            }
        }
        # SkipPause mode (API default, non-ApiMinimal): after commander setup, MUST
        # call CMUIX_ReadyBeginCountdown() explicitly. Otherwise CMRE is stuck at
        # selector-unit state (observation: self_units=1, type=4051, hp=1, no
        # abilities, all Actions return NotSupported). ReadyBeginCountdown triggers
        # ReadyCountdownFinishHandler -> CMUIX_FinalApplyLocalLaunchConfiguration
        # + TriggerSendEvent(CMUIX_EVENT_COMMANDER_CHOICE_CLOSED), which lets
        # downstream galaxy triggers spawn real commander units (SCV/CommandCenter/Marine).
        # We do NOT directly TriggerSendEvent because ReadyBeginCountdown also runs
        # FinalApplyLocalLaunchConfiguration (sets Mode/Mission/Enemy/Mutators).
        if (-not $ApiMinimal) {
            $replacementBody += [Environment]::NewLine + '    CMUIX_ReadyBeginCountdown();' + [Environment]::NewLine + '    return ;'
            Write-Host "DEBUG Enable-CmreSavedProfileStartup: SkipPause mode appended CMUIX_ReadyBeginCountdown() + return"
        }
    } elseif ($SkipCountdown) {
        # 黑屏修复（2026-07-28 真因）：CC_DevStartupBegin 中 libCOOC_gf_ShowHideWorldCover(true, ...)
        # 隐藏了世界画面，但 CC_DevStartupFinish 不会在 SkipCountdown 模式下被调用，
        # 导致世界永远被隐藏。在 return ; 之前手动恢复：解除暂停 + 显示世界 + 显示游戏 UI。
        $blackScreenFixInDevStartup = [string]::Join([Environment]::NewLine, @(
            '    // CMRE_PATCH_BLACK_SCREEN_FIX_IN_DEVSTARTUP',
            '    // 恢复世界画面：CC_DevStartupBegin 隐藏了世界，但 DevStartupFinish 不会被调用',
            '    GameSetMissionTimePaused(false);',
            '    AITimePause(false);',
            '    UnitPauseAll(false);',
            '    libCOOC_gf_ShowHideWorldCover(false, 0.0, 1);',
            '    if ((PlayerType(14) == c_playerTypeUser)) {',
            '        libCOOC_gf_ShowHideWorldCover(false, 0.0, 14);',
            '    }',
            '    libNtve_gf_HideGameUI(false, PlayerGroupAll());',
            '    // 黑屏检测：写入对话框可见性到银行文件',
            '    BankLoad("CMRERebornDebug", 1);',
            '    if (DialogIsVisible(libCOOC_gv_cC_WorldCoverDlg, 1)) {',
            '        BankValueSetFromInt(BankLastCreated(), "debug", "world_cover_dialog_visible_p1", 1);',
            '    } else {',
            '        BankValueSetFromInt(BankLastCreated(), "debug", "world_cover_dialog_visible_p1", 0);',
            '    }',
            '    BankValueSetFromInt(BankLastCreated(), "debug", "world_cover_dialog_id", libCOOC_gv_cC_WorldCoverDlg);',
            '    if (GameIsMissionTimePaused()) {',
            '        BankValueSetFromInt(BankLastCreated(), "debug", "game_mission_time_paused", 1);',
            '    } else {',
            '        BankValueSetFromInt(BankLastCreated(), "debug", "game_mission_time_paused", 0);',
            '    }',
            '    BankSave(BankLastCreated());'
        ))
        $replacementBody += [Environment]::NewLine + '    // SkipCountdown (API mode): CMUIX_ReadyBeginCountdown() omitted to avoid Launched-state stall' + [Environment]::NewLine + $blackScreenFixInDevStartup + [Environment]::NewLine + '    return ;'
        Write-Host "DEBUG Enable-CmreSavedProfileStartup: SkipCountdown=true (API mode, no CMUIX_ReadyBeginCountdown) + black screen fix injected"
    } else {
        # This matches CMRE's native saved-profile path. ReadyBeginCountdown commits the
        # empty launcher draft and clears bank-provided Mode=2/3 mutators before game start.
        $replacementBody += [Environment]::NewLine + '    TriggerSendEvent("CU_CommChoiceEventClosed");' + [Environment]::NewLine + '    return ;'
    }
    $replacement = $replacementBody
    Write-Host "DEBUG Enable-CmreSavedProfileStartup: Commander=$Commander"
    Write-Host "DEBUG replacement (first 200 chars): $($replacement.Substring(0, [Math]::Min(200, $replacement.Length)))"
    if ([regex]::IsMatch($content, [regex]::Escape($replacement))) {
        Write-Host "DEBUG: replacement already in content, skipping"
        return
    }
    if ([regex]::IsMatch($content, $startupPattern)) {
        $content = [regex]::Replace($content, $startupPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $startupFallbackPattern)) {
        $content = [regex]::Replace($content, $startupFallbackPattern, $replacement, 1)
    } else {
        throw "CMRE saved-profile startup anchor not found"
    }
    [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "CMRE saved-profile startup patch applied to map: $path"
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

    # 检查是否已 patch（幂等）— 仅控制是否注入 K5Kerrigan 代码块，BOM 剥离总是执行。
    $patchMarker = '// CMRE_PATCH_K5KERRIGAN_SPAWN'
    $alreadyPatched = $content.Contains($patchMarker)

    if (-not $alreadyPatched) {
        # 在 SwarmSetup 触发前注入 K5Kerrigan 创建代码。
        # 为 coop_group 中所有可能的玩家（P1 和 P14）创建 K5Kerrigan，让 CommanderStart
        # 能为每个玩家替换出对应指挥官的特有单位。
        # 使用 Point(0,0) 作为创建位置（地图原点），避免 PlayerStartLocation 在库初始化时不可用。
        # Galaxy 注释必须用纯英文（ASCII），中文注释会导致编译器失败。
        $injectBlock = @"
    // CMRE_PATCH_K5KERRIGAN_SPAWN: create temp K5Kerrigan hero for each coop player
    // so CommanderStart can find and replace it with commander-specific unit.
    // P1 is always in coop_group; P14 is added when PlayerType(14)==c_playerTypeUser.
    libNtve_gf_CreateUnitsWithDefaultFacing(1, "K5Kerrigan", 0, 1, Point(0.0, 0.0));
    if ((PlayerType(14) == c_playerTypeUser)) {
        libNtve_gf_CreateUnitsWithDefaultFacing(1, "K5Kerrigan", 0, 14, Point(0.0, 0.0));
    }
$marker
"@
        $content = $content.Replace($marker, $injectBlock)
        Write-Host "Patch-RebornK5KerriganSpawn: injected K5Kerrigan spawn before SwarmSetup in Lib48DF4533.galaxy"
    } else {
        Write-Host "Patch-RebornK5KerriganSpawn: patch already applied, only ensuring BOM-less encoding"
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

    # V2 patch: use PlayerStartLocation instead of Point(0,0).
    # Root cause: Point(0.0, 0.0) is outside the playable map area on most coop maps (including Dead of Night),
    # so libNtve_gf_CreateUnitsWithDefaultFacing silently fails to create K5Kerrigan. CommanderStart then finds
    # zero K5Kerrigan units and the replacement loop (Abathur→HunterKiller, Raynor→WarPig, etc.) is skipped.
    # PlayerStartLocation(1) returns the player's start point which is always inside the playable area.
    # Also write a debug bank entry so we can verify from runtime evidence that the patch actually executed.
    $injectBlock = @"
    // CMRE_PATCH_K5KERRIGAN_SPAWN_V2: create temp K5Kerrigan hero at player start location
    // (Point(0,0) is outside playable area on most coop maps, causing silent creation failure).
    // Also write debug bank entry to verify patch execution from runtime evidence.
    libNtve_gf_CreateUnitsWithDefaultFacing(1, "K5Kerrigan", 0, 1, PlayerStartLocation(1));
    if ((PlayerType(14) == c_playerTypeUser)) {
        libNtve_gf_CreateUnitsWithDefaultFacing(1, "K5Kerrigan", 0, 14, PlayerStartLocation(14));
    }
    BankLoad("CMRERebornDebug", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "k5kerrigan_patch_ran", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "k5kerrigan_p1_count", UnitGroupCount(UnitGroup("K5Kerrigan", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
    BankSave(BankLastCreated());
$marker
"@
    $content = $content.Replace($marker, $injectBlock)
    Write-Host "Patch-RebornLibraryInit: injected V2 K5Kerrigan spawn (PlayerStartLocation + debug bank) into map copy of Lib48DF4533.galaxy"

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
    if (-not $content.Contains($blackScreenFixMarker)) {
        # 移除旧版注入块（从 CMRE_PATCH_SWARMSETUP_DIRECT_TRIGGER 到 gt_DisableArmySelectPoll_Init();）
        # 保证重新注入最新代码（含黑屏修复）
        $oldPatchPattern = '(?m)^    // CMRE_PATCH_SWARMSETUP_DIRECT_TRIGGER[\s\S]*?    gt_DisableArmySelectPoll_Init\(\);\r?\n'
        $content = [regex]::Replace($content, $oldPatchPattern, '')
        $initLibInjectBlock = @"
    $initLibInjectMarker
    // 直接异步触发 SwarmSetup，绕过 Initialization_Func 中的 Wait 卡死问题。
    // SwarmSetup 会执行 K5Kerrigan spawn + CommanderStart（指挥官单位替换）+ UnitUnlocks。
    // 同时在此直接创建 K5Kerrigan + 写 debug bank，作为 SwarmSetup 是否执行的独立验证。
    // 如果 SwarmSetup 因 trigger 队列问题未执行，这里创建的 K5Kerrigan 仍能被后续
    // CommanderStart（若被触发）替换为指挥官专属单位。
    libNtve_gf_CreateUnitsWithDefaultFacing(1, "K5Kerrigan", 0, 1, PlayerStartLocation(1));
    if ((PlayerType(14) == c_playerTypeUser)) {
        libNtve_gf_CreateUnitsWithDefaultFacing(1, "K5Kerrigan", 0, 14, PlayerStartLocation(14));
    }
    BankLoad("CMRERebornDebug", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "initlib_patch_ran", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "initlib_k5kerrigan_p1_count", UnitGroupCount(UnitGroup("K5Kerrigan", 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 1), c_unitCountAlive));
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
    libNtve_gf_HideGameUI(true, PlayerGroupAll());
    BankLoad("CMRERebornDebug", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "black_screen_fix_ran", 1);
    BankSave(BankLastCreated());
    TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false);
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
    // 1. 只给 1 个初始基地（Hatchery）+ 4 个工蜂，其他建筑和资源由玩家自行发展
    // 2. 验证 HunterKiller 的 5 个 Abathur 特有技能（UnitAbilityExists）
    // 3. 写入深度调试银行作为运行时信源
    // 只对虫族指挥官创建初始基地（Abathur/Dehaka/Izsha/Kerrigan/Naktul/Stukov/Zagara）
    // 非虫族指挥官（Raynor/Mengsk/Tosh/Warfield/Narud/Karass/Urun/Zeratul）跳过
    if ((("$RebornCommander" == "Abathur") || ("$RebornCommander" == "Dehaka") || ("$RebornCommander" == "Izsha") || ("$RebornCommander" == "Kerrigan") || ("$RebornCommander" == "Naktul") || ("$RebornCommander" == "Stukov") || ("$RebornCommander" == "Zagara")) && (PlayerStartLocation(1) != null)) {
        UnitCreate(1, "Hatchery", c_unitCreateIgnorePlacement, 1, PointWithOffset(PlayerStartLocation(1), 0.0, 8.0), 270.0);
        UnitCreate(1, "Drone", c_unitCreateIgnorePlacement, 1, PointWithOffsetPolar(PlayerStartLocation(1), 3.0, 0.0), 270.0);
        UnitCreate(1, "Drone", c_unitCreateIgnorePlacement, 1, PointWithOffsetPolar(PlayerStartLocation(1), 3.0, 90.0), 270.0);
        UnitCreate(1, "Drone", c_unitCreateIgnorePlacement, 1, PointWithOffsetPolar(PlayerStartLocation(1), 3.0, 180.0), 270.0);
        UnitCreate(1, "Drone", c_unitCreateIgnorePlacement, 1, PointWithOffsetPolar(PlayerStartLocation(1), 3.0, 270.0), 270.0);
    }
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
    if (-not ($mapScript -match '(?m)^include "Lib48DF4533"')) {
        $includeMatches = [regex]::Matches($mapScript, '(?m)^[ \t]*include "[^"]+"[^\r\n]*')
        if ($includeMatches.Count -gt 0) {
            $lastInclude = $includeMatches[$includeMatches.Count - 1]
            $insertPos = $lastInclude.Index + $lastInclude.Length
            $newIncludes = "`r`n" + 'include "Lib281DEC45"' + "`r`n" + 'include "Lib48DF4533"'
            $mapScript = $mapScript.Substring(0, $insertPos) + $newIncludes + $mapScript.Substring($insertPos)
            Write-Host "Patch-RebornLibraryInit: injected include ""Lib281DEC45"" + ""Lib48DF4533"" after last existing include"
        } else {
            # 罕见：地图没有 include 语句，在文件开头插入
            $mapScript = 'include "Lib281DEC45"' + "`r`n" + 'include "Lib48DF4533"' + "`r`n" + $mapScript
            Write-Host "Patch-RebornLibraryInit: no existing include found, prepended Lib281DEC45 + Lib48DF4533 at file start"
        }
    }

    # 注入 lib281DEC45_InitLib() 和 lib48DF4533_InitLib() 到 InitLibs() 末尾
    # 顺序：lib281DEC45_InitLib() 必须在 lib48DF4533_InitLib() 之前（依赖关系）
    if (-not ($mapScript -match 'lib48DF4533_InitLib\s*\(\s*\)')) {
        $initLibsPattern = '(?s)void InitLibs \(\) \{(.*?)\}'
        $initLibsMatch = [regex]::Match($mapScript, $initLibsPattern)
        if (-not $initLibsMatch.Success) {
            throw "Patch-RebornLibraryInit: InitLibs() function not found in MapScript.galaxy"
        }
        $initLibsBody = $initLibsMatch.Groups[1].Value
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
    } elseif (-not ($mapScript -match 'lib281DEC45_InitLib\s*\(\s*\)')) {
        # lib48DF4533_InitLib 已注入但 lib281DEC45_InitLib 缺失，补上
        $mapScript = $mapScript -replace '(    lib48DF4533_InitLib\(\);)', '    lib281DEC45_InitLib();' + "`r`n" + '$1'
        Write-Host "Patch-RebornLibraryInit: added missing lib281DEC45_InitLib() before lib48DF4533_InitLib()"
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

    Write-Host "DEBUG Install-CmreDynamicObserver: isAlengerCommander=$isAlengerCommander alengerId=$alengerId MapPath=$MapPath"

    $neuroRoot = Join-Path $WorkspaceRoot "reference\SC2-Neuro-API-Integration"
    $observerRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\runtime"
    $adapterRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\adapters\dead-of-night"
    $baseData = Join-Path $MapPath "Base.SC2Data"
    $files = @(
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406_h.galaxy"; Name = "LibEFA54406_h.galaxy" },
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406.galaxy"; Name = "LibEFA54406.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver_h.galaxy"; Name = "LibPortingObserver_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver.galaxy"; Name = "LibPortingObserver.galaxy" },
        @{ Source = Join-Path $observerRoot "LibNeuroCommandBridge_h.galaxy"; Name = "LibNeuroCommandBridge_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibNeuroCommandBridge.galaxy"; Name = "LibNeuroCommandBridge.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver_h.galaxy"; Name = "LibDeadOfNightObserver_h.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver.galaxy"; Name = "LibDeadOfNightObserver.galaxy" }
    )
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath $file.Source)) { throw "Observer input not found: $($file.Source)" }
        [System.IO.File]::Copy($file.Source, (Join-Path $baseData $file.Name), $true)
    }

    $efaPath = Join-Path $baseData "LibEFA54406.galaxy"
    $efa = [System.IO.File]::ReadAllText($efaPath, [System.Text.Encoding]::UTF8)
    if ($efa -notmatch '(?m)^include "LibPortingObserver_h"$') {
        $efa = $efa.Replace('include "LibEFA54406_h"', "include `"LibEFA54406_h`"`r`ninclude `"LibPortingObserver_h`"")
    }
    $actionAnchor = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + "`r`n    return true;"
    $actionPatch = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + "`r`n    libEFA54406_gf_BootstrapPortingObserver();`r`n    return true;"
    if ($efa.Contains($actionAnchor)) { $efa = $efa.Replace($actionAnchor, $actionPatch) }
    # The integration library's legacy color conversion is rejected by this CMRE runtime.
    # Keep the upstream text while omitting only that incompatible conversion in the live copy.
    $legacyColorCall = '            libEFA54406_gv_displayNameText = TextWithColor(libEFA54406_gv_displayNameText, Color(100.00, 50.20, 75.29));'
    if ($efa.Contains($legacyColorCall)) {
        $efa = $efa.Replace($legacyColorCall, '            // CMRE adapter: display text retained without incompatible color conversion.')
    }
    # CMRE fix: upstream Executeactionsglobal_Func sets bankwriteallowed=false at
    # entry (line 351) but never resets it to true. Every other bank-writing
    # function in this library follows the pattern set-false -> work -> set-true,
    # but Executeactionsglobal_Func omits the final set-true. This permanently
    # blocks all subsequent create_context Publish calls (they spin on
    # while(bankwriteallowed==false) Wait(...)). The bug manifests as:
    #   - execute_actions_fired key never appears in Bank
    #   - alenger_unit_presence stuck at bootstrap-time values (commander_p1 empty)
    #   - player_*_inventory never written
    # Reset the semaphore after the map event handlers return.
    $execMapAnchor = '    BankSave(BankLastCreated());' + "`r`n" +
                     '    Wait(0.1, c_timeReal);' + "`r`n" +
                     '    TriggerSendEvent("execute_actions_map");' + "`r`n" +
                     '    return true;'
    $execMapPatch = '    BankSave(BankLastCreated());' + "`r`n" +
                    '    Wait(0.1, c_timeReal);' + "`r`n" +
                    '    TriggerSendEvent("execute_actions_map");' + "`r`n" +
                    '    libEFA54406_gv_bankwriteallowed = true;' + "`r`n" +
                    '    return true;'
    if ($efa.Contains($execMapAnchor)) {
        $efa = $efa.Replace($execMapAnchor, $execMapPatch)
    }
    [System.IO.File]::WriteAllText($efaPath, $efa, [System.Text.UTF8Encoding]::new($false))

    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    $mapScript = [System.IO.File]::ReadAllText($mapScriptPath, [System.Text.Encoding]::UTF8)
    # 参数化 include 和 InitLib：当 adapterFiles 为空或非Alenger指挥官时不注入 adapter 库引用
    $adapterInclude = ''
    $adapterInitLib = ''
    if ($isAlengerCommander -and $adapterFiles.Count -gt 0 -and $adapterLibPrefix) {
        $adapterInclude = "`r`n" + 'include "Lib' + $adapterLibPrefix + '"'
        $adapterInitLib = "`r`n" + '    lib' + $adapterLibPrefix + '_InitLib();'
    }
    if ($mapScript -notmatch '(?m)^include "LibEFA54406"$') {
        $incReplacement = 'include "LibCOUI"' + "`r`n" + 'include "LibEFA54406"' + "`r`n" + 'include "LibNeuroCommandBridge"' + "`r`n" + 'include "LibPortingObserver"' + $adapterInclude
        $mapScript = $mapScript.Replace('include "LibCOUI"', $incReplacement)
    }
    if (-not $mapScript.Contains('include "LibNeuroCommandBridge"')) {
        $mapScript = $mapScript.Replace('include "LibEFA54406"', 'include "LibEFA54406"' + "`r`n" + 'include "LibNeuroCommandBridge"')
    }
    if ($mapScript -notmatch 'libEFA54406_InitLib\s*\(\s*\)') {
        $initReplacement = '    libCOUI_InitLib();' + "`r`n" + '    libEFA54406_InitLib();' + "`r`n" + '    libNeuroCommandBridge_InitLib();' + $adapterInitLib
        $mapScript = $mapScript.Replace('    libCOUI_InitLib();', $initReplacement)
    }
    if ($mapScript -notmatch 'libNeuroCommandBridge_InitLib\s*\(\s*\)') {
        $mapScript = $mapScript.Replace('    libEFA54406_InitLib();', '    libEFA54406_InitLib();' + "`r`n" + '    libNeuroCommandBridge_InitLib();')
    }
    # LibDeadOfNightObserver 必须在文件开头的 include 块中（Galaxy 语法要求 include 在所有声明之前）。
    # 之前把它放在 pollGlue 中（Map Initialization 注释前），那个位置在函数定义之后，
    # 导致 Galaxy 编译器报 "函数已声明但尚未定义" 错误（include 在文件中间被忽略，
    # libDeadOfNightObserver_gf_Update / libDeadOfNightObserver_InitLib 等库函数无法解析）。
    if ($mapScript -notmatch '(?m)^include "LibDeadOfNightObserver"$') {
        $donIncReplacement = 'include "LibPortingObserver"' + "`r`n" + 'include "LibDeadOfNightObserver"'
        $mapScript = $mapScript.Replace('include "LibPortingObserver"', $donIncReplacement)
    }
    if ($mapScript -notmatch 'gt_PortingObserverDeadOfNightPoll_Func') {
        $mapInitAnchor = "//--------------------------------------------------------------------------------------------------`r`n// Map Initialization"
        if (-not $mapScript.Contains($mapInitAnchor)) { throw "Map initialization anchor not found in MapScript" }
        # 亡者之夜专用代码块：引用 gv_dayORNight/gv_nightNumber/gv_objective_Primary_DestroyInfestation
        # 等亡者之夜特有的全局变量。其他地图（如克哈裂痕）没有这些变量，注入会导致编译崩溃。
        # 只在亡者之夜地图注入这段代码；其他地图用空字符串占位，保持 poll trigger 通用部分可用。
        $donUpdateBlock = ''
        if ($MapName -eq "亡者之夜.SC2Map") {
            $donUpdateBlock = @'
        if (gv_objective_Primary_DestroyInfestation != c_invalidObjectiveId) {
            lv_primaryState = ObjectiveGetState(gv_objective_Primary_DestroyInfestation);
        }
        if (gv_objective_Bonus_DestroyInfestationSource != c_invalidObjectiveId) {
            lv_bonusState = ObjectiveGetState(gv_objective_Bonus_DestroyInfestationSource);
        }
        libDeadOfNightObserver_gf_Update(gv_dayORNight, gv_nightNumber,
            gv_infestedStructuresRemaining, gv_infestedStructuresTotal, lv_primaryState, lv_bonusState);
'@
        }
        if ($isAlengerCommander) {
            $pollGlue = @"
trigger gt_PortingObserverDeadOfNightPoll;
trigger gt_${alengerId}StartingUnits;

bool gt_PortingObserverDeadOfNightPoll_Func(bool testConds, bool runActions) {
    int lv_primaryState = -1;
    int lv_bonusState = -1;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    libPortingObserver_gf_Publish("poll_trigger_started", "DeadOfNight poll trigger is running", false);
    Wait(10.0, c_timeReal);
    while (true) {
${donUpdateBlock}
        libPortingObserver_gf_PublishAlengerPresenceProbe();
        Wait(1.0, c_timeReal);
        libPortingObserver_gf_PublishAlengerStructureProbe();
        Wait(1.0, c_timeReal);
        libPortingObserver_gf_PublishAlengerCommandCardDump();
        Wait(1.0, c_timeReal);
        libPortingObserver_gf_PublishAlengerWorkerBuildDump();
        Wait(1.0, c_timeReal);
        // Generic per-player inventory probe (does not hardcode any commander-specific unit IDs).
        // Outputs "player_N_inventory" bank keys listing every unit type + count on the map for player N.
        // This is the primary evidence for verifying Reborn commander SwarmSetup actually produced
        // the expected Reborn-specific units/buildings.
        libPortingObserver_gf_PublishPlayerInventory(1);
        Wait(1.0, c_timeReal);
        libPortingObserver_gf_PublishPlayerInventory(2);
        Wait(7.0, c_timeReal);
    }
    return true;
}

void gt_PortingObserverDeadOfNightPoll_Init() {
    gt_PortingObserverDeadOfNightPoll = TriggerCreate("gt_PortingObserverDeadOfNightPoll_Func");
    TriggerExecute(gt_PortingObserverDeadOfNightPoll, false, true);
}

int gf_RemoveAllUnitsOfType(int lp_player, string lp_type) {
    unitgroup lv_units;
    int lv_count;
    int lv_i;
    if (lp_type == "") { return 0; }
    if (!CatalogEntryIsValid(c_gameCatalogUnit, lp_type)) { return 0; }
    lv_units = UnitGroup(lp_type, lp_player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_count = UnitGroupCount(lv_units, c_unitCountAll);
    for (lv_i = lv_count; lv_i >= 1; lv_i -= 1) {
        UnitRemove(UnitGroupUnit(lv_units, lv_i));
    }
    return lv_count;
}

bool gt_${alengerId}StartingUnits_Func(bool testConds, bool runActions) {
    point lv_p1Start = null;
    point lv_p2Start = null;
    int lv_i = 0;
    unitgroup lv_beforeP1 = UnitGroupEmpty();
    unitgroup lv_afterP1 = UnitGroupEmpty();
    unitgroup lv_beforeP2 = UnitGroupEmpty();
    unitgroup lv_afterP2 = UnitGroupEmpty();
    int lv_beforeCount = 0;
    int lv_createdP1 = 0;
    int lv_createdP2 = 0;
    string lv_diag = "";
    string lv_p1Valid = "F";
    string lv_p2Valid = "F";
    int lv_removedP1 = 0;
    int lv_removedP2 = 0;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    libPortingObserver_gf_Publish("alenger_starting_units_begin", "creating Alenger starting units", false);
    Wait(5.0, c_timeReal);
    lv_p1Start = PlayerStartLocation(1);
    lv_p2Start = PlayerStartLocation(2);
    if (lv_p1Start != null) { lv_p1Valid = "T"; }
    if (lv_p2Start != null) { lv_p2Valid = "T"; }
"@
            $vanillaRemoveBlockP1 = ""
            foreach ($u in $vanillaRemovals) {
                $vanillaRemoveBlockP1 += "    lv_removedP1 += gf_RemoveAllUnitsOfType(1, `"$u`");`r`n"
            }
            $vanillaRemoveBlockP2 = ""
            foreach ($u in $vanillaRemovals) {
                $vanillaRemoveBlockP2 += "    lv_removedP2 += gf_RemoveAllUnitsOfType(2, `"$u`");`r`n"
            }
            $pollGlue += $vanillaRemoveBlockP1 + $vanillaRemoveBlockP2
            $pollGlue += @"
    lv_beforeP1 = UnitGroup("$startingStructure", 1, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_beforeCount = UnitGroupCount(lv_beforeP1, c_unitCountAll);
    if (lv_p1Start != null) {
        UnitCreate(1, "$startingStructure", c_unitCreateIgnorePlacement, 1, lv_p1Start, 270.0);
        for (lv_i = 0; lv_i < $workerCount; lv_i += 1) {
            UnitCreate(1, "$startingWorker", c_unitCreateIgnorePlacement, 1,
                PointWithOffsetPolar(lv_p1Start, 3.0, (IntToFixed(lv_i) * 72.0)), 270.0);
        }
    }
    lv_afterP1 = UnitGroup("$startingStructure", 1, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_createdP1 = UnitGroupCount(lv_afterP1, c_unitCountAll) - lv_beforeCount;
    lv_beforeP2 = UnitGroup("$startingStructure", 2, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_beforeCount = UnitGroupCount(lv_beforeP2, c_unitCountAll);
    if (lv_p2Start != null) {
        UnitCreate(1, "$startingStructure", c_unitCreateIgnorePlacement, 2, lv_p2Start, 270.0);
        for (lv_i = 0; lv_i < $workerCount; lv_i += 1) {
            UnitCreate(1, "$startingWorker", c_unitCreateIgnorePlacement, 2,
                PointWithOffsetPolar(lv_p2Start, 3.0, (IntToFixed(lv_i) * 72.0)), 270.0);
        }
    }
    lv_afterP2 = UnitGroup("$startingStructure", 2, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_createdP2 = UnitGroupCount(lv_afterP2, c_unitCountAll) - lv_beforeCount;
    lv_diag = "p1_start=" + lv_p1Valid + "; p2_start=" + lv_p2Valid +
        "; created_p1=" + IntToString(lv_createdP1) + "; created_p2=" + IntToString(lv_createdP2) +
        "; after_p1=" + IntToString(UnitGroupCount(lv_afterP1, c_unitCountAll)) +
        "; after_p2=" + IntToString(UnitGroupCount(lv_afterP2, c_unitCountAll)) +
        "; removed_vanilla_p1=" + IntToString(lv_removedP1) +
        "; removed_vanilla_p2=" + IntToString(lv_removedP2);
    libPortingObserver_gf_Publish("alenger_starting_units_done", lv_diag, false);
    return true;
}

void gt_${alengerId}StartingUnits_Init() {
    gt_${alengerId}StartingUnits = TriggerCreate("gt_${alengerId}StartingUnits_Func");
    TriggerExecute(gt_${alengerId}StartingUnits, false, true);
}

trigger gt_${alengerId}TrainProbe;

bool gt_${alengerId}TrainProbe_Func(bool testConds, bool runActions) {
    string lv_structureType = "$startingStructure";
    string lv_workerType = "$startingWorker";
    unitgroup lv_structs = null;
    unitgroup lv_workers = null;
    int lv_workerBefore = 0;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    libPortingObserver_gf_Publish("alenger_train_probe_begin", "starting train completion probe", false);
    Wait(25.0, c_timeReal);
    lv_structs = UnitGroup(lv_structureType, c_playerAny, RegionEntireMap(),
        UnitFilter(0, 0, 0, (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    if (UnitGroupCount(lv_structs, c_unitCountAll) == 0) {
        libPortingObserver_gf_Publish("alenger_train_probe_result", "no_producer; worker_before=0; worker_after=0; new_workers=0; train_completed=false", false);
        return true;
    }
    lv_workers = UnitGroup(lv_workerType, c_playerAny, RegionEntireMap(),
        UnitFilter(0, 0, 0, (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_workerBefore = UnitGroupCount(lv_workers, c_unitCountAll);
    libPortingObserver_gf_Publish("alenger_train_probe_result",
        "train_ability_placeholder; worker_before=" + IntToString(lv_workerBefore) + "; train_completed=false(diag_skip)", false);
    return true;
}

void gt_${alengerId}TrainProbe_Init() {
    gt_${alengerId}TrainProbe = TriggerCreate("gt_${alengerId}TrainProbe_Func");
    TriggerExecute(gt_${alengerId}TrainProbe, false, true);
}

"@
        } else {
            $pollGlue = @"
trigger gt_PortingObserverDeadOfNightPoll;

bool gt_PortingObserverDeadOfNightPoll_Func(bool testConds, bool runActions) {
    int lv_primaryState = -1;
    int lv_bonusState = -1;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    libPortingObserver_gf_Publish("poll_trigger_started", "DeadOfNight poll trigger is running", false);
    Wait(10.0, c_timeReal);
    while (true) {
${donUpdateBlock}
        Wait(10.0, c_timeReal);
    }
    return true;
}

void gt_PortingObserverDeadOfNightPoll_Init() {
    gt_PortingObserverDeadOfNightPoll = TriggerCreate("gt_PortingObserverDeadOfNightPoll_Func");
    TriggerExecute(gt_PortingObserverDeadOfNightPoll, false, true);
}

"@
        }
        $mapScript = $mapScript.Replace($mapInitAnchor, $pollGlue.Replace("`n", "`r`n") + $mapInitAnchor)
    }
    if ($mapScript -notmatch 'libDeadOfNightObserver_InitLib\s*\(\s*\)') {
        $initAnchor = "    InitTriggers();`r`n"
        if (-not $mapScript.Contains($initAnchor)) { throw "InitMap anchor not found in MapScript" }
        if ($isAlengerCommander) {
            $initMapReplacement = "    libDeadOfNightObserver_InitLib();`r`n    gt_PortingObserverDeadOfNightPoll_Init();`r`n    gt_${alengerId}StartingUnits_Init();`r`n    gt_${alengerId}TrainProbe_Init();`r`n" + $initAnchor
        } else {
            $initMapReplacement = "    libDeadOfNightObserver_InitLib();`r`n    gt_PortingObserverDeadOfNightPoll_Init();`r`n" + $initAnchor
        }
        $mapScript = $mapScript.Replace($initAnchor, $initMapReplacement)
    }
    [System.IO.File]::WriteAllText($mapScriptPath, $mapScript, [System.Text.UTF8Encoding]::new($false))

    $bankListPath = Join-Path $MapPath "BankList.xml"
    [xml]$bankList = [System.IO.File]::ReadAllText($bankListPath, [System.Text.Encoding]::UTF8)
    $bankChanged = $false
    if (@($bankList.BankList.Bank | Where-Object { $_.Name -eq "NeuroIntegration" -and $_.Player -eq "1" }).Count -eq 0) {
        $bank = $bankList.CreateElement("Bank")
        $bank.SetAttribute("Name", "NeuroIntegration")
        $bank.SetAttribute("Player", "1")
        $bankList.BankList.AppendChild($bank) | Out-Null
        $bankChanged = $true
    }
    # RuntimeProbe Bank registration intentionally omitted: RuntimeProbe is
    # deprecated as runtime evidence (see docs/deprecated-runtime-probe.md).
    if ($bankChanged) {
        $settings = [System.Xml.XmlWriterSettings]::new(); $settings.Indent = $true; $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
        $writer = [System.Xml.XmlWriter]::Create($bankListPath, $settings)
        try { $bankList.Save($writer) } finally { $writer.Dispose() }
    }
}

function Patch-CmreCoreRuntimeErrors {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    # CMRE-ALENGER3-RUNTIME-002: 6 classes of non-fatal runtime errors in
    # LibCOTF.galaxy, LibCOUI.galaxy and LibCOMI.galaxy. CMRE core assumes
    # fully configured commander data (decal, revive behavior, shield color,
    # AI vision dialog, gameUser for player 2) but the 5-dep Alenger3
    # composition does not populate all of these fields. Patches add defensive
    # guards / fallbacks to suppress ScriptError noise. Idempotent: skips
    # anchors that already contain the patch marker.

    $baseData = Join-Path $MapPath "Base.SC2Data"
    $patchCount = 0

    # --- LibCOTF.galaxy patches ---
    $cotfPath = Join-Path $baseData "LibCOTF.galaxy"
    if (-not (Test-Path -LiteralPath $cotfPath)) { throw "LibCOTF.galaxy not found: $cotfPath" }
    $cotf = [System.IO.File]::ReadAllText($cotfPath, [System.Text.Encoding]::UTF8)

    # Patch 1: line 176 - EventPlayerEffectUsedUnitOwner has no effect event in InitGlobals context
    $cotfAnchor1 = '    libCOTF_gv_player = EventPlayerEffectUsedUnitOwner(c_effectPlayerCaster);'
    $cotfPatch1 = '    libCOTF_gv_player = 1; // CMRE patch: InitGlobals has no effect event context'
    if (-not $cotf.Contains($cotfPatch1)) {
        if (-not $cotf.Contains($cotfAnchor1)) { throw "LibCOTF patch 1 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor1, $cotfPatch1); $patchCount++
    }

    # Patch 2: line 7828 - PlayerHandle returns non-numeric string; StringToInt fails.
    # Line 7829 also fails (DateTimeToString returns non-numeric string).
    # Both lines are redundant: the while loop at line 7830 provides continuous
    # random seeds via RandomInt. Comment out both lines to suppress ScriptError.
    $cotfAnchor2 = '    GameSetSeed(StringToInt((PlayerHandle(1) + PlayerHandle(2))));'
    $cotfPatch2 = '    // CMRE patch: skip PlayerHandle-based seed (StringToInt cannot parse handle string)'
    if (-not $cotf.Contains($cotfPatch2)) {
        if (-not $cotf.Contains($cotfAnchor2)) { throw "LibCOTF patch 2 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor2, $cotfPatch2); $patchCount++
    }

    # Patch 2b: line 7829 - DateTimeToString returns non-numeric string; StringToInt fails.
    $cotfAnchor2b = '    GameSetSeed(StringToInt(DateTimeToString(CurrentDateTimeGet())));'
    $cotfPatch2b = '    // CMRE patch: skip DateTime-based seed (StringToInt cannot parse datetime string; while loop below provides continuous random seed)'
    if (-not $cotf.Contains($cotfPatch2b)) {
        if (-not $cotf.Contains($cotfAnchor2b)) { throw "LibCOTF patch 2b anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor2b, $cotfPatch2b); $patchCount++
    }

    # Patch 3: line 7959 - DialogSetVisible with invalid dialog handle
    $cotfAnchor3 = '    DialogSetVisible(libCOTF_gv_uT_AIVisionDialog, PlayerGroupAll(), false);'
    $cotfPatch3 = '    if (libCOTF_gv_uT_AIVisionDialog != c_invalidDialogId) { DialogSetVisible(libCOTF_gv_uT_AIVisionDialog, PlayerGroupAll(), false); } // CMRE patch: guard invalid dialog handle'
    if (-not $cotf.Contains($cotfPatch3)) {
        if (-not $cotf.Contains($cotfAnchor3)) { throw "LibCOTF patch 3 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor3, $cotfPatch3); $patchCount++
    }

    [System.IO.File]::WriteAllText($cotfPath, $cotf, [System.Text.UTF8Encoding]::new($false))

    # --- LibCOUI.galaxy patches ---
    $couiPath = Join-Path $baseData "LibCOUI.galaxy"
    if (-not (Test-Path -LiteralPath $couiPath)) { throw "LibCOUI.galaxy not found: $couiPath" }
    $coui = [System.IO.File]::ReadAllText($couiPath, [System.Text.Encoding]::UTF8)

    # Patch 4: line 3306 - SetDialogItemUnitGroup with invalid control handle
    $couiAnchor4 = '    libNtve_gf_SetDialogItemUnitGroup(libCOUI_gv_cU_GPCmdPanel[lp_player], libCOUI_gv_cU_GPCasterGroup[lp_player], PlayerGroupSingle(lp_player));'
    $couiPatch4 = '    if (libCOUI_gv_cU_GPCmdPanel[lp_player] != c_invalidDialogControlId) { libNtve_gf_SetDialogItemUnitGroup(libCOUI_gv_cU_GPCmdPanel[lp_player], libCOUI_gv_cU_GPCasterGroup[lp_player], PlayerGroupSingle(lp_player)); } // CMRE patch: guard invalid control handle'
    if (-not $coui.Contains($couiPatch4)) {
        if (-not $coui.Contains($couiAnchor4)) { throw "LibCOUI patch 4 anchor not found" }
        $coui = $coui.Replace($couiAnchor4, $couiPatch4); $patchCount++
    }

    [System.IO.File]::WriteAllText($couiPath, $coui, [System.Text.UTF8Encoding]::new($false))

    # --- LibCOMI.galaxy patches ---
    $comiPath = Join-Path $baseData "LibCOMI.galaxy"
    if (-not (Test-Path -LiteralPath $comiPath)) { throw "LibCOMI.galaxy not found: $comiPath" }
    $comi = [System.IO.File]::ReadAllText($comiPath, [System.Text.Encoding]::UTF8)

    # Patch 5+6: lines 23813 and 23851 - CatalogFieldValueGet with empty decal entry (same anchor, replaces both)
    $comiAnchor5 = '    lv_commanderDefaultDecalString = CatalogFieldValueGet(c_gameCatalogTexture, lv_commanderDefaultDecal, "File", c_playerAny);'
    $comiPatch5 = '    if (lv_commanderDefaultDecal != "") { lv_commanderDefaultDecalString = CatalogFieldValueGet(c_gameCatalogTexture, lv_commanderDefaultDecal, "File", c_playerAny); } // CMRE patch: guard empty decal entry'
    if (-not $comi.Contains($comiPatch5)) {
        if (-not $comi.Contains($comiAnchor5)) { throw "LibCOMI patch 5 anchor not found" }
        $comi = $comi.Replace($comiAnchor5, $comiPatch5); $patchCount += 2
    }

    # Patch 7: line 18204 - CatalogFieldValueGet fails when NormalRevive behavior is empty.
    # Guard the call itself (not just the fallback) to suppress ScriptError at the source.
    $comiAnchor7 = '    lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player), "Duration", lp_player));'
    $comiPatch7 = '    if (libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player) != "") { lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player), "Duration", lp_player)); } if (lv_reviveDuration <= 0.0) { lv_reviveDuration = 60.0; } // CMRE patch: guard empty normal revive behavior entry'
    if (-not $comi.Contains($comiPatch7)) {
        if (-not $comi.Contains($comiAnchor7)) { throw "LibCOMI patch 7 anchor not found" }
        $comi = $comi.Replace($comiAnchor7, $comiPatch7); $patchCount++
    }

    # Patch 8: line 18244 - CatalogFieldValueGet fails when FirstRevive behavior is empty.
    # Guard the call itself (not just the fallback) to suppress ScriptError at the source.
    $comiAnchor8 = '    lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player), "Duration", lp_player));'
    $comiPatch8 = '    if (libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player) != "") { lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player), "Duration", lp_player)); } if (lv_reviveDuration <= 0.0) { lv_reviveDuration = 60.0; } // CMRE patch: guard empty first revive behavior entry'
    if (-not $comi.Contains($comiPatch8)) {
        if (-not $comi.Contains($comiAnchor8)) { throw "LibCOMI patch 8 anchor not found" }
        $comi = $comi.Replace($comiAnchor8, $comiPatch8); $patchCount++
    }

    # Patch 9: line 18259 - divide-by-zero when lv_reviveDuration is 0
    $comiAnchor9 = '    UnitSetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeRegen, (UnitGetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeMax, c_unitPropCurrent)/lv_reviveDuration));'
    $comiPatch9 = '    if (lv_reviveDuration > 0.0) { UnitSetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeRegen, (UnitGetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeMax, c_unitPropCurrent)/lv_reviveDuration)); } // CMRE patch: guard divide-by-zero'
    if (-not $comi.Contains($comiPatch9)) {
        if (-not $comi.Contains($comiAnchor9)) { throw "LibCOMI patch 9 anchor not found" }
        $comi = $comi.Replace($comiAnchor9, $comiPatch9); $patchCount++
    }

    # Patch 10: CM_HeroWaitForRevive_TriggerFunc 在无英雄指挥官（如 Alenger）时
    # libCOMI_gv_cM_HeroReviver[lp_player] 为 null，执行到 UnitGetPosition 会抛
    # "无法从参数中获取 unit(0#0)" 致命错误。无英雄复活单位则直接跳过复活逻辑。
    # 注意：Galaxy 不允许在局部变量声明之前出现可执行语句，故 guard 必须放在
    # 变量声明之后。锚点用 autoE01594B5_var（该触发器函数独有的自动变量）保证
    # 只命中 CM_HeroWaitForRevive_TriggerFunc，避免误注入到其他函数（如复活时长计算）。
    # 用正则容忍声明之间的空行数量差异。
    $comiAnchor10 = 'unit autoE01594B5_var;[\s\S]*?lv_commander = libCOOC_gf_ActiveCommanderForPlayer\(lp_player\);'
    $comiPatch10 = 'unit autoE01594B5_var;' + "`r`n" + "`r`n" + `
        '    // CMRE patch: 无英雄指挥官（如 Alenger）的 cM_HeroReviver 为 null，跳过复活逻辑' + "`r`n" + `
        '    if (libCOMI_gv_cM_HeroReviver[lp_player] == null) { return true; }' + "`r`n" + `
        '    lv_commander = libCOOC_gf_ActiveCommanderForPlayer(lp_player);'
    if (-not $comi.Contains($comiPatch10)) {
        if (-not [regex]::IsMatch($comi, $comiAnchor10)) { throw "LibCOMI patch 10 anchor not found" }
        $comi = [regex]::Replace($comi, $comiAnchor10, $comiPatch10)
        $patchCount++
    }

    # Patch 11: libCOMI_gf_CM_CommanderVOSend - 当 lp_vOSound 为 null（指挥官未配置
    # VO lines，如 Alenger6）时，SoundPlayForPlayer 会抛 "无法从'sCreateSound'的参数中
    # 获取'sound'(值：0)" 触发器错误。跳过 null soundlink 的播放，避免运行时错误。
    # 该错误在克哈裂痕等地图上单位被攻击时立即触发（libCOMI_gt_CM_VOEnemySpotted_Func）。
    $comiAnchor11 = 'void libCOMI_gf_CM_CommanderVOSend (int lp_listenerPlayer, soundlink lp_vOSound, playergroup lp_targetPlayers) {
    // Automatic Variable Declarations
    // Implementation
    SoundSetListenerGender(lp_vOSound, libCOOC_gf_CC_CommanderGender(libCOOC_gf_ActiveCommanderForPlayer(lp_listenerPlayer)));'
    $comiPatch11 = 'void libCOMI_gf_CM_CommanderVOSend (int lp_listenerPlayer, soundlink lp_vOSound, playergroup lp_targetPlayers) {
    // Automatic Variable Declarations
    // Implementation
    if ((lp_vOSound == null)) { return; } // CMRE patch: guard null soundlink (VO line not configured for this commander)
    SoundSetListenerGender(lp_vOSound, libCOOC_gf_CC_CommanderGender(libCOOC_gf_ActiveCommanderForPlayer(lp_listenerPlayer)));'
    if (-not $comi.Contains($comiPatch11)) {
        if (-not $comi.Contains($comiAnchor11)) { throw "LibCOMI patch 11 anchor not found" }
        $comi = $comi.Replace($comiAnchor11, $comiPatch11); $patchCount++
    }

    [System.IO.File]::WriteAllText($comiPath, $comi, [System.Text.UTF8Encoding]::new($false))

    Write-Host "CMRE core runtime error patches applied: $patchCount locations"
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
        'Player|2|Commander' = @("string", $Commander)
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

$lock = Acquire-TestLock -TestType "cmre_alenger" -MapName $MapName -Commander $Commander
$debugPidFile = Join-Path $env:TEMP "cmre-debug-sc2.pid"
try {
    if ($PlayerMode) {
        # PlayerMode：不清理任何 SC2 进程，避免杀玩家游戏。已有 SC2 在跑则报错退出。
        $existing = Get-Process -Name "SC2_x64","SC2","StarCraft II" -ErrorAction SilentlyContinue
        if ($existing) {
            throw "检测到 SC2 已在运行（PID: $($existing.Id -join ',')）。PlayerMode 不会自动关闭已有游戏，请先手动关闭 SC2 再启动。"
        }
        # 无 SC2 运行时清理 GameLogs，避免旧 Alerts.txt 被 wait-for-game-ready.ps1 误判为加载完成信号
        Clear-GameLogs
    } elseif ($DebugMode) {
        # DebugMode：只清理自己上次启动的 SC2（按 PID 文件，禁止按进程名 kill 避免误杀玩家游戏）
        if (Test-Path $debugPidFile) {
            $oldPid = Get-Content $debugPidFile -ErrorAction SilentlyContinue
            if ($oldPid) {
                Write-Host "DebugMode: 清理上次调试启动的 SC2 (PID=$oldPid)"
                Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
            }
            Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep 2
        Clear-GameLogs
    } else {
        # 命令行手动启动（都不传）：走原有全量清理逻辑
        Stop-RunningSc2
        # Stop-RunningSc2 only targets SC2_x64/SC2Switcher_x64, but the live process
        # is often named "SC2". Stop it as well so Clear-GameLogs does not hit locked
        # SystemInfo.txt (which causes the launcher to abort with IOException).
        Get-Process -Name "SC2","StarCraft II" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep 2
        Clear-GameLogs
    }
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
    if ($ShowSelectionUI) {
        # ShowSelectionUI: 不 patch LibCOOC.galaxy，保留 CMRE 原生启动流程。
        # 地图加载后会显示指挥官选择界面，用户可以手动选择指挥官和因子。
        Write-Host "CMRE ShowSelectionUI: skipping saved-profile startup patch, selection UI will be shown"
    } elseif ($ApiMinimal) {
        # ApiMinimal: 跳过所有 galaxy 状态干预（commander 设置 + countdown），让 SC2 通过
        # API CreateGame+JoinGame 正常从 init_game → in_game。Alenger6 mod catalog 仍通过
        # mod 依赖加载，P11 catalog 验证可用。
        Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -ApiMinimal
    } elseif ($SkipCountdown) {
        # 显式 SkipCountdown：跳过 CMUIX_ReadyBeginCountdown()，客户端用 CreateGame+JoinGame 推进状态。
        Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -SkipCountdown
    } else {
        # 默认模式（含 -ListenPort > 0 的 API 模式）：注入 commander 设置 +
        # CU_CommChoiceEventClosed 事件，让 galaxy 触发器自动把 SC2 从 Launched
        # 推进到 in_game。客户端用 CreateGame + JoinGame 连接。
        # 之前把 -ListenPort > 0 合并到 SkipCountdown 分支是错误的：ReadyBeginCountdown 被跳过
        # 导致 SC2 永远卡在 Launched，GameInfo/Step 全部报 "Not in a game"。
        # 2026-07-25 修复：API 模式（-ListenPort > 0）加 -SkipPause，跳过
        # DevStartupBegin 开头的 GameSetMissionTimePaused/AITimePause/UnitPauseAll，
        # 这三个调用会把游戏暂停，但不会影响 API 状态（状态由 CreateGame/JoinGame 控制）。
        if ($ListenPort -gt 0) {
            # API 模式：P1 和 P2 都设置指挥官（CMRE 正常逻辑）。
            # CMRE galaxy 触发器强制 P1=Participant（API 加入位置），P2=Computer（AI 队友）。
            # API 以 P1 身份加入，操作 P1 的指挥官单位（type_4390/4386 CC / type_4382 SCV）。
            # 这才是 CMRE 的"玩家队友"角色——有指挥官的单位，而非 vanilla 单位。
            # ability ID 使用 CMRE 自定义值（17428/17514 训练 SCV，16/17/18 建造建筑）。
            Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander -SkipPause
        } else {
            Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander
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
    try {
        Set-CampaignXCorePrimaryCommander -SelectedCommanders @($Commander)
        Set-CampaignXCoreTestRunId -RunId "CMREAlenger"
    } catch {
        Write-Host "WARN: CampaignXCore mapping skipped for $Commander (non-fatal for Reborn commanders): $_"
    }
    # Reborn 模式：预写 cryswarmcoop.SC2Bank，让重生虫心 mod 读取指定指挥官并自动执行 SwarmSetup。
    # 必须在 -EnableReborn 模式下使用，且 RebornCommander 必须是重生虫心支持的指挥官名称。
    if ($EnableReborn -and $RebornCommander -ne "") {
        Set-RebornCommander -Commander $RebornCommander -Difficulty $RebornDifficulty -Speed $RebornSpeed -UnlockAllMaps
    }
    if ($ShowSelectionUI) {
        # 删除已有的 LaunchProfile 银行文件，确保 CMRE 不会自动应用已保存的配置，
        # 而是显示指挥官选择界面。
        $bankPath = "C:\Users\22448\Documents\StarCraft II\Banks\CMCoopLaunchProfile.SC2Bank"
        if (Test-Path -LiteralPath $bankPath) {
            [System.IO.File]::Delete($bankPath)
            Write-Host "CMRE ShowSelectionUI: deleted existing CMCoopLaunchProfile.SC2Bank to force selection UI"
        }
    } else {
        Write-CmreLaunchProfile
    }
    if ($NoLaunch) { Write-Host "CMRE Alenger composition staged: $liveMap"; exit 0 }
    $switcher = Join-Path $Sc2Root "Support64\SC2Switcher_x64.exe"
    if ($ListenPort -gt 0) {
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
        Start-Process -FilePath $switcher -ArgumentList $argList -WorkingDirectory $Sc2Root
        # API 模式下轮询 TCP 端口，直到 SC2 API 监听就绪（最多等 120s）。
        Write-Host "SC2 API mode: polling TCP 127.0.0.1:$ListenPort until listening (max 120s)..."
        $deadline = (Get-Date).AddSeconds(120)
        $listening = $false
        while ((Get-Date) -lt $deadline) {
            $proc = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
            if ($null -eq $proc) {
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
                throw "SC2 API mode: SC2_x64.exe exited before API port $ListenPort opened (crash or auth broker missing). Check GameLogs."
            } else {
                throw "SC2 API mode: SC2_x64.exe is running but API port $ListenPort did not open within 120s."
            }
        }
        Write-Host "SC2 API mode: API listening on 127.0.0.1:$ListenPort (SC2_x64 PID=$($proc.Id))"
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
                $scriptErr = Get-ChildItem -LiteralPath $latestDir.FullName -Filter "ScriptError*.txt" -ErrorAction SilentlyContinue
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
    } else {
        # 普通模式：地图路径作为位置参数传给 Switcher，SC2 启动后自动加载地图
        $args = @("`"$liveMap`"")
        Start-Process -FilePath $switcher -ArgumentList $args -WorkingDirectory (Split-Path -Parent $switcher)
        # StartupGraceSeconds=120: SC2Switcher 启动 SC2_x64 需要 1-3 分钟（patch 检查、auth、模块加载）。
        # 默认 0 会在 SC2 未启动 10 秒后误判 crash。之前 08:14 测试 SC2 启动快（10 秒内）所以通过，
        # 但 Battle.net auth 慢或 patch 检查时会超过 10 秒导致误判。
        $exitCode = Wait-GameReady -ScriptsRoot (Join-Path $LegacyRoot "scripts") -StartupGraceSeconds 120
        if ($exitCode -ne 0) { throw "SC2 readiness check failed with exit code $exitCode" }
    }
} finally {
    # DebugMode 退出时按 PID 关闭自己启动的 SC2（禁止按进程名 kill，避免误杀玩家游戏）
    if ($DebugMode -and (Test-Path $debugPidFile)) {
        $debugPid = Get-Content $debugPidFile -ErrorAction SilentlyContinue
        if ($debugPid) {
            Write-Host "DebugMode: 退出时关闭 SC2 (PID=$debugPid)"
            Stop-Process -Id $debugPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $debugPidFile -Force -ErrorAction SilentlyContinue
    }
    Release-TestLock -LockContext $lock
}
