"""Runtime-side proof: the generated Galaxy bundle backs every runtime gen.* call.

The offline VM (test_vm_all_internal_coverage.py) proves the *Python* side routes
all 11,676 ``gen.*`` through the canonical dispatcher. But a ``gen.N`` is only
*callable at runtime* if the compiled Galaxy bundle shipped with the map actually
contains a ``libVibeInvoke_gf_Call<N>`` adapter and a ``Dispatch`` route to it.

This file statically verifies that invariant for the generated bundle, so a
generator→Galaxy drift (the VIBE_GEN_001..007 class: shard arity mismatch,
nested else-if overflow, native argument-type mismatch, …) cannot ship silently.
It is the compiled-code counterpart to the offline routing sweep.

The bundle is *per-map* — the registry is the union of every map's exposed
functions, so a single map legitimately exposes a subset. The invariant tested
here is therefore *internal consistency*: every adapter that is defined is also
routed, every route lands on a defined adapter, and ``functionId == N`` always
dispatches to ``CallN`` (never a misnumbered neighbour). A dangling route or a
misrouted id would mean a ``gen.*`` the VM promises to call would crash the
Kernel at runtime.
"""
from __future__ import annotations

import glob
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]  # .../sc2-porting-workspace
# Per-map generated bundle: .../packages/Maps/<Map>/Base.SC2Data/generated/<Map>/
MAPS_ROOT = ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps"
REGISTRY_PATH = ROOT / "tools" / "galaxy-vibe" / "kernel" / "function-registry.json"


def _find_bundles() -> list[Path]:
    """Return every directory that contains a LibVibeInvokeDispatch.galaxy."""
    found = []
    for dispatch in MAPS_ROOT.rglob("LibVibeInvokeDispatch.galaxy"):
        found.append(dispatch.parent)
    return sorted(found)


def _parse_bundle(bundle: Path):
    """Return (call_defs, routes) for a generated bundle directory.

    *call_defs* — set of N where ``libVibeInvoke_gf_Call<N>(`` is defined.
    *routes*    — set of (functionId, callN) where a shard routes
                   ``functionId == N { ... libVibeInvoke_gf_Call<N>(``.
    """
    call_defs: set[int] = set()
    routes: set[tuple[int, int]] = set()
    for path in glob.glob(str(bundle / "LibVibeInvoke_*.galaxy")):
        src = Path(path).read_text(encoding="utf-8")
        for m in re.finditer(r"libVibeInvoke_gf_Call(\d+)\s*\(", src):
            call_defs.add(int(m.group(1)))
        for m in re.finditer(
            r"functionId\s*==\s*(\d+)\s*\)\s*\{[^}]*?libVibeInvoke_gf_Call(\d+)", src, re.S
        ):
            routes.add((int(m.group(1)), int(m.group(2))))
    return call_defs, routes


class GalaxyBundleConsistencyTests(unittest.TestCase):
    """Every shipped adapter must be routed, and routed correctly."""

    @classmethod
    def setUpClass(cls):
        cls.bundles = _find_bundles()
        cls.gen_ids = None
        if REGISTRY_PATH.exists():
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            functions = data.get("functions", {})
            cls.gen_ids = {int(k[4:]) for k in functions if k.startswith("gen.")}

    def test_bundle_present(self):
        # Skip (not fail) when no generated bundle is checked out locally.
        if not self.bundles:
            self.skipTest("no generated LibVibeInvoke bundle found under packages/Maps")
        self.assertGreaterEqual(len(self.bundles), 1)

    def test_every_adapter_is_routed(self):
        if not self.bundles:
            self.skipTest("no generated LibVibeInvoke bundle found")
        for bundle in self.bundles:
            with self.subTest(bundle=bundle.name):
                call_defs, routes = _parse_bundle(bundle)
                routed_ids = {n for n, _ in routes}
                orphan = sorted(call_defs - routed_ids)
                self.assertEqual(
                    orphan, [],
                    msg=f"{bundle.name}: {len(orphan)} Call<N> adapters with no Dispatch route: {orphan[:10]}",
                )

    def test_every_route_targets_a_defined_adapter(self):
        if not self.bundles:
            self.skipTest("no generated LibVibeInvoke bundle found")
        for bundle in self.bundles:
            with self.subTest(bundle=bundle.name):
                call_defs, routes = _parse_bundle(bundle)
                dangling = sorted({(n, c) for n, c in routes if c not in call_defs})
                self.assertEqual(
                    dangling, [],
                    msg=f"{bundle.name}: {len(dangling)} routes to undefined Call: {dangling[:10]}",
                )

    def test_function_id_matches_call_target(self):
        """functionId == N must dispatch to CallN, never a misnumbered neighbour."""
        if not self.bundles:
            self.skipTest("no generated LibVibeInvoke bundle found")
        for bundle in self.bundles:
            with self.subTest(bundle=bundle.name):
                _, routes = _parse_bundle(bundle)
                mismatches = sorted({(n, c) for n, c in routes if n != c})
                self.assertEqual(
                    mismatches, [],
                    msg=f"{bundle.name}: functionId != Call target: {mismatches[:10]}",
                )

    def test_defs_equal_routes_count(self):
        """The adapter set and the routed set must be identical (no drift)."""
        if not self.bundles:
            self.skipTest("no generated LibVibeInvoke bundle found")
        for bundle in self.bundles:
            with self.subTest(bundle=bundle.name):
                call_defs, routes = _parse_bundle(bundle)
                routed_ids = {n for n, _ in routes}
                self.assertEqual(
                    len(call_defs), len(routed_ids),
                    msg=f"{bundle.name}: {len(call_defs)} defs vs {len(routed_ids)} routes",
                )

    def test_exposed_adapters_back_registered_functions(self):
        """Every adapter a bundle ships must correspond to a registered gen.* id."""
        if not self.bundles:
            self.skipTest("no generated LibVibeInvoke bundle found")
        if self.gen_ids is None:
            self.skipTest("function-registry.json not found")
        for bundle in self.bundles:
            with self.subTest(bundle=bundle.name):
                call_defs, _ = _parse_bundle(bundle)
                phantom = sorted(call_defs - self.gen_ids)
                self.assertEqual(
                    phantom, [],
                    msg=f"{bundle.name}: {len(phantom)} Call<N> with no registry entry: {phantom[:10]}",
                )


if __name__ == "__main__":
    unittest.main()
