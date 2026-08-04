"""Tests for observation normalization and encoding (G3)."""

from __future__ import annotations

import unittest

from cmre_rl_training.observation import (
    _FALLBACK_FEATURE_NAMES,
    encode_rl_observation,
    normalize_observation,
    rl_feature_count,
)


class NormalizeObservationTests(unittest.TestCase):
    def test_fills_missing_fields(self) -> None:
        raw = {"loop": 5, "player_id": 1, "own_units": []}
        norm = normalize_observation(raw)
        self.assertIn("visible_enemies", norm)
        self.assertIn("visible_allies", norm)
        self.assertIn("resources", norm)
        self.assertIn("mission", norm)
        self.assertIn("mineral_fields", norm)
        self.assertIn("vespene_geysers", norm)
        self.assertIn("tech", norm)

    def test_tech_defaults(self) -> None:
        norm = normalize_observation({})
        tech = norm["tech"]
        self.assertIn("completed_upgrades", tech)
        self.assertIn("researching", tech)

    def test_preserves_existing_fields(self) -> None:
        raw = {
            "own_units": [{"entity_id": 1}],
            "mineral_fields": [{"entity_id": 200}],
        }
        norm = normalize_observation(raw)
        self.assertEqual(len(norm["own_units"]), 1)
        self.assertEqual(len(norm["mineral_fields"]), 1)

    def test_types_are_correct(self) -> None:
        norm = normalize_observation({"loop": "5", "player_id": "1"})
        self.assertIsInstance(norm["loop"], int)
        self.assertIsInstance(norm["player_id"], int)
        self.assertIsInstance(norm["own_units"], list)
        self.assertIsInstance(norm["resources"], dict)


class EncodeRlObservationTests(unittest.TestCase):
    def test_returns_float_list(self) -> None:
        obs = {
            "loop": 0,
            "player_id": 1,
            "own_units": [],
            "visible_enemies": [],
            "resources": {"minerals": 50, "vespene": 0,
                          "supply_used": 5, "supply_cap": 11},
            "mission": {"progress": 0.0, "night": 0},
        }
        vector = encode_rl_observation(obs)
        self.assertIsInstance(vector, list)
        self.assertTrue(all(isinstance(v, float) for v in vector))

    def test_fallback_length_matches_feature_count(self) -> None:
        count = rl_feature_count()
        obs = normalize_observation({})
        vector = encode_rl_observation(obs)
        self.assertEqual(len(vector), count)

    def test_fallback_feature_names_defined(self) -> None:
        self.assertGreater(len(_FALLBACK_FEATURE_NAMES), 0)

    def test_encoding_is_deterministic(self) -> None:
        obs = normalize_observation({
            "resources": {"minerals": 100, "vespene": 50,
                          "supply_used": 10, "supply_cap": 20},
            "mission": {"progress": 0.5, "night": 1},
        })
        v1 = encode_rl_observation(obs)
        v2 = encode_rl_observation(obs)
        self.assertEqual(v1, v2)


if __name__ == "__main__":
    unittest.main()
