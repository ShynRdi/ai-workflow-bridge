from __future__ import annotations

import hashlib
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from checkpoint_snapshot import (
    ALWAYS_EXCLUDED_NAMES,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TOTAL_BYTES,
    SNAPSHOT_VERSION,
    VOLATILE_DIRECTORY_NAMES,
)


RESTORE_VERSION = 1

CHECKPOINT_ID_RE = re.compile(
    r"^[A-Za-z0-9._-]{1,128}$"
)

MAX_ARCHIVE_MEMBERS = (
    DEFAULT_MAX_FILES * 4
    + 1024
)


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


def _safe_checkpoint_id(
    value: Any,
) -> str:
    checkpoint_id = str(
        value or ""
    ).strip()

    if not CHECKPOINT_ID_RE.fullmatch(
        checkpoint_id
    ):
        raise ValueError(
            "Unsafe checkpoint id"
        )

    return checkpoint_id


def _is_excluded_name(
    value: str,
) -> bool:
    return (
        value in ALWAYS_EXCLUDED_NAMES
        or value
        in VOLATILE_DIRECTORY_NAMES
    )


def _is_excluded_relative(
    relative: PurePosixPath,
) -> bool:
    return any(
        _is_excluded_name(part)
        for part in relative.parts
    )


def _validated_member_path(
    name: str,
) -> PurePosixPath:
    value = str(
        name or ""
    )

    if (
        not value
        or value.startswith("/")
        or "\\" in value
    ):
        raise ValueError(
            f"Unsafe archive member: {value!r}"
        )

    relative = PurePosixPath(
        value
    )

    if (
        relative.is_absolute()
        or not relative.parts
        or any(
            part in {
                "",
                ".",
                "..",
            }
            for part in relative.parts
        )
    ):
        raise ValueError(
            f"Unsafe archive member: {value!r}"
        )

    if _is_excluded_relative(
        relative
    ):
        raise ValueError(
            "Checkpoint archive illegally "
            f"contains excluded path: {value}"
        )

    return relative


def _validated_archive(
    metadata: dict[str, Any],
) -> tuple[
    str,
    Path,
]:
    if not isinstance(
        metadata,
        dict,
    ):
        raise ValueError(
            "Snapshot metadata must be a mapping"
        )

    if (
        metadata.get("version")
        != SNAPSHOT_VERSION
    ):
        raise ValueError(
            "Unsupported snapshot version"
        )

    if (
        str(
            metadata.get("kind")
            or ""
        )
        != "workspace_tar_v1"
    ):
        raise ValueError(
            "Unsupported snapshot kind"
        )

    checkpoint_id = (
        _safe_checkpoint_id(
            metadata.get(
                "checkpoint_id"
            )
        )
    )

    raw_archive = str(
        metadata.get(
            "archive_path"
        )
        or ""
    ).strip()

    if not raw_archive:
        raise ValueError(
            "Snapshot archive path is missing"
        )

    archive_candidate = Path(
        raw_archive
    ).expanduser()

    if not archive_candidate.is_absolute():
        raise ValueError(
            "Snapshot archive path must "
            "be absolute"
        )

    # Check the path supplied by checkpoint metadata BEFORE
    # resolve(), otherwise a symlink would disappear from
    # observation after canonicalization.
    if (
        archive_candidate.is_symlink()
        or archive_candidate.parent.is_symlink()
    ):
        raise ValueError(
            "Snapshot archive path must not "
            "be symbolic"
        )

    archive = archive_candidate.resolve()

    if (
        archive.name
        != "workspace.tar.gz"
    ):
        raise ValueError(
            "Unexpected snapshot archive filename"
        )

    if (
        archive.parent.name
        != checkpoint_id
    ):
        raise ValueError(
            "Snapshot archive/checkpoint "
            "identity mismatch"
        )

    if not archive.is_file():
        raise ValueError(
            "Snapshot archive does not exist"
        )

    expected = str(
        metadata.get(
            "archive_sha256"
        )
        or ""
    ).strip().lower()

    if not re.fullmatch(
        r"[0-9a-f]{64}",
        expected,
    ):
        raise ValueError(
            "Snapshot archive SHA-256 "
            "is invalid"
        )

    actual = _sha256_file(
        archive
    )

    if actual != expected:
        raise ValueError(
            "Snapshot archive integrity "
            "verification failed"
        )

    return (
        checkpoint_id,
        archive,
    )


def _validated_workspace(
    metadata: dict[str, Any],
    workspace_root: str | None,
) -> Path:
    expected_raw = str(
        metadata.get(
            "workspace_root"
        )
        or ""
    ).strip()

    if not expected_raw:
        raise ValueError(
            "Snapshot workspace root "
            "is missing"
        )

    expected = Path(
        expected_raw
    ).expanduser().resolve()

    selected_raw = Path(
        workspace_root
        if workspace_root is not None
        else expected_raw
    ).expanduser()

    if selected_raw.is_symlink():
        raise ValueError(
            "Workspace root must not "
            "be a symbolic link"
        )

    selected = (
        selected_raw.resolve()
    )

    if selected != expected:
        raise ValueError(
            "Rollback workspace does not "
            "match checkpoint workspace"
        )

    if not selected.is_dir():
        raise ValueError(
            "Rollback workspace does not exist"
        )

    return selected


def _positive_bounded_int(
    value: Any,
    default: int,
    hard_max: int,
) -> int:
    try:
        parsed = int(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        parsed = default

    if parsed <= 0:
        parsed = default

    return min(
        parsed,
        hard_max,
    )


def _snapshot_limits(
    metadata: dict[str, Any],
) -> tuple[
    int,
    int,
    int,
]:
    raw = metadata.get(
        "limits"
    )

    limits = (
        raw
        if isinstance(raw, dict)
        else {}
    )

    max_files = (
        _positive_bounded_int(
            limits.get(
                "max_files"
            ),
            DEFAULT_MAX_FILES,
            DEFAULT_MAX_FILES,
        )
    )

    max_total_bytes = (
        _positive_bounded_int(
            limits.get(
                "max_total_bytes"
            ),
            DEFAULT_MAX_TOTAL_BYTES,
            DEFAULT_MAX_TOTAL_BYTES,
        )
    )

    max_file_bytes = (
        _positive_bounded_int(
            limits.get(
                "max_file_bytes"
            ),
            DEFAULT_MAX_FILE_BYTES,
            DEFAULT_MAX_FILE_BYTES,
        )
    )

    return (
        max_files,
        max_total_bytes,
        max_file_bytes,
    )


def _extract_validated_snapshot(
    *,
    archive: Path,
    metadata: dict[str, Any],
    staging: Path,
) -> tuple[
    set[str],
    dict[str, int],
]:
    (
        max_files,
        max_total_bytes,
        max_file_bytes,
    ) = _snapshot_limits(
        metadata
    )

    desired_dirs: set[str] = set()

    desired_files: dict[
        str,
        int,
    ] = {}

    seen: set[str] = set()

    file_count = 0
    total_bytes = 0
    member_count = 0

    with tarfile.open(
        archive,
        "r:gz",
    ) as tf:
        members = []

        for member in tf:
            member_count += 1

            if (
                member_count
                > MAX_ARCHIVE_MEMBERS
            ):
                raise ValueError(
                    "Checkpoint archive contains "
                    "too many members"
                )

            relative = (
                _validated_member_path(
                    member.name
                )
            )

            name = relative.as_posix()

            if name in seen:
                raise ValueError(
                    "Checkpoint archive contains "
                    f"duplicate member: {name}"
                )

            seen.add(
                name
            )

            if (
                member.issym()
                or member.islnk()
                or member.ischr()
                or member.isblk()
                or member.isfifo()
            ):
                raise ValueError(
                    "Checkpoint archive contains "
                    f"unsupported member type: {name}"
                )

            if member.isdir():
                desired_dirs.add(
                    name
                )

            elif member.isfile():
                if member.size < 0:
                    raise ValueError(
                        "Checkpoint archive contains "
                        f"invalid file size: {name}"
                    )

                if (
                    member.size
                    > max_file_bytes
                ):
                    raise ValueError(
                        "Checkpoint archive file exceeds "
                        f"restore limit: {name}"
                    )

                file_count += 1
                total_bytes += (
                    member.size
                )

                if (
                    file_count
                    > max_files
                ):
                    raise ValueError(
                        "Checkpoint archive exceeds "
                        "file-count restore limit"
                    )

                if (
                    total_bytes
                    > max_total_bytes
                ):
                    raise ValueError(
                        "Checkpoint archive exceeds "
                        "total-size restore limit"
                    )

                desired_files[
                    name
                ] = (
                    member.mode
                    & 0o777
                )

                for parent in (
                    relative.parents
                ):
                    if str(parent) == ".":
                        continue

                    desired_dirs.add(
                        parent.as_posix()
                    )

            else:
                raise ValueError(
                    "Checkpoint archive contains "
                    f"unsupported member type: {name}"
                )

            members.append(
                (
                    member,
                    relative,
                )
            )

        recorded_count = metadata.get(
            "file_count"
        )

        if (
            isinstance(
                recorded_count,
                int,
            )
            and recorded_count
            != file_count
        ):
            raise ValueError(
                "Checkpoint archive file-count "
                "metadata mismatch"
            )

        recorded_total = metadata.get(
            "total_bytes"
        )

        if (
            isinstance(
                recorded_total,
                int,
            )
            and recorded_total
            != total_bytes
        ):
            raise ValueError(
                "Checkpoint archive size "
                "metadata mismatch"
            )

        directory_modes: dict[
            str,
            int,
        ] = {}

        for (
            member,
            relative,
        ) in members:
            target = (
                staging /
                Path(
                    *relative.parts
                )
            )

            if member.isdir():
                target.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                directory_modes[
                    relative.as_posix()
                ] = (
                    member.mode
                    & 0o777
                )

                continue

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            source = (
                tf.extractfile(
                    member
                )
            )

            if source is None:
                raise ValueError(
                    "Checkpoint archive file "
                    f"could not be read: {member.name}"
                )

            written = 0

            with target.open(
                "wb"
            ) as output:
                while True:
                    chunk = source.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    written += len(
                        chunk
                    )

                    if (
                        written
                        > member.size
                    ):
                        raise ValueError(
                            "Checkpoint archive member "
                            f"expanded unexpectedly: "
                            f"{member.name}"
                        )

                    output.write(
                        chunk
                    )

            if written != member.size:
                raise ValueError(
                    "Checkpoint archive member "
                    f"was truncated: {member.name}"
                )

            try:
                target.chmod(
                    member.mode
                    & 0o777
                )
            except OSError:
                pass

        for name in sorted(
            directory_modes,
            key=lambda value:
            value.count("/"),
            reverse=True,
        ):
            target = (
                staging /
                Path(
                    *PurePosixPath(
                        name
                    ).parts
                )
            )

            try:
                target.chmod(
                    directory_modes[
                        name
                    ]
                )
            except OSError:
                pass

    return (
        desired_dirs,
        desired_files,
    )


def _scan_current_workspace(
    root: Path,
) -> tuple[
    dict[str, str],
    list[str],
]:
    entries: dict[
        str,
        str,
    ] = {}

    excluded: list[str] = []

    count = 0

    def visit(
        directory: Path,
        relative: PurePosixPath,
    ) -> None:
        nonlocal count

        with os.scandir(
            directory
        ) as iterator:
            children = sorted(
                iterator,
                key=lambda item:
                item.name,
            )

        for entry in children:
            rel = (
                relative /
                entry.name
            )

            rel_text = (
                rel.as_posix()
            )

            if _is_excluded_name(
                entry.name
            ):
                excluded.append(
                    rel_text
                )
                continue

            count += 1

            if (
                count
                > MAX_ARCHIVE_MEMBERS
            ):
                raise ValueError(
                    "Current workspace contains "
                    "too many rollback-visible entries"
                )

            if entry.is_symlink():
                entries[
                    rel_text
                ] = "symlink"
                continue

            if entry.is_dir(
                follow_symlinks=False
            ):
                entries[
                    rel_text
                ] = "dir"

                visit(
                    Path(
                        entry.path
                    ),
                    rel,
                )

                continue

            if entry.is_file(
                follow_symlinks=False
            ):
                entries[
                    rel_text
                ] = "file"
                continue

            raise ValueError(
                "Current workspace contains "
                "unsupported filesystem entry: "
                f"{rel_text}"
            )

    visit(
        root,
        PurePosixPath(),
    )

    return (
        entries,
        sorted(
            set(
                excluded
            )
        ),
    )


def _contains_excluded_descendant(
    directory: Path,
) -> bool:
    with os.scandir(
        directory
    ) as iterator:
        children = list(
            iterator
        )

    for entry in children:
        if _is_excluded_name(
            entry.name
        ):
            return True

        if entry.is_symlink():
            continue

        if entry.is_dir(
            follow_symlinks=False
        ):
            if _contains_excluded_descendant(
                Path(
                    entry.path
                )
            ):
                return True

    return False


def _atomic_copy(
    source: Path,
    target: Path,
    mode: int,
) -> None:
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = (
        target.parent /
        (
            ".awb-rollback-"
            + uuid.uuid4().hex
            + ".tmp"
        )
    )

    try:
        shutil.copyfile(
            source,
            tmp,
        )

        try:
            tmp.chmod(
                mode
                & 0o777
            )
        except OSError:
            pass

        os.replace(
            tmp,
            target,
        )

    finally:
        if (
            tmp.exists()
            or tmp.is_symlink()
        ):
            try:
                tmp.unlink()
            except OSError:
                pass


def restore_workspace_snapshot(
    *,
    metadata: dict[str, Any],
    workspace_root: str | None = None,
) -> dict[str, Any]:
    (
        checkpoint_id,
        archive,
    ) = _validated_archive(
        metadata
    )

    root = _validated_workspace(
        metadata,
        workspace_root,
    )

    checkpoint_dir = (
        archive.parent
    )

    with tempfile.TemporaryDirectory(
        prefix="rollback-staging-",
        dir=str(
            checkpoint_dir
        ),
    ) as staging_name:
        staging = Path(
            staging_name
        )

        (
            desired_dirs,
            desired_files,
        ) = _extract_validated_snapshot(
            archive=archive,
            metadata=metadata,
            staging=staging,
        )

        (
            current,
            excluded,
        ) = _scan_current_workspace(
            root
        )

        # Fail BEFORE mutation when replacing a current
        # directory with a snapshot file would destroy
        # excluded rollback-out-of-scope state.
        for relative in (
            desired_files
        ):
            if (
                current.get(
                    relative
                )
                != "dir"
            ):
                continue

            candidate = (
                root /
                Path(
                    *PurePosixPath(
                        relative
                    ).parts
                )
            )

            if _contains_excluded_descendant(
                candidate
            ):
                raise ValueError(
                    "Rollback cannot replace "
                    f"directory {relative!r} "
                    "because it contains excluded "
                    "out-of-scope state"
                )

        removed_entries = 0

        # Remove current files/symlinks that did not exist
        # as files in the checkpoint. Symlinks are unlinked,
        # never followed.
        for (
            relative,
            kind,
        ) in sorted(
            current.items(),
            key=lambda item:
            item[0].count("/"),
            reverse=True,
        ):
            if kind not in {
                "file",
                "symlink",
            }:
                continue

            target = (
                root /
                Path(
                    *PurePosixPath(
                        relative
                    ).parts
                )
            )

            if (
                relative
                in desired_files
                and kind == "file"
            ):
                continue

            target.unlink()
            removed_entries += 1

        # Remove rollback-visible directories that did not
        # exist in the checkpoint. Directories containing
        # excluded state remain as structural parents.
        for (
            relative,
            kind,
        ) in sorted(
            current.items(),
            key=lambda item:
            item[0].count("/"),
            reverse=True,
        ):
            if kind != "dir":
                continue

            if relative in desired_dirs:
                continue

            target = (
                root /
                Path(
                    *PurePosixPath(
                        relative
                    ).parts
                )
            )

            try:
                target.rmdir()
                removed_entries += 1
            except OSError:
                if _contains_excluded_descendant(
                    target
                ):
                    continue

                raise

        for relative in sorted(
            desired_dirs,
            key=lambda value:
            value.count("/"),
        ):
            target = (
                root /
                Path(
                    *PurePosixPath(
                        relative
                    ).parts
                )
            )

            if target.is_symlink():
                target.unlink()

            if target.exists():
                if not target.is_dir():
                    target.unlink()

            target.mkdir(
                parents=True,
                exist_ok=True,
            )

        restored_files = 0

        for (
            relative,
            mode,
        ) in sorted(
            desired_files.items()
        ):
            source = (
                staging /
                Path(
                    *PurePosixPath(
                        relative
                    ).parts
                )
            )

            target = (
                root /
                Path(
                    *PurePosixPath(
                        relative
                    ).parts
                )
            )

            if target.is_symlink():
                target.unlink()

            if (
                target.exists()
                and target.is_dir()
            ):
                try:
                    target.rmdir()
                except OSError as error:
                    raise ValueError(
                        "Rollback could not safely "
                        f"replace directory: {relative}"
                    ) from error

            _atomic_copy(
                source,
                target,
                mode,
            )

            restored_files += 1

        return {
            "version": RESTORE_VERSION,
            "checkpoint_id": checkpoint_id,
            "rollback_scope": (
                "workspace_files_only"
            ),
            "restored_files": (
                restored_files
            ),
            "removed_entries": (
                removed_entries
            ),
            "preserved_excluded_paths": (
                excluded
            ),
            "archive_sha256": str(
                metadata[
                    "archive_sha256"
                ]
            ),
            "external_side_effects_restored": (
                False
            ),
            "git_metadata_restored": (
                False
            ),
            "native_lifecycle_restored": (
                False
            ),
        }
