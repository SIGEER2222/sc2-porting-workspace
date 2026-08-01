"""Victory-time comparison facade for tactical balance experiments.

This module keeps the public comparison entry point separate from the replay
runner while reusing the same deterministic simulation implementation.
"""

from __future__ import annotations

from .consumers.tactical import AggregatedMetrics, Strategy, _aggregate
from .replay_simulation import VictoryTimeComparison, compare_strategies


def run_strategy_seeds(
    strategy: Strategy,
    scenario_dict: dict,
    seeds: list[int],
    ally_player_id: int = 1,
    max_loops: int = 15000,
) -> AggregatedMetrics:
    """Run one strategy over a seed set and aggregate victory-time metrics."""
    return _aggregate(strategy, scenario_dict, seeds, ally_player_id, max_loops)


__all__ = [
    "AggregatedMetrics",
    "VictoryTimeComparison",
    "compare_strategies",
    "run_strategy_seeds",
]
