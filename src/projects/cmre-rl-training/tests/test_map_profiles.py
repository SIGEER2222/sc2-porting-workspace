"""Stage 06 tests for deterministic map profiles and context encoding."""

from __future__ import annotations

import unittest

from cmre_rl_training.map_profiles import (
    MAP_CONTEXT_NAMES,
    MapProfileRegistry,
    map_context_schema_hash,
    normalize_map_id,
)


class MapProfileTests(unittest.TestCase):
    def test_known_map_and_unknown_fallback_are_deterministic(self) -> None:
        registry = MapProfileRegistry()
        known = registry.resolve("Dead of Night.SC2Map")
        unknown_a = registry.resolve("A Newly Published Map")
        unknown_b = registry.resolve("A Newly Published Map")

        self.assertEqual(known.map_id, "dead-of-night")
        self.assertTrue(known.known)
        self.assertFalse(unknown_a.known)
        self.assertEqual(unknown_a, unknown_b)
        self.assertEqual(len(unknown_a.context_vector()), len(MAP_CONTEXT_NAMES))
        self.assertEqual(unknown_a.context_dim, 8)

    def test_context_hash_is_stable_and_normalization_is_bounded(self) -> None:
        self.assertEqual(map_context_schema_hash(), map_context_schema_hash())
        self.assertEqual(normalize_map_id("Temple of the Past"), "temple-of-the-past")
        self.assertEqual(len(set(MapProfileRegistry().resolve("Void Launch").context_vector())), 3)

    def test_point_for_prefers_live_enemy_centroid(self) -> None:
        profile = MapProfileRegistry().resolve("Mist Opportunities")
        point = profile.point_for(
            "attack",
            {"visible_enemies": [{"entity_id": 1, "x": 10, "y": 20}, {"entity_id": 2, "x": 30, "y": 40}]},
        )
        self.assertEqual(point, (20.0, 30.0))


if __name__ == "__main__":
    unittest.main()
