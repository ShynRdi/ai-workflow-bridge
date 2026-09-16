from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_phase_stage_are_not_present_in_extension_frontend():
    html = (EXT / "sidepanel.html").read_text()
    sidepanel = (EXT / "sidepanel.js").read_text()
    assert 'id="phase"' not in html
    assert 'id="stage"' not in html
    assert '$("phase")' not in sidepanel
    assert '$("stage")' not in sidepanel
    assert 'id="roadmapCurrent"' in html
    assert 'id="roadmapNext"' in html
    assert 'id="roadmapProgress"' in html
    assert '<script src="project-state-ui.js"></script>' in html


def test_project_state_ui_reads_native_state_only():
    script = (EXT / "project-state-ui.js").read_text()
    assert 'event.kind === "state"' in script
    assert 'event.state?.project_state' in script
    assert "roadmapCurrent" in script
    assert "roadmapNext" in script
    assert "roadmapProgress" in script


def test_native_orchestrator_owns_phase_stage_and_roadmap():
    orchestrator = (ROOT / "native_host" / "orchestrator.py").read_text()
    project_state = (ROOT / "native_host" / "orchestrator_project_state.py").read_text()
    assert 'for key in ("phase", "stage", "roadmap")' in orchestrator
    assert ".ai-workflow lifecycle documents are native-host owned" in project_state
    assert "advance_project_state" in project_state
