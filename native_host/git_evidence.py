from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from redaction import redact_text
from runner import (
    git_snapshot,
    sanitized_environment,
)


MAX_CHANGED_FILES = 500
CONTROL_DIR_NAME = ".ai-workflow"


def _git_run(
    root: Path,
    *args: str,
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            [
                "git",
                *args,
            ],
            cwd=str(root),
            text=False,
            capture_output=True,
            timeout=20,
            env=sanitized_environment(),
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None


def _git_bytes(
    root: Path,
    *args: str,
) -> bytes | None:
    proc = _git_run(
        root,
        *args,
    )

    if (
        proc is None
        or proc.returncode != 0
    ):
        return None

    return bytes(
        proc.stdout
    )


def _decode_z(
    value: bytes,
) -> list[str]:
    return [
        redact_text(
            item.decode(
                "utf-8",
                errors="replace",
            )
        )
        for item in value.split(
            b"\0"
        )
        if item
    ]


def _allowed_path(
    path: str,
) -> bool:
    normalized = (
        str(path)
        .replace(
            "\\",
            "/",
        )
    )

    while normalized.startswith("./"):
        normalized = normalized[2:]

    return not (
        normalized == CONTROL_DIR_NAME
        or normalized.startswith(
            f"{CONTROL_DIR_NAME}/"
        )
    )


def _baseline_git(
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    value = (
        baseline
        if isinstance(
            baseline,
            dict,
        )
        else {}
    )

    nested = value.get(
        "git"
    )

    if isinstance(
        nested,
        dict,
    ):
        return nested

    return value


def _stage_git_snapshot(
    workspace_root: str,
) -> dict[str, Any]:
    snapshot = dict(
        git_snapshot(
            workspace_root
        )
    )

    if not bool(
        snapshot.get("is_git")
    ):
        return snapshot

    root = (
        Path(workspace_root)
        .expanduser()
        .resolve()
    )

    pathspec = (
        ".",
        ":(exclude).ai-workflow",
        ":(exclude).ai-workflow/**",
    )

    status_raw = _git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        *pathspec,
    )

    index_raw = _git_bytes(
        root,
        "diff",
        "--cached",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-ext-diff",
        "--",
        *pathspec,
    )

    worktree_raw = _git_bytes(
        root,
        "diff",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-ext-diff",
        "--",
        *pathspec,
    )

    untracked_raw = _git_bytes(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        *pathspec,
    )

    conflicts_raw = _git_bytes(
        root,
        "diff",
        "--name-only",
        "--diff-filter=U",
        "-z",
        "--",
        *pathspec,
    )

    def present(
        value: bytes | None,
    ) -> bool | None:
        if value is None:
            return None

        return bool(value)

    def digest(
        value: bytes | None,
    ) -> str:
        if value is None:
            return ""

        return hashlib.sha256(
            value
        ).hexdigest()

    snapshot.update({
        "dirty": present(
            status_raw
        ),
        "has_staged_changes": present(
            index_raw
        ),
        "has_unstaged_changes": present(
            worktree_raw
        ),
        "has_untracked_files": present(
            untracked_raw
        ),
        "has_conflicts": present(
            conflicts_raw
        ),
        "status_digest": digest(
            status_raw
        ),
        "index_digest": digest(
            index_raw
        ),
        "worktree_digest": digest(
            worktree_raw
        ),
    })

    return snapshot


def capture_stage_baseline(
    workspace_root: str,
    phase: str,
    stage: str,
    captured_at: str,
) -> dict[str, Any]:
    try:
        snapshot = _stage_git_snapshot(
            workspace_root
        )
    except Exception as error:
        return {
            "version": 1,
            "phase": str(
                phase
            ),
            "stage": str(
                stage
            ),
            "captured_at": str(
                captured_at
            ),
            "git": {
                "is_git": False,
                "inspection_error": str(
                    error
                )[:300],
            },
        }

    return {
        "version": 1,
        "phase": str(
            phase
        ),
        "stage": str(
            stage
        ),
        "captured_at": str(
            captured_at
        ),
        "git": {
            "is_git": bool(
                snapshot.get(
                    "is_git"
                )
            ),
            "head_oid": str(
                snapshot.get(
                    "head_oid"
                )
                or snapshot.get(
                    "head"
                )
                or ""
            ),
            "branch": str(
                snapshot.get(
                    "branch"
                )
                or ""
            ),
            "detached": bool(
                snapshot.get(
                    "detached"
                )
            ),
            "dirty": snapshot.get(
                "dirty"
            ),
            "has_staged_changes": snapshot.get(
                "has_staged_changes"
            ),
            "has_unstaged_changes": snapshot.get(
                "has_unstaged_changes"
            ),
            "has_untracked_files": snapshot.get(
                "has_untracked_files"
            ),
            "has_conflicts": snapshot.get(
                "has_conflicts"
            ),
            "status_digest": str(
                snapshot.get(
                    "status_digest"
                )
                or ""
            ),
            "index_digest": str(
                snapshot.get(
                    "index_digest"
                )
                or ""
            ),
            "worktree_digest": str(
                snapshot.get(
                    "worktree_digest"
                )
                or ""
            ),
        },
    }


def public_stage_baseline(
    baseline: Any,
    expected_phase: str = "",
    expected_stage: str = "",
) -> dict[str, Any] | None:
    if not isinstance(
        baseline,
        dict,
    ):
        return None

    phase = str(
        baseline.get(
            "phase"
        )
        or ""
    )

    stage = str(
        baseline.get(
            "stage"
        )
        or ""
    )

    if (
        expected_phase
        and phase != expected_phase
    ):
        return None

    if (
        expected_stage
        and stage != expected_stage
    ):
        return None

    git = _baseline_git(
        baseline
    )

    return {
        "version": int(
            baseline.get(
                "version"
            )
            or 1
        ),
        "phase": phase,
        "stage": stage,
        "captured_at": str(
            baseline.get(
                "captured_at"
            )
            or ""
        ),
        "git": {
            "is_git": bool(
                git.get(
                    "is_git"
                )
            ),
            "head_oid": str(
                git.get(
                    "head_oid"
                )
                or ""
            ),
            "branch": str(
                git.get(
                    "branch"
                )
                or ""
            ),
            "detached": bool(
                git.get(
                    "detached"
                )
            ),
            "dirty": git.get(
                "dirty"
            ),
            "has_staged_changes": git.get(
                "has_staged_changes"
            ),
            "has_unstaged_changes": git.get(
                "has_unstaged_changes"
            ),
            "has_untracked_files": git.get(
                "has_untracked_files"
            ),
            "has_conflicts": git.get(
                "has_conflicts"
            ),
            "status_digest": str(
                git.get(
                    "status_digest"
                )
                or ""
            ),
            "index_digest": str(
                git.get(
                    "index_digest"
                )
                or ""
            ),
            "worktree_digest": str(
                git.get(
                    "worktree_digest"
                )
                or ""
            ),
            "inspection_error": str(
                git.get(
                    "inspection_error"
                )
                or ""
            ),
        },
    }


def _ancestor_state(
    root: Path,
    baseline_head: str,
    current_head: str,
) -> bool | None:
    if (
        not baseline_head
        or not current_head
    ):
        return None

    proc = _git_run(
        root,
        "merge-base",
        "--is-ancestor",
        baseline_head,
        current_head,
    )

    if proc is None:
        return None

    if proc.returncode == 0:
        return True

    if proc.returncode == 1:
        return False

    return None


def git_changed_file_evidence(
    workspace_root: str,
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    root = (
        Path(
            workspace_root
        )
        .expanduser()
        .resolve()
    )

    baseline_value = (
        baseline
        if isinstance(
            baseline,
            dict,
        )
        else {}
    )

    baseline_git = _baseline_git(
        baseline_value
    )

    if not bool(
        baseline_git.get(
            "is_git"
        )
    ):
        return {
            "version": 1,
            "available": False,
            "reason": (
                "stage baseline is not a Git repository"
            ),
            "attribution_exact": False,
            "files": [],
        }

    baseline_head = str(
        baseline_git.get(
            "head_oid"
        )
        or ""
    ).strip()

    if not baseline_head:
        return {
            "version": 1,
            "available": False,
            "reason": (
                "stage baseline has no HEAD commit"
            ),
            "attribution_exact": False,
            "files": [],
        }

    current = _stage_git_snapshot(
        str(root)
    )

    if not bool(
        current.get(
            "is_git"
        )
    ):
        return {
            "version": 1,
            "available": False,
            "reason": (
                "current workspace is not a Git repository"
            ),
            "attribution_exact": False,
            "files": [],
        }

    current_head = str(
        current.get(
            "head_oid"
        )
        or current.get(
            "head"
        )
        or ""
    ).strip()

    changed_raw = _git_bytes(
        root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        baseline_head,
        "--",
    )

    untracked_raw = _git_bytes(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )

    if (
        changed_raw is None
        or untracked_raw is None
    ):
        return {
            "version": 1,
            "available": False,
            "reason": (
                "Git changed-file inspection failed"
            ),
            "attribution_exact": False,
            "files": [],
        }

    tokens = _decode_z(
        changed_raw
    )

    files: list[
        dict[str, Any]
    ] = []

    index = 0

    while index < len(tokens):
        raw_status = tokens[
            index
        ]

        index += 1

        if not raw_status:
            continue

        status = raw_status[0]

        if status in {
            "R",
            "C",
        }:
            if (
                index + 1
                >= len(tokens)
            ):
                break

            previous_path = tokens[
                index
            ]

            path = tokens[
                index + 1
            ]

            index += 2

            if not (
                _allowed_path(
                    previous_path
                )
                or _allowed_path(
                    path
                )
            ):
                continue

            files.append({
                "status": status,
                "path": path,
                "previous_path": previous_path,
                "score": raw_status[1:],
            })

            continue

        if index >= len(tokens):
            break

        path = tokens[
            index
        ]

        index += 1

        if not _allowed_path(
            path
        ):
            continue

        files.append({
            "status": status,
            "path": path,
        })

    known_paths = {
        str(
            item.get(
                "path"
            )
            or ""
        )
        for item in files
    }

    for path in _decode_z(
        untracked_raw
    ):
        if (
            not _allowed_path(
                path
            )
            or path in known_paths
        ):
            continue

        files.append({
            "status": "?",
            "path": path,
        })

    order = {
        "A": 0,
        "M": 1,
        "D": 2,
        "R": 3,
        "C": 4,
        "T": 5,
        "U": 6,
        "?": 7,
    }

    files.sort(
        key=lambda item: (
            order.get(
                str(
                    item.get(
                        "status"
                    )
                    or ""
                ),
                99,
            ),
            str(
                item.get(
                    "path"
                )
                or ""
            ),
        )
    )

    counts = {
        "added": 0,
        "modified": 0,
        "deleted": 0,
        "renamed": 0,
        "copied": 0,
        "type_changed": 0,
        "unmerged": 0,
        "untracked": 0,
        "other": 0,
    }

    mapping = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type_changed",
        "U": "unmerged",
        "?": "untracked",
    }

    for item in files:
        key = mapping.get(
            str(
                item.get(
                    "status"
                )
                or ""
            ),
            "other",
        )

        counts[
            key
        ] += 1

    total_files = len(
        files
    )

    truncated = (
        total_files
        > MAX_CHANGED_FILES
    )

    visible_files = files[
        :MAX_CHANGED_FILES
    ]

    baseline_branch = str(
        baseline_git.get(
            "branch"
        )
        or ""
    )

    current_branch = str(
        current.get(
            "branch"
        )
        or ""
    )

    branch_changed = (
        baseline_branch
        != current_branch
    )

    ancestor = _ancestor_state(
        root,
        baseline_head,
        current_head,
    )

    baseline_dirty = (
        baseline_git.get(
            "dirty"
        )
    )

    attribution_exact = (
        baseline_dirty is False
        and not branch_changed
        and ancestor is True
    )

    notes: list[str] = []

    if baseline_dirty is not False:
        notes.append(
            "repository was already dirty when the stage started"
        )

    if branch_changed:
        notes.append(
            "Git branch changed after the stage baseline"
        )

    if ancestor is False:
        notes.append(
            "current HEAD is not descended from the stage baseline HEAD"
        )
    elif ancestor is None:
        notes.append(
            "Git ancestry could not be verified"
        )

    if truncated:
        notes.append(
            "changed-file list was truncated"
        )

    return {
        "version": 1,
        "available": True,
        "phase": str(
            baseline_value.get(
                "phase"
            )
            or ""
        ),
        "stage": str(
            baseline_value.get(
                "stage"
            )
            or ""
        ),
        "attribution_exact": attribution_exact,
        "baseline_dirty": baseline_dirty,
        "current_dirty": current.get(
            "dirty"
        ),
        "baseline_head": baseline_head,
        "current_head": current_head,
        "baseline_branch": baseline_branch,
        "current_branch": current_branch,
        "head_changed": (
            baseline_head
            != current_head
        ),
        "branch_changed": branch_changed,
        "baseline_is_ancestor": ancestor,
        "baseline_status_digest": str(
            baseline_git.get(
                "status_digest"
            )
            or ""
        ),
        "current_status_digest": str(
            current.get(
                "status_digest"
            )
            or ""
        ),
        "counts": counts,
        "total_files": total_files,
        "truncated": truncated,
        "files": visible_files,
        "note": "; ".join(
            notes
        ),
    }
