import json
import threading
import urllib.request
from pathlib import Path

import server
from galaxy_script_lab import validate_source


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger" / "startup" / "LibDouQuquUser.galaxy"


def test_real_user_galaxy_template_has_a_valid_editable_entrypoint():
    source = TEMPLATE.read_text(encoding="utf-8")
    result = validate_source(source)
    assert result["valid"] is True
    assert result["function_id"] == "douququ.user.run"
    assert "UnitCreate" in source
    assert "PlayerModifyPropertyInt" in source


def test_user_galaxy_validation_rejects_bootstrap_and_unbalanced_source():
    result = validate_source(
        'include "LibVibeKernel_h"\n'
        'void InitMap() {\n'
        'string libDouQuquUser_gf_Run(string argsJson) { return "x";\n'
    )
    assert result["valid"] is False
    messages = " ".join(item["message"] for item in result["diagnostics"])
    assert "InitMap" in messages
    assert "大括号" in messages


def test_galaxy_script_http_load_validate_and_save(tmp_path, monkeypatch):
    template = tmp_path / "LibDouQuquUser.galaxy"
    template.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    artifact = tmp_path / "artifact" / "LibDouQuquUser.galaxy"
    stage_root = tmp_path / "stage"
    monkeypatch.setattr(server, "DOU_QUQU_USER_SCRIPT_TEMPLATE", template)
    monkeypatch.setattr(server, "DOU_QUQU_USER_SCRIPT_ARTIFACT", artifact)
    monkeypatch.setattr(server, "DOU_QUQU_USER_SCRIPT_STAGE_ROOT", stage_root)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CmreWebUIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/api/vibe/galaxy-script"
        with urllib.request.urlopen(url, timeout=5) as response:
            loaded = json.loads(response.read())
        assert response.status == 200
        assert loaded["function_id"] == "douququ.user.run"
        source = loaded["source"].replace("mineralDelta =", "mineralDelta =")
        request = urllib.request.Request(
            url + "/validate",
            data=json.dumps({"source": source}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            validated = json.loads(response.read())
        assert validated["valid"] is True
        request = urllib.request.Request(
            url + "/save",
            data=json.dumps({"source": source}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            saved = json.loads(response.read())
        assert saved["success"] is True
        assert artifact.is_file()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
