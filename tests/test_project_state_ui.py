import json
import subprocess
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


def test_stage_review_ui_uses_native_review_identity():
    html = (EXT / "sidepanel.html").read_text()
    panel = (EXT / "sidepanel.js").read_text()
    background = (EXT / "background.js").read_text()

    assert 'id="acceptStageReview"' in html
    assert 'id="rejectStageReview"' in html
    assert "stage_review" in panel
    assert "review_id" in panel
    assert 'command("stage_review_decision"' in panel
    assert 'type: "stage_review_decision"' in background


def test_stage_review_action_keeps_rendered_identity_after_state_replacement():
    identity = EXT / "stage-review-identity.js"
    source = identity.read_text(encoding="utf-8")
    node = f"""
const vm = require("vm");
const context = {{}};
context.globalThis = context;
vm.runInNewContext({json.dumps(source)}, context);
const button = {{ dataset: {{}} }};
context.AWB_STAGE_REVIEW_IDENTITY.bindActionIdentity(button, {{
  review_id: "review-A", phase: "P0", stage: "ONE",
}});
// An unrelated state update has selected a newer Review B, but this button
// remains the UI control rendered for Review A until it is re-rendered.
const lastState = {{ project_state: {{ stage_review: {{
  review_id: "review-B", phase: "P0", stage: "ONE",
}} }} }};
console.log(JSON.stringify({{
  lastStateReview: lastState.project_state.stage_review.review_id,
  sent: context.AWB_STAGE_REVIEW_IDENTITY.actionPayload(button, "accept"),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", node],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)

    assert result["lastStateReview"] == "review-B"
    assert result["sent"] == {
        "review_id": "review-A",
        "phase": "P0",
        "stage": "ONE",
        "decision": "accept",
    }

    panel = (EXT / "sidepanel.js").read_text(encoding="utf-8")
    handlers = panel[
        panel.index('for (const [id, decision] of [["acceptStageReview"'):
        panel.index('$("prepareRecovery")', panel.index('for (const [id, decision] of [["acceptStageReview"'))
    ]
    assert "lastState?.project_state?.stage_review" not in handlers
    assert "actionPayload(event.currentTarget, decision)" in handlers
