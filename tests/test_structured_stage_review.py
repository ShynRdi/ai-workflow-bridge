from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"
sys.path.insert(0, str(HOST))

from project_state import (
    advance_project_state,
    collect_stage_review,
    initialize_project_state,
    load_project_state,
    project_state_summary,
    resolve_stage_review,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, check=True,
        capture_output=True,
    ).stdout.strip()


def repo_with_stage(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Review Test")
    git(repo, "config", "user.email", "review@example.invalid")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "app.txt")
    git(repo, "commit", "-qm", "base")
    initialize_project_state(str(repo), [{
        "id": "P0", "title": "Build", "stages": ["ONE", "TWO"],
        "acceptance_criteria": {"ONE": ["Application evidence is reviewed"]},
    }])
    return repo


def test_review_persists_exact_identity_and_accept_flow(tmp_path: Path):
    repo = repo_with_stage(tmp_path)
    (repo / "app.txt").write_text("changed\n", encoding="utf-8")
    review = collect_stage_review(str(repo))

    assert review["status"] == "review_required"
    assert review["phase"] == "P0"
    assert review["stage"] == "ONE"
    assert review["changed_file_count"] == 1
    assert review["criterion_assessments"][0]["status"] == "unassessed"
    assert review["changed_file_evidence"]["files"][0]["path"] == "app.txt"

    with pytest.raises(ValueError, match="identity"):
        resolve_stage_review(str(repo), "wrong-id", "accept")

    accepted = resolve_stage_review(str(repo), review["review_id"], "accept")
    assert accepted["status"] == "accepted"
    advanced = advance_project_state(str(repo), "P0", "TWO")
    assert advanced["current"]["stage"] == "TWO"
    assert advanced["stage_review"] is None


def test_stale_review_cannot_accept_after_git_change(tmp_path: Path):
    repo = repo_with_stage(tmp_path)
    review = collect_stage_review(str(repo))
    (repo / "later.txt").write_text("later\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        resolve_stage_review(str(repo), review["review_id"], "accept")

    summary = project_state_summary(str(repo))
    assert summary["stage_review"]["status"] == "stale"
    assert load_project_state(str(repo))["stage_review"]["status"] == "stale"


def test_rejected_review_blocks_transition_and_control_files_are_excluded(tmp_path: Path):
    repo = repo_with_stage(tmp_path)
    review = collect_stage_review(str(repo))
    assert review["changed_file_count"] == 0
    (repo / ".ai-workflow" / "private-note.txt").write_text("native only\n", encoding="utf-8")
    # Native control files are intentionally excluded from product evidence.
    refreshed = project_state_summary(str(repo))["stage_review"]
    assert refreshed["status"] == "review_required"
    assert refreshed["changed_file_count"] == 0
    rejected = resolve_stage_review(str(repo), review["review_id"], "reject")
    assert rejected["status"] == "rejected"
    with pytest.raises(ValueError, match="structured review"):
        advance_project_state(str(repo), "P0", "TWO")

