from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
from pathlib import Path
from typing import Any

import config


SNAPSHOT_VERSION = 1

DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 128 * 1024 * 1024

ALWAYS_EXCLUDED_NAMES = {
    ".git",
    ".ai-workflow",
}

VOLATILE_DIRECTORY_NAMES = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".next",
    "dist",
    "build",
    "coverage",
}

CHECKPOINT_ID_RE = re.compile(
    r"^[A-Za-z0-9._-]{1,128}$"
)


def _inside(
    root: Path,
    candidate: Path,
) -> bool:
    try:
        candidate.resolve().relative_to(
            root.resolve()
        )
        return True
    except ValueError:
        return False


def _safe_checkpoint_id(
    checkpoint_id: str,
) -> str:
    value = str(
        checkpoint_id or ""
    ).strip()

    if not CHECKPOINT_ID_RE.fullmatch(
        value
    ):
        raise ValueError(
            "Unsafe checkpoint id"
        )

    return value


def _sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def _write_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    os.replace(
        tmp,
        path,
    )

    try:
        path.chmod(0o600)
    except OSError:
        pass


def _snapshot_storage_root(
    storage_root: str | Path | None,
) -> Path:
    if storage_root is None:
        root = (
            config.APP_DIR /
            "checkpoints"
        )
    else:
        root = Path(
            storage_root
        ).expanduser()

    root = root.resolve()

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        root.chmod(0o700)
    except OSError:
        pass

    return root


def _walk_workspace(
    root: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_file_bytes: int,
) -> tuple[
    list[tuple[Path, str, bool]],
    list[str],
    int,
    int,
]:
    entries: list[
        tuple[Path, str, bool]
    ] = []

    excluded: list[str] = []

    file_count = 0
    total_bytes = 0

    def visit(
        directory: Path,
        relative: Path,
    ) -> None:
        nonlocal file_count
        nonlocal total_bytes

        with os.scandir(
            directory
        ) as iterator:
            children = sorted(
                iterator,
                key=lambda item: item.name,
            )

        for entry in children:
            rel = relative / entry.name
            rel_text = rel.as_posix()

            if entry.name in ALWAYS_EXCLUDED_NAMES:
                excluded.append(
                    rel_text
                )
                continue

            if (
                entry.is_dir(
                    follow_symlinks=False
                )
                and entry.name
                in VOLATILE_DIRECTORY_NAMES
            ):
                excluded.append(
                    rel_text
                )
                continue

            if entry.is_symlink():
                raise ValueError(
                    "Workspace snapshot refuses "
                    f"symbolic link: {rel_text}"
                )

            path = Path(
                entry.path
            )

            if entry.is_dir(
                follow_symlinks=False
            ):
                entries.append(
                    (
                        path,
                        rel_text,
                        True,
                    )
                )

                visit(
                    path,
                    rel,
                )

                continue

            if not entry.is_file(
                follow_symlinks=False
            ):
                raise ValueError(
                    "Workspace snapshot found "
                    "unsupported filesystem entry: "
                    f"{rel_text}"
                )

            size = entry.stat(
                follow_symlinks=False
            ).st_size

            if size > max_file_bytes:
                raise ValueError(
                    "Workspace snapshot file exceeds "
                    f"limit: {rel_text} "
                    f"({size} bytes)"
                )

            file_count += 1
            total_bytes += size

            if file_count > max_files:
                raise ValueError(
                    "Workspace snapshot exceeds "
                    f"file-count limit ({max_files})"
                )

            if total_bytes > max_total_bytes:
                raise ValueError(
                    "Workspace snapshot exceeds "
                    "total-size limit "
                    f"({max_total_bytes} bytes)"
                )

            entries.append(
                (
                    path,
                    rel_text,
                    False,
                )
            )

    visit(
        root,
        Path(),
    )

    return (
        entries,
        sorted(
            set(excluded)
        ),
        file_count,
        total_bytes,
    )


def create_workspace_snapshot(
    *,
    checkpoint_id: str,
    workspace_root: str,
    storage_root: str | Path | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, Any]:
    checkpoint_id = (
        _safe_checkpoint_id(
            checkpoint_id
        )
    )

    original_root = Path(
        workspace_root
    ).expanduser()

    if original_root.is_symlink():
        raise ValueError(
            "Workspace root must not be "
            "a symbolic link"
        )

    root = original_root.resolve()

    if not root.is_dir():
        raise ValueError(
            f"Workspace does not exist: {root}"
        )

    storage = _snapshot_storage_root(
        storage_root
    )

    if _inside(
        root,
        storage,
    ):
        raise ValueError(
            "Checkpoint storage must not "
            "be inside the workspace"
        )

    checkpoint_dir = (
        storage /
        checkpoint_id
    )

    if checkpoint_dir.exists():
        raise FileExistsError(
            "Checkpoint snapshot already exists: "
            f"{checkpoint_id}"
        )

    checkpoint_dir.mkdir(
        parents=False,
        exist_ok=False,
    )

    try:
        checkpoint_dir.chmod(
            0o700
        )
    except OSError:
        pass

    archive = (
        checkpoint_dir /
        "workspace.tar.gz"
    )

    archive_tmp = (
        checkpoint_dir /
        "workspace.tar.gz.tmp"
    )

    metadata_path = (
        checkpoint_dir /
        "snapshot.json"
    )

    try:
        (
            entries,
            excluded,
            file_count,
            total_bytes,
        ) = _walk_workspace(
            root,
            max_files=max_files,
            max_total_bytes=max_total_bytes,
            max_file_bytes=max_file_bytes,
        )

        with tarfile.open(
            archive_tmp,
            mode="w:gz",
            dereference=False,
        ) as tf:
            for (
                path,
                relative,
                is_directory,
            ) in entries:
                tf.add(
                    path,
                    arcname=relative,
                    recursive=False,
                )

        os.replace(
            archive_tmp,
            archive,
        )

        try:
            archive.chmod(
                0o600
            )
        except OSError:
            pass

        archive_sha256 = (
            _sha256_file(
                archive
            )
        )

        metadata = {
            "version": SNAPSHOT_VERSION,
            "kind": "workspace_tar_v1",
            "checkpoint_id": checkpoint_id,
            "workspace_root": str(
                root
            ),
            "archive_path": str(
                archive
            ),
            "archive_sha256": (
                archive_sha256
            ),
            "file_count": file_count,
            "total_bytes": total_bytes,
            "excluded_paths": excluded,
            "limits": {
                "max_files": max_files,
                "max_total_bytes": (
                    max_total_bytes
                ),
                "max_file_bytes": (
                    max_file_bytes
                ),
            },
        }

        _write_json_atomic(
            metadata_path,
            metadata,
        )

        return metadata

    except Exception:
        shutil.rmtree(
            checkpoint_dir,
            ignore_errors=True,
        )
        raise


def remove_workspace_snapshot(
    *,
    checkpoint_id: str,
    storage_root: str | Path | None = None,
) -> bool:
    checkpoint_id = _safe_checkpoint_id(
        checkpoint_id
    )

    storage = _snapshot_storage_root(
        storage_root
    )

    target = (
        storage /
        checkpoint_id
    )

    if target.is_symlink():
        target.unlink()
        return True

    if not target.exists():
        return False

    if not target.is_dir():
        raise ValueError(
            "Checkpoint snapshot path is not "
            "a directory"
        )

    shutil.rmtree(
        target
    )

    return True


def verify_workspace_snapshot(
    metadata: dict[str, Any],
) -> bool:
    if not isinstance(
        metadata,
        dict,
    ):
        return False

    if (
        metadata.get("version")
        != SNAPSHOT_VERSION
    ):
        return False

    archive = Path(
        str(
            metadata.get(
                "archive_path"
            )
            or ""
        )
    )

    expected = str(
        metadata.get(
            "archive_sha256"
        )
        or ""
    )

    if (
        not archive.is_file()
        or not expected
    ):
        return False

    return (
        _sha256_file(
            archive
        )
        == expected
    )
