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
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


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
    }
)



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


def dimensions(lo: Vector, hi: Vector) -> Vector:
    return hi - lo


def align_candidate(candidate: bpy.types.Object, target_meshes: list[bpy.types.Object]) -> dict[str, Any]:
    # glTF import leaves a -90-degree X basis on the object. Bake that basis
    # first; otherwise Blender's transform_apply applies the fit scale in the
    # wrong local axes and detaches the mesh from the canonical skeleton.
    target_lo, target_hi = bounds(target_meshes)
    target_dim = dimensions(target_lo, target_hi)
    imported_world = candidate.matrix_world.copy()
    candidate.data.transform(imported_world)
    candidate.matrix_world = Matrix.Identity(4)
    axis_matrix = Matrix.Rotation(math.radians(90.0), 4, "Z")
    candidate.data.transform(axis_matrix)
    bpy.context.view_layer.update()
    source_lo, source_hi = bounds([candidate])
    source_dim = dimensions(source_lo, source_hi)
    if min(source_dim) <= 0 or min(target_dim) <= 0:
        raise RuntimeError("cannot align zero-sized mesh")
    fit_scale = Vector((
        target_dim.x / source_dim.x,
        target_dim.y / source_dim.y,
        target_dim.z / source_dim.z,
    ))
    candidate.data.transform(Matrix.Diagonal((fit_scale.x, fit_scale.y, fit_scale.z, 1.0)))
    armature = next((obj.parent for obj in target_meshes if obj.parent and obj.parent.type == "ARMATURE"), None)
    root = armature.data.bones.get("Ref_Origin") if armature else None
    if root is None and armature:
        root = armature.data.bones.get("Dummy01")
    if root is None or armature is None:
        raise RuntimeError("canonical source has no Ref_Origin/Dummy01 root")
    target_root = armature.matrix_world @ root.head_local
    candidate.data.transform(Matrix.Translation(target_root))
    candidate.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    final_lo, final_hi = bounds([candidate])
    return {
        "rotationZDegrees": 90.0,
        "targetRootBone": root.name,
        "targetRoot": list(target_root),
        "targetBounds": {"min": list(target_lo), "max": list(target_hi), "dimensions": list(target_dim)},
        "sourceBoundsAfterAxisCorrection": {"min": list(source_lo), "max": list(source_hi), "dimensions": list(source_dim)},
        "finalBounds": {"min": list(final_lo), "max": list(final_hi), "dimensions": list(dimensions(final_lo, final_hi))},
    }




def remove_armature_modifiers(obj: bpy.types.Object) -> None:
    for modifier in list(obj.modifiers):
        if modifier.type == "ARMATURE":
            obj.modifiers.remove(modifier)


def transfer_template_weights(mesh: bpy.types.Object, source_meshes: list[bpy.types.Object]) -> None:
    """Transfer canonical skin weights from nearby source vertices.

    Nearest-bone weighting is unstable for a stylized mesh because multiple
    legs and the tail are close in world space. The source M3 already contains
    the intended region-to-bone assignments, so blend the four nearest source
    vertex assignments instead and leave attachment/collision groups unused.
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
        total = sum(blended.values())
        if total <= 0.0:
            raise RuntimeError(f"weight transfer produced no assignment for vertex {vertex.index}")
        for name, weight in blended.items():
            groups[name].add([vertex.index], weight / total, "REPLACE")


def bind_candidate(candidate: bpy.types.Object, armature: bpy.types.Object, source_meshes: list[bpy.types.Object]) -> str:
    remove_armature_modifiers(candidate)
    candidate.parent = armature
    candidate.matrix_parent_inverse = armature.matrix_world.inverted()
    transfer_template_weights(candidate, source_meshes)
    modifier = candidate.modifiers.new("AI_Zergling_Armature", "ARMATURE")
    modifier.object = armature
    weighted = sum(1 for vertex in candidate.data.vertices if vertex.groups)
    if weighted != len(candidate.data.vertices):
        raise RuntimeError(f"template weight transfer left {len(candidate.data.vertices) - weighted} unweighted vertices")
    return "template-nearest-vertex-transfer"


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
    alignment = align_candidate(candidate, source_meshes)
    weighting_method = bind_candidate(candidate, armature, source_meshes)
    template = source_meshes[-1]
    export_mesh = make_export_mesh(candidate, template, armature)
    export_mesh.hide_render = True
    export_mesh.hide_viewport = False
    hide_template_meshes(source_meshes, candidate)
    scene = bpy.context.scene
    scene.frame_set(int((actions["Stand"].frame_range[0] + actions["Stand"].frame_range[1]) / 2))
    preview_dir = out_dir / "w4-ai-textured-previews"
    preview_outputs = render_midpoints(scene, armature, actions, candidate, preview_dir)
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
            "armature": armature.name,
            "boneCount": len(armature.data.bones),
            "sourceMeshCount": len(source_meshes),
            "candidateMesh": candidate.name,
            "candidateVertices": len(candidate.data.vertices),
            "candidateTriangles": sum(len(poly.vertices) - 2 for poly in candidate.data.polygons),
            "candidateUvLayers": len(candidate.data.uv_layers),
            "alignment": alignment,
            "weighting": {"method": weighting_method, "vertexGroups": len(candidate.vertex_groups), "armatureModifier": any(mod.type == "ARMATURE" and mod.object == armature for mod in candidate.modifiers)},
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
    if args.mode == "integrate":
        integrate(args)
    else:
        verify(args)
    bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
