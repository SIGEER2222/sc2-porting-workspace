"""Validation for the JSON Schema subset accepted by Neuro actions."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .errors import ContractErrorCode, ContractViolation


class SchemaValidationError(ContractViolation):
    """Raised when action arguments do not match their registered schema."""

    def __init__(self, message: str, *, schema_error: bool = False) -> None:
        code = (
            ContractErrorCode.INVALID_SCHEMA
            if schema_error
            else ContractErrorCode.INVALID_ARGUMENTS
        )
        super().__init__(code, message)


def validate_action_arguments(
    arguments: Mapping[str, Any] | None,
    schema: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate arguments against the supported object-schema subset.

    Supported value constraints are ``type``, ``enum``, ``pattern``,
    ``minimum`` and ``maximum``. Object schemas support ``properties``,
    ``required`` and ``additionalProperties``.
    """

    if not schema:
        if arguments is None:
            return None
        return dict(arguments)
    if arguments is None:
        raise SchemaValidationError("missing action arguments")
    if not isinstance(arguments, Mapping):
        raise SchemaValidationError("action arguments must be an object")
    if schema.get("type") != "object":
        raise SchemaValidationError(
            "action schema must have type 'object'", schema_error=True
        )

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    additional_properties = schema.get("additionalProperties", True)
    if not isinstance(properties, Mapping):
        raise SchemaValidationError(
            "schema properties must be an object", schema_error=True
        )
    if not isinstance(required, list) or not all(
        isinstance(item, str) for item in required
    ):
        raise SchemaValidationError(
            "schema required must be a list of strings", schema_error=True
        )
    if not isinstance(additional_properties, bool):
        raise SchemaValidationError(
            "schema additionalProperties must be a boolean", schema_error=True
        )

    for name in required:
        if name not in arguments:
            raise SchemaValidationError(f"missing required argument '{name}'")

    if not additional_properties:
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise SchemaValidationError(
                f"unexpected argument(s): {', '.join(unexpected)}"
            )

    for name, value in arguments.items():
        property_schema = properties.get(name)
        if property_schema is None:
            continue
        if not isinstance(property_schema, Mapping):
            raise SchemaValidationError(
                f"schema for '{name}' must be an object", schema_error=True
            )
        _validate_value(name, value, property_schema)

    return dict(arguments)


def _validate_value(name: str, value: Any, schema: Mapping[str, Any]) -> None:
    expected_type = schema.get("type")
    if expected_type == "string":
        if not isinstance(value, str):
            raise SchemaValidationError(f"argument '{name}' must be a string")
        _validate_string(name, value, schema)
        return
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaValidationError(f"argument '{name}' must be an integer")
        _validate_bounds(name, value, schema)
        return
    if expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SchemaValidationError(f"argument '{name}' must be a number")
        _validate_bounds(name, float(value), schema)
        return
    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise SchemaValidationError(f"argument '{name}' must be a boolean")
        return
    raise SchemaValidationError(
        f"unsupported schema type for '{name}': {expected_type!r}",
        schema_error=True,
    )


def _validate_string(name: str, value: str, schema: Mapping[str, Any]) -> None:
    enum_values = schema.get("enum")
    if enum_values is not None:
        if not isinstance(enum_values, list) or not all(
            isinstance(item, str) for item in enum_values
        ):
            raise SchemaValidationError(
                f"enum for '{name}' must be a list of strings", schema_error=True
            )
        if value not in enum_values:
            raise SchemaValidationError(
                f"argument '{name}' must be one of: {', '.join(enum_values)}"
            )

    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise SchemaValidationError(
                f"pattern for '{name}' must be a string", schema_error=True
            )
        try:
            matches = re.fullmatch(pattern, value)
        except re.error as exc:
            raise SchemaValidationError(
                f"invalid schema pattern for '{name}'", schema_error=True
            ) from exc
        if matches is None:
            raise SchemaValidationError(
                f"argument '{name}' must match pattern: {pattern}"
            )


def _validate_bounds(name: str, value: int | float, schema: Mapping[str, Any]) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None:
        if not isinstance(minimum, (int, float)) or isinstance(minimum, bool):
            raise SchemaValidationError(
                f"minimum for '{name}' must be numeric", schema_error=True
            )
        if value < minimum:
            raise SchemaValidationError(f"argument '{name}' must be >= {minimum}")
    if maximum is not None:
        if not isinstance(maximum, (int, float)) or isinstance(maximum, bool):
            raise SchemaValidationError(
                f"maximum for '{name}' must be numeric", schema_error=True
            )
        if value > maximum:
            raise SchemaValidationError(f"argument '{name}' must be <= {maximum}")
