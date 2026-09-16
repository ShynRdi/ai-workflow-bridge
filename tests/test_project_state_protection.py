from pathlib import Path

from project_state import initialize_project_state
from runner import run_command


def roadmap():
    return [{"id": "P0", "title": "Foundation", "stages": ["BOOT", "TEST"]}]


def test_runner_restores_native_owned_project_state_after_mutation(tmp_path: Path):
    initialize_project_state(str(tmp_path), roadmap())
    roadmap_path = tmp_path / ".ai-workflow" / "ROADMAP.md"
    before = roadmap_path.read_bytes()

    try:
        run_command(
            "printf hacked > .ai-workflow/ROADMAP.md",
            str(tmp_path),
            ".",
            10,
            10000,
        )
    except RuntimeError as error:
        assert "native-owned .ai-workflow" in str(error)
    else:
        raise AssertionError("protected lifecycle mutation should fail")

    assert roadmap_path.read_bytes() == before


def test_runner_allows_read_only_project_state_inspection(tmp_path: Path):
    initialize_project_state(str(tmp_path), roadmap())
    result = run_command(
        "cat .ai-workflow/ROADMAP.md",
        str(tmp_path),
        ".",
        10,
        10000,
    )
    assert result.exit_code == 0
    assert "AI Workflow Roadmap" in result.stdout
