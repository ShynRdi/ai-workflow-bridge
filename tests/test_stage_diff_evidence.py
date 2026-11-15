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

from git_evidence import (
    git_changed_file_evidence,
)

from project_state import (
    advance_project_state,
    apply_course_change,
    initialize_project_state,
    load_project_state,
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
        "Stage Evidence Test",
    )

    git(
        repo,
        "config",
        "user.email",
        "stage@example.invalid",
    )

    (
        repo /
        "keep.txt"
    ).write_text(
        "base\n",
        encoding="utf-8",
    )

    (
        repo /
        "delete.txt"
    ).write_text(
        "delete\n",
        encoding="utf-8",
    )

    git(
        repo,
        "add",
        "keep.txt",
        "delete.txt",
    )

    git(
        repo,
        "commit",
        "-q",
        "-m",
        "initial",
    )


def roadmap():
    return [
        {
            "id": "P0",
            "title": "Build",
            "stages": [
                "ONE",
                "TWO",
            ],
        }
    ]


def test_initial_stage_baseline_is_persisted(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    summary = initialize_project_state(
        str(repo),
        roadmap(),
    )

    baseline = summary[
        "stage_baseline"
    ]

    assert baseline[
        "phase"
    ] == "P0"

    assert baseline[
        "stage"
    ] == "ONE"

    assert baseline[
        "git"
    ][
        "is_git"
    ] is True

    assert baseline[
        "git"
    ][
        "dirty"
    ] is False

    assert baseline[
        "git"
    ][
        "head_oid"
    ] == git(
        repo,
        "rev-parse",
        "HEAD",
    )


def test_changed_file_evidence_is_structured_and_read_only(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    initialize_project_state(
        str(repo),
        roadmap(),
    )

    baseline = load_project_state(
        str(repo)
    )[
        "stage_baseline"
    ]

    (
        repo /
        "keep.txt"
    ).write_text(
        "changed\n",
        encoding="utf-8",
    )

    (
        repo /
        "delete.txt"
    ).unlink()

    (
        repo /
        "new.txt"
    ).write_text(
        "new\n",
        encoding="utf-8",
    )

    before_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    before_status = git(
        repo,
        "status",
        "--porcelain=v1",
    )

    evidence = git_changed_file_evidence(
        str(repo),
        baseline,
    )

    after_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    after_status = git(
        repo,
        "status",
        "--porcelain=v1",
    )

    assert before_head == after_head
    assert before_status == after_status

    assert evidence[
        "available"
    ] is True

    assert evidence[
        "attribution_exact"
    ] is True

    assert evidence[
        "baseline_is_ancestor"
    ] is True

    by_path = {
        item["path"]: item["status"]
        for item in evidence[
            "files"
        ]
    }

    assert by_path[
        "keep.txt"
    ] == "M"

    assert by_path[
        "delete.txt"
    ] == "D"

    assert by_path[
        "new.txt"
    ] == "?"

    assert not any(
        path.startswith(
            ".ai-workflow"
        )
        for path in by_path
    )

    assert evidence[
        "counts"
    ][
        "modified"
    ] == 1

    assert evidence[
        "counts"
    ][
        "deleted"
    ] == 1

    assert evidence[
        "counts"
    ][
        "untracked"
    ] == 1


def test_committed_rename_is_reported_from_stage_baseline(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    initialize_project_state(
        str(repo),
        roadmap(),
    )

    baseline = load_project_state(
        str(repo)
    )[
        "stage_baseline"
    ]

    git(
        repo,
        "mv",
        "keep.txt",
        "renamed.txt",
    )

    git(
        repo,
        "commit",
        "-q",
        "-m",
        "rename file",
    )

    evidence = git_changed_file_evidence(
        str(repo),
        baseline,
    )

    rename = next(
        item
        for item in evidence[
            "files"
        ]
        if item[
            "status"
        ] == "R"
    )

    assert rename[
        "previous_path"
    ] == "keep.txt"

    assert rename[
        "path"
    ] == "renamed.txt"

    assert evidence[
        "counts"
    ][
        "renamed"
    ] == 1

    assert evidence[
        "head_changed"
    ] is True

    assert evidence[
        "baseline_is_ancestor"
    ] is True

    assert evidence[
        "attribution_exact"
    ] is True


def test_dirty_stage_baseline_is_conservative(
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
        "keep.txt"
    ).write_text(
        "already dirty\n",
        encoding="utf-8",
    )

    initialize_project_state(
        str(repo),
        roadmap(),
    )

    baseline = load_project_state(
        str(repo)
    )[
        "stage_baseline"
    ]

    evidence = git_changed_file_evidence(
        str(repo),
        baseline,
    )

    assert evidence[
        "available"
    ] is True

    assert evidence[
        "baseline_dirty"
    ] is True

    assert evidence[
        "attribution_exact"
    ] is False

    assert (
        "already dirty"
        in evidence[
            "note"
        ]
    )


def test_advance_refreshes_stage_baseline(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    initialize_project_state(
        str(repo),
        roadmap(),
    )

    first = load_project_state(
        str(repo)
    )[
        "stage_baseline"
    ]

    (
        repo /
        "stage-one.txt"
    ).write_text(
        "done\n",
        encoding="utf-8",
    )

    git(
        repo,
        "add",
        "stage-one.txt",
    )

    git(
        repo,
        "commit",
        "-q",
        "-m",
        "finish stage one",
    )

    new_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    summary = advance_project_state(
        str(repo),
        "P0",
        "TWO",
    )

    second = summary[
        "stage_baseline"
    ]

    assert second[
        "phase"
    ] == "P0"

    assert second[
        "stage"
    ] == "TWO"

    assert second[
        "git"
    ][
        "head_oid"
    ] == new_head

    assert (
        first[
            "git"
        ][
            "head_oid"
        ]
        != second[
            "git"
        ][
            "head_oid"
        ]
    )


def test_non_git_stage_evidence_is_explicitly_unavailable(
    tmp_path: Path,
):
    workspace = (
        tmp_path /
        "workspace"
    )

    workspace.mkdir()

    initialize_project_state(
        str(workspace),
        roadmap(),
    )

    baseline = load_project_state(
        str(workspace)
    )[
        "stage_baseline"
    ]

    evidence = git_changed_file_evidence(
        str(workspace),
        baseline,
    )

    assert evidence[
        "available"
    ] is False

    assert evidence[
        "attribution_exact"
    ] is False

    assert evidence[
        "files"
    ] == []


def test_course_change_refreshes_stage_baseline(
    tmp_path: Path,
):
    repo = (
        tmp_path /
        "repo"
    )

    init_repo(
        repo
    )

    initialize_project_state(
        str(repo),
        roadmap(),
    )

    first = load_project_state(
        str(repo)
    )[
        "stage_baseline"
    ]

    (
        repo /
        "course-change.txt"
    ).write_text(
        "new approved direction\n",
        encoding="utf-8",
    )

    git(
        repo,
        "add",
        "course-change.txt",
    )

    git(
        repo,
        "commit",
        "-q",
        "-m",
        "prepare course change",
    )

    new_head = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    summary = apply_course_change(
        str(repo),
        roadmap(),
        proposed_phase="P0",
        proposed_stage="ONE",
        summary="approved scope refinement",
    )

    second = summary[
        "stage_baseline"
    ]

    assert second[
        "phase"
    ] == "P0"

    assert second[
        "stage"
    ] == "ONE"

    assert second[
        "git"
    ][
        "head_oid"
    ] == new_head

    assert second[
        "git"
    ][
        "dirty"
    ] is False

    assert (
        second[
            "git"
        ][
            "head_oid"
        ]
        != first[
            "git"
        ][
            "head_oid"
        ]
    )
