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



def test_recovery_panel_exposes_explicit_human_decisions():
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    panel = (EXT / "sidepanel.js").read_text(encoding="utf-8")

    assert 'id="recoveryPanel"' in html
    assert 'id="recoveryLifecycle"' in html
    assert 'id="recoveryStatus"' in html
    assert 'id="recoveryStep"' in html
    assert 'id="recoveryApprovals"' in html
    assert 'id="prepareRecovery"' in html
    assert 'id="discardRecovery"' in html

    assert 'command("recovery_prepare")' in panel
    assert 'command("recovery_discard")' in panel
    assert "renderRecovery(state)" in panel


def test_recovery_ui_does_not_send_llm_prompt_directly():
    panel = (EXT / "sidepanel.js").read_text(encoding="utf-8")

    start = panel.index(
        '$("prepareRecovery").addEventListener'
    )
    end = panel.index(
        '$("planProject").addEventListener',
        start,
    )

    block = panel[start:end]

    assert "send_text" not in block
    assert "SEND_TO_LLM" not in block
    assert 'command("arm")' not in block


def test_checkpoint_panel_exposes_scope_and_explicit_controls():
    html = (
        EXT /
        "sidepanel.html"
    ).read_text(
        encoding="utf-8"
    )

    panel = (
        EXT /
        "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    for element_id in [
        "checkpointPanel",
        "checkpointStatus",
        "checkpointSummary",
        "checkpointRisk",
        "checkpointScope",
        "checkpointFiles",
        "checkpointBytes",
        "checkpointLimitations",
        "acceptCheckpoint",
        "rollbackCheckpoint",
    ]:
        assert (
            f'id="{element_id}"'
            in html
        )

    assert (
        "renderCheckpoint(state)"
        in panel
    )

    assert (
        'command("checkpoint_accept")'
        in panel
        or (
            '"checkpoint_accept"'
            in panel
        )
    )

    assert (
        '"checkpoint_rollback"'
        in panel
    )

    assert (
        "globalThis.confirm("
        in panel
    )


def test_checkpoint_ui_states_rollback_limitations():
    html = (
        EXT /
        "sidepanel.html"
    ).read_text(
        encoding="utf-8"
    )

    panel = (
        EXT /
        "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    combined = (
        html +
        panel
    ).lower()

    assert (
        "git history"
        in combined
        or "git metadata"
        in combined
    )

    assert (
        "remote"
        in combined
    )

    assert (
        "database"
        in combined
    )

    assert (
        "system"
        in combined
    )

    assert (
        ".ai-workflow"
        in combined
    )


def test_recovery_ui_surfaces_uncertain_checkpoint_state():
    html = (
        EXT /
        "sidepanel.html"
    ).read_text(
        encoding="utf-8"
    )

    panel = (
        EXT /
        "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="recoveryCheckpointBlock"'
        in html
    )

    assert (
        'id="recoveryCheckpointStatus"'
        in html
    )

    assert (
        'id="recoveryCheckpointId"'
        in html
    )

    assert (
        "recovery.checkpoint_recovery"
        in panel
    )

    assert (
        "will not automatically retry"
        in html
    )


def test_checkpoint_buttons_follow_authoritative_native_capabilities():
    panel = (
        EXT /
        "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'checkpoint.can_accept !== true'
        in panel
    )

    assert (
        'checkpoint.can_rollback !== true'
        in panel
    )

    assert (
        '$("acceptCheckpoint").disabled ='
        in panel
    )

    assert (
        '$("rollbackCheckpoint").disabled ='
        in panel
    )

    assert (
        "checkpoint.can_accept !== true"
        in panel
    )

    assert (
        "checkpoint.can_rollback !== true"
        in panel
    )


def test_checkpoint_state_refreshes_after_execution_or_pause_boundary():
    panel = (
        EXT /
        "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"waiting_llm"'
        in panel
    )

    assert (
        '"paused"'
        in panel
    )

    assert (
        'command("get_state")'
        in panel
    )


def test_checkpoint_confirmation_never_claims_full_transaction():
    panel = (
        EXT /
        "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    start = panel.index(
        '$("rollbackCheckpoint").addEventListener'
    )

    end = panel.index(
        '$("planProject").addEventListener',
        start,
    )

    block = panel[
        start:end
    ].lower()

    assert (
        "this does not undo"
        in block
    )

    assert (
        "git history"
        in block
    )

    assert (
        "remote actions"
        in block
    )

    assert (
        "database changes"
        in block
    )

    assert (
        "system/package changes"
        in block
    )

    assert (
        ".ai-workflow"
        in block
    )

    assert (
        "full rollback"
        not in block
    )

    assert (
        "fully transactional"
        not in block
    )
