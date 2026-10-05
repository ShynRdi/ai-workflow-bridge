from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(
        0,
        str(HOST),
    )


import storage
from checkpoint import (
    build_checkpoint_metadata,
)


def isolated_store(
    monkeypatch,
    tmp_path: Path,
):
    db_path = (
        tmp_path /
        "bridge.sqlite3"
    )

    monkeypatch.setattr(
        storage,
        "DB_PATH",
        db_path,
    )

    monkeypatch.setattr(
        storage,
        "ensure_app_dir",
        lambda: None,
    )

    return storage.Store()


def checkpoint(
    workspace: Path,
    **overrides,
):
    values = {
        "workspace_root": str(
            workspace
        ),
        "lifecycle": "running",
        "phase": "implementation",
        "stage": "checkpoint",
        "command_index": 2,
        "command_summary": (
            "Update local project files"
        ),
        "risk_level": "R2",
        "reason": (
            "Before meaningful local mutation"
        ),
        "git": {
            "is_git": True,
            "head": "abc123",
            "branch": "feature/test",
            "status": " M app.py",
        },
        "snapshot_metadata": {
            "kind": "pending",
        },
    }

    values.update(
        overrides
    )

    return build_checkpoint_metadata(
        **values
    )


def test_checkpoint_metadata_contains_no_execution_cursor(
    tmp_path: Path,
):
    payload = checkpoint(
        tmp_path
    )

    serialized = repr(
        payload
    )

    assert "continuation" not in serialized
    assert "approved_index" not in serialized
    assert "execution_cursor" not in serialized
    assert "contract" not in serialized

    assert (
        payload["command"]["index"]
        == 2
    )

    assert (
        payload["command"]["summary"]
        == "Update local project files"
    )


def test_checkpoint_round_trip_survives_store_restart(
    monkeypatch,
    tmp_path: Path,
):
    first = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path
    )

    checkpoint_id = (
        first.put_checkpoint(
            payload
        )
    )

    second = storage.Store()

    restored = (
        second.get_checkpoint(
            checkpoint_id
        )
    )

    assert restored is not None

    assert (
        restored["checkpoint_id"]
        == checkpoint_id
    )

    assert (
        restored["status"]
        == "ready"
    )

    assert (
        restored["workspace_root"]
        == str(
            tmp_path.resolve()
        )
    )

    assert (
        restored["command"]["index"]
        == 2
    )


def test_checkpoint_status_transition_is_persisted(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path
    )

    checkpoint_id = (
        store.put_checkpoint(
            payload
        )
    )

    assert store.update_checkpoint_status(
        checkpoint_id,
        "accepted",
    )

    restarted = storage.Store()

    restored = (
        restarted.get_checkpoint(
            checkpoint_id
        )
    )

    assert restored is not None

    assert (
        restored["status"]
        == "accepted"
    )

    assert (
        restored["updated_at"]
        != ""
    )


def test_checkpoint_listing_can_be_scoped_to_workspace(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    first_workspace = (
        tmp_path /
        "first"
    )

    second_workspace = (
        tmp_path /
        "second"
    )

    first_workspace.mkdir()
    second_workspace.mkdir()

    first = checkpoint(
        first_workspace,
        checkpoint_id="checkpoint-first",
        created_at=(
            "2026-10-05T10:00:00+00:00"
        ),
    )

    second = checkpoint(
        first_workspace,
        checkpoint_id="checkpoint-second",
        created_at=(
            "2026-10-05T11:00:00+00:00"
        ),
    )

    other = checkpoint(
        second_workspace,
        checkpoint_id="checkpoint-other",
        created_at=(
            "2026-10-05T12:00:00+00:00"
        ),
    )

    store.put_checkpoint(first)
    store.put_checkpoint(second)
    store.put_checkpoint(other)

    items = store.list_checkpoints(
        workspace_root=str(
            first_workspace.resolve()
        )
    )

    assert [
        item["checkpoint_id"]
        for item in items
    ] == [
        "checkpoint-second",
        "checkpoint-first",
    ]


def test_store_rejects_executable_continuation_state(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path
    )

    payload["continuation"] = {
        "contract": "must-not-persist",
        "approved_index": 2,
    }

    with pytest.raises(
        ValueError,
        match="executable continuation state",
    ):
        store.put_checkpoint(
            payload
        )


def test_invalid_checkpoint_status_is_rejected(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path
    )

    checkpoint_id = (
        store.put_checkpoint(
            payload
        )
    )

    with pytest.raises(
        ValueError,
        match="Invalid checkpoint status",
    ):
        store.update_checkpoint_status(
            checkpoint_id,
            "executing",
        )


def test_checkpoint_atomic_transition_ready_to_accepted(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path,
        checkpoint_id="cp-accept",
    )

    store.put_checkpoint(
        payload
    )

    assert store.transition_checkpoint_status(
        "cp-accept",
        expected_status="ready",
        new_status="accepted",
    )

    restored = store.get_checkpoint(
        "cp-accept"
    )

    assert restored is not None
    assert restored["status"] == "accepted"


def test_checkpoint_atomic_transition_rejects_stale_expected_status(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path,
        checkpoint_id="cp-cas",
    )

    store.put_checkpoint(
        payload
    )

    assert store.transition_checkpoint_status(
        "cp-cas",
        expected_status="ready",
        new_status="rolling_back",
    )

    assert (
        store.transition_checkpoint_status(
            "cp-cas",
            expected_status="ready",
            new_status="accepted",
        )
        is False
    )

    restored = store.get_checkpoint(
        "cp-cas"
    )

    assert restored is not None
    assert restored["status"] == "rolling_back"


def test_checkpoint_rollback_transition_chain(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path,
        checkpoint_id="cp-rollback",
    )

    store.put_checkpoint(
        payload
    )

    assert store.transition_checkpoint_status(
        "cp-rollback",
        expected_status="ready",
        new_status="rolling_back",
    )

    assert store.transition_checkpoint_status(
        "cp-rollback",
        expected_status="rolling_back",
        new_status="rolled_back",
    )

    restored = store.get_checkpoint(
        "cp-rollback"
    )

    assert restored is not None
    assert restored["status"] == "rolled_back"


def test_checkpoint_rollback_failure_transition(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path,
        checkpoint_id="cp-failed",
    )

    store.put_checkpoint(
        payload
    )

    assert store.transition_checkpoint_status(
        "cp-failed",
        expected_status="ready",
        new_status="rolling_back",
    )

    assert store.transition_checkpoint_status(
        "cp-failed",
        expected_status="rolling_back",
        new_status="rollback_failed",
    )

    restored = store.get_checkpoint(
        "cp-failed"
    )

    assert restored is not None
    assert (
        restored["status"]
        == "rollback_failed"
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (
            "ready",
            "rolled_back",
        ),
        (
            "accepted",
            "ready",
        ),
        (
            "accepted",
            "rolling_back",
        ),
        (
            "rolled_back",
            "ready",
        ),
        (
            "rollback_failed",
            "rolling_back",
        ),
    ],
)
def test_checkpoint_invalid_lifecycle_transition_is_rejected(
    monkeypatch,
    tmp_path: Path,
    current,
    target,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path,
        checkpoint_id=(
            "cp-invalid-"
            + current
            + "-"
            + target
        ),
        status=current,
    )

    store.put_checkpoint(
        payload
    )

    with pytest.raises(
        ValueError,
        match="Invalid checkpoint transition",
    ):
        store.transition_checkpoint_status(
            payload["checkpoint_id"],
            expected_status=current,
            new_status=target,
        )


def test_missing_checkpoint_transition_returns_false(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    assert (
        store.transition_checkpoint_status(
            "does-not-exist",
            expected_status="ready",
            new_status="accepted",
        )
        is False
    )


def test_legacy_status_update_cannot_bypass_lifecycle(
    monkeypatch,
    tmp_path: Path,
):
    store = isolated_store(
        monkeypatch,
        tmp_path,
    )

    payload = checkpoint(
        tmp_path,
        checkpoint_id="cp-legacy-guard",
    )

    store.put_checkpoint(
        payload
    )

    with pytest.raises(
        ValueError,
        match="Invalid checkpoint transition",
    ):
        store.update_checkpoint_status(
            "cp-legacy-guard",
            "rolled_back",
        )

    restored = store.get_checkpoint(
        "cp-legacy-guard"
    )

    assert restored is not None
    assert restored["status"] == "ready"
