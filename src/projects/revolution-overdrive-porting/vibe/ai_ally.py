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
_RESCUE_CALL = "libNtve_gf_RescueUnit"
_AI_CALLS = ("AIStart", "AIMeleeStart")
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_INTEGER = re.compile(r"^-?\d+$")
_GV = re.compile(r"\b(gv_[A-Za-z0-9_]+)\b")
# PlayerGroupLoop iterator pattern: a group `auto<hex>_g` iterated by `auto<hex>_var`.
_DYN_PREFIX = re.compile(r"\b(auto[0-9A-Fa-f]{8})_(var|g)\b")
_GROUP_DEF = re.compile(r"\b(auto[0-9A-Fa-f]{8})_g\s*=\s*([^;]+);")
_PG_ADD = re.compile(r"PlayerGroupAdd\s*\(\s*auto[0-9A-Fa-f]{8}_g\s*,\s*([^)]+)\)")
_BUILTIN_GROUP = re.compile(
    r"\b(c_playerGroup\w*|PlayerGroupAll|PlayerGroupEnemyPlayers|"
    r"PlayerGroupAllyPlayers|PlayerGroupNeutralPlayers|PlayerGroupObservers|"
    r"libNtve_gf_PlayerGroupFromPlayer|PlayerGroupAlliance)\b"
)


@dataclass(frozen=True)
class StaticCall:
    """A parsed call, including arguments that could not be resolved.

    ``reason`` documents *why* a call stayed unresolved so the fail-closed audit
    trail is explicit rather than a silent drop.  Known values:
      - ``runtime_leader_identity``: an endpoint is a library global initialised
        at runtime (e.g. ``libA9E65AFF_gv_player01``) with no static integer
        assignment anywhere in the map's galaxy sources.
      - ``opaque_group``: the iterated player group expands to a builtin runtime
        group whose membership cannot be enumerated statically.
      - ``empty_group``: the iterated player group statically expands to nobody.
      - ``target_unresolved``: the non-iterator endpoint could not be resolved.
    """

    name: str
    arguments: tuple[str, ...]
    resolved_arguments: tuple[Optional[int], ...]
    line: int
    reason: Optional[str] = None


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
class AllyActivation:
    """Map-owned lifecycle gate for when an ally can receive actions."""

    mode: str
    ally_player_id: Optional[int]
    handover_unit_ref: Optional[str] = None
    handover_line: Optional[int] = None
    gate_unit_type: Optional[str] = None
    gate_region_id: Optional[int] = None
    gate_event_line: Optional[int] = None
    issues: tuple[str, ...] = tuple()

    def is_observed_active(self, owned_unit_count: int) -> bool:
        """Require a live native census for delayed or unresolved ally lifecycles."""

        if isinstance(owned_unit_count, bool) or owned_unit_count < 0:
            return False
        if self.mode == "immediate":
            return True
        if self.mode in {"time-gated", "observation-gated"}:
            return owned_unit_count > 0
        return False


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
    dynamic_alliance_calls: tuple[AllianceCall, ...]
    dynamic_unresolved_alliance_calls: tuple[StaticCall, ...]
    dynamic_resolved_call_count: int
    runtime_ally_activations: tuple[AllyActivation, ...]
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
    activation: AllyActivation

    def accepts_command_from(self, player_id: int) -> bool:
        """Only the map leader may issue commands through this contract."""

        return self.valid and player_id in self.authorized_command_sources

    def is_safe_target(self, player_id: int) -> bool:
        """Allow only positive, explicitly declared enemy owners."""

        if not self.valid or isinstance(player_id, bool):
            return False
        return player_id > 0 and player_id in self.valid_enemy_targets

    def ally_observation_ready(self, ally_owned_count: int) -> bool:
        """Return whether a native census proves that the ally can be controlled."""

        return self.valid and self.activation.is_observed_active(ally_owned_count)

    def can_dispatch_ally_action(self, source_player_id: int, ally_owned_count: int) -> bool:
        """Gate P1 -> P2 dispatch on both authorization and observed P2 ownership."""

        return self.accepts_command_from(source_player_id) and self.ally_observation_ready(ally_owned_count)


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


def _extract_ally_activations(
    source: str,
    map_name: str,
    aliases: Mapping[str, int],
) -> tuple[AllyActivation, ...]:
    """Extract safe handover facts without guessing unresolved trigger ownership."""

    activations: list[AllyActivation] = []
    gate_event = None
    gate_unit_type = None
    if map_name == "thorner03.SC2Map":
        gate_event = re.search(
            r"TriggerAddEventUnitRegion\([^;]*?RegionFromId\(24\)",
            source,
            re.DOTALL,
        )
        gate_unit_type = re.search(
            r'UnitGetType\(EventUnit\(\)\)\s*==\s*"([^"]+)"',
            source,
        )

    for raw_call in _iter_calls(source, (_RESCUE_CALL,)):
        call = _resolved_call(raw_call, aliases)
        if len(call.arguments) < 2:
            continue
        ally_player_id = call.resolved_arguments[1]
        if ally_player_id is None:
            continue

        gate_region_id: Optional[int] = None
        gate_line: Optional[int] = None
        gate_type: Optional[str] = None
        if (
            map_name == "thorner03.SC2Map"
            and ally_player_id == 2
            and call.arguments[0] == "UnitFromId(2)"
            and gate_event is not None
            and gate_unit_type is not None
        ):
            gate_region_id = 24
            gate_line = source.count("\n", 0, gate_event.start()) + 1
            gate_type = gate_unit_type.group(1)

        activations.append(
            AllyActivation(
                mode="time-gated",
                ally_player_id=ally_player_id,
                handover_unit_ref=call.arguments[0],
                handover_line=call.line,
                gate_unit_type=gate_type,
                gate_region_id=gate_region_id,
                gate_event_line=gate_line,
                issues=tuple(
                    issue
                    for issue, condition in (
                        ("handover_gate_not_linked", gate_region_id is None),
                        ("handover_gate_unit_type_unresolved", gate_type is None),
                    )
                    if condition
                ),
            )
        )
    return tuple(activations)


def _expand_group_members(prefix: str, clean_source: str, aliases: Mapping[str, int]) -> "set[int] | None":
    """Return concrete player IDs for a `auto<prefix>_g` group, or None if opaque.

    Opaque means the group is a builtin runtime group (e.g. ``PlayerGroupAll``)
    whose membership cannot be enumerated statically -> fail-closed.
    """

    players: set[int] = set()
    group_symbols: set[str] = set()
    assignments = list(re.finditer(rf"\b{prefix}_g\s*=\s*([^;]+);", clean_source))
    for assignment in assignments:
        expression = assignment.group(1).strip()
        if _IDENTIFIER.fullmatch(expression):
            group_symbols.add(expression)

    # Only expand PlayerGroupAdd calls that target the group bound to this
    # iterator. A global scan would merge unrelated mission groups.
    for match in re.finditer(
        r"PlayerGroupAdd\s*\(\s*([^,]+),\s*([^)]+)\)",
        clean_source,
    ):
        group_symbol = match.group(1).strip()
        if group_symbol not in group_symbols:
            continue
        value = _resolve(match.group(2), aliases)
        if value is not None and value >= 0:
            players.add(value)
    for expression_match in assignments:
        expr = expression_match.group(1).strip()
        if _BUILTIN_GROUP.search(expr):
            return None
        for gv in _GV.findall(expr):
            value = aliases.get(gv)
            if value is not None and value >= 0:
                players.add(value)
        for literal in re.findall(r"-?\d+", expr):
            if int(literal) >= 0:
                players.add(int(literal))
    return players


def _extract_dynamic_alliances(
    clean_source: str,
    aliases: Mapping[str, int],
) -> tuple[tuple[AllianceCall, ...], tuple[StaticCall, ...], int]:
    """Resolve ``PlayerGroupLoop`` SetAlliance calls whose owner side is an iterator.

    Galaxy maps iterate player groups with a generated variable ``auto<hex>_var``
    bound to group ``auto<hex>_g``. These calls cannot be resolved by the main
    alias pass (the owner is a loop variable), so they fall into
    ``unresolved_alliance_calls`` and the map fails closed.  This pass pairs each
    iterator with its group, expands the group to concrete players, and re-resolves
    the call.  Edges whose group is opaque/empty stay unresolved (fail-closed).
    """

    dynamic_calls: list[AllianceCall] = []
    unresolved_calls: list[StaticCall] = []
    resolved_count = 0

    groups: dict[str, "set[int] | None"] = {}
    for m in _GROUP_DEF.finditer(clean_source):
        groups[m.group(1)] = _expand_group_members(m.group(1), clean_source, aliases)

    for raw_call in _iter_calls(clean_source, (_ALLIANCE_CALL,)):
        arguments = raw_call.arguments
        if len(arguments) < 3:
            continue
        var_prefixes = {prefix for prefix, kind in _DYN_PREFIX.findall(" ".join(arguments)) if kind == "var"}
        if not var_prefixes:
            continue
        prefix = next(iter(var_prefixes))
        members = groups.get(prefix)
        if members is None:
            unresolved_calls.append(
                StaticCall(raw_call.name, raw_call.arguments, raw_call.resolved_arguments, raw_call.line, "opaque_group")
            )
            continue
        if not members:
            unresolved_calls.append(
                StaticCall(raw_call.name, raw_call.arguments, raw_call.resolved_arguments, raw_call.line, "empty_group")
            )
            continue
        target: "int | None" = None
        target_token: str = ""
        for argument in arguments[:2]:
            if re.search(rf"\b{prefix}_var\b", argument):
                continue
            target_token = argument.strip()
            target = _resolve(argument, aliases)
            if target is not None:
                break
        if target is None or target < 0:
            is_library_global = bool(
                _IDENTIFIER.fullmatch(target_token)
                and aliases.get(target_token) is None
                and ("_gv_" in target_token or re.search(r"^lib[0-9A-Fa-f]{8}_", target_token))
            )
            reason = "runtime_leader_identity" if is_library_global else "target_unresolved"
            unresolved_calls.append(
                StaticCall(raw_call.name, raw_call.arguments, raw_call.resolved_arguments, raw_call.line, reason)
            )
            continue
        resolved_count += 1
        relation = _relation(arguments[2])
        for player in sorted(members):
            dynamic_calls.append(
                AllianceCall(player, target, arguments[2], relation, raw_call.line, raw_call.arguments)
            )
    return tuple(dynamic_calls), tuple(unresolved_calls), resolved_count


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
    runtime_ally_activations = _extract_ally_activations(clean_source, map_path.name, aliases)
    dynamic_alliance_calls, dynamic_unresolved_calls, dynamic_resolved_count = _extract_dynamic_alliances(
        clean_source, aliases
    )

    after = script_path.read_bytes()
    if alliance_calls:
        classification = "mission"
    elif dynamic_alliance_calls:
        classification = "dynamic-mission"
    else:
        classification = "entry-flow"
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
        dynamic_alliance_calls=dynamic_alliance_calls,
        dynamic_unresolved_alliance_calls=dynamic_unresolved_calls,
        dynamic_resolved_call_count=dynamic_resolved_count,
        runtime_ally_activations=runtime_ally_activations,
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
    if roster.classification not in ("mission", "dynamic-mission"):
        issues.append("unsupported_map_classification")
    if not positive_ids(leader_player_id) or not positive_ids(ally_player_id):
        issues.append("invalid_player_id")
    if leader_player_id == ally_player_id:
        issues.append("leader_and_ally_must_differ")

    # Union of explicitly-resolved edges and group-expanded (PlayerGroupLoop) edges.
    # Dynamic edges are genuine map facts; folding them in completes the contract
    # surface for the 24 maps whose owner side is a loop iterator (RO-AI-001).
    allies: DefaultDict[int, set[int]] = defaultdict(set)
    enemies: DefaultDict[int, set[int]] = defaultdict(set)
    for player, targets in roster.direct_allies_by_player.items():
        for target in targets:
            allies[player].add(target)
            allies[target].add(player)
    for player, targets in roster.direct_enemies_by_player.items():
        for target in targets:
            enemies[player].add(target)
            enemies[target].add(player)
    for call in roster.dynamic_alliance_calls:
        if call.source_player is None or call.target_player is None:
            continue
        source, target = call.source_player, call.target_player
        if call.relation == "ally":
            allies[source].add(target)
            allies[target].add(source)
        else:
            enemies[source].add(target)
            enemies[target].add(source)
    leader_allies = frozenset(allies.get(leader_player_id, set()))
    leader_enemies = frozenset(enemies.get(leader_player_id, set()))
    if ally_player_id not in leader_allies:
        issues.append("no_explicit_leader_ally_edge")
    if ally_player_id in leader_enemies:
        issues.append("leader_ally_conflict")

    activation_candidates = tuple(
        activation
        for activation in roster.runtime_ally_activations
        if activation.ally_player_id == ally_player_id
    )
    if len(activation_candidates) == 1:
        activation = activation_candidates[0]
    elif len(activation_candidates) > 1:
        activation = AllyActivation(
            mode="ambiguous",
            ally_player_id=ally_player_id,
            issues=("multiple_handover_paths",),
        )
    else:
        activation = AllyActivation(
            mode="observation-gated",
            ally_player_id=ally_player_id,
            issues=("no_static_handover_path",),
        )

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
        activation=activation,
    )
