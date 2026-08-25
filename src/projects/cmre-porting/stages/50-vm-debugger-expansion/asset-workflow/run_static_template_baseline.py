"""Run the repeatable static portion of an offline SC2 M3 template workflow.

This runner intentionally does not perform M3Studio export or SC2 runtime work:
those operations require Blender's graphical UI or a future SC2 installation.
It produces a baseline manifest and a GLB preview whose required actions can be
validated deterministically in Blender background mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def locate_workspace_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "src/config/workspace.json").is_file():
            return candidate
    raise RuntimeError("Unable to locate workspace root from workflow runner path")


WORKSPACE_ROOT = locate_workspace_root()
DEFAULT_BLENDER = Path(os.environ.get("SC2_ASSET_BLENDER", "blender"))


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_workspace_path(relative_path: str) -> Path:
    candidate = WORKSPACE_ROOT / relative_path
    if not candidate.is_file():
        raise FileNotFoundError(f"Declared source file does not exist: {relative_path}")
    return candidate


def run_converter(converter: Path, source_model: Path, output_glb: Path) -> None:
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["node", str(converter), str(source_model), str(output_glb)],
        cwd=WORKSPACE_ROOT,
        check=True,
    )


def blender_probe_script(glb_path: Path, required_actions: list[str], output_path: Path) -> str:
    return f'''import hashlib
import json
from pathlib import Path
import bpy

input_glb = Path(r"{glb_path}")
output_json = Path(r"{output_path}")
required_actions = {required_actions!r}
bpy.ops.import_scene.gltf(filepath=str(input_glb))
armature = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
if armature is None:
    raise RuntimeError("Imported GLB has no armature")
mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
result = {{
    "armature": armature.name,
    "meshes": len(mesh_objects),
    "boneCount": len(armature.data.bones),
    "actions": {{}},
}}
for name in required_actions:
    action = bpy.data.actions.get(name)
    if action is None:
        raise RuntimeError(f"Missing required action: {{name}}")
    start = int(action.frame_range[0])
    end = int(action.frame_range[1] + 0.999999)
    midpoint = (start + end) // 2
    if armature.animation_data is None:
        armature.animation_data_create()
    armature.animation_data.action = action
    samples = []
    for frame in (start, midpoint, end):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        values = []
        for obj in mesh_objects:
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            try:
                values.extend(round(value, 7) for vertex in mesh.vertices for value in vertex.co)
            finally:
                evaluated.to_mesh_clear()
        samples.append(hashlib.sha256(repr(values).encode("utf-8")).hexdigest())
    result["actions"][name] = {{
        "frames": [start, midpoint, end],
        "fcurves": len(action.fcurves),
        "meshPoseHashes": samples,
        "deforms": len(set(samples)) > 1,
    }}
output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
print("ASSET_WORKFLOW_BLENDER_PROBE=" + json.dumps(result, ensure_ascii=False))
bpy.ops.wm.quit_blender()
'''


def resolve_executable(executable: Path) -> Path:
    if executable.is_absolute():
        if executable.is_file():
            return executable
        raise FileNotFoundError(f"Blender executable does not exist: {executable}")
    resolved = shutil.which(str(executable))
    if resolved is None:
        raise FileNotFoundError(
            "Blender was not found on PATH. Set SC2_ASSET_BLENDER or pass --blender."
        )
    return Path(resolved)


def run_blender_probe(blender: Path, glb_path: Path, required_actions: list[str], output_path: Path) -> dict[str, Any]:
    blender = resolve_executable(blender)
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        script_path = Path(handle.name)
        handle.write(blender_probe_script(glb_path, required_actions, output_path))
    try:
        subprocess.run(
            [str(blender), "--background", "--factory-startup", "--python", str(script_path)],
            cwd=WORKSPACE_ROOT,
            check=True,
        )
    finally:
        script_path.unlink(missing_ok=True)
    return read_json(output_path)


def build_report(manifest: dict[str, Any], manifest_path: Path, blender: Path) -> dict[str, Any]:
    source = manifest["source"]
    source_model = resolve_workspace_path(source["model"])
    textures = [resolve_workspace_path(texture) for texture in source["textures"]]
    preview = manifest["preview"]
    converter = resolve_workspace_path(preview["converter"])
    output_glb = WORKSPACE_ROOT / preview["output"]

    run_converter(converter, source_model, output_glb)
    probe_path = output_glb.with_suffix(".probe.json")
    probe = run_blender_probe(blender, output_glb, preview["requiredActions"], probe_path)

    action_results = probe["actions"]
    actions_valid = all(
        action["fcurves"] > 0 and action["deforms"]
        for action in action_results.values()
    )
    return {
        "schemaVersion": 1,
        "workflow": "offline-sc2-m3-template-static-baseline.v1",
        "status": "PASS" if actions_valid else "FAIL",
        "evidenceType": "static",
        "template": {
            "id": manifest["templateId"],
            "rigFamily": manifest["rigFamily"],
            "manifest": str(manifest_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
        },
        "source": {
            "model": {
                "path": source["model"],
                "bytes": source_model.stat().st_size,
                "sha256": sha256(source_model),
            },
            "textures": [
                {
                    "path": texture.relative_to(WORKSPACE_ROOT).as_posix(),
                    "bytes": texture.stat().st_size,
                    "sha256": sha256(texture),
                }
                for texture in textures
            ],
        },
        "preview": {
            "glb": {
                "path": str(output_glb.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                "bytes": output_glb.stat().st_size,
                "sha256": sha256(output_glb),
            },
            "probe": {
                "path": str(probe_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                **probe,
            },
        },
        "manualGates": manifest["manualGates"],
        "scopeBoundary": (
            "This runner establishes only the repeatable static source-to-GLB "
            "and Blender action-preview baseline. Source hashes and semantic "
            "action probes are compared; the binary GLB hash is recorded per run "
            "but is not treated as a determinism assertion. M3Studio authoring/"
            "export and SC2 Previewer, Actor, and in-game validation remain manual gates."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to a template manifest, relative to workspace root or absolute.")
    parser.add_argument("--blender", type=Path, default=DEFAULT_BLENDER, help="Blender executable for the static GLB probe.")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON report path, relative to workspace root or absolute.")
    return parser.parse_args()


def workspace_or_absolute(path: Path) -> Path:
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def main() -> int:
    args = parse_args()
    manifest_path = workspace_or_absolute(args.manifest)
    output_path = workspace_or_absolute(args.out)
    manifest = read_json(manifest_path)
    report = build_report(manifest, manifest_path, args.blender)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
