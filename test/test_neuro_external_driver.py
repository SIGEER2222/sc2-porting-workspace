"""Neuro 外部驱动 bank 动作构造的单元测试。"""
import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / "tools" / "runtime-bridge" / "neuro_external_driver.py"
spec = importlib.util.spec_from_file_location("neuro_external_driver", DRIVER_PATH)
driver = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = driver
spec.loader.exec_module(driver)


SAMPLE_BANK = """<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
    <Section name="game_state">
        <Key name="active">
            <Value int="41"/>
        </Key>
    </Section>
</Bank>
"""


class TestNeuroExternalDriverBankAction(unittest.TestCase):
    def test_prepare_chat_action_inserts_do_action_and_bumps_active(self):
        updated, result = driver.prepare_chat_action(SAMPLE_BANK, "hello sc2")

        self.assertEqual(result.old_active, 41)
        self.assertEqual(result.new_active, 42)
        self.assertIn('<Section name="do_action">', updated)
        self.assertIn('<Key name="chat_message">', updated)
        self.assertIn('<Value flag="1"/>', updated)
        self.assertIn('<Value string="hello sc2"/>', updated)
        self.assertIn('<Value int="42"/>', updated)

    def test_prepare_chat_action_replaces_existing_do_action(self):
        original, _ = driver.prepare_chat_action(SAMPLE_BANK, "first")
        updated, result = driver.prepare_chat_action(original, "second")

        self.assertEqual(result.old_active, 42)
        self.assertEqual(result.new_active, 43)
        self.assertEqual(updated.count('<Section name="do_action">'), 1)
        self.assertNotIn('<Value string="first"/>', updated)
        self.assertIn('<Value string="second"/>', updated)

    def test_read_chat_flag_handles_cleared_and_pending_flags(self):
        pending, _ = driver.prepare_chat_action(SAMPLE_BANK, "pending")
        cleared = pending.replace('<Value flag="1"/>', '<Value flag="0"/>', 1)

        self.assertEqual(driver.read_chat_flag(pending), "1")
        self.assertEqual(driver.read_chat_flag(cleared), "0")

    def test_order_action_has_three_arguments_and_a_consumable_flag(self):
        section = driver.build_action_section("issue_order", ["Marine", "move", "42 64"])
        updated = driver.replace_or_insert_section(SAMPLE_BANK, "do_action", section)

        self.assertEqual(driver.read_action_flag(updated, "issue_order"), "1")
        self.assertIn('<Key name="issue_order_arg_1">', updated)
        self.assertIn('<Value string="Marine"/>', updated)
        self.assertIn('<Value string="move"/>', updated)
        self.assertIn('<Value string="42 64"/>', updated)


if __name__ == "__main__":
    unittest.main()
