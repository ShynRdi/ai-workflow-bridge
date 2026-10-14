from __future__ import annotations

import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(
        0,
        str(HOST),
    )


from checkpoint_snapshot import (
    create_workspace_snapshot,
    verify_workspace_snapshot,
)


def test_snapshot_round_trip_archive(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    (workspace / "app.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    folder = (
        workspace /
        "src"
    )

    folder.mkdir()

    (folder / "main.txt").write_text(
        "content",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-one",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    assert metadata["file_count"] == 2
    assert metadata["total_bytes"] > 0

    assert verify_workspace_snapshot(
        metadata
    )

    archive = Path(
        metadata["archive_path"]
    )

    with tarfile.open(
        archive,
        "r:gz",
    ) as tf:
        names = set(
            tf.getnames()
        )

    assert "app.py" in names
    assert "src" in names
    assert "src/main.txt" in names


def test_native_and_git_state_are_excluded(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    (workspace / "visible.txt").write_text(
        "keep",
        encoding="utf-8",
    )

    git_dir = (
        workspace /
        ".git"
    )

    git_dir.mkdir()

    (git_dir / "secret").write_text(
        "git-internal",
        encoding="utf-8",
    )

    control = (
        workspace /
        ".ai-workflow"
    )

    control.mkdir()

    (control / "ROADMAP.md").write_text(
        "native-owned",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-exclusions",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    assert ".git" in metadata[
        "excluded_paths"
    ]

    assert ".ai-workflow" in metadata[
        "excluded_paths"
    ]

    with tarfile.open(
        metadata["archive_path"],
        "r:gz",
    ) as tf:
        names = tf.getnames()

    assert "visible.txt" in names

    assert not any(
        name.startswith(".git")
        for name in names
    )

    assert not any(
        name.startswith(
            ".ai-workflow"
        )
        for name in names
    )


def test_volatile_directories_are_reported_as_excluded(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    node_modules = (
        workspace /
        "node_modules"
    )

    node_modules.mkdir()

    (node_modules / "huge.js").write_text(
        "ignored",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-volatile",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    assert (
        "node_modules"
        in metadata[
            "excluded_paths"
        ]
    )

    assert metadata[
        "file_count"
    ] == 0


def test_snapshot_refuses_symlink(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    outside = (
        tmp_path /
        "outside.txt"
    )

    workspace.mkdir()

    outside.write_text(
        "outside",
        encoding="utf-8",
    )

    (
        workspace /
        "escape"
    ).symlink_to(
        outside
    )

    with pytest.raises(
        ValueError,
        match="symbolic link",
    ):
        create_workspace_snapshot(
            checkpoint_id="cp-link",
            workspace_root=str(
                workspace
            ),
            storage_root=storage,
        )

    assert not (
        storage /
        "cp-link"
    ).exists()


def test_snapshot_enforces_total_size_limit(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    (workspace / "large.bin").write_bytes(
        b"x" * 32
    )

    with pytest.raises(
        ValueError,
        match="total-size limit",
    ):
        create_workspace_snapshot(
            checkpoint_id="cp-size",
            workspace_root=str(
                workspace
            ),
            storage_root=storage,
            max_total_bytes=16,
            max_file_bytes=64,
        )

    assert not (
        storage /
        "cp-size"
    ).exists()


def test_snapshot_enforces_single_file_limit(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    (workspace / "large.bin").write_bytes(
        b"x" * 32
    )

    with pytest.raises(
        ValueError,
        match="file exceeds limit",
    ):
        create_workspace_snapshot(
            checkpoint_id="cp-file-size",
            workspace_root=str(
                workspace
            ),
            storage_root=storage,
            max_file_bytes=16,
        )


def test_checkpoint_id_cannot_escape_storage(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    with pytest.raises(
        ValueError,
        match="Unsafe checkpoint id",
    ):
        create_workspace_snapshot(
            checkpoint_id="../escape",
            workspace_root=str(
                workspace
            ),
            storage_root=storage,
        )


def test_storage_cannot_live_inside_workspace(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir()

    storage = (
        workspace /
        ".snapshots"
    )

    with pytest.raises(
        ValueError,
        match="must not be inside",
    ):
        create_workspace_snapshot(
            checkpoint_id="cp-inside",
            workspace_root=str(
                workspace
            ),
            storage_root=storage,
        )


def test_archive_tampering_is_detected(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    (workspace / "file.txt").write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-hash",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    archive = Path(
        metadata["archive_path"]
    )

    archive.write_bytes(
        archive.read_bytes()
        + b"tampered"
    )

    assert (
        verify_workspace_snapshot(
            metadata
        )
        is False
    )


def test_snapshot_cleanup_removes_only_checkpoint_directory(
    tmp_path: Path,
):
    from checkpoint_snapshot import (
        remove_workspace_snapshot,
    )

    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    (workspace / "file.txt").write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-cleanup",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    checkpoint_dir = Path(
        metadata[
            "archive_path"
        ]
    ).parent

    other = (
        storage /
        "other"
    )

    other.mkdir()

    assert checkpoint_dir.is_dir()

    assert remove_workspace_snapshot(
        checkpoint_id="cp-cleanup",
        storage_root=storage,
    )

    assert not checkpoint_dir.exists()
    assert other.is_dir()

    assert (
        remove_workspace_snapshot(
            checkpoint_id="cp-cleanup",
            storage_root=storage,
        )
        is False
    )


def test_snapshot_cleanup_removes_only_checkpoint_directory(
    tmp_path: Path,
):
    from checkpoint_snapshot import (
        remove_workspace_snapshot,
    )

    workspace = (
        tmp_path /
        "workspace"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()

    (workspace / "file.txt").write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-cleanup",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    checkpoint_dir = Path(
        metadata[
            "archive_path"
        ]
    ).parent

    other = (
        storage /
        "other"
    )

    other.mkdir()

    assert checkpoint_dir.is_dir()

    assert remove_workspace_snapshot(
        checkpoint_id="cp-cleanup",
        storage_root=storage,
    )

    assert not checkpoint_dir.exists()
    assert other.is_dir()

    assert (
        remove_workspace_snapshot(
            checkpoint_id="cp-cleanup",
            storage_root=storage,
        )
        is False
    )
