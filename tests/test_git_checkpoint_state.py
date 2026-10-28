from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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


from runner import (
    compare_git_snapshots,
    git_snapshot,
)


def git(
    repo: Path,
    *args: str,
) -> str:
    proc = subprocess.run(
        [
            "git",
            *args,
        ],
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=True,
    )

    return proc.stdout.strip()


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


def test_non_git_workspace_has_explicit_non_restorable_state(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir()

    snapshot = git_snapshot(
        str(workspace)
    )

    assert snapshot == {
        "version": 2,
        "is_git": False,
        "git_metadata_restorable": False,
    }


def test_git_snapshot_distinguishes_dirty_state_classes(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    (
        repo /
        "staged.txt"
    ).write_text(
        "staged\n",
        encoding="utf-8",
    )

    git(
        repo,
        "add",
        "staged.txt",
    )

    (
        repo /
        "tracked.txt"
    ).write_text(
        "unstaged\n",
        encoding="utf-8",
    )

    (
        repo /
        "untracked.txt"
    ).write_text(
        "untracked\n",
        encoding="utf-8",
    )

    snapshot = git_snapshot(
        str(repo)
    )

    assert snapshot[
        "version"
    ] == 2

    assert snapshot[
        "is_git"
    ] is True

    assert snapshot[
        "dirty"
    ] is True

    assert snapshot[
        "has_staged_changes"
    ] is True

    assert snapshot[
        "has_unstaged_changes"
    ] is True

    assert snapshot[
        "has_untracked_files"
    ] is True

    assert snapshot[
        "has_conflicts"
    ] is False

    assert snapshot[
        "git_metadata_restorable"
    ] is False

    for key in [
        "status_digest",
        "index_digest",
        "worktree_digest",
    ]:
        assert len(
            snapshot[key]
        ) == 64


def test_git_snapshot_does_not_modify_repository_state(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    (
        repo /
        "tracked.txt"
    ).write_text(
        "dirty\n",
        encoding="utf-8",
    )

    before_status = git(
        repo,
        "status",
        "--porcelain=v1",
    )

    before_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    first = git_snapshot(
        str(repo)
    )

    second = git_snapshot(
        str(repo)
    )

    after_status = git(
        repo,
        "status",
        "--porcelain=v1",
    )

    after_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    assert first == second
    assert before_status == after_status
    assert before_head == after_head


def test_git_comparison_detects_index_only_transition(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    (
        repo /
        "tracked.txt"
    ).write_text(
        "dirty\n",
        encoding="utf-8",
    )

    before = git_snapshot(
        str(repo)
    )

    git(
        repo,
        "add",
        "tracked.txt",
    )

    after = git_snapshot(
        str(repo)
    )

    comparison = (
        compare_git_snapshots(
            before,
            after,
        )
    )

    assert comparison[
        "head_changed"
    ] is False

    assert comparison[
        "branch_changed"
    ] is False

    assert comparison[
        "index_changed"
    ] is True

    assert comparison[
        "git_metadata_changed"
    ] is True

    assert comparison[
        "requires_git_review"
    ] is True

    assert comparison[
        "git_metadata_restored"
    ] is False


def test_identical_git_snapshots_require_no_git_review(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    before = git_snapshot(
        str(repo)
    )

    after = git_snapshot(
        str(repo)
    )

    comparison = (
        compare_git_snapshots(
            before,
            after,
        )
    )

    assert comparison[
        "head_changed"
    ] is False

    assert comparison[
        "branch_changed"
    ] is False

    assert comparison[
        "index_changed"
    ] is False

    assert comparison[
        "worktree_status_changed"
    ] is False

    assert comparison[
        "git_metadata_changed"
    ] is False

    assert comparison[
        "requires_git_review"
    ] is False
