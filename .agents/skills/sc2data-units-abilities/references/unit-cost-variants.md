# Unit Cost Pitfalls — Alternate-State CUnit Variants

Reference detail split out of the `sc2data-units-abilities` skill. When a unit or building can
change form, SC2 uses a *separate* `CUnit` catalog entry for the transformed form. If that
alternate form's inherited cost differs from your override, **SC2 charges or refunds the
difference when the transition happens**.

**Rule:** whenever you override a unit or building cost, also override ALL its alternate-state
variant CUnit IDs to match.

## Terran flying building cost pitfall

Several Terran buildings can **lift off** (fly). Each has a *separate* `CUnit` catalog entry with
a `Flying` suffix. If the flying form's inherited cost is higher than the overridden grounded
cost, SC2 charges the difference when the building lifts off or lands.

**Confirmed flying variants** (PlanetaryFortress cannot lift off and has NO flying variant):

| Grounded CUnit | Flying CUnit |
|---|---|
| `CommandCenter` | `CommandCenterFlying` |
| `OrbitalCommand` | `OrbitalCommandFlying` |
| `Barracks` | `BarracksFlying` |
| `Factory` | `FactoryFlying` |
| `Starport` | `StarportFlying` |

## Terran alternate-state building cost pitfall

**SupplyDepotLowered** — when a Supply Depot is lowered underground it becomes a separate
`CUnit`. Always match its cost to `SupplyDepot`.

| Primary CUnit | Alternate CUnit | Trigger |
|---|---|---|
| `SupplyDepot` | `SupplyDepotLowered` | Player lowers/raises depot |

**TechLab add-on variants** — each building that can build a TechLab has its own CUnit
(e.g. `BarracksTechLab`). Always match all three to the generic `TechLab` cost.

| Generic CUnit | Building-specific CUnit |
|---|---|
| `TechLab` | `BarracksTechLab` |
| `TechLab` | `FactoryTechLab` |
| `TechLab` | `StarportTechLab` |

**Reactor add-on variants** — same pattern as TechLab. Always match all three to the generic
`Reactor` cost.

| Generic CUnit | Building-specific CUnit |
|---|---|
| `Reactor` | `BarracksReactor` |
| `Reactor` | `FactoryReactor` |
| `Reactor` | `StarportReactor` |

**Rule:** whenever you override `SupplyDepot`, `TechLab`, or `Reactor`, override all their
variant CUnit IDs to match.

## Zerg morph/burrowed unit cost pitfall

When a Zerg unit can **uproot, burrow, or morph**, SC2 uses a *separate* `CUnit` catalog entry
for the transformed form. If that alternate form's `CostResource` (inherited from the base mod)
is higher than the primary form's overridden cost, SC2 charges the mineral/vespene difference
when the unit transitions between states.

**Confirmed variant IDs:**

| Primary CUnit | Variant CUnit | Transition |
|---|---|---|
| `SpineCrawler` | `SpineCrawlerUprooted` | Uproot/replant |
| `SporeCrawler` | `SporeCrawlerUprooted` | Uproot/replant |
| `SwarmHost` | `SwarmHostBurrowed` | Burrow to attack |
| `Lurker` | `LurkerBurrowed` | Burrow to attack |

**Units with suspected variants — confirm catalog ID with user before writing override:**

| Primary CUnit | Suspected variant | Confirm? |
|---|---|---|
| `Zergling` | `ZerglingBurrowed` | Yes |
| `Drone` | `DroneBurrowed` | Yes |
| `Queen` | `QueenBurrowed` | Yes |
| `Roach` | `RoachBurrowed` | Yes |
| `Baneling` | `BanelingBurrowed` | Yes |
| `Hydralisk` | `HydraliskBurrowed` | Yes |
| `Infestor` | `InfestorBurrowed` | Yes |
| `Ultralisk` | `UltraliskBurrowed` | Yes |
| `Viper` | `ViperBurrowed` | Yes |

**Workflow:** When modifying any Zerg unit cost, check `sc2-units-reference` for known variants.
If the variant ID is not in the confirmed list above, **ask the user to verify the catalog ID**
from the SC2 Data Editor before writing the `CUnit` override.
