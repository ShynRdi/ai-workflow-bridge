from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(
    __file__
).resolve().parents[1]

HOST = (
    ROOT /
    "native_host"
)

if str(HOST) not in sys.path:
    sys.path.insert(
        0,
        str(HOST),
    )


import orchestrator_checkpoints

from checkpoint import (
    build_checkpoint_metadata,
)

from checkpoint_snapshot import (
    create_workspace_snapshot,
)

from orchestrator_checkpoints import (
    CheckpointControlMixin,
)

from runner import (
    git_snapshot,
)


def git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            *args,
        ],
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=check,
    )


def init_repo(
    repo: Path,
) -> None:
    repo.mkdir()

    git(
        repo,
        "init",
        "-q",
    )

    git(
        repo,
        "config",
        "user.name",
        "Checkpoint Test",
    )

    git(
        repo,
        "config",
        "user.email",
        "checkpoint@example.invalid",
    )

    (
        repo /
        "tracked.txt"
    ).write_text(
        "base\n",
        encoding="utf-8",
    )

    git(
        repo,
        "add",
        "tracked.txt",
    )

    git(
        repo,
        "commit",
        "-q",
        "-m",
        "initial",
    )


class Store:
    def __init__(
        self,
        payload,
    ):
        self.payload = payload
        self.transitions = []

    def get_checkpoint(
        self,
        checkpoint_id,
    ):
        if (
            self.payload.get(
                "checkpoint_id"
            )
            != checkpoint_id
        ):
            return None

        return self.payload

    def put_checkpoint(
        self,
        payload,
    ):
        # Preserve object identity because several assertions
        # intentionally observe the original payload reference.
        self.payload.clear()
        self.payload.update(
            payload
        )

        return str(
            payload[
                "checkpoint_id"
            ]
        )

    def list_checkpoints(
        self,
        *,
        workspace_root=None,
        status=None,
        limit=50,
    ):
        if (
            workspace_root
            and self.payload[
                "workspace_root"
            ] != workspace_root
        ):
            return []

        if (
            status is not None
            and self.payload[
                "status"
            ] != status
        ):
            return []

        return [
            self.payload
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

        if (
            checkpoint_id
            != self.payload[
                "checkpoint_id"
            ]
        ):
            return False

        if (
            self.payload[
                "status"
            ]
            != expected_status
        ):
            return False

        self.payload[
            "status"
        ] = new_status

        return True


class Bridge(
    CheckpointControlMixin
):
    def __init__(
        self,
        *,
        workspace: Path,
        payload,
    ):
        self.config = {
            "workspace_root": str(
                workspace
            ),
        }

        self.store = Store(
            payload
        )

        self.lock = (
            threading.RLock()
        )

        self.command_execution_active = False
        self.paused = True
        self.lifecycle = "paused"
        self.status = "paused"
        self.current_step = "Paused"

        self.active_provider = "chatgpt"
        self.provider_guard = False
        self.pending = {}

        self.recovery_context = None
        self.checkpoint_recovery_context = None

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


def build_payload(
    *,
    repo: Path,
    storage: Path,
    checkpoint_id: str,
):
    pre_git = git_snapshot(
        str(repo)
    )

    snapshot = (
        create_workspace_snapshot(
            checkpoint_id=checkpoint_id,
            workspace_root=str(
                repo
            ),
            storage_root=storage,
        )
    )

    snapshot = {
        **snapshot,
        "rollback_scope": (
            "workspace_files_only"
        ),
    }

    payload = (
        build_checkpoint_metadata(
            workspace_root=str(
                repo
            ),
            lifecycle="running",
            phase="P1",
            stage="S1",
            command_index=0,
            command_summary=(
                "Protected Git-aware mutation"
            ),
            risk_level="R2",
            reason="test",
            git=pre_git,
            snapshot_metadata=snapshot,
            checkpoint_id=checkpoint_id,
        )
    )

    return (
        payload,
        pre_git,
    )


def rolled_back_event(
    bridge: Bridge,
):
    return next(
        event
        for event in bridge.events
        if event.get(
            "kind"
        )
        == "checkpoint_rolled_back"
    )


def test_rollback_restores_dirty_file_but_does_not_rewrite_index(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    storage = (
        tmp_path /
        "storage"
    )

    init_repo(
        repo
    )

    # Pre-existing dirty workspace state that belongs to
    # the user and must be restored as workspace content.
    (
        repo /
        "tracked.txt"
    ).write_text(
        "pre-existing dirty\n",
        encoding="utf-8",
    )

    (
        payload,
        pre_git,
    ) = build_payload(
        repo=repo,
        storage=storage,
        checkpoint_id="cp-git-index",
    )

    assert (
        pre_git[
            "has_unstaged_changes"
        ]
        is True
    )

    assert (
        pre_git[
            "has_staged_changes"
        ]
        is False
    )

    # Simulate a protected command changing both the file
    # and Git index after the checkpoint.
    (
        repo /
        "tracked.txt"
    ).write_text(
        "command mutation\n",
        encoding="utf-8",
    )

    git(
        repo,
        "add",
        "tracked.txt",
    )

    bridge = Bridge(
        workspace=repo,
        payload=payload,
    )

    assert (
        bridge.rollback_checkpoint(
            payload["checkpoint_id"]
        )
        is True
    )

    # Workspace file content is restored.
    assert (
        repo /
        "tracked.txt"
    ).read_text(
        encoding="utf-8",
    ) == "pre-existing dirty\n"

    # The Git index remains command-mutated because .git
    # is deliberately outside rollback scope.
    cached = git(
        repo,
        "diff",
        "--cached",
        "--quiet",
        check=False,
    )

    assert cached.returncode == 1

    event = rolled_back_event(
        bridge
    )

    review = event[
        "git_review"
    ]

    assert review[
        "index_changed"
    ] is True

    assert review[
        "git_metadata_changed"
    ] is True

    assert review[
        "requires_git_review"
    ] is True

    assert review[
        "git_metadata_restored"
    ] is False

    assert event[
        "git_review_required"
    ] is True

    assert event[
        "git_metadata_restored"
    ] is False

    assert bridge.paused is True


def test_rollback_does_not_rewind_head_commit(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    storage = (
        tmp_path /
        "storage"
    )

    init_repo(
        repo
    )

    (
        payload,
        pre_git,
    ) = build_payload(
        repo=repo,
        storage=storage,
        checkpoint_id="cp-git-head",
    )

    original_head = (
        pre_git[
            "head_oid"
        ]
    )

    (
        repo /
        "tracked.txt"
    ).write_text(
        "new committed state\n",
        encoding="utf-8",
    )

    git(
        repo,
        "add",
        "tracked.txt",
    )

    git(
        repo,
        "commit",
        "-q",
        "-m",
        "command mutation",
    )

    changed_head = git(
        repo,
        "rev-parse",
        "HEAD",
    ).stdout.strip()

    assert (
        changed_head
        != original_head
    )

    bridge = Bridge(
        workspace=repo,
        payload=payload,
    )

    assert (
        bridge.rollback_checkpoint(
            payload["checkpoint_id"]
        )
        is True
    )

    # Visible file returns to checkpoint state.
    assert (
        repo /
        "tracked.txt"
    ).read_text(
        encoding="utf-8",
    ) == "base\n"

    # HEAD is deliberately NOT rewound.
    current_head = git(
        repo,
        "rev-parse",
        "HEAD",
    ).stdout.strip()

    assert current_head == changed_head

    event = rolled_back_event(
        bridge
    )

    review = event[
        "git_review"
    ]

    assert review[
        "head_changed"
    ] is True

    assert review[
        "git_metadata_changed"
    ] is True

    assert review[
        "requires_git_review"
    ] is True

    assert review[
        "git_metadata_restored"
    ] is False


def test_git_inspection_failure_does_not_turn_successful_restore_into_failure(
    monkeypatch,
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    storage = (
        tmp_path /
        "storage"
    )

    init_repo(
        repo
    )

    (
        payload,
        _pre_git,
    ) = build_payload(
        repo=repo,
        storage=storage,
        checkpoint_id="cp-git-inspection",
    )

    (
        repo /
        "tracked.txt"
    ).write_text(
        "mutation\n",
        encoding="utf-8",
    )

    def fail_git_inspection(
        _workspace,
    ):
        raise RuntimeError(
            "simulated Git inspection failure"
        )

    monkeypatch.setattr(
        orchestrator_checkpoints,
        "git_snapshot",
        fail_git_inspection,
    )

    bridge = Bridge(
        workspace=repo,
        payload=payload,
    )

    assert (
        bridge.rollback_checkpoint(
            payload["checkpoint_id"]
        )
        is True
    )

    assert (
        repo /
        "tracked.txt"
    ).read_text(
        encoding="utf-8",
    ) == "base\n"

    assert (
        payload[
            "status"
        ]
        == "rolled_back"
    )

    event = rolled_back_event(
        bridge
    )

    review = event[
        "git_review"
    ]

    assert review[
        "inspection_error"
    ] is True

    assert review[
        "requires_git_review"
    ] is True

    assert review[
        "git_metadata_restored"
    ] is False

    assert (
        "simulated Git inspection failure"
        in review[
            "inspection_error_detail"
        ]
    )
