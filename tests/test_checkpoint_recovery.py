from __future__ import annotations

import sys
import threading
from pathlib import Path

from pytest import fail


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(
        0,
        str(HOST),
    )


from orchestrator import Orchestrator
from recovery import (
    build_runtime_snapshot,
    sanitize_checkpoint_recovery,
)
from safety import RunBudget


def test_checkpoint_recovery_metadata_is_review_only():
    result = sanitize_checkpoint_recovery({
        "checkpoint_id": "cp-1",
        "status": "rolling_back",
        "rollback_scope": "workspace_files_only",
        "command_summary": "Mutate files",
        "risk_level": "R2",
        "uncertain": True,
        "note": "Interrupted rollback",
        "archive_path": "/secret/archive.tar.gz",
        "continuation": {
            "index": 9,
        },
        "contract": "DO NOT RESTORE",
    })

    assert result == {
        "checkpoint_id": "cp-1",
        "status": "rolling_back",
        "rollback_scope": "workspace_files_only",
        "command_summary": "Mutate files",
        "risk_level": "R2",
        "uncertain": True,
        "note": "Interrupted rollback",
    }

    assert "archive_path" not in result
    assert "continuation" not in result
    assert "contract" not in result


class RecoveryStore:
    def __init__(
        self,
        *,
        runtime=None,
        checkpoint=None,
    ):
        self.runtime = runtime
        self.checkpoint = checkpoint
        self.transitions = []
        self.runtime_writes = []
        self.events = []
        self.expired = False

    def get_runtime_state(
        self,
        _key,
    ):
        return self.runtime

    def put_runtime_state(
        self,
        key,
        payload,
    ):
        self.runtime = dict(
            payload
        )

        self.runtime_writes.append(
            (
                key,
                dict(payload),
            )
        )

    def list_checkpoints(
        self,
        *,
        workspace_root=None,
        status=None,
        limit=50,
    ):
        if self.checkpoint is None:
            return []

        if (
            self.checkpoint.get(
                "workspace_root"
            )
            != workspace_root
        ):
            return []

        if (
            self.checkpoint.get(
                "status"
            )
            != status
        ):
            return []

        return [
            dict(
                self.checkpoint
            )
        ][:limit]

    def get_checkpoint(
        self,
        checkpoint_id,
    ):
        if (
            self.checkpoint is None
            or self.checkpoint.get(
                "checkpoint_id"
            )
            != checkpoint_id
        ):
            return None

        return dict(
            self.checkpoint
        )

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

        if (
            self.checkpoint is None
            or self.checkpoint.get(
                "checkpoint_id"
            )
            != checkpoint_id
            or self.checkpoint.get(
                "status"
            )
            != expected_status
        ):
            return False

        self.checkpoint[
            "status"
        ] = new_status

        return True

    def expire_pending_approvals(
        self,
    ):
        self.expired = True

    def event(
        self,
        kind,
        payload,
    ):
        self.events.append(
            (
                kind,
                dict(payload),
            )
        )


def make_bridge(
    tmp_path: Path,
    store,
):
    bridge = Orchestrator.__new__(
        Orchestrator
    )

    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir(
        exist_ok=True
    )

    bridge.store = store
    bridge.lock = threading.RLock()

    bridge.config = {
        "workspace_root": str(
            workspace
        ),
    }

    bridge.active_provider = "chatgpt"
    bridge.provider_guard = False
    bridge.paused = False
    bridge.lifecycle = "setup"
    bridge.status = "idle"
    bridge.current_step = ""

    bridge.pending = {}
    bridge.download_waiters = {}
    bridge.no_contract_recoveries = 0

    bridge.budget = RunBudget()
    bridge.budget.reset(
        "chatgpt"
    )

    bridge.recovery_context = None
    bridge.checkpoint_recovery_context = None

    bridge.command_execution_active = False

    bridge.emit = lambda _event: None

    return (
        bridge,
        workspace,
    )


def rolling_checkpoint(
    workspace: Path,
):
    return {
        "checkpoint_id": "cp-crash",
        "status": "rolling_back",
        "workspace_root": str(
            workspace.resolve()
        ),
        "command": {
            "summary": "Mutate project",
            "risk_level": "R2",
        },
        "snapshot": {
            "rollback_scope": (
                "workspace_files_only"
            ),
            "archive_path": (
                "/must/not/be/exposed"
            ),
        },
    }


def test_rolling_back_db_state_requires_recovery_without_runtime_snapshot(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir()

    checkpoint = rolling_checkpoint(
        workspace
    )

    store = RecoveryStore(
        runtime=None,
        checkpoint=checkpoint,
    )

    bridge, _ = make_bridge(
        tmp_path,
        store,
    )

    bridge._restore_runtime_state()

    assert bridge.paused is True
    assert (
        bridge.lifecycle
        == "recovery_required"
    )
    assert (
        bridge.status
        == "recovery_required"
    )

    review = bridge.recovery_context[
        "checkpoint_recovery"
    ]

    assert (
        review["checkpoint_id"]
        == "cp-crash"
    )
    assert (
        review["status"]
        == "rolling_back"
    )
    assert review["uncertain"] is True

    assert "archive_path" not in review


def test_runtime_checkpoint_context_reconciles_with_durable_terminal_state(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir()

    checkpoint = rolling_checkpoint(
        workspace
    )

    checkpoint[
        "status"
    ] = "rolled_back"

    runtime = build_runtime_snapshot(
        lifecycle="recovering",
        status="recovering",
        current_step="Rollback",
        paused=True,
        active_provider="chatgpt",
        provider_guard=False,
        checkpoint_recovery={
            "checkpoint_id": "cp-crash",
            "status": "rolling_back",
            "rollback_scope": (
                "workspace_files_only"
            ),
            "uncertain": True,
        },
    )

    store = RecoveryStore(
        runtime=runtime,
        checkpoint=checkpoint,
    )

    bridge, _ = make_bridge(
        tmp_path,
        store,
    )

    bridge._restore_runtime_state()

    review = bridge.recovery_context[
        "checkpoint_recovery"
    ]

    assert (
        review["status"]
        == "rolled_back"
    )
    assert review["uncertain"] is False

    assert (
        bridge.lifecycle
        == "recovery_required"
    )


def test_recovery_resolution_invalidates_uncertain_rolling_back_checkpoint(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir()

    checkpoint = rolling_checkpoint(
        workspace
    )

    runtime = build_runtime_snapshot(
        lifecycle="recovering",
        status="recovering",
        current_step="Rollback",
        paused=True,
        active_provider="chatgpt",
        provider_guard=False,
        checkpoint_recovery={
            "checkpoint_id": "cp-crash",
            "status": "rolling_back",
            "rollback_scope": (
                "workspace_files_only"
            ),
            "uncertain": True,
        },
    )

    store = RecoveryStore(
        runtime=runtime,
        checkpoint=checkpoint,
    )

    bridge, _ = make_bridge(
        tmp_path,
        store,
    )

    bridge._restore_runtime_state()

    assert bridge.resolve_recovery(
        "discard"
    )

    assert (
        checkpoint["status"]
        == "invalid"
    )

    assert store.transitions == [
        (
            "cp-crash",
            "rolling_back",
            "invalid",
        )
    ]

    assert (
        bridge.lifecycle
        == "paused"
    )
    assert bridge.paused is True

    assert (
        bridge.checkpoint_recovery_context
        is None
    )


def test_restart_recovery_never_calls_restore_primitive(
    monkeypatch,
    tmp_path: Path,
):
    import orchestrator_checkpoints

    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir()

    checkpoint = rolling_checkpoint(
        workspace
    )

    store = RecoveryStore(
        checkpoint=checkpoint,
    )

    bridge, _ = make_bridge(
        tmp_path,
        store,
    )

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "restore_workspace_snapshot",
        lambda **_kwargs:
        fail(
            "restart must never replay rollback"
        ),
    )

    bridge._restore_runtime_state()

    assert (
        bridge.lifecycle
        == "recovery_required"
    )
