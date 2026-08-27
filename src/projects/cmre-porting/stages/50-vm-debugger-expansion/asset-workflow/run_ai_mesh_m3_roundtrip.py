"""Offline W4/W5 AI mesh integration and M3 round-trip preview.

This runner is intentionally Blender/M3Studio-only. It never launches SC2 or edits
maps/mods. The source M3 remains read-only; every output is written under the
Stage50 artifact directory.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

ROOT_MARKER = Path("src/config/workspace.json")
REQUIRED_ACTIONS = ("Stand", "Walk", "Attack")
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
        "BoneStockR01",
        "BoneStockR02",
        "BoneStockR03",
        "BoneStockL01",
        "BoneStockL02",
        "BoneStockL03",
    }
)
SEGMENT_WEIGHT_SIGMA = 0.08



def workspace_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ROOT_MARKER).is_file():
            return parent
    raise RuntimeError("workspace root not found")


ROOT = workspace_root()


def path(value: str | Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("integrate", "verify"), required=True)
    parser.add_argument("--source-m3", required=True, type=Path)
    parser.add_argument("--candidate-glb", required=False, type=Path)
    parser.add_argument("--candidate-m3", required=False, type=Path)
    parser.add_argument("--addon-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--diffuse", required=False, type=Path)
    parser.add_argument("--normal", required=False, type=Path)
    parser.add_argument("--bone-fit-mode", choices=("skin-groups", "template", "surface-fitted"), default="template")
    parser.add_argument("--weight-mode", choices=("body-transfer", "all-surface", "surface-transfer", "fitted-segments"), default="body-transfer")
    parser.add_argument("--segment-sigma", type=float, default=SEGMENT_WEIGHT_SIGMA)
    parser.add_argument("--segment-influences", type=int, default=4)
    parser.add_argument("--animation-scale", type=float, default=1.0)
    parser.add_argument(
        "--surface-fit-strategy",
        choices=("iterative-segment", "source-chain-landmarks"),
        default="iterative-segment",
        help="Use ordered source groups and terminal landmarks instead of a self-referential segment refinement.",
    )
    return parser.parse_args(raw)


def clear_scene() -> None:
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for action in list(bpy.data.actions):
        if action.users == 0:
            bpy.data.actions.remove(action)


def register_m3studio(addon_dir: Path) -> None:
    addon_dir = path(addon_dir).resolve()
    if str(addon_dir) not in sys.path:
        sys.path.insert(0, str(addon_dir))
    import m3studio  # type: ignore[import-not-found]

    try:
        m3studio.register()
    except (RuntimeError, ValueError) as exc:
        if not hasattr(bpy.ops.m3, "import"):
            raise RuntimeError(f"M3Studio registration failed: {exc}") from exc


def import_m3(model: Path) -> bpy.types.Object:
    result = getattr(bpy.ops.m3, "import")(
        filepath=str(path(model)),
        id_name="(New Object)",
        get_mesh=True,
        get_effects=False,
        get_rig=True,
        get_anims=True,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"M3 import did not finish: {result}")
    armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("M3 import produced no armature")
    return armature


def actions_for(armature: bpy.types.Object) -> dict[str, bpy.types.Action]:
    actions = {action.name: action for action in bpy.data.actions}
    resolved: dict[str, bpy.types.Action] = {}
    for requested in REQUIRED_ACTIONS:
        wanted = "".join(ch.lower() for ch in requested if ch.isalnum())
        for name, action in actions.items():
            normalized = "".join(ch.lower() for ch in name if ch.isalnum())
            if normalized == wanted or normalized.endswith(wanted) or wanted in normalized:
                resolved[requested] = action
                break
    missing = [name for name in REQUIRED_ACTIONS if name not in resolved]
    if missing:
        raise RuntimeError(f"missing required actions: {missing}")
    if armature.animation_data is None:
        armature.animation_data_create()
    return resolved
def reset_pose(armature: bpy.types.Object, frame: int = 0) -> None:
    armature.animation_data_create()
    armature.animation_data.action = None
    for pose_bone in armature.pose.bones:
        pose_bone.matrix_basis.identity()
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points: list[Vector] = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        points.extend(evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box)
    if not points:
        raise RuntimeError("no mesh bounds")
    return (
        Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points))),
        Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points))),
    )
def raw_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    """Return undeformed mesh bounds in world space.

    Alignment must use bind-pose vertices, not an evaluated Armature modifier;
    the imported source M3 may still have an action selected when this runs.
    """
    points = [obj.matrix_world @ vertex.co for obj in objects for vertex in obj.data.vertices]
    if not points:
        raise RuntimeError("no raw mesh vertices")
    return (
        Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points))),
        Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points))),
    )



def dimensions(lo: Vector, hi: Vector) -> Vector:
    return hi - lo

def mesh_surface_area(mesh: bpy.types.Object) -> float:
    """Return the source mesh's world-space surface area for body selection."""
    area = 0.0
    for polygon in mesh.data.polygons:
        if len(polygon.vertices) < 3:
            continue
        origin = mesh.matrix_world @ mesh.data.vertices[polygon.vertices[0]].co
        for offset in range(1, len(polygon.vertices) - 1):
            first = mesh.matrix_world @ mesh.data.vertices[polygon.vertices[offset]].co
            second = mesh.matrix_world @ mesh.data.vertices[polygon.vertices[offset + 1]].co
            area += (first - origin).cross(second - origin).length * 0.5
    return area


def has_transferable_weights(mesh: bpy.types.Object) -> bool:
    deform_groups = {
        group.index for group in mesh.vertex_groups if group.name not in NON_SKIN_GROUPS
    }
    return any(
        assignment.group in deform_groups and assignment.weight > 0.0
        for vertex in mesh.data.vertices
        for assignment in vertex.groups
    )


def select_alignment_body(source_meshes: list[bpy.types.Object]) -> bpy.types.Object:
    """Select the visible canonical body, not attachment/collision meshes.

    The imported M3 contains several skinned helper parts. The highest-vertex
    object is not sufficient here because the helper/limb shell is split into
    many disconnected triangles. The largest transferable surface is the
    actual character body (Mesh.005 in the Zergling template).
    """
    candidates = [mesh for mesh in source_meshes if has_transferable_weights(mesh)]
    if not candidates:
        raise RuntimeError("source M3 has no skinned body candidate")
    return max(candidates, key=mesh_surface_area)



def align_candidate(candidate: bpy.types.Object, target_meshes: list[bpy.types.Object]) -> dict[str, Any]:
    # glTF import leaves a -90-degree X basis on the object. Bake that basis
    # first; otherwise Blender's transform_apply applies the fit scale in the
    # wrong local axes and detaches the mesh from the canonical skeleton.
    target_lo, target_hi = raw_bounds(target_meshes)
    target_dim = dimensions(target_lo, target_hi)
    imported_world = candidate.matrix_world.copy()
    candidate.data.transform(imported_world)
    candidate.matrix_world = Matrix.Identity(4)
    axis_matrix = Matrix.Rotation(math.radians(90.0), 4, "Z")
    candidate.data.transform(axis_matrix)
    bpy.context.view_layer.update()
    source_lo, source_hi = raw_bounds([candidate])
    source_dim = dimensions(source_lo, source_hi)
    if min(source_dim) <= 0 or min(target_dim) <= 0:
        raise RuntimeError("cannot align zero-sized mesh")
    fit_scale = Vector((
        target_dim.x / source_dim.x,
        target_dim.y / source_dim.y,
        target_dim.z / source_dim.z,
    ))
    candidate.data.transform(Matrix.Diagonal((fit_scale.x, fit_scale.y, fit_scale.z, 1.0)))
    scaled_lo, scaled_hi = raw_bounds([candidate])
    armature = next((obj.parent for obj in target_meshes if obj.parent and obj.parent.type == "ARMATURE"), None)
    root = armature.data.bones.get("Ref_Origin") if armature else None
    if root is None and armature:
        root = armature.data.bones.get("Dummy01")
    if root is None or armature is None:
        raise RuntimeError("canonical source has no Ref_Origin/Dummy01 root")
    target_root = armature.matrix_world @ root.head_local
    translation = target_lo - scaled_lo
    candidate.data.transform(Matrix.Translation(translation))
    candidate.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    final_lo, final_hi = raw_bounds([candidate])
    return {
        "rotationZDegrees": 90.0,
        "targetRootBone": root.name,
        "targetRoot": list(target_root),
        "targetMeshes": [mesh.name for mesh in target_meshes],
        "translationMode": "source-bounds-to-body-bounds",
        "translation": list(translation),
        "targetBounds": {"min": list(target_lo), "max": list(target_hi), "dimensions": list(target_dim)},
        "sourceBoundsAfterAxisCorrection": {"min": list(source_lo), "max": list(source_hi), "dimensions": list(source_dim)},
        "sourceBoundsAfterScale": {"min": list(scaled_lo), "max": list(scaled_hi), "dimensions": list(dimensions(scaled_lo, scaled_hi))},
        "finalBounds": {"min": list(final_lo), "max": list(final_hi), "dimensions": list(dimensions(final_lo, final_hi))},
        "boundsMode": "raw-rest-mesh-vertices",
    }




def remove_armature_modifiers(obj: bpy.types.Object) -> None:
    for modifier in list(obj.modifiers):
        if modifier.type == "ARMATURE":
            obj.modifiers.remove(modifier)


def transfer_template_weights(mesh: bpy.types.Object, source_meshes: list[bpy.types.Object]) -> None:
    """Transfer skin weights from canonical body surfaces only.

    Nearest-bone weighting is unstable for a stylized mesh because multiple
    legs and the tail are close in world space. The source M3 already contains
    the intended region-to-bone assignments, so blend the four nearest body
    vertices and retain only the four strongest resulting influences. Helper,
    attachment, and collision meshes are intentionally excluded by the caller.
    """
    for group in list(mesh.vertex_groups):
        mesh.vertex_groups.remove(group)
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
    neighbor_count = min(4, len(samples))
    for vertex in mesh.data.vertices:
        point = mesh.matrix_world @ vertex.co
        neighbors = tree.find_n(point, neighbor_count)
        if neighbors and neighbors[0][2] <= 1e-8:
            neighbors = neighbors[:1]
        blended: dict[str, float] = {}
        for _, sample_index, distance in neighbors:
            influence = 1.0 / max(distance, 1e-6)
            for name, weight in samples[sample_index][1].items():
                blended[name] = blended.get(name, 0.0) + influence * weight
        strongest = sorted(
            ((name, weight) for name, weight in blended.items() if weight > 0.0),
            key=lambda item: item[1],
            reverse=True,
        )[:4]
        total = sum(weight for _, weight in strongest)
        if total <= 0.0:
            raise RuntimeError(f"weight transfer produced no assignment for vertex {vertex.index}")
        for name, weight in strongest:
            groups[name].add([vertex.index], weight / total, "REPLACE")


def transfer_template_surface_weights(mesh: bpy.types.Object, source_meshes: list[bpy.types.Object]) -> None:
    """Interpolate canonical skin weights from nearest template faces.

    The established body-transfer mode samples source vertices, which can blend
    across a nearby but anatomically separate limb. This isolated option uses
    barycentric interpolation at the closest face on all weighted source mesh
    pieces. It preserves the unmodified template skeleton and action data.
    """
    for group in list(mesh.vertex_groups):
        mesh.vertex_groups.remove(group)
    points: list[Vector] = []
    assignments_by_index: list[dict[str, float]] = []
    triangles: list[tuple[int, int, int]] = []
    group_names: set[str] = set()
    for source in source_meshes:
        offset = len(points)
        source_assignments: list[dict[str, float]] = []
        for vertex in source.data.vertices:
            assignments: dict[str, float] = {}
            for assignment in vertex.groups:
                if assignment.group >= len(source.vertex_groups):
                    continue
                name = source.vertex_groups[assignment.group].name
                if name not in NON_SKIN_GROUPS and assignment.weight > 0.0:
                    assignments[name] = assignment.weight
            points.append(source.matrix_world @ vertex.co)
            assignments_by_index.append(assignments)
            source_assignments.append(assignments)
            group_names.update(assignments)
        for polygon in source.data.polygons:
            indexes = list(polygon.vertices)
            for index in range(1, len(indexes) - 1):
                triangle = (indexes[0], indexes[index], indexes[index + 1])
                if any(source_assignments[vertex_index] for vertex_index in triangle):
                    triangles.append(tuple(offset + vertex_index for vertex_index in triangle))
    if not triangles or not group_names:
        raise RuntimeError("source M3 has no weighted faces for template surface transfer")
    tree = BVHTree.FromPolygons(points, triangles, all_triangles=True)
    groups = {name: mesh.vertex_groups.new(name=name) for name in sorted(group_names)}
    for vertex in mesh.data.vertices:
        closest, _normal, face_index, _distance = tree.find_nearest(mesh.matrix_world @ vertex.co)
        if closest is None or face_index is None:
            raise RuntimeError(f"surface weight transfer found no source face for vertex {vertex.index}")
        indices = triangles[face_index]
        first, second, third = (points[index] for index in indices)
        edge_first = second - first
        edge_second = third - first
        relative = closest - first
        dot_00 = edge_first.dot(edge_first)
        dot_01 = edge_first.dot(edge_second)
        dot_11 = edge_second.dot(edge_second)
        denominator = dot_00 * dot_11 - dot_01 * dot_01
        if abs(denominator) <= 1e-12:
            factors = (1.0, 0.0, 0.0)
        else:
            factor_second = (dot_11 * relative.dot(edge_first) - dot_01 * relative.dot(edge_second)) / denominator
            factor_third = (dot_00 * relative.dot(edge_second) - dot_01 * relative.dot(edge_first)) / denominator
            factors = (1.0 - factor_second - factor_third, factor_second, factor_third)
        blended: dict[str, float] = {}
        for source_index, factor in zip(indices, factors):
            for name, weight in assignments_by_index[source_index].items():
                blended[name] = blended.get(name, 0.0) + factor * weight
        strongest = sorted(
            ((name, weight) for name, weight in blended.items() if weight > 0.0),
            key=lambda item: item[1],
            reverse=True,
        )[:4]
        total = sum(weight for _name, weight in strongest)
        if total <= 0.0:
            raise RuntimeError(f"surface weight transfer produced no assignment for vertex {vertex.index}")
        for name, weight in strongest:
            groups[name].add([vertex.index], weight / total, "REPLACE")


def bind_candidate(
    candidate: bpy.types.Object,
    armature: bpy.types.Object,
    source_meshes: list[bpy.types.Object],
    surface_transfer: bool = False,
) -> str:
    remove_armature_modifiers(candidate)
    candidate.parent = armature
    candidate.matrix_parent_inverse = armature.matrix_world.inverted()
    if surface_transfer:
        transfer_template_surface_weights(candidate, source_meshes)
        method = "template-all-weighted-surfaces-nearest-face-barycentric-transfer-top4"
    else:
        transfer_template_weights(candidate, source_meshes)
        method = "template-body-nearest-vertex-transfer-top4"
    modifier = candidate.modifiers.new("AI_Zergling_Armature", "ARMATURE")
    modifier.object = armature
    weighted = sum(1 for vertex in candidate.data.vertices if vertex.groups)
    if weighted != len(candidate.data.vertices):
        raise RuntimeError(f"template weight transfer left {len(candidate.data.vertices) - weighted} unweighted vertices")
    return method


def transfer_fitted_segment_weights(mesh: bpy.types.Object, armature: bpy.types.Object, sigma: float, max_influences: int) -> str:
    """Weight every AI vertex to the nearest fitted deform-bone segments."""
    bones = [bone for bone in armature.data.bones if bone.name not in NON_SKIN_GROUPS]
    if not bones:
        raise RuntimeError("armature has no deform bones for fitted segment weights")
    if sigma <= 0.0:
        raise RuntimeError("segment sigma must be positive")
    if not 1 <= max_influences <= len(bones):
        raise RuntimeError(f"segment influences must be between 1 and {len(bones)}")
    for group in list(mesh.vertex_groups):
        mesh.vertex_groups.remove(group)
    groups = {bone.name: mesh.vertex_groups.new(name=bone.name) for bone in bones}
    inverse = armature.matrix_world.inverted()
    sigma_sq_twice = 2.0 * sigma * sigma
    for vertex in mesh.data.vertices:
        point = inverse @ (mesh.matrix_world @ vertex.co)
        scored: list[tuple[float, str]] = []
        for bone in bones:
            start = bone.head_local
            delta = bone.tail_local - start
            denominator = delta.length_squared
            amount = (point - start).dot(delta) / denominator if denominator > 1e-12 else 0.0
            amount = max(0.0, min(1.0, amount))
            closest = start + delta * amount
            scored.append(((point - closest).length_squared, bone.name))
        nearest = sorted(scored)[:max_influences]
        weights = [(name, math.exp(-distance_sq / sigma_sq_twice)) for distance_sq, name in nearest]
        total = sum(weight for _, weight in weights)
        if total <= 0.0:
            raise RuntimeError(f"fitted segment weighting produced no assignment for vertex {vertex.index}")
        for name, weight in weights:
            groups[name].add([vertex.index], weight / total, "REPLACE")
    return f"fitted-rest-segment-softmax-top{max_influences}-sigma-{sigma:g}"
def candidate_group_centers(mesh: bpy.types.Object, armature: bpy.types.Object) -> dict[str, Vector]:
    """Return weighted AI-surface centers in armature-local coordinates."""
    totals: dict[str, Vector] = {}
    weights: dict[str, float] = {}
    inverse = armature.matrix_world.inverted()
    for vertex in mesh.data.vertices:
        point = inverse @ (mesh.matrix_world @ vertex.co)
        for assignment in vertex.groups:
            if assignment.group >= len(mesh.vertex_groups) or assignment.weight <= 0.0:
                continue
            name = mesh.vertex_groups[assignment.group].name
            totals[name] = totals.get(name, Vector()) + point * assignment.weight
            weights[name] = weights.get(name, 0.0) + assignment.weight
    return {name: totals[name] / weights[name] for name in totals if weights[name] > 0.0}


def candidate_group_terminal(mesh: bpy.types.Object, armature: bpy.types.Object, group_name: str, direction: Vector) -> Vector:
    """Find the AI surface endpoint in a bone-chain direction."""
    group = mesh.vertex_groups.get(group_name)
    if group is None:
        raise RuntimeError(f"candidate has no skin group {group_name}")
    inverse = armature.matrix_world.inverted()
    points = [inverse @ (mesh.matrix_world @ vertex.co) for vertex in mesh.data.vertices if any(assignment.group == group.index and assignment.weight > 0.0 for assignment in vertex.groups)]
    if not points:
        raise RuntimeError(f"candidate skin group {group_name} has no vertices")
    axis = direction.normalized() if direction.length > 1e-8 else Vector((0.0, 1.0, 0.0))
    return max(points, key=lambda point: point.dot(axis))

def candidate_surface_terminal(mesh: bpy.types.Object, armature: bpy.types.Object, origin: Vector, direction: Vector) -> Vector:
    """Extend a missing transferred group along its local chain without selecting an unrelated appendage."""
    axis = direction.normalized() if direction.length > 1e-8 else Vector((0.0, 1.0, 0.0))
    inverse = armature.matrix_world.inverted()
    points = [inverse @ (mesh.matrix_world @ vertex.co) for vertex in mesh.data.vertices]

    def score(point: Vector) -> float:
        offset = point - origin
        along = offset.dot(axis)
        radial = (offset - axis * along).length
        return along - radial * 1.5

    return max(points, key=score)
def candidate_group_nearest(mesh: bpy.types.Object, armature: bpy.types.Object, group_name: str, target: Vector) -> Vector:
    """Return the candidate surface point in a group nearest a chain joint."""
    group = mesh.vertex_groups.get(group_name)
    if group is None:
        raise RuntimeError(f"candidate has no skin group {group_name}")
    inverse = armature.matrix_world.inverted()
    points = [inverse @ (mesh.matrix_world @ vertex.co) for vertex in mesh.data.vertices if any(assignment.group == group.index and assignment.weight > 0.0 for assignment in vertex.groups)]
    if not points:
        raise RuntimeError(f"candidate skin group {group_name} has no vertices")
    return min(points, key=lambda point: (point - target).length_squared)



def capture_action_deltas(armature: bpy.types.Object, actions: dict[str, bpy.types.Action]) -> dict[str, dict[int, dict[str, Matrix]]]:
    """Capture each clip's local pose basis for every canonical bone."""
    armature.animation_data_create()
    saved_action = armature.animation_data.action
    saved_frame = bpy.context.scene.frame_current
    captured: dict[str, dict[int, dict[str, Matrix]]] = {}
    try:
        for requested, action in actions.items():
            armature.animation_data.action = action
            start = int(action.frame_range[0])
            end = int(action.frame_range[1])
            bpy.context.scene.frame_set(start)
            bpy.context.view_layer.update()
            captured[requested] = {}
            for frame in range(start, end + 1):
                bpy.context.scene.frame_set(frame)
                bpy.context.view_layer.update()
                captured[requested][frame] = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
    finally:
        armature.animation_data.action = saved_action
        bpy.context.scene.frame_set(saved_frame)
        bpy.context.view_layer.update()
    return captured

def capture_action_world_deltas(
    armature: bpy.types.Object,
    actions: dict[str, bpy.types.Action],
    template_rest: dict[str, dict[str, Any]],
) -> dict[str, dict[int, dict[str, Matrix]]]:
    """Capture each action as a per-bone delta from the canonical rest pose."""
    armature.animation_data_create()
    saved_action = armature.animation_data.action
    saved_frame = bpy.context.scene.frame_current
    captured: dict[str, dict[int, dict[str, Matrix]]] = {}
    try:
        for requested, action in actions.items():
            armature.animation_data.action = action
            start = int(action.frame_range[0])
            end = int(action.frame_range[1])
            captured[requested] = {}
            for frame in range(start, end + 1):
                bpy.context.scene.frame_set(frame)
                bpy.context.view_layer.update()
                captured[requested][frame] = {
                    bone.name: armature.pose.bones[bone.name].matrix.copy() @ template_rest[bone.name]["matrix"].inverted()
                    for bone in armature.data.bones
                    if bone.name in armature.pose.bones and bone.name in template_rest
                }
    finally:
        armature.animation_data.action = saved_action
        bpy.context.scene.frame_set(saved_frame)
        bpy.context.view_layer.update()
    return captured


def dampen_world_delta(delta: Matrix, amount: float) -> Matrix:
    if not 0.0 <= amount <= 1.0:
        raise RuntimeError("animation scale must be between 0 and 1")
    if amount == 1.0:
        return delta.copy()
    location, rotation, stretch = delta.decompose()
    blended_rotation = Quaternion((1.0, 0.0, 0.0, 0.0)).slerp(rotation, amount)
    blended_scale = Vector((1.0, 1.0, 1.0)).lerp(stretch, amount)
    result = blended_rotation.to_matrix().to_4x4() @ Matrix.Diagonal(
        (blended_scale.x, blended_scale.y, blended_scale.z, 1.0)
    )
    result.translation = location * amount
    return result

def retarget_world_deltas_to_new_rest(
    armature: bpy.types.Object,
    actions: dict[str, bpy.types.Action],
    deltas: dict[str, dict[int, dict[str, Matrix]]],
    animation_scale: float,
) -> dict[str, Any]:
    """Bake canonical world-space motion deltas onto fitted rest bones."""
    armature.animation_data_create()
    saved_action = armature.animation_data.action
    saved_frame = bpy.context.scene.frame_current
    armature.animation_data.action = None
    bone_order = [bone.name for bone in armature.data.bones]
    bone_order.sort(key=lambda name: len(list(iter_parent_names(armature.data.bones[name]))))
    baked_frames = 0
    try:
        for requested, action in actions.items():
            for fcurve in list(action.fcurves):
                action.fcurves.remove(fcurve)
            armature.animation_data.action = action
            for frame, bone_deltas in deltas[requested].items():
                bpy.context.scene.frame_set(frame)
                for name in bone_order:
                    pose_bone = armature.pose.bones.get(name)
                    rest = armature.data.bones.get(name)
                    delta = bone_deltas.get(name)
                    if pose_bone is None or rest is None or delta is None:
                        continue
                    pose_bone.matrix = dampen_world_delta(delta, animation_scale) @ rest.matrix_local
                bpy.context.view_layer.update()
                for name in bone_order:
                    pose_bone = armature.pose.bones.get(name)
                    if pose_bone is None:
                        continue
                    pose_bone.keyframe_insert(data_path="location", frame=frame, group=name)
                    if pose_bone.rotation_mode == "QUATERNION":
                        pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame, group=name)
                    elif pose_bone.rotation_mode == "AXIS_ANGLE":
                        pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame, group=name)
                    else:
                        pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame, group=name)
                    pose_bone.keyframe_insert(data_path="scale", frame=frame, group=name)
                baked_frames += 1
    finally:
        armature.animation_data.action = saved_action
        bpy.context.scene.frame_set(saved_frame)
        bpy.context.view_layer.update()
    return {"method": "world-space-delta-retarget", "animationScale": animation_scale, "clips": len(actions), "bakedFrames": baked_frames}


def iter_parent_names(bone: bpy.types.Bone):
    parent = bone.parent
    while parent is not None:
        yield parent.name
        parent = parent.parent


def retarget_actions_to_new_rest(armature: bpy.types.Object, actions: dict[str, bpy.types.Action], deltas: dict[str, dict[int, dict[str, Matrix]]]) -> dict[str, Any]:
    """Bake source local pose bases onto the fitted rest skeleton."""
    armature.animation_data_create()
    saved_action = armature.animation_data.action
    saved_frame = bpy.context.scene.frame_current
    armature.animation_data.action = None
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    bone_order = [bone.name for bone in armature.data.bones]
    baked_frames = 0
    try:
        for requested, action in actions.items():
            for fcurve in list(action.fcurves):
                action.fcurves.remove(fcurve)
            armature.animation_data.action = action
            for frame, bone_bases in deltas[requested].items():
                bpy.context.scene.frame_set(frame)
                for name in bone_order:
                    pose_bone = armature.pose.bones.get(name)
                    basis = bone_bases.get(name)
                    if pose_bone is None or basis is None:
                        continue
                    pose_bone.matrix_basis = basis.copy()
                bpy.context.view_layer.update()
                for name in bone_order:
                    pose_bone = armature.pose.bones.get(name)
                    if pose_bone is None:
                        continue
                    pose_bone.keyframe_insert(data_path="location", frame=frame, group=name)
                    if pose_bone.rotation_mode == "QUATERNION":
                        pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame, group=name)
                    elif pose_bone.rotation_mode == "AXIS_ANGLE":
                        pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame, group=name)
                    else:
                        pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame, group=name)
                    pose_bone.keyframe_insert(data_path="scale", frame=frame, group=name)
                baked_frames += 1
    finally:
        armature.animation_data.action = saved_action
        bpy.context.scene.frame_set(saved_frame)
        bpy.context.view_layer.update()
    return {"method": "local-pose-basis-retarget", "clips": len(actions), "bakedFrames": baked_frames}


def retarget_deform_chains_to_candidate(armature: bpy.types.Object, mesh: bpy.types.Object) -> dict[str, Any]:
    """Move the complete deform skeleton onto transferred AI skin regions.

    The canonical action contract is retained, but the AI mesh has different
    body and appendage proportions. Keeping the old rest bones would leave
    visible bones floating outside the generated model. Each chain follows
    transferred skin-group centers, with terminal bones ending at the surface.
    """
    centers = candidate_group_centers(mesh, armature)
    chains = [
        ("Bone_Tail", ["Bone_Tail", "Bone_Tail 01", "Bone_Tail 02", "Bone_Tail 03", "Bone01"], "Bone_Pelvis"),
        ("Bone_Leg Right Front", ["Bone_Leg Right Front", "Bone_Leg Right Front 01", "Bone_Foot Right Front"], "Bone_Chest"),
        ("Bone_Leg Left Front", ["Bone_Leg Left Front", "Bone_Leg Left Front 01", "Bone_Foot Left Front"], "Bone_Chest"),
        ("Bone_Leg Right Rear", ["Bone_Leg Right Rear", "Bone_Leg Right Rear 01", "Bone_Leg Right Rear 02", "Bone_Foot Right Rear", "Bone_Foot Right Rear 01"], "Bone_Pelvis"),
        ("Bone_Leg Left Rear", ["Bone_Leg Left Rear", "Bone_Leg Left Rear 01", "Bone_Leg Left Rear 02", "Bone_Foot Left Rear", "Bone_Foot Left Rear 01"], "Bone_Pelvis"),
    ]
    armature.animation_data_create()
    saved_action = armature.animation_data.action
    armature.animation_data.action = None
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edited = 0
        core_points = [centers["Bone_Pelvis"], centers["Bone_Chest"], centers["Bone_Head"]]
        for index, bone_name in enumerate(("Bone_Chest", "Bone_Head")):
            bone = armature.data.edit_bones.get(bone_name)
            if bone is None:
                continue
            bone.head = core_points[index]
            bone.tail = core_points[index + 1]
            edited += 1
        for _, bone_names, anchor_name in chains:
            group_names = [name for name in bone_names if name in centers]
            if not group_names:
                continue
            anchor = centers.get(anchor_name)
            if anchor is None:
                raise RuntimeError(f"candidate has no anchor skin group {anchor_name}")
            points = [anchor]
            for group_name in group_names:
                nearest = candidate_group_nearest(mesh, armature, group_name, points[-1])
                points.append(nearest.lerp(centers[group_name], 0.35))
            if len(group_names) < len(bone_names):
                direction = points[-1] - points[-2]
                points.append(candidate_group_terminal(mesh, armature, group_names[-1], direction))
            for index, bone_name in enumerate(bone_names):
                bone = armature.data.edit_bones.get(bone_name)
                if bone is None or index + 1 >= len(points):
                    continue
                bone.head = points[index]
                bone.tail = points[index + 1]
                edited += 1
        bpy.context.view_layer.update()
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        armature.animation_data.action = saved_action
        bpy.context.scene.frame_set(0)
        bpy.context.view_layer.update()
    return {"method": "candidate-skin-group-chain-retarget", "chains": len(chains), "bonesRetargeted": edited, "coreBonesRetargeted": ["Bone_Pelvis", "Bone_Chest", "Bone_Head"]}

def fit_full_skeleton_to_candidate(
    armature: bpy.types.Object,
    mesh: bpy.types.Object,
    source_chain_landmarks: bool = False,
) -> dict[str, Any]:
    """Fit every visible template bone to the candidate's current skin regions.

    The default iterative strategy runs again after segment weights are
    generated. The optional source-chain strategy preserves the template
    group order and reaches the source-transferred terminal surface before
    segment weighting makes those regional groups self-referential.
    """
    centers = candidate_group_centers(mesh, armature)
    required = {
        "Bone_Pelvis", "Bone_Chest", "Bone_Head",
        "Bone_Tail", "Bone_Tail 01", "Bone_Tail 02", "Bone_Tail 03", "Bone01",
        "Bone_Leg Right Front", "Bone_Leg Right Front 01", "Bone_Foot Right Front",
        "Bone_Leg Left Front", "Bone_Leg Left Front 01", "Bone_Foot Left Front",
        "Bone_Leg Right Rear", "Bone_Leg Right Rear 01", "Bone_Leg Right Rear 02",
        "Bone_Foot Right Rear", "Bone_Foot Right Rear 01",
        "Bone_Leg Left Rear", "Bone_Leg Left Rear 01", "Bone_Leg Left Rear 02",
        "Bone_Foot Left Rear", "Bone_Foot Left Rear 01",
    }
    original = {
        bone.name: (bone.head_local.copy(), bone.tail_local.copy())
        for bone in armature.data.bones
    }
    inverse = armature.matrix_world.inverted()
    surface_points = [inverse @ (mesh.matrix_world @ vertex.co) for vertex in mesh.data.vertices]
    populated = {mesh.vertex_groups[assignment.group].name for vertex in mesh.data.vertices for assignment in vertex.groups if assignment.group < len(mesh.vertex_groups) and assignment.weight > 0.0}
    missing = sorted(name for name in required if name not in centers)
    for name in missing:
        head, tail = original[name]
        target = (head + tail) / 2.0
        centers[name] = min(surface_points, key=lambda point: (point - target).length_squared)
    chains = [
        (["Bone_Tail", "Bone_Tail 01", "Bone_Tail 02", "Bone_Tail 03", "Bone01"], "Bone_Pelvis"),
        (["Bone_Leg Right Front", "Bone_Leg Right Front 01", "Bone_Foot Right Front"], "Bone_Chest"),
        (["Bone_Leg Left Front", "Bone_Leg Left Front 01", "Bone_Foot Left Front"], "Bone_Chest"),
        (["Bone_Leg Right Rear", "Bone_Leg Right Rear 01", "Bone_Leg Right Rear 02", "Bone_Foot Right Rear", "Bone_Foot Right Rear 01"], "Bone_Pelvis"),
        (["Bone_Leg Left Rear", "Bone_Leg Left Rear 01", "Bone_Leg Left Rear 02", "Bone_Foot Left Rear", "Bone_Foot Left Rear 01"], "Bone_Pelvis"),
    ]
    armature.animation_data_create()
    saved_action = armature.animation_data.action
    armature.animation_data.action = None
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edited = 0
        pelvis = centers["Bone_Pelvis"]
        chest = centers["Bone_Chest"]
        head = centers["Bone_Head"]
        core_centers = [pelvis, chest, head]
        core_points = [
            core_centers[0] - (core_centers[1] - core_centers[0]) * 0.5,
            core_centers[0].lerp(core_centers[1], 0.5),
            core_centers[1].lerp(core_centers[2], 0.5),
            core_centers[2] + (core_centers[2] - core_centers[1]) * 0.5,
        ]
        for index, name in enumerate(("Bone_Pelvis", "Bone_Chest", "Bone_Head")):
            bone = armature.data.edit_bones.get(name)
            if bone is not None:
                bone.head = core_points[index]
                bone.tail = core_points[index + 1]
                edited += 1
        for bone_names, anchor_name in chains:
            anchor = centers[anchor_name]
            chain_centers = [centers[name] for name in bone_names]
            if source_chain_landmarks:
                direction = chain_centers[-1] - chain_centers[-2] if len(chain_centers) > 1 else chain_centers[0] - anchor
                terminal_group = mesh.vertex_groups.get(bone_names[-1])
                terminal = (
                    candidate_group_terminal(mesh, armature, bone_names[-1], direction)
                    if terminal_group is not None
                    else candidate_surface_terminal(mesh, armature, chain_centers[-1], direction)
                )
                points = [anchor, *chain_centers[:-1], terminal]
            else:
                chain_centers.sort(key=lambda point: (point - anchor).length_squared)
                centers_on_chain = [anchor, *chain_centers]
                points = [centers_on_chain[0].lerp(centers_on_chain[1], 0.5)]
                for index in range(1, len(centers_on_chain) - 1):
                    points.append(centers_on_chain[index].lerp(centers_on_chain[index + 1], 0.5))
                points.append(centers_on_chain[-2].lerp(centers_on_chain[-1], 0.15))
            for index, bone_name in enumerate(bone_names):
                bone = armature.data.edit_bones.get(bone_name)
                if bone is None:
                    continue
                bone.head = points[index]
                bone.tail = points[index + 1]
                edited += 1

        lo, hi = raw_bounds([mesh])
        envelope_center = (lo + hi) / 2.0
        envelope_bottom = Vector((envelope_center.x, envelope_center.y, lo.z))
        envelope_top = Vector((envelope_center.x, envelope_center.y, hi.z))

        def short_helper(name: str, anchor: Vector, axis: Vector, length: float = 0.04) -> None:
            bone = armature.data.edit_bones.get(name)
            if bone is None:
                return
            unit = axis.normalized() if axis.length > 1e-8 else Vector((1.0, 0.0, 0.0))
            bone.head = anchor
            bone.tail = anchor + unit * length

        for names, axis in (
            (("BoneStockR01", "BoneStockR02", "BoneStockR03"), Vector((1.0, 0.0, 0.0))),
            (("BoneStockL01", "BoneStockL02", "BoneStockL03"), Vector((-1.0, 0.0, 0.0))),
        ):
            for index, name in enumerate(names):
                short_helper(name, pelvis + axis * (0.025 * index), axis, 0.025)
        for name in ("Ref_Head",):
            parent = armature.data.edit_bones.get("Bone_Head")
            short_helper(name, parent.tail if parent else head, Vector((1.0, 0.0, 0.0)))
        for name, parent_name in (("Ref_Weapon Right", "BoneStockR03"), ("Ref_Weapon Left", "BoneStockL03")):
            parent = armature.data.edit_bones.get(parent_name)
            short_helper(name, parent.tail if parent else pelvis, Vector((0.0, 1.0, 0.0)), 0.05)
        for name in ("HitTestFuzzy02", "HitTestFuzzy01", "HitTestTight", "HitTestFuzzy", "Ref_Center", "Vol_Target"):
            parent = armature.data.edit_bones.get("Bone_Pelvis")
            short_helper(name, parent.tail if parent else pelvis, Vector((1.0, 0.0, 0.0)), 0.04)
        short_helper("Dummy01", envelope_bottom, Vector((0.0, 0.0, 1.0)), 0.04)
        short_helper("Ref_Origin", envelope_bottom, Vector((1.0, 0.0, 0.0)), 0.04)
        short_helper("Ref_Hardpoint", pelvis, Vector((0.0, 1.0, 0.0)), 0.04)
        short_helper("Unit_Zerg_Zergling_Konker_02", head, Vector((1.0, 0.0, 0.0)), 0.04)
        short_helper("Ref_Overhead", envelope_top, Vector((1.0, 0.0, 0.0)), 0.04)
        edited += 20
        bpy.context.view_layer.update()
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        armature.animation_data.action = saved_action
        bpy.context.scene.frame_set(0)
        bpy.context.view_layer.update()
    return {
        "method": "source-group-ordered-terminal-fit" if source_chain_landmarks else "all-deform-chains-and-helper-envelope-fit",
        "chains": len(chains),
        "bonesRetargeted": edited,
        "deformGroupsUsed": len(required),
        "helperPolicy": "short-parent-or-envelope-attached",
        "originalBoneEndpointsPreservedIn": "authoring source blend",
    }

def capture_template_rest(armature: bpy.types.Object) -> dict[str, dict[str, Any]]:
    return {
        bone.name: {
            "head": bone.head_local.copy(),
            "tail": bone.tail_local.copy(),
            "matrix": bone.matrix_local.copy(),
        }
        for bone in armature.data.bones
    }


def remap_candidate_from_fitted_rest(
    mesh: bpy.types.Object,
    armature: bpy.types.Object,
    template_rest: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Map fitted-rig rest vertices back onto the canonical template rig.

    Fitting the armature alone makes the animation contract follow the AI mesh,
    but does not produce a mesh bound to the original SC2 skeleton. For every
    vertex, blend the fitted-to-template rest transform for its positive skin
    influences, then restore the canonical bone endpoints. The final modifier
    therefore uses the untouched template actions with a mesh whose bind space
    has already been corrected.
    """
    fitted = {bone.name: bone.matrix_local.copy() for bone in armature.data.bones}
    armature_inverse = armature.matrix_world.inverted()
    mesh_to_armature = armature_inverse @ mesh.matrix_world
    armature_to_mesh = mesh_to_armature.inverted()
    transformed = 0
    for vertex in mesh.data.vertices:
        point = mesh_to_armature @ vertex.co
        output = Vector()
        total = 0.0
        for assignment in vertex.groups:
            if assignment.group >= len(mesh.vertex_groups) or assignment.weight <= 0.0:
                continue
            name = mesh.vertex_groups[assignment.group].name
            source = fitted.get(name)
            target = template_rest.get(name)
            if source is None or target is None:
                continue
            output += (target["matrix"] @ source.inverted() @ point) * assignment.weight
            total += assignment.weight
        if total > 1e-8:
            vertex.co = armature_to_mesh @ (output / total)
            transformed += 1
    bpy.context.view_layer.update()
    return {
        "method": "weighted-fitted-rest-to-template-rest-remap",
        "transformedVertices": transformed,
        "totalVertices": len(mesh.data.vertices),
        "templateBoneCount": len(template_rest),
    }


def restore_template_rest(armature: bpy.types.Object, template_rest: dict[str, dict[str, Any]]) -> None:
    armature.animation_data_create()
    saved_action = armature.animation_data.action
    armature.animation_data.action = None
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        for name, values in template_rest.items():
            bone = armature.data.edit_bones.get(name)
            if bone is None:
                continue
            bone.head = values["head"]
            bone.tail = values["tail"]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        armature.animation_data.action = saved_action
        bpy.context.view_layer.update()




def copy_vertex_groups(source: bpy.types.Object, target: bpy.types.Object) -> None:
    for group in list(target.vertex_groups):
        target.vertex_groups.remove(group)
    for source_group in source.vertex_groups:
        target_group = target.vertex_groups.new(name=source_group.name)
        for vertex in source.data.vertices:
            for assignment in vertex.groups:
                if assignment.group == source_group.index:
                    target_group.add([vertex.index], assignment.weight, "REPLACE")
                    break


def make_export_mesh(candidate: bpy.types.Object, template: bpy.types.Object, armature: bpy.types.Object) -> bpy.types.Object:
    export_mesh = template.copy()
    export_mesh.data = candidate.data.copy()
    export_mesh.name = "AI_Zergling_SC2_Mesh"
    bpy.context.scene.collection.objects.link(export_mesh)
    export_mesh.parent = armature
    export_mesh.location = candidate.location
    export_mesh.rotation_euler = candidate.rotation_euler
    export_mesh.scale = candidate.scale
    copy_vertex_groups(candidate, export_mesh)
    remove_armature_modifiers(export_mesh)
    modifier = export_mesh.modifiers.new("AI_Zergling_Armature", "ARMATURE")
    modifier.object = armature
    try:
        export_mesh.m3_mesh_export = True
        export_mesh.m3_mesh_uv0 = export_mesh.data.uv_layers[0].name if export_mesh.data.uv_layers else ""
    except AttributeError as exc:
        raise RuntimeError("M3Studio mesh properties unavailable on export mesh") from exc
    export_mesh.hide_viewport = False
    return export_mesh


def hide_template_meshes(meshes: list[bpy.types.Object], visible: bpy.types.Object) -> None:
    for mesh in meshes:
        mesh.hide_render = mesh != visible
        mesh.hide_viewport = mesh != visible
        try:
            mesh.m3_mesh_export = False
        except AttributeError:
            pass


def point_camera(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def setup_render(scene: bpy.types.Scene, meshes: list[bpy.types.Object], frames: list[int]) -> None:
    lo, hi = bounds(meshes)
    center = (lo + hi) / 2
    extent = max(hi - lo)
    camera_data = bpy.data.cameras.new("AI_SC2_Camera")
    camera = bpy.data.objects.new("AI_SC2_Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + Vector((1.65, -2.25, 1.2)).normalized() * extent * 2.15
    camera_data.lens = 58
    point_camera(camera, center)
    scene.camera = camera
    for name, offset, energy, size in (
        ("AI_Key", (1.5, -1.4, 2.0), 130.0, 2.8),
        ("AI_Fill", (-1.6, -0.8, 0.7), 34.0, 3.0),
        ("AI_Rim", (0.5, 1.6, 1.6), 65.0, 2.6),
    ):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = extent * size
        light_data.color = (1.0, 1.0, 1.0)
        light = bpy.data.objects.new(name, light_data)
        scene.collection.objects.link(light)
        light.location = center + Vector(offset).normalized() * extent * 1.8
        point_camera(light, center)
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.012, 0.012, 0.012)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def render_midpoints(scene: bpy.types.Scene, armature: bpy.types.Object, actions: dict[str, bpy.types.Action], mesh: bpy.types.Object, output_dir: Path) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_render(scene, [mesh], [int((a.frame_range[0] + a.frame_range[1]) / 2) for a in actions.values()])
    results = []
    for requested in REQUIRED_ACTIONS:
        action = actions[requested]
        armature.animation_data.action = action
        frame = int((action.frame_range[0] + action.frame_range[1]) / 2)
        scene.frame_set(frame)
        output = output_dir / f"{requested.lower()}-mid.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        results.append({"action": requested, "resolvedAction": action.name, "frame": frame, "path": str(output.relative_to(ROOT)).replace("\\", "/")})
    return results


def image_material(name: str, diffuse: Path | None, normal: Path | None) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.72
    if diffuse and path(diffuse).is_file():
        image = bpy.data.images.load(str(path(diffuse)), check_existing=True)
        image.colorspace_settings.name = "sRGB"
        node = nodes.new("ShaderNodeTexImage")
        node.image = image
        links.new(node.outputs["Color"], shader.inputs["Base Color"])
    if normal and path(normal).is_file():
        image = bpy.data.images.load(str(path(normal)), check_existing=True)
        image.colorspace_settings.name = "Non-Color"
        node = nodes.new("ShaderNodeTexImage")
        node.image = image
        normal_node = nodes.new("ShaderNodeNormalMap")
        normal_node.inputs["Strength"].default_value = 0.35
        links.new(node.outputs["Color"], normal_node.inputs["Color"])
        links.new(normal_node.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def integrate(args: argparse.Namespace) -> None:
    out_dir = path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = path(args.candidate_glb)
    source_path = path(args.source_m3)
    clear_scene()
    register_m3studio(args.addon_dir)
    armature = import_m3(source_path)
    actions = actions_for(armature)
    source_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not source_meshes:
        raise RuntimeError("source M3 imported without meshes")
    source_blend = out_dir / "zergling-ai-w4-source.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(source_blend))

    bpy.ops.import_scene.gltf(filepath=str(candidate_path))
    candidate_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith("node")]
    if len(candidate_objects) != 1:
        raise RuntimeError(f"expected one imported AI mesh, got {[obj.name for obj in candidate_objects]}")
    candidate = candidate_objects[0]
    try:
        candidate.m3_mesh_export = False
    except AttributeError:
        pass
    alignment_body = select_alignment_body(source_meshes)
    alignment = align_candidate(candidate, [alignment_body])
    binding_meshes = source_meshes if args.weight_mode in {"all-surface", "surface-transfer"} or args.bone_fit_mode == "surface-fitted" else [alignment_body]
    weighting_method = bind_candidate(candidate, armature, binding_meshes, surface_transfer=args.weight_mode == "surface-transfer")
    template_rest = capture_template_rest(armature)
    if args.bone_fit_mode == "surface-fitted":
        animation_deltas = capture_action_world_deltas(armature, actions, template_rest)
    elif args.bone_fit_mode == "skin-groups":
        animation_deltas = capture_action_deltas(armature, actions)
    else:
        animation_deltas = None
    rest_remap = {"method": "not-applied"}
    if args.bone_fit_mode == "surface-fitted":
        source_chain_landmarks = args.surface_fit_strategy == "source-chain-landmarks"
        retargeting = fit_full_skeleton_to_candidate(armature, candidate, source_chain_landmarks)
        if args.weight_mode == "fitted-segments":
            weighting_method = transfer_fitted_segment_weights(candidate, armature, args.segment_sigma, args.segment_influences)
            if source_chain_landmarks:
                retargeting["refinement"] = {
                    "method": "not-applied",
                    "reason": "preserve source-group terminal landmarks instead of refitting to generated segment weights",
                }
            else:
                refinement = fit_full_skeleton_to_candidate(armature, candidate)
                weighting_method = transfer_fitted_segment_weights(candidate, armature, args.segment_sigma, args.segment_influences)
                retargeting["refinement"] = refinement
    elif args.bone_fit_mode == "skin-groups":
        retargeting = retarget_deform_chains_to_candidate(armature, candidate)
    else:
        retargeting = {"method": "template-rest-skeleton", "chains": 0, "bonesRetargeted": 0, "coreBonesRetargeted": []}
    if args.bone_fit_mode == "surface-fitted":
        animation_retargeting = retarget_world_deltas_to_new_rest(armature, actions, animation_deltas, args.animation_scale)
    elif args.bone_fit_mode == "skin-groups":
        animation_retargeting = retarget_actions_to_new_rest(armature, actions, animation_deltas)
    else:
        animation_retargeting = {"method": "template-action-preserved", "clips": 0, "bakedFrames": 0}
    if args.weight_mode == "fitted-segments" and args.bone_fit_mode != "surface-fitted":
        weighting_method = transfer_fitted_segment_weights(candidate, armature, args.segment_sigma, args.segment_influences)
    template = alignment_body
    export_mesh = make_export_mesh(candidate, template, armature)
    export_mesh.hide_render = True
    hide_template_meshes(source_meshes, candidate)
    scene = bpy.context.scene
    scene.frame_set(int((actions["Stand"].frame_range[0] + actions["Stand"].frame_range[1]) / 2))
    preview_dir = out_dir / "w4-ai-textured-previews"
    preview_outputs = render_midpoints(scene, armature, actions, candidate, preview_dir)
    reset_pose(armature)
    scene.frame_set(int((actions["Stand"].frame_range[0] + actions["Stand"].frame_range[1]) / 2))
    blend_path = out_dir / "zergling-ai-w4-rigged.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    m3_path = out_dir / "zergling-ai-sc2-candidate.m3"
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    result = bpy.ops.m3.export(
        filepath=str(m3_path),
        output_anims=True,
        section_reuse_mode="EXPLICIT",
        cull_unused_bones=False,
        cull_material_layers=True,
        use_only_max_bounds=True,
    )
    if not m3_path.is_file() or m3_path.stat().st_size == 0:
        raise RuntimeError(f"M3 export produced no file; operator result={result}")
    report = {
        "schemaVersion": 1,
        "workflow": "offline-sc2-ai-mesh-w4-w5.v1",
        "status": "W4_STATIC_BINDING_PASS_VISUAL_REVIEW_REQUIRED_W5_EXPORT_PENDING_REIMPORT",
        "evidenceType": "static",
        "source": {"m3": str(source_path.relative_to(ROOT)).replace("\\", "/"), "aiGlb": str(candidate_path.relative_to(ROOT)).replace("\\", "/")},
        "w4": {
            "authoringBlend": str(blend_path.relative_to(ROOT)).replace("\\", "/"),
            "sourceAuthoringBlend": str(source_blend.relative_to(ROOT)).replace("\\", "/"),
            "boneCount": len(armature.data.bones),
            "sourceMeshCount": len(source_meshes),
            "weighting": {"method": weighting_method, "sourceMeshes": [mesh.name for mesh in binding_meshes], "vertexGroups": len(candidate.vertex_groups), "maxPositiveInfluences": max(sum(1 for assignment in vertex.groups if assignment.weight > 0.0) for vertex in candidate.data.vertices), "armatureModifier": any(mod.type == "ARMATURE" and mod.object == armature for mod in candidate.modifiers)},
            "weightMode": args.weight_mode,
            "surfaceFitStrategy": args.surface_fit_strategy if args.bone_fit_mode == "surface-fitted" else None,
            "alignmentBodyMesh": alignment_body.name,
            "animationRetargeting": animation_retargeting,
            "alignmentBodyVertices": len(alignment_body.data.vertices),
            "alignment": alignment,
            "restPoseRetargeting": retargeting,
            "restSpaceRemap": rest_remap,
            "candidateMesh": candidate.name,
            "candidateVertices": len(candidate.data.vertices),
            "actions": {name: {"action": action.name, "frames": [int(action.frame_range[0]), int(action.frame_range[1])]} for name, action in actions.items()},
            "previewRenders": preview_outputs,
        },
        "w5": {"candidateM3": str(m3_path.relative_to(ROOT)).replace("\\", "/"), "fileBytes": m3_path.stat().st_size, "status": "EXPORTED_PENDING_FRESH_REIMPORT"},
        "scopeBoundary": "Offline Blender/M3Studio only. No SC2 Previewer, Actor, map, mod, or in-game runtime evidence.",
    }
    report_path = out_dir / "w4-w5-export-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("AI_MESH_M3_EXPORT_READY=" + str(report_path))


def verify(args: argparse.Namespace) -> None:
    out_dir = path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clear_scene()
    register_m3studio(args.addon_dir)
    armature = import_m3(path(args.candidate_m3))
    actions = actions_for(armature)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("reimported M3 has no mesh")
    material = image_material("AI_SC2_OfflinePreview", args.diffuse, args.normal)
    for mesh in meshes:
        mesh.data.materials.clear()
        mesh.data.materials.append(material)
        mesh.hide_render = False
    preview_dir = out_dir / "w5-reimport-previews"
    preview_outputs = render_midpoints(bpy.context.scene, armature, actions, meshes[0], preview_dir)
    reset_pose(armature)
    blend_path = out_dir / "zergling-ai-sc2-reimport.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    report = {
        "schemaVersion": 1,
        "workflow": "offline-sc2-ai-mesh-w5-reimport.v1",
        "status": "PASS",
        "evidenceType": "static",
        "candidateM3": str(path(args.candidate_m3).relative_to(ROOT)).replace("\\", "/"),
        "reimport": {
            "blend": str(blend_path.relative_to(ROOT)).replace("\\", "/"),
            "armature": armature.name,
            "boneCount": len(armature.data.bones),
            "meshCount": len(meshes),
            "meshes": [{"name": mesh.name, "vertices": len(mesh.data.vertices), "triangles": sum(len(poly.vertices) - 2 for poly in mesh.data.polygons), "uvLayers": len(mesh.data.uv_layers), "vertexGroups": len(mesh.vertex_groups)} for mesh in meshes],
            "actions": {name: {"action": action.name, "frames": [int(action.frame_range[0]), int(action.frame_range[1])]} for name, action in actions.items()},
            "previewRenders": preview_outputs,
            "previewTextures": {"diffuse": str(path(args.diffuse).relative_to(ROOT)).replace("\\", "/") if args.diffuse else None, "normal": str(path(args.normal).relative_to(ROOT)).replace("\\", "/") if args.normal else None},
        },
        "scopeBoundary": "Fresh Blender/M3Studio re-import and render evidence only. SC2 Previewer, Actor, and in-game runtime remain unverified.",
    }
    report_path = out_dir / "w5-reimport-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("AI_MESH_M3_REIMPORT_READY=" + str(report_path))


def main() -> None:
    args = parse_args()
    if bpy.app.background:
        raise RuntimeError("This runner requires graphical Blender; M3Studio GPU drawing is unavailable in background mode")
    try:
        if args.mode == "integrate":
            integrate(args)
        else:
            verify(args)
    finally:
        bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
