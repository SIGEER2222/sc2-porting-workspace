"""MVP checks for the traceable static map-detail API and WebUI surface."""

import json
import threading
import urllib.error
import urllib.request

import server


def test_map_detail_contains_time_location_translation_and_source():
    payload = server.load_map_details("亡者之夜.SC2Map", "cmre", "TerranAlenger3")

    assert payload["evidence_type"] == "static"
    assert payload["map"]["sourcePath"].endswith("亡者之夜.SC2Map")
    assert payload["regions"]
    assert payload["preplaced"]
    event = next(item for item in payload["events"] if item["unit_types"])
    assert event["source"]["file"].endswith("MapScript.galaxy")
    assert isinstance(event["source"]["line"], int)
    assert event["time_text_zh"]
    assert event["content_zh"]
    assert event["unit_names_zh"]
    assert payload["adapter"]["startup"]["startingStructure"] == "CommandCenter"
    json.dumps(payload, ensure_ascii=False)


def test_map_detail_http_endpoint_and_ui_contract():
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CmreWebUIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with urllib.request.urlopen(
            base + "/api/map-details?mapName=%E4%BA%A1%E8%80%85%E4%B9%8B%E5%A4%9C.SC2Map&mapPackage=cmre&commander=TerranAlenger3",
            timeout=20,
        ) as response:
            payload = json.loads(response.read())
        assert payload["schema_version"] == "cmre-map-details.v1"
        assert payload["timeline"]

        with urllib.request.urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        assert response.status == 200
        assert 'id="map-detail-panel"' in html
        assert 'id="map-detail-timeline"' in html
        try:
            urllib.request.urlopen(
                base + "/api/map-details?mapName=missing.SC2Map&mapPackage=cmre",
                timeout=5,
            )
        except urllib.error.HTTPError as error:
            assert error.code == 404
            missing = json.loads(error.read())
            assert missing["status"] == "not_scanned"
        else:
            raise AssertionError("missing map should not be reported as scanned")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_celestial_lock_detail_is_current_and_not_cached():
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CmreWebUIHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        url = (
            base
            + "/api/map-details?mapName=%E5%A4%A9%E7%95%8C%E5%B0%81%E9%94%81.SC2Map"
            + "&mapPackage=cmre&commander=TerranAlenger3"
        )
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert payload["map"]["id"] == "天界封锁.SC2Map"
        assert payload["summary"]["preplaced_count"] == 1713
        assert payload["summary"]["region_count"] == 40
        assert len(payload["timeline"]) == 94
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
