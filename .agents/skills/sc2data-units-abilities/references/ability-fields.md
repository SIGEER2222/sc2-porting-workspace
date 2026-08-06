# Ability Fields Reference

Reference detail split out of the `sc2data-units-abilities` skill.

## Set ID — shared command buttons

`Set ID` is a string shared across multiple abilities. When a player issues an order or sends a
unit to a selection with a `Set ID`, **all abilities with the same Set ID** on that unit respond.
Used for `BurrowDown`/`BurrowUp` so holding a `Burrow` key issues for the correct morph ability:

```xml
<CAbilMorph id="BurrowDown_Zergling">
    <CmdButtonArray index="Execute" DefaultButtonFace="Burrow" SetId="BrwD"/>
</CAbilMorph>
<CAbilMorph id="BurrowDown_Roach">
    <CmdButtonArray index="Execute" DefaultButtonFace="Burrow" SetId="BrwD"/>
</CAbilMorph>
```

## Cooldown Location

Controls which scope the cooldown is shared across:

| Value | Meaning |
|---|---|
| `Ability` | Default — cooldown is per-ability instance on this unit |
| `Unit` | Shared across all morphed forms of the same unit |
| `Player` | All units of this player share one cooldown (global per-player) |
| `Global` | All players share one cooldown (fully global) |

## Cooldown Operation

How a dynamic cooldown modification (e.g. from an upgrade or behavior) is applied:

| Value | Effect |
|---|---|
| `Add` | Add to remaining cooldown |
| `Add if Not In Cooldown` | Add only if ability is not currently on cooldown |
| `Max` | Set to whichever is larger (current vs. new) |
| `Min` | Set to whichever is smaller |
| `Multiply` | Multiply remaining cooldown |
| `Set` | Override remaining cooldown directly |

## Charge System

Abilities with charges can be used multiple times before triggering a cooldown:

| Field | Purpose |
|---|---|
| `Count Max` | Maximum charge count |
| `Count Start` | Charges available at game start |
| `Count Use` | Charges consumed per use (usually 1) |
| `Time Start` | Initial recharge time |
| `Time Use` | Recharge time per charge restored |
| `Time Delay` | Wait after all charges depleted before recharge begins |
| `Hide Count` | Suppress the charge counter in the UI |

## State Behavior

`State Behavior` links a behavior to the ability's lifecycle — the behavior is created when the
ability's state changes (created/destroyed/enabled/disabled). Useful for passive effects that
mirror ability availability.

## Shared Flags

| Flag | Effect |
|---|---|
| `Disable While Dead` | Automatically disable ability when unit is dead |
| `Disabled` | Start disabled by default (enable via effect or script) |
| `Register Charge Event` | Allow actor events for charge state changes |
| `Register Cooldown Event` | Allow actor events for cooldown state changes |
| `Skip Preload` | Do not preload ability assets |
| `Snap Target To Unit Radius` | Force-snap target to the edge of the target unit's radius |

## Veterancy Level Min / Skip

Used with hero abilities to gate or skip levels:

- `Veterancy Level Min` — minimum level before this ability is available (for tiered hero abilities)
- `Veterancy Level Skip` — if leveling skips past this level (from bonus XP), behaviour is defined here

## Refund Fraction

`-1` means 100% refund of resources if the ability is cancelled before its "Refundable Stage"
(e.g. cancelled mid-build).
