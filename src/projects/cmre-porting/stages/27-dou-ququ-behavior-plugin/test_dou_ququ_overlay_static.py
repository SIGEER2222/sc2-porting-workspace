from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
LAUNCHER = ROOT / "tools" / "launchers" / "launch-cmre-alenger.ps1"
OVERLAY = ROOT / "tools" / "launchers" / "lib" / "cmre-on-demand-overlay.ps1"
GALAXY = ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup" / "LibDouQuquBehavior.galaxy"
EFFECTS = ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup" / "EffectData.xml"
ATTACH = ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup" / "AttachMethodData.xml"
ACTOR = ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup" / "ActorData.xml"
CONFIG = ROOT / "src" / "projects" / "cmre-porting" / "vibe" / "dou_ququ_behavior.json"


def test_launcher_exposes_map_scoped_switch():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "$EnableDouQuquBehavior" in source
    assert "restricted to the 斗蛐蛐 map" in source
    assert "-EnableDouQuquBehavior:$EnableDouQuquBehavior" in source


def test_overlay_copies_and_initializes_plugin_only_when_enabled():
    source = OVERLAY.read_text(encoding="utf-8-sig")
    assert "[switch]$EnableDouQuquBehavior" in source
    assert "LibDouQuquBehavior_h.galaxy" in source
    assert "LibDouQuquBehavior.galaxy" in source
    assert "include \"LibDouQuquBehavior\"" in source
    assert "libDouQuquBehavior_InitLib();" in source
    assert source.index("if ($EnableDouQuquBehavior)") < source.index("include \"LibDouQuquBehavior\"")


def test_overlay_has_a_signature_scoped_standalone_map_path():
    source = OVERLAY.read_text(encoding="utf-8-sig")
    glue = (ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "map-glue.dou-ququ-standalone.galaxy").read_text(encoding="utf-8-sig")
    assert "Install-CmreDouQuquStandaloneMapOverlay" in source
    assert "lllAtg" in source
    assert "lllnIs" in source
    assert "CMRE_DOUQUQU_STANDALONE_RUNTIME_GLUE" in glue
    assert "runtime_listener_ready" in glue
    assert "initialization_complete" in glue


def test_galaxy_plugin_has_all_six_rules_and_real_event_hooks():
    source = GALAXY.read_text(encoding="utf-8")
    effects = EFFECTS.read_text(encoding="utf-8")
    for token in (
        '"Reaver"', '"Zealot"', '"Vulture"', '"SpiderMine"',
        '"InfestedBanshee"', '"Marine"', '"BroodLord"',
        '"K5Kerrigan"', '"KerriganInfestBroodling"',
        "TriggerAddEventUnitAttacked2", "TriggerAddEventUnitDied",
        "TriggerAddEventUnitCreated", "TriggerAddEventTimePeriodic",
        "UnitAbilityAddChargeUsed", "PlayerModifyPropertyInt",
        "UnitSetPropertyFixed", "libNtve_gf_KillingUnit",
        "CRV_BroodLord_BanelingLaunch", "UnitCreateEffectUnit",
    ):
        assert token in source
    assert 'SpawnUnit value="Baneling"' in effects


def test_reaver_uses_thor_style_rolling_weapon_attachments():
    attach = ATTACH.read_text(encoding="utf-8")
    actor = ACTOR.read_text(encoding="utf-8")
    for token in (
        '<CAttachMethodFilter id="CRV_AMFilterReaverWeapons">',
        '<Keys Keyword="Weapon" Index="10"/>',
        '<Keys Keyword="Weapon" Index="11"/>',
        '<Keys Keyword="Weapon" Index="13"/>',
        '<Keys Keyword="Weapon" Index="14"/>',
        '<Logic value="OR"/>',
        '<CAttachMethodPattern id="CRV_AMPatternReaverScarab">',
        '<Base value="::RollingIndex"/>',
        '<Driver value="ScarabLM"/>',
    ):
        assert token in attach
    assert '<CActorAction id="ScarabAttack"' in actor
    assert 'Methods="CRV_AMFilterReaverWeapons CRV_AMPatternReaverScarab"' in actor
    assert '<ImpactSiteOps Ops="SOpAttachHarness SOpAttachVolumeStandard SOpForwardLaunchGuide"/>' in actor
    assert '<ImpactPhysics Name="Explosion" MatchKeys="Basic" Physics="ScarabExplosionForce"/>' in actor


def test_config_matches_plugin_contract():
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == 1
    assert data["enabledByDefault"] is False
    assert data["rules"]["vultureStorage"]["storageBonus"] == 2
    assert data["rules"]["vultureStorage"]["refillCost"] == 50
    assert data["rules"]["vultureDeath"]["spawnCount"] == 3
    assert data["rules"]["infestedBansheeHatch"]["energyCost"] == 20.0
    assert data["rules"]["infestedBansheeHatch"]["spawnUnit"] == "Marine"
    assert data["rules"]["hydraliskKill"]["healAmount"] == 25.0
    assert data["rules"]["kerriganKill"]["spawnCount"] == 2
