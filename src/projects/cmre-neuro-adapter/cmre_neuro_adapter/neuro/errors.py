"""Stable error codes for the Neuro contract boundary."""

from __future__ import annotations

from enum import Enum


class ContractErrorCode(str, Enum):
    INVALID_JSON = "invalid_json"
    INVALID_MESSAGE = "invalid_message"
    UNKNOWN_COMMAND = "unknown_command"
    MISSING_DATA = "missing_data"
    INVALID_ARGUMENTS = "invalid_arguments"
    INVALID_SCHEMA = "invalid_schema"


class ContractViolation(ValueError):
    """A caller-visible contract failure with a stable machine-readable code."""

    def __init__(self, code: ContractErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
