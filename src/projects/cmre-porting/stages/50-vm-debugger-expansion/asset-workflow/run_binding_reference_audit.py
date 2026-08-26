"""Quantify offline binding candidates for an SC2 AI mesh reference.

The audit is deliberately separate from the production W4 runner. It opens a
saved M3Studio authoring Blend, imports one static GLB, builds isolated binding
candidates, samples the canonical actions, and writes JSON evidence. It never
modifies the source M3, exports an M3, launches SC2, or edits a map/mod.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


ROOT_MARKER = Path("src/config/workspace.json")
REQUIRED_ACTIONS = ("Stand", "Walk", "Attack")
AUDIT_MODES = (
    "chest-rigid",
    "pelvis-rigid",
    "automatic",
    "envelope",
    "template-nearest-vertex-transfer",
)
NON_SKIN_GROUPS = frozenset(
    {
        "Dummy01",
        "Ref_Head",
        "Ref_Weapon Left",
        "Ref_Weapon Right",
        "HitTestFuzzy01",
        "HitTestFuzzy02",
        "HitTestTight",
        "HitTestFuzzy",
        "Ref_Center",
        "Vol_Target",
        "Unit_Zerg_Zergling_Konker_02",
        "Ref_Hardpoint",
        "Ref_Origin",
        "Ref_Overhead",
    }
)


def workspace_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ROOT_MARKER).is_file():
            return parent
    raise RuntimeError("workspace root not found")


ROOT = workspace_root()


def resolve_path(value: str | Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-blend", required=True, type=Path)
    parser.add_argument("--candidate-glb", required=True, type=Path)
    parser.add_argument("--out-report", required=True, type=Path)
    return parser.parse_args(raw)


def bone_hierarchy(armature: bpy.types.Object) -> list[dict[str, Any]]:
    return [
        {
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "head": list(bone.head_local),
            "tail": list(bone.tail_local),
        }
        for bone in armature.data.bones
    ]


def find_actions(armature: bpy.types.Object) -> dict[str, bpy.types.Action]:
    resolved: dict[str, bpy.types.Action] = {}
    for requested in REQUIRED_ACTIONS:
        wanted = "".join(ch.lower() for ch in requested if ch.isalnum())
        for action in bpy.data.actions:
            normalized = "".join(ch.lower() for ch in action.name if ch.isalnum())
            if normalized == wanted or normalized.endswith(wanted) or wanted in normalized:
                resolved[requested] = action
                break
    missing = [name for name in REQUIRED_ACTIONS if name not in resolved]
    if missing:
        raise RuntimeError(f"missing required actions: {missing}")
    if armature.animation_data is None:
        armature.animation_data_create()
    return resolved


def bounds_from_points(points: list[Vector]) -> dict[str, list[float]]:
    if not points:
        raise RuntimeError("cannot calculate bounds for empty point set")
    lo = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    hi = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    return {"min": list(lo), "max": list(hi), "dimensions": list(hi - lo)}


def evaluated_vertices(obj: bpy.types.Object) -> list[Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co.copy() for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def mesh_signature(points: list[Vector]) -> str:
    digest = hashlib.sha256()
    for point in points:
        digest.update(",".join(f"{value:.7f}" for value in point).encode("ascii"))
        digest.update(b";")
    return digest.hexdigest()


def align_candidate(candidate: bpy.types.Object, source_meshes: list[bpy.types.Object], armature: bpy.types.Object) -> dict[str, Any]:
    target_points = [point for mesh in source_meshes for point in evaluated_vertices(mesh)]
    target_bounds = bounds_from_points(target_points)
    target_dim = Vector(target_bounds["dimensions"])

    imported_world = candidate.matrix_world.copy()
    candidate.data.transform(imported_world)
    candidate.matrix_world = Matrix.Identity(4)
    candidate.data.transform(Matrix.Rotation(math.radians(90.0), 4, "Z"))
    bpy.context.view_layer.update()

    source_points = evaluated_vertices(candidate)
    source_bounds = bounds_from_points(source_points)
    source_dim = Vector(source_bounds["dimensions"])
    if min(source_dim) <= 0 or min(target_dim) <= 0:
        raise RuntimeError("cannot align zero-sized mesh")
    fit_scale = Vector((target_dim.x / source_dim.x, target_dim.y / source_dim.y, target_dim.z / source_dim.z))
    candidate.data.transform(Matrix.Diagonal((fit_scale.x, fit_scale.y, fit_scale.z, 1.0)))

    root = armature.data.bones.get("Ref_Origin") or armature.data.bones.get("Dummy01")
    if root is None:
        raise RuntimeError("canonical source has no Ref_Origin/Dummy01 root")
    target_root = armature.matrix_world @ root.head_local
    candidate.data.transform(Matrix.Translation(target_root))
    candidate.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    final_bounds = bounds_from_points(evaluated_vertices(candidate))
    return {
        "rotationZDegrees": 90.0,
        "targetRootBone": root.name,
        "targetRoot": list(target_root),
        "targetBounds": target_bounds,
        "sourceBoundsAfterAxisCorrection": source_bounds,
        "finalBounds": final_bounds,
    }


def clear_binding(obj: bpy.types.Object) -> None:
    for modifier in list(obj.modifiers):
        if modifier.type == "ARMATURE":
            obj.modifiers.remove(modifier)
    for group in list(obj.vertex_groups):
        obj.vertex_groups.remove(group)
    obj.parent = None
    obj.matrix_parent_inverse = Matrix.Identity(4)


def add_armature_modifier(obj: bpy.types.Object, armature: bpy.types.Object) -> None:
    modifier = obj.modifiers.new("AuditArmature", "ARMATURE")
    modifier.object = armature


def transfer_template_weights(mesh: bpy.types.Object, source_meshes: list[bpy.types.Object]) -> None:
    samples: list[tuple[Vector, dict[str, float]]] = []
    group_names: set[str] = set()
    for source in source_meshes:
        for vertex in source.data.vertices:
            assignments: dict[str, float] = {}
            for assignment in vertex.groups:
                if assignment.group >= len(source.vertex_groups):
                    continue
                name = source.vertex_groups[assignment.group].name
                if name not in NON_SKIN_GROUPS and assignment.weight > 0.0:
                    assignments[name] = assignment.weight
            if assignments:
                samples.append((source.matrix_world @ vertex.co, assignments))
                group_names.update(assignments)
    if not samples:
        raise RuntimeError("source M3 has no transferable skin assignments")

    tree = KDTree(len(samples))
    for index, (point, _) in enumerate(samples):
        tree.insert(point, index)
    tree.balance()
    groups = {name: mesh.vertex_groups.new(name=name) for name in sorted(group_names)}
    for vertex in mesh.data.vertices:
        point = mesh.matrix_world @ vertex.co
        neighbors = tree.find_n(point, min(4, len(samples)))
        if neighbors and neighbors[0][2] <= 1e-8:
            neighbors = neighbors[:1]
        blended: dict[str, float] = {}
        for _, sample_index, distance in neighbors:
            influence = 1.0 / max(distance, 1e-6)
            for name, weight in samples[sample_index][1].items():
                blended[name] = blended.get(name, 0.0) + influence * weight
        total = sum(blended.values())
        if total <= 0.0:
            raise RuntimeError(f"weight transfer produced no assignment for vertex {vertex.index}")
        for name, weight in blended.items():
            groups[name].add([vertex.index], weight / total, "REPLACE")


def bind_candidate(obj: bpy.types.Object, armature: bpy.types.Object, source_meshes: list[bpy.types.Object], mode: str) -> None:
    clear_binding(obj)
    if mode in {"chest-rigid", "pelvis-rigid"}:
        obj.parent = armature
        obj.matrix_parent_inverse = armature.matrix_world.inverted()
        group = obj.vertex_groups.new(name="Bone_Chest" if mode == "chest-rigid" else "Bone_Pelvis")
        group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
        add_armature_modifier(obj, armature)
        return
    if mode == "template-nearest-vertex-transfer":
        obj.parent = armature
        obj.matrix_parent_inverse = armature.matrix_world.inverted()
        transfer_template_weights(obj, source_meshes)
        add_armature_modifier(obj, armature)
        return
    if mode not in {"automatic", "envelope"}:
        raise RuntimeError(mode)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.parent_set(type="ARMATURE_AUTO" if mode == "automatic" else "ARMATURE_ENVELOPE")
    # Parent Set may add its own modifier. Keep the generated groups but make
    # the modifier stack deterministic for the audit.
    for modifier in list(obj.modifiers):
        if modifier.type == "ARMATURE":
            obj.modifiers.remove(modifier)
    add_armature_modifier(obj, armature)


def group_metrics(obj: bpy.types.Object) -> dict[str, Any]:
    assigned = 0
    influence_counts: list[int] = []
    for vertex in obj.data.vertices:
        count = sum(1 for assignment in vertex.groups if assignment.weight > 0.0)
        if count:
            assigned += 1
        influence_counts.append(count)
    return {
        "vertexGroups": len(obj.vertex_groups),
        "vertexGroupNames": sorted(group.name for group in obj.vertex_groups),
        "assignedVertices": assigned,
        "totalVertices": len(obj.data.vertices),
        "unassignedVertices": len(obj.data.vertices) - assigned,
        "maxInfluencesPerVertex": max(influence_counts, default=0),
        "meanInfluencesPerVertex": sum(influence_counts) / len(influence_counts) if influence_counts else 0.0,
    }


def shape_change(rest: list[Vector], posed: list[Vector]) -> dict[str, float]:
    if len(rest) != len(posed):
        raise RuntimeError("rest and posed vertex counts differ")
    deltas = [(posed[index] - rest[index]).length for index in range(len(rest))]
    sample_indices = list(range(0, len(rest), max(1, len(rest) // 64)))[:64]
    pair_errors: list[float] = []
    for left_index, left in enumerate(sample_indices):
        for right in sample_indices[left_index + 1 :]:
            rest_distance = (rest[left] - rest[right]).length
            if rest_distance > 1e-6:
                posed_distance = (posed[left] - posed[right]).length
                pair_errors.append(abs(posed_distance - rest_distance) / rest_distance)
    return {
        "maxVertexDelta": max(deltas, default=0.0),
        "meanVertexDelta": sum(deltas) / len(deltas) if deltas else 0.0,
        "movedFraction": sum(delta > 1e-4 for delta in deltas) / len(deltas) if deltas else 0.0,
        "sampledPairDistanceChangeMean": sum(pair_errors) / len(pair_errors) if pair_errors else 0.0,
        "sampledPairDistanceChangeMax": max(pair_errors, default=0.0),
    }


def action_metrics(armature: bpy.types.Object, actions: dict[str, bpy.types.Action], obj: bpy.types.Object, rest: list[Vector]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for requested in REQUIRED_ACTIONS:
        action = actions[requested]
        armature.animation_data.action = action
        start, end = action.frame_range
        frame_samples = (int(start), int((start + end) / 2), int(end))
        samples: dict[str, Any] = {}
        for label, frame in zip(("start", "mid", "end"), frame_samples):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            posed = evaluated_vertices(obj)
            samples[label] = {
                "frame": frame,
                "bounds": bounds_from_points(posed),
                "deformation": shape_change(rest, posed),
                "poseSignature": mesh_signature(posed),
            }
        results[requested] = {
            "resolvedAction": action.name,
            "frames": list(frame_samples),
            "samples": samples,
        }
    armature.animation_data.action = None
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    return results


def assessment(mode: str, metrics: dict[str, Any]) -> dict[str, str]:
    if mode in {"chest-rigid", "pelvis-rigid"}:
        return {
            "role": "shape-preserving-control",
            "finding": "Whole mesh follows one bone; it is not a usable local skinning solution.",
            "decision": "reject-as-production-binding",
        }
    if mode == "template-nearest-vertex-transfer":
        return {
            "role": "current-production-baseline",
            "finding": "Canonical groups and actions are retained, but visual fit still requires manual review.",
            "decision": "retain-for-review",
        }
    return {
        "role": "automatic-comparison-baseline",
        "finding": "Automatic groups provide a diagnostic comparison only; numeric deformation does not prove anatomical fit.",
        "decision": "do-not-promote-without-visual-review",
    }


def main() -> None:
    args = parse_args()
    source_blend = resolve_path(args.source_blend)
    candidate_glb = resolve_path(args.candidate_glb)
    out_report = resolve_path(args.out_report)
    if not source_blend.is_file() or not candidate_glb.is_file():
        raise FileNotFoundError(f"missing source input: {source_blend} / {candidate_glb}")

    bpy.ops.wm.open_mainfile(filepath=str(source_blend))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    source_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not source_meshes:
        raise RuntimeError("source Blend contains no template meshes")
    if armature.animation_data:
        armature.animation_data.action = None
    bpy.context.scene.frame_set(0)
    bpy.ops.import_scene.gltf(filepath=str(candidate_glb))
    imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name == "node_0"]
    if len(imported) != 1:
        raise RuntimeError(f"expected one imported candidate mesh, got {[obj.name for obj in imported]}")
    candidate = imported[0]
    alignment = align_candidate(candidate, source_meshes, armature)
    actions = find_actions(armature)
    candidates: list[dict[str, Any]] = []
    for mode in AUDIT_MODES:
        obj = candidate.copy()
        obj.data = candidate.data.copy()
        obj.name = f"binding_audit_{mode}"
        bpy.context.scene.collection.objects.link(obj)
        bind_candidate(obj, armature, source_meshes, mode)
        bpy.context.view_layer.update()
        armature.animation_data.action = None
        bpy.context.scene.frame_set(0)
        bpy.context.view_layer.update()
        rest = evaluated_vertices(obj)
        metrics = {
            "mode": mode,
            "geometry": {
                "vertices": len(obj.data.vertices),
                "triangles": sum(len(poly.vertices) - 2 for poly in obj.data.polygons),
                "restBounds": bounds_from_points(rest),
            },
            "groups": group_metrics(obj),
            "actions": action_metrics(armature, actions, obj, rest),
        }
        metrics["assessment"] = assessment(mode, metrics)
        candidates.append(metrics)
        clear_binding(obj)
        bpy.data.objects.remove(obj, do_unlink=True)
    report = {
        "schemaVersion": 1,
        "workflow": "offline-sc2-ai-binding-reference-audit.v1",
        "evidenceType": "static",
        "inputs": {
            "sourceBlend": str(source_blend.relative_to(ROOT)).replace("\\", "/"),
            "candidateGlb": str(candidate_glb.relative_to(ROOT)).replace("\\", "/"),
            "templateArmature": armature.name,
            "templateBoneCount": len(armature.data.bones),
            "requiredActions": list(REQUIRED_ACTIONS),
        },
        "templateBones": bone_hierarchy(armature),
        "candidates": candidates,
        "recommendation": {
            "referenceRole": "Teach AI to preserve a canonical SC2 rig and action contract while generating mesh and texture content.",
            "preferredWorkflow": "Use the template rig and actions, start from supervised/template weight transfer, then perform manual local Weight Paint or regenerate the mesh to template proportions.",
            "doNotLearnAsGroundTruth": [
                "Whole-mesh rigid parenting",
                "Unreviewed automatic or envelope weights",
                "Current candidate deform-bone overlay as an anatomical fit target",
            ],
            "scopeBoundary": "Offline Blender evidence only; no SC2 Previewer, Actor, map, mod, or in-game runtime validation.",
        },
    }
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("BINDING_REFERENCE_AUDIT_READY=" + str(out_report))
    bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
