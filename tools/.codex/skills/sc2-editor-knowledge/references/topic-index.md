# Topic Index

Flat map of common topics to their authoritative files. Use this for direct
`Read` access when you know the topic but not the file path.

Paths starting with `docs/kb-sources/` are committed to Git. Paths starting with
`reference/sc2mapster/SC2GameData/` live in the Blizzard data mirror submodule (~1.1 GB;
run `git submodule update --init reference/sc2mapster/SC2GameData` after cloning). Querying
the vector index is the recommended discovery mechanism — this file is a
fallback for direct reads.

## Galaxy script

| Topic | File |
|-------|------|
| Language syntax, types, control flow | `docs/kb-sources/galaxy/syntax.md` |
| Native function index (curated) | `docs/kb-sources/galaxy/natives-reference.md` |
| Native function index (per-category, ~1500 natives) | `docs/kb-sources/galaxy/native-index.md` |
| Full native declarations (all ~1500 natives) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/natives.galaxy` |
| NativeLib source (high-level wrappers) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/NativeLib.galaxy` |
| Natives missing from editor autocomplete | `docs/kb-sources/galaxy/natives-missing.galaxy` |
| Per-catalog-scope natives (49 files: Abil/Actor/Behavior/Effect/Unit/...) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/*.galaxy` |
| ScriptError codes | `docs/kb-sources/galaxy/script-error-codes.md` |
| Campaign library declarations | `docs/kb-sources/galaxy/CampaignLib_h.galaxy` |
| Generated MapScript sample | `docs/kb-sources/galaxy/MapScript-sample.galaxy` |
| Hotkey script sample | `docs/kb-sources/galaxy/hotkeys-sample.galaxy` |
| Community tutorial (legacy) | `docs/kb-sources/legacy/galaxy-tutorial.txt` |

## Catalog

| Topic | File |
|-------|------|
| XML format, scopes, entry structure, inheritance | `docs/kb-sources/catalog/format.md` |
| Field reference: all 105 catalog scopes (CUnit / CAbil / CWeapon / CEffect / CBehavior / CUpgrade / CButton / CMover / CValidator / CTargetFind / CTargetSort) | `docs/kb-sources/catalog/fields-reference.md` |
| CEffect deep dive: chain pattern, Subject model, 32 subclasses | `docs/kb-sources/catalog/effects.md` |
| CValidator deep dive: 80+ subclasses, combine/compare/filter patterns | `docs/kb-sources/catalog/validators.md` |
| CTargetFind / CTargetSort targeting system, sort chaining | `docs/kb-sources/catalog/targeting.md` |
| Official CUnit catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/UnitData.xml` |
| Official CAbil catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/AbilData.xml` |
| Official CWeapon catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/WeaponData.xml` |
| Official CEffect catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/EffectData.xml` |
| Official CBehavior catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/BehaviorData.xml` |
| Official CActor catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/ActorData.xml` |
| Official CUpgrade catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/UpgradeData.xml` |
| Official CRequirement catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/RequirementData.xml` |
| Other reference XMLs (Button/Validator/Mover/TargetFind/TargetSort/Turret/Footprint/Talent) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/*.xml` |
| Race-specific overrides (Terran/Zerg/Protoss) | `reference/sc2mapster/SC2GameData/mods/{liberty,swarm,void}.sc2mod/base.sc2data/GameData/*.xml` |
| Co-op commander libraries (LibCOMI/LibCOMU/LibCOOC/LibCOUI) | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/Lib*.galaxy` |
| Data space mode (modular layout) | `docs/kb-sources/data-spaces/usage-guide.md` |

## Editor

| Topic | File |
|-------|------|
| Editor overview, modules, basic operations | `docs/kb-sources/editor/editor-overview.md` |
| AI-assisted modding guide | `docs/kb-sources/editor/ai-development-guide.md` |

## Document structure

| Topic | File |
|-------|------|
| Files inside a SC2Map / SC2Mod | `docs/kb-sources/document-structure/overview.md` |
| DocumentHeader vs DocumentInfo (binary vs XML) | `docs/kb-sources/document-structure/overview.md` |
| 7vs1 campaign map caveats | `docs/kb-sources/document-structure/overview.md` |

## Triggers

| Topic | File |
|-------|------|
| ECA structure, parameter types, custom script | `docs/kb-sources/triggers/system.md` |
| GUI vs custom script, library auto-loading | `docs/kb-sources/triggers/system.md` |
| Lib<Name>.galaxy library file pattern | `docs/kb-sources/triggers/system.md` |
| Initialization order | `docs/kb-sources/triggers/system.md` |
| TriggerExecute / Wait semantics | `docs/kb-sources/triggers/system.md` |
| TriggerAddEventTimePeriodic pitfall | `docs/kb-sources/triggers/system.md`, `docs/kb-sources/galaxy/syntax.md` |

## Data spaces

| Topic | File |
|-------|------|
| Data space mode usage guide | `docs/kb-sources/data-spaces/usage-guide.md` |

## Bank

| Topic | File |
|-------|------|
| Bank file format, API, encryption | `docs/kb-sources/bank/format.md` |

## MPQ

| Topic | File |
|-------|------|
| MPQ container format, unpack/repack | `docs/kb-sources/mpq/format.md` |

## Actor

| Topic | File |
|-------|------|
| Actor kinds, events, message chain | `docs/kb-sources/actor/system.md` |
| Actor messages (ActorSend/SendTo/ScopeSend, msg names, refNames, LookAt, TextureGroup) | `docs/kb-sources/actor/messages.md` |
| Actor native declarations | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/Actor.galaxy` |
| Official CActor catalog (Blizzard) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/ActorData.xml` |

## Unit (runtime state)

| Topic | File |
|-------|------|
| Unit flags (c_unitFlag*) and runtime states (c_unitState*) | `docs/kb-sources/unit/state-and-flags.md` |
| UnitFilter system (UnitFilterStr grammar, filter attributes) | `docs/kb-sources/unit/state-and-flags.md` |
| State toggle patterns (Selectable/Targetable/Invulnerable/Stunned) | `docs/kb-sources/unit/state-and-flags.md` |
| CBehaviorBuff Modification.States array | `docs/kb-sources/unit/state-and-flags.md`, `docs/kb-sources/catalog/fields-reference.md` |

## Requirement / Upgrade / Tech Tree

| Topic | File |
|-------|------|
| Requirement nodes, tech-tree gating, multi-level upgrades | `docs/kb-sources/requirement/system.md` |
| Requirement native declarations | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/Requirement.galaxy` |
| Upgrade native declarations | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/Upgrade.galaxy` |
| Official CRequirement catalog | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/RequirementData.xml` |
| Official CUpgrade catalog | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/UpgradeData.xml` |

## AI

| Topic | File |
|-------|------|
| AI-assisted modding guide | `docs/kb-sources/editor/ai-development-guide.md` |
| AI framework entry (natives) | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/AI.galaxy` |
| High-level AI base | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/BaseAI.galaxy` |
| Build order execution | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/BuildAI.galaxy` |
| Melee AI | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/MeleeAI.galaxy` |
| Shared AI utilities | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/SharedAI.galaxy` |
| Computer player setup | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/Computer.galaxy` |
| AI debug helpers | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/DebugAI.galaxy` |
| Co-op commander AI (LibCOMI/LibCOMU/LibCOOC/LibCOUI) | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/Lib*.galaxy` |

## Mutators

| Topic | File |
|-------|------|
| Mutator mod structure, Lib<Hex>.galaxy pattern | `docs/kb-sources/mutator/system.md` |
| CMutator catalog entries | `docs/kb-sources/mutator/system.md` |
| LibCOMU registration (RegisterMutator/EnableDisable) | `docs/kb-sources/mutator/system.md`, `docs/kb-sources/coop/commander-framework.md` |
| Per-mutator hook functions (CT_Apply*) | `docs/kb-sources/mutator/system.md` |
| Combo mutator pattern | `docs/kb-sources/mutator/system.md` |
| Mutator catalog (~100 mutators total, Blizzard mirror) | `reference/sc2mapster/SC2GameData/mods/mutators/` |
| Single mutator example: Blizzard | `reference/sc2mapster/SC2GameData/mods/mutators/mutatorblizzard.sc2mod/base.sc2data/Lib9B7202B2.galaxy` |
| Mutator quick-list preset constants | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/LibCOMU_h.galaxy` |

## Co-op commander framework

| Topic | File |
|-------|------|
| LibCOOC/LibCOMU/LibCOMI/LibCOUI dependency chain | `docs/kb-sources/coop/commander-framework.md` |
| Commander data model (CCommander) | `docs/kb-sources/coop/commander-framework.md` |
| Player-commander binding API | `docs/kb-sources/coop/commander-framework.md` |
| Mastery system (levels, save/load) | `docs/kb-sources/coop/commander-framework.md` |
| Mission lifecycle (LibCOMI phases) | `docs/kb-sources/coop/commander-framework.md` |
| `libCOOC_gf_CC_CommanderIsDeveloping` does not exist | `docs/kb-sources/coop/commander-framework.md` |
| Commander library source (Blizzard) | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/Lib*.galaxy` |
| Commander catalog (CCommander entries) | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/GameData/CommanderData.xml` |
| Mastery preset constants | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/LibCOOC_h.galaxy` |

## Cutscene / Transmission / Conversation

| Topic | File |
|-------|------|
| Cutscene native API (Create/Play/Bookmark/Filter) | `docs/kb-sources/cutscene/system.md` |
| Transmission sources (Unit/Model/Movie) | `docs/kb-sources/cutscene/system.md` |
| TransmissionSendForPlayer parameters | `docs/kb-sources/cutscene/system.md` |
| Conversation data-driven state model | `docs/kb-sources/cutscene/system.md` |
| Conversation UI (Create/Reply/Show) | `docs/kb-sources/cutscene/system.md` |
| Cutscene bookmark events | `docs/kb-sources/cutscene/system.md` |
| Co-op transmission helpers (libCOMI_gf_MissionTransmission) | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/LibCOMI_h.galaxy` |

## Sound / Soundtrack / VoiceOver

| Topic | File |
|-------|------|
| Sound playback (SoundPlayForPlayer variants) | `docs/kb-sources/sound/system.md` |
| Sound channel volume / mute / DSP | `docs/kb-sources/sound/system.md` |
| Soundtrack (music) cue / index / continuous | `docs/kb-sources/sound/system.md` |
| Sound length sync (multiplayer) | `docs/kb-sources/sound/system.md`, `docs/kb-sources/multiplayer/sync.md` |
| Reverb / 3D sound factors | `docs/kb-sources/sound/system.md` |
| VoiceOver (CVoiceOver) data entries | `docs/kb-sources/sound/system.md` |
| Sound category preset constants | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/Sound.galaxy` |

## Hero / Talent

| Topic | File |
|-------|------|
| CHero catalog (Flags/Role/Difficulty) | `docs/kb-sources/hero-talent/system.md` |
| TalentTree native API (Select/ClearTier/Level) | `docs/kb-sources/hero-talent/system.md` |
| CTalent modification types | `docs/kb-sources/hero-talent/system.md` |
| CHeroAbil variant swap | `docs/kb-sources/hero-talent/system.md` |
| CHeroStat stat tracks | `docs/kb-sources/hero-talent/system.md` |
| Hero native declarations | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/Hero.galaxy` |
| Talent native declarations | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/Talent.galaxy` |
| Official CHero catalog | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/HeroData.xml` |
| Official CTalent catalog | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/GameData/TalentData.xml` |

## Campaign

| Topic | File |
|-------|------|
| CCampaign / CCharacter / CLocation / CObjective | `docs/kb-sources/campaign/system.md` |
| Objective native API (create/state/order/primary) | `docs/kb-sources/campaign/system.md` |
| Campaign progress natives (Blizzard-only) | `docs/kb-sources/campaign/system.md` |
| Campaign AI vs Melee AI | `docs/kb-sources/campaign/system.md`, `docs/kb-sources/editor/ai-development-guide.md` |
| LibCOMI Co-op campaign lifecycle | `docs/kb-sources/campaign/system.md`, `docs/kb-sources/coop/commander-framework.md` |
| Campaign native declarations | `reference/sc2mapster/SC2GameData/mods/core.sc2mod/base.sc2data/TriggerLibs/GameData/Campaign.galaxy` |
| Official CCampaign catalog | `reference/sc2mapster/SC2GameData/mods/alliedcommanders.sc2mod/base.sc2data/GameData/CampaignData.xml` |

## Multiplayer & Sync

| Topic | File |
|-------|------|
| Deterministic lockstep model | `docs/kb-sources/multiplayer/sync.md` |
| SynchronousGameStartTimeGet / CurrentSynchronousGameTimeGet | `docs/kb-sources/multiplayer/sync.md` |
| PlayerLocal / PlayerIsLocal (host-only pattern) | `docs/kb-sources/multiplayer/sync.md` |
| Bank preload/wait for cross-player sync | `docs/kb-sources/multiplayer/sync.md`, `docs/kb-sources/bank/format.md` |
| UI sync frames (c_syncFrameType*) | `docs/kb-sources/multiplayer/sync.md` |
| Network-aware natives (SoundLengthSync/AnimLengthSync) | `docs/kb-sources/multiplayer/sync.md` |
| Random number determinism (desync) | `docs/kb-sources/multiplayer/sync.md` |
| TriggerAddEventPlayerLeft | `docs/kb-sources/multiplayer/sync.md` |

## Performance

| Topic | File |
|-------|------|
| Per-tick cost offenders (UnitGroup/Catalog/BankSave) | `docs/kb-sources/performance/tuning.md` |
| Caching catalog field values at init | `docs/kb-sources/performance/tuning.md` |
| Async execution via TriggerExecute | `docs/kb-sources/performance/tuning.md` |
| DeferredCleanup pattern (UnitRemove during init) | `docs/kb-sources/performance/tuning.md` |
| Wait granularity (1/16 second minimum) | `docs/kb-sources/performance/tuning.md`, `docs/kb-sources/triggers/system.md` |
| Mod size and load time | `docs/kb-sources/performance/tuning.md` |
| Profiling patterns | `docs/kb-sources/performance/tuning.md` |

## Runtime contracts

| Topic | File |
|-------|------|
| Runtime observer, run directory, acceptance criteria | `docs/kb-sources/runtime-contracts/observer.md` |
| Readiness gate, ScriptError scanning, process gate | `docs/kb-sources/runtime-contracts/observer.md` |

## External resources

| Topic | File |
|-------|------|
| SC2Mapster community resources | `docs/kb-sources/legacy/sc2mapster-resources.md` |
| General learning resources | `docs/kb-sources/legacy/learning-resources.md` |

## Common gotchas

| Gotcha | Where to look |
|--------|---------------|
| `libCOOC_gf_CC_CommanderIsDeveloping` not boolean (CMRE) | `docs/kb-sources/runtime-contracts/observer.md`, `projects/cmre-porting/stages/04-runtime-baseline/issues.json` |
| `AchievementTermQuantitySet` restricted after init | `docs/kb-sources/runtime-contracts/observer.md` |
| `CatalogFieldValueGet` race strings are `Terr`/`Zerg`/`Prot` | `docs/kb-sources/galaxy/syntax.md`, `docs/kb-sources/galaxy/natives-reference.md` |
| Chinese variable names break editor save | `docs/kb-sources/galaxy/syntax.md`, `docs/kb-sources/document-structure/overview.md` |
| CJK map path can't store components | `docs/kb-sources/document-structure/overview.md` |
| `_h` suffix include does not load implementation | `docs/kb-sources/galaxy/syntax.md` |
| `TriggerAddEventTimePeriodic` unreliable on 7vs1 | `docs/kb-sources/galaxy/syntax.md`, `docs/kb-sources/triggers/system.md` |
| `UnitRemove` no-ops during init | `docs/kb-sources/galaxy/syntax.md` |
| HiddenWhenRequirementNotMet hides unit from build panel | `docs/kb-sources/requirement/system.md` |
| Actor messages are async; do not check state immediately after send | `docs/kb-sources/actor/system.md` |
| AI scripts run on host thread; long loops cause frame drops | `docs/kb-sources/editor/ai-development-guide.md` |
| 7vs1 campaign AI differs from melee AI | `docs/kb-sources/editor/ai-development-guide.md`, `docs/kb-sources/document-structure/overview.md` |
