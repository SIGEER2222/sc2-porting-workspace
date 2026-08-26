"""Run the offline M3Studio authoring/preview gate in Blender's graphical UI.

This script intentionally stays on the offline Blender/M3Studio side. It does
not launch SC2, edit a map/mod, or call any SC2 runtime API. Blender must be
started without ``--background`` because M3Studio initializes GPU drawing
support during registration/import.

The script imports the manifest's source M3 with M3Studio, saves an untouched
W2 authoring baseline, maps declared DDS files to a separate preview material,
renders key action frames for W3, saves a preview Blend, and leaves Blender
open with an Offline Asset Workflow panel for manual inspection.
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
from mathutils import Vector


REQUIRED_ACTIONS = ("Stand", "Walk", "Attack")
WORKSPACE_MARKER = Path("src/config/workspace.json")


def locate_workspace_root() -> Path:
    script_path = Path(__file__).resolve()
    for candidate in script_path.parents:
        if (candidate / WORKSPACE_MARKER).is_file():
            return candidate
    raise RuntimeError("Unable to locate workspace root from GUI workflow script")


WORKSPACE_ROOT = locate_workspace_root()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def workspace_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else WORKSPACE_ROOT / candidate


def normalize_action_name(name: str) -> str:
    return "".join(character.lower() for character in name if character.isalnum())


def find_action(actions: dict[str, bpy.types.Action], requested: str) -> bpy.types.Action | None:
    if requested in actions:
        return actions[requested]
    wanted = normalize_action_name(requested)
    for name, action in actions.items():
        normalized = normalize_action_name(name)
        if normalized == wanted or normalized.endswith(wanted) or wanted in normalized:
            return action
    return None


def clear_scene() -> None:
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)
    for action in list(bpy.data.actions):
        if action.users == 0:
            bpy.data.actions.remove(action)


def register_m3studio(addon_dir: Path) -> None:
    addon_dir = addon_dir.resolve()
    if not addon_dir.is_dir():
        raise FileNotFoundError(f"M3Studio addon directory does not exist: {addon_dir}")
    if str(addon_dir) not in sys.path:
        sys.path.insert(0, str(addon_dir))
    import m3studio  # type: ignore[import-not-found]

    try:
        m3studio.register()
    except (RuntimeError, ValueError) as exc:
        # Blender may retain a registration when the script is re-run in the same UI session.
        if not hasattr(bpy.ops.m3, "import"):
            raise RuntimeError(f"M3Studio registration failed: {exc}") from exc


def import_source_model(model_path: Path) -> bpy.types.Object:
    result = getattr(bpy.ops.m3, "import")(
        filepath=str(model_path),
        id_name="(New Object)",
        get_mesh=True,
        get_effects=False,
        get_rig=True,
        get_anims=True,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"M3Studio import did not finish: {result}")
    armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        raise RuntimeError("M3Studio import finished without an armature")
    return armature


def select_asset(armature: bpy.types.Object, meshes: list[bpy.types.Object]) -> None:
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature


def action_metadata(actions: dict[str, bpy.types.Action]) -> tuple[dict[str, Any], dict[str, bpy.types.Action]]:
    metadata: dict[str, Any] = {}
    resolved: dict[str, bpy.types.Action] = {}
    for requested in REQUIRED_ACTIONS:
        action = find_action(actions, requested)
        if action is None:
            metadata[requested] = {"status": "MISSING"}
            continue
        start = int(math.floor(action.frame_range[0]))
        end = int(math.ceil(action.frame_range[1]))
        resolved[requested] = action
        metadata[requested] = {
            "status": "PASS",
            "action": action.name,
            "frames": [start, (start + end) // 2, end],
            "fcurves": len(action.fcurves),
        }
    return metadata, resolved


def evaluated_bounds(scene: bpy.types.Scene, meshes: list[bpy.types.Object], frames: list[int]) -> tuple[Vector, Vector]:
    minimum = Vector((float("inf"), float("inf"), float("inf")))
    maximum = Vector((float("-inf"), float("-inf"), float("-inf")))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for mesh in meshes:
            evaluated = mesh.evaluated_get(depsgraph)
            evaluated_mesh = evaluated.to_mesh()
            try:
                for vertex in evaluated_mesh.vertices:
                    point = evaluated.matrix_world @ vertex.co
                    minimum.x = min(minimum.x, point.x)
                    minimum.y = min(minimum.y, point.y)
                    minimum.z = min(minimum.z, point.z)
                    maximum.x = max(maximum.x, point.x)
                    maximum.y = max(maximum.y, point.y)
                    maximum.z = max(maximum.z, point.z)
            finally:
                evaluated.to_mesh_clear()
    if not all(math.isfinite(value) for value in (*minimum, *maximum)):
        raise RuntimeError("Imported model has no finite evaluated mesh bounds")
    return minimum, maximum


def point_camera(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def setup_camera_and_lights(scene: bpy.types.Scene, meshes: list[bpy.types.Object], frames: list[int]) -> None:
    minimum, maximum = evaluated_bounds(scene, meshes, frames)
    center = (minimum + maximum) / 2
    extent = max(maximum - minimum)
    if extent <= 0:
        raise RuntimeError("Imported model has zero render extent")

    camera_data = bpy.data.cameras.new("OfflineAssetCamera")
    camera = bpy.data.objects.new("OfflineAssetCamera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + Vector((1.6, -2.2, 1.2)).normalized() * extent * 2.8
    camera_data.lens = 55
    point_camera(camera, center)
    scene.camera = camera

    for name, offset, power, size, color in (
        ("OfflineKey", (1.5, -1.4, 2.0), 900.0, 3.0, (1.0, 0.82, 0.72)),
        ("OfflineFill", (-1.6, -0.8, 0.7), 500.0, 2.5, (0.35, 0.55, 1.0)),
        ("OfflineRim", (0.5, 1.6, 1.6), 700.0, 2.2, (0.9, 0.25, 0.45)),
    ):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = power
        light_data.shape = "DISK"
        light_data.size = extent * size
        light_data.color = color
        light = bpy.data.objects.new(name, light_data)
        scene.collection.objects.link(light)
        light.location = center + Vector(offset).normalized() * extent * 2.0
        point_camera(light, center)

    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.008, 0.010, 0.018)


def texture_by_role(texture_paths: list[Path], role: str) -> Path | None:
    role_tokens = {
        "diffuse": ("@dif", "diffuse", "basecolor"),
        "normal": ("@norm", "normal"),
        "specular": ("@spec", "specular"),
        "emissive": ("@emiss", "emissive"),
    }[role]
    for path in texture_paths:
        lowered = path.name.lower()
        if any(token in lowered for token in role_tokens):
            return path
    return None


def load_image(path: Path, loaded: dict[str, Any], errors: list[str]) -> bpy.types.Image | None:
    try:
        image = bpy.data.images.load(str(path), check_existing=True)
    except (RuntimeError, OSError) as exc:
        errors.append(f"{path}: {exc}")
        return None
    loaded[path.as_posix()] = {
        "path": str(path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        "size": [image.size[0], image.size[1]],
    }
    return image


def build_preview_material(
    template_id: str,
    texture_paths: list[Path],
    loaded: dict[str, Any],
    errors: list[str],
) -> tuple[bpy.types.Material, bool]:
    material = bpy.data.materials.new(f"{template_id}_OfflinePreview")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.55
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    diffuse = texture_by_role(texture_paths, "diffuse")
    diffuse_image = load_image(diffuse, loaded, errors) if diffuse else None
    if diffuse_image:
        node = nodes.new("ShaderNodeTexImage")
        node.name = "Diffuse DDS"
        node.label = "Diffuse DDS"
        node.image = diffuse_image
        links.new(node.outputs["Color"], shader.inputs["Base Color"])

    normal = texture_by_role(texture_paths, "normal")
    normal_image = load_image(normal, loaded, errors) if normal else None
    if normal_image:
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = "Normal DDS"
        texture.label = "Normal DDS"
        texture.image = normal_image
        texture.image.colorspace_settings.name = "Non-Color"
        normal_map = nodes.new("ShaderNodeNormalMap")
        links.new(texture.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])

    emissive = texture_by_role(texture_paths, "emissive")
    emissive_image = load_image(emissive, loaded, errors) if emissive else None
    if emissive_image:
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = "Emissive DDS"
        texture.label = "Emissive DDS"
        texture.image = emissive_image
        emission_input = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
        if emission_input:
            links.new(texture.outputs["Color"], emission_input)
            if shader.inputs.get("Emission Strength"):
                shader.inputs["Emission Strength"].default_value = 0.35

    return material, diffuse_image is not None


def render_action_frames(
    scene: bpy.types.Scene,
    armature: bpy.types.Object,
    resolved_actions: dict[str, bpy.types.Action],
    output_dir: Path,
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for requested in REQUIRED_ACTIONS:
        action = resolved_actions[requested]
        if armature.animation_data is None:
            armature.animation_data_create()
        armature.animation_data.action = action
        start = int(math.floor(action.frame_range[0]))
        end = int(math.ceil(action.frame_range[1]))
        frames = [start, (start + end) // 2, end]
        for label, frame in zip(("start", "mid", "end"), frames):
            scene.frame_set(frame)
            path = output_dir / f"{requested.lower()}-{label}.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            outputs.append({
                "action": requested,
                "resolvedAction": action.name,
                "frame": frame,
                "path": str(path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
            })
    return outputs


def frame_viewport() -> bool:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is None:
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_selected(use_all_regions=False)
                area.spaces.active.shading.type = "MATERIAL"
            return True
    return False


class OfflineAssetWorkflowSetAction(bpy.types.Operator):
    bl_idname = "offline_asset_workflow.set_action"
    bl_label = "Preview Action"
    action_name: bpy.props.StringProperty()

    def execute(self, context: bpy.types.Context) -> set[str]:
        armature = next((obj for obj in context.scene.objects if obj.type == "ARMATURE"), None)
        action = bpy.data.actions.get(self.action_name)
        if armature is None or action is None:
            self.report({"ERROR"}, "Armature or action is unavailable")
            return {"CANCELLED"}
        if armature.animation_data is None:
            armature.animation_data_create()
        armature.animation_data.action = action
        start = int(math.floor(action.frame_range[0]))
        end = int(math.ceil(action.frame_range[1]))
        context.scene.frame_set((start + end) // 2)
        return {"FINISHED"}


class OfflineAssetWorkflowSaveSnapshot(bpy.types.Operator):
    bl_idname = "offline_asset_workflow.save_snapshot"
    bl_label = "Save Interactive Snapshot"

    def execute(self, context: bpy.types.Context) -> set[str]:
        path = Path(context.scene.get("offline_asset_snapshot_path", ""))
        if not path:
            self.report({"ERROR"}, "No snapshot path configured")
            return {"CANCELLED"}
        path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        context.scene["offline_asset_last_snapshot"] = str(path)
        self.report({"INFO"}, f"Saved {path.name}")
        return {"FINISHED"}


class OfflineAssetWorkflowPanel(bpy.types.Panel):
    bl_label = "Offline SC2 Asset Workflow"
    bl_idname = "OFFLINE_ASSET_WORKFLOW_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Asset Workflow"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        scene = context.scene
        layout.label(text=f"Template: {scene.get('offline_asset_template_id', 'unknown')}")
        layout.label(text="SC2 runtime: intentionally not used")
        layout.separator()
        layout.label(text="Actions")
        for requested in REQUIRED_ACTIONS:
            action_name = scene.get(f"offline_asset_action_{requested}")
            if action_name:
                operator = layout.operator("offline_asset_workflow.set_action", text=requested)
                operator.action_name = action_name
        layout.separator()
        layout.operator("offline_asset_workflow.save_snapshot", icon="FILE_TICK")
        layout.label(text="W2/W3 evidence saved to report")


GUI_CLASSES = (
    OfflineAssetWorkflowSetAction,
    OfflineAssetWorkflowSaveSnapshot,
    OfflineAssetWorkflowPanel,
)


def register_gui_panel(template_id: str, resolved_actions: dict[str, bpy.types.Action], snapshot_path: Path) -> None:
    for cls in GUI_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass
    scene = bpy.context.scene
    scene["offline_asset_template_id"] = template_id
    scene["offline_asset_snapshot_path"] = str(snapshot_path)
    for requested, action in resolved_actions.items():
        scene[f"offline_asset_action_{requested}"] = action.name


def parse_args() -> argparse.Namespace:
    if "--" in sys.argv:
        raw_args = sys.argv[sys.argv.index("--") + 1 :]
    else:
        raw_args = []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--addon-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    return parser.parse_args(raw_args)


def main() -> None:
    if bpy.app.background:
        raise RuntimeError("GUI authoring requires Blender without --background")
    args = parse_args()
    manifest_path = workspace_path(args.manifest)
    manifest = read_json(manifest_path)
    template_id = manifest["templateId"]
    source_model = workspace_path(manifest["source"]["model"])
    texture_paths = [workspace_path(path) for path in manifest["source"].get("textures", [])]
    gui_config = manifest.get("gui", {})
    output_dir = workspace_path(args.out_dir or gui_config.get(
        "outputDir",
        f"artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/sc2-model-reference/workflow-runs/{template_id}-gui",
    ))
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = output_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    authoring_blend = output_dir / f"{template_id}-source.blend"
    preview_blend = output_dir / f"{template_id}-preview.blend"
    report_path = output_dir / "gui-authoring-report.json"
    addon_dir = args.addon_dir or Path(os.environ.get("SC2_M3STUDIO_ADDON_DIR", ""))
    if not addon_dir:
        raise RuntimeError("Set SC2_M3STUDIO_ADDON_DIR or pass --addon-dir")

    clear_scene()
    register_m3studio(workspace_path(addon_dir))
    armature = import_source_model(source_model)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    actions = {action.name: action for action in bpy.data.actions}
    action_report, resolved_actions = action_metadata(actions)
    missing = [name for name in REQUIRED_ACTIONS if name not in resolved_actions]
    if missing:
        raise RuntimeError(f"M3Studio import is missing required actions: {missing}")
    select_asset(armature, meshes)

    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = max(int(math.ceil(action.frame_range[1])) for action in resolved_actions.values())
    scene.frame_set(int(math.floor(resolved_actions["Stand"].frame_range[0])))
    bpy.ops.wm.save_as_mainfile(filepath=str(authoring_blend))

    loaded_textures: dict[str, Any] = {}
    texture_errors: list[str] = []
    preview_material, diffuse_loaded = build_preview_material(
        template_id,
        texture_paths,
        loaded_textures,
        texture_errors,
    )
    for mesh in meshes:
        mesh.data.materials.clear()
        mesh.data.materials.append(preview_material)

    render_frames = [
        int(math.floor(action.frame_range[0]))
        for action in resolved_actions.values()
    ] + [
        int(math.ceil(action.frame_range[1]))
        for action in resolved_actions.values()
    ]
    setup_camera_and_lights(scene, meshes, render_frames)
    preview_outputs = render_action_frames(scene, armature, resolved_actions, preview_dir)
    armature.animation_data.action = resolved_actions["Stand"]
    scene.frame_set(int(sum(resolved_actions["Stand"].frame_range) / 2))
    select_asset(armature, meshes)
    scene["offline_asset_evidence_type"] = "static"
    scene["offline_asset_sc2_runtime"] = "NOT_USED"
    register_gui_panel(template_id, resolved_actions, preview_blend)
    frame_viewport()
    bpy.ops.wm.save_as_mainfile(filepath=str(preview_blend))

    report = {
        "schemaVersion": 1,
        "workflow": "offline-sc2-m3-template-gui-authoring.v1",
        "status": "PASS" if diffuse_loaded and not texture_errors else "W2_PASS_W3_TEXTURE_REVIEW",
        "evidenceType": "static",
        "uiEvidence": {
            "blenderBackground": bool(bpy.app.background),
            "m3studioAddon": str(workspace_path(addon_dir).resolve()).replace("\\", "/"),
            "panel": "Offline SC2 Asset Workflow",
        },
        "sc2Integration": False,
        "template": {
            "id": template_id,
            "manifest": str(manifest_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
            "sourceModel": str(source_model.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        },
        "authoring": {
            "blend": str(authoring_blend.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
            "armature": armature.name,
            "boneCount": len(armature.data.bones),
            "meshCount": len(meshes),
            "actions": action_report,
        },
        "preview": {
            "blend": str(preview_blend.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
            "textures": loaded_textures,
            "textureErrors": texture_errors,
            "renders": preview_outputs,
        },
        "scopeBoundary": (
            "This is offline Blender/M3Studio graphical evidence only. It does not "
            "launch SC2, modify a map or mod, or prove Previewer, Actor, or in-game behavior."
        ),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("GUI_ASSET_WORKFLOW_READY=" + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
