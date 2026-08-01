from __future__ import annotations

import json
import unittest

from cmre_neuro_adapter.neuro.actions import ActionDefinition, ExecutionResult
from cmre_neuro_adapter.neuro.context import ContextEnvelope
from cmre_neuro_adapter.neuro.errors import ContractErrorCode, ContractViolation
from cmre_neuro_adapter.neuro.evidence import EvidenceRecord, EvidenceType
from cmre_neuro_adapter.neuro.messages import (
    NeuroMessageBuilder,
    parse_incoming_message,
)
from cmre_neuro_adapter.neuro.session import NeuroSessionIdentity


class MessageContractTests(unittest.TestCase):
    def test_outgoing_messages_match_reference_shapes(self) -> None:
        builder = NeuroMessageBuilder("StarCraft 2")
        schema = {
            "type": "object",
            "properties": {"target": {"type": "integer"}},
            "required": ["target"],
            "additionalProperties": False,
        }
        action = ActionDefinition(
            name="attack_unit",
            description="Attack one visible enemy.",
            schema=schema,
            uses=3,
        )

        self.assertEqual(
            builder.startup(), {"command": "startup", "game": "StarCraft 2"}
        )
        self.assertEqual(
            builder.context(ContextEnvelope("mission", "Night 1", silent=False)),
            {
                "command": "context",
                "game": "StarCraft 2",
                "data": {"message": "Night 1", "silent": False},
            },
        )
        self.assertEqual(
            builder.actions_register([action])["data"]["actions"],
            [
                {
                    "name": "attack_unit",
                    "description": "Attack one visible enemy.",
                    "schema": schema,
                }
            ],
        )
        self.assertEqual(
            builder.actions_unregister(["attack_unit"])["data"],
            {"action_names": ["attack_unit"]},
        )
        self.assertEqual(
            builder.actions_force(
                "Defend the base",
                ["attack_unit"],
                state="night",
                priority="high",
            )["data"],
            {
                "query": "Defend the base",
                "ephemeral_context": False,
                "priority": "high",
                "action_names": ["attack_unit"],
                "state": "night",
            },
        )
        self.assertEqual(
            builder.action_result(
                ExecutionResult(
                    "action-1", True, "Command accepted.", "unit.order", loop=12
                )
            )["data"],
            {
                "id": "action-1",
                "success": True,
                "message": "Command accepted.",
            },
        )

    def test_parse_supported_incoming_messages(self) -> None:
        cases = [
            ({"command": "action", "data": {"id": "1", "name": "hold"}}, "action"),
            ({"command": "startup", "data": {"session": {}}}, "startup"),
            ({"command": "actions/reregister_all"}, "actions/reregister_all"),
        ]
        for payload, expected_command in cases:
            with self.subTest(command=expected_command):
                parsed = parse_incoming_message(json.dumps(payload))
                self.assertEqual(parsed.command, expected_command)

    def test_parse_rejects_malformed_messages(self) -> None:
        payloads = [
            "not-json",
            "[]",
            json.dumps({"data": {}}),
            json.dumps({"command": "unknown", "data": {}}),
            json.dumps({"command": "action"}),
            json.dumps({"command": "startup", "data": "bad"}),
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_incoming_message(payload)

    def test_parse_errors_include_stable_codes(self) -> None:
        with self.assertRaises(ContractViolation) as caught:
            parse_incoming_message("not-json")
        self.assertEqual(caught.exception.code, ContractErrorCode.INVALID_JSON)

        with self.assertRaises(ContractViolation) as caught:
            parse_incoming_message({"command": "unknown", "data": {}})
        self.assertEqual(caught.exception.code, ContractErrorCode.UNKNOWN_COMMAND)

    def test_session_identity_parses_startup_response(self) -> None:
        identity = NeuroSessionIdentity.from_startup_data(
            {
                "session": {
                    "sessionId": "session-1",
                    "characterId": "character-1",
                    "displayName": "Neuro",
                }
            }
        )
        self.assertEqual(identity.session_id, "session-1")
        self.assertEqual(identity.character_id, "character-1")
        self.assertEqual(identity.display_name, "Neuro")

    def test_invalid_outgoing_contracts_are_rejected(self) -> None:
        builder = NeuroMessageBuilder()
        with self.assertRaises(ValueError):
            builder.actions_unregister([])
        with self.assertRaises(ValueError):
            builder.actions_force("query", ["hold"], priority="urgent")
        with self.assertRaises(ValueError):
            ActionDefinition("", "description")
        with self.assertRaises(ValueError):
            ContextEnvelope("mission", "")

    def test_evidence_record_has_stable_wire_shape(self) -> None:
        record = EvidenceRecord(
            claim="Message contract tests pass",
            evidence_type=EvidenceType.STATIC,
            source="tests/test_messages.py",
            command="python -m unittest discover -s tests -v",
            passed=True,
            details={"tests": 12},
        )
        self.assertEqual(
            record.to_dict(),
            {
                "claim": "Message contract tests pass",
                "evidence_type": "static",
                "source": "tests/test_messages.py",
                "command": "python -m unittest discover -s tests -v",
                "passed": True,
                "details": {"tests": 12},
            },
        )


if __name__ == "__main__":
    unittest.main()
