"""CMRE 当前阶段收口记录的回归测试。"""
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_DIR = REPO_ROOT / "src" / "projects" / "cmre-porting" / "stages" / "04-runtime-baseline"


class TestCmreRuntimeBaselineClosure(unittest.TestCase):
    def test_plan_records_alenger3_baseline_and_external_driver_handoff(self):
        """阶段计划必须反映实际收口对象和剩余 Gary/Neuro 外部驱动缺口。"""
        plan = (STAGE_DIR / "plan.md").read_text(encoding="utf-8")

        self.assertIn("TerranAlenger3", plan)
        self.assertIn("Gary/Neuro external-driver", plan)
        self.assertIn("CMRE-RUNTIME-003", plan)

    def test_issues_point_to_formal_external_driver_tool(self):
        """Gary/Neuro 外部驱动缺口应指向正式工具入口，而不是散落的 legacy 脚本。"""
        issues = (STAGE_DIR / "issues.json").read_text(encoding="utf-8")

        self.assertIn("tools/runtime-bridge/neuro_external_driver.py", issues)


if __name__ == "__main__":
    unittest.main()
