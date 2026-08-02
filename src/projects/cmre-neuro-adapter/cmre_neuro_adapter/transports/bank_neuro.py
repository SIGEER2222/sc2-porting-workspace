"""XML Bank transport using the same section/key/value boundary as the reference integration."""

from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..neuro.actions import ActionCommand, ExecutionResult
from ..neuro.context import ContextEnvelope
from ..neuro.mission_projection import MissionContextProjector, PublicMissionContext
from .common import (
    TransportError,
    TransportExecutionResult,
    TransportStatus,
    canonical_json,
    failed_result,
    result_from_raw,
)


@runtime_checkable
class BankStore(Protocol):
    def read(self) -> Mapping[str, Mapping[str, Any]]: ...

    def write(self, updates: Mapping[str, Mapping[str, Any]]) -> None: ...


class XmlBankStore:
    """Read and atomically update an SC2 Bank file without external dependencies."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, dict[str, Any]]:
        try:
            root = ET.parse(self.path).getroot()
        except (OSError, ET.ParseError) as exc:
            raise TransportError("bank_read_failed", str(exc)) from exc
        parsed: dict[str, dict[str, Any]] = {}
        for section in root.findall("Section"):
            section_name = section.get("name")
            if not section_name:
                continue
            values: dict[str, Any] = {}
            for key in section.findall("Key"):
                key_name = key.get("name")
                if not key_name:
                    continue
                values[key_name] = _read_value(key.find("Value"))
            parsed[section_name] = values
        return parsed

    def write(self, updates: Mapping[str, Mapping[str, Any]]) -> None:
        if not isinstance(updates, Mapping):
            raise TypeError("bank updates must be an object")
        try:
            tree = ET.parse(self.path)
            root = tree.getroot()
            for section_name, values in updates.items():
                section = _find_section(root, section_name)
                if not isinstance(values, Mapping):
                    raise TypeError("bank section updates must be objects")
                for key_name, value in values.items():
                    key = _find_key(section, str(key_name))
                    value_node = key.find("Value")
                    if value_node is None:
                        value_node = ET.SubElement(key, "Value")
                    _write_value(value_node, value)
            ET.indent(tree, space="    ")
            with tempfile.NamedTemporaryFile(
                "wb", dir=self.path.parent, suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
            try:
                tree.write(temporary, encoding="utf-8", xml_declaration=True)
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        except TransportError:
            raise
        except (OSError, ET.ParseError, TypeError, ValueError) as exc:
            raise TransportError("bank_write_failed", str(exc)) from exc


class BankTransport:
    """Stage typed actions and context through a NeuroIntegration-style bank."""

    name = "bank"

    def __init__(
        self,
        store: BankStore,
        *,
        map_name: str = "dead-of-night",
        observation_section: str = "public_observation",
    ) -> None:
        if not isinstance(store, BankStore):
            raise TypeError("store does not implement BankStore")
        self.store = store
        self._projector = MissionContextProjector(map_name=map_name)
        self.observation_section = observation_section
        self._connected = False
        self._generation = 0
        self._reconnects = 0
        self._last_error: str | None = None
        self._last_context: PublicMissionContext | None = None
        self._results: dict[str, TransportExecutionResult] = {}

    @property
    def status(self) -> TransportStatus:
        return TransportStatus(
            name=self.name,
            connected=self._connected,
            generation=self._generation,
            reconnects=self._reconnects,
            last_error=self._last_error,
        )

    def connect(self) -> TransportStatus:
        try:
            self.store.read()
        except Exception as exc:
            self._last_error = str(exc)
            raise _bank_error("connect_failed", exc) from exc
        self._connected = True
        self._generation += 1
        self._last_error = None
        return self.status

    def disconnect(self) -> TransportStatus:
        self._connected = False
        return self.status

    def reconnect(self) -> TransportStatus:
        self._reconnects += 1
        self._connected = False
        return self.connect()

    def observe(self) -> PublicMissionContext:
        self._require_connected()
        try:
            sections = self.store.read()
            values = sections.get(self.observation_section)
            if not isinstance(values, Mapping):
                raise TransportError(
                    "observation_missing",
                    f"bank section '{self.observation_section}' is missing",
                )
            payload = values.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, Mapping):
                raise TransportError("invalid_observation", "bank observation payload must be an object")
            state_version = payload.get("state_version", payload.get("loop"))
            context = self._projector.project(payload, state_version=state_version)
        except Exception as exc:
            self._last_error = str(exc)
            if isinstance(exc, TransportError):
                raise
            raise _bank_error("observation_failed", exc) from exc
        self._last_context = context
        self._last_error = None
        return context

    def publish_context(self, envelope: ContextEnvelope | PublicMissionContext) -> None:
        self._require_connected()
        if isinstance(envelope, PublicMissionContext):
            envelope = envelope.to_envelope()
        if not isinstance(envelope, ContextEnvelope):
            raise TypeError("envelope must be a ContextEnvelope or PublicMissionContext")
        try:
            self.store.write(
                {
                    "game_context": {
                        envelope.name: envelope.message,
                        f"{envelope.name}_silent": envelope.silent,
                        f"{envelope.name}_new": True,
                    }
                }
            )
        except Exception as exc:
            self._last_error = str(exc)
            raise _bank_error("context_write_failed", exc) from exc

    def dispatch(self, command: ActionCommand) -> TransportExecutionResult:
        if not isinstance(command, ActionCommand):
            raise TypeError("command must be an ActionCommand")
        duplicate = self._results.get(command.action_id)
        if duplicate is not None:
            return TransportExecutionResult(
                action_id=duplicate.action_id,
                success=duplicate.success,
                message=duplicate.message,
                operation=duplicate.operation,
                loop=duplicate.loop,
                transport=duplicate.transport,
                state_version=duplicate.state_version,
                duplicate=True,
            )
        if not self._connected:
            return self._remember(
                failed_result(
                    command,
                    transport=self.name,
                    code="not_connected",
                    message="Bank transport is not connected",
                )
            )
        try:
            self.store.write(
                {
                    "do_action": {
                        "action_id": command.action_id,
                        "action_name": command.name,
                        "arguments": canonical_json(dict(command.args or {})),
                        "pending": True,
                    }
                }
            )
            result = result_from_raw(
                command,
                None,
                transport=self.name,
                default_operation="bank.stage_action",
                state_version=(
                    self._last_context.state_version if self._last_context else None
                ),
            )
        except Exception as exc:
            result = failed_result(
                command,
                transport=self.name,
                code=exc.code if isinstance(exc, TransportError) else "action_write_failed",
                message=str(exc),
                state_version=self._last_context.state_version if self._last_context else None,
            )
            self._last_error = result.message
        else:
            self._last_error = None
        return self._remember(result)

    def poll_result(self, action_id: str) -> TransportExecutionResult | None:
        self._require_connected()
        sections = self.store.read()
        values = sections.get("action_result", {})
        if not isinstance(values, Mapping) or values.get("action_id") != action_id:
            return None
        command = ActionCommand(action_id, str(values.get("action_name", "unknown")), {}, 0.0)
        return result_from_raw(
            command,
            values,
            transport=self.name,
            default_operation="bank.action_result",
            state_version=values.get("state_version"),
        )

    def execute(self, command: ActionCommand) -> TransportExecutionResult:
        return self.dispatch(command)

    def _remember(self, result: TransportExecutionResult) -> TransportExecutionResult:
        self._results[result.action_id] = result
        return result

    def _require_connected(self) -> None:
        if not self._connected:
            raise TransportError("not_connected", "Bank transport is not connected")


def _find_section(root: ET.Element, name: str) -> ET.Element:
    for section in root.findall("Section"):
        if section.get("name") == name:
            return section
    return ET.SubElement(root, "Section", {"name": name})


def _find_key(section: ET.Element, name: str) -> ET.Element:
    for key in section.findall("Key"):
        if key.get("name") == name:
            return key
    return ET.SubElement(section, "Key", {"name": name})


def _read_value(node: ET.Element | None) -> Any:
    if node is None:
        return None
    if "flag" in node.attrib:
        return node.attrib["flag"] == "1"
    if "int" in node.attrib:
        try:
            return int(node.attrib["int"])
        except ValueError:
            return node.attrib["int"]
    if "fixed" in node.attrib:
        try:
            return float(node.attrib["fixed"])
        except ValueError:
            return node.attrib["fixed"]
    if "string" in node.attrib:
        return node.attrib["string"]
    if "text" in node.attrib:
        return node.attrib["text"]
    return (node.text or "").strip()


def _write_value(node: ET.Element, value: Any) -> None:
    node.attrib.clear()
    node.text = None
    if isinstance(value, bool):
        node.set("flag", "1" if value else "0")
    elif isinstance(value, int) and not isinstance(value, bool):
        node.set("int", str(value))
    elif isinstance(value, float):
        node.set("fixed", str(value))
    else:
        node.set("string", str(value))


def _bank_error(code: str, exc: Exception) -> TransportError:
    return exc if isinstance(exc, TransportError) else TransportError(code, str(exc))


__all__ = ["BankStore", "BankTransport", "XmlBankStore"]
