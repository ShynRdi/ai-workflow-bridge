import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_smoke_test_is_explicit_single_turn_and_no_retry_loop():
    script = (EXT / "provider-smoke.js").read_text(encoding="utf-8")
    assert "AWB_SMOKE_OK" in script
    assert 'type: "SEND_TO_LLM"' in script
    assert "No retries or fallback" in script
    assert "No retry was attempted" in script
    assert "setInterval" not in script


def test_smoke_test_is_wired_into_sidepanel():
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    assert 'id="providerSmokeTest"' in html
    assert 'id="providerSmokeStatus"' in html
    assert '<script src="provider-smoke.js"></script>' in html


def test_extension_version_025_and_permissions_remain_optional():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.5"
    assert manifest.get("host_permissions") == []
    assert "cookies" not in manifest.get("permissions", [])
