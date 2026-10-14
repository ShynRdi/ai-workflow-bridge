from __future__ import annotations

import hashlib
import io
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


from checkpoint_restore import (
    restore_workspace_snapshot,
)
from checkpoint_snapshot import (
    create_workspace_snapshot,
)


def test_restore_returns_workspace_to_checkpoint_state(
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

    (workspace / "app.txt").write_text(
        "before\n",
        encoding="utf-8",
    )

    src = (
        workspace /
        "src"
    )

    src.mkdir()

    (src / "keep.txt").write_text(
        "original\n",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-restore",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    (workspace / "app.txt").write_text(
        "after\n",
        encoding="utf-8",
    )

    (src / "keep.txt").unlink()

    (workspace / "new.txt").write_text(
        "new\n",
        encoding="utf-8",
    )

    extra = (
        workspace /
        "extra"
    )

    extra.mkdir()

    (extra / "created.txt").write_text(
        "created\n",
        encoding="utf-8",
    )

    report = restore_workspace_snapshot(
        metadata=metadata,
        workspace_root=str(
            workspace
        ),
    )

    assert (
        workspace /
        "app.txt"
    ).read_text(
        encoding="utf-8",
    ) == "before\n"

    assert (
        src /
        "keep.txt"
    ).read_text(
        encoding="utf-8",
    ) == "original\n"

    assert not (
        workspace /
        "new.txt"
    ).exists()

    assert not extra.exists()

    assert (
        report[
            "rollback_scope"
        ]
        == "workspace_files_only"
    )

    assert (
        report[
            "external_side_effects_restored"
        ]
        is False
    )


def test_restore_preserves_excluded_state(
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

    (workspace / "tracked.txt").write_text(
        "before",
        encoding="utf-8",
    )

    git_dir = (
        workspace /
        ".git"
    )

    git_dir.mkdir()

    (git_dir / "state").write_text(
        "git-before",
        encoding="utf-8",
    )

    control = (
        workspace /
        ".ai-workflow"
    )

    control.mkdir()

    (control / "ROADMAP.md").write_text(
        "roadmap-before",
        encoding="utf-8",
    )

    modules = (
        workspace /
        "node_modules"
    )

    modules.mkdir()

    (modules / "cache").write_text(
        "modules-before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-preserve",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    (workspace / "tracked.txt").write_text(
        "after",
        encoding="utf-8",
    )

    (git_dir / "state").write_text(
        "git-after",
        encoding="utf-8",
    )

    (control / "ROADMAP.md").write_text(
        "roadmap-after",
        encoding="utf-8",
    )

    (modules / "cache").write_text(
        "modules-after",
        encoding="utf-8",
    )

    report = restore_workspace_snapshot(
        metadata=metadata,
    )

    assert (
        workspace /
        "tracked.txt"
    ).read_text(
        encoding="utf-8",
    ) == "before"

    assert (
        git_dir /
        "state"
    ).read_text(
        encoding="utf-8",
    ) == "git-after"

    assert (
        control /
        "ROADMAP.md"
    ).read_text(
        encoding="utf-8",
    ) == "roadmap-after"

    assert (
        modules /
        "cache"
    ).read_text(
        encoding="utf-8",
    ) == "modules-after"

    assert ".git" in report[
        "preserved_excluded_paths"
    ]

    assert ".ai-workflow" in report[
        "preserved_excluded_paths"
    ]

    assert "node_modules" in report[
        "preserved_excluded_paths"
    ]


def test_tampered_archive_fails_before_workspace_mutation(
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

    target = (
        workspace /
        "file.txt"
    )

    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-tamper",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    archive = Path(
        metadata[
            "archive_path"
        ]
    )

    archive.write_bytes(
        archive.read_bytes()
        + b"tampered"
    )

    with pytest.raises(
        ValueError,
        match="integrity",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"


def test_path_traversal_archive_is_rejected(
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

    target = (
        workspace /
        "file.txt"
    )

    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-traversal",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    archive = Path(
        metadata[
            "archive_path"
        ]
    )

    with tarfile.open(
        archive,
        "w:gz",
    ) as tf:
        info = tarfile.TarInfo(
            "../escape.txt"
        )

        payload = b"escape"

        info.size = len(
            payload
        )

        tf.addfile(
            info,
            io.BytesIO(
                payload
            ),
        )

    metadata[
        "archive_sha256"
    ] = hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()

    metadata[
        "file_count"
    ] = 1

    metadata[
        "total_bytes"
    ] = len(
        b"escape"
    )

    with pytest.raises(
        ValueError,
        match="Unsafe archive member",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"

    assert not (
        tmp_path /
        "escape.txt"
    ).exists()


def test_post_checkpoint_symlink_is_unlinked_not_followed(
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

    original = (
        workspace /
        "file.txt"
    )

    original.write_text(
        "before",
        encoding="utf-8",
    )

    outside.write_text(
        "outside",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-symlink",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    original.unlink()

    original.symlink_to(
        outside
    )

    restore_workspace_snapshot(
        metadata=metadata,
    )

    assert not original.is_symlink()

    assert original.read_text(
        encoding="utf-8",
    ) == "before"

    assert outside.read_text(
        encoding="utf-8",
    ) == "outside"


def test_workspace_identity_mismatch_is_rejected(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    other = (
        tmp_path /
        "other"
    )

    storage = (
        tmp_path /
        "storage"
    )

    workspace.mkdir()
    other.mkdir()

    (workspace / "file").write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-workspace",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
            workspace_root=str(
                other
            ),
        )


def test_restore_fails_before_mutation_when_excluded_state_blocks_file_restore(
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

    target = (
        workspace /
        "target"
    )

    target.write_text(
        "checkpoint-file",
        encoding="utf-8",
    )

    sentinel = (
        workspace /
        "sentinel.txt"
    )

    sentinel.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-conflict",
        workspace_root=str(
            workspace
        ),
        storage_root=storage,
    )

    target.unlink()
    target.mkdir()

    excluded = (
        target /
        "node_modules"
    )

    excluded.mkdir()

    (
        excluded /
        "keep"
    ).write_text(
        "out-of-scope",
        encoding="utf-8",
    )

    sentinel.write_text(
        "after",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="excluded",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    # Preflight failed before any rollback mutation.
    assert sentinel.read_text(
        encoding="utf-8",
    ) == "after"

    assert (
        excluded /
        "keep"
    ).read_text(
        encoding="utf-8",
    ) == "out-of-scope"


def _rewrite_archive(
    metadata,
    writer,
):
    archive = Path(
        metadata["archive_path"]
    )

    writer(
        archive
    )

    metadata[
        "archive_sha256"
    ] = hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()


def test_duplicate_archive_members_are_rejected_before_mutation(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-duplicate",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    def writer(archive):
        with tarfile.open(
            archive,
            "w:gz",
        ) as tf:
            for payload in (
                b"first",
                b"second",
            ):
                info = tarfile.TarInfo(
                    "duplicate.txt"
                )

                info.size = len(payload)

                tf.addfile(
                    info,
                    io.BytesIO(payload),
                )

    _rewrite_archive(
        metadata,
        writer,
    )

    metadata["file_count"] = 2
    metadata["total_bytes"] = (
        len(b"first")
        + len(b"second")
    )

    with pytest.raises(
        ValueError,
        match="duplicate member",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"


def test_archive_symlink_member_is_rejected_before_mutation(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-member-link",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    def writer(archive):
        with tarfile.open(
            archive,
            "w:gz",
        ) as tf:
            info = tarfile.TarInfo(
                "escape-link"
            )

            info.type = tarfile.SYMTYPE
            info.linkname = "/tmp/outside"

            tf.addfile(info)

    _rewrite_archive(
        metadata,
        writer,
    )

    metadata["file_count"] = 0
    metadata["total_bytes"] = 0

    with pytest.raises(
        ValueError,
        match="unsupported member type",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        (
            "file_count",
            999,
            "file-count metadata mismatch",
        ),
        (
            "total_bytes",
            999999,
            "size metadata mismatch",
        ),
    ],
)
def test_archive_metadata_mismatch_fails_before_mutation(
    tmp_path: Path,
    field,
    value,
    match,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id=(
            "cp-metadata-"
            + field.replace("_", "-")
        ),
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    metadata[field] = value

    with pytest.raises(
        ValueError,
        match=match,
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"


def test_malicious_native_control_member_is_rejected_and_preserved(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    control = (
        workspace /
        ".ai-workflow"
    )

    control.mkdir()

    roadmap = (
        control /
        "ROADMAP.md"
    )

    roadmap.write_text(
        "native-before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-control-attack",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    roadmap.write_text(
        "native-after",
        encoding="utf-8",
    )

    def writer(archive):
        payload = b"malicious-roadmap"

        with tarfile.open(
            archive,
            "w:gz",
        ) as tf:
            info = tarfile.TarInfo(
                ".ai-workflow/ROADMAP.md"
            )

            info.size = len(payload)

            tf.addfile(
                info,
                io.BytesIO(payload),
            )

    _rewrite_archive(
        metadata,
        writer,
    )

    metadata["file_count"] = 1
    metadata["total_bytes"] = len(
        b"malicious-roadmap"
    )

    with pytest.raises(
        ValueError,
        match="excluded path",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"

    assert roadmap.read_text(
        encoding="utf-8",
    ) == "native-after"


def test_symlinked_archive_path_is_rejected(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    (
        workspace /
        "file.txt"
    ).write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-archive-link",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    real_archive = Path(
        metadata["archive_path"]
    )

    alias_root = (
        tmp_path /
        "alias"
    )

    alias_dir = (
        alias_root /
        "cp-archive-link"
    )

    alias_dir.mkdir(
        parents=True,
    )

    alias_archive = (
        alias_dir /
        "workspace.tar.gz"
    )

    alias_archive.symlink_to(
        real_archive
    )

    metadata[
        "archive_path"
    ] = str(
        alias_archive
    )

    with pytest.raises(
        ValueError,
        match="must not be symbolic",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )


def _rewrite_archive(
    metadata,
    writer,
):
    archive = Path(
        metadata["archive_path"]
    )

    writer(
        archive
    )

    metadata[
        "archive_sha256"
    ] = hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()


def test_duplicate_archive_members_are_rejected_before_mutation(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-duplicate",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    def writer(archive):
        with tarfile.open(
            archive,
            "w:gz",
        ) as tf:
            for payload in (
                b"first",
                b"second",
            ):
                info = tarfile.TarInfo(
                    "duplicate.txt"
                )

                info.size = len(payload)

                tf.addfile(
                    info,
                    io.BytesIO(payload),
                )

    _rewrite_archive(
        metadata,
        writer,
    )

    metadata["file_count"] = 2
    metadata["total_bytes"] = (
        len(b"first")
        + len(b"second")
    )

    with pytest.raises(
        ValueError,
        match="duplicate member",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"


def test_archive_symlink_member_is_rejected_before_mutation(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-member-link",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    def writer(archive):
        with tarfile.open(
            archive,
            "w:gz",
        ) as tf:
            info = tarfile.TarInfo(
                "escape-link"
            )

            info.type = tarfile.SYMTYPE
            info.linkname = "/tmp/outside"

            tf.addfile(info)

    _rewrite_archive(
        metadata,
        writer,
    )

    metadata["file_count"] = 0
    metadata["total_bytes"] = 0

    with pytest.raises(
        ValueError,
        match="unsupported member type",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        (
            "file_count",
            999,
            "file-count metadata mismatch",
        ),
        (
            "total_bytes",
            999999,
            "size metadata mismatch",
        ),
    ],
)
def test_archive_metadata_mismatch_fails_before_mutation(
    tmp_path: Path,
    field,
    value,
    match,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id=(
            "cp-metadata-"
            + field.replace("_", "-")
        ),
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    metadata[field] = value

    with pytest.raises(
        ValueError,
        match=match,
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"


def test_malicious_native_control_member_is_rejected_and_preserved(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    target = workspace / "file.txt"
    target.write_text(
        "before",
        encoding="utf-8",
    )

    control = (
        workspace /
        ".ai-workflow"
    )

    control.mkdir()

    roadmap = (
        control /
        "ROADMAP.md"
    )

    roadmap.write_text(
        "native-before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-control-attack",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    target.write_text(
        "after",
        encoding="utf-8",
    )

    roadmap.write_text(
        "native-after",
        encoding="utf-8",
    )

    def writer(archive):
        payload = b"malicious-roadmap"

        with tarfile.open(
            archive,
            "w:gz",
        ) as tf:
            info = tarfile.TarInfo(
                ".ai-workflow/ROADMAP.md"
            )

            info.size = len(payload)

            tf.addfile(
                info,
                io.BytesIO(payload),
            )

    _rewrite_archive(
        metadata,
        writer,
    )

    metadata["file_count"] = 1
    metadata["total_bytes"] = len(
        b"malicious-roadmap"
    )

    with pytest.raises(
        ValueError,
        match="excluded path",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )

    assert target.read_text(
        encoding="utf-8",
    ) == "after"

    assert roadmap.read_text(
        encoding="utf-8",
    ) == "native-after"


def test_symlinked_archive_path_is_rejected(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    storage = tmp_path / "storage"

    workspace.mkdir()

    (
        workspace /
        "file.txt"
    ).write_text(
        "before",
        encoding="utf-8",
    )

    metadata = create_workspace_snapshot(
        checkpoint_id="cp-archive-link",
        workspace_root=str(workspace),
        storage_root=storage,
    )

    real_archive = Path(
        metadata["archive_path"]
    )

    alias_root = (
        tmp_path /
        "alias"
    )

    alias_dir = (
        alias_root /
        "cp-archive-link"
    )

    alias_dir.mkdir(
        parents=True,
    )

    alias_archive = (
        alias_dir /
        "workspace.tar.gz"
    )

    alias_archive.symlink_to(
        real_archive
    )

    metadata[
        "archive_path"
    ] = str(
        alias_archive
    )

    with pytest.raises(
        ValueError,
        match="must not be symbolic",
    ):
        restore_workspace_snapshot(
            metadata=metadata,
        )
