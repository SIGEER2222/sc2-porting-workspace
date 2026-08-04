"""Tests for action alignment and encoder integration (G2, G3)."""

from __future__ import annotations

import sys
import unittest

# Add cross-project paths for integration tests
_REPO_ROOT = r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
_NEURO_PATH = _REPO_ROOT + r"\src\projects\cmre-neuro-adapter"
_VIBE_PATH = _REPO_ROOT + r"\src\projects\cmre-porting"
for _p in (_NEURO_PATH, _VIBE_PATH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cmre_rl_training.action_space import ACTION_NAMES


class ActionAlignmentTests(unittest.TestCase):
    """G2: Verify ACTION_NAMES matches BASIC_ACTION_ROUTES 1:1."""

    def test_action_names_match_basic_routes(self) -> None:
        from cmre_neuro_adapter.neuro.basic_actions import (
            BASIC_ACTION_ROUTES,
        )

        route_keys = sorted(BASIC_ACTION_ROUTES.keys())
        our_names = sorted(ACTION_NAMES)
        self.assertEqual(
            our_names,
            route_keys,
            f"action mismatch: extra={set(our_names)-set(route_keys)}, "
            f"missing={set(route_keys)-set(our_names)}",
        )

    def test_action_count_is_19(self) -> None:
        from cmre_neuro_adapter.neuro.basic_actions import (
            BASIC_ACTION_ROUTES,
        )

        self.assertEqual(len(ACTION_NAMES), len(BASIC_ACTION_ROUTES))


class EncoderIntegrationTests(unittest.TestCase):
    """G3: Verify encode_rl_observation produces correct-length vector."""

    def test_feature_names_available(self) -> None:
        from vibe.ml.encoder import FEATURE_NAMES

        self.assertGreater(len(FEATURE_NAMES), 0)

    def test_encode_produces_correct_length(self) -> None:
        from vibe.ml.encoder import FEATURE_NAMES
        from cmre_rl_training.observation import encode_rl_observation

        obs = {
            "loop": 0,
            "player_id": 1,
            "own_units": [],
            "visible_enemies": [],
            "visible_allies": [],
            "resources": {
                "minerals": 100,
                "vespene": 50,
                "supply_used": 5,
                "supply_cap": 11,
            },
            "mission": {
                "phase": "active",
                "night": 0,
                "wave": 0,
                "progress": 0.0,
            },
            "mineral_fields": [{"entity_id": 200, "x": 80, "y": 90}],
            "vespene_geysers": [{"entity_id": 201, "x": 82, "y": 88}],
            "tech": {"completed_upgrades": [], "researching": []},
        }
        vector = encode_rl_observation(obs)
        self.assertEqual(len(vector), len(FEATURE_NAMES))

    def test_rl_feature_count_matches(self) -> None:
        from vibe.ml.encoder import FEATURE_NAMES
        from cmre_rl_training.observation import rl_feature_count

        self.assertEqual(rl_feature_count(), len(FEATURE_NAMES))

    def test_schema_hash_stable(self) -> None:
        from vibe.ml.encoder import feature_schema_hash

        h1 = feature_schema_hash()
        h2 = feature_schema_hash()
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # SHA-256 hex


if __name__ == "__main__":
    unittest.main()
