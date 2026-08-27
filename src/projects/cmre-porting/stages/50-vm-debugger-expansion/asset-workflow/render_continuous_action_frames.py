"""Render continuous Blender action frames from a saved offline SC2 asset preview.

This tool intentionally opens an existing `.blend` rather than importing an M3, so it
can run in Blender background mode without M3Studio's GPU registration path. It only
creates PNG evidence under the caller-provided artifact directory; FFmpeg encodes the
resulting sequences separately.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


PREFERRED_ACTIONS = {
    "stand": "Armature_Stand 01_full",
    "walk": "Armature_Walk_full",
    "attack": "Armature_Attack 01_full",
}

ROOT_MARKER = Path("src/config/workspace.json")


def workspace_root() -> Path:
    for parent in Path(__file__).resolve().parents:
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
    parser.add_argument("--actions", nargs="+", default=["Stand", "Walk", "Attack"])
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--resolution", type=int, default=1024)
    return parser.parse_args(raw)


def normalized(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def resolve_actions(requested: list[str]) -> dict[str, bpy.types.Action]:
    resolved: dict[str, bpy.types.Action] = {}
    actions_by_normalized_name = {normalized(action.name): action for action in bpy.data.actions}
    for display_name in requested:
        wanted = normalized(display_name)
        preferred_name = PREFERRED_ACTIONS.get(wanted)
        if preferred_name is not None:
            preferred = actions_by_normalized_name.get(normalized(preferred_name))
            if preferred is not None:
                resolved[display_name] = preferred
                continue
        candidates = [
            action
            for action in bpy.data.actions
            if wanted in normalized(action.name) and normalized(action.name).endswith("full")
        ]
        if not candidates:
            raise RuntimeError(f"missing requested action: {display_name}")
        candidates.sort(key=lambda action: (len(action.name), action.name))
        resolved[display_name] = candidates[0]
    return resolved


def evaluated_bounds(meshes: list[bpy.types.Object], armature: bpy.types.Object, actions: dict[str, bpy.types.Action]) -> tuple[Vector, Vector]:
    corners: list[Vector] = []
    scene = bpy.context.scene
    for action in actions.values():
        armature.animation_data.action = action
        first, last = (int(value) for value in action.frame_range)
        for frame in range(first, last + 1):
            scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            for mesh in meshes:
                evaluated = mesh.evaluated_get(depsgraph)
                corners.extend(evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box)
    if not corners:
        raise RuntimeError("no mesh bounds available for camera framing")
    return (
        Vector((min(point.x for point in corners), min(point.y for point in corners), min(point.z for point in corners))),
        Vector((max(point.x for point in corners), max(point.y for point in corners), max(point.z for point in corners))),
    )


def point_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def remove_named_objects(names: tuple[str, ...]) -> None:
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)


def setup_render(meshes: list[bpy.types.Object], lo: Vector, hi: Vector, fps: int, resolution: int) -> None:
    scene = bpy.context.scene
    remove_named_objects(("ContinuousActionPreview_Camera", "ContinuousActionPreview_Key", "ContinuousActionPreview_Fill", "ContinuousActionPreview_Rim"))
    center = (lo + hi) / 2.0
    extent = max(hi - lo)
    camera_data = bpy.data.cameras.new("ContinuousActionPreview_Camera")
    camera = bpy.data.objects.new("ContinuousActionPreview_Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + Vector((1.65, -2.25, 1.2)).normalized() * extent * 2.3
    camera_data.lens = 58
    point_at(camera, center)
    scene.camera = camera
    for name, offset, energy, size in (
        ("ContinuousActionPreview_Key", (1.5, -1.4, 2.0), 130.0, 2.8),
        ("ContinuousActionPreview_Fill", (-1.6, -0.8, 0.7), 34.0, 3.0),
        ("ContinuousActionPreview_Rim", (0.5, 1.6, 1.6), 65.0, 2.6),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = extent * size
        light = bpy.data.objects.new(name, data)
        scene.collection.objects.link(light)
        light.location = center + Vector(offset).normalized() * extent * 1.8
        point_at(light, center)
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        # Blender 5.2 retained Eevee but renamed this enum identifier.
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.fps = fps
    scene.world.color = (0.012, 0.012, 0.012)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def main() -> None:
    args = parse_args()
    blend_path = resolve(args.blend)
    out_dir = resolve(args.out_dir)
    if not blend_path.is_file():
        raise FileNotFoundError(f"missing Blend: {blend_path}")
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    armatures = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(f"expected one armature, found {len(armatures)}")
    armature = armatures[0]
    armature.animation_data_create()
    meshes = [obj for obj in scene.objects if obj.type == "MESH" and not obj.hide_render]
    if not meshes:
        raise RuntimeError("Blend has no render-visible mesh")
    actions = resolve_actions(args.actions)
    lo, hi = evaluated_bounds(meshes, armature, actions)
    setup_render(meshes, lo, hi, args.fps, args.resolution)
    rendered: list[dict[str, object]] = []
    for display_name, action in actions.items():
        armature.animation_data.action = action
        first, last = (int(value) for value in action.frame_range)
        action_dir = out_dir / display_name.lower()
        action_dir.mkdir(parents=True, exist_ok=True)
        for frame in range(first, last + 1):
            scene.frame_set(frame)
            output = action_dir / f"frame-{frame:04d}.png"
            scene.render.filepath = str(output)
            bpy.ops.render.render(write_still=True)
        rendered.append(
            {
                "requestedAction": display_name,
                "resolvedAction": action.name,
                "frameRange": [first, last],
                "frameCount": last - first + 1,
                "directory": str(action_dir.relative_to(ROOT)).replace("\\", "/"),
            }
        )
    report = {
        "schemaVersion": 1,
        "workflow": "offline-sc2-continuous-action-frame-render.v1",
        "status": "PASS",
        "evidenceType": "static",
        "blend": str(blend_path.relative_to(ROOT)).replace("\\", "/"),
        "armature": armature.name,
        "visibleMeshes": [{"name": mesh.name, "vertices": len(mesh.data.vertices)} for mesh in meshes],
        "fps": args.fps,
        "resolution": [args.resolution, args.resolution],
        "actions": rendered,
        "scopeBoundary": "Offline Blender render only. It does not invoke M3Studio import/export, SC2 Previewer, Actor, map, mod, or game runtime.",
    }
    report_path = out_dir / "continuous-action-frame-render-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("CONTINUOUS_ACTION_FRAMES_READY=" + str(report_path))


if __name__ == "__main__":
    main()
