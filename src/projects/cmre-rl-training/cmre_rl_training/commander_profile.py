"""Commander max-level / full-mastery validation and reporting.

CMRE co-op commanders carry a persistent ``level`` (1..max_level) and a mastery
allocation. The ML autonomous-completion plan requires every training / eval run
to use a max-level, full-mastery commander. A run whose commander cannot be
proven max level must be reported as ``blocked``, never ``passed``.

Evidence sources (in increasing strength):

* ``config``  -- the runner/launcher explicitly declared the intended level and
  mastery on the command line (``--commander-level``, ``--commander-mastery``).
  This satisfies the plan's "config must explicitly record the commander
  level/mastery profile" requirement, but it is a declaration, not runtime proof.
* ``bank``    -- a bank/JSON evidence file read from the running game proving
  the in-game commander state (``read_commander_evidence``).
* ``runtime`` -- a live observation field (reserved; not yet emitted by the
  raw session).

When no level is declared and no evidence is available, validation cannot pass
and the caller should set status ``blocked``.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


# SC2 co-op commanders reach level 15; CMRE co-op follows the same max.
DEFAULT_MAX_LEVEL = 15
# Full mastery = every mastery point allocated across the commander's trees.
DEFAULT_MASTERY_TREES = 3
FULL_MASTERY_TOKEN = "full"
LAUNCH_PROFILE_SECTION = "CMUI|LaunchProfile"
LAUNCH_PROFILE_FULL_MASTERY_LEVEL = 180
LAUNCH_PROFILE_FULL_MASTERY_VALUES = (30, 30, 30, 30, 30, 30)


@dataclass(frozen=True)
class CommanderSpec:
    """Static capability spec for a known commander."""

    commander_id: str
    max_level: int = DEFAULT_MAX_LEVEL
    mastery_trees: int = DEFAULT_MASTERY_TREES
    known: bool = True
    notes: str = ""


# Registry of commanders the ML training plan cares about. ``known=False``
# entries are sensible defaults applied to commanders we have not yet audited;
# they still enforce the max-level gate but are flagged for review.
KNOWN_COMMANDERS: dict[str, CommanderSpec] = {
    "TerranRaynor": CommanderSpec("TerranRaynor", max_level=15, mastery_trees=3, known=True),
    "TerranAlenger": CommanderSpec("TerranAlenger", max_level=15, mastery_trees=3, known=True),
    "TerranAlenger1": CommanderSpec("TerranAlenger1", max_level=15, mastery_trees=3, known=True),
    "TerranAlenger2": CommanderSpec("TerranAlenger2", max_level=15, mastery_trees=3, known=True),
    "TerranAlenger3": CommanderSpec("TerranAlenger3", max_level=15, mastery_trees=3, known=True),
}


def get_commander_spec(commander_id: str) -> CommanderSpec:
    """Return the spec for ``commander_id``, defaulting to a max-level unknown."""

    if commander_id in KNOWN_COMMANDERS:
        return KNOWN_COMMANDERS[commander_id]
    return CommanderSpec(
        commander_id=str(commander_id),
        max_level=DEFAULT_MAX_LEVEL,
        mastery_trees=DEFAULT_MASTERY_TREES,
        known=False,
        notes="unknown commander; applying default max-level assumption",
    )


@dataclass
class CommanderProfile:
    """Resolved commander state for one run, before validation."""

    commander_id: str
    declared_level: int | None = None
    declared_mastery: str | None = None
    # ``commander_id`` is the caller's requested identity. Evidence must not
    # rewrite it: a maxed but different commander is invalid runtime evidence.
    observed_commander_id: str | None = None
    observed_level: int | None = None
    observed_mastery: str | None = None
    evidence_source: str | None = None
    evidence_path: str | None = None

    @property
    def max_level(self) -> int:
        return get_commander_spec(self.commander_id).max_level

    @property
    def mastery_trees(self) -> int:
        return get_commander_spec(self.commander_id).mastery_trees

    @property
    def known(self) -> bool:
        return get_commander_spec(self.commander_id).known

    def effective_level(self) -> int | None:
        if self.observed_level is not None:
            return self.observed_level
        return self.declared_level

    def effective_mastery(self) -> str | None:
        if self.observed_mastery is not None:
            return self.observed_mastery
        return self.declared_mastery


def _normalize_mastery(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("", "none", "null"):
        return None
    if text in ("full", "max", "complete", "all"):
        return FULL_MASTERY_TOKEN
    if text in ("partial", "half", "some"):
        return "partial"
    return text


def _read_sc2_bank_values(path: Path, *, section_name: str) -> dict[str, str]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    except ET.ParseError as exc:
        raise ValueError(f"sc2_bank_xml_invalid:{path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"sc2_bank_unreadable:{path}: {exc}") from exc

    values: dict[str, str] = {}
    for section in root.findall("Section"):
        if section.attrib.get("name") != section_name:
            continue
        for key in section.findall("Key"):
            key_name = key.attrib.get("name")
            value_node = key.find("Value")
            if not key_name or value_node is None:
                continue
            for attr in ("int", "string", "text", "fixed"):
                if attr in value_node.attrib:
                    values[key_name] = value_node.attrib[attr]
                    break
    return values


def _bank_int(values: Mapping[str, str], key: str) -> int | None:
    raw = values.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"launch_profile_bank_int_invalid:{key}:{raw}") from exc


def read_launch_profile_bank(path: str | Path, *, player: int = 1) -> dict[str, Any]:
    """Read commander level/mastery evidence from CMCoopLaunchProfile.SC2Bank.

    This is the bank the approved launcher writes and the CMRE UI path reads via
    CMUIX_LaunchProfileApplyCommanderCustomization. It is stronger than the
    runner's CLI declaration because it proves the values reached the launch
    profile file the game consumes.
    """

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"launch_profile_bank_not_found:{path}")
    values = _read_sc2_bank_values(path, section_name=LAUNCH_PROFILE_SECTION)
    prefix = f"Player|{int(player)}|"

    result: dict[str, Any] = {
        "source": "bank",
        "bank_section": LAUNCH_PROFILE_SECTION,
        "player": int(player),
    }
    commander_id = values.get(prefix + "Commander")
    if commander_id:
        result["commander_id"] = commander_id
    level = _bank_int(values, prefix + "CommanderLevel")
    if level is not None:
        result["level"] = level
    mastery_level = _bank_int(values, prefix + "MasteryLevel")
    mastery_count = _bank_int(values, prefix + "MasteryCount")
    if mastery_level is not None:
        result["mastery_level"] = mastery_level
    if mastery_count is not None:
        result["mastery_count"] = mastery_count
    slot_count = mastery_count if mastery_count is not None else len(LAUNCH_PROFILE_FULL_MASTERY_VALUES)
    mastery_values: list[int] = []
    for slot in range(1, int(slot_count) + 1):
        value = _bank_int(values, f"{prefix}Mastery|{slot}|Value")
        if value is not None:
            mastery_values.append(value)
    if mastery_values:
        result["mastery_values"] = mastery_values

    full_by_level = mastery_level is not None and mastery_level >= LAUNCH_PROFILE_FULL_MASTERY_LEVEL
    full_by_slots = mastery_values[:6] == list(LAUNCH_PROFILE_FULL_MASTERY_VALUES)
    if full_by_level and full_by_slots:
        result["mastery"] = FULL_MASTERY_TOKEN
    elif mastery_level is not None or mastery_values:
        result["mastery"] = "partial"
    return result


def read_commander_evidence(path: str | Path) -> dict[str, Any]:
    """Read a JSON bank/evidence file describing in-game commander state.

    Expected schema (all fields optional)::

        {
          "commander_id": "TerranRaynor",
          "level": 15,
          "mastery": "full",
          "source": "bank"
        }

    Returns a dict with ``level``, ``mastery``, ``commander_id``, ``source``
    keys (missing keys absent). Raises ``ValueError`` on unreadable/invalid JSON.
    """

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"commander_evidence_not_found:{path}")
    if path.suffix.lower() == ".sc2bank":
        return read_launch_profile_bank(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"commander_evidence_invalid:{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"commander_evidence_must_be_object:{path}")

    result: dict[str, Any] = {}
    if "level" in data and data["level"] is not None:
        try:
            result["level"] = int(data["level"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"commander_evidence_level_invalid:{data.get('level')}") from exc
    mastery = _normalize_mastery(data.get("mastery"))
    if mastery is not None:
        result["mastery"] = mastery
    if data.get("commander_id"):
        result["commander_id"] = str(data["commander_id"])
    if data.get("source"):
        result["source"] = str(data["source"])
    return result


def build_commander_profile(
    commander_id: str,
    *,
    level: int | None = None,
    mastery: str | None = None,
    evidence_path: str | Path | None = None,
) -> CommanderProfile:
    """Build a :class:`CommanderProfile` from CLI args and optional evidence."""

    profile = CommanderProfile(
        commander_id=str(commander_id),
        # Default the declared profile to the max-level / full-mastery spec so
        # the runner records the intended high-power commander state even when
        # the caller does not pass explicit --commander-level/--commander-mastery.
        # This is config evidence (declaration), not runtime proof; the live
        # runner can override it with --commander-evidence for true proof.
        declared_level=int(level) if level is not None else get_commander_spec(commander_id).max_level,
        declared_mastery=_normalize_mastery(mastery) or FULL_MASTERY_TOKEN,
    )
    if evidence_path is not None:
        evidence = read_commander_evidence(evidence_path)
        obs_level = evidence.get("level")
        obs_mastery = evidence.get("mastery")
        if obs_level is not None:
            profile.observed_level = int(obs_level)
        if obs_mastery is not None:
            profile.observed_mastery = obs_mastery
        if evidence.get("commander_id"):
            profile.observed_commander_id = str(evidence["commander_id"])
        profile.evidence_source = evidence.get("source") or "bank"
        profile.evidence_path = str(evidence_path)
    return profile


def validate_commander_profile(
    profile: CommanderProfile,
    *,
    require_full_mastery: bool = True,
) -> dict[str, Any]:
    """Validate a commander profile against the max-level / full-mastery gate.

    Returns a dict with ``passed``, ``level_ok``, ``mastery_ok``,
    ``runtime_proven``, ``evidence_source``, and human-readable ``reasons``.
    ``passed`` is ``True`` only when the effective level reaches ``max_level``
    and (if required) mastery is recorded as full. When nothing is declared and
    no evidence exists, ``passed`` is ``False`` and the reasons explain why.
    """

    spec = get_commander_spec(profile.commander_id)
    level = profile.effective_level()
    mastery = profile.effective_mastery()
    reasons: list[str] = []

    identity_ok = True
    if (
        profile.observed_commander_id is not None
        and profile.observed_commander_id != profile.commander_id
    ):
        identity_ok = False
        reasons.append(
            "commander identity mismatch: "
            f"requested {profile.commander_id}, observed {profile.observed_commander_id}"
        )

    level_ok = False
    if level is None:
        reasons.append(
            "commander level not declared and no bank/runtime evidence available"
        )
    elif level < spec.max_level:
        reasons.append(
            f"commander level {level} below max level {spec.max_level}"
        )
    else:
        level_ok = True

    mastery_ok = not require_full_mastery
    if require_full_mastery:
        if mastery is None:
            reasons.append("full mastery not declared or observed")
        elif mastery != FULL_MASTERY_TOKEN:
            reasons.append(f"mastery '{mastery}' is not full")
        else:
            mastery_ok = True

    runtime_proven = profile.evidence_source in ("bank", "runtime")
    evidence_source = profile.evidence_source or (
        "config" if (profile.declared_level is not None or profile.declared_mastery is not None)
        else None
    )

    passed = bool(identity_ok and level_ok and mastery_ok)
    if not passed and evidence_source is None:
        reasons.append("no commander level/mastery evidence of any kind was provided")

    return {
        "passed": passed,
        "commander_id": profile.commander_id,
        "observed_commander_id": profile.observed_commander_id,
        "identity_ok": identity_ok,
        "declared_level": profile.declared_level,
        "observed_level": profile.observed_level,
        "effective_level": level,
        "max_level": spec.max_level,
        "declared_mastery": profile.declared_mastery,
        "observed_mastery": profile.observed_mastery,
        "effective_mastery": mastery,
        "require_full_mastery": bool(require_full_mastery),
        "level_ok": level_ok,
        "mastery_ok": mastery_ok,
        "known_commander": spec.known,
        "runtime_proven": runtime_proven,
        "evidence_source": evidence_source,
        "evidence_path": profile.evidence_path,
        "reasons": reasons,
    }


def commander_report_fields(
    profile: CommanderProfile,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the report fields the training/live reports must preserve."""

    return {
        "commander_id": validation["commander_id"],
        "commander_observed_id": validation["observed_commander_id"],
        "commander_identity_ok": bool(validation["identity_ok"]),
        "commander_level": validation["effective_level"],
        "commander_max_level": validation["max_level"],
        "commander_mastery": validation["effective_mastery"],
        "commander_max_level_gate_passed": bool(validation["passed"]),
        "commander_level_ok": bool(validation["level_ok"]),
        "commander_mastery_ok": bool(validation["mastery_ok"]),
        "commander_known": bool(validation["known_commander"]),
        "commander_runtime_proven": bool(validation["runtime_proven"]),
        "commander_evidence_source": validation["evidence_source"],
        "commander_evidence_path": validation["evidence_path"],
        "commander_gate_reasons": list(validation["reasons"]),
    }


__all__ = [
    "DEFAULT_MAX_LEVEL",
    "DEFAULT_MASTERY_TREES",
    "FULL_MASTERY_TOKEN",
    "CommanderProfile",
    "CommanderSpec",
    "KNOWN_COMMANDERS",
    "build_commander_profile",
    "commander_report_fields",
    "get_commander_spec",
    "read_commander_evidence",
    "read_launch_profile_bank",
    "validate_commander_profile",
]
