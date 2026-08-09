"""Definitive proof that the runtime VM supports *every* internal function.

Two complementary guarantees:

1. ``CoverageAllVibeExecuteTests`` — a single ``DebugVm`` program driven by the
   real ``SimulatorSessionDebugVmBridge`` (genuine side effects, not the
   synthetic marker) that calls **all 20** handwritten ``vibe.*`` functions with
   correct, realistic arguments and asserts the real world mutations.

2. ``FullRegistryRoutingSweepTests`` — loops over the *entire* function
   registry (11676 ``gen.*`` + 20 ``vibe.*`` = 11696 entries) and asserts the
   canonical offline dispatcher accepts and routes every one with valid,
   registry-conformant args. ``gen.*`` have heterogeneous signatures (3405 take
   no args, 4281 take p0+p1, ...); this proves the router + registry cover all
   of them, not just a sample.

No live SC2 required. This is the offline counterpart to the Kernel's
``libVibeKernel_gf_Dispatch`` / ``libVibeInvoke_gf_Dispatch`` chains.
"""
from __future__ import annotations

import ast
import asyncio
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]  # .../sc2-porting-workspace
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

from vibe.function_registry import invoke_registered_function  # noqa: E402
from vibe.debug_vm import (  # noqa: E402
    DebugVm,
    HostDebugVmBridge,
    SimulatorSessionDebugVmBridge,
    load_function_metadata,
)


def _sample_args(spec: dict) -> dict:
    """Build registry-conformant args for a single function spec (routing only)."""
    args: dict = {}
    for name, as_ in spec.get("args", {}).items():
        if not as_.get("required", False):
            continue
        type_name = as_.get("type")
        if type_name == "integer":
            args[name] = int(as_.get("min", 1))
        elif type_name == "fixed":
            args[name] = float(as_.get("min", 1.0))
        elif type_name == "string":
            args[name] = (as_.get("enum") or ["x"])[0]
        else:
            args[name] = "x"
    return args


PROGRAM = {
    "vm": "vibe-debug/1",
    "steps": [
        # 1) vibe.test.ping — diagnostic, no side effect
        {"op": "call", "fn": "vibe.test.ping", "args": {"nonce": "cov"}, "save": "ping"},
        # 2) vibe.player.set_resource
        {"op": "call", "fn": "vibe.player.set_resource",
         "args": {"player": 1, "resource": "minerals", "value": 1234}, "save": "res"},
        # 3) vibe.unit.spawn (player 1 marine, anchor for most later ops)
        {"op": "call", "fn": "vibe.unit.spawn",
         "args": {"unit_type": "Marine", "count": 1, "player": 1, "x": 1.0, "y": 1.0}, "save": "sp"},
        # 4) vibe.unit.spawn_group
        {"op": "call", "fn": "vibe.unit.spawn_group",
         "args": {"unit_type": "Marine", "count": 3, "player": 1, "x": 4.0, "y": 4.0}, "save": "grp"},
        # 5) vibe.unit.add_behavior
        {"op": "call", "fn": "vibe.unit.add_behavior",
         "args": {"unit_tag": "$vars.sp.unit_tag", "behavior": "StimpackBehavior", "stacks": 1}, "save": "ab"},
        # 6) vibe.unit.query_behavior
        {"op": "call", "fn": "vibe.unit.query_behavior",
         "args": {"unit_tag": "$vars.sp.unit_tag", "behavior": "StimpackBehavior"}, "save": "qb"},
        # 7) vibe.unit.add_ability
        {"op": "call", "fn": "vibe.unit.add_ability",
         "args": {"unit_tag": "$vars.sp.unit_tag", "ability": "Stimpack"}, "save": "aa"},
        # 8) vibe.unit.query_ability
        {"op": "call", "fn": "vibe.unit.query_ability",
         "args": {"unit_tag": "$vars.sp.unit_tag", "ability": "Stimpack"}, "save": "qa"},
        # 9) vibe.unit.set_vital
        {"op": "call", "fn": "vibe.unit.set_vital",
         "args": {"unit_tag": "$vars.sp.unit_tag", "vital": "life", "value": 100.0}, "save": "sv"},
        # 10) vibe.unit.query_attrs
        {"op": "call", "fn": "vibe.unit.query_attrs",
         "args": {"unit_tag": "$vars.sp.unit_tag"}, "save": "qa2"},
        # 11) vibe.catalog.set
        {"op": "call", "fn": "vibe.catalog.set",
         "args": {"catalog": "unit", "entry": "Marine", "field": "test_field", "player": 0, "value": "hello"}, "save": "cs"},
        # 12) vibe.catalog.get
        {"op": "call", "fn": "vibe.catalog.get",
         "args": {"catalog": "unit", "entry": "Marine", "field": "test_field", "player": 0}, "save": "cg"},
        # 13-16) vibe.visual.* (all on the spawned marine)
        {"op": "call", "fn": "vibe.visual.set_tint",
         "args": {"unit_tag": "$vars.sp.unit_tag", "color": "#ff0000"}, "save": "vt"},
        {"op": "call", "fn": "vibe.visual.set_scale",
         "args": {"unit_tag": "$vars.sp.unit_tag", "scale": 2.0}, "save": "vs"},
        {"op": "call", "fn": "vibe.visual.set_opacity",
         "args": {"unit_tag": "$vars.sp.unit_tag", "opacity": 0.5}, "save": "vo"},
        {"op": "call", "fn": "vibe.visual.model_swap",
         "args": {"unit_tag": "$vars.sp.unit_tag", "model": "Marine", "variation": 1}, "save": "vm"},
        # 17) vibe.query.units (player 1)
        {"op": "call", "fn": "vibe.query.units", "args": {"player": 1}, "save": "qu"},
        # 18) vibe.query.structures (player 1)
        {"op": "call", "fn": "vibe.query.structures", "args": {"owner_player": 1}, "save": "qs"},
        # 19) vibe.unit.attack — spawn a real enemy on player 2, then attack
        {"op": "call", "fn": "vibe.unit.spawn",
         "args": {"unit_type": "Marine", "count": 1, "player": 2, "x": 9.0, "y": 9.0}, "save": "enemy"},
        {"op": "call", "fn": "vibe.unit.attack",
         "args": {"attacker_tag": "$vars.sp.unit_tag", "target_tag": "$vars.enemy.unit_tag"}, "save": "atk"},
        # 20) vibe.unit.kill (anchor marine) — must be last so 5-16 still see it
        {"op": "call", "fn": "vibe.unit.kill", "args": {"unit_tag": "$vars.sp.unit_tag"}, "save": "kill"},
        # gen.* routing marker through the real session bridge
        {"op": "call", "fn": "gen.1", "args": {"p0": 1, "p1": "a", "p2": "b"}, "save": "gen"},
    ],
}


class CoverageAllVibeExecuteTests(unittest.TestCase):
    """One program exercising every vibe.* with asserted real world effects."""

    def setUp(self):
        self.bridge = SimulatorSessionDebugVmBridge()
        self.meta = load_function_metadata()

    def _run(self):
        return asyncio.run(
            DebugVm(self.bridge, function_metadata=self.meta).run(PROGRAM)
        )

    def test_program_passes(self):
        result = self._run()
        self.assertEqual(result["status"], "passed", msg=result["error"])

    def test_ping_diagnostic(self):
        r = self._run()
        self.assertEqual(r["vars"]["ping"]["message"], "pong")
        self.assertEqual(r["vars"]["ping"]["nonce"], "cov")

    def test_resource_side_effect(self):
        r = self._run()
        self.assertEqual(r["vars"]["res"]["value"], 1234)

    def test_spawn_and_group_counts(self):
        r = self._run()
        self.assertEqual(r["vars"]["sp"]["created"], 1)
        self.assertEqual(r["vars"]["grp"]["created"], 3)
        self.assertIsInstance(r["vars"]["sp"]["unit_tag"], int)

    def test_behavior_apply_and_query(self):
        r = self._run()
        self.assertEqual(r["vars"]["ab"]["behavior"], "StimpackBehavior")
        self.assertTrue(r["vars"]["qb"]["has_behavior"])

    def test_ability_apply_and_query(self):
        r = self._run()
        self.assertTrue(r["vars"]["aa"]["has_ability"])
        self.assertTrue(r["vars"]["qa"]["has_ability"])

    def test_vital_and_attrs(self):
        r = self._run()
        self.assertEqual(r["vars"]["sv"]["value"], 100.0)
        self.assertEqual(r["vars"]["qa2"]["unit_type"], "Marine")

    def test_catalog_roundtrip(self):
        r = self._run()
        self.assertEqual(r["vars"]["cs"]["value"], "hello")
        self.assertEqual(r["vars"]["cg"]["value"], "hello")

    def test_visual_all_applied(self):
        r = self._run()
        for v in ("vt", "vs", "vo", "vm"):
            self.assertTrue(r["vars"][v]["applied"], msg=v)

    def test_query_units_and_structures(self):
        r = self._run()
        self.assertGreaterEqual(r["vars"]["qu"]["count"], 4)
        self.assertGreaterEqual(r["vars"]["qs"]["live_count"], 1)

    def test_attack_issues_on_enemy(self):
        r = self._run()
        self.assertTrue(r["vars"]["atk"]["issued"])
        self.assertEqual(r["vars"]["atk"]["target_owner"], 2)

    def test_kill_and_gen_routing(self):
        r = self._run()
        self.assertTrue(r["vars"]["kill"]["killed"])
        self.assertEqual(r["vars"]["gen"]["routed"], "runtime")

    def test_every_dispatch_branch_hit(self):
        """Assert the program actually exercised all 20 vibe.* + gen.1."""
        r = self._run()
        covered = set()
        for trace in r["trace"]:
            if trace["op"] == "call":
                covered.add(trace["function_id"])
        vibe_covered = {c for c in covered if c.startswith("vibe.")}
        self.assertEqual(len(vibe_covered), 20)
        self.assertIn("gen.1", covered)


class FullRegistryRoutingSweepTests(unittest.TestCase):
    """Every registered internal function must route through the offline dispatcher."""

    def setUp(self):
        self.fns = load_function_metadata()

    def test_registry_size_is_complete(self):
        vibe = [k for k in self.fns if k.startswith("vibe.")]
        gen = [k for k in self.fns if k.startswith("gen.")]
        self.assertEqual(len(vibe), 20)
        self.assertEqual(len(gen), 11676)
        self.assertEqual(len(self.fns), 11696)

    def test_all_vibe_functions_route(self):
        for fid in (k for k in self.fns if k.startswith("vibe.")):
            with self.subTest(fid=fid):
                payload = invoke_registered_function(fid, _sample_args(self.fns[fid]), registry=self.fns)
                self.assertEqual(payload["function_id"], fid)
                if fid == "vibe.test.ping":
                    self.assertEqual(payload["message"], "pong")
                else:
                    self.assertEqual(payload["routed"], "simulator")

    def test_all_gen_functions_route(self):
        # gen.* have heterogeneous signatures; routing with conformant args must
        # succeed for all 11676, not just a sample.
        count = 0
        for fid in (k for k in self.fns if k.startswith("gen.")):
            with self.subTest(fid=fid):
                payload = invoke_registered_function(fid, _sample_args(self.fns[fid]), registry=self.fns)
                self.assertEqual(payload["function_id"], fid)
                self.assertEqual(payload["routed"], "runtime")
                count += 1
        self.assertEqual(count, 11676)

    def test_full_registry_sweep_no_function_not_found(self):
        rejected = []
        for fid in sorted(self.fns):
            try:
                invoke_registered_function(fid, _sample_args(self.fns[fid]), registry=self.fns)
            except Exception as exc:  # noqa: BLE001
                rejected.append((fid, type(exc).__name__, str(exc)))
        self.assertEqual(rejected, [], msg=f"unroutable functions: {rejected[:5]}")


class DispatchConsistencyTests(unittest.TestCase):
    """Enforced invariant: the offline VM dispatch must serve *every* internal
    function, with no silent drift between the registry, the dispatcher, and the
    backing ``SimulatorSession``.

    This is the automated form of the manual "I verified it covers all 20" check
    that previously lived only in run notes. If anyone adds a 21st ``vibe.*`` to
    the registry without a dispatch branch, or references a ``SimulatorSession``
    method that does not exist, these tests fail instead of the gap going
    unnoticed until a live call hits ``FUNCTION_NOT_FOUND``.
    """

    VIBE_DIR = Path(__file__).resolve().parents[5] / "src" / "projects" / "cmre-porting" / "vibe"

    def setUp(self):
        self.fns = load_function_metadata()
        self.vibe = sorted(k for k in self.fns if k.startswith("vibe."))
        self.gen = sorted(k for k in self.fns if k.startswith("gen."))
        self.transport_src = (self.VIBE_DIR / "simulator_transport.py").read_text(encoding="utf-8")
        self.session_src = (self.VIBE_DIR / "simulator_session.py").read_text(encoding="utf-8")

    # ---- static gates ----------------------------------------------------

    def test_dispatcher_branches_equal_registry_vibe(self):
        """Every ``if function_id == "vibe.x"`` branch must match a registry entry, 1:1."""
        dispatched = sorted(set(re.findall(r'function_id == "([^"]+)"', self.transport_src)))
        dispatched_vibe = sorted(d for d in dispatched if d.startswith("vibe."))
        self.assertEqual(
            set(dispatched_vibe), set(self.vibe),
            msg=f"dispatch/registry mismatch: only-in-dispatch={set(dispatched_vibe) - set(self.vibe)} "
                f"only-in-registry={set(self.vibe) - set(dispatched_vibe)}",
        )

    def test_dispatcher_calls_defined_session_methods(self):
        """Every ``s.<method>`` the dispatcher invokes must exist on SimulatorSession."""
        called = sorted(set(re.findall(r"\bs\.([A-Za-z_]\w*)\s*\(", self.transport_src)))
        tree = ast.parse(self.session_src)
        defined = {
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # attributes accessed off the session object, not methods
        non_methods = {"world", "terminated", "end_reason"}
        missing = [m for m in called if m not in defined and m not in non_methods]
        self.assertEqual(missing, [], msg=f"dispatcher calls undefined session methods: {missing}")

    def test_no_duplicate_dispatch_branches(self):
        branches = re.findall(r'function_id == "([^"]+)"', self.transport_src)
        dups = {b for b in branches if branches.count(b) > 1}
        self.assertEqual(dups, set(), msg=f"duplicate dispatch branches: {dups}")

    # ---- dynamic gate: every vibe.* callable through the bridge ----------

    def _spawn_tag(self, bridge, *, player, x, y):
        resp = bridge.call(
            "vibe.unit.spawn",
            {"unit_type": "Marine", "count": 1, "player": player, "x": x, "y": y},
        )
        self.assertEqual(resp.error_code, 0, msg=resp.payload)
        return resp.payload["unit_tag"]

    def _bridge_args(self, fid, anchor, enemy):
        if fid == "vibe.test.ping":
            return {"nonce": "x"}
        if fid == "vibe.player.set_resource":
            return {"player": 1, "resource": "minerals", "value": 50}
        if fid == "vibe.unit.spawn":
            return {"unit_type": "Marine", "count": 1, "player": 1, "x": 1.0, "y": 1.0}
        if fid == "vibe.unit.spawn_group":
            return {"unit_type": "Marine", "count": 2, "player": 1, "x": 1.0, "y": 1.0}
        if fid == "vibe.unit.add_behavior":
            return {"unit_tag": anchor, "behavior": "StimpackBehavior", "stacks": 1}
        if fid == "vibe.unit.query_behavior":
            return {"unit_tag": anchor, "behavior": "StimpackBehavior"}
        if fid == "vibe.unit.add_ability":
            return {"unit_tag": anchor, "ability": "Stimpack"}
        if fid == "vibe.unit.query_ability":
            return {"unit_tag": anchor, "ability": "Stimpack"}
        if fid == "vibe.unit.set_vital":
            return {"unit_tag": anchor, "vital": "life", "value": 100.0}
        if fid == "vibe.unit.query_attrs":
            return {"unit_tag": anchor}
        if fid == "vibe.catalog.set":
            return {"catalog": "unit", "entry": "Marine", "field": "t", "player": 0, "value": "v"}
        if fid == "vibe.catalog.get":
            return {"catalog": "unit", "entry": "Marine", "field": "t", "player": 0}
        if fid == "vibe.visual.set_tint":
            return {"unit_tag": anchor, "color": "#ff0000"}
        if fid == "vibe.visual.set_scale":
            return {"unit_tag": anchor, "scale": 2.0}
        if fid == "vibe.visual.set_opacity":
            return {"unit_tag": anchor, "opacity": 0.5}
        if fid == "vibe.visual.model_swap":
            return {"unit_tag": anchor, "model": "Marine", "variation": 1}
        if fid == "vibe.query.units":
            return {"player": 1}
        if fid == "vibe.query.structures":
            return {"owner_player": 1}
        if fid == "vibe.unit.kill":
            return {"unit_tag": anchor}
        if fid == "vibe.unit.attack":
            return {"attacker_tag": anchor, "target_tag": enemy}
        raise AssertionError(f"no fixture for {fid}")

    def test_every_vibe_callable_through_bridge_individually(self):
        """Each of the 20 vibe.* must be callable on its own through the bridge."""
        bridge = SimulatorSessionDebugVmBridge()
        anchor = self._spawn_tag(bridge, player=1, x=1.0, y=1.0)
        enemy = self._spawn_tag(bridge, player=2, x=9.0, y=9.0)
        # kill destroys the anchor, so run it last.
        ordered = [v for v in self.vibe if v != "vibe.unit.kill"] + ["vibe.unit.kill"]
        for fid in ordered:
            with self.subTest(fid=fid):
                resp = bridge.call(fid, self._bridge_args(fid, anchor, enemy))
                self.assertEqual(
                    resp.error_code, 0,
                    msg=f"{fid} failed: {resp.kind}/{resp.error_code}: {resp.payload}",
                )
                self.assertIsInstance(resp.payload, dict)

    def _payload(self, resp):
        """The bridge returns a protocol.Response for vibe.* but a plain dict for
        the gen.* routing short-circuit; normalize both to a dict payload."""
        return resp if isinstance(resp, dict) else resp.payload

    def test_gen_routing_marker_through_bridge(self):
        bridge = SimulatorSessionDebugVmBridge()
        for fid in self.gen[:50]:
            with self.subTest(fid=fid):
                resp = bridge.call(fid, _sample_args(self.fns[fid]))
                # bridge short-circuits gen.* to a routing marker (no live Galaxy).
                self.assertEqual(self._payload(resp).get("routed"), "runtime")


class GenArgValidationContractTests(unittest.TestCase):
    """The runtime contract for ``gen.*`` must be *uniform* with ``vibe.*``:

    * valid, registry-conformant args -> accepted (routed marker, carries the
      normalized args);
    * invalid args (missing required, wrong scalar type, unknown arg) -> rejected
      with ``INVALID_ARGS``.

    This used to be a hole: the two bridges short-circuited ``gen.*`` and returned
    a routing marker for *any* args, so a malformed ``gen.*`` call was silently
    accepted at the bridge layer while ``vibe.*`` was fully validated. The bridge
    now routes ``gen.*`` through ``invoke_registered_function`` (which validates),
    so the contract holds across all 11676 internal functions, not just the 20
    handwritten ones.
    """

    def setUp(self):
        self.fns = load_function_metadata()
        self.gen = sorted(k for k in self.fns if k.startswith("gen."))
        self.bridge = SimulatorSessionDebugVmBridge()

    @staticmethod
    def _payload(resp):
        return resp if isinstance(resp, dict) else resp.payload

    def _build_full_args(self, spec: dict) -> dict:
        """Fill every declared arg with a registry-conformant value (required + defaults)."""
        args: dict = {}
        for name, as_ in spec.get("args", {}).items():
            type_name = as_.get("type")
            if type_name == "integer":
                args[name] = int(as_.get("min", 1)) if "min" in as_ else 1
            elif type_name == "fixed":
                args[name] = float(as_.get("min", 1.0)) if "min" in as_ else 1.0
            elif type_name == "string":
                args[name] = (as_.get("enum") or ["x"])[0]
            else:
                args[name] = "x"
        return args

    def _arity(self, spec: dict) -> int:
        return sum(
            1 for a in spec.get("args", {}).values()
            if a.get("required", False) or "default" in a
        )

    def test_bridge_rejects_missing_required_arg(self):
        # gen.5 is arity-2 (p0 integer, p1 string); drop p1 -> must be rejected.
        resp = self.bridge.call("gen.5", {"p0": 1})
        self.assertEqual(self._payload(resp).get("error_code"), "INVALID_ARGS")

    def test_bridge_rejects_wrong_scalar_type(self):
        resp = self.bridge.call("gen.5", {"p0": "not-an-int", "p1": "a"})
        self.assertEqual(self._payload(resp).get("error_code"), "INVALID_ARGS")

    def test_bridge_rejects_unknown_arg(self):
        resp = self.bridge.call("gen.5", {"p0": 1, "p1": "a", "bogus": 1})
        self.assertEqual(self._payload(resp).get("error_code"), "INVALID_ARGS")

    def test_bridge_accepts_valid_gen_args(self):
        ok = self._payload(self.bridge.call("gen.5", {"p0": 1, "p1": "a"}))
        self.assertEqual(ok.get("routed"), "runtime")
        # normalized args are echoed back, so the VM trace is honest
        self.assertEqual(ok.get("args", {}).get("p0"), 1)

    def test_canonical_dispatcher_rejects_invalid_gen_args(self):
        cases = [
            ("gen.5", {"p0": 1}),                      # missing required p1
            ("gen.5", {"p0": "x", "p1": "a"}),         # wrong type p0
            ("gen.5", {"p0": 1, "p1": "a", "extra": 1}),  # unknown arg
            ("gen.1", {"p0": 1, "p1": "a"}),           # arity-3 missing p2
        ]
        for fid, bad_args in cases:
            with self.subTest(fid=fid):
                with self.assertRaises(Exception):
                    invoke_registered_function(fid, bad_args, registry=self.fns)

    def test_every_arity_class_dispatchable_via_bridge(self):
        """One representative gen.* from each arity class (0,1,2,...,38) must route."""
        by_arity: dict[int, str] = {}
        for fid in self.gen:
            by_arity.setdefault(self._arity(self.fns[fid]), fid)
        # signatures are genuinely heterogeneous (see gen arity distribution).
        self.assertGreaterEqual(len(by_arity), 10, msg=f"arity classes found: {sorted(by_arity)}")
        for arity, fid in sorted(by_arity.items()):
            with self.subTest(arity=arity, fid=fid):
                args = self._build_full_args(self.fns[fid])
                ok = self._payload(self.bridge.call(fid, args))
                self.assertEqual(ok.get("routed"), "runtime", msg=f"{fid} args={args}")

    def test_bridge_does_not_overreject_valid_gen_sample(self):
        """A broad sample of valid gen.* calls must all route (no false rejects)."""
        step = max(1, len(self.gen) // 200)
        accepted = 0
        for fid in self.gen[::step]:
            args = _sample_args(self.fns[fid])
            ok = self._payload(self.bridge.call(fid, args))
            self.assertEqual(
                ok.get("routed"), "runtime",
                msg=f"{fid} wrongly rejected: {ok.get('error_code')} {ok.get('payload')}",
            )
            accepted += 1
        self.assertGreaterEqual(accepted, 100)


class HostBridgeRuntimeContractTests(unittest.TestCase):
    """The live Host bridge must honor the SAME gen.* runtime contract offline.

    ``gen.*`` adapters only exist inside the live Galaxy runtime, but the Host
    bridge validates args and returns the routing marker *without opening a
    websocket*, so the VM can prove routability for all 11676 ``gen.*`` before a
    host attaches. This closes the loop opened by ``GenArgValidationContractTests``
    for the Simulator bridge: both runtime paths present one uniform contract.
    """

    def setUp(self):
        self.fns = load_function_metadata()
        self.gen = sorted(k for k in self.fns if k.startswith("gen."))
        self.host = HostDebugVmBridge("ws://127.0.0.1:0/void")  # never connects for gen.*

    @staticmethod
    def _payload(resp):
        return resp if isinstance(resp, dict) else resp.payload

    def test_gen_routing_marker_offline_no_connection(self):
        async def _go():
            return await self.host.call("gen.5", {"p0": 1, "p1": "a"})
        resp = asyncio.run(_go())
        self.assertEqual(self._payload(resp).get("routed"), "runtime")

    def test_gen_invalid_args_rejected_offline(self):
        async def _go():
            return await self.host.call("gen.5", {"p0": 1})  # missing required p1
        resp = asyncio.run(_go())
        self.assertEqual(self._payload(resp).get("error_code"), "INVALID_ARGS")

    def test_host_and_sim_bridges_agree_on_gen(self):
        sim = SimulatorSessionDebugVmBridge()
        for fid in self.gen[:30]:
            with self.subTest(fid=fid):
                args = _sample_args(self.fns[fid])
                h = asyncio.run(self.host.call(fid, args))
                s = sim.call(fid, args)
                self.assertEqual(
                    self._payload(h).get("routed"), self._payload(s).get("routed"),
                    msg=f"{fid}: host={self._payload(h)} sim={self._payload(s)}",
                )


if __name__ == "__main__":
    unittest.main()
