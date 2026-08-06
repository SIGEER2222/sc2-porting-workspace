# Void.SC2Mod Standard Train & Build Slot Mappings

Reference detail split out of the `sc2data-units-abilities` skill. These tables are the confirmed
slot mappings for `CAbilTrain` and `CAbilBuild` in `Mods/Void.SC2Mod`, verified from Data Editor
screenshots. All `(None)` slots are confirmed empty — do not assign them; skipping them in an XML
override is correct and safe.

> **Critical pitfall (both ability types):** the `index` attribute is always a positional slot
> (`Train1`, `Build1`, ...), **not** a unit or structure catalog ID. Using a catalog ID silently
> creates an unused entry with no in-game effect.

## Train Slot Mapping (CAbilTrain)

**Terran — `CommandCenterTrain`** (CC / OC / PF):

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | SCV | `SCV` | 17 |

**Terran — `BarracksTrain`**:

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | Marine | `Marine` | 25 |
| `Train2` | Reaper | `Reaper` | 32 |
| `Train3` | Ghost | `Ghost` | 29 |
| `Train4` | Marauder | `Marauder` | 30 |

**Terran — `FactoryTrain`**:

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | *(None)* | — | — |
| `Train2` | Siege Tank | `SiegeTank` | 32 |
| `Train3` | *(None)* | — | — |
| `Train4` | *(None)* | — | — |
| `Train5` | Thor | `Thor` | 60 |
| `Train6` | Hellion | `Hellion` | 30 |
| `Train7` | Hellbat (Battle Mode) | `Hellbat` | 30 |
| `Train8` | Cyclone | `Cyclone` | 36 |
| `Train9`–`Train24` | *(None)* | — | — |
| `Train25` | Widow Mine | `WidowMine` | 40 |

**Terran — `StarportTrain`**:

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | Medivac | `Medivac` | 30 |
| `Train2` | Banshee | `Banshee` | 43 |
| `Train3` | Raven | `Raven` | 43 |
| `Train4` | Battlecruiser | `Battlecruiser` | 90 |
| `Train5` | Viking (Fighter Mode) | `Viking` | 32 |
| `Train6` | *(None)* | — | — |
| `Train7` | Liberator (AA) | `Liberator` | 43 |

**Protoss — `NexusTrain`**:

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | Probe | `Probe` | 17 |

**Protoss — `GatewayTrain` and `WarpGateTrain`** (identical slot layout; both must be overridden together):

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | Zealot | `Zealot` | 38 |
| `Train2` | Stalker | `Stalker` | 42 |
| `Train3` | *(None)* | — | — |
| `Train4` | High Templar | `HighTemplar` | 55 |
| `Train5` | Dark Templar | `DarkTemplar` | 55 |
| `Train6` | Sentry | `Sentry` | 42 |
| `Train7` | Adept | `Adept` | 40 |

**Protoss — `RoboticsFacilityTrain`**:

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | Warp Prism (Transport Mode) | `WarpPrism` | 36 |
| `Train2` | Observer | `Observer` | 21 |
| `Train3` | Colossus | `Colossus` | 54 |
| `Train4` | Immortal | `Immortal` | 39 |

**Protoss — `StargateTrain`**:

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | Phoenix | `Phoenix` | 35 |
| `Train2` | *(None)* | — | — |
| `Train3` | Carrier | `Carrier` | 86 |
| `Train4` | *(None)* | — | — |
| `Train5` | Void Ray | `VoidRay` | 43 |
| `Train6` | *(None)* | — | — |
| `Train7` | *(None)* | — | — |
| `Train8` | *(None)* | — | — |
| `Train9` | Oracle | `Oracle` | 37 |
| `Train10` | Tempest | `Tempest` | 54 |

**Zerg — `LarvaWormhole`** (all larva morphs share one ability):

| Slot | Unit | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Train1` | Drone | `Drone` | 17 |
| `Train2` | Zergling | `Zergling` | 24 |
| `Train3` | Overlord | `Overlord` | 25 |
| `Train4` | Hydralisk | `Hydralisk` | 33 |
| `Train5` | Mutalisk | `Mutalisk` | 33 |
| `Train6` | *(None)* | — | — |
| `Train7` | Ultralisk | `Ultralisk` | 55 |
| `Train8` | *(None)* | — | — |
| `Train9` | *(None)* | — | — |
| `Train10` | Roach | `Roach` | 27 |
| `Train11` | Infestor (Spellcaster) | `Infestor` | 50 |
| `Train12` | Corruptor | `Corruptor` | 40 |
| `Train13` | Viper | `Viper` | 40 |
| `Train14` | *(None)* | — | — |
| `Train15` | Swarm Host | `SwarmHost` | 36 |

## Build Slot Mapping (CAbilBuild)

The three worker build abilities (`TerranBuild`, `ProtossBuild`, `ZergBuild`) are defined in
`Mods/Void.SC2Mod`. Slots labelled *(None)* exist in the editor's array but have no building
assigned — they can be omitted from any XML override.

**TerranBuild** — SCV (`id="TerranBuild"`):

| Index | Building | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Build1` | Command Center | `CommandCenter` | 71 |
| `Build2` | Supply Depot | `SupplyDepot` | 21 |
| `Build3` | Refinery | `Refinery` | 21 |
| `Build4` | Barracks | `Barracks` | 46 |
| `Build5` | Engineering Bay | `EngineeringBay` | 25 |
| `Build6` | Missile Turret | `MissileTurret` | 18 |
| `Build7` | Bunker | `Bunker` | 29 |
| `Build8` | Refinery (Rich) | `RefineryRich` | 21 |
| `Build9` | Sensor Tower | `SensorTower` | 18 |
| `Build10` | Ghost Academy | `GhostAcademy` | 29 |
| `Build11` | Factory | `Factory` | 43 |
| `Build12` | Starport | `Starport` | 36 |
| `Build13` | *(None)* | — | — |
| `Build14` | Armory | `Armory` | 46 |
| `Build15` | *(None)* | — | — |
| `Build16` | Fusion Core | `FusionCore` | 46 |

**ProtossBuild** — Probe (`id="ProtossBuild"`):

| Index | Building | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Build1` | Nexus | `Nexus` | 71 |
| `Build2` | Pylon | `Pylon` | 21 |
| `Build3` | Assimilator | `Assimilator` | 21 |
| `Build4` | Gateway | `Gateway` | 46 |
| `Build5` | Forge | `Forge` | 25 |
| `Build6` | Fleet Beacon | `FleetBeacon` | 43 |
| `Build7` | Twilight Council | `TwilightCouncil` | 36 |
| `Build8` | Photon Cannon | `PhotonCannon` | 29 |
| `Build9` | *(None)* | — | — |
| `Build10` | Stargate | `Stargate` | 43 |
| `Build11` | Templar Archives | `TemplarArchive` | 36 |
| `Build12` | Dark Shrine | `DarkShrine` | 100 |
| `Build13` | Robotics Bay | `RoboticsBay` | 46 |
| `Build14` | Robotics Facility | `RoboticsFacility` | 46 |
| `Build15` | Cybernetics Core | `CyberneticsCore` | 36 |

**ZergBuild** — Drone (`id="ZergBuild"`):

| Index | Building | Editor ID | Standard Time (s) |
|---|---|---|---|
| `Build1` | Hatchery | `Hatchery` | 71 |
| `Build2` | Creep Tumor | `CreepTumor` | 15 |
| `Build3` | Extractor | `Extractor` | 21 |
| `Build4` | Spawning Pool | `SpawningPool` | 46 |
| `Build5` | Evolution Chamber | `EvolutionChamber` | 25 |
| `Build6` | Hydralisk Den | `HydraliskDen` | 33 |
| `Build7` | Spire | `Spire` | 71 |
| `Build8` | Ultralisk Cavern | `UltraliskCavern` | 46 |
| `Build9` | Infestation Pit | `InfestationPit` | 36 |
| `Build10` | Nydus Network | `NydusNetwork` | 36 |
| `Build11` | Baneling Nest | `BanelingNest` | 43 |
| `Build12` | *(None)* | — | — |
| `Build13` | *(None)* | — | — |
| `Build14` | Roach Warren | `RoachWarren` | 39 |
| `Build15` | Spine Crawler | `SpineCrawler` | 36 |
| `Build16` | Spore Crawler | `SporeCrawler` | 21 |

> **Morphs use CAbilMorph, not CAbilBuild:** Zerg tier upgrades (Lair, Hive, Greater Spire) and
> Terran CC upgrades (Orbital Command, Planetary Fortress) are `CAbilMorph` entries, not
> `CAbilBuild`. They have separate ability IDs and a different InfoArray key format.

> **Morph cost pitfall — CUnit costs are cumulative:** SC2 calculates the mineral/vespene charged
> for a morph as `target CUnit cost − source CUnit cost`. If you reduce the source unit's cost
> (e.g. CommandCenter → 80M) but set the morph target (OrbitalCommand) to only its upgrade delta
> (30M), the game will *refund* the difference (30−80 = −50M). **Always set morph target CUnit
> cost to `source cost + upgrade delta`:**
> - `OrbitalCommand` = CC(80M) + upgrade(30M) = **110M**
> - `PlanetaryFortress` = CC(80M) + upgrade(30M) = **110M** minerals, 0V + 8V = **8V**
> - `Lair` = Hatchery(60M) + upgrade(30M) = **90M**, 0V + 5V = **5V**
> - `Hive` = Lair(90M) + upgrade(40M) = **130M**, 5V + 8V = **13V**
> - `GreaterSpire` = Spire(40M) + upgrade(20M) = **60M**, 10V + 8V = **18V**
