"""Vibe Kernel —— SimulatorSession。

持有运行时 WorldState + CatalogHandle，派发 §4.5 typed operation。
不提供任意 ``call FuncName``；仅白名单操作。

操作集（simulator-first §4.5）：
  system.ping
  scenario.load / reset / step / run / pause
  unit.spawn / kill / set_vital / order
  player.set_resource
  query.units / unit / player / mission
  snapshot.create / restore / compare
  assert.exists / not_exists / count / equals / range / eventually

幂等、参数校验、错误码由 ``SimulatorTransport``（包装 ``protocol.SessionRegistry``）处理；
本 session 只负责单个操作的状态副作用与查询。

证据分类：本模块是 ``static`` 代码；其行为正确性由 ``simulator_transport`` 的 P1 闸门运行时验证（``simulator``）保证。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .contracts import (
    CatalogHandle,
    Observation,
    ScenarioHandle,
    SnapshotHandle,
    TraceHandle,
    build_world,
    clone_world,
    run_scenario,
    wrap_catalog,
)
from .sim_path import ensure_simulator_on_path

ensure_simulator_on_path()

from sc2_simulator.catalog.model import CatalogSnapshot  # noqa: E402
from sc2_simulator.catalog.m7_units import m7_catalog  # noqa: E402
from sc2_simulator.fixed import Fixed, fixed_from  # noqa: E402
from sc2_simulator.scenario.model import ScenarioDefinition  # noqa: E402
from sc2_simulator.world.orders import Command, CommandKind  # noqa: E402

# 命令 kind 字符串 -> CommandKind
_CMD_KIND_MAP = {k.value: k for k in CommandKind}


class KernelError(Exception):
    """Kernel 操作错误。code 见 protocol.ErrorCode。"""

    def __init__(self, code: int, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"[{code}] {detail}")


@dataclass
class StepResult:
    """scenario.step 的返回。"""

    loop: int
    terminated: bool
    end_reason: str
    snapshot_hash: str


@dataclass
class AssertResult:
    ok: bool
    detail: str
    actual: Any = None
    expected: Any = None


class SimulatorSession:
    """单会话 Kernel。一个 session 对应一个运行中或待运行的场景实例。

    生命周期：
      scenario.load -> scenario.reset (建 world) -> scenario.step/run -> snapshot/assert
    """

    def __init__(self):
        self.catalog: Optional[CatalogHandle] = None
        self.scenario: Optional[ScenarioHandle] = None
        self.world = None  # WorldState
        self.result = None  # RunResult（run 到终局后）
        self.terminated: bool = False
        self.paused: bool = False
        self._snapshots: dict[str, SnapshotHandle] = {}
        self._initial_snapshot: Optional[SnapshotHandle] = (
            None  # scenario.reset 后的首个快照
        )
        # Stage 08: 波次时机数据（用于胜利时间计算 nights_survived）
        self._wave_timing: Optional[dict] = None

    # ----- system -----
    def ping(self) -> dict:
        return {
            "backend": "simulator",
            "catalog_loaded": self.catalog is not None,
            "world_loaded": self.world is not None,
            "loop": self.world.clock.now.loop if self.world else 0,
            "terminated": self.terminated,
        }

    # ----- scenario -----
    def scenario_load(
        self,
        scenario_path: Optional[str] = None,
        scenario_dict: Optional[dict] = None,
        catalog: Optional[str] = None,
    ) -> dict:
        if scenario_path:
            self.scenario = ScenarioHandle.from_file(scenario_path)
        elif scenario_dict:
            self.scenario = ScenarioHandle.from_dict(scenario_dict)
        else:
            raise KernelError(2, "scenario.load 需要 scenario_path 或 scenario_dict")
        # 选 catalog
        cat_snap = self._select_catalog(
            catalog or self.scenario.definition.schema_version
        )
        self.catalog = wrap_catalog(cat_snap, source="sc2_simulator")
        return {
            "scenario_name": self.scenario.definition.name,
            "schema_version": self.scenario.definition.schema_version,
            "catalog_hash": self.catalog.content_hash,
            "fidelity_summary": _fidelity_summary(self.catalog),
        }

    def set_wave_timing(self, wave_timing: dict) -> None:
        """设置波次时机数据（用于胜利时间计算 nights_survived）。

        通常在 scenario_load 后、scenario_reset 前调用。
        数据来源：map_extractor.extract_dead_of_night().wave_timing
        """
        self._wave_timing = wave_timing

    def _select_catalog(self, key: str) -> CatalogSnapshot:
        # 默认用 m7（超集）；显式 m2/m3 也支持
        if key.startswith("m2"):
            from sc2_simulator.catalog.m2_units import m2_catalog

            return m2_catalog()
        if key.startswith("m3"):
            from sc2_simulator.catalog.m3_units import m3_catalog

            return m3_catalog()
        return m7_catalog()

    def scenario_reset(self) -> dict:
        if self.scenario is None or self.catalog is None:
            raise KernelError(2, "scenario.reset 前需 scenario.load")
        self.world = build_world(self.scenario.definition, self.catalog.snapshot)
        self.world._win_condition = self.scenario.definition.win_condition  # noqa: SLF001
        self.result = None
        self.terminated = False
        self.paused = False
        self._snapshots.clear()
        self._initial_snapshot = SnapshotHandle.from_world(self.world)
        return {
            "loop": 0,
            "initial_snapshot_hash": self._initial_snapshot.hash,
            "entity_count": len(self.world.entities),
        }

    def scenario_step(self, loops: int = 1, snapshot: bool = True) -> StepResult:
        if self.world is None:
            raise KernelError(2, "scenario.step 前需 scenario.reset")
        if self.terminated:
            return StepResult(
                self.world.clock.now.loop,
                True,
                "already_terminated",
                SnapshotHandle.from_world(self.world).hash if snapshot else "",
            )
        if loops < 1:
            raise KernelError(2, f"loops 必须 >=1，得到 {loops}")
        from sc2_simulator.scenario.runner import (
            _dispatch_command,
            _convert_scenario_command,
            check_win_condition,
        )
        from sc2_simulator.systems import (
            movement,
            combat,
            projectile,
            economy,
            construction,
            production,
            upgrades,
            repair,
            morph,
            shields,
            vision,
            abilities,
        )

        scenario = self.scenario.definition
        commands_by_loop = {}
        for sc in scenario.commands:
            commands_by_loop.setdefault(sc.loop, []).append(sc)
        max_loop = min(self.world.clock.now.loop + loops, scenario.max_loops)
        end_reason = ""
        while self.world.clock.now.loop < max_loop:
            cur = self.world.clock.now.loop
            for sc in commands_by_loop.get(cur, []):
                _dispatch_command(self.world, _convert_scenario_command(sc, self.world))
            movement.step(self.world)
            combat.step(self.world)
            projectile.step(self.world)
            economy.step(self.world)
            construction.step(self.world)
            production.step(self.world)
            upgrades.step(self.world)
            repair.step(self.world)
            morph.step(self.world)
            shields.step(self.world)
            vision.step(self.world)
            abilities.step(self.world)
            economy.recompute_supply(self.world)
            self.world.events.pop_due(cur)
            dead = self.world.remove_dead()
            for d in dead:
                self.world.events.schedule(
                    loop=cur,
                    system="system",
                    kind="entity_removed",
                    entity_id=d.entity_id,
                    payload={"unit_type": d.unit_type_id},
                )
            self.world.events.pop_due(cur)
            winner, end_reason = check_win_condition(self.world)
            if winner is not None or end_reason:
                self.terminated = True
                self.end_reason = end_reason
                break
            self.world.clock.tick()
        snap_hash = SnapshotHandle.from_world(self.world).hash if snapshot else ""
        return StepResult(
            self.world.clock.now.loop, self.terminated, end_reason, snap_hash
        )

    def scenario_step_movement_only(self) -> StepResult:
        """Advance a static-map replay through the real movement system.

        Map-derived replay frames can contain more than a thousand native
        structures and resource nodes but no P1/P2 units. Running the complete
        combat/economy/vision stack for every idle native entity makes a long
        map-script timeline impractical. This bounded path still applies the
        simulator's actual movement implementation to dynamic overlay units,
        then advances the game clock; it is not a replacement for full mission
        simulation.
        """
        if self.world is None:
            raise KernelError(2, "scenario.step_movement_only 前需 scenario.reset")
        from sc2_simulator.systems import movement

        movement.step(self.world)
        self.world.events.pop_due(self.world.clock.now.loop)
        self.world.clock.tick()
        return StepResult(
            self.world.clock.now.loop,
            self.terminated,
            "",
            "",
        )

    def scenario_run(self, max_loops: Optional[int] = None) -> dict:
        """运行到终局。重置后从头跑（保留当前 world 也可，但 P1 约定 run = reset+到终局）。"""
        if self.world is None:
            raise KernelError(2, "scenario.run 前需 scenario.reset")
        if self.terminated:
            return {
                "loop": self.world.clock.now.loop,
                "terminated": True,
                "end_reason": getattr(self, "end_reason", ""),
            }
        # 复用 run_scenario 的完整循环（含 coverage 标记），但 world 已存在 -> 用 step 推进
        scenario = self.scenario.definition
        budget = max_loops if max_loops is not None else scenario.max_loops
        remaining = budget - self.world.clock.now.loop
        sr = self.scenario_step(remaining)
        self.result = _build_run_result(
            self.world, sr.loop, sr.end_reason or "max_loops_reached"
        )
        return {
            "loop": sr.loop,
            "terminated": sr.terminated or True,
            "end_reason": sr.end_reason or "max_loops_reached",
            "trace_hash": TraceHandle.from_world(self.world).hash,
            "winner": _extract_winner(self.world, sr.end_reason),
        }

    def scenario_pause(self) -> dict:
        self.paused = True
        return {"paused": True, "loop": self.world.clock.now.loop if self.world else 0}

    # ----- unit -----
    def unit_spawn(
        self, unit_type_id: str, owner_player_id: int, x: float, y: float
    ) -> dict:
        if self.world is None:
            raise KernelError(2, "unit.spawn 前需 scenario.reset")
        e = self.world.create_entity(
            unit_type_id, owner_player_id, fixed_from(x), fixed_from(y)
        )
        return {
            "entity_id": e.entity_id,
            "unit_type_id": unit_type_id,
            "owner": owner_player_id,
        }

    def unit_add_behavior(self, entity_id: int, behavior_id: str, stacks: int) -> dict:
        if self.world is None:
            raise KernelError(2, "unit.add_behavior 前需 scenario.reset")
        entity = self.world.get_entity(entity_id)
        if entity is None or not entity.is_alive:
            raise KernelError(2, "unit_not_found_or_stale")
        behavior = self.world.catalog.get_behavior(behavior_id)
        if behavior is None:
            raise KernelError(2, f"behavior_not_found: {behavior_id}")
        existing = next(
            (item for item in entity.active_behaviors if item.get("id") == behavior_id),
            None,
        )
        if existing is None:
            existing = {
                "id": behavior.id,
                "kind": behavior.kind.value,
                "remaining": behavior.duration,
                "speed_multiplier": behavior.speed_multiplier,
                "attack_speed_multiplier": behavior.attack_speed_multiplier,
                "armor_add": behavior.armor_add,
                "damage_add": behavior.damage_add,
                "damage_per_tick": behavior.damage_per_tick,
                "tick_interval": behavior.tick_interval,
                "last_tick": 0,
                "source_entity_id": entity_id,
                "stacks": stacks,
            }
            entity.active_behaviors.append(existing)
        else:
            existing["stacks"] = int(existing.get("stacks", 1)) + stacks
            existing["remaining"] = behavior.duration
        self.world.events.schedule(
            loop=self.world.clock.now.loop,
            system="abilities",
            kind="behavior_applied",
            entity_id=entity_id,
            payload={"behavior": behavior_id, "stacks": existing["stacks"]},
        )
        return {
            "unit_tag": entity_id,
            "behavior": behavior_id,
            "stacks": existing["stacks"],
            "count": existing["stacks"],
        }

    def query_behavior(self, entity_id: int, behavior_id: str) -> dict:
        if self.world is None:
            raise KernelError(2, "unit.query_behavior 前需 scenario.reset")
        entity = self.world.get_entity(entity_id)
        if entity is None:
            raise KernelError(2, "unit_not_found_or_stale")
        if self.world.catalog.get_behavior(behavior_id) is None:
            raise KernelError(2, f"behavior_not_found: {behavior_id}")
        count = sum(
            int(item.get("stacks", 1))
            for item in entity.active_behaviors
            if item.get("id") == behavior_id
        )
        return {
            "unit_tag": entity_id,
            "behavior": behavior_id,
            "count": count,
            "has_behavior": count > 0,
        }

    def unit_kill(self, entity_id: int) -> dict:
        if self.world is None:
            raise KernelError(2, "unit.kill 前需 scenario.reset")
        e = self.world.get_entity(entity_id)
        if e is None:
            raise KernelError(2, f"单位 {entity_id} 不存在")
        e.health = Fixed.from_int(0)
        e.state = (
            e.state.__class__("dead") if hasattr(e.state, "__class__") else e.state
        )
        from sc2_simulator.world.entity import UnitState

        e.state = UnitState.DEAD
        return {"entity_id": entity_id, "killed": True}

    def unit_set_vital(
        self,
        entity_id: int,
        health: Optional[float] = None,
        shields: Optional[float] = None,
        energy: Optional[float] = None,
    ) -> dict:
        if self.world is None:
            raise KernelError(2, "unit.set_vital 前需 scenario.reset")
        e = self.world.get_entity(entity_id)
        if e is None:
            raise KernelError(2, f"单位 {entity_id} 不存在")
        if health is not None:
            e.health = fixed_from(health)
        if shields is not None:
            e.shields = fixed_from(shields)
        if energy is not None:
            e.energy = fixed_from(energy)
        return {
            "entity_id": entity_id,
            "health": e.health.raw,
            "shields": e.shields.raw,
            "energy": e.energy.raw,
        }

    def unit_order(
        self,
        entity_ids: list[int],
        kind: str,
        issuer_player_id: int,
        target_entity_id: int = 0,
        target_x: float = 0.0,
        target_y: float = 0.0,
        unit_type_id: str = "",
        ability_id: str = "",
    ) -> dict:
        if self.world is None:
            raise KernelError(2, "unit.order 前需 scenario.reset")
        if kind not in _CMD_KIND_MAP:
            raise KernelError(1, f"未知命令 kind: {kind}")
        from sc2_simulator.scenario.runner import _dispatch_command

        effective_target_entity_id = target_entity_id
        # The project policy uses native SC2 semantics for gas gathering:
        # workers right-click the completed Refinery.  The read-only M2
        # simulator still models the resource source as VespeneGeyser.  Keep
        # the public command native and resolve only at this transport
        # boundary, preserving the real resource state machine.
        if kind == "smart" and target_entity_id:
            target = self.world.get_entity(target_entity_id)
            if target is not None and target.unit_type_id == "Refinery":
                geysers = [
                    entity for entity in self.world.entities.values()
                    if entity.is_alive
                    and entity.unit_type_id == "VespeneGeyser"
                ]
                if geysers:
                    effective_target_entity_id = min(
                        geysers,
                        key=lambda entity: (
                            (entity.x.raw - target.x.raw) ** 2
                            + (entity.y.raw - target.y.raw) ** 2,
                            entity.entity_id,
                        ),
                    ).entity_id

        # The reference runner's SMART fallback has a local-import bug when
        # no target entity is supplied.  Native point-smart semantics are a
        # move in that case, so normalize at this owned transport boundary.
        dispatch_kind = (
            "move" if kind == "smart" and not effective_target_entity_id else kind
        )
        cmd = Command(
            kind=_CMD_KIND_MAP[dispatch_kind],
            issuer_player_id=issuer_player_id,
            entity_ids=tuple(entity_ids),
            target_entity_id=effective_target_entity_id,
            target_x=fixed_from(target_x),
            target_y=fixed_from(target_y),
            unit_type_id=unit_type_id,
            ability_id=ability_id,
            issued_loop=self.world.clock.now.loop,
        )
        original_validate_placement = None
        if kind == "build" and unit_type_id == "Refinery":
            # The reference M2 placement guard reserves all neutral resource
            # cells for ordinary structures.  A Refinery is the intentional
            # exception: it occupies the geyser footprint.  Keep the shared
            # terrain/structure checks, but omit only the resource reservation
            # check for this one native building type.
            original_validate_placement = self.world.validate_structure_placement

            def validate_refinery_placement(
                product_id,
                x,
                y,
                *,
                exclude_entity_id=0,
            ):
                if product_id != "Refinery" or self.world.terrain is None:
                    return original_validate_placement(
                        product_id,
                        x,
                        y,
                        exclude_entity_id=exclude_entity_id,
                    )
                unit_type = self.world.catalog.get(product_id)
                if self.world.terrain_is_explicit:
                    valid, reason, cells = self.world.terrain.can_place_footprint(
                        x,
                        y,
                        unit_type.footprint_width,
                        unit_type.footprint_height,
                    )
                    if not valid:
                        return False, reason
                else:
                    cells = self.world.terrain.footprint_cells(
                        x,
                        y,
                        unit_type.footprint_width,
                        unit_type.footprint_height,
                    )
                if any(
                    cell in self.world.occupied_structure_cells(exclude_entity_id)
                    for cell in cells
                ):
                    return False, "occupied"
                return True, ""

            self.world.validate_structure_placement = validate_refinery_placement
        try:
            _dispatch_command(self.world, cmd)
        finally:
            if original_validate_placement is not None:
                del self.world.validate_structure_placement
        return {
            "issued": True,
            "kind": kind,
            "entity_ids": entity_ids,
            "loop": self.world.clock.now.loop,
        }

    # ----- player -----
    def player_set_resource(
        self,
        player_id: int,
        minerals: Optional[int] = None,
        vespene: Optional[int] = None,
    ) -> dict:
        if self.world is None:
            raise KernelError(2, "player.set_resource 前需 scenario.reset")
        res = self.world.get_resources(player_id)
        if minerals is not None:
            res.minerals = minerals
        if vespene is not None:
            res.vespene = vespene
        return res.snapshot()

    # ----- query -----
    def query_units(self, owner_player_id: Optional[int] = None) -> dict:
        if self.world is None:
            raise KernelError(2, "query.units 前需 scenario.reset")
        es = (
            self.world.entities_of(owner_player_id)
            if owner_player_id is not None
            else list(self.world.entities.values())
        )
        return {"units": [_entity_brief(e) for e in es], "count": len(es)}

    def query_structures(
        self, owner_player_id: int = 0, unit_type_id: str = ""
    ) -> dict:
        """Return a read-only census of live player-owned structures."""
        if self.world is None:
            raise KernelError(2, "query.structures 前需 scenario.reset")
        if owner_player_id < 0 or owner_player_id > 15:
            raise KernelError(2, f"owner_player_id 超出范围: {owner_player_id}")
        structures = []
        for entity in sorted(self.world.entities.values(), key=lambda item: item.entity_id):
            if not entity.is_alive or entity.owner_player_id <= 0:
                continue
            if owner_player_id and entity.owner_player_id != owner_player_id:
                continue
            unit_type = self.world.catalog.get(entity.unit_type_id)
            if not unit_type.is_structure or getattr(unit_type, "race", "") == "neutral":
                continue
            if unit_type_id and entity.unit_type_id != unit_type_id:
                continue
            structures.append({
                "owner": entity.owner_player_id,
                "unit_type": entity.unit_type_id,
                "unit_tag": entity.entity_id,
            })
        return {
            "owner_player": owner_player_id,
            "unit_type": unit_type_id,
            "live_count": len(structures),
            "structures": structures,
        }

    def query_unit(self, entity_id: int) -> dict:
        if self.world is None:
            raise KernelError(2, "query.unit 前需 scenario.reset")
        e = self.world.get_entity(entity_id)
        if e is None:
            raise KernelError(2, f"单位 {entity_id} 不存在")
        return _entity_brief(e)

    def query_player(self, player_id: int) -> dict:
        if self.world is None:
            raise KernelError(2, "query.player 前需 scenario.reset")
        return {
            "resources": self.world.get_resources(player_id).snapshot(),
            "units": len(self.world.entities_of(player_id)),
        }

    def query_mission(self) -> dict:
        if self.world is None:
            raise KernelError(2, "query.mission 前需 scenario.reset")
        return {
            "loop": self.world.clock.now.loop,
            "terminated": self.terminated,
            "end_reason": getattr(self, "end_reason", ""),
            "win_condition": getattr(self.world, "_win_condition", "annihilation"),  # noqa: SLF001
        }

    # ----- snapshot -----
    def snapshot_create(self, name: str) -> dict:
        if self.world is None:
            raise KernelError(2, "snapshot.create 前需 scenario.reset")
        h = SnapshotHandle.from_world(self.world)
        self._snapshots[name] = h
        return {"name": name, "hash": h.hash, "loop": h.loop}

    def snapshot_restore(self, name: str) -> dict:
        if self.world is None:
            raise KernelError(2, "snapshot.restore 前需 scenario.reset")
        h = self._snapshots.get(name)
        if h is None:
            raise KernelError(2, f"快照 {name} 不存在")
        self.world.restore_into(h.data)
        self.terminated = False
        return {"name": name, "restored_hash": h.hash, "loop": h.loop}

    def snapshot_compare(self, name_a: str, name_b: str) -> dict:
        a = self._snapshots.get(name_a)
        b = self._snapshots.get(name_b)
        if a is None or b is None:
            raise KernelError(2, f"快照 {name_a}/{name_b} 不存在")
        return {"hash_a": a.hash, "hash_b": b.hash, "equal": a.hash == b.hash}

    # ----- assert -----
    def assert_exists(self, entity_id: int) -> AssertResult:
        if self.world is None:
            return AssertResult(False, "world 未加载")
        e = self.world.get_entity(entity_id)
        ok = e is not None and e.is_alive
        return AssertResult(
            ok, f"entity {entity_id} exists={ok}", actual=ok, expected=True
        )

    def assert_not_exists(self, entity_id: int) -> AssertResult:
        if self.world is None:
            return AssertResult(False, "world 未加载")
        e = self.world.get_entity(entity_id)
        ok = e is None or not e.is_alive
        return AssertResult(
            ok, f"entity {entity_id} not_exists={ok}", actual=ok, expected=True
        )

    def assert_count(
        self,
        owner_player_id: Optional[int],
        expected: int,
        unit_type_id: Optional[str] = None,
    ) -> AssertResult:
        if self.world is None:
            return AssertResult(False, "world 未加载")
        es = (
            self.world.entities_of(owner_player_id)
            if owner_player_id is not None
            else list(self.world.entities.values())
        )
        if unit_type_id:
            es = [e for e in es if e.unit_type_id == unit_type_id]
        actual = len(es)
        return AssertResult(
            actual == expected,
            f"count={actual} expected={expected}",
            actual=actual,
            expected=expected,
        )

    def assert_equals(
        self, entity_id: int, field: str, expected: float
    ) -> AssertResult:
        if self.world is None:
            return AssertResult(False, "world 未加载")
        e = self.world.get_entity(entity_id)
        if e is None:
            return AssertResult(False, f"单位 {entity_id} 不存在")
        val = _get_field(e, field)
        if val is None:
            return AssertResult(False, f"未知字段 {field}")
        ok = abs(val - expected) < 1e-6
        return AssertResult(
            ok, f"{field}={val} expected={expected}", actual=val, expected=expected
        )

    def assert_range(
        self, entity_id: int, field: str, low: float, high: float
    ) -> AssertResult:
        if self.world is None:
            return AssertResult(False, "world 未加载")
        e = self.world.get_entity(entity_id)
        if e is None:
            return AssertResult(False, f"单位 {entity_id} 不存在")
        val = _get_field(e, field)
        if val is None:
            return AssertResult(False, f"未知字段 {field}")
        ok = low <= val <= high
        return AssertResult(
            ok, f"{field}={val} range=[{low},{high}]", actual=val, expected=[low, high]
        )

    def assert_eventually(
        self, check_fn_name: str, max_loops: int = 1000, **kwargs
    ) -> AssertResult:
        """简单实现：向前推进直到条件成立或达到 max_loops。check_fn_name 限定为 exists/not_exists/count。"""
        if self.world is None:
            return AssertResult(False, "world 未加载")
        if check_fn_name not in ("exists", "not_exists", "count"):
            return AssertResult(
                False,
                f"eventually 仅支持 exists/not_exists/count，得到 {check_fn_name}",
            )
        for _ in range(max_loops):
            if self.terminated:
                break
            if check_fn_name == "exists":
                r = self.assert_exists(kwargs["entity_id"])
            elif check_fn_name == "not_exists":
                r = self.assert_not_exists(kwargs["entity_id"])
            else:
                r = self.assert_count(
                    kwargs.get("owner_player_id"),
                    kwargs["expected"],
                    kwargs.get("unit_type_id"),
                )
            if r.ok:
                return AssertResult(
                    True,
                    f"eventually {check_fn_name} ok @ loop {self.world.clock.now.loop}",
                )
            self.scenario_step(1, snapshot=False)
        return AssertResult(
            False, f"eventually {check_fn_name} 未在 {max_loops} loop 内成立"
        )


def _entity_brief(e) -> dict:
    # 位置返回世界单位 float（与 contracts._entity_brief 对齐）；
    # health/shields/energy 保留 raw int（P4A 断言 marine_hp=46080=45*1024）。
    return {
        "entity_id": e.entity_id,
        "unit_type_id": e.unit_type_id,
        "owner": e.owner_player_id,
        "x": e.x.to_float(),
        "y": e.y.to_float(),
        "health": e.health.raw,
        "shields": e.shields.raw,
        "energy": e.energy.raw,
        "state": e.state.value if hasattr(e.state, "value") else str(e.state),
    }


def _get_field(e, field: str) -> Optional[float]:
    m = {
        "health": e.health.raw,
        "shields": e.shields.raw,
        "energy": e.energy.raw,
        "x": e.x.to_float(),
        "y": e.y.to_float(),
    }
    return m.get(field)


def _fidelity_summary(cat: CatalogHandle) -> dict:
    from collections import Counter

    c = Counter(cat.fidelity.values())
    return dict(c)


def _build_run_result(world, end_loop, end_reason):
    from sc2_simulator.scenario.runner import RunResult

    survivors = {}
    for e in world.entities.values():
        if e.is_alive:
            survivors.setdefault(e.owner_player_id, []).append(
                {
                    "entity_id": e.entity_id,
                    "unit_type_id": e.unit_type_id,
                    "health": e.health.raw,
                }
            )
    summary = {"end_loop": end_loop, "total_events": len(world.events.emitted)}
    return RunResult(
        winner_player_id=None,
        end_loop=end_loop,
        end_reason=end_reason,
        survivors=survivors,
        summary=summary,
        coverage={},
    )


def _extract_winner(world, end_reason) -> Optional[int]:
    if end_reason != "annihilation":
        return None
    alive = {e.owner_player_id for e in world.entities.values() if e.is_alive}
    if len(alive) == 1:
        return next(iter(alive))
    return None


__all__ = ["SimulatorSession", "KernelError", "StepResult", "AssertResult"]
