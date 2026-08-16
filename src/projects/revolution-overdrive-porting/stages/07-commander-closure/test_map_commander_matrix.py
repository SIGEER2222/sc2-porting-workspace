import json
import unittest
from pathlib import Path


STAGE_ROOT = Path(__file__).resolve().parent
MATRIX = (
    STAGE_ROOT.parents[4]
    / "artifacts"
    / "projects"
    / "revolution-overdrive-porting"
    / "stage07-commander-closure"
    / "map-commander-matrix.json"
)


class MapCommanderMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    def test_matrix_is_complete_and_excludes_arcade_entry(self):
        self.assertEqual(self.matrix["mapCount"], 30)
        self.assertEqual(self.matrix["commanderCount"], 5)
        self.assertEqual(len(self.matrix["cells"]), 150)
        self.assertNotIn("tarcade.SC2Map", self.matrix["maps"])
        self.assertEqual(
            {cell["map"] for cell in self.matrix["cells"]},
            set(self.matrix["maps"]),
        )
        self.assertEqual(
            {cell["commander"] for cell in self.matrix["cells"]},
            set(self.matrix["commanders"]),
        )

    def test_every_cell_has_static_and_runtime_contract_fields(self):
        for cell in self.matrix["cells"]:
            with self.subTest(cell=f'{cell["map"]}/{cell["commander"]}'):
                self.assertIn(cell["status"], {"runtime_pass", "runtime_pending", "blocked", "unsupported"})
                self.assertTrue(cell["mapScript"])
                self.assertTrue(cell["staticRoster"])
                self.assertTrue(cell["adapterRule"])
                self.assertTrue(cell["targetCatalogs"])
                self.assertTrue(cell["protectedPlayers"])
                self.assertTrue(cell["evidenceDir"])

    def test_known_runtime_passes_have_current_evidence(self):
        expected = {
            ("thanson01.SC2Map", "Iron"),
            ("thanson01.SC2Map", "Coverts"),
            ("thanson01.SC2Map", "Umojan"),
            ("thanson01.SC2Map", "Pirate"),
            ("thanson01.SC2Map", "Madness"),
            ("thanson02.SC2Map", "Iron"),
            ("thanson03a.SC2Map", "Iron"),
        }
        actual = {
            (cell["map"], cell["commander"])
            for cell in self.matrix["cells"]
            if cell["status"] == "runtime_pass"
        }
        self.assertEqual(actual, expected)
        for map_name, commander in expected:
            cell = next(
                item
                for item in self.matrix["cells"]
                if item["map"] == map_name and item["commander"] == commander
            )
            self.assertTrue(cell["runtimeEvidence"])


if __name__ == "__main__":
    unittest.main()
