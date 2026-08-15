#!/usr/bin/env python3
"""Local WebUI and runtime-dependency launcher for an unpacked SC2 map.

The map archive remains immutable.  Each launch gets a disposable debug-mod
shim under artifacts/; selected installed mods are declared in that shim's
DocumentInfo and are therefore loaded only for that SC2 session.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_ROOT = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage26-full-function-invoke"
    / "map-debug-runtime"
)
DEFAULT_MAP = (
    REPO_ROOT
    / "artifacts"
    / "projects"
    / "cmre-porting"
    / "stage26-full-function-invoke"
    / "input-map-original.SC2Map"
)
DEFAULT_DEBUG_MOD = REPO_ROOT / "tools" / "galaxy-vibe" / "galaxy-debug-mod"
DEFAULT_LAUNCHER = REPO_ROOT / "tools" / "galaxy-vibe" / "launch-galaxy-vibe.ps1"
DEFAULT_VERIFY = REPO_ROOT / "tools" / "cmre-webui" / "debug_map_smoke.vtest"
EXTRACTOR = REPO_ROOT / "tools" / "mpq" / "scripts" / "extract_mpq.py"


class RuntimeConfigError(RuntimeError):
    """Raised when a runtime dependency cannot be resolved safely."""


def _absolute(path: str | Path, base: Path = REPO_ROOT) -> Path:
    value = Path(path)
    return value if value.is_absolute() else (base / value).resolve()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _xml_root(path: Path) -> ET.Element:
    try:
        return ET.fromstring(_read_text(path))
    except (ET.ParseError, OSError) as exc:
        raise RuntimeConfigError(f"无法解析 XML: {path}: {exc}") from exc


def _document_dependencies(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    root = _xml_root(path)
    result: list[dict[str, str]] = []
    for value in root.findall("./Dependencies/Value"):
        raw = (value.text or "").strip()
        if not raw:
            continue
        descriptor, separator, target = raw.partition(",")
        if not separator:
            target = descriptor
            descriptor = ""
        result.append({"raw": raw, "descriptor": descriptor, "path": target})
    return result


def _runtime_path(path: Path, sc2_root: Path) -> str | None:
    """Map an installed/source package to a SC2-relative dependency path."""
    try:
        return path.resolve().relative_to(sc2_root.resolve()).as_posix()
    except ValueError:
        pass
    parts = list(path.resolve().parts)
    for index, part in enumerate(parts):
        if part.casefold() == "mods" and index < len(parts) - 1:
            return PurePosixPath(*parts[index:]).as_posix()
    return None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _copy_debug_mod(source: Path, destination: Path) -> None:
    """Copy the debug runtime while omitting alternate generated dispatches.

    The debug mod contains map-bundle generated adapters plus two optional
    rollout dispatch files per bundle.  The normal dispatch does not include
    either rollout file, and copying them is unreliable on Windows for the
    nested Chinese bundle paths.  Keep the adapters and core files intact,
    but leave the unused alternatives out of each session shim.
    """

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name.casefold() in {
                "libvibeinvokedispatch_tier100.galaxy",
                "libvibeinvokedispatch_tier1000.galaxy",
            }
        }

    try:
        shutil.copytree(source, destination, ignore=ignore)
    except (OSError, shutil.Error) as exc:
        raise RuntimeConfigError(f"复制 debug mod 失败: {exc}") from exc


@dataclass(frozen=True)
class RuntimeConfig:
    repo_root: Path
    map_path: Path
    sc2_root: Path | None
    mod_roots: tuple[Path, ...]
    debug_mod: Path
    artifact_root: Path
    launcher: Path
    verify_default: Path | None


class MapRuntime:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._launcher_process: subprocess.Popen[str] | None = None
        self._session: dict[str, Any] | None = None

    @property
    def map_path(self) -> Path:
        path = self.config.map_path
        if not path.exists():
            raise RuntimeConfigError(f"地图不存在: {path}")
        return path

    def _extract_dir(self) -> Path:
        source = self.map_path
        if source.is_dir():
            return source
        if source.suffix.casefold() not in {".sc2map", ".sc2mod"}:
            raise RuntimeConfigError(f"地图输入必须是 .SC2Map 文件或已解包目录: {source}")
        target = self.config.artifact_root / "extracted" / source.name
        marker = target / "DocumentInfo"
        if not marker.is_file():
            if not EXTRACTOR.is_file():
                raise RuntimeConfigError(f"解包工具不存在: {EXTRACTOR}")
            target.parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(EXTRACTOR), str(source), str(target), "*"]
            completed = subprocess.run(
                command,
                cwd=self.config.repo_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0 or not marker.is_file():
                detail = (completed.stdout + "\n" + completed.stderr).strip()[-2000:]
                raise RuntimeConfigError(f"地图解包失败 (exit={completed.returncode}): {detail}")
        return target

    def map_manifest(self) -> dict[str, Any]:
        source = self.map_path
        extracted = self._extract_dir()
        document_info = extracted / "DocumentInfo"
        dependencies = _document_dependencies(document_info)
        files = [p for p in extracted.rglob("*") if p.is_file()]
        return {
            "mapPath": str(source),
            "mapName": source.name,
            "sourceKind": "directory" if source.is_dir() else "archive",
            "sha256": _hash_file(source) if source.is_file() else None,
            "extractedPath": str(extracted),
            "fileCount": len(files),
            "dependencies": dependencies,
            "readOnly": True,
        }

    def mod_catalog(self) -> list[dict[str, Any]]:
        sc2_root = self.config.sc2_root
        if sc2_root is None:
            return []
        records: dict[str, dict[str, Any]] = {}
        for root in self.config.mod_roots:
            if not root.is_dir():
                continue
            for mod_path in sorted(root.rglob("*.SC2Mod")):
                if not mod_path.is_dir():
                    continue
                runtime_path = _runtime_path(mod_path, sc2_root)
                if not runtime_path or not runtime_path.casefold().startswith("mods/"):
                    continue
                record = {
                    "id": runtime_path,
                    "name": mod_path.name.removesuffix(".SC2Mod"),
                    "runtimePath": runtime_path,
                    "sourcePath": str(mod_path),
                    "installed": (sc2_root / Path(*runtime_path.split("/"))).is_dir(),
                    "dependencies": _document_dependencies(mod_path / "DocumentInfo"),
                }
                previous = records.get(runtime_path)
                if previous is None or str(mod_path).casefold().startswith(str(sc2_root).casefold()):
                    records[runtime_path] = record
        return sorted(records.values(), key=lambda item: (item["name"].casefold(), item["id"].casefold()))

    def _selected_mods(self, selected_ids: list[str]) -> list[dict[str, Any]]:
        catalog = {item["id"]: item for item in self.mod_catalog()}
        unknown = [item for item in selected_ids if item not in catalog]
        if unknown:
            raise RuntimeConfigError(f"未知或未安装 Mod: {', '.join(unknown)}")
        selected = [catalog[item] for item in dict.fromkeys(selected_ids)]
        if self.config.sc2_root is None and selected:
            raise RuntimeConfigError("选择 Mod 前必须提供 SC2_ROOT 或 --sc2-root")
        for item in selected:
            installed_path = self.config.sc2_root / Path(*item["runtimePath"].split("/"))
            if not installed_path.is_dir():
                raise RuntimeConfigError(f"运行时依赖未安装: {item['runtimePath']}")
        return selected

    def prepare(self, selected_ids: list[str]) -> dict[str, Any]:
        selected = self._selected_mods(selected_ids)
        if not self.config.debug_mod.is_dir():
            raise RuntimeConfigError(f"debug mod 不存在: {self.config.debug_mod}")
        map_info = self.map_manifest()
        session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
        session_root = self.config.artifact_root / "sessions" / session_id
        shim = session_root / "GalaxyVibeDebugRuntime.SC2Mod"
        session_root.mkdir(parents=True, exist_ok=True)
        _copy_debug_mod(self.config.debug_mod, shim)

        doc_root = ET.Element("DocInfo")
        dependencies = ET.SubElement(doc_root, "Dependencies")
        for item in selected:
            ET.SubElement(dependencies, "Value").text = f"file:{item['runtimePath']}"
        ET.ElementTree(doc_root).write(shim / "DocumentInfo", encoding="utf-8", xml_declaration=True)

        result = {
            "sessionId": session_id,
            "createdAt": _utc_now(),
            "map": map_info,
            "mapDependencies": map_info["dependencies"],
            "selectedMods": selected,
            "runtimeDependencies": [f"file:{item['runtimePath']}" for item in selected],
            "shimPath": str(shim),
            "readOnlyInputs": [str(self.map_path), str(self.config.debug_mod)],
        }
        session_json = session_root / "session.json"
        session_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _powershell(self) -> str:
        configured = os.environ.get("POWERSHELL_EXE", "").strip()
        if configured:
            return configured
        return shutil.which("pwsh") or shutil.which("powershell") or "pwsh"

    def _launch_args(self, prepared: dict[str, Any], port: int, verify: str | None) -> list[str]:
        if not self.config.launcher.is_file():
            raise RuntimeConfigError(f"approved launcher 不存在: {self.config.launcher}")
        args = [
            self._powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.config.launcher),
            "-Port",
            str(port),
            "-Map",
            str(self.map_path),
            "-ModPath",
            str(prepared["shimPath"]),
        ]
        verify_path = _absolute(verify, self.config.repo_root) if verify else self.config.verify_default
        if verify_path:
            if not verify_path.is_file():
                raise RuntimeConfigError(f"验证场景不存在: {verify_path}")
            args.extend(["-Verify", str(verify_path)])
        return args

    def launch(self, selected_ids: list[str], port: int, verify: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._launcher_process and self._launcher_process.poll() is None:
                raise RuntimeConfigError("已有本 WebUI 会话正在启动")
            prepared = self.prepare(selected_ids)
            session_root = Path(prepared["shimPath"]).parent
            stdout_path = session_root / "launcher.stdout.log"
            stderr_path = session_root / "launcher.stderr.log"
            stdout = stdout_path.open("w", encoding="utf-8", buffering=1)
            stderr = stderr_path.open("w", encoding="utf-8", buffering=1)
            args = self._launch_args(prepared, port, verify)
            try:
                process = subprocess.Popen(
                    args,
                    cwd=self.config.repo_root,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError:
                stdout.close()
                stderr.close()
                raise
            self._launcher_process = process
            self._session = {
                **prepared,
                "port": port,
                "verify": str(_absolute(verify, self.config.repo_root)) if verify else str(self.config.verify_default or ""),
                "launcherPid": process.pid,
                "launcherArgs": args,
                "stdoutPath": str(stdout_path),
                "stderrPath": str(stderr_path),
            }
            (session_root / "session.json").write_text(
                json.dumps(self._session, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return self.status()

    def status(self) -> dict[str, Any]:
        process = self._launcher_process
        return_code = process.poll() if process else None
        session = self._session or {}
        port = int(session.get("port", 0) or 0)
        ready = False
        if port:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.15)
                ready = sock.connect_ex(("127.0.0.1", port)) == 0
        tail = ""
        stdout_path = session.get("stdoutPath")
        if stdout_path and Path(stdout_path).is_file():
            tail = _read_text(Path(stdout_path))[-4000:]
        return {
            "active": bool(process and return_code is None),
            "launcherPid": process.pid if process else session.get("launcherPid"),
            "launcherExitCode": return_code,
            "runtimeReady": ready,
            "port": port,
            "sessionId": session.get("sessionId"),
            "selectedMods": [item.get("id") for item in session.get("selectedMods", [])],
            "tail": tail,
        }


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class DebugMapHandler(BaseHTTPRequestHandler):
    runtime: MapRuntime
    static_root = Path(__file__).with_name("webui")

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[debug-map-webui] " + (format % args) + "\n")

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeConfigError(f"请求 JSON 无效: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeConfigError("请求体必须是 JSON 对象")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/manifest":
                _json_response(self, self.runtime.map_manifest())
                return
            if path == "/api/mods":
                _json_response(self, {"mods": self.runtime.mod_catalog()})
                return
            if path == "/api/status":
                _json_response(self, self.runtime.status())
                return
            if path == "/api/health":
                _json_response(self, {"ok": True})
                return
            filename = "debug-map.html" if path in {"/", ""} else path.lstrip("/")
            if "/" in filename or filename not in {"debug-map.html", "debug-map.js", "debug-map.css"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            asset = self.static_root / filename
            if not asset.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
            }[asset.suffix]
            body = asset.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except RuntimeConfigError as exc:
            _json_response(self, {"ok": False, "error": str(exc)}, 400)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body()
            selected = body.get("mods", [])
            if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
                raise RuntimeConfigError("mods 必须是字符串数组")
            if path == "/api/prepare":
                _json_response(self, {"ok": True, "session": self.runtime.prepare(selected)})
                return
            if path == "/api/launch":
                port = int(body.get("port", 0) or 0)
                if port < 1 or port > 65535:
                    raise RuntimeConfigError("port 必须在 1..65535")
                verify = body.get("verify") or None
                _json_response(self, {"ok": True, "status": self.runtime.launch(selected, port, verify)})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (RuntimeConfigError, ValueError) as exc:
            _json_response(self, {"ok": False, "error": str(exc)}, 400)


def _default_mod_roots(sc2_root: Path | None) -> tuple[Path, ...]:
    roots = [REPO_ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Mods"]
    if sc2_root:
        roots.insert(0, sc2_root / "Mods")
    return tuple(roots)


def _config_from_args(args: argparse.Namespace) -> RuntimeConfig:
    sc2_value = args.sc2_root or os.environ.get("SC2_ROOT", "").strip()
    sc2_root = _absolute(sc2_value) if sc2_value else None
    mod_roots = tuple(_absolute(item) for item in args.mod_root) if args.mod_root else _default_mod_roots(sc2_root)
    verify = _absolute(args.verify) if args.verify else (DEFAULT_VERIFY if DEFAULT_VERIFY.is_file() else None)
    return RuntimeConfig(
        repo_root=REPO_ROOT,
        map_path=_absolute(args.map),
        sc2_root=sc2_root,
        mod_roots=mod_roots,
        debug_mod=_absolute(args.debug_mod),
        artifact_root=_absolute(args.artifact_root),
        launcher=_absolute(args.launcher),
        verify_default=verify,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WebUI + on-demand runtime dependencies for a local SC2 map")
    parser.add_argument("--map", default=str(DEFAULT_MAP), help=".SC2Map archive or unpacked map directory")
    parser.add_argument("--sc2-root", default="", help="SC2 installation root; also reads SC2_ROOT")
    parser.add_argument("--mod-root", action="append", default=[], help="additional mod catalog root (repeatable)")
    parser.add_argument("--debug-mod", default=str(DEFAULT_DEBUG_MOD))
    parser.add_argument("--artifact-root", default=str(DEFAULT_ARTIFACT_ROOT))
    parser.add_argument("--launcher", default=str(DEFAULT_LAUNCHER))
    parser.add_argument("--verify", default="", help="default .vtest used by Launch")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--prepare", action="store_true", help="prepare a shim and print JSON, without starting WebUI")
    parser.add_argument("--mods", default="", help="comma-separated runtime dependency IDs for --prepare")
    args = parser.parse_args(argv)
    runtime = MapRuntime(_config_from_args(args))
    if args.prepare:
        selected = [item.strip() for item in args.mods.split(",") if item.strip()]
        print(json.dumps(runtime.prepare(selected), ensure_ascii=False, indent=2))
        return 0
    DebugMapHandler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), DebugMapHandler)
    print(f"debug-map-webui: http://{args.host}:{args.port}/", flush=True)
    print(f"map: {runtime.map_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
