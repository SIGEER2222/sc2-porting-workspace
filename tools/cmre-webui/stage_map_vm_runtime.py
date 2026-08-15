#!/usr/bin/env python3
"""Create an isolated Vibe-kernel staging copy for an arbitrary SC2 map.

The source map is never edited. The output is intended for artifacts/ and can
then be packed with the existing StormLib packer before an approved launcher
starts SC2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KERNEL_ROOT = REPO_ROOT / "tools" / "galaxy-vibe" / "kernel"
DEFAULT_DISPATCH = REPO_ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup" / "invoke-disabled.galaxy"
DEFAULT_DOU_QUQU_ROOT = REPO_ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup"
EXTRACTOR = REPO_ROOT / "tools" / "mpq" / "scripts" / "extract_mpq.py"

_ATTRIBUTION_EXPRESSION = 'TextExpressionAssemble("Param/Expression/265C2CBF")'
_ATTRIBUTION_DIALOG_START = "DialogCreate(600,400,c_anchorCenter,0,0,true);"
_ATTRIBUTION_DIALOG_MARKER = "// CMRE_WEBUI_ATTRIBUTION_POPUP_REMOVED"
_ATTRIBUTION_STRING_KEYS = {
    "DocInfo/HowToPlayAdvanced00",
    "DocInfo/HowToPlayBasic00",
    "DocInfo/HowToPlayWinning00",
    "Param/Expression/265C2CBF",
}


class StagingError(RuntimeError):
    """Raised when a map cannot be staged without guessing."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_if_needed(source: Path, work_root: Path) -> tuple[Path, bool]:
    if source.is_dir():
        return source, False
    if source.suffix.casefold() not in {".sc2map", ".sc2mod"}:
        raise StagingError(f"source must be an unpacked map directory or .SC2Map: {source}")
    target = work_root / "source-extract" / source.name
    if not (target / "DocumentInfo").is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        completed = __import__("subprocess").run(
            [sys.executable, str(EXTRACTOR), str(source), str(target), "*"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not (target / "DocumentInfo").is_file():
            detail = (completed.stdout + "\n" + completed.stderr).strip()[-2000:]
            raise StagingError(f"map extraction failed (exit={completed.returncode}): {detail}")
    return target, True


def _write_bank_list(path: Path) -> None:
    if path.is_file():
        root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    else:
        root = ET.Element("BankList")
    existing = {(item.get("Name"), item.get("Player")) for item in root.findall("./Bank")}
    for player in ("1", "2"):
        if ("GalaxyVibe", player) not in existing:
            ET.SubElement(root, "Bank", Name="GalaxyVibe", Player=player)
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _patch_map_script(
    path: Path,
    *,
    enable_dou_ququ_features: bool = False,
    enable_dou_ququ_runtime: bool = False,
) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    marker = "// CMRE_WEBUI_VIBE_VM_STAGING"
    if marker in text:
        raise StagingError(f"source map already contains staging marker: {path}")
    anchor = 'include "TriggerLibs/NativeLib"'
    if text.count(anchor) != 1:
        raise StagingError(f"expected one NativeLib include in {path}")
    include_lines = [
        marker,
        'include "LibVibeKernel"',
        'include "LibVibeHandles"',
        'include "LibVibeInvokeDispatch_active"',
    ]
    include_lines.append(
        'include "LibDouQuquRuntime"'
        if enable_dou_ququ_runtime
        else 'include "LibDouQuquRuntimeDisabled"'
    )
    if enable_dou_ququ_features:
        include_lines.append('include "LibDouQuquBehavior"')
    missing_includes = [line for line in include_lines if line not in text]
    bootstrap_block = marker
    if missing_includes:
        bootstrap_block += "\n" + "\n".join(missing_includes)
    text = text.replace(anchor, anchor + "\n" + bootstrap_block, 1)
    old_init = "void lllAtg(){libNtve_InitLib();}"
    new_init = "void lllAtg(){libVibeKernel_InitLib();libNtve_InitLib();}"
    if text.count(old_init) == 1:
        text = text.replace(old_init, new_init, 1)
    elif text.count(new_init) != 1:
        raise StagingError(f"expected one斗蛐蛐 NativeLib init wrapper in {path}")
    # The source map's InitMap body creates its native triggers after lllAtg.
    # Register the VM only after that graph exists; relying on a 0.0 time event
    # is not reliable in an API-created game with no advancing game clock.
    init_map = re.search(r"(void\s+InitMap\s*\(\s*\)\s*\{)(.*?)(\}\s*)\Z", text, re.DOTALL)
    if init_map is None:
        raise StagingError(f"expected one terminal InitMap body in {path}")
    if "CMRE_WEBUI_VIBE_VM_REGISTER" in init_map.group(2):
        raise StagingError(f"source map already contains VM registration marker: {path}")
    init_body = init_map.group(2).rstrip()
    init_body += "\n// CMRE_WEBUI_VIBE_VM_REGISTER\n    libVibeKernel_gf_RegisterEntryPoints();\n"
    if enable_dou_ququ_features:
        init_body += "    libDouQuquBehavior_InitLib();\n"
    text = text[:init_map.start(2)] + init_body + "\n" + text[init_map.start(3):]
    path.write_text(text, encoding="utf-8", newline="\n")
    return [
        "LibVibeKernel",
        "LibVibeHandles",
        "LibVibeInvokeDispatch_active",
        "LibDouQuquRuntime" if enable_dou_ququ_runtime else "LibDouQuquRuntimeDisabled",
        "libVibeKernel_InitLib",
        "libVibeKernel_gf_RegisterEntryPoints",
        *(["LibDouQuquBehavior", "libDouQuquBehavior_InitLib"] if enable_dou_ququ_features else []),
    ]


def _remove_source_attribution_popup(output: Path) -> dict:
    """Remove the source map's attribution dialog from the isolated copy.

    The source map is immutable. This only edits the copied MapScript and its
    localized strings after ``copytree``. The match is intentionally exact so
    an unrelated dialog cannot be removed by a broad text replacement.
    """
    map_script = output / "MapScript.galaxy"
    text = map_script.read_text(encoding="utf-8-sig")
    expression_count = text.count(_ATTRIBUTION_EXPRESSION)
    if expression_count == 0:
        return {"applied": False, "files": [], "reason": "expression_not_found"}
    if expression_count != 1:
        raise StagingError(
            "expected one source attribution expression in staged MapScript, "
            f"found {expression_count}"
        )
    if _ATTRIBUTION_DIALOG_MARKER in text:
        raise StagingError("staged MapScript already contains attribution cleanup marker")

    expression_offset = text.index(_ATTRIBUTION_EXPRESSION)
    dialog_start = text.rfind(_ATTRIBUTION_DIALOG_START, 0, expression_offset)
    return_offset = text.find("return true;}", expression_offset)
    if dialog_start < 0 or return_offset < 0:
        raise StagingError("source attribution dialog boundaries were not found")
    text = (
        text[:dialog_start]
        + _ATTRIBUTION_DIALOG_MARKER
        + "\n"
        + text[return_offset:]
    )
    map_script.write_text(text, encoding="utf-8", newline="\n")
    cleaned_files = ["MapScript.galaxy"]
    removed_keys = []

    localized = output / "zhCN.SC2Data" / "LocalizedData" / "GameStrings.txt"
    if localized.is_file():
        lines = localized.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        kept = []
        removed_keys = []
        for line in lines:
            key = line.split("=", 1)[0].strip()
            if key in _ATTRIBUTION_STRING_KEYS:
                removed_keys.append(key)
                continue
            kept.append(line)
        if removed_keys:
            localized.write_text("".join(kept), encoding="utf-8", newline="\n")
            cleaned_files.append("zhCN.SC2Data/LocalizedData/GameStrings.txt")
    return {
        "applied": True,
        "files": cleaned_files,
        "removedKeys": sorted(set(removed_keys)),
        "marker": _ATTRIBUTION_DIALOG_MARKER,
    }


def stage_map(source: Path, output: Path, kernel_root: Path = DEFAULT_KERNEL_ROOT,
              dispatch_source: Path = DEFAULT_DISPATCH, replace: bool = False,
              enable_dou_ququ_features: bool = False,
              dou_ququ_root: Path = DEFAULT_DOU_QUQU_ROOT,
              enable_dou_ququ_runtime: bool = False) -> dict:
    source = source.resolve()
    output = output.resolve()
    kernel_root = kernel_root.resolve()
    dispatch_source = dispatch_source.resolve()
    dou_ququ_root = dou_ququ_root.resolve()
    if not source.exists():
        raise StagingError(f"source map not found: {source}")
    if output.exists():
        if not replace:
            raise StagingError(f"output already exists; use --replace: {output}")
        if output.is_dir():
            shutil.rmtree(output)
        else:
            output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_dir, extracted = _extract_if_needed(source, output.parent)
    map_label = source_dir.name
    if enable_dou_ququ_features and not re.search(r"斗蛐蛐|dou[-_ ]?ququ", map_label, re.IGNORECASE):
        raise StagingError("--enable-dou-ququ-features is restricted to the 斗蛐蛐 map")
    if enable_dou_ququ_runtime and not re.search(r"斗蛐蛐|dou[-_ ]?ququ", map_label, re.IGNORECASE):
        raise StagingError("--enable-dou-ququ-runtime is restricted to the 斗蛐蛐 map")
    shutil.copytree(source_dir, output)
    map_script = output / "MapScript.galaxy"
    document_info = output / "DocumentInfo"
    if not map_script.is_file() or not document_info.is_file():
        raise StagingError(f"staged source is missing MapScript.galaxy or DocumentInfo: {source_dir}")
    injection = _patch_map_script(
        map_script,
        enable_dou_ququ_features=enable_dou_ququ_features,
        enable_dou_ququ_runtime=enable_dou_ququ_runtime,
    )
    attribution_cleanup = _remove_source_attribution_popup(output)
    base_data = output / "Base.SC2Data"
    base_data.mkdir(parents=True, exist_ok=True)
    for name in ("LibVibeKernel.galaxy", "LibVibeKernel_h.galaxy", "LibVibeHandles.galaxy"):
        source_file = kernel_root / name
        if not source_file.is_file():
            raise StagingError(f"kernel file missing: {source_file}")
        shutil.copy2(source_file, base_data / name)
    if not dispatch_source.is_file():
        raise StagingError(f"dispatch stub missing: {dispatch_source}")
    shutil.copy2(dispatch_source, base_data / "LibVibeInvokeDispatch_active.galaxy")
    dou_ququ_files: list[str] = []
    runtime_name = "LibDouQuquRuntime.galaxy" if enable_dou_ququ_runtime else "LibDouQuquRuntimeDisabled.galaxy"
    runtime_source = dou_ququ_root / runtime_name
    if not runtime_source.is_file():
        raise StagingError(f"斗蛐蛐 runtime Galaxy file missing: {runtime_source}")
    shutil.copy2(runtime_source, base_data / runtime_name)
    dou_ququ_files.append(f"Base.SC2Data/{runtime_name}")
    if enable_dou_ququ_features:
        for name in ("LibDouQuquBehavior.galaxy", "LibDouQuquBehavior_h.galaxy"):
            source_file = dou_ququ_root / name
            if not source_file.is_file():
                raise StagingError(f"斗蛐蛐 Galaxy file missing: {source_file}")
            shutil.copy2(source_file, base_data / name)
            dou_ququ_files.append(f"Base.SC2Data/{name}")
        game_data = base_data / "GameData"
        game_data.mkdir(parents=True, exist_ok=True)
        for name in ("AttachMethodData.xml", "EffectData.xml", "AbilData.xml", "UnitData.xml", "ActorData.xml", "ButtonData.xml"):
            source_file = dou_ququ_root / name
            if not source_file.is_file():
                raise StagingError(f"斗蛐蛐 Data file missing: {source_file}")
            shutil.copy2(source_file, game_data / name)
            dou_ququ_files.append(f"Base.SC2Data/GameData/{name}")
    _write_bank_list(output / "BankList.xml")
    manifest = {
        "schemaVersion": 1,
        "stage": "27-dou-ququ-behavior-plugin" if (enable_dou_ququ_features or enable_dou_ququ_runtime) else "26-full-function-invoke",
        "mapLabel": map_label,
        "sourceMap": str(source),
        "sourceMapSha256": sha256(source) if source.is_file() else None,
        "sourceExtracted": extracted,
        "sourceDirectory": str(source_dir),
        "stagedDirectory": str(output),
        "stagedFileCount": sum(1 for item in output.rglob("*") if item.is_file()),
        "kernelFiles": [
            "Base.SC2Data/LibVibeKernel.galaxy",
            "Base.SC2Data/LibVibeKernel_h.galaxy",
            "Base.SC2Data/LibVibeHandles.galaxy",
            "Base.SC2Data/LibVibeInvokeDispatch_active.galaxy",
        ],
        "injection": injection,
        "douQuquBehavior": {
            "enabled": enable_dou_ququ_features,
            "files": dou_ququ_files,
        },
        "douQuquRuntime": {
            "enabled": enable_dou_ququ_runtime,
            "module": f"Base.SC2Data/{runtime_name}",
            "execution": "function.invoke douququ.*",
        },
        "stagedCleanup": {
            "sourceAttributionPopup": attribution_cleanup,
            "scope": "staged-copy-only",
        },
        "bankList": "GalaxyVibe players 1,2",
        "readOnlyInputs": [str(source), str(kernel_root), str(dispatch_source)],
        "forbiddenMap": "亡者之夜",
    }
    manifest_path = output.parent / "staging-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"stagedMap": str(output), "manifest": str(manifest_path), **manifest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage an isolated Vibe VM copy of a user SC2 map")
    parser.add_argument("--source", required=True, help="unpacked map directory or .SC2Map archive")
    parser.add_argument("--output", required=True, help="artifacts staging directory")
    parser.add_argument("--kernel-root", default=str(DEFAULT_KERNEL_ROOT))
    parser.add_argument("--dispatch-source", default=str(DEFAULT_DISPATCH))
    parser.add_argument("--enable-dou-ququ-features", action="store_true")
    parser.add_argument("--enable-dou-ququ-runtime", action="store_true")
    parser.add_argument("--dou-ququ-root", default=str(DEFAULT_DOU_QUQU_ROOT))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = stage_map(
            Path(args.source), Path(args.output), Path(args.kernel_root), Path(args.dispatch_source), args.replace,
            args.enable_dou_ququ_features, Path(args.dou_ququ_root), args.enable_dou_ququ_runtime,
        )
    except (OSError, ET.ParseError, StagingError) as exc:
        print(f"[stage-vm] ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
