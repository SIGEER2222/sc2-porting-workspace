// RO_PATCH_RUNTIME_OVERLAY_V1 {{PATCH_ID}}
// Staged-map overlay. The source map and commander Mods remain unchanged.
trigger gv_ro_patch_bootstrap;
bool gv_ro_patch_busy;
bool gv_ro_patch_hero_created;
bool gv_ro_patch_startup_created;

void gf_ro_patch_replace_p1_unit (unit lp_unit) {
    string lv_type;
    if (lp_unit == null || UnitGetOwner(lp_unit) != 1) {
        return;
    }
    lv_type = UnitGetType(lp_unit);
{{REPLACEMENT_BODY}}
}

void gf_ro_patch_create_hero_once () {
    unitgroup lv_units;
    unit lv_unit;
    int lv_index;
    if (gv_ro_patch_hero_created || "{{HERO}}" == "") {
        return;
    }
    if (!CatalogEntryIsValid(c_gameCatalogUnit, "{{HERO}}")) {
        return;
    }
    lv_units = UnitGroup(null, 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_index = UnitGroupCount(lv_units, c_unitCountAll);
    for (;; lv_index -= 1) {
        lv_unit = UnitGroupUnitFromEnd(lv_units, lv_index);
        if (lv_unit == null) {
            break;
        }
        if (UnitGetType(lv_unit) == "{{STARTING_STRUCTURE}}") {
            UnitCreate(1, "{{HERO}}", c_unitCreateIgnorePlacement, 1, UnitGetPosition(lv_unit), UnitGetFacing(lv_unit));
            gv_ro_patch_hero_created = true;
            return;
        }
    }
}

void gf_ro_patch_ensure_startup_once () {
    unitgroup lv_units;
    unit lv_unit;
    unit lv_anchor;
    int lv_index;
    if (gv_ro_patch_startup_created) {
        return;
    }
    lv_units = UnitGroup(null, 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_index = UnitGroupCount(lv_units, c_unitCountAll);
    for (;; lv_index -= 1) {
        lv_unit = UnitGroupUnitFromEnd(lv_units, lv_index);
        if (lv_unit == null) {
            break;
        }
        if (UnitGetType(lv_unit) == "{{STARTING_STRUCTURE}}") {
            gv_ro_patch_startup_created = true;
            return;
        }
        if (lv_anchor == null) {
            lv_anchor = lv_unit;
        }
    }
    if (lv_anchor == null) {
        return;
    }
    UnitCreate(1, "{{STARTING_STRUCTURE}}", c_unitCreateIgnorePlacement, 1, UnitGetPosition(lv_anchor), UnitGetFacing(lv_anchor));
    UnitCreate({{WORKER_COUNT}}, "{{STARTING_WORKER}}", c_unitCreateIgnorePlacement, 1, UnitGetPosition(lv_anchor), UnitGetFacing(lv_anchor));
    gv_ro_patch_startup_created = true;
}

void gf_ro_patch_scan_p1 () {
    unitgroup lv_units;
    unit lv_unit;
    int lv_index;
    lv_units = UnitGroup(null, 1, RegionEntireMap(), UnitFilter(0, 0, (1 << c_targetFilterMissile), (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_index = UnitGroupCount(lv_units, c_unitCountAll);
    for (;; lv_index -= 1) {
        lv_unit = UnitGroupUnitFromEnd(lv_units, lv_index);
        if (lv_unit == null) {
            break;
        }
        gf_ro_patch_replace_p1_unit(lv_unit);
    }
    gf_ro_patch_ensure_startup_once();
    gf_ro_patch_create_hero_once();
}

bool gt_ro_patch_bootstrap_Func (bool testConds, bool runActions) {
    if (!runActions || gv_ro_patch_busy) {
        return true;
    }
    gv_ro_patch_busy = true;
    if (EventUnit() != null) {
        gf_ro_patch_replace_p1_unit(EventUnit());
    }
    gf_ro_patch_scan_p1();
    gv_ro_patch_busy = false;
    return true;
}

void gt_ro_patch_bootstrap_Init () {
    gv_ro_patch_bootstrap = TriggerCreate("gt_ro_patch_bootstrap_Func");
    TriggerAddEventUnitCreated(gv_ro_patch_bootstrap, null, null, null);
    TriggerAddEventUnitChangeOwner(gv_ro_patch_bootstrap, null);
    TriggerAddEventTimePeriodic(gv_ro_patch_bootstrap, 0.25, c_timeGame);
}
