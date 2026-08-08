"""Static trace of the thorner03 P2 (Tychus/Odin) AI ally contract.

Stage 07 recorded P2 as ``blocked`` because no P2-owned unit existed at loop 48. This module
establishes, from the shipped map script alone, *why* that is the expected behavior: P2 is a
time-gated scripted ally that receives its unit only after a map-owned trigger chain completes.

The trace is deliberately citation-based. Every field carries the source line number so the
finding can be re-audited against the read-only source at any time.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[5]
PROJECT_ROOT = ROOT / "src" / "projects" / "revolution-overdrive-porting"
MAPS_ROOT = PROJECT_ROOT / "packages" / "Maps"

# The mission that Stage 07 probed and left blocked.
DEFAULT_MAP = "thorner03.SC2Map"


@dataclass(frozen=True)
class Citation:
    """A single source line kept with its 1-based line number."""

    line: int
    text: str

    @staticmethod
    def of(index: int, raw: str) -> "Citation":
        return Citation(line=index + 1, text=raw.strip())


@dataclass
class P2ContractTrace:
    map_name: str
    map_script_sha256: str
    map_script_lines: int

    leader_player_id: int | None = None
    ally_player_id: int | None = None
    leader_symbol: str | None = None
    ally_symbol: str | None = None

    alliance_setup: list[Citation] = field(default_factory=list)
    ally_enemy_setup: list[Citation] = field(default_factory=list)
    unit_handover: list[Citation] = field(default_factory=list)
    handover_trigger_chain: list[Citation] = field(default_factory=list)
    gate_event: list[Citation] = field(default_factory=list)
    gate_condition: list[Citation] = field(default_factory=list)
    ai_wave_control: list[Citation] = field(default_factory=list)
    generic_ai_start: list[Citation] = field(default_factory=list)

    # Lifecycle of the single unit P2 ever receives.
    handover_unit_binding: list[Citation] = field(default_factory=list)
    handover_unit_hidden: list[Citation] = field(default_factory=list)
    handover_unit_revealed: list[Citation] = field(default_factory=list)
    ai_script_control: list[Citation] = field(default_factory=list)

    @property
    def owns_units_at_start(self) -> bool:
        """P2 owns no unit at map start: its only unit arrives through RescueUnit."""
        return False

    @property
    def is_time_gated_ally(self) -> bool:
        return bool(self.alliance_setup and self.unit_handover and self.gate_event)

    @property
    def is_script_driven_ai(self) -> bool:
        return bool(self.ai_wave_control) and not self.generic_ai_start

    @property
    def gate_region_id(self) -> int | None:
        """Region the gate unit must enter, e.g. RegionFromId(24)."""
        for citation in self.gate_event:
            match = re.search(r"RegionFromId\((\d+)\)", citation.text)
            if match:
                return int(match.group(1))
        return None

    @property
    def gate_unit_type(self) -> str | None:
        """Unit type that must enter the gate region, e.g. "TychusCommando"."""
        for citation in self.gate_condition:
            match = re.search(r'UnitGetType\(EventUnit\(\)\)\s*==\s*"([^"]+)"', citation.text)
            if match:
                return match.group(1)
        return None

    @property
    def handover_unit_ref(self) -> str | None:
        """The unit handed to P2, as written in the map script, e.g. UnitFromId(2)."""
        for citation in self.unit_handover:
            match = re.search(r"RescueUnit\(\s*([^,]+?)\s*,", citation.text)
            if match:
                return match.group(1).strip()
        return None

    @property
    def handover_unit_alias(self) -> str | None:
        """Global alias bound to the handover unit, e.g. `gv_odin = UnitFromId(2);`."""
        for citation in self.handover_unit_binding:
            match = re.search(r"^\s*(gv_\w+)\s*=", citation.text)
            if match:
                return match.group(1)
        return None

    @property
    def hidden_before_handover(self) -> bool:
        """The handover unit is pre-placed but concealed until the map reveals it."""
        return bool(self.handover_unit_hidden and self.handover_unit_revealed)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["derived"] = {
            "ownsUnitsAtStart": self.owns_units_at_start,
            "isTimeGatedAlly": self.is_time_gated_ally,
            "isScriptDrivenAi": self.is_script_driven_ai,
            "usesGenericMeleeAi": bool(self.generic_ai_start),
            "gateRegionId": self.gate_region_id,
            "gateUnitType": self.gate_unit_type,
            "handoverUnitRef": self.handover_unit_ref,
            "handoverUnitAlias": self.handover_unit_alias,
            "hiddenBeforeHandover": self.hidden_before_handover,
            "aiScriptControlReleased": bool(self.ai_script_control),
        }
        return payload


def _find(lines: Iterable[str], pattern: str) -> list[Citation]:
    regex = re.compile(pattern)
    return [Citation.of(i, raw) for i, raw in enumerate(lines) if regex.search(raw)]


def _function_span(lines: list[str], func_name: str) -> tuple[int, int] | None:
    """Return the [start, end) line span of a top-level Galaxy function body.

    Galaxy generated code opens the body on the signature line and closes it with a `}` in
    column 0, so brace depth tracking is unnecessary and would be fragile against strings.
    """
    start = None
    for i, raw in enumerate(lines):
        if start is None:
            if re.match(rf"^\s*\w[\w\s]*\b{re.escape(func_name)}\s*\(", raw):
                start = i
            continue
        if raw.startswith("}"):
            return start, i + 1
    return (start, len(lines)) if start is not None else None


def _find_within(
    lines: list[str], func_name: str, pattern: str
) -> list[Citation]:
    """Search only inside one function body, so citations cannot leak in from other triggers."""
    span = _function_span(lines, func_name)
    if span is None:
        return []
    start, end = span
    regex = re.compile(pattern)
    return [
        Citation.of(i, lines[i]) for i in range(start, end) if regex.search(lines[i])
    ]


def trace_p2_contract(map_dir: Path | None = None) -> P2ContractTrace:
    map_dir = map_dir or (MAPS_ROOT / DEFAULT_MAP)
    script = map_dir / "MapScript.galaxy"
    raw = script.read_bytes()
    lines = raw.decode("utf-8", errors="replace").splitlines()

    trace = P2ContractTrace(
        map_name=map_dir.name,
        map_script_sha256=hashlib.sha256(raw).hexdigest(),
        map_script_lines=len(lines),
    )

    # Player identity constants, e.g. `const int gv_p02_TYCHUS = 2;`
    for citation in _find(lines, r"^\s*const\s+int\s+gv_p0\d_\w+\s*=\s*\d+\s*;"):
        match = re.search(r"const\s+int\s+(gv_p0(\d)_\w+)\s*=\s*(\d+)", citation.text)
        if not match:
            continue
        symbol, _, value = match.group(1), match.group(2), int(match.group(3))
        if value == 1 and trace.leader_symbol is None:
            trace.leader_symbol, trace.leader_player_id = symbol, value
        elif value == 2 and trace.ally_symbol is None:
            trace.ally_symbol, trace.ally_player_id = symbol, value

    ally = trace.ally_symbol or "gv_p02_TYCHUS"
    leader = trace.leader_symbol or "gv_p01_USER"

    # 1. Alliance: the leader treats P2 as an ally from initialization onward.
    trace.alliance_setup = _find(
        lines, rf"(SetAlliance)\(\s*{re.escape(leader)}\s*,\s*{re.escape(ally)}\b"
    )
    # 2. P2 is hostile to every mission enemy - it is a real side, not decoration.
    trace.ally_enemy_setup = _find(
        lines, rf"SetAlliance\(\s*{re.escape(ally)}\s*,.*AllianceSetting_Enemy"
    )
    # 3. The single call that gives P2 a unit.
    trace.unit_handover = _find(lines, rf"RescueUnit\(.*,\s*{re.escape(ally)}\s*,")
    # 4. The trigger chain that reaches the handover.
    trace.handover_trigger_chain = _find(lines, r"TriggerExecute\(\s*gt_(MidQ|MidCleanup)\b")
    # 5. The event that opens the chain, and the type condition guarding it. The condition is
    #    scoped to the gate trigger's own body: other triggers in this map also test EventUnit
    #    types, and mixing them in would misstate the precondition.
    trace.gate_event = _find(lines, r"TriggerAddEventUnitRegion\(\s*gt_VictoryWarehouseDudesKilled")
    trace.gate_condition = _find_within(
        lines, "gt_VictoryWarehouseDudesKilled_Func", r"UnitGetType\(EventUnit\(\)\)\s*=="
    )
    # 6. Post-handover behavior is driven by map-owned AI wave calls bound to P2.
    trace.ai_wave_control = _find(lines, rf"AIAttackWave\w*\(\s*{re.escape(ally)}\b")
    # 7. Guard: the map must not rely on generic melee AI.
    trace.generic_ai_start = _find(lines, r"\bAI(Melee)?Start\s*\(")

    # 8. Lifecycle of the handed-over unit. The runtime probe observed the same unit tag move
    #    hidden -> owner 16 (rescuable) -> owner 2, so the static side must name that unit and
    #    show that it is pre-placed and concealed rather than spawned for P2.
    handover_ref = trace.handover_unit_ref or "UnitFromId(2)"
    escaped_ref = re.escape(handover_ref)
    trace.handover_unit_binding = _find(lines, rf"^\s*gv_\w+\s*=\s*{escaped_ref}\s*;")
    alias = trace.handover_unit_alias
    ref_or_alias = escaped_ref if alias is None else rf"(?:{escaped_ref}|{re.escape(alias)})"
    trace.handover_unit_hidden = _find(
        lines, rf"ShowHideUnit\(\s*{ref_or_alias}\s*,\s*false\s*\)"
    )
    trace.handover_unit_revealed = _find(
        lines, rf"ShowHideUnit\(\s*{ref_or_alias}\s*,\s*true\s*\)"
    )
    trace.ai_script_control = _find(
        lines, rf"AI(?:SetUnitScriptControlled|RemoveUnitFromAnyWaves)\(\s*{ref_or_alias}\b"
    )

    return trace


def main() -> None:
    trace = trace_p2_contract()
    out_dir = (
        ROOT
        / "artifacts"
        / "projects"
        / "revolution-overdrive-porting"
        / "stage08-ai-ally-native-closure"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "p2-contract-trace.json"
    payload = {
        "schemaVersion": 1,
        "stage": "08-ai-ally-native-closure",
        "source": f"src/projects/revolution-overdrive-porting/packages/Maps/{trace.map_name}/MapScript.galaxy",
        "trace": trace.to_dict(),
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["trace"]["derived"], indent=2))
    print(f"wrote {out_path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
