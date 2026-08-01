"""Dead of Night macro plan built on AresSC2 native behaviors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ares.behaviors.macro import (
    AutoSupply,
    BuildWorkers,
    ExpansionController,
    GasBuildingController,
    MacroPlan,
    ProductionController,
    SpawnController,
)
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class MacroConfig:
    """Macro targets for the Raynor Dead of Night profile."""

    target_worker_count: int = 66
    target_gas_buildings: int = 4
    max_bases: int = 3
    max_pending_bases: int = 1
    max_production_structures: int = 12
    army_composition: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.army_composition:
            self.army_composition = {
                UnitTypeId.SIEGETANK: {"proportion": 0.20, "priority": 0},
                UnitTypeId.MEDIVAC: {"proportion": 0.15, "priority": 1},
                UnitTypeId.MARINE: {"proportion": 0.50, "priority": 2},
                UnitTypeId.MARAUDER: {"proportion": 0.15, "priority": 3},
            }


class DeadOfNightMacroPlan:
    """Register Ares macro behaviors in explicit execution priority order."""

    def __init__(self, bot: "AresBot", config: MacroConfig | None = None) -> None:
        self.bot = bot
        self.config = config or MacroConfig()
        self.plan = MacroPlan()

    def build(self, base_location: Point2) -> MacroPlan:
        """Build the plan. Ares executes the first behavior that acts."""
        self.plan = MacroPlan()
        self.plan.add(AutoSupply(base_location))
        self.plan.add(BuildWorkers(to_count=self.config.target_worker_count))
        self.plan.add(
            GasBuildingController(
                to_count=self.config.target_gas_buildings,
                max_pending=1,
                closest_to=base_location,
            )
        )
        self.plan.add(
            ExpansionController(
                to_count=self.config.max_bases,
                max_pending=self.config.max_pending_bases,
                check_location_is_safe=True,
                can_afford_check=True,
            )
        )
        self.plan.add(
            SpawnController(
                army_composition_dict=self.config.army_composition,
                ignore_proportions_below_unit_count=8,
                spawn_target=base_location,
            )
        )
        self.plan.add(
            ProductionController(
                army_composition_dict=self.config.army_composition,
                base_location=base_location,
                max_production_structures=self.config.max_production_structures,
            )
        )
        return self.plan

    def register(self, base_location: Point2) -> None:
        """Register the plan with Ares' BehaviorExecutioner."""
        self.bot.register_behavior(self.build(base_location))
