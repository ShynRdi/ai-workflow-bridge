from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))

from project_state import (
    advance_project_state,
    complete_project_state,
    initialize_project_state,
    load_project_state,
    project_state_summary,
)


def sample_roadmap():
    return [
        {"id": "P0", "title": "Foundation", "stages": ["BOOT", "CONFIG"]},
        {"id": "P1", "title": "Build", "stages": ["API", "TEST"]},
    ]


def test_project_state_creates_local_docs_and_tracks_next(tmp_path: Path):
    summary = initialize_project_state(str(tmp_path), sample_roadmap())
    assert summary["exists"] is True
    assert summary["current"]["label"] == "P0 / BOOT"
    assert summary["next"]["label"] == "P0 / CONFIG"
    assert summary["completed"] == 0
    assert (tmp_path / ".ai-workflow" / "ROADMAP.md").is_file()
    assert (tmp_path / ".ai-workflow" / "HISTORY.md").is_file()


def test_advance_is_immediate_and_persists_history(tmp_path: Path):
    initialize_project_state(str(tmp_path), sample_roadmap())
    summary = advance_project_state(str(tmp_path), "P0", "CONFIG")
    assert summary["current"]["label"] == "P0 / CONFIG"
    assert summary["next"]["label"] == "P1 / API"
    assert summary["completed"] == 1
    history = (tmp_path / ".ai-workflow" / "HISTORY.md").read_text()
    assert "Completed `P0 / BOOT`" in history
    assert "Started `P0 / CONFIG`" in history


def test_advance_rejects_skipping_stages(tmp_path: Path):
    initialize_project_state(str(tmp_path), sample_roadmap())
    try:
        advance_project_state(str(tmp_path), "P1", "API")
    except ValueError as error:
        assert "immediate next" in str(error)
    else:
        raise AssertionError("stage skip should be rejected")


def test_complete_marks_current_completed_and_clears_current(tmp_path: Path):
    initialize_project_state(str(tmp_path), sample_roadmap())
    summary = complete_project_state(str(tmp_path))
    assert summary["status"] == "complete"
    assert summary["current"] is None
    assert summary["completed"] == 1
    state = load_project_state(str(tmp_path))
    assert state["status"] == "complete"


def test_roadmap_markdown_contains_machine_state(tmp_path: Path):
    initialize_project_state(str(tmp_path), sample_roadmap())
    text = (tmp_path / ".ai-workflow" / "ROADMAP.md").read_text()
    assert "# AI Workflow Roadmap" in text
    assert "AI_WORKFLOW_STATE_BEGIN" in text
    assert "AI_WORKFLOW_STATE_END" in text
    assert "P0 / BOOT" in text
