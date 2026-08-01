"""Session identity returned by the Neuro startup handshake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class NeuroSessionIdentity:
    session_id: str
    character_id: str
    display_name: str

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if not self.character_id.strip():
            raise ValueError("character_id must not be empty")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")

    @classmethod
    def from_startup_data(cls, data: Mapping[str, Any]) -> "NeuroSessionIdentity":
        session = data.get("session")
        if not isinstance(session, Mapping):
            raise ValueError("startup data must contain a session object")
        return cls(
            session_id=str(session.get("sessionId") or "").strip(),
            character_id=str(session.get("characterId") or "").strip(),
            display_name=str(session.get("displayName") or "").strip(),
        )
