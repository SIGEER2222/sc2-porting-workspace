"""Tests for action distribution + illegal-action metrics (plan Stage 3 / 5)."""

from __future__ import annotations

import math
import unittest

import numpy as np

from cmre_rl_training.action_metrics import (
    aggregate_action_summaries,
    summarize_action_trace,
    summarize_rollout_actions,
)
from cmre_rl_training.action_space import ACTION_NAMES, NUM_ACTIONS
from cmre_rl_training.ppo import RolloutBuffer


def _make_buffer(actions: list[int], illegal_mask_indices: set[int]) -> RolloutBuffer:
    """Build a RolloutBuffer with the given action sequence.

    ``illegal_mask_indices`` marks which step indices should have their chosen
    action masked as illegal.
    """

    buffer = RolloutBuffer(capacity=len(actions), obs_dim=4, action_dim=1, mask_dim=NUM_ACTIONS)
    for step_idx, action_idx in enumerate(actions):
        mask = np.ones(NUM_ACTIONS, dtype=bool)
        if step_idx in illegal_mask_indices:
            mask[action_idx] = False
        buffer.store(
            obs=np.zeros(4, dtype=np.float32),
            action=np.array([action_idx], dtype=np.int64),
            logprob=np.zeros(1, dtype=np.float32),
            value=np.zeros(1, dtype=np.float32),
            reward=0.0,
            done=False,
            mask=mask,
        )
    return buffer


class SummarizeRolloutActionsTests(unittest.TestCase):
    def test_distribution_counts_match_actions(self) -> None:
        actions = [0, 0, 1, 2, 0]
        buffer = _make_buffer(actions, illegal_mask_indices=set())
        summary = summarize_rollout_actions(buffer)
        self.assertEqual(summary["n_steps"], 5)
        self.assertEqual(summary["action_distribution"][ACTION_NAMES[0]], 3)
        self.assertEqual(summary["action_distribution"][ACTION_NAMES[1]], 1)
        self.assertEqual(summary["action_distribution"][ACTION_NAMES[2]], 1)
        self.assertEqual(summary["illegal_action_count"], 0)
        self.assertAlmostEqual(summary["illegal_action_rate"], 0.0)
        self.assertEqual(summary["distinct_actions_used"], 3)

    def test_illegal_action_rate_detected(self) -> None:
        actions = [3, 3, 3]
        # Mark step 0's chosen action (3) as masked => illegal.
        buffer = _make_buffer(actions, illegal_mask_indices={0})
        summary = summarize_rollout_actions(buffer)
        self.assertEqual(summary["illegal_action_count"], 1)
        self.assertAlmostEqual(summary["illegal_action_rate"], 1 / 3)

    def test_entropy_is_zero_for_single_action(self) -> None:
        buffer = _make_buffer([5, 5, 5, 5], illegal_mask_indices=set())
        summary = summarize_rollout_actions(buffer)
        self.assertAlmostEqual(summary["action_entropy_nats"], 0.0)
        self.assertEqual(summary["distinct_actions_used"], 1)

    def test_entropy_max_for_uniform(self) -> None:
        # 4 distinct actions, equal counts => entropy = ln(4).
        actions = [0, 1, 2, 3]
        buffer = _make_buffer(actions, illegal_mask_indices=set())
        summary = summarize_rollout_actions(buffer)
        self.assertAlmostEqual(summary["action_entropy_nats"], math.log(4), places=5)

    def test_top_actions_returns_highest_frequency(self) -> None:
        actions = [0, 0, 0, 1, 1, 2]
        buffer = _make_buffer(actions, illegal_mask_indices=set())
        summary = summarize_rollout_actions(buffer)
        self.assertEqual(summary["top_actions"][0]["action"], ACTION_NAMES[0])
        self.assertEqual(summary["top_actions"][0]["count"], 3)

    def test_normalized_distribution_sums_to_one(self) -> None:
        buffer = _make_buffer([0, 1, 2, 0], illegal_mask_indices=set())
        summary = summarize_rollout_actions(buffer)
        total = sum(summary["action_distribution_normalized"].values())
        self.assertAlmostEqual(total, 1.0)


class AggregateActionSummariesTests(unittest.TestCase):
    def test_aggregate_merges_counts_and_recomputes(self) -> None:
        buf_a = _make_buffer([0, 0, 1], illegal_mask_indices=set())
        buf_b = _make_buffer([0, 2, 2], illegal_mask_indices={1})
        merged = aggregate_action_summaries([
            summarize_rollout_actions(buf_a),
            summarize_rollout_actions(buf_b),
        ])
        self.assertEqual(merged["n_steps"], 6)
        self.assertEqual(merged["action_distribution"][ACTION_NAMES[0]], 3)
        self.assertEqual(merged["action_distribution"][ACTION_NAMES[2]], 2)
        self.assertEqual(merged["illegal_action_count"], 1)
        self.assertAlmostEqual(merged["illegal_action_rate"], 1 / 6)


class ActionTraceSummaryTests(unittest.TestCase):
    def test_runtime_failures_are_reported_as_illegal_action_rate(self) -> None:
        summary = summarize_action_trace([
            {"action_id": "produce_unit", "success": True, "translated": True, "errors": []},
            {"action_id": "build_structure", "success": False, "translated": True, "errors": ["NotSupported"]},
            {"action_id": "attack_units", "success": False, "translated": False, "error": "no target"},
        ])
        self.assertEqual(summary["attempt_count"], 3)
        self.assertEqual(summary["success_count"], 1)
        self.assertEqual(summary["failure_count"], 2)
        self.assertEqual(summary["translated_failure_count"], 1)
        self.assertEqual(summary["error_count"], 2)
        self.assertAlmostEqual(summary["action_success_rate"], 1 / 3)
        self.assertAlmostEqual(summary["illegal_action_rate"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
