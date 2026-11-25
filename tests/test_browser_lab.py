from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_browser_lab_preparation_keeps_production_extension_unchanged(tmp_path):
    spec = importlib.util.spec_from_file_location("browser_lab", ROOT / "tests" / "browser_lab.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    originals = {p: p.read_bytes() for p in (ROOT / "extension").glob("*") if p.is_file()}
    root = tmp_path / "lab"
    lab.prepare(root)
    data = lab.metadata(root)
    manifest = json.loads((root / "extension" / "manifest.json").read_text())
    assert manifest["host_permissions"] == []
    assert manifest["optional_host_permissions"] == ["http://127.0.0.1/*"]
    assert data["host"] != lab.PRODUCTION_HOST
    config = json.loads((root / "state" / "config.json").read_text())
    assert config["workspace_root"] == str(root / "workspace")
    assert config["provider_id"] == "mock"
    assert config["auto_run_low_risk"] is False
    assert (root / "workspace" / ".git").is_dir()
    assert str(root / "state") in (root / "launcher.sh").read_text()
    for name in ("providers.js", "conversation-identity.js", "background.js", "sidepanel.js"):
        subprocess.run(["node", "--check", str(root / "extension" / name)], check=True)
    fixture_js = tmp_path / "fixture.js"
    fixture_js.write_text(lab.HTML.split("<script>", 1)[1].split("</script>", 1)[0])
    subprocess.run(["node", "--check", str(fixture_js)], check=True)
    assert all(p.read_bytes() == content for p, content in originals.items())
    with pytest.raises(FileExistsError):
        lab.prepare(root)
