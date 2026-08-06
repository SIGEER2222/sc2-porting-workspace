"""Static, mission-owned AI ally contracts for Revolution Overdrive maps.

The adapter reads unpacked MapScript.galaxy files and never writes to the map.  It
only turns relationships that are statically resolvable from literal player IDs
into an action contract.  Dynamic Galaxy expressions remain visible as call
records but cannot authorize an ally or target.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import DefaultDict, Iterable, Mapping, Optional, Sequence


_ALLIANCE_CALL = "libNtve_gf_SetAlliance"
_PLAYER_SET_ALLIANCE_CALL = "PlayerSetAlliance"
_PLAYER_GROUP_ADD_CALL = "PlayerGroupAdd"
_AI_CALLS = ("AIStart", "AIMeleeStart")
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_INTEGER = re.compile(r"^-?\d+$")


@dataclass(frozen=True)
class StaticCall:
    """A parsed call, including arguments that could not be resolved."""

    name: str
    arguments: tuple[str, ...]
    resolved_arguments: tuple[Optional[int], ...]
    line: int


@dataclass(frozen=True)
class AllianceCall:
    """A SetAlliance call and its safe-to-use player resolution."""

    source_player: Optional[int]
    target_player: Optional[int]
    setting: str
    relation: str
    line: int
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class PlayerSetAllianceCall:
    """A low-level alliance-channel call preserved for audit purposes."""

    source_player: Optional[int]
    alliance_id: str
    target_player: Optional[int]
    enabled: str
    line: int
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class PlayerGroupAddCall:
    """A PlayerGroupAdd call with a resolved player where possible."""

    group: str
    player: Optional[int]
    line: int
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class MapRoster:
    """Static relationship information extracted from one owned map script."""

    map_name: str
    map_script: str
    classification: str
    aliases: Mapping[str, int]
    direct_allies_by_player: Mapping[int, frozenset[int]]
    direct_enemies_by_player: Mapping[int, frozenset[int]]
    player_groups: Mapping[str, frozenset[int]]
    alliance_calls: tuple[AllianceCall, ...]
    player_set_alliance_calls: tuple[PlayerSetAllianceCall, ...]
    player_group_add_calls: tuple[PlayerGroupAddCall, ...]
    unresolved_alliance_calls: tuple[StaticCall, ...]
    generic_ai_start_calls: tuple[StaticCall, ...]
    generic_ai_melee_start_calls: tuple[StaticCall, ...]
    source_hash: str
    map_script_preserved: bool

    @property
    def explicit_enemy_players(self) -> frozenset[int]:
        """Return all enemy owners explicitly declared by the map."""

        enemies: set[int] = set()
        for players in self.direct_enemies_by_player.values():
            enemies.update(players)
        return frozenset(enemies)


@dataclass(frozen=True)
class AllyContract:
    """Fail-closed action and observation boundary for one map pairing."""

    valid: bool
    map_name: str
    leader_player_id: int
    ally_player_id: int
    authorized_command_sources: tuple[int, ...]
    observed_player_ids: tuple[int, ...]
    valid_enemy_targets: tuple[int, ...]
    issues: tuple[str, ...]

    def accepts_command_from(self, player_id: int) -> bool:
        """Only the map leader may issue commands through this contract."""

        return self.valid and player_id in self.authorized_command_sources

    def is_safe_target(self, player_id: int) -> bool:
        """Allow only positive, explicitly declared enemy owners."""

        if not self.valid or isinstance(player_id, bool):
            return False
        return player_id > 0 and player_id in self.valid_enemy_targets


def _strip_comments(source: str) -> str:
    """Remove Galaxy comments while preserving strings and line numbers."""

    output: list[str] = []
    index = 0
    in_string = False
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if in_string:
            output.append(char)
            if char == "\\" and next_char:
                output.append(next_char)
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(source) and source[index] != "\n":
                index += 1
            if index < len(source):
                output.append("\n")
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index < len(source):
                if source[index] == "*" and index + 1 < len(source) and source[index + 1] == "/":
                    index += 2
                    break
                if source[index] == "\n":
                    output.append("\n")
                index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _extract_aliases(source: str) -> dict[str, int]:
    """Resolve only stable integer assignments for global player aliases."""

    candidates: DefaultDict[str, set[int]] = defaultdict(set)
    assignment_pattern = re.compile(
        r"(?m)^\s*(?:(?:const\s+)?int\s+)?([A-Za-z_]\w*)\s*=\s*(-?\d+)\s*;"
    )
    for match in assignment_pattern.finditer(source):
        name = match.group(1)
        if name.startswith("gv_") or "_gv_" in name:
            candidates[name].add(int(match.group(2)))
    return {name: next(iter(values)) for name, values in candidates.items() if len(values) == 1}


def _extract_parenthesized(source: str, open_index: int) -> tuple[str, int]:
    """Return call contents and the index immediately after its closing paren."""

    depth = 0
    in_string = False
    index = open_index
    content_start = open_index + 1
    while index < len(source):
        char = source[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[content_start:index], index + 1
        index += 1
    raise ValueError("unterminated Galaxy call")


def _split_arguments(arguments: str) -> tuple[str, ...]:
    """Split a call's top-level comma-separated arguments."""

    values: list[str] = []
    start = 0
    depth = 0
    in_string = False
    index = 0
    while index < len(arguments):
        char = arguments[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            values.append(arguments[start:index].strip())
            start = index + 1
        index += 1
    final = arguments[start:].strip()
    if final or values:
        values.append(final)
    return tuple(values)


def _iter_calls(source: str, names: Iterable[str]) -> Iterable[StaticCall]:
    """Yield named function calls without treating identifiers as calls."""

    for name in names:
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}\s*\(")
        for match in pattern.finditer(source):
            arguments, _ = _extract_parenthesized(source, match.end() - 1)
            raw_arguments = _split_arguments(arguments)
            line = source.count("\n", 0, match.start()) + 1
            yield StaticCall(name, raw_arguments, tuple(None for _ in raw_arguments), line)


def _resolve(token: str, aliases: Mapping[str, int]) -> Optional[int]:
    token = token.strip()
    if _INTEGER.fullmatch(token):
        return int(token)
    if _IDENTIFIER.fullmatch(token):
        return aliases.get(token)
    return None


def _relation(setting: str) -> str:
    lowered = setting.lower()
    if "enemy" in lowered:
        return "enemy"
    if "neutral" in lowered:
        return "neutral"
    if "ally" in lowered:
        return "ally"
    return "unknown"


def _resolved_call(call: StaticCall, aliases: Mapping[str, int]) -> StaticCall:
    return StaticCall(
        call.name,
        call.arguments,
        tuple(_resolve(argument, aliases) for argument in call.arguments),
        call.line,
    )


def _map_of_sets(values: Mapping[int, set[int]]) -> Mapping[int, frozenset[int]]:
    return {key: frozenset(sorted(items)) for key, items in values.items()}


def extract_map_roster(map_dir: Path | str) -> MapRoster:
    """Extract one map's static roster without modifying its source."""

    map_path = Path(map_dir)
    script_path = map_path / "MapScript.galaxy"
    before = script_path.read_bytes()
    source = before.decode("utf-8-sig", errors="replace")
    clean_source = _strip_comments(source)
    aliases = _extract_aliases(clean_source)

    alliance_calls: list[AllianceCall] = []
    unresolved_alliance_calls: list[StaticCall] = []
    allies: DefaultDict[int, set[int]] = defaultdict(set)
    enemies: DefaultDict[int, set[int]] = defaultdict(set)
    for raw_call in _iter_calls(clean_source, (_ALLIANCE_CALL,)):
        call = _resolved_call(raw_call, aliases)
        if len(call.arguments) < 3:
            unresolved_alliance_calls.append(call)
            continue
        source_player = call.resolved_arguments[0]
        target_player = call.resolved_arguments[1]
        setting = call.arguments[2]
        relation = _relation(setting)
        parsed = AllianceCall(
            source_player,
            target_player,
            setting,
            relation,
            call.line,
            call.arguments,
        )
        alliance_calls.append(parsed)
        if source_player is None or target_player is None or relation not in {"ally", "enemy"}:
            if source_player is None or target_player is None:
                unresolved_alliance_calls.append(call)
            continue
        target_set = allies if relation == "ally" else enemies
        target_set[source_player].add(target_player)
        target_set[target_player].add(source_player)

    player_set_alliance_calls: list[PlayerSetAllianceCall] = []
    for raw_call in _iter_calls(clean_source, (_PLAYER_SET_ALLIANCE_CALL,)):
        call = _resolved_call(raw_call, aliases)
        if len(call.arguments) < 4:
            continue
        player_set_alliance_calls.append(
            PlayerSetAllianceCall(
                call.resolved_arguments[0],
                call.arguments[1],
                call.resolved_arguments[2],
                call.arguments[3],
                call.line,
                call.arguments,
            )
        )

    player_group_add_calls: list[PlayerGroupAddCall] = []
    groups: DefaultDict[str, set[int]] = defaultdict(set)
    for raw_call in _iter_calls(clean_source, (_PLAYER_GROUP_ADD_CALL,)):
        call = _resolved_call(raw_call, aliases)
        if len(call.arguments) < 2:
            continue
        player = call.resolved_arguments[1]
        group = call.arguments[0]
        player_group_add_calls.append(PlayerGroupAddCall(group, player, call.line, call.arguments))
        if player is not None:
            groups[group].add(player)

    generic_ai_start_calls = tuple(
        _resolved_call(call, aliases)
        for call in _iter_calls(clean_source, ("AIStart",))
    )
    generic_ai_melee_start_calls = tuple(
        _resolved_call(call, aliases)
        for call in _iter_calls(clean_source, ("AIMeleeStart",))
    )

    after = script_path.read_bytes()
    classification = "mission" if alliance_calls else "entry-flow"
    return MapRoster(
        map_name=map_path.name,
        map_script=f"{map_path.name}/MapScript.galaxy",
        classification=classification,
        aliases=dict(sorted(aliases.items())),
        direct_allies_by_player=_map_of_sets(allies),
        direct_enemies_by_player=_map_of_sets(enemies),
        player_groups={key: frozenset(sorted(value)) for key, value in sorted(groups.items())},
        alliance_calls=tuple(alliance_calls),
        player_set_alliance_calls=tuple(player_set_alliance_calls),
        player_group_add_calls=tuple(player_group_add_calls),
        unresolved_alliance_calls=tuple(unresolved_alliance_calls),
        generic_ai_start_calls=generic_ai_start_calls,
        generic_ai_melee_start_calls=generic_ai_melee_start_calls,
        source_hash=hashlib.sha256(before).hexdigest(),
        map_script_preserved=before == after,
    )


def extract_all_map_rosters(maps_root: Path | str) -> list[MapRoster]:
    """Extract all unpacked SC2Map directories in deterministic order."""

    root = Path(maps_root)
    return [extract_map_roster(path) for path in sorted(root.glob("*.SC2Map")) if path.is_dir()]


def build_ally_contract(
    roster: MapRoster,
    leader_player_id: int,
    ally_player_id: int,
) -> AllyContract:
    """Build a mission-derived, fail-closed command and target contract."""

    issues: list[str] = []
    positive_ids = lambda value: isinstance(value, int) and not isinstance(value, bool) and value > 0
    if roster.classification != "mission":
        issues.append("unsupported_map_classification")
    if not positive_ids(leader_player_id) or not positive_ids(ally_player_id):
        issues.append("invalid_player_id")
    if leader_player_id == ally_player_id:
        issues.append("leader_and_ally_must_differ")

    leader_allies = roster.direct_allies_by_player.get(leader_player_id, frozenset())
    leader_enemies = roster.direct_enemies_by_player.get(leader_player_id, frozenset())
    if ally_player_id not in leader_allies:
        issues.append("no_explicit_leader_ally_edge")
    if ally_player_id in leader_enemies:
        issues.append("leader_ally_conflict")

    safe_targets = sorted(
        target
        for target in leader_enemies
        if positive_ids(target) and target != ally_player_id and target not in leader_allies
    )
    valid = not issues
    return AllyContract(
        valid=valid,
        map_name=roster.map_name,
        leader_player_id=leader_player_id,
        ally_player_id=ally_player_id,
        authorized_command_sources=(leader_player_id,) if valid else tuple(),
        observed_player_ids=(leader_player_id, ally_player_id) if valid else tuple(),
        valid_enemy_targets=tuple(safe_targets) if valid else tuple(),
        issues=tuple(issues),
    )
