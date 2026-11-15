from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))

from orchestrator_project_state import ProjectStateMixin
from project_policy import ensure_policy_state, load_policy_state


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
