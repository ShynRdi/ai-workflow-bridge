from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_diagnostics_panel_is_wired_to_read_only_command():
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    panel = (EXT / "sidepanel.js").read_text(encoding="utf-8")

    assert 'id="runDiagnostics"' in html
    assert 'id="diagnosticsOverall"' in html
    assert 'id="diagnosticsList"' in html

    assert 'command("diagnostics")' in panel
    assert "runSystemDiagnostics" in panel
    assert "renderDiagnostics" in panel


def test_project_progress_bar_is_backed_by_roadmap_counts():
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    ui = (EXT / "project-state-ui.js").read_text(encoding="utf-8")

    assert 'id="roadmapProgressBar"' in html
    assert 'id="roadmapProgressFill"' in html
    assert 'id="roadmapProgressPercent"' in html
    assert 'id="roadmapRemaining"' in html

    assert "projectState.completed" in ui
    assert "projectState.total" in ui
    assert "Math.round((boundedCompleted / total) * 100)" in ui
    assert 'progressFill.style.width = `${percent}%`' in ui


def test_diagnostics_ui_does_not_request_permissions_or_send_prompts():
    panel = (EXT / "sidepanel.js").read_text(encoding="utf-8")

    start = panel.index("async function runSystemDiagnostics()")
    end = panel.index("function showApproval", start)
    block = panel[start:end]

    assert "chrome.permissions.request" not in block
    assert "SEND_TO_LLM" not in block
    assert "send_text" not in block
