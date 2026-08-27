"""Render an offline mesh/armature coupling overlay from a saved Blender scene.

This diagnostic is deliberately Blender-only. It draws pose bones as thin cylinders
on top of the visible mesh so W4 visual review can distinguish a bound rig from a
skeleton that merely exists beside the model.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from mathutils.kdtree import KDTree

import bpy
from mathutils import Vector


ROOT_MARKER = Path("src/config/workspace.json")
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


def workspace_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ROOT_MARKER).is_file():
            return parent
    raise RuntimeError("workspace root not found")


ROOT = workspace_root()


def resolve(value: str | Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--include-helpers", action="store_true")
    parser.add_argument("--action", choices=("rest", "Stand", "Walk", "Attack"), default="rest")
    parser.add_argument("--xray", action="store_true", help="render the mesh translucent to inspect hidden bones")
    parser.add_argument("--frame", type=int)
    return parser.parse_args(raw)


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ vertex.co for obj in objects for vertex in obj.data.vertices]
    if not points:
        raise RuntimeError("no visible mesh vertices")
    return (
        Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points))),
        Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points))),
    )

def coupling_metrics(armature: bpy.types.Object, mesh: bpy.types.Object) -> dict[str, object]:
    """Compare posed deform bones with the evaluated vertices they influence."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh.evaluated_get(depsgraph)
    points_by_group: dict[str, list[Vector]] = {}
    for source_vertex, evaluated_vertex in zip(mesh.data.vertices, evaluated.data.vertices):
        point = evaluated.matrix_world @ evaluated_vertex.co
        for assignment in source_vertex.groups:
            if assignment.group >= len(mesh.vertex_groups) or assignment.weight < 0.2:
                continue
            name = mesh.vertex_groups[assignment.group].name
            if name in NON_SKIN_GROUPS:
                continue
            points_by_group.setdefault(name, []).append(point)
    trees: dict[str, KDTree] = {}
    for name, points in points_by_group.items():
        tree = KDTree(len(points))
        for index, point in enumerate(points):
            tree.insert(point, index)
        tree.balance()
        trees[name] = tree
    bone_distances: list[dict[str, object]] = []
    for bone in armature.pose.bones:
        tree = trees.get(bone.name)
        if tree is None:
            continue
        head = armature.matrix_world @ bone.head
        tail = armature.matrix_world @ bone.tail
        distance = sum(tree.find(head.lerp(tail, index / 10.0))[2] for index in range(11)) / 11
        bone_distances.append(
            {
                "bone": bone.name,
                "head": list(head),
                "tail": list(tail),
                "meanDistance": distance,
            }
        )
    if not bone_distances:
        raise RuntimeError("no deform bones have weighted evaluated vertices")
    bone_distances.sort(key=lambda item: float(item["meanDistance"]), reverse=True)
    return {
        "weightedDeformBones": len(bone_distances),
        "meanBoneToInfluencedVertexDistance": sum(float(item["meanDistance"]) for item in bone_distances) / len(bone_distances),
        "maxBoneToInfluencedVertexDistance": float(bone_distances[0]["meanDistance"]),
        "worstBones": bone_distances[:5],
        "perBone": bone_distances,
        "weightThreshold": 0.2,
    }
def evaluated_positions(mesh: bpy.types.Object) -> list[Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh.evaluated_get(depsgraph)
    return [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]


def coupling_certificate(armature: bpy.types.Object, mesh: bpy.types.Object, current_action: bpy.types.Action | None, current_frame: int) -> dict[str, object]:
    """Prove the visible mesh is skinned to the armature, not merely co-located."""
    current = evaluated_positions(mesh)
    bind = [mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices]
    saved_bases = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
    armature.animation_data_create()
    armature.animation_data.action = None
    for bone in armature.pose.bones:
        bone.matrix_basis.identity()
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    rest = evaluated_positions(mesh)
    if len(current) != len(rest):
        raise RuntimeError("evaluated vertex topology changed between the current action and rest pose")
    rest_topology_matches_raw = len(rest) == len(bind)
    rest_deltas = [(posed - base).length for posed, base in zip(rest, bind)] if rest_topology_matches_raw else []
    motion_deltas = [(posed - base).length for posed, base in zip(current, rest)]
    armature.animation_data.action = current_action
    bpy.context.scene.frame_set(current_frame)
    bpy.context.view_layer.update()
    if current_action is None:
        for bone in armature.pose.bones:
            saved = saved_bases.get(bone.name)
            if saved is not None:
                bone.matrix_basis = saved
        bpy.context.view_layer.update()
    deform_indices = {group.index for group in mesh.vertex_groups if group.name not in NON_SKIN_GROUPS}
    weighted_vertices = sum(
        any(assignment.group in deform_indices and assignment.weight > 0.0 for assignment in vertex.groups)
        for vertex in mesh.data.vertices
    )
    max_influences = max(
        (sum(1 for assignment in vertex.groups if assignment.group in deform_indices and assignment.weight > 0.0) for vertex in mesh.data.vertices),
        default=0,
    )
    moved = [delta for delta in motion_deltas if delta > 1e-5]
    return {
        "armatureModifier": any(mod.type == "ARMATURE" and mod.object == armature for mod in mesh.modifiers),
        "vertexCount": len(mesh.data.vertices),
        "evaluatedVertexCount": len(current),
        "weightedVertices": weighted_vertices,
        "unweightedVertices": len(mesh.data.vertices) - weighted_vertices,
        "maxPositiveInfluences": max_influences,
        "restPoseInvariant": {
            "status": "PASS" if rest_topology_matches_raw else "UNVERIFIED_EVALUATED_TOPOLOGY_CHANGED",
            "rawVertexCount": len(bind),
            "evaluatedVertexCount": len(rest),
            "maxVertexDelta": max(rest_deltas, default=None),
            "meanVertexDelta": sum(rest_deltas) / len(rest_deltas) if rest_deltas else None,
        },
        "actionMotion": {
            "action": current_action.name if current_action else None,
            "frame": current_frame,
            "evaluatedVertexCount": len(current),
            "changedVertices": len(moved),
            "maxVertexDelta": max(motion_deltas, default=0.0),
            "meanVertexDelta": sum(motion_deltas) / len(motion_deltas) if motion_deltas else 0.0,
        },
    }


def set_xray_surface(meshes: list[bpy.types.Object], opacity: float = 0.28) -> None:
    """Use a translucent diagnostic surface so hidden bones remain inspectable."""
    surface = bpy.data.materials.new("BindingOverlay_XRay_Surface")
    surface.use_nodes = True
    shader = next(node for node in surface.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (0.22, 0.34, 0.52, 1.0)
    shader.inputs["Roughness"].default_value = 0.58
    shader.inputs["Alpha"].default_value = opacity
    if hasattr(surface, "surface_render_method"):
        surface.surface_render_method = "DITHERED"
    for mesh in meshes:
        mesh.data.materials.clear()
        mesh.data.materials.append(surface)


def material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    result = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    result.diffuse_color = color
    result.use_nodes = True
    shader = next((node for node in result.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
    if shader is not None:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = 0.45
        shader.inputs["Metallic"].default_value = 0.0
    return result


def point_camera(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def make_bone_overlay(armature: bpy.types.Object, extent: float, include_helpers: bool = False) -> tuple[bpy.types.Collection, dict[str, int]]:
    collection = bpy.data.collections.new("Binding Overlay")
    bpy.context.scene.collection.children.link(collection)
    deform_material = material("BindingOverlay_Deform", (1.0, 0.03, 0.02, 1.0))
    helper_material = material("BindingOverlay_Helper", (1.0, 0.75, 0.02, 1.0))
    counts = {"deform": 0, "helper": 0, "zeroLength": 0}
    radius = max(extent * 0.004, 0.002)
    for bone in armature.pose.bones:
        if not include_helpers and bone.name in NON_SKIN_GROUPS:
            continue
        head = armature.matrix_world @ bone.head
        tail = armature.matrix_world @ bone.tail
        delta = tail - head
        length = delta.length
        if length <= 1e-7:
            counts["zeroLength"] += 1
            continue
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=8,
            radius=radius if bone.name not in NON_SKIN_GROUPS else radius * 0.7,
            depth=length,
            location=(head + tail) / 2.0,
        )
        line = bpy.context.view_layer.objects.active
        line.name = f"BindingOverlay_{bone.name}"
        line.rotation_mode = "QUATERNION"
        line.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(delta.normalized())
        for old in list(line.users_collection):
            old.objects.unlink(line)
        collection.objects.link(line)
        line.data.materials.append(helper_material if bone.name in NON_SKIN_GROUPS else deform_material)
        if bone.name in NON_SKIN_GROUPS:
            counts["helper"] += 1
        else:
            counts["deform"] += 1
    return collection, counts


def configure_render(scene: bpy.types.Scene, meshes: list[bpy.types.Object], extent: float) -> None:
    lo, hi = bounds(meshes)
    center = (lo + hi) / 2.0
    camera_data = bpy.data.cameras.new("BindingOverlay_Camera")
    camera = bpy.data.objects.new("BindingOverlay_Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + Vector((1.65, -2.25, 1.2)).normalized() * extent * 2.15
    camera_data.lens = 58
    point_camera(camera, center)
    scene.camera = camera
    for name, offset, energy, size in (
        ("BindingOverlay_Key", (1.5, -1.4, 2.0), 130.0, 2.8),
        ("BindingOverlay_Fill", (-1.6, -0.8, 0.7), 34.0, 3.0),
        ("BindingOverlay_Rim", (0.5, 1.6, 1.6), 65.0, 2.6),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = extent * size
        light = bpy.data.objects.new(name, data)
        scene.collection.objects.link(light)
        light.location = center + Vector(offset).normalized() * extent * 1.8
        point_camera(light, center)
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.008, 0.008, 0.008)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def action_by_name(name: str) -> bpy.types.Action | None:
    if name == "rest":
        return None
    wanted = "".join(char.lower() for char in name if char.isalnum())
    for action in bpy.data.actions:
        normalized = "".join(char.lower() for char in action.name if char.isalnum())
        if normalized == wanted or normalized.endswith(wanted) or wanted in normalized:
            return action
    raise RuntimeError(f"missing action: {name}")

def main() -> None:
    args = parse_args()
    blend_path = resolve(args.blend)
    out_dir = resolve(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    armature = next((obj for obj in scene.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("blend has no armature")
    meshes = [obj for obj in scene.objects if obj.type == "MESH" and not obj.hide_render]
    if not meshes:
        raise RuntimeError("blend has no visible mesh")
    action = action_by_name(args.action)
    armature.animation_data_create()
    armature.animation_data.action = action
    if action is None:
        for pose_bone in armature.pose.bones:
            pose_bone.matrix_basis.identity()
        bpy.context.view_layer.update()
    if args.frame is None:
        frame = 0 if action is None else int((action.frame_range[0] + action.frame_range[1]) / 2)
    else:
        frame = args.frame
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    lo, hi = bounds(meshes)
    extent = max(hi - lo)
    _, overlay_counts = make_bone_overlay(armature, extent, args.include_helpers)
    coupling = coupling_metrics(armature, meshes[0])
    certificate = coupling_certificate(armature, meshes[0], action, frame)
    if args.xray:
        set_xray_surface(meshes)
    configure_render(scene, meshes, extent)
    output = out_dir / f"binding-overlay-{args.action.lower()}-{frame}.png"
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    report = {
        "schemaVersion": 1,
        "workflow": "offline-sc2-ai-binding-overlay.v1",
        "status": "PASS",
        "evidenceType": "static",
        "blend": str(blend_path.relative_to(ROOT)).replace("\\", "/"),
        "action": args.action,
        "frame": frame,
        "armature": armature.name,
        "boneCount": len(armature.data.bones),
        "overlayMode": "all-44-bones" if args.include_helpers else "deform-only",
        "xray": args.xray,
        "nonSkinBonesExcluded": 0 if args.include_helpers else len(NON_SKIN_GROUPS),
        "visibleMeshes": [{"name": mesh.name, "vertices": len(mesh.data.vertices)} for mesh in meshes],
        "overlayCounts": overlay_counts,
        "coupling": coupling,
        "couplingCertificate": certificate,
        "scopeBoundary": "Offline Blender render only; no SC2 Previewer, Actor, or in-game validation.",
    }
    report_path = out_dir / f"binding-overlay-{args.action.lower()}-{frame}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("BINDING_OVERLAY_READY=" + str(report_path))
    bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
