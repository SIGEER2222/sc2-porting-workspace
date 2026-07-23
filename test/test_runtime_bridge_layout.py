"""runtime-bridge 目录布局约束测试。"""
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_BRIDGE = REPO_ROOT / "tools" / "runtime-bridge"


class TestRuntimeBridgeLayout(unittest.TestCase):
    def test_root_has_no_temporary_diagnostic_scripts(self):
        """一次性诊断脚本应归档到 legacy，不应留在 runtime-bridge 根目录。"""
        forbidden = [
            "_check_status.py",
            "_diag_join.py",
            "_poll_status.py",
            "_print_enums.py",
            "_query_maps.py",
            "test-create-game.py",
        ]
        existing = [name for name in forbidden if (RUNTIME_BRIDGE / name).exists()]
        self.assertEqual(existing, [])


if __name__ == "__main__":
    unittest.main()
