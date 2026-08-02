"""Envelope encoding, checksums, and explicit persistence migrations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping


CURRENT_SCHEMA_VERSION = 1
DOMAINS = frozenset({"abilities", "campaign", "mission", "runtime"})
_ENVELOPE_FIELDS = frozenset({"domain", "schema_version", "payload", "checksum"})


class PersistenceError(ValueError):
    """Base error for invalid or unusable persisted state."""


class StateCorruptionError(PersistenceError):
    """Raised when no valid copy of a state file can be read."""


class StateValidationError(PersistenceError):
    """Raised when a valid envelope contains an invalid state payload."""


class UnsupportedSchemaError(PersistenceError):
    """Raised when a state file is newer than this adapter understands."""


@dataclass(frozen=True)
class StateEnvelope:
    domain: str
    schema_version: int
    payload: dict[str, Any]
    checksum: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "checksum": self.checksum,
            "domain": self.domain,
            "payload": self.payload,
            "schema_version": self.schema_version,
        }


def canonical_json(value: Any) -> str:
    """Encode JSON with one stable representation for checksums and replay."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StateValidationError(f"state is not deterministic JSON: {exc}") from exc


def checksum_for(domain: str, schema_version: int, payload: Mapping[str, Any]) -> str:
    body = {
        "domain": domain,
        "payload": dict(payload),
        "schema_version": schema_version,
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def make_envelope(
    domain: str,
    payload: Mapping[str, Any],
    *,
    schema_version: int = CURRENT_SCHEMA_VERSION,
) -> StateEnvelope:
    _validate_domain(domain)
    _validate_schema_version(schema_version)
    if not isinstance(payload, Mapping):
        raise StateValidationError("state payload must be an object")
    normalized = dict(payload)
    return StateEnvelope(
        domain=domain,
        schema_version=schema_version,
        payload=normalized,
        checksum=checksum_for(domain, schema_version, normalized),
    )


def parse_envelope(raw: str | bytes) -> StateEnvelope:
    """Parse an envelope while rejecting malformed JSON and duplicate keys."""

    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, DuplicateKeyError, UnicodeDecodeError) as exc:
        raise StateCorruptionError(f"invalid state JSON: {exc}") from exc
    try:
        return migrate_envelope(value)
    except PersistenceError:
        raise
    except (TypeError, ValueError) as exc:
        raise StateCorruptionError(f"invalid state envelope: {exc}") from exc


def migrate_envelope(raw: Any) -> StateEnvelope:
    if not isinstance(raw, Mapping):
        raise StateCorruptionError("state envelope must be an object")
    keys = set(raw)
    missing = _ENVELOPE_FIELDS - keys
    if missing:
        raise StateCorruptionError(
            f"state envelope is missing fields: {', '.join(sorted(missing))}"
        )
    unknown = keys - _ENVELOPE_FIELDS
    if unknown:
        raise StateCorruptionError(
            f"state envelope has unsupported fields: {', '.join(sorted(unknown))}"
        )

    domain = raw["domain"]
    schema_version = raw["schema_version"]
    payload = raw["payload"]
    checksum = raw["checksum"]
    _validate_domain(domain)
    _validate_schema_version(schema_version)
    if not isinstance(payload, Mapping):
        raise StateCorruptionError("state envelope payload must be an object")
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise StateCorruptionError("state envelope checksum must be a SHA-256 string")
    expected = checksum_for(domain, schema_version, payload)
    if not _constant_time_equal(checksum, expected):
        raise StateCorruptionError("state checksum mismatch")

    migrated_payload = dict(payload)
    while schema_version < CURRENT_SCHEMA_VERSION:
        migrated_payload = _migrate_one(domain, schema_version, migrated_payload)
        schema_version += 1
    return make_envelope(
        domain,
        migrated_payload,
        schema_version=schema_version,
    )


class DuplicateKeyError(ValueError):
    """Raised for ambiguous JSON objects that contain a duplicate key."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key '{key}'")
        result[key] = value
    return result


def _migrate_one(
    domain: str,
    schema_version: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if schema_version != 0:
        raise UnsupportedSchemaError(
            f"no migration registered for {domain} schema {schema_version}"
        )
    migrated = dict(payload)
    aliases = {
        "abilities": {},
        "campaign": {"campaign_id": "id"},
        "mission": {"map_name": "map"},
        "runtime": {
            "active_actions": "active_action_names",
            "queued_ids": "queued_action_ids",
        },
    }[domain]
    for old_name, new_name in aliases.items():
        if new_name not in migrated and old_name in migrated:
            migrated[new_name] = migrated.pop(old_name)
    return migrated


def _validate_domain(domain: Any) -> None:
    if not isinstance(domain, str) or domain not in DOMAINS:
        raise StateCorruptionError(f"unsupported state domain: {domain!r}")


def _validate_schema_version(schema_version: Any) -> None:
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 0
    ):
        raise StateCorruptionError("schema_version must be a non-negative integer")
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaError(
            f"state schema {schema_version} is newer than supported schema "
            f"{CURRENT_SCHEMA_VERSION}"
        )


def _constant_time_equal(left: str, right: str) -> bool:
    return hashlib.sha256(left.encode("ascii")).digest() == hashlib.sha256(
        right.encode("ascii")
    ).digest()


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DOMAINS",
    "PersistenceError",
    "StateCorruptionError",
    "StateEnvelope",
    "StateValidationError",
    "UnsupportedSchemaError",
    "canonical_json",
    "checksum_for",
    "make_envelope",
    "migrate_envelope",
    "parse_envelope",
]
