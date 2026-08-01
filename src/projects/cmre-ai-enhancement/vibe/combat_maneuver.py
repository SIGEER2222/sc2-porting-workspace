"""Dead of Night combat behaviors built on AresSC2 primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    KeepUnitSafe,
    SiegeTankDecision,
    ShootTargetInRange,
)
from ares.consts import UnitTreeQueryType
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

if TYPE_CHECKING:
    from ares import AresBot
    from ares.managers.manager_mediator import ManagerMediator


@dataclass
class MicroConfig:
    """Combat thresholds for the profile."""

    base_defense_range: float = 15.0
    support_range: float = 12.0


class DeadOfNightCombatManeuver:
    """Create one ordered Ares maneuver per active combat unit."""

    def __init__(
        self,
        bot: "AresBot",
        mediator: "ManagerMediator",
        base_position: Point2,
        config: MicroConfig | None = None,
    ) -> None:
        self.bot = bot
        self.mediator = mediator
        self.base_position = base_position
        self.config = config or MicroConfig()
        self._maneuvers: dict[int, CombatManeuver] = {}

    def register_for_units(self, units: Units) -> None:
        """Register current combat maneuvers for the next Ares step."""
        for unit in units:
            self.bot.register_behavior(self._maneuver_for(unit))

    def _maneuver_for(self, unit: Unit) -> CombatManeuver:
        maneuver = CombatManeuver()
        self._maneuvers[unit.tag] = maneuver

        grid = (
            self.mediator.get_air_grid
            if unit.is_flying
            else self.mediator.get_ground_grid
        )
        maneuver.add(KeepUnitSafe(unit, grid))

        close_enemy = self._close_enemies(unit)
        if unit.type_id in {UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}:
            maneuver.add(
                SiegeTankDecision(
                    unit=unit,
                    close_enemy=list(close_enemy),
                    target=self._attack_target(unit),
                    stay_sieged_near_target=True,
                )
            )
        elif close_enemy:
            maneuver.add(ShootTargetInRange(unit, close_enemy))

        maneuver.add(AMove(unit, self._attack_target(unit)))
        return maneuver

    def _close_enemies(self, unit: Unit) -> Units:
        query = (
            UnitTreeQueryType.EnemyAir
            if unit.is_flying
            else UnitTreeQueryType.EnemyGround
        )
        return self.mediator.get_units_in_range(
            start_points=[unit.position],
            distances=self.config.support_range,
            query_tree=query,
        )[0]

    def _attack_target(self, unit: Unit) -> Point2 | Unit:
        nearby = self._close_enemies(unit)
        if nearby:
            return nearby.closest_to(unit)

        if self.bot.enemy_units:
            return self.bot.enemy_units.closest_to(unit)

        return self.bot.enemy_start_locations[0]

    def clear(self, unit_tag: int) -> None:
        self._maneuvers.pop(unit_tag, None)
