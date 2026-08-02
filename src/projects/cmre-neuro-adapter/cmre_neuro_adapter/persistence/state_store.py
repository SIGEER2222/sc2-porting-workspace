"""Atomic, checksummed storage for campaign, mission, and runtime state."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..mission.mission_state import (
    CampaignState,
    MissionSnapshot,
    RuntimeState,
)
from ..abilities.state import AbilityState
from .ability_state import decode_ability_state, encode_ability_state
from .campaign_state import decode_campaign_state, encode_campaign_state
from .migrations import (
    DOMAINS,
    StateCorruptionError,
    StateEnvelope,
    StateValidationError,
    UnsupportedSchemaError,
    canonical_json,
    make_envelope,
    parse_envelope,
)
from .mission_state import decode_mission_state, encode_mission_state
from .runtime_state import decode_runtime_state, encode_runtime_state


class StateStoreError(ValueError):
    """Base error for state-store operations."""


class StateNotFoundError(StateStoreError):
    """Raised when neither the primary nor backup file exists."""


class AtomicWriteError(StateStoreError):
    """Raised when a state replacement fails before the primary is replaced."""


@dataclass(frozen=True)
class _LoadedPayload:
    envelope: StateEnvelope
    recovered: bool


class StateStore:
    """Persist only public Stage 04 state, with one file per state domain."""

    _FILENAMES = {
        "abilities": "abilities.json",
        "campaign": "campaign.json",
        "mission": "mission.json",
        "runtime": "runtime.json",
    }

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_load_recovered = False

    def path_for(self, domain: str) -> Path:
        self._validate_domain(domain)
        return self.root / self._FILENAMES[domain]

    def backup_path_for(self, domain: str) -> Path:
        return self.path_for(domain).with_name(self.path_for(domain).name + ".bak")

    def save_campaign(self, state: CampaignState) -> None:
        self._save("campaign", encode_campaign_state(state))

    def save_mission(self, state: Any) -> None:
        self._save("mission", encode_mission_state(state))

    def save_runtime(self, state: RuntimeState) -> None:
        self._save("runtime", encode_runtime_state(state))

    def save_abilities(self, state: AbilityState) -> None:
        self._save("abilities", encode_ability_state(state))

    def save_snapshot(self, snapshot: MissionSnapshot) -> None:
        if not isinstance(snapshot, MissionSnapshot):
            raise StateValidationError("snapshot has the wrong type")
        payloads = {
            "campaign": encode_campaign_state(snapshot.campaign),
            "mission": encode_mission_state(snapshot.mission),
            "runtime": encode_runtime_state(snapshot.runtime),
        }
        for domain, payload in payloads.items():
            self._save(domain, payload)
        if snapshot.abilities is not None:
            self.save_abilities(snapshot.abilities)

    def load_campaign(self) -> CampaignState:
        loaded = self._load("campaign")
        self.last_load_recovered = loaded.recovered
        return decode_campaign_state(loaded.envelope.payload)

    def load_mission(self):
        loaded = self._load("mission")
        self.last_load_recovered = loaded.recovered
        return decode_mission_state(loaded.envelope.payload)

    def load_runtime(self) -> RuntimeState:
        loaded = self._load("runtime")
        self.last_load_recovered = loaded.recovered
        return decode_runtime_state(loaded.envelope.payload)

    def load_abilities(self) -> AbilityState:
        loaded = self._load("abilities")
        self.last_load_recovered = loaded.recovered
        return decode_ability_state(loaded.envelope.payload)

    def load_snapshot(self) -> MissionSnapshot:
        campaign = self._load("campaign")
        mission = self._load("mission")
        runtime = self._load("runtime")
        abilities = None
        if (
            self.path_for("abilities").exists()
            or self.backup_path_for("abilities").exists()
        ):
            abilities = self._load("abilities")
        self.last_load_recovered = (
            campaign.recovered
            or mission.recovered
            or runtime.recovered
            or (abilities.recovered if abilities is not None else False)
        )
        return MissionSnapshot(
            campaign=decode_campaign_state(campaign.envelope.payload),
            mission=decode_mission_state(mission.envelope.payload),
            runtime=decode_runtime_state(runtime.envelope.payload),
            abilities=(
                decode_ability_state(abilities.envelope.payload)
                if abilities is not None
                else None
            ),
        )

    def _save(self, domain: str, payload: dict[str, Any]) -> None:
        envelope = make_envelope(domain, payload)
        data = (canonical_json(envelope.to_dict()) + "\n").encode("utf-8")
        self._atomic_replace(self.path_for(domain), data)

    def _load(self, domain: str) -> _LoadedPayload:
        primary = self.path_for(domain)
        backup = self.backup_path_for(domain)
        candidates = ((primary, False), (backup, True))
        errors: list[str] = []
        found = False
        for path, recovered in candidates:
            if not path.exists():
                continue
            found = True
            try:
                envelope = parse_envelope(path.read_bytes())
                if envelope.domain != domain:
                    raise StateCorruptionError(
                        f"expected {domain} state, found {envelope.domain}"
                    )
                return _LoadedPayload(envelope, recovered)
            except UnsupportedSchemaError:
                raise
            except (OSError, StateCorruptionError, StateValidationError) as exc:
                errors.append(f"{path.name}: {exc}")
        if not found:
            raise StateNotFoundError(f"no persisted {domain} state exists")
        detail = "; ".join(errors) if errors else "unknown read failure"
        raise StateCorruptionError(f"no valid {domain} state copy: {detail}")

    def _atomic_replace(self, path: Path, data: bytes) -> None:
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            try:
                self._atomic_copy(path, self.backup_path_for(path.stem))
            except OSError:
                # The primary is already a complete, fsynced envelope. A backup
                # failure must not turn a successful state replacement into a
                # false corruption report.
                pass
            _fsync_directory(path.parent)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise AtomicWriteError(f"atomic state write failed for {path.name}: {exc}") from exc
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _atomic_copy(source: Path, target: Path) -> None:
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with source.open("rb") as source_handle, temp.open("wb") as target_handle:
                while True:
                    chunk = source_handle.read(1024 * 1024)
                    if not chunk:
                        break
                    target_handle.write(chunk)
                target_handle.flush()
                os.fsync(target_handle.fileno())
            os.replace(temp, target)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _validate_domain(domain: str) -> None:
        if domain not in DOMAINS:
            raise StateStoreError(f"unsupported state domain: {domain!r}")


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)


__all__ = [
    "AtomicWriteError",
    "StateNotFoundError",
    "StateStore",
    "StateStoreError",
]
