from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))

import orchestrator_project_state
import orchestrator_response

from orchestrator_core import CoreMixin
from orchestrator_project_state import ProjectStateMixin
from orchestrator_response import ResponseMixin
from project_state import (
    initialize_project_state,
    load_project_state,
)


ROADMAP_TEXT = """Planning complete.

<<<AI_WORKFLOW_ROADMAP>>>
{
  "phases": [
    {
      "id": "P0",
      "title": "Foundation",
      "stages": ["BOOT"]
    }
  ]
}
<<<END_AI_WORKFLOW_ROADMAP>>>

READY_TO_ARM"""


class TelegramStub:
    def send_report(self, _text):
        pass


class Harness(
    ProjectStateMixin,
    ResponseMixin,
):
    extract_roadmap = staticmethod(
        CoreMixin.extract_roadmap
    )

    def __init__(
        self,
        workspace: Path,
        trace: list[str],
    ):
        self.config = {
            "workspace_root": str(workspace),
            "roadmap": [],
            "phase": "",
            "stage": "",
        }

        self.lifecycle = "planning"
        self.status = "planning"
        self.current_step = ""
        self.paused = False
        self.active_provider = "chatgpt"
        self.provider_guard = False
        self.no_contract_recoveries = 0

        self.lock = threading.RLock()
        self.telegram = TelegramStub()
        self.trace = trace

    def emit_event(self, event):
        badge = event.get("badge")

        if badge == "READY!":
            self.trace.append(
                "runtime_ready"
            )

        if badge == "FIN!":
            self.trace.append(
                "runtime_complete"
            )

    def emit(self, _event):
        pass

    def state(self):
        return {
            "lifecycle": self.lifecycle,
            "status": self.status,
        }

    @staticmethod
    def provider_name(value):
        return value


def patch_save_config(
    monkeypatch,
    bridge,
):
    def fake_save(patch):
        return {
            **bridge.config,
            **patch,
        }

    monkeypatch.setattr(
        orchestrator_response,
        "save_config",
        fake_save,
    )

    monkeypatch.setattr(
        orchestrator_project_state,
        "save_config",
        fake_save,
    )


def test_canonical_roadmap_commits_before_ready_to_arm(
    monkeypatch,
    tmp_path,
):
    trace = []

    bridge = Harness(
        tmp_path,
        trace,
    )

    patch_save_config(
        monkeypatch,
        bridge,
    )

    real_initialize = (
        orchestrator_project_state
        .initialize_project_state
    )

    def traced_initialize(
        *args,
        **kwargs,
    ):
        trace.append(
            "project_initialized"
        )

        return real_initialize(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        orchestrator_project_state,
        "initialize_project_state",
        traced_initialize,
    )

    bridge.process_assistant_response({
        "text": ROADMAP_TEXT,
    })

    assert bridge.lifecycle == "ready_to_arm"

    assert (
        trace.index("project_initialized")
        < trace.index("runtime_ready")
    )

    state = load_project_state(
        str(tmp_path)
    )

    assert state is not None
    assert (
        state["current"]["phase"]
        == "P0"
    )
    assert (
        state["current"]["stage"]
        == "BOOT"
    )


def test_canonical_completion_commits_before_runtime_complete(
    monkeypatch,
    tmp_path,
):
    initialize_project_state(
        str(tmp_path),
        [
            {
                "id": "P0",
                "title": "Foundation",
                "stages": ["BOOT"],
            }
        ],
    )

    trace = []

    bridge = Harness(
        tmp_path,
        trace,
    )

    bridge.lifecycle = "finishing"
    bridge.status = "finishing"

    patch_save_config(
        monkeypatch,
        bridge,
    )

    real_complete = (
        orchestrator_project_state
        .complete_project_state
    )

    complete_calls = []

    def traced_complete(
        *args,
        **kwargs,
    ):
        complete_calls.append(1)
        trace.append(
            "project_complete"
        )

        return real_complete(
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        orchestrator_project_state,
        "complete_project_state",
        traced_complete,
    )

    bridge.process_assistant_response({
        "text": (
            "Final verification complete.\n"
            "<<<AI_WORKFLOW_PROJECT_DONE>>>"
        ),
    })

    assert bridge.lifecycle == "complete"
    assert bridge.status == "complete"

    assert (
        trace.index("project_complete")
        < trace.index("runtime_complete")
    )

    # No duplicate completion/history transition.
    assert len(complete_calls) == 1

    state = load_project_state(
        str(tmp_path)
    )

    assert state is not None
    assert state["status"] == "complete"
    assert state["current"] is None
