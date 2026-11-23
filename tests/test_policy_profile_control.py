from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))

from orchestrator_project_state import ProjectStateMixin
from orchestrator_messages import MessageMixin
from project_policy import ensure_policy_state, load_policy_state
import config as config_module


class Bridge(ProjectStateMixin):
    def __init__(self, workspace: Path):
        self.config = {"workspace_root": str(workspace)}
        self.lifecycle = "paused"
        self.status = "paused"
        self.current_step = ""
        self.pending = {}
        self.command_execution_active = False
        self.events = []

    def emit_event(self, event):
        self.events.append(event)

    def emit(self, event):
        self.events.append(event)

    def state(self):
        return {"lifecycle": self.lifecycle, "status": self.status}


def test_profile_change_is_cas_bound_and_never_resumes(tmp_path: Path):
    bridge = Bridge(tmp_path)
    first = ensure_policy_state(str(tmp_path))
    bridge.change_security_policy_profile("strict", first["revision"])
    changed = load_policy_state(str(tmp_path))
    assert changed["profile"] == "strict"
    assert bridge.lifecycle == "paused"
    assert bridge.status == "paused"
    with pytest.raises(ValueError, match="stale"):
        bridge.change_security_policy_profile("balanced", first["revision"])
    assert load_policy_state(str(tmp_path))["profile"] == "strict"


@pytest.mark.parametrize("attribute, value, message", [
    ("command_execution_active", True, "executing"),
    ("pending", {"approval": {}}, "approval"),
    ("lifecycle", "recovery_required", "recovery"),
    ("lifecycle", "running", "inert"),
])
def test_profile_change_is_blocked_during_unsafe_lifecycle(
    tmp_path: Path, attribute: str, value, message: str,
):
    bridge = Bridge(tmp_path)
    state = ensure_policy_state(str(tmp_path))
    setattr(bridge, attribute, value)
    with pytest.raises(ValueError, match=message):
        bridge.change_security_policy_profile("strict", state["revision"])
    assert load_policy_state(str(tmp_path))["profile"] == "balanced"


def test_recovery_message_cannot_replay_or_change_policy(tmp_path: Path):
    class RecoveryBridge(MessageMixin):
        def __init__(self):
            self.lifecycle = "recovery_required"
            self.status = "recovery_required"
            self.events = []
            self.called = False

        def change_security_policy_profile(self, *_args):
            self.called = True

        def emit_event(self, event):
            self.events.append(event)

        def emit(self, event):
            self.events.append(event)

        def state(self):
            return {"lifecycle": self.lifecycle, "status": self.status}

    bridge = RecoveryBridge()
    bridge.handle({
        "type": "policy_profile_change",
        "desired_profile": "strict",
        "expected_policy_revision": "stale",
    })
    assert bridge.called is False
    assert any(event.get("badge") == "RECOVER!" for event in bridge.events)


def test_generic_config_cannot_change_canonical_project_policy(tmp_path: Path, monkeypatch):
    app_dir = tmp_path / "bridge-config"
    monkeypatch.setattr(config_module, "APP_DIR", app_dir)
    monkeypatch.setattr(config_module, "CONFIG_PATH", app_dir / "config.json")
    canonical = ensure_policy_state(str(tmp_path))
    saved = config_module.save_config({
        "workspace_root": str(tmp_path),
        "policy_profile": "strict",
        "profile": "strict",
    })
    assert "policy_profile" not in saved
    assert "profile" not in saved
    assert load_policy_state(str(tmp_path))["revision"] == canonical["revision"]
    assert load_policy_state(str(tmp_path))["profile"] == "balanced"
