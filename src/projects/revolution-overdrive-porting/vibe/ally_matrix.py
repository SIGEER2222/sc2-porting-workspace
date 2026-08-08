"""Ally-pair capability matrix for Revolution Overdrive owned maps.

Purpose (RO-AI-001 generalization evidence)
-------------------------------------------
Stage 08 proved a single map (``thorner03``) hands P2 a native ally.  The open
question left behind was whether the static contract adapter generalizes: 24 of
31 owned maps declare their alliances through ``PlayerGroupLoop`` iterators, so
their owner side is a runtime variable and every edge failed closed.

``ai_ally._extract_dynamic_alliances`` now pairs each ``auto<hex>_var`` iterator
with its ``auto<hex>_g`` group and expands the group to concrete player IDs.
This module measures what that buys us: for every owned map it enumerates every
``(leader, ally)`` pair for which :func:`ai_ally.build_ally_contract` returns a
valid, fail-closed contract, and attributes each pair to *static* edges alone or
to edges that only exist after dynamic group expansion.

The module is read-only: it never writes to a map and never mutates a roster.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import DefaultDict, Iterable, Mapping, Sequence

try:  # package import (preferred)
    from .ai_ally import AllyContract, MapRoster, build_ally_contract, extract_all_map_rosters
except ImportError:  # pragma: no cover - direct `python vibe/ally_matrix.py` execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ai_ally import (  # type: ignore[no-redef]
        AllyContract,
        MapRoster,
        build_ally_contract,
        extract_all_map_rosters,
    )

# Player IDs the campaign reserves for non-participant roles.  They may appear
# as alliance endpoints but are never legal ally candidates for a human leader.
_RESERVED_PLAYER_IDS = frozenset({0, 15, 16})
# SC2 supports 15 controllable slots; anything past that is an engine sentinel.
_MAX_PLAYER_ID = 15


@dataclass(frozen=True)
class AllyPair:
    """One ``(leader, ally)`` pairing that yields a valid contract."""

    leader_player_id: int
    ally_player_id: int
    enemy_targets: tuple[int, ...]
    activation_mode: str
    #: ``"static"`` when literal-ID edges alone authorize the pair, ``"dynamic"``
    #: when the pair only exists after PlayerGroupLoop group expansion.
    evidence: str

    def as_dict(self) -> dict:
        return {
            "leaderPlayerId": self.leader_player_id,
            "allyPlayerId": self.ally_player_id,
            "enemyTargets": list(self.enemy_targets),
            "activationMode": self.activation_mode,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class MapAllyCapability:
    """Ally capability summary for a single owned map."""

    map_name: str
    classification: str
    alliance_call_count: int
    dynamic_resolved_call_count: int
    dynamic_unresolved_call_count: int
    pairs: tuple[AllyPair, ...] = field(default=tuple())

    @property
    def supported(self) -> bool:
        return bool(self.pairs)

    @property
    def needs_dynamic_expansion(self) -> bool:
        """True when the map has no purely-static ally pair but a dynamic one."""

        if not self.pairs:
            return False
        return all(pair.evidence == "dynamic" for pair in self.pairs)

    def as_dict(self) -> dict:
        return {
            "mapName": self.map_name,
            "classification": self.classification,
            "allianceCallCount": self.alliance_call_count,
            "dynamicResolvedCallCount": self.dynamic_resolved_call_count,
            "dynamicUnresolvedCallCount": self.dynamic_unresolved_call_count,
            "supported": self.supported,
            "needsDynamicExpansion": self.needs_dynamic_expansion,
            "pairs": [pair.as_dict() for pair in self.pairs],
        }


def _candidate_player_ids(roster: MapRoster) -> list[int]:
    """Collect every plausible controllable player ID referenced by the map."""

    seen: set[int] = set()
    sources: Iterable[Mapping[int, frozenset[int]]] = (
        roster.direct_allies_by_player,
        roster.direct_enemies_by_player,
    )
    for mapping in sources:
        for player, targets in mapping.items():
            seen.add(player)
            seen.update(targets)
    for call in roster.dynamic_alliance_calls:
        for value in (call.source_player, call.target_player):
            if value is not None:
                seen.add(value)
    return sorted(
        player
        for player in seen
        if isinstance(player, int)
        and not isinstance(player, bool)
        and 0 < player <= _MAX_PLAYER_ID
        and player not in _RESERVED_PLAYER_IDS
    )


def _static_only_roster(roster: MapRoster) -> MapRoster:
    """Return a copy of ``roster`` with dynamic (group-expanded) edges removed.

    Used to attribute each valid pair to static or dynamic evidence.  Building a
    contract from this copy answers "would this pair exist without RO-AI-001?".
    """

    from dataclasses import replace

    return replace(
        roster,
        dynamic_alliance_calls=tuple(),
        dynamic_resolved_call_count=0,
    )


def build_map_capability(roster: MapRoster) -> MapAllyCapability:
    """Enumerate every valid ally pairing the map itself authorizes."""

    static_roster = _static_only_roster(roster)
    pairs: list[AllyPair] = []
    candidates = _candidate_player_ids(roster)
    for leader in candidates:
        for ally in candidates:
            if leader == ally:
                continue
            contract: AllyContract = build_ally_contract(roster, leader, ally)
            if not contract.valid:
                continue
            static_contract = build_ally_contract(static_roster, leader, ally)
            pairs.append(
                AllyPair(
                    leader_player_id=leader,
                    ally_player_id=ally,
                    enemy_targets=contract.valid_enemy_targets,
                    activation_mode=contract.activation.mode,
                    evidence="static" if static_contract.valid else "dynamic",
                )
            )
    return MapAllyCapability(
        map_name=roster.map_name,
        classification=roster.classification,
        alliance_call_count=len(roster.alliance_calls),
        dynamic_resolved_call_count=roster.dynamic_resolved_call_count,
        dynamic_unresolved_call_count=len(roster.dynamic_unresolved_alliance_calls),
        pairs=tuple(pairs),
    )


def build_capability_matrix(maps_root: Path | str) -> list[MapAllyCapability]:
    """Build the capability matrix for every unpacked owned map."""

    return [build_map_capability(roster) for roster in extract_all_map_rosters(maps_root)]


def summarize(matrix: Sequence[MapAllyCapability]) -> dict:
    """Aggregate the matrix into a report payload."""

    by_evidence: DefaultDict[str, int] = defaultdict(int)
    for capability in matrix:
        for pair in capability.pairs:
            by_evidence[pair.evidence] += 1

    supported = [c for c in matrix if c.supported]
    dynamic_only = [c for c in supported if c.needs_dynamic_expansion]
    unsupported = [c for c in matrix if not c.supported]
    return {
        "mapCount": len(matrix),
        "supportedMapCount": len(supported),
        "dynamicOnlyMapCount": len(dynamic_only),
        "unsupportedMapCount": len(unsupported),
        "pairCountByEvidence": dict(sorted(by_evidence.items())),
        "dynamicResolvedCallTotal": sum(c.dynamic_resolved_call_count for c in matrix),
        "dynamicUnresolvedCallTotal": sum(c.dynamic_unresolved_call_count for c in matrix),
        "supportedMaps": [c.map_name for c in supported],
        "dynamicOnlyMaps": [c.map_name for c in dynamic_only],
        "unsupportedMaps": [c.map_name for c in unsupported],
    }


def build_report(maps_root: Path | str) -> dict:
    """Build the full JSON-serializable capability report."""

    matrix = build_capability_matrix(maps_root)
    return {
        "schemaVersion": 1,
        "issue": "RO-AI-001",
        "sourceMutated": False,
        "summary": summarize(matrix),
        "maps": [capability.as_dict() for capability in matrix],
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps-root", required=True, help="Directory of unpacked *.SC2Map folders")
    parser.add_argument("--out", help="Write the JSON report to this path")
    args = parser.parse_args(argv)

    report = build_report(args.maps_root)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {out_path}")
    summary = report["summary"]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
