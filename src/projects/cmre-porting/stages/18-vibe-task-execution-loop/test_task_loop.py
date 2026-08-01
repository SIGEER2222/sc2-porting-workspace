import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.task_loop import TaskLoopError, TaskLoopRunner, TaskScenario, run_simulator_task  # noqa: E402


STAGE_DIR = Path(__file__).resolve().parent


class TestTaskLoopScenario(unittest.TestCase):
    def test_simulator_action_loop_passes_and_captures_tag(self):
        scenario = TaskScenario.from_file(STAGE_DIR / "action-loop.json")
        result = run_simulator_task(scenario, STAGE_DIR / "simulator-empty.json")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["steps_completed"], 6)
        self.assertEqual(result["captures"]["spawn-marines"]["payload"]["created"], 2)
        self.assertEqual(result["captures"]["observe-after-kill"]["payload"]["count"], 1)
        self.assertEqual([item["request_id"] for item in result["trace"]], [
            "task-003", "task-004", "task-005", "task-006", "task-007", "task-008",
        ])

    def test_side_effect_retry_is_rejected(self):
        data = {
            "schemaVersion": 1,
            "task_id": "invalid-retry",
            "steps": [{
                "id": "spawn",
                "mode": "act",
                "function_id": "vibe.unit.spawn",
                "args": {"unit_type": "Marine", "count": 1, "player": 1},
                "retries": 1,
            }],
        }
        with self.assertRaises(TaskLoopError):
            TaskScenario.from_dict(data)

    def test_invalid_function_is_rejected_before_execution(self):
        data = {
            "schemaVersion": 1,
            "task_id": "invalid-function",
            "steps": [{
                "id": "invoke",
                "mode": "observe",
                "function_id": "vibe.not_registered",
            }],
        }
        with self.assertRaisesRegex(TaskLoopError, "not registered"):
            TaskScenario.from_dict(data)

    def test_failed_predicate_stops_loop(self):
        scenario = TaskScenario.from_dict({
            "schemaVersion": 1,
            "task_id": "failed-predicate",
            "steps": [{
                "id": "observe",
                "mode": "observe",
                "function_id": "vibe.query.units",
                "args": {"player": 1, "unit_type": "Marine"},
                "expect": {"path": "payload.count", "equals": 1},
            }],
        })

        def invoke(function_id, args, timeout_seconds):
            return {
                "kind": "result", "request_id": "predicate-1",
                "error_code": "OK", "payload": {"count": 0},
                "state_version": 0,
            }

        result = TaskLoopRunner(invoke).run(scenario)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("payload.count equals", result["failures"][0]["reason"])

    def test_timeout_stops_loop_and_records_timeout(self):
        scenario = TaskScenario.from_dict({
            "schemaVersion": 1,
            "task_id": "timeout",
            "steps": [{
                "id": "observe",
                "mode": "observe",
                "function_id": "vibe.query.units",
                "args": {"player": 1, "unit_type": "Marine"},
                "timeout_seconds": 2,
            }],
        })

        def invoke(function_id, args, timeout_seconds):
            self.assertEqual(timeout_seconds, 2.0)
            raise TimeoutError("Bank response timed out")

        result = TaskLoopRunner(invoke).run(scenario)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["trace"][0]["error_code"], "TIMEOUT")
        self.assertIn("timed out", result["failures"][0]["reason"])

    def test_timeout_policy_is_bounded(self):
        data = {
            "schemaVersion": 1,
            "task_id": "invalid-timeout",
            "steps": [{
                "id": "observe",
                "mode": "observe",
                "function_id": "vibe.query.units",
                "args": {"player": 1, "unit_type": "Marine"},
                "timeout_seconds": 121,
            }],
        }
        with self.assertRaisesRegex(TaskLoopError, "timeout_seconds"):
            TaskScenario.from_dict(data)

    def test_stale_response_stops_loop(self):
        scenario = TaskScenario.from_dict({
            "schemaVersion": 1,
            "task_id": "stale-response",
            "steps": [
                {"id": "first", "mode": "observe", "function_id": "vibe.query.units",
                 "args": {"player": 1, "unit_type": "Marine"}},
                {"id": "second", "mode": "observe", "function_id": "vibe.query.units",
                 "args": {"player": 1, "unit_type": "Marine"}},
            ],
        })
        actual_versions = iter((3, 2))

        def invoke_stale(function_id, args, timeout_seconds):
            version = next(actual_versions)
            return {
                "kind": "result", "request_id": f"request-{version}",
                "error_code": "OK", "payload": {"count": 0},
                "state_version": version,
            }

        result = TaskLoopRunner(invoke_stale).run(scenario)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("stale state_version", result["failures"][0]["reason"])

    def test_observe_retry_can_recover(self):
        scenario = TaskScenario.from_dict({
            "schemaVersion": 1,
            "task_id": "retry-observe",
            "steps": [{
                "id": "observe",
                "mode": "observe",
                "function_id": "vibe.query.units",
                "args": {"player": 1, "unit_type": "Marine"},
                "retries": 1,
                "expect": {"path": "payload.count", "equals": 0},
            }],
        })
        calls = []

        def invoke(function_id, args, timeout_seconds):
            calls.append(1)
            if len(calls) == 1:
                return {"kind": "error", "request_id": "r1", "error_code": "TIMEOUT", "payload": {}, "state_version": 0}
            return {"kind": "result", "request_id": "r2", "error_code": "OK", "payload": {"count": 0}, "state_version": 0}

        result = TaskLoopRunner(invoke).run(scenario)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
