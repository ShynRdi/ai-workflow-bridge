from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(
        0,
        str(HOST),
    )


import orchestrator_checkpoints
from orchestrator_checkpoints import (
    CheckpointControlMixin,
)
from orchestrator_messages import (
    MessageMixin,
)


class FakeStore:
    def __init__(
        self,
        checkpoint=None,
    ):
        self.checkpoint = checkpoint
        self.transitions = []

    def list_checkpoints(
        self,
        *,
        workspace_root=None,
        status=None,
        limit=50,
    ):
        if (
            self.checkpoint is None
            or status != "ready"
        ):
            return []

        return [
            self.checkpoint
        ][:limit]

    def transition_checkpoint_status(
        self,
        checkpoint_id,
        *,
        expected_status,
        new_status,
    ):
        self.transitions.append(
            (
                checkpoint_id,
                expected_status,
                new_status,
            )
        )

        if self.checkpoint is None:
            return False

        if (
            self.checkpoint["status"]
            != expected_status
        ):
            return False

        self.checkpoint[
            "status"
        ] = new_status

        return True


def checkpoint(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir(
        exist_ok=True
    )

    return {
        "checkpoint_id": "cp-latest",
        "workspace_root": str(
            workspace.resolve()
        ),
        "status": "ready",
        "snapshot": {
            "checkpoint_id": "cp-latest",
            "workspace_root": str(
                workspace.resolve()
            ),
            "rollback_scope": (
                "workspace_files_only"
            ),
        },
    }


class Bridge(
    CheckpointControlMixin
):
    def __init__(
        self,
        *,
        workspace: Path,
        store,
    ):
        self.config = {
            "workspace_root": str(
                workspace
            ),
        }

        self.store = store
        self.lock = threading.RLock()

        self.command_execution_active = False

        self.paused = True
        self.lifecycle = "paused"
        self.status = "paused"
        self.current_step = "Paused"

        self.active_provider = "chatgpt"
        self.provider_guard = False
        self.pending = {}

        self.recovery_context = None

        self.events = []
        self.emitted = []
        self.runtime_writes = []

    def _runtime_snapshot(
        self,
    ):
        return {
            "version": 2,
            "lifecycle": self.lifecycle,
            "status": self.status,
            "current_step": self.current_step,
            "paused": self.paused,
            "active_provider": (
                self.active_provider
            ),
            "provider_guard": (
                self.provider_guard
            ),
            "pending_approvals": [],
            "budget": {},
        }

    def _persist_runtime_state(
        self,
    ):
        self.runtime_writes.append(
            (
                self.lifecycle,
                self.status,
            )
        )

    def emit_event(
        self,
        event,
    ):
        self.events.append(
            event
        )

        self._persist_runtime_state()

    def emit(
        self,
        event,
    ):
        self.emitted.append(
            event
        )

    def state(
        self,
    ):
        return {
            "paused": self.paused,
            "lifecycle": self.lifecycle,
            "status": self.status,
            "recovery": self.recovery_context,
        }


def test_accept_latest_checkpoint(
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    store = FakeStore(
        payload
    )

    bridge = Bridge(
        workspace=workspace,
        store=store,
    )

    assert (
        bridge.accept_latest_checkpoint()
        is True
    )

    assert store.transitions == [
        (
            "cp-latest",
            "ready",
            "accepted",
        )
    ]

    assert any(
        event.get("kind")
        == "checkpoint_accepted"
        for event in bridge.events
    )


def test_rollback_requires_paused_workflow(
    monkeypatch,
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    bridge = Bridge(
        workspace=workspace,
        store=FakeStore(
            payload
        ),
    )

    bridge.paused = False
    bridge.lifecycle = "running"

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "restore_workspace_snapshot",
        lambda **_kwargs:
        pytest.fail(
            "restore must not run"
        ),
    )

    assert (
        bridge.rollback_latest_checkpoint()
        is False
    )

    assert (
        payload["status"]
        == "ready"
    )


def test_rollback_is_forbidden_during_command_execution(
    monkeypatch,
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    bridge = Bridge(
        workspace=workspace,
        store=FakeStore(
            payload
        ),
    )

    bridge.command_execution_active = True

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "restore_workspace_snapshot",
        lambda **_kwargs:
        pytest.fail(
            "restore must not run"
        ),
    )

    assert (
        bridge.rollback_latest_checkpoint()
        is False
    )

    assert (
        payload["status"]
        == "ready"
    )


def test_rollback_persists_crash_boundary_before_restore(
    monkeypatch,
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    store = FakeStore(
        payload
    )

    bridge = Bridge(
        workspace=workspace,
        store=store,
    )

    trace = []

    original_persist = (
        bridge._persist_runtime_state
    )

    def persist():
        trace.append(
            (
                "persist",
                bridge.lifecycle,
                bridge.status,
            )
        )

        original_persist()

    bridge._persist_runtime_state = (
        persist
    )

    original_transition = (
        store.transition_checkpoint_status
    )

    def transition(
        checkpoint_id,
        *,
        expected_status,
        new_status,
    ):
        trace.append(
            (
                "transition",
                expected_status,
                new_status,
            )
        )

        return original_transition(
            checkpoint_id,
            expected_status=expected_status,
            new_status=new_status,
        )

    store.transition_checkpoint_status = (
        transition
    )

    def restore(**_kwargs):
        trace.append(
            ("restore",)
        )

        return {
            "rollback_scope": (
                "workspace_files_only"
            ),
            "restored_files": 2,
            "removed_entries": 1,
        }

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "restore_workspace_snapshot",
        restore,
    )

    assert (
        bridge.rollback_latest_checkpoint()
        is True
    )

    recovering_persist = (
        "persist",
        "recovering",
        "recovering",
    )

    claim = (
        "transition",
        "ready",
        "rolling_back",
    )

    restore_item = (
        "restore",
    )

    complete = (
        "transition",
        "rolling_back",
        "rolled_back",
    )

    assert (
        trace.index(
            recovering_persist
        )
        < trace.index(
            claim
        )
        < trace.index(
            restore_item
        )
        < trace.index(
            complete
        )
    )

    assert bridge.paused is True
    assert bridge.lifecycle == "paused"
    assert bridge.status == "paused"

    assert (
        payload["status"]
        == "rolled_back"
    )


def test_rollback_failure_enters_recovery_required(
    monkeypatch,
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    bridge = Bridge(
        workspace=workspace,
        store=FakeStore(
            payload
        ),
    )

    def fail_restore(
        **_kwargs,
    ):
        raise RuntimeError(
            "simulated restore failure"
        )

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "restore_workspace_snapshot",
        fail_restore,
    )

    assert (
        bridge.rollback_latest_checkpoint()
        is False
    )

    assert (
        payload["status"]
        == "rollback_failed"
    )

    assert (
        bridge.lifecycle
        == "recovery_required"
    )

    assert (
        bridge.status
        == "recovery_required"
    )

    assert bridge.paused is True

    assert (
        bridge.recovery_context[
            "required"
        ]
        is True
    )

    assert any(
        "No automatic retry"
        in str(
            event.get(
                "text"
            )
        )
        for event in bridge.events
    )


def test_checkpoint_message_routes_are_explicit():
    calls = []

    class MessageBridge(
        MessageMixin
    ):
        def __init__(
            self,
        ):
            self.lifecycle = "idle"

        def accept_latest_checkpoint(
            self,
        ):
            calls.append(
                "accept"
            )

        def rollback_latest_checkpoint(
            self,
        ):
            calls.append(
                "rollback"
            )

    bridge = MessageBridge()

    bridge.handle({
        "type": "checkpoint_accept",
    })

    bridge.handle({
        "type": "checkpoint_rollback",
    })

    assert calls == [
        "accept",
        "rollback",
    ]


from recovery import requires_recovery


def test_crash_after_rollback_claim_leaves_recovery_boundary(
    monkeypatch,
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload["workspace_root"]
    )

    store = FakeStore(
        payload
    )

    bridge = Bridge(
        workspace=workspace,
        store=store,
    )

    def crash_before_restore(
        **_kwargs,
    ):
        raise SystemExit(
            "simulated process crash"
        )

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "restore_workspace_snapshot",
        crash_before_restore,
    )

    with pytest.raises(
        SystemExit,
        match="simulated process crash",
    ):
        bridge.rollback_latest_checkpoint()

    # The rollback was claimed, but restore never ran.
    # A restart must NOT silently retry it.
    assert (
        payload["status"]
        == "rolling_back"
    )

    assert bridge.runtime_writes

    lifecycle, status = (
        bridge.runtime_writes[-1]
    )

    assert lifecycle == "recovering"
    assert status == "recovering"

    assert requires_recovery({
        "lifecycle": lifecycle,
        "status": status,
    })

    assert not any(
        event.get("kind")
        == "checkpoint_rolled_back"
        for event in bridge.events
    )


def test_crash_after_restore_before_completion_is_left_uncertain(
    monkeypatch,
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload["workspace_root"]
    )

    restored = []

    class CrashOnCompletionStore(
        FakeStore
    ):
        def transition_checkpoint_status(
            self,
            checkpoint_id,
            *,
            expected_status,
            new_status,
        ):
            if (
                expected_status
                == "rolling_back"
                and new_status
                == "rolled_back"
            ):
                raise SystemExit(
                    "simulated crash after restore"
                )

            return super().transition_checkpoint_status(
                checkpoint_id,
                expected_status=expected_status,
                new_status=new_status,
            )

    store = CrashOnCompletionStore(
        payload
    )

    bridge = Bridge(
        workspace=workspace,
        store=store,
    )

    def successful_restore(
        **_kwargs,
    ):
        restored.append(
            True
        )

        return {
            "rollback_scope": (
                "workspace_files_only"
            ),
            "restored_files": 3,
            "removed_entries": 2,
        }

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "restore_workspace_snapshot",
        successful_restore,
    )

    with pytest.raises(
        SystemExit,
        match="simulated crash after restore",
    ):
        bridge.rollback_latest_checkpoint()

    # Workspace restore happened, but its durable completion
    # marker did not. This is deliberately an uncertain
    # recovery boundary and must never be replayed automatically.
    assert restored == [
        True
    ]

    assert (
        payload["status"]
        == "rolling_back"
    )

    lifecycle, status = (
        bridge.runtime_writes[-1]
    )

    assert lifecycle == "recovering"
    assert status == "recovering"

    assert requires_recovery({
        "lifecycle": lifecycle,
        "status": status,
    })

    assert not any(
        event.get("kind")
        == "checkpoint_rolled_back"
        for event in bridge.events
    )


def test_checkpoint_actions_are_blocked_during_recovery_required():
    calls = []
    emitted = []

    class RecoveryBridge(
        MessageMixin
    ):
        def __init__(
            self,
        ):
            self.lifecycle = (
                "recovery_required"
            )
            self.status = (
                "recovery_required"
            )

        def accept_latest_checkpoint(
            self,
        ):
            calls.append(
                "accept"
            )

        def rollback_latest_checkpoint(
            self,
        ):
            calls.append(
                "rollback"
            )

        def emit_event(
            self,
            event,
        ):
            emitted.append(
                event
            )

        def emit(
            self,
            event,
        ):
            emitted.append(
                event
            )

        def state(
            self,
        ):
            return {
                "lifecycle": (
                    self.lifecycle
                ),
                "status": (
                    self.status
                ),
            }

    bridge = RecoveryBridge()

    bridge.handle({
        "type": "checkpoint_accept",
    })

    bridge.handle({
        "type": "checkpoint_rollback",
    })

    assert calls == []

    errors = [
        item
        for item in emitted
        if (
            isinstance(
                item,
                dict,
            )
            and item.get("kind")
            == "error"
        )
    ]

    assert len(errors) == 2

    assert all(
        item.get("status")
        == "recovery_required"
        for item in errors
    )


def test_public_checkpoint_state_exposes_safe_review_metadata(
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    payload[
        "created_at"
    ] = "2026-10-06T10:00:00+00:00"

    payload[
        "command"
    ] = {
        "summary": "Protected mutation",
        "risk_level": "R2",
    }

    payload[
        "snapshot"
    ].update({
        "archive_path": (
            "/secret/checkpoint/workspace.tar.gz"
        ),
        "archive_sha256": (
            "a" * 64
        ),
        "file_count": 7,
        "total_bytes": 2048,
        "rollback_limitations": [
            "Git metadata is not captured.",
            "Remote effects are outside this checkpoint.",
        ],
    })

    store = FakeStore(
        payload
    )

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    bridge = Bridge(
        workspace=workspace,
        store=store,
    )

    result = (
        bridge.public_checkpoint_state()
    )

    assert result[
        "available"
    ] is True

    assert (
        result[
            "checkpoint_id"
        ]
        == "cp-latest"
    )

    assert (
        result[
            "command_summary"
        ]
        == "Protected mutation"
    )

    assert (
        result[
            "risk_level"
        ]
        == "R2"
    )

    assert (
        result[
            "file_count"
        ]
        == 7
    )

    assert (
        result[
            "total_bytes"
        ]
        == 2048
    )

    serialized = repr(
        result
    )

    assert (
        "archive_path"
        not in serialized
    )

    assert (
        "/secret/checkpoint"
        not in serialized
    )

    assert (
        "archive_sha256"
        not in serialized
    )


def test_public_checkpoint_state_requires_pause_for_rollback(
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    bridge = Bridge(
        workspace=workspace,
        store=FakeStore(
            payload
        ),
    )

    bridge.paused = False
    bridge.lifecycle = "running"

    running = (
        bridge.public_checkpoint_state()
    )

    assert (
        running[
            "can_accept"
        ]
        is True
    )

    assert (
        running[
            "can_rollback"
        ]
        is False
    )

    assert (
        running[
            "rollback_requires_pause"
        ]
        is True
    )

    bridge.paused = True
    bridge.lifecycle = "paused"

    paused = (
        bridge.public_checkpoint_state()
    )

    assert (
        paused[
            "can_rollback"
        ]
        is True
    )


def test_orchestrator_state_never_exposes_checkpoint_archive_material(
    tmp_path,
):
    payload = checkpoint(
        tmp_path
    )

    payload[
        "snapshot"
    ].update({
        "archive_path": (
            "/private/checkpoints/workspace.tar.gz"
        ),
        "archive_sha256": (
            "b" * 64
        ),
        "file_count": 3,
        "total_bytes": 123,
    })

    workspace = Path(
        payload[
            "workspace_root"
        ]
    )

    bridge = Bridge(
        workspace=workspace,
        store=FakeStore(
            payload
        ),
    )

    public = (
        bridge.public_checkpoint_state()
    )

    serialized = repr(
        public
    )

    assert (
        "archive_path"
        not in serialized
    )

    assert (
        "archive_sha256"
        not in serialized
    )

    assert (
        "/private/checkpoints"
        not in serialized
    )
