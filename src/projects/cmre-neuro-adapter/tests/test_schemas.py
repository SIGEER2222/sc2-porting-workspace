from __future__ import annotations

import unittest

from cmre_neuro_adapter.neuro.schemas import (
    SchemaValidationError,
    validate_action_arguments,
)
from cmre_neuro_adapter.neuro.errors import ContractErrorCode


ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "count": {"type": "integer", "minimum": 1, "maximum": 5},
        "ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "mode": {"type": "string", "enum": ["attack", "defend"]},
        "unit": {"type": "string", "pattern": r"[A-Za-z][A-Za-z0-9_]*"},
        "queued": {"type": "boolean"},
    },
    "required": ["count", "mode"],
    "additionalProperties": False,
}


class SchemaValidationTests(unittest.TestCase):
    def test_validate_complete_action_arguments(self) -> None:
        args = {
            "count": 2,
            "ratio": 0.5,
            "mode": "attack",
            "unit": "Marine_1",
            "queued": False,
        }
        self.assertEqual(validate_action_arguments(args, ACTION_SCHEMA), args)

    def test_validate_rejects_invalid_arguments(self) -> None:
        cases = [
            ({"mode": "attack"}, "missing required argument 'count'"),
            ({"count": 2, "mode": "attack", "extra": 1}, "unexpected argument"),
            ({"count": True, "mode": "attack"}, "must be an integer"),
            ({"count": 0, "mode": "attack"}, "must be >= 1"),
            ({"count": 6, "mode": "attack"}, "must be <= 5"),
            ({"count": 2, "mode": "retreat"}, "must be one of"),
            (
                {"count": 2, "mode": "attack", "unit": "bad unit"},
                "must match pattern",
            ),
            ({"count": 2, "mode": "attack", "queued": 1}, "must be a boolean"),
            ({"count": 2, "mode": "attack", "ratio": True}, "must be a number"),
        ]
        for args, message in cases:
            with (
                self.subTest(args=args),
                self.assertRaisesRegex(SchemaValidationError, message),
            ):
                validate_action_arguments(args, ACTION_SCHEMA)

    def test_schema_is_optional_for_argument_free_actions(self) -> None:
        self.assertIsNone(validate_action_arguments(None, None))
        self.assertEqual(
            validate_action_arguments({"reason": "manual"}, None),
            {"reason": "manual"},
        )

    def test_schema_requires_arguments_when_present(self) -> None:
        with self.assertRaisesRegex(SchemaValidationError, "missing action arguments"):
            validate_action_arguments(None, ACTION_SCHEMA)

    def test_argument_and_schema_failures_have_distinct_codes(self) -> None:
        with self.assertRaises(SchemaValidationError) as caught:
            validate_action_arguments({"count": 0, "mode": "attack"}, ACTION_SCHEMA)
        self.assertEqual(caught.exception.code, ContractErrorCode.INVALID_ARGUMENTS)

        invalid_schema = {
            "type": "object",
            "properties": {"count": {"type": "array"}},
        }
        with self.assertRaises(SchemaValidationError) as caught:
            validate_action_arguments({"count": []}, invalid_schema)
        self.assertEqual(caught.exception.code, ContractErrorCode.INVALID_SCHEMA)


if __name__ == "__main__":
    unittest.main()
