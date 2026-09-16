from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))

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


def test_runner_restores_project_state_even_when_command_times_out(tmp_path: Path):
    initialize_project_state(str(tmp_path), roadmap())
    roadmap_path = tmp_path / ".ai-workflow" / "ROADMAP.md"
    before = roadmap_path.read_bytes()

    command = 'printf "hacked" > .ai-workflow/ROADMAP.md; sleep 2'

    try:
        run_command(
            command,
            str(tmp_path),
            ".",
            0.1,
            10000,
        )
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("timed-out protected mutation should time out")

    assert roadmap_path.read_bytes() == before


def test_runner_removes_control_directory_created_by_project_command(tmp_path: Path):
    control = tmp_path / ".ai-workflow"
    assert not control.exists()

    try:
        run_command(
            "mkdir -p .ai-workflow",
            str(tmp_path),
            ".",
            10,
            10000,
        )
    except RuntimeError as error:
        assert "native-owned .ai-workflow" in str(error)
    else:
        raise AssertionError("project command should not be able to create the control directory")

    assert not control.exists()


def test_runner_refuses_preexisting_symlinked_control_directory(
    tmp_path: Path,
):
    outside = tmp_path / "outside-runner"
    outside.mkdir()
    marker = outside / "marker.txt"
    marker.write_text("KEEP")

    control = tmp_path / ".ai-workflow"
    control.symlink_to(outside, target_is_directory=True)

    try:
        run_command(
            "true",
            str(tmp_path),
            ".",
            10,
            10000,
        )
    except ValueError as error:
        assert "symbolic link" in str(error)
    else:
        raise AssertionError(
            "runner must reject a pre-existing control-directory symlink"
        )

    assert marker.read_text() == "KEEP"


def test_runner_unlinks_control_symlink_created_by_command(
    tmp_path: Path,
):
    import shlex

    outside = tmp_path / "outside-created-link"
    outside.mkdir()
    marker = outside / "marker.txt"
    marker.write_text("KEEP")

    target = shlex.quote(str(outside))

    try:
        run_command(
            f"ln -s {target} .ai-workflow",
            str(tmp_path),
            ".",
            10,
            10000,
        )
    except RuntimeError as error:
        assert "native-owned .ai-workflow" in str(error)
    else:
        raise AssertionError(
            "project command must not leave a control-directory symlink"
        )

    control = tmp_path / ".ai-workflow"
    assert not control.exists()
    assert not control.is_symlink()
    assert marker.read_text() == "KEEP"


def test_runner_restores_state_if_control_is_replaced_with_symlink(
    tmp_path: Path,
):
    import shlex

    initialize_project_state(str(tmp_path), roadmap())

    roadmap_path = tmp_path / ".ai-workflow" / "ROADMAP.md"
    before = roadmap_path.read_bytes()

    outside = tmp_path / "outside-replacement"
    outside.mkdir()
    marker = outside / "marker.txt"
    marker.write_text("KEEP")

    target = shlex.quote(str(outside))

    try:
        run_command(
            f"rm -rf .ai-workflow && ln -s {target} .ai-workflow",
            str(tmp_path),
            ".",
            10,
            10000,
        )
    except RuntimeError as error:
        assert "native-owned .ai-workflow" in str(error)
    else:
        raise AssertionError(
            "replacement control-directory symlink must be repaired"
        )

    control = tmp_path / ".ai-workflow"

    assert control.is_dir()
    assert not control.is_symlink()
    assert roadmap_path.read_bytes() == before
    assert marker.read_text() == "KEEP"
