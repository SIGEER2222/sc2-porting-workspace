$ErrorActionPreference = "Stop"

function Replace-CmreCoreLiteral {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Anchor,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Patch,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]::IsNullOrEmpty($Anchor)) { throw "$Label anchor resolved empty" }
    return $Content.Replace($Anchor, $Patch)
}

function Install-CmreCoreRuntimeErrorOverlay {
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

    # Patch 12: CM_StartingTechForHumanPlayer reads Race.StartingUnitArray using
    # an empty PlayerSpawnRace for commander-map compositions that bypass the
    # stock commander selection UI. Guard the catalog read and skip larva lookup
    # when no town hall type was resolved.
    $comiAnchor12 = '    lv_townHallType = (CatalogFieldValueGet(c_gameCatalogRace, libCOOC_gf_CC_PlayerSpawnRace(lp_player), "StartingUnitArray[" + IntToString(0) + "].Unit", c_playerAny));'
    $comiPatch12 = '    if ((libCOOC_gf_CC_PlayerSpawnRace(lp_player) != null) && (libCOOC_gf_CC_PlayerSpawnRace(lp_player) != "")) { lv_townHallType = (CatalogFieldValueGet(c_gameCatalogRace, libCOOC_gf_CC_PlayerSpawnRace(lp_player), "StartingUnitArray[" + IntToString(0) + "].Unit", c_playerAny)); } // CMRE patch: guard empty spawn race'
    if (-not $comi.Contains($comiPatch12)) {
        if (-not $comi.Contains($comiAnchor12)) { throw "LibCOMI patch 12 anchor not found" }
        $comi = $comi.Replace($comiAnchor12, $comiPatch12); $patchCount++
    }
    $comiAnchor12b = '    if ((lv_larvaCount > 0)) {'
    $comiPatch12b = '    if ((lv_larvaCount > 0) && (lv_townHallType != "")) { // CMRE patch: only search town hall when resolved'
    if (-not $comi.Contains($comiPatch12b)) {
        if (-not $comi.Contains($comiAnchor12b)) { throw "LibCOMI patch 12b anchor not found" }
        $comi = $comi.Replace($comiAnchor12b, $comiPatch12b); $patchCount++
    }

    # Patch 13: CM_GlobalCasterInitial can request an empty global power unit
    # type for on-demand commanders. NativeLib's CreateUnitsWithDefaultFacing
    # dereferences that empty type through CatalogFieldValueGet, so skip caster
    # creation unless a valid unit entry exists.
    $comiAnchor13 = '    libNtve_gf_CreateUnitsWithDefaultFacing(1, libCOOC_gf_CC_PlayerGlobalPowerUnitType(lp_player), c_unitCreateIgnorePlacement, lp_player, Point(0.0, 0.0));'
    $comiPatch13 = '    if ((libCOOC_gf_CC_PlayerGlobalPowerUnitType(lp_player) == "") || (!CatalogEntryIsValid(c_gameCatalogUnit, libCOOC_gf_CC_PlayerGlobalPowerUnitType(lp_player)))) { return; } libNtve_gf_CreateUnitsWithDefaultFacing(1, libCOOC_gf_CC_PlayerGlobalPowerUnitType(lp_player), c_unitCreateIgnorePlacement, lp_player, Point(0.0, 0.0)); // CMRE patch: guard empty global caster unit type'
    if (-not $comi.Contains($comiPatch13)) {
        if (-not $comi.Contains($comiAnchor13)) { throw "LibCOMI patch 13 anchor not found" }
        $comi = $comi.Replace($comiAnchor13, $comiPatch13); $patchCount++
    }

    # Patch 14: CM_HeroSpawn can enter the hero-structure branch with a link set
    # but an empty/invalid HeroStructure unit type for on-demand commanders. Skip
    # that branch rather than calling UnitCreate with an empty unit type.
    $comiAnchor14 = '        if ((libCOOC_gf_CC_PlayerHeroStructureLinks(lv_indexPlayer) != null)) {'
    $comiPatch14 = '        if ((libCOOC_gf_CC_PlayerHeroStructureLinks(lv_indexPlayer) != null) && (libCOOC_gf_CC_PlayerHeroStructureType(lv_indexPlayer) != "") && (CatalogEntryIsValid(c_gameCatalogUnit, libCOOC_gf_CC_PlayerHeroStructureType(lv_indexPlayer)))) { // CMRE patch: guard empty hero structure unit type'
    if (-not $comi.Contains($comiPatch14)) {
        if (-not $comi.Contains($comiAnchor14)) { throw "LibCOMI patch 14 anchor not found" }
        $comi = $comi.Replace($comiAnchor14, $comiPatch14); $patchCount++
    }

    # Patch 15: CM_HeroSpawnForPlayer treats an empty HeroUnit link as a valid
    # non-null value. Skip the complete hero branch unless the resolved unit is
    # present in the catalog, so later UnitLastCreated/UI calls cannot receive
    # a null unit after UnitCreate is skipped.
    $comiAnchor15 = '    if ((libCOOC_gf_CC_PlayerHeroUnitType(lp_player) != null)) {'
    $comiPatch15 = '    if ((libCOOC_gf_CC_PlayerHeroUnitType(lp_player) != null) && (libCOOC_gf_CC_PlayerHeroUnitType(lp_player) != "") && (CatalogEntryIsValid(c_gameCatalogUnit, libCOOC_gf_CC_PlayerHeroUnitType(lp_player)))) { // CMRE patch: guard empty hero unit type'
    if (-not $comi.Contains($comiPatch15)) {
        if (-not $comi.Contains($comiAnchor15)) { throw "LibCOMI patch 15 anchor not found" }
        $comi = $comi.Replace($comiAnchor15, $comiPatch15); $patchCount++
    }

    # Patch 16: the main CM_HeroSpawn trigger has the same null-only guard but
    # runs the full hero setup inline. Apply the catalog guard there as well.
    $comiAnchor16 = '        if ((libCOOC_gf_CC_PlayerHeroLinks(lv_indexPlayer) != null)) {'
    $comiPatch16 = '        if ((libCOOC_gf_CC_PlayerHeroLinks(lv_indexPlayer) != null) && (libCOOC_gf_CC_PlayerHeroUnitType(lv_indexPlayer) != null) && (libCOOC_gf_CC_PlayerHeroUnitType(lv_indexPlayer) != "") && (CatalogEntryIsValid(c_gameCatalogUnit, libCOOC_gf_CC_PlayerHeroUnitType(lv_indexPlayer)))) { // CMRE patch: guard empty hero unit type'
    if (-not $comi.Contains($comiPatch16)) {
        if (-not $comi.Contains($comiAnchor16)) { throw "LibCOMI patch 16 anchor not found" }
        $comi = $comi.Replace($comiAnchor16, $comiPatch16); $patchCount++
    }

    # Patch 17: keep direct callers of CM_HeroCreateForPlayer from attempting
    # UnitCreate with an empty or invalid catalog entry.
    $comiAnchor17 = '    UnitCreate(1, libCOOC_gf_CC_PlayerHeroUnitType(lp_player), lp_flags, lp_player, lp_spawnPoint, lp_facing);'
    $comiPatch17 = '    if ((libCOOC_gf_CC_PlayerHeroUnitType(lp_player) == null) || (libCOOC_gf_CC_PlayerHeroUnitType(lp_player) == "") || (!CatalogEntryIsValid(c_gameCatalogUnit, libCOOC_gf_CC_PlayerHeroUnitType(lp_player)))) { return; } UnitCreate(1, libCOOC_gf_CC_PlayerHeroUnitType(lp_player), lp_flags, lp_player, lp_spawnPoint, lp_facing); // CMRE patch: guard invalid hero unit type'
    if (-not $comi.Contains($comiPatch17)) {
        if (-not $comi.Contains($comiAnchor17)) { throw "LibCOMI patch 17 anchor not found" }
        $comi = $comi.Replace($comiAnchor17, $comiPatch17); $patchCount++
    }

    # Patch 10: CM_HeroWaitForRevive_TriggerFunc 在无英雄指挥官（如 Alenger）时
    # libCOMI_gv_cM_HeroReviver[lp_player] 为 null，执行到 UnitGetPosition 会抛
    # "无法从参数中获取 unit(0#0)" 致命错误。无英雄复活单位则直接跳过复活逻辑。
    # 注意：Galaxy 不允许在局部变量声明之前出现可执行语句，故 guard 必须放在
    # 变量声明之后。锚点用 autoE01594B5_var（该触发器函数独有的自动变量）保证
    # 只命中 CM_HeroWaitForRevive_TriggerFunc，避免误注入到其他函数（如复活时长计算）。
    # Use deterministic offsets inside the uniquely named trigger function.
    # A broad [\s\S]*? Regex.Replace here can repeatedly match generated
    # fragments and inflate LibCOMI from 3 MB to hundreds of MB.
    $comiFunction10 = 'bool auto_libCOMI_gf_CM_HeroWaitForRevive_TriggerFunc'
    $comiUnitAnchor10 = '    unit autoE01594B5_var;'
    $comiCommanderAnchor10 = '    lv_commander = libCOOC_gf_ActiveCommanderForPlayer(lp_player);'
    $nl = if ($comi.Contains("`r`n")) { "`r`n" } else { "`n" }
    $comiPatch10 = $comiUnitAnchor10 + $nl + $nl + '    // CMRE patch: 无英雄指挥官（如 Alenger）的 cM_HeroReviver 为 null，跳过复活逻辑' + $nl + '    if (libCOMI_gv_cM_HeroReviver[lp_player] == null) { return true; }' + $nl + $comiCommanderAnchor10
    if (-not $comi.Contains($comiPatch10)) {
        $functionIndex10 = $comi.IndexOf($comiFunction10, [System.StringComparison]::Ordinal)
        if ($functionIndex10 -lt 0) { throw "LibCOMI patch 10 function anchor not found" }
        $unitIndex10 = $comi.IndexOf($comiUnitAnchor10, $functionIndex10, [System.StringComparison]::Ordinal)
        if ($unitIndex10 -lt 0) { throw "LibCOMI patch 10 unit anchor not found" }
        $commanderIndex10 = $comi.IndexOf($comiCommanderAnchor10, $unitIndex10, [System.StringComparison]::Ordinal)
        if ($commanderIndex10 -lt 0) { throw "LibCOMI patch 10 commander anchor not found" }
        $commanderEnd10 = $commanderIndex10 + $comiCommanderAnchor10.Length
        $comi = $comi.Substring(0, $unitIndex10) + $comiPatch10 + $comi.Substring($commanderEnd10)
        $patchCount++
    }

    # Patch 11: libCOMI_gf_CM_CommanderVOSend - 当 lp_vOSound 为 null（指挥官未配置
    # VO lines，如 Alenger6）时，SoundPlayForPlayer 会抛 "无法从'sCreateSound'的参数中
    # 获取'sound'(值：0)" 触发器错误。跳过 null soundlink 的播放，避免运行时错误。
    # 该错误在克哈裂痕等地图上单位被攻击时立即触发（libCOMI_gt_CM_VOEnemySpotted_Func）。
    $comiPatch11 = '    if ((lp_vOSound == null)) { return; } // CMRE patch: guard null soundlink (VO line not configured for this commander)'
    if (-not $comi.Contains($comiPatch11)) {
        $comiFunction11 = 'void libCOMI_gf_CM_CommanderVOSend (int lp_listenerPlayer, soundlink lp_vOSound, playergroup lp_targetPlayers) {'
        $comiSoundLine11 = '    SoundSetListenerGender(lp_vOSound, libCOOC_gf_CC_CommanderGender(libCOOC_gf_ActiveCommanderForPlayer(lp_listenerPlayer)));'
        $functionIndex11 = $comi.IndexOf($comiFunction11)
        if ($functionIndex11 -lt 0) { throw "LibCOMI patch 11 function anchor not found" }
        $soundIndex11 = $comi.IndexOf($comiSoundLine11, $functionIndex11)
        if ($soundIndex11 -lt 0) { throw "LibCOMI patch 11 sound line anchor not found" }
        $comi = $comi.Insert($soundIndex11, $comiPatch11 + $nl)
        $patchCount++
    }

    [System.IO.File]::WriteAllText($comiPath, $comi, [System.Text.UTF8Encoding]::new($false))

    Write-Host "CMRE core runtime error patches applied: $patchCount locations"
}
