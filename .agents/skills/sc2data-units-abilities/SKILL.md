---
name: sc2data-units-abilities
description: SC2 Data Editor — Units, Abilities, Movers, Turrets, Requirements, and Races in XML. Use when creating or modifying units (CUnit/CUnitHero), abilities (CAbilEffectTarget, CAbilEffectInstant, CAbilResearch, etc.), movement (CMover), turrets (CTurret), or tech requirements in GameData XML files. Always consult the catalogsData.xsd schema for exact fields and structure — do not assume unsupported fields exist. Do not use for Actors/visuals (use sc2data-actors-visuals), damage/effects (use sc2data-effects-weapons), or Galaxy scripting (use the galaxy-* skills).
---

# SC2 Data Editor – Units & Abilities

The Data Editor stores all game data as XML inside `Base.SC2Data/GameData/`. Every entry is a child of `<Catalog>`. You edit by adding or overriding entries; anything not defined in your mod/map inherits from Blizzard's base game data.

## Key References

| Resource | URL |
|---|---|
| Data Editor Introduction | https://s2editor-guides.readthedocs.io/New_Tutorials/04_Data_Editor/058_Data_Editor_Introduction/ |
| Units guide | https://s2editor-guides.readthedocs.io/New_Tutorials/04_Data_Editor/059_Units/ |
| Validators guide | https://s2editor-guides.readthedocs.io/New_Tutorials/04_Data_Editor/071_Validators/ |
| Buttons guide | https://s2editor-guides.readthedocs.io/New_Tutorials/04_Data_Editor/075_Buttons/ |
| SC2Mapster wiki | https://sc2mapster.wiki.gg/ |
| Abilities (wiki) | https://sc2mapster.wiki.gg/wiki/Data/Abilities |
| Units (wiki) | https://sc2mapster.wiki.gg/wiki/Data/Units |
| Data Editor settings (wiki) | https://sc2mapster.wiki.gg/wiki/Data_Types |
| ShadowDragon Base.SC2Data (real GameData XML reference) | https://github.com/ShadowDragonSC2/Base.SC2Data/tree/main/GameData |
| **Source of Truth: CatalogsData XSD Schema** | https://github.com/ShadowDragonSC2/Base.SC2Data/raw/refs/heads/main/.vscode/schemas/catalogsData.xsd — Always consult this for exact fields, attributes, and structure of units, abilities, movers, turrets, requirements, and races. Do not assume fields exist; verify against the schema. |
| **Recommended VS Code Extension** | Red Hat XML (redhat.vscode-xml) — Install this extension for XML validation, auto-completion, and error detection using the catalogsData.xsd schema. Configure it in .vscode/settings.json for automatic validation.
| **SC2 Unit Catalog IDs** | See skill `sc2-units-reference` for a full list of all multiplayer unit/structure catalog IDs (editor IDs), races, attributes, and expansion of origin — use when looking up the correct `id` string to reference for a parent or existing unit.

## XML Schema Error Check and Fix Workflow

When editing SC2 data XML, always run this loop until diagnostics are clean:

1. Validate with Red Hat XML diagnostics (Problems panel).
2. For each error, identify whether it is an invalid element, invalid attribute, invalid enum value, or invalid field path/array index.
3. Verify the exact allowed structure in `catalogsData.xsd` before changing anything.
4. Fix the XML by aligning to schema-supported fields only; remove guessed or unsupported fields.
5. Re-validate and repeat until no schema errors remain.

If a user asks to fix XML errors, perform this end-to-end workflow rather than only describing it.

---

## File Organization Pattern — One File Per Unit

Rather than adding entries into monolithic type-specific files (`UnitData.xml`, `ActorData.xml`, etc.), the recommended approach is to create **one self-contained XML file per unit or feature**. All catalog types for that unit — unit, weapon, effects, abilities, behaviors, actors, models, sounds — live together in that one file.

**Directory structure:**
```
Base.SC2Data/
  GameData.xml                             ← lists all included files
  GameData/
    Terran/NCO/Herc/
      Herc.xml                             ← all data for Herc in one file
    Zerg/MyUnit/
      MyUnit.xml                           ← all data for MyUnit in one file
```

**`GameData.xml`** at the mod root uses `<Includes>` to register each file:
```xml
<?xml version="1.0" encoding="utf-8"?>
<Includes>
    <Catalog path="GameData/Terran/NCO/Herc/Herc.xml"/>
    <Catalog path="GameData/Zerg/MyUnit/MyUnit.xml"/>
</Includes>
```

**Each unit file** uses a single `<Catalog>` root containing all data types for that unit in sequence:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Catalog>
    <!-- Button -->
    <CButton id="MyUnit" .../>  

    <!-- Unit -->
    <CUnit id="MyUnit" parent="Generic_Unit_Ground">...</CUnit>

    <!-- Weapon + its effects -->
    <CWeaponLegacy id="MyUnit_Weapon">...</CWeaponLegacy>
    <CEffectDamage id="MyUnit_Weapon@Damage">...</CEffectDamage>

    <!-- Ability + its effects + behaviors -->
    <CAbilEffectTarget id="MyUnit_Ability">...</CAbilEffectTarget>
    <CEffectSet id="MyUnit_Ability@Set">...</CEffectSet>
    <CBehaviorBuff id="MyUnit_Ability@Buff">...</CBehaviorBuff>

    <!-- Actor, Model, Sound -->
    <CActorUnit id="MyUnit" unitName="MyUnit">...</CActorUnit>
    <CModel id="MyUnit" parent="Unit">...</CModel>
    <CSound id="MyUnit@Death" parent="Zerg_ExplosionSmall"/>

    <!-- Requirement -->
    <CRequirement id="MyUnit@Use"/>

    <!-- Data collection — groups entries for the editor UI -->
    <CDataCollectionUnit id="MyUnit">
        <DataRecord Entry="Unit,MyUnit"/>
        <DataRecord Entry="Actor,MyUnit"/>
        <DataRecord Entry="Model,MyUnit"/>
        <DataRecord Entry="Weapon,MyUnit_Weapon"/>
    </CDataCollectionUnit>
</Catalog>
```

**To add a new unit:**
1. Create `GameData/YourFaction/UnitName/UnitName.xml` with a `<Catalog>` root.
2. Add `<Catalog path="GameData/YourFaction/UnitName/UnitName.xml"/>` to `GameData.xml`.

> See [ShadowDragon Base.SC2Data](https://github.com/ShadowDragonSC2/Base.SC2Data) — `GameData.xml` for the include list, and any unit subfolder (e.g. `GameData/Terran/Campaign/NCO/Herc/Herc.xml`) for a complete self-contained real-world example.

---

## XML Basics

```xml
<?xml version="1.0" encoding="utf-8"?>
<Catalog>
    <!-- Each entry has an id and optionally a parent to inherit from -->
    <CUnit id="MyHero" parent="Zergling">
        <!-- Fields that differ from the parent only -->
        <LifeMax value="500"/>
        <ShieldsMax value="0"/>
        <Speed value="4.13"/>
    </CUnit>
</Catalog>
```

**Rules:**
- The `id` attribute is the data key used everywhere else in data and Galaxy.
- If `parent` is omitted, the entry has no explicit parent (inherits from default base).
- Only fields that **differ** from the parent need to be written — everything else inherits.
- `default="1"` marks an entry as the default override for that type.
- Commented-out XML (`<!-- ... -->`) is live documentation left by Blizzard; safe to reference but not active.
- Arrays use `index` to address specific slots: `<WeaponArray index="0" Link="MyWeapon"/>`.

---

## Units (`UnitData.xml`)

File: `Base.SC2Data/GameData/UnitData.xml`  
Types: `CUnit`, `CUnitHero`

### Minimal unit override

```xml
<CUnit id="MyUnit" parent="Marine">
    <Name value="Unit/Name/MyUnit"/>          <!-- references GameStrings.txt -->
    <LifeMax value="200"/>
    <LifeArmor value="1"/>
    <ShieldsMax value="0"/>
    <ShieldsArmor value="0"/>
    <EnergyMax value="0"/>
    <EnergyStart value="0"/>
    <Speed value="2.25"/>
    <Sight value="9"/>
    <Radius value="0.375"/>
    <EditorCategories value="Race:Terran"/>
    <AbilArray index="Move" Link="Move"/>
    <AbilArray index="Attack" Link="Attack"/>
    <AbilArray index="Stop" Link="Stop"/>
    <WeaponArray index="0" Link="MarineWeapon"/>
    <Attributes index="Light" value="1"/>
    <Attributes index="Biological" value="1"/>
    <CargoSize value="1"/>
</CUnit>
```

### Hero unit

```xml
<CUnitHero id="MyHeroUnit" parent="Zergling">
    <LifeMax value="600"/>
    <XP index="0" value="0"/>     <!-- XP thresholds per level -->
    <XP index="1" value="300"/>
    <XP index="2" value="600"/>
    <!-- Hero-specific fields -->
</CUnitHero>
```

### Key unit fields

| Field | Purpose |
|---|---|
| `LifeMax` | Max HP |
| `LifeArmor` | Armor value |
| `ShieldsMax` | Protoss shields |
| `EnergyMax` / `EnergyStart` | Mana pool |
| `Speed` | Movement speed |
| `Sight` | Vision radius |
| `Radius` | Collision radius |
| `Height` | Flight height |
| `AbilArray` | Abilities attached to this unit |
| `WeaponArray` | Weapons attached to this unit |
| `BehaviorArray` | Default behaviors on spawn |
| `CargoSize` | Transport slots consumed |
| `FoodCost` | Supply cost |
| `Attributes` | Light/Heavy/Biological/Mechanical/Psionic/Massive/Structure/Hover |
| `MovementType` | Ground/Fly/Burrowed/Cliff |
| `PlacementRadius` | Footprint radius for placement |
| `EditorCategories` | Organizational tags (Race, AbilityorEffectType, etc.) |

### Alternate-state / morph cost pitfalls

Whenever you override a unit or building cost, you must also override every alternate-state
variant CUnit (Terran `Flying` forms, `SupplyDepotLowered`, TechLab/Reactor add-on variants,
Zerg `Uprooted`/`Burrowed` morphs) — otherwise SC2 charges or refunds the difference on state
change. The confirmed variant ID tables and the confirm-before-writing workflow live in
[references/unit-cost-variants.md](references/unit-cost-variants.md).

### Race supply cap (`RaceData.xml`)

```xml
<CRace id="Prot">
    <StartingUnitArray index="1" Count="12"/>   <!-- starting workers -->
    <FoodCeiling value="275"/>                  <!-- max supply -->
</CRace>
```

---

## Abilities (`AbilData.xml`)

File: `Base.SC2Data/GameData/AbilData.xml`

Ability types map directly to XML element names — see the full list in the
[Ability Subtypes Reference](#ability-subtypes-reference) table below.

### Targeted ability pattern

```xml
<CAbilEffectTarget id="MyBlast">
    <EditorCategories value="Race:Terran,AbilityorEffectType:Units"/>
    <Effect index="0" value="MyBlastEffect"/>       <!-- which effect to fire -->
    <Cost index="0">
        <Vital index="Energy" value="75"/>
        <Cooldown TimeStart="0" TimeUse="12"/>
    </Cost>
    <Range value="7"/>
    <Arc value="360"/>
    <CursorEffect value="MyBlastEffect"/>
    <PrepTime index="0" value="0.5"/>               <!-- cast time (seconds) -->
    <CmdButtonArray index="Execute" DefaultButtonFace="MyBlastButton"/>
    <TargetFilters index="0" value="Visible;Self,Ally,Neutral,Invulnerable,Dead"/>
</CAbilEffectTarget>
```

### Instant cast (no target)

```xml
<CAbilEffectInstant id="MyShield">
    <Cost index="0">
        <Cooldown TimeUse="40"/>
    </Cost>
    <Effect index="0" value="MyShieldEffect"/>
    <CmdButtonArray index="Execute" DefaultButtonFace="MyShieldButton"/>
</CAbilEffectInstant>
```

### Research ability

```xml
<CAbilResearch id="MyBuildingResearch">
    <InfoArray index="Research1" Time="45">
        <Effect value="ResearchMyTech"/>
    </InfoArray>
    <InfoArray index="Research2" Time="60">
        <Effect value="ResearchMyTech2"/>
    </InfoArray>
</CAbilResearch>
```

### Train ability (CAbilTrain) — unit production

`CAbilTrain` controls which units a building can produce and how long each takes. Like `CAbilBuild`, each unit occupies a **sequential numeric slot** (`Train1`, `Train2`, etc.) — the slot number, NOT the unit's catalog ID.

> **Critical pitfall:** Always use `Train1`, `Train2`, etc. Never use the unit catalog ID (e.g. `index="Marine"`) — that silently creates an unused entry.

```xml
<!-- Override Barracks train times -->
<CAbilTrain id="BarracksTrain">
    <InfoArray index="Train1" Time="2.5"/>   <!-- Marine -->
    <InfoArray index="Train2" Time="3.2"/>   <!-- Reaper -->
</CAbilTrain>
```

#### Void.SC2Mod Standard Train Slot Mapping

The confirmed per-building train slot tables (`CommandCenterTrain`, `BarracksTrain`,
`FactoryTrain`, `StarportTrain`, `NexusTrain`, `GatewayTrain`/`WarpGateTrain`,
`RoboticsFacilityTrain`, `StargateTrain`, `LarvaWormhole`) live in
[references/train-build-slot-mappings.md](references/train-build-slot-mappings.md).
All `(None)` slots are confirmed empty — skipping them in an XML override is correct and safe.

---

### Build ability (CAbilBuild) — worker construction

`CAbilBuild` controls which structures a worker unit can construct and how long each takes. Each buildable structure occupies a **sequential numeric slot** in the InfoArray:

> **Critical pitfall:** The `index` attribute is always `Build1`, `Build2`, `Build3`, etc. — a positional slot number. It is **NOT the structure's catalog ID**. Using `index="CommandCenter"` or `index="Nexus"` silently creates a new entry that never overrides the correct slot and has no in-game effect. Always use the numeric `BuildN` format confirmed from the Data Editor's InfoArray panel.

```xml
<!-- Override Terran build times — only specify slots you change -->
<CAbilBuild id="TerranBuild">
    <InfoArray index="Build1"  Time="71"/>   <!-- CommandCenter -->
    <InfoArray index="Build4"  Time="46"/>   <!-- Barracks -->
    <InfoArray index="Build11" Time="43"/>   <!-- Factory -->
</CAbilBuild>
```

#### Void.SC2Mod Standard Build Slot Mapping

The complete active-slot tables for the three worker build abilities (`TerranBuild`,
`ProtossBuild`, `ZergBuild`) live in
[references/train-build-slot-mappings.md](references/train-build-slot-mappings.md).
Slots labelled *(None)* can be omitted from any XML override.

> **Morphs use CAbilMorph, not CAbilBuild:** Zerg tier upgrades (Lair, Hive, Greater Spire) and Terran CC upgrades (Orbital Command, Planetary Fortress) are `CAbilMorph` entries, not `CAbilBuild`. They have separate ability IDs and a different InfoArray key format.

> **Morph cost pitfall — CUnit costs are cumulative:** SC2 calculates the mineral/vespene charged for a morph as `target CUnit cost − source CUnit cost`. If you reduce the source unit's cost (e.g. CommandCenter → 80M) but set the morph target (OrbitalCommand) to only its upgrade delta (30M), the game will *refund* the difference (30−80 = −50M). **Always set morph target CUnit cost to `source cost + upgrade delta`:**
> - `OrbitalCommand` = CC(80M) + upgrade(30M) = **110M**
> - `PlanetaryFortress` = CC(80M) + upgrade(30M) = **110M** minerals, 0V + 8V = **8V**
> - `Lair` = Hatchery(60M) + upgrade(30M) = **90M**, 0V + 5V = **5V**
> - `Hive` = Lair(90M) + upgrade(40M) = **130M**, 5V + 8V = **13V**
> - `GreaterSpire` = Spire(40M) + upgrade(20M) = **60M**, 10V + 8V = **18V**

### Cost fields

| Field | Purpose |
|---|---|
| `Vital index="Energy"` | Energy cost |
| `Vital index="Life"` | HP cost |
| `Cooldown TimeUse` | Cooldown after use (seconds) |
| `Cooldown TimeStart` | Initial cooldown on game start |
| `Charge TimeUse` | Charge-based cooldown |

### TargetFilters

Multiple filter groups separated by `;`. Within a group, values are flags — prefix with `!` to negate:

```xml
<!-- Visible, non-self, non-ally, non-dead targets -->
<TargetFilters index="0" value="Visible;Self,Ally,Dead"/>
```

Common filter terms: `Visible`, `Invulnerable`, `Self`, `Ally`, `Enemy`, `Neutral`, `Dead`, `Ground`, `Air`, `Structure`, `Hero`, `Biological`, `Mechanical`.

---

## Ability Subtypes Reference

| XML Type | Use case |
|---|---|
| `CAbilEffectTarget` | Targeted — range + arc, fires effect at point or unit |
| `CAbilEffectInstant` | No-target instant cast (self-buff, passive trigger) |
| `CAbilBehavior` | Toggle a behavior on/off |
| `CAbilBuild` | Build a structure (button on a worker) |
| `CAbilTrain` | Train a unit at a building |
| `CAbilResearch` | Research an upgrade at a building |
| `CAbilMorph` | Transform the caster unit into a different unit type |
| `CAbilMorphPlacement` | Morph that requires a placement target (e.g. Barracks → Flying) |
| `CAbilHarvest` | Harvest resources (worker gather) |
| `CAbilInteract` | Interact with a target (e.g. repair) |
| `CAbilInventory` | Manage item inventory |
| `CAbilLearn` | Spend XP/points to learn a skill (hero talents) |
| `CAbilMerge` | Merge multiple units into one |
| `CAbilMove` | Override movement command |
| `CAbilQueue` | Queue sub-abilities (used for multi-stage abilities) |
| `CAbilRally` | Set a rally point |
| `CAbilRevive` | Revive a dead hero |
| `CAbilSpecialize` | Hero specialization/talent selection |
| `CAbilStop` | Stop command |
| `CAbilTransport` | Load/unload transport |
| `CAbilWarpTrain` | Train via Warp Gate mechanic |
| `CAbilArmMagazine` | Arm + fire (e.g. nuclear launch: arm first, then fire separately) |

---

## Ability Fields Reference

Detailed field semantics (Set ID shared buttons, Cooldown Location/Operation, Charge System,
State Behavior, Shared Flags, Veterancy gating, Refund Fraction) live in
[references/ability-fields.md](references/ability-fields.md).

---

## Movers (`MoverData.xml`)

File: `Base.SC2Data/GameData/MoverData.xml`

| XML Type | Use |
|---|---|
| `CMoverMissile` | Projectile movement (homing, ballistic, linear) |
| `CMoverAvoid` | Ground unit avoidance mover |
| `CMoverBallistic` | Arc projectile |

```xml
<CMoverMissile id="MyMissile">
    <MotionPhases index="0" MaxSpeed="10"/>   <!-- max speed of the missile -->
</CMoverMissile>

<CMoverAvoid id="Ground2">
    <!-- Ground movement with collision avoidance -->
</CMoverAvoid>
```

---

## Turrets (`TurretData.xml`)

```xml
<CTurret id="MyTurret">
    <YawArc value="360"/>      <!-- rotation arc in degrees (360 = any direction) -->
    <YawRate value="999"/>     <!-- rotation speed (degrees/sec) -->
</CTurret>
```

---

## Buttons (`ButtonData.xml`)

File: `Base.SC2Data/GameData/ButtonData.xml`  
Buttons are the command card icon + tooltip. Each ability's `CmdButtonArray` references a button by id.

```xml
<CButton id="MyAbilityButton">
    <Icon value="Assets\Textures\btn-ability-myability.dds"/>   <!-- 76×76 .dds -->
    <Tooltip value="Abil/Tooltip/MyAbilityButton"/>              <!-- GameStrings key -->
    <Name value="Abil/Name/MyAbilityButton"/>
    <Hotkey value="W"/>
</CButton>
```

Button icon naming convention: `btn-` prefix, 76×76 pixels, `.dds` format.

---

## Requirements (`RequirementData.xml` / `RequirementNodeData.xml`)

Requirements gate abilities, units, or research behind conditions.

```xml
<!-- A compound AND requirement -->
<CRequirement id="HaveBarracksAndArmory">
    <NodeArray index="0" value="CountUnitBarracksCompleteOnly"/>
    <NodeArray index="1" value="CountUnitArmoryCompleteOnly"/>
</CRequirement>

<!-- A node that counts completed buildings -->
<CRequirementCountUnit id="CountUnitBarracksCompleteOnly">
    <Link value="Barracks"/>
    <State value="Complete"/>
</CRequirementCountUnit>
```

---

## Naming Conventions

| Item | Convention |
|---|---|
| Unit id | `PascalCase` matching the unit type name (e.g., `MyHeroZealot`) |
| Ability id | `PascalCase`, typically `UnitNameAbilityName` (e.g., `AlarakPsiOrb`) |
| Button id | Same as ability id (e.g., `AlarakPsiOrb`) |
| Effect id | Same as ability id + effect role suffix (e.g., `AlarakPsiOrbDamage`) |
| Name strings | `"Unit/Name/UnitId"` or `"Abil/Name/AbilId"` — resolved via `GameStrings.txt` |
| EditorCategories | `"Race:Terran,AbilityorEffectType:Units"` |

---

## Data Editor Recommended View Settings

From the Data Editor **View** menu — settings that improve navigation and reduce common confusion:

| Setting | Recommended | Notes |
|---|---|---|
| Toggle Easy Mode | Off | Easy mode hides important fields |
| Display Object List As Tree | Off | Flat list is easier to search |
| Show Object Explorer | On | Useful cross-reference panel |
| Table View | On | Has a search bar for field names |
| Detail View | Off | Slows editor significantly |
| Sort Field By Source | On | Groups base vs. overridden fields |
| Combine Structure View | On | Some array fields break without it |
| Show Field Differences | On | Highlights what your mod overrides vs. parent |
| XML Syntax Highlighting | On | Essential for XML view work |

---

## Best Practices

- Always set `parent` to the closest matching base unit/ability — inherit as much as possible.
- Use `EditorCategories` to keep mod data organized and filterable.
- Only override the fields that differ from the parent. Do not duplicate parent values.
- Commented-out entries (`<!-- ... -->`) are safe to leave — they don't affect gameplay.
- When disabling an array element from a parent, use `index` with an empty or zeroed-out value.
- Test changes in the editor with **View Raw Data** enabled to see actual field IDs.
