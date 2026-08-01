"""Runnable AresBot subclass for the CMRE AI enhancement project."""

from __future__ import annotations

from typing import Optional

from ares import AresBot

from .enhanced_policy import EnhancedPolicy


class CmreEnhancedBot(AresBot):
    """Use Ares' native lifecycle instead of wrapping raw SC2 observations."""

    def __init__(self, game_step_override: Optional[int] = None) -> None:
        super().__init__(game_step_override)
        self.policy = EnhancedPolicy(self)

    async def on_start(self) -> None:
        await super().on_start()
        await self.policy.on_start()

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        self.policy.on_step()

    async def on_unit_destroyed(self, unit_tag: int) -> None:
        await super().on_unit_destroyed(unit_tag)
        self.policy.on_unit_destroyed(unit_tag)
