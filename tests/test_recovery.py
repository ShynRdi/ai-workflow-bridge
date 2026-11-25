from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))

import storage
from recovery import (
    build_runtime_snapshot,
    recovery_summary,
    requires_recovery,
)


def test_runtime_state_round_trip(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "bridge.sqlite3"

    monkeypatch.setattr(storage, "DB_PATH", db_path)
    monkeypatch.setattr(storage, "ensure_app_dir", lambda: None)

    store = storage.Store()

    payload = {
        "version": 1,
        "lifecycle": "running",
        "status": "waiting_llm",
    }

    store.put_runtime_state("orchestrator", payload)

    assert store.get_runtime_state("orchestrator") == payload

    store.clear_runtime_state("orchestrator")

    assert store.get_runtime_state("orchestrator") is None


def test_pending_approvals_survive_store_restart(
    monkeypatch,
    tmp_path: Path,
):
    db_path = tmp_path / "bridge.sqlite3"

    monkeypatch.setattr(storage, "DB_PATH", db_path)
    monkeypatch.setattr(storage, "ensure_app_dir", lambda: None)

    first = storage.Store()

    first.put_approval(
        "approval-1",
        {
            "approval_id": "approval-1",
            "summary": "Protected action",
            "command": "git push",
            "impact": "remote mutation",
        },
    )

    second = storage.Store()

    approvals = second.list_pending_approvals()

    assert len(approvals) == 1
    assert approvals[0]["approval_id"] == "approval-1"
    assert approvals[0]["command"] == "git push"


def test_running_state_requires_explicit_recovery():
    snapshot = build_runtime_snapshot(
        lifecycle="running",
        status="waiting_llm",
        current_step="Waiting for ChatGPT",
        paused=False,
        active_provider="chatgpt",
        provider_guard=False,
    )

    assert requires_recovery(snapshot) is True


def test_idle_and_complete_states_do_not_require_recovery():
    idle = build_runtime_snapshot(
        lifecycle="idle",
        status="idle",
        current_step="",
        paused=False,
        active_provider="chatgpt",
        provider_guard=False,
    )

    complete = build_runtime_snapshot(
        lifecycle="complete",
        status="complete",
        current_step="Project closed out",
        paused=True,
        active_provider="chatgpt",
        provider_guard=False,
    )

    assert requires_recovery(idle) is False
    assert requires_recovery(complete) is False


def test_recovery_snapshot_does_not_preserve_executable_continuation():
    snapshot = build_runtime_snapshot(
        lifecycle="running",
        status="waiting_approval",
        current_step="Awaiting approval",
        paused=False,
        active_provider="chatgpt",
        provider_guard=False,
        pending={
            "abc": {
                "approval_id": "abc",
                "summary": "Run migration",
                "command": "python migrate.py",
                "impact": "database mutation",
                "continuation": {
                    "kind": "command",
                    "index": 4,
                    "dangerous_internal_state": "DO NOT RESTORE",
                },
            },
        },
    )

    approval = snapshot["pending_approvals"][0]

    assert approval["approval_id"] == "abc"
    assert approval["command"] == "python migrate.py"
    assert "continuation" not in approval


def test_recovery_summary_preserves_review_context_only():
    snapshot = build_runtime_snapshot(
        lifecycle="running",
        status="waiting_approval",
        current_step="Awaiting approval",
        paused=False,
        active_provider="claude",
        provider_guard=True,
        pending={
            "abc": {
                "approval_id": "abc",
                "summary": "Protected action",
                "command": "git push",
                "impact": "remote mutation",
            },
        },
    )

    result = recovery_summary(snapshot)

    assert result["required"] is True
    assert result["previous_status"] == "waiting_approval"
    assert result["active_provider"] == "claude"
    assert result["provider_guard"] is True
    assert len(result["pending_approvals"]) == 1


class FakeStore:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.events = []
        self.runtime_writes = []

    def get_runtime_state(self, key):
        return self.snapshot

    def put_runtime_state(self, key, payload):
        self.runtime_writes.append((key, payload))

    def event(self, kind, payload):
        self.events.append((kind, payload))

    def expire_pending_approvals(self):
        self.expired_pending = True


def test_core_restore_enters_fail_closed_recovery_state():
    from orchestrator import Orchestrator
    from safety import RunBudget

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.store = FakeStore(
        build_runtime_snapshot(
            lifecycle="running",
            status="waiting_llm",
            current_step="Waiting for ChatGPT",
            paused=False,
            active_provider="chatgpt",
            provider_guard=False,
        )
    )

    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = False
    bridge.lifecycle = "setup"
    bridge.status = "idle"
    bridge.current_step = ""
    bridge.pending = {}
    bridge.budget = RunBudget()
    bridge.recovery_context = None

    bridge._restore_runtime_state()

    assert bridge.paused is True
    assert bridge.lifecycle == "recovery_required"
    assert bridge.status == "recovery_required"
    assert bridge.recovery_context["required"] is True
    assert (
        bridge.recovery_context["previous_status"]
        == "waiting_llm"
    )


def test_recovery_state_is_exposed_publicly():
    from orchestrator import Orchestrator
    from safety import RunBudget

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.paused = True
    bridge.status = "recovery_required"
    bridge.lifecycle = "recovery_required"
    bridge.current_step = "Interrupted workflow"
    bridge.config = {}
    bridge.active_provider = "chatgpt"
    bridge.pending = {}
    bridge.provider_guard = False
    bridge.budget = RunBudget()
    bridge.recovery_context = {
        "required": True,
        "previous_status": "running",
    }

    state = bridge.state()

    assert state["recovery"]["required"] is True
    assert state["lifecycle"] == "recovery_required"


def test_recovery_gate_blocks_project_actions():
    from orchestrator import Orchestrator
    from safety import RunBudget

    emitted = []

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.emit = emitted.append
    bridge.store = FakeStore()
    bridge.config = {}
    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = True
    bridge.lifecycle = "recovery_required"
    bridge.status = "recovery_required"
    bridge.current_step = "Interrupted workflow"
    bridge.pending = {}
    bridge.download_waiters = {}
    bridge.recovery_context = {
        "required": True,
        "previous_status": "waiting_llm",
    }
    bridge.budget = RunBudget()

    bridge.handle({
        "type": "build_controller_prompt",
        "provider": "chatgpt",
    })

    assert bridge.lifecycle == "recovery_required"
    assert bridge.status == "recovery_required"

    assert any(
        item.get("kind") == "error"
        and item.get("status") == "recovery_required"
        for item in emitted
        if isinstance(item, dict)
    )


def test_recovery_gate_allows_get_state():
    from orchestrator import Orchestrator
    from safety import RunBudget

    emitted = []

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.emit = emitted.append
    bridge.store = FakeStore()
    bridge.config = {}
    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = True
    bridge.lifecycle = "recovery_required"
    bridge.status = "recovery_required"
    bridge.current_step = "Interrupted workflow"
    bridge.pending = {}
    bridge.download_waiters = {}
    bridge.recovery_context = {
        "required": True,
        "previous_status": "waiting_llm",
    }
    bridge.budget = RunBudget()

    bridge.handle({"type": "get_state"})

    states = [
        item for item in emitted
        if isinstance(item, dict)
        and item.get("kind") == "state"
    ]

    assert len(states) == 1
    assert (
        states[0]["state"]["lifecycle"]
        == "recovery_required"
    )



def test_recovery_required_state_survives_another_restart():
    snapshot = build_runtime_snapshot(
        lifecycle="recovery_required",
        status="recovery_required",
        current_step="Interrupted workflow requires recovery review",
        paused=True,
        active_provider="chatgpt",
        provider_guard=False,
    )

    assert requires_recovery(snapshot) is True



def _make_recovery_bridge():
    import threading
    from orchestrator import Orchestrator
    from safety import RunBudget

    emitted = []
    sent = []

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.emit = emitted.append
    bridge.store = FakeStore()
    bridge.store.expired_pending = False
    bridge.config = {}
    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = True
    bridge.lifecycle = "recovery_required"
    bridge.status = "recovery_required"
    bridge.current_step = "Interrupted workflow"
    bridge.pending = {
        "old-approval": {
            "approval_id": "old-approval",
            "summary": "Protected action",
            "command": "git push",
            "impact": "remote mutation",
            "continuation": {
                "kind": "command",
                "index": 2,
            },
        },
    }
    bridge.download_waiters = {}
    bridge.recovery_context = {
        "required": True,
        "previous_lifecycle": "running",
        "previous_status": "waiting_approval",
        "previous_step": "Awaiting approval",
        "active_provider": "chatgpt",
        "provider_guard": False,
        "pending_approvals": [
            {
                "approval_id": "old-approval",
                "summary": "Protected action",
                "command": "git push",
                "impact": "remote mutation",
            },
        ],
    }
    bridge.no_contract_recoveries = 1
    bridge.budget = RunBudget()
    bridge.lock = threading.RLock()
    bridge._send_result_to_chatgpt = sent.append

    return bridge, emitted, sent


def test_prepare_recovery_never_replays_or_sends_prompt():
    bridge, emitted, sent = _make_recovery_bridge()

    bridge.handle({
        "type": "recovery_prepare",
        "tab_id": 42,
        "provider": "chatgpt",
    })

    assert bridge.lifecycle == "idle"
    assert bridge.status == "idle"
    assert bridge.paused is False
    assert bridge.pending == {}
    assert bridge.recovery_context is None
    assert bridge.store.expired_pending is True
    assert sent == []

    assert any(
        item.get("kind") == "recovery_resolved"
        and item.get("decision") == "prepare"
        for item in emitted
        if isinstance(item, dict)
    )


def test_discard_recovery_keeps_project_paused():
    bridge, emitted, sent = _make_recovery_bridge()

    bridge.handle({"type": "recovery_discard"})

    assert bridge.lifecycle == "paused"
    assert bridge.status == "paused"
    assert bridge.paused is True
    assert bridge.pending == {}
    assert bridge.recovery_context is None
    assert bridge.store.expired_pending is True
    assert sent == []


def test_prepare_recovery_does_not_clear_provider_guard():
    bridge, emitted, sent = _make_recovery_bridge()

    bridge.provider_guard = True

    bridge.handle({
        "type": "recovery_prepare",
        "tab_id": 42,
        "provider": "chatgpt",
    })

    assert bridge.lifecycle == "paused"
    assert bridge.status == "provider_guard"
    assert bridge.paused is True
    assert bridge.provider_guard is True
    assert sent == []



def test_prepare_recovery_requires_explicit_browser_binding():
    bridge, emitted, sent = _make_recovery_bridge()

    bridge.handle({
        "type": "recovery_prepare",
        "provider": "chatgpt",
    })

    assert bridge.lifecycle == "recovery_required"
    assert bridge.status == "recovery_required"
    assert bridge.recovery_context is not None
    assert sent == []


def test_prepare_recovery_rejects_provider_switch():
    bridge, emitted, sent = _make_recovery_bridge()

    bridge.handle({
        "type": "recovery_prepare",
        "tab_id": 42,
        "provider": "claude",
    })

    assert bridge.lifecycle == "recovery_required"
    assert bridge.status == "recovery_required"
    assert bridge.active_provider == "chatgpt"
    assert bridge.recovery_context is not None
    assert sent == []


def test_run_budget_round_trip_preserves_turns():
    from safety import RunBudget

    first = RunBudget()
    first.reset("chatgpt")
    first.record_send()
    first.record_send()

    payload = first.export_state()

    second = RunBudget()

    assert second.restore_state(payload) is True

    public = second.public({
        "max_turns_per_session": 25,
        "max_turns_per_hour": 20,
        "max_runtime_minutes": 90,
    })

    assert public["provider_id"] == "chatgpt"
    assert public["session_turns"] == 2
    assert public["turns_last_hour"] == 2


def test_provider_guard_survives_restart_fail_closed():
    from orchestrator import Orchestrator
    from safety import RunBudget

    budget = RunBudget()
    budget.reset("chatgpt")
    budget.block("provider safety signal")

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.store = FakeStore(
        build_runtime_snapshot(
            lifecycle="paused",
            status="provider_guard",
            current_step="Provider guard active",
            paused=True,
            active_provider="chatgpt",
            provider_guard=True,
            budget=budget.export_state(),
        )
    )

    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = False
    bridge.lifecycle = "setup"
    bridge.status = "idle"
    bridge.current_step = ""
    bridge.pending = {}
    bridge.budget = RunBudget()
    bridge.recovery_context = None

    bridge._restore_runtime_state()

    assert bridge.provider_guard is True
    assert bridge.paused is True
    assert bridge.lifecycle == "paused"
    assert bridge.status == "provider_guard"

    decision = bridge.budget.decision({})

    assert decision["allowed"] is False
    assert decision["hard"] is True


def test_budget_exhausted_state_survives_restart():
    from orchestrator import Orchestrator
    from safety import RunBudget

    budget = RunBudget()
    budget.reset("chatgpt")
    budget.record_send()
    budget.record_send()

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.store = FakeStore(
        build_runtime_snapshot(
            lifecycle="budget_exhausted",
            status="budget_exhausted",
            current_step="AI-turn budget exhausted",
            paused=True,
            active_provider="chatgpt",
            provider_guard=False,
            budget=budget.export_state(),
        )
    )

    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = False
    bridge.lifecycle = "setup"
    bridge.status = "idle"
    bridge.current_step = ""
    bridge.pending = {}
    bridge.budget = RunBudget()
    bridge.recovery_context = None

    bridge._restore_runtime_state()

    assert bridge.paused is True
    assert bridge.lifecycle == "budget_exhausted"
    assert bridge.status == "budget_exhausted"
    assert bridge.budget.public({})["session_turns"] == 2


def test_user_paused_state_survives_restart():
    from orchestrator import Orchestrator
    from safety import RunBudget

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.store = FakeStore(
        build_runtime_snapshot(
            lifecycle="paused",
            status="paused",
            current_step="Workflow paused by user",
            paused=True,
            active_provider="claude",
            provider_guard=False,
        )
    )

    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = False
    bridge.lifecycle = "setup"
    bridge.status = "idle"
    bridge.current_step = ""
    bridge.pending = {}
    bridge.budget = RunBudget()
    bridge.recovery_context = None

    bridge._restore_runtime_state()

    assert bridge.active_provider == "claude"
    assert bridge.paused is True
    assert bridge.lifecycle == "paused"
    assert bridge.status == "paused"


def test_runtime_snapshot_persists_budget_state():
    from orchestrator import Orchestrator
    from safety import RunBudget

    bridge = Orchestrator.__new__(Orchestrator)

    bridge.lifecycle = "running"
    bridge.status = "waiting_llm"
    bridge.current_step = "Waiting"
    bridge.paused = False
    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.pending = {}
    bridge.budget = RunBudget()

    bridge.budget.record_send()

    snapshot = bridge._runtime_snapshot()

    assert snapshot["version"] == 2
    assert snapshot["budget"]["provider_id"] == "chatgpt"
    assert len(snapshot["budget"]["turn_timestamps"]) == 1


def test_reset_budget_after_discard_never_resumes_or_replays():
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.handle({"type": "recovery_discard"})
    bridge.budget.record_send()
    previous_step = bridge.current_step

    bridge.handle({"type": "reset_session"})

    assert bridge.lifecycle == "paused"
    assert bridge.status == "paused"
    assert bridge.paused is True
    assert bridge.current_step == previous_step
    assert bridge.pending == {}
    assert bridge.budget.public(bridge.config)["session_turns"] == 0
    assert sent == []
    assert not any(event.get("kind") == "send_to_llm" for event in emitted)


def test_reset_budget_does_not_bypass_unreviewed_recovery():
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.handle({"type": "reset_session"})

    assert bridge.lifecycle == "recovery_required"
    assert bridge.paused is True
    assert bridge.recovery_context is not None
    assert bridge.pending
    assert sent == []


def test_reset_budget_clears_acknowledged_guard_without_resuming():
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.provider_guard = True
    bridge.budget.block("rate limit")
    bridge.handle({"type": "recovery_discard"})
    bridge.handle({"type": "reset_session"})

    assert bridge.provider_guard is False
    assert bridge.lifecycle == "paused"
    assert bridge.status == "paused"
    assert bridge.paused is True
    assert sent == []


def test_reset_budget_does_not_change_running_status():
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.lifecycle = "running"
    bridge.status = "waiting_llm"
    bridge.paused = False
    bridge.recovery_context = None
    bridge.pending.clear()

    bridge.handle({"type": "reset_session"})

    assert bridge.lifecycle == "running"
    assert bridge.status == "waiting_llm"
    assert bridge.paused is False
    assert sent == []


def test_explicit_planning_after_discard_uses_new_provider_without_resuming_old_run():
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.handle({"type": "recovery_discard"})
    bridge.handle({"type": "reset_session"})
    bridge.config = {"project_goal": "Plan a calculator", "provider_id": "glm", "provider_mode": "manual"}
    bridge.start_prompt = lambda: "PLAN ONLY"

    def capture(text):
        assert bridge.paused is False
        assert bridge.lifecycle == "planning"
        sent.append(text)

    bridge._send_result_to_chatgpt = capture
    bridge.handle({"type": "build_start_prompt", "provider": "glm"})

    assert bridge.active_provider == "glm"
    assert bridge.budget.provider_id == "glm"
    assert bridge.pending == {}
    assert sent == ["PLAN ONLY"]


def test_planning_does_not_clear_provider_guard_or_switch_provider():
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.provider_guard = True
    bridge.handle({"type": "recovery_discard"})
    bridge.config = {"project_goal": "Plan a calculator", "provider_id": "glm"}
    bridge.handle({"type": "build_start_prompt", "provider": "glm"})

    assert bridge.paused is True
    assert bridge.provider_guard is True
    assert bridge.active_provider == "chatgpt"
    assert sent == []


def test_planning_refuses_active_work_approvals_pending_sends_and_mismatched_provider():
    for reason in ("running", "approval", "command", "timer", "provider"):
        bridge, emitted, sent = _make_recovery_bridge()
        bridge.handle({"type": "recovery_discard"})
        bridge.config = {"project_goal": "Plan a calculator", "provider_id": "glm"}
        provider = "glm"
        if reason == "running":
            bridge.lifecycle = "running"
        elif reason == "approval":
            bridge.pending["old"] = {}
        elif reason == "command":
            bridge.command_execution_active = True
        elif reason == "timer":
            bridge.pending_send_timer = object()
        else:
            provider = "claude"
        bridge.handle({"type": "build_start_prompt", "provider": provider})

        assert bridge.active_provider == "chatgpt"
        assert bridge.lifecycle != "planning"
        assert sent == []


def test_safety_warning_cancels_pending_send_and_ignores_late_ack():
    from unittest.mock import Mock

    bridge, emitted, sent = _make_recovery_bridge()
    bridge.handle({"type": "recovery_discard"})
    bridge.lifecycle = "planning"
    bridge.status = "waiting_llm"
    bridge.paused = False
    bridge.active_provider = "glm"
    bridge.telegram = Mock()
    timer = Mock()
    bridge.pending_send_timer = timer

    bridge.handle({"type": "provider_safety_signal", "payload": {
        "provider": "glm", "kind": "auth_challenge", "text": "Security verification",
    }})
    timer.cancel.assert_called_once()
    assert bridge.pending_send_timer is None
    assert bridge.paused is True
    assert bridge.lifecycle == "paused"
    assert bridge.provider_guard is True
    assert bridge.budget.public(bridge.config)["cooldown_until"] == "manual"

    for message in (
        {"type": "chat_send_ack", "ok": True, "submitted": True},
        {"type": "chat_send_ack", "ok": False},
        {"type": "chat_response_timeout"},
        {"type": "resume"},
        {"type": "build_controller_prompt", "provider": "glm"},
        {"type": "change_course", "provider": "glm"},
        {"type": "finish_project", "provider": "glm"},
    ):
        bridge.handle(message)
        assert bridge.status == "provider_guard"
        assert bridge.paused is True
        assert bridge.provider_guard is True

    assert sent == []


def test_unknown_response_timeout_pauses_without_retry():
    from unittest.mock import Mock

    bridge, emitted, sent = _make_recovery_bridge()
    bridge.handle({"type": "recovery_discard"})
    bridge.lifecycle = "planning"
    bridge.status = "waiting_llm"
    bridge.paused = False
    timer = Mock()
    bridge.pending_send_timer = timer

    bridge.handle({"type": "chat_response_timeout"})

    timer.cancel.assert_called_once()
    assert bridge.pending_send_timer is None
    assert bridge.lifecycle == "paused"
    assert bridge.paused is True
    assert bridge.status == "paused"
    assert sent == []


def test_planning_ack_distinguishes_guard_rejection_from_acceptance():
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.handle({"type": "recovery_discard"})
    bridge.config = {"project_goal": "Plan a calculator", "provider_id": "glm"}
    bridge.start_prompt = lambda: "PLAN ONLY"
    bridge.provider_guard = True
    bridge.status = "provider_guard"
    request = {"type": "build_start_prompt", "provider": "glm", "action_request_id": "blocked"}
    bridge.handle(request)
    assert sent == []
    assert bridge.paused
    assert bridge.provider_guard
    assert any(e.get("kind") == "action_ack" and e.get("action_request_id") == "blocked" and e.get("ok") is False for e in emitted)
    assert any(e.get("badge") == "BLOCKED" for e in emitted)
    bridge.handle({"type": "reset_session"})
    bridge.handle({**request, "action_request_id": "accepted"})
    assert sent == ["PLAN ONLY"]
    assert any(e.get("kind") == "action_ack" and e.get("action_request_id") == "accepted" and e.get("ok") is True for e in emitted)
    assert not any(e.get("badge") == "ARMED" for e in emitted)


def test_save_ack_is_emitted_only_after_native_save(monkeypatch):
    import orchestrator_messages
    bridge, emitted, sent = _make_recovery_bridge()
    bridge.handle({"type": "recovery_discard"})
    trace = []
    def save(config):
        trace.append("persisted")
        return config
    monkeypatch.setattr(orchestrator_messages, "save_config", save)
    original = bridge.emit
    def emit(event):
        if event.get("kind") == "action_ack":
            assert trace == ["persisted"]
        original(event)
    bridge.emit = emit
    bridge.handle({"type": "set_config", "action_request_id": "save-1", "config": {"project_goal": "test"}})
    assert any(e.get("kind") == "action_ack" and e.get("action_request_id") == "save-1" and e.get("ok") is True for e in emitted)
