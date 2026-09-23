from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))

import diagnostics


def _configure_paths(monkeypatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "bridge-state"
    app_dir.mkdir()

    monkeypatch.setattr(diagnostics, "APP_DIR", app_dir)
    monkeypatch.setattr(diagnostics, "CONFIG_PATH", app_dir / "config.json")


def _check_by_id(result, check_id):
    return next(item for item in result["checks"] if item["id"] == check_id)


def test_diagnostics_accepts_local_writable_workspace(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = diagnostics.collect_diagnostics(
        {
            "workspace_root": str(workspace),
            "bot_token": "should-never-appear",
        }
    )

    assert result["schema_version"] == 1
    assert _check_by_id(result, "python")["status"] == "pass"
    assert _check_by_id(result, "workspace")["status"] == "pass"

    serialized = json.dumps(result)
    assert "should-never-appear" not in serialized


def test_diagnostics_warns_when_workspace_is_not_configured(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)

    result = diagnostics.collect_diagnostics({"workspace_root": ""})

    workspace = _check_by_id(result, "workspace")
    assert workspace["status"] == "warn"
    assert result["overall"] in {"warn", "pass"}


def test_diagnostics_fails_for_missing_configured_workspace(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)

    missing = tmp_path / "does-not-exist"

    result = diagnostics.collect_diagnostics(
        {"workspace_root": str(missing)}
    )

    workspace = _check_by_id(result, "workspace")

    assert workspace["status"] == "fail"
    assert result["overall"] == "fail"


def test_native_message_layer_exposes_diagnostics_action():
    source = (HOST / "orchestrator_messages.py").read_text(encoding="utf-8")

    assert 'msg_type == "diagnostics"' in source
    assert '"kind": "diagnostics_result"' in source
    assert '"request_id": str(message.get("request_id") or "")' in source
    assert "collect_diagnostics(self.config)" in source
