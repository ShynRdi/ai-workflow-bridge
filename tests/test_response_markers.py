import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))
from orchestrator_response import PROJECT_DONE_MARKER, STAGE_STOP_MARKER, has_exact_trailing_marker


def test_completion_markers_must_be_trailing():
    assert has_exact_trailing_marker("summary\n" + PROJECT_DONE_MARKER, PROJECT_DONE_MARKER)
    assert not has_exact_trailing_marker(PROJECT_DONE_MARKER + "\nextra", PROJECT_DONE_MARKER)
    assert has_exact_trailing_marker("summary\n" + STAGE_STOP_MARKER + "\n", STAGE_STOP_MARKER)
    assert not has_exact_trailing_marker(STAGE_STOP_MARKER + " trailing text", STAGE_STOP_MARKER)
