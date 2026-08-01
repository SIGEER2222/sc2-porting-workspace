"""Ares-native policy coordinator for the Dead of Night profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId

from .combat_maneuver import DeadOfNightCombatManeuver, MicroConfig
from .macro_plan import DeadOfNightMacroPlan, MacroConfig

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class EnhancedPolicyConfig:
    macro: MacroConfig = field(default_factory=MacroConfig)
    micro: MicroConfig = field(default_factory=MicroConfig)


class EnhancedPolicy:
    """Coordinate macro registration and combat registration in an Ares bot."""

    def __init__(
        self, bot: "AresBot", config: EnhancedPolicyConfig | None = None
    ) -> None:
        self.bot = bot
        self.config = config or EnhancedPolicyConfig()
        self.macro = DeadOfNightMacroPlan(bot, self.config.macro)
        self.combat: DeadOfNightCombatManeuver | None = None
        self.initialized = False

    async def on_start(self) -> None:
        """Register macro behavior after Ares has initialized its managers."""
        base_position = self.bot.start_location
        self.macro.register(base_position)
        self.combat = DeadOfNightCombatManeuver(
            self.bot, self.bot.mediator, base_position, self.config.micro
        )
        self.initialized = True

    def on_step(self) -> None:
        """Register current combat behaviors for this Ares step."""
        if not self.combat:
            return

        combat_units = self.bot.units.filter(
            lambda unit: (
                unit.type_id
                not in {
                    UnitTypeId.SCV,
                    UnitTypeId.MULE,
                    UnitTypeId.LARVA,
                    UnitTypeId.EGG,
                }
                and not unit.is_structure
            )
        )
        self.combat.register_for_units(combat_units)

        for unit in combat_units:
            if unit.tag not in self.bot.mediator.get_unit_role_dict.get(
                UnitRole.DEFENDING, set()
            ):
                self.bot.mediator.assign_role(tag=unit.tag, role=UnitRole.DEFENDING)

    def on_unit_destroyed(self, unit_tag: int) -> None:
        if self.combat:
            self.combat.clear(unit_tag)

    def status(self) -> dict:
        army = self.bot.units.filter(
            lambda unit: not unit.is_structure and unit.type_id != UnitTypeId.SCV
        )
        return {
            "initialized": self.initialized,
            "bases": len(self.bot.townhalls),
            "workers": len(self.bot.workers),
            "army_supply": self.bot.get_total_supply(army),
        }


def create_enhanced_policy(
    bot: "AresBot", config: EnhancedPolicyConfig | None = None
) -> EnhancedPolicy:
    return EnhancedPolicy(bot, config)
