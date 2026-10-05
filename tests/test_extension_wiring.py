from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_extension_uses_optional_provider_permissions_and_reinjection():
    manifest = json.loads((EXT / "manifest.json").read_text())
    assert "scripting" in manifest["permissions"]
    assert manifest.get("host_permissions") == []
    assert len(manifest.get("optional_host_permissions") or []) >= 10
    background = (EXT / "background.js").read_text()
    assert "chrome.scripting.executeScript" in background
    assert 'files: ["providers.js", "content.js"]' in background
    assert "chrome.storage.session" in background
    content = (EXT / "content.js").read_text()
    assert 'message?.type === "BRIDGE_PING"' in content
    assert 'message?.type === "SEND_TO_LLM"' in content


def test_extension_confirms_real_llm_submission():
    background = (EXT / "background.js").read_text(); content = (EXT / "content.js").read_text()
    assert "result?.submitted !== true" in background
    assert "Prompt remained unsubmitted on" in content
    assert "getUserTurns().length > beforeUserCount" in content
    assert "waitForSendButton" in content
    assert "form.requestSubmit" in content


def test_provider_registry_has_major_web_llms():
    providers = (EXT / "providers.js").read_text()
    for provider in ["chatgpt", "claude", "gemini", "deepseek", "grok", "perplexity", "mistral", "copilot", "glm", "kimi"]:
        assert f'id: "{provider}"' in providers
    assert '#composer-submit-button' in providers
    assert 'button[data-testid*="send-button"]' in providers


def test_native_host_public_identifier_matches_installer():
    background = (EXT / "background.js").read_text(); installer = (ROOT / "install_native_host.sh").read_text(); host = "io.github.shynrdi.ai_workflow_bridge"
    assert host in background; assert host in installer


def test_content_version_matches_manifest_and_ping_exposes_provider_status():
    manifest = json.loads((EXT / "manifest.json").read_text())
    content = (EXT / "content.js").read_text()
    assert f'const CONTENT_VERSION = "{manifest["version"]}"' in content
    assert "providerStatus" in content


def test_browser_diagnostics_are_read_only_and_cover_bridge_health():
    background = (EXT / "background.js").read_text()

    assert "async function collectBrowserDiagnostics()" in background
    assert "async function runDiagnostics()" in background
    assert 'command.action === "diagnostics"' in background
    assert 'type: "diagnostics"' in background

    assert "chrome.permissions.contains" in background
    assert 'type: "BRIDGE_PING"' in background
    assert '"content_version"' in background
    assert '"composer"' in background

    diagnostics_start = background.index(
        "async function collectBrowserDiagnostics()"
    )
    diagnostics_end = background.index(
        "async function runDiagnostics()"
    )
    diagnostics_block = background[
        diagnostics_start:diagnostics_end
    ]

    assert "chrome.permissions.request" not in diagnostics_block
    assert "chrome.scripting.executeScript" not in diagnostics_block
    assert "SEND_TO_LLM" not in diagnostics_block

def test_user_actions_bind_to_active_llm_tab_and_do_not_fallback():
    background = (EXT / "background.js").read_text()

    assert "async function findActiveLlmTab()" in background
    assert 'active: true' in background
    assert 'currentWindow: true' in background

    lifecycle = background[
        background.index(
            '["plan_project", "arm", "change_course", "finish_project"]'
        ):
    ]

    assert "findActiveLlmTab()" in lifecycle


def test_bound_workflow_ignores_other_llm_tabs():
    background = (EXT / "background.js").read_text()

    assert (
        "Response came from a non-bound LLM tab"
        in background
    )

    assert (
        "Safety signal came from a non-bound LLM tab"
        in background
    )

    assert "await getPinnedLlmTabId()" in background


def test_diagnostics_do_not_search_other_provider_tabs():
    background = (EXT / "background.js").read_text()

    start = background.index(
        "async function findDiagnosticProviderTab("
    )
    end = background.index(
        "async function collectBrowserDiagnostics()",
        start,
    )

    block = background[start:end]

    assert "active: true" in block
    assert "currentWindow: true" in block
    assert "url: provider.origins" not in block


def test_autonomous_send_is_bound_tab_only():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    assert "async function findBoundLlmTab(" in background
    assert "async function inspectActiveLlmTab()" in background
    assert "findLlmTab(" not in background

    start = background.index(
        "async function findBoundLlmTab("
    )
    end = background.index(
        "function receiverMissing",
        start,
    )

    block = background[start:end]

    assert "chrome.tabs.get(boundTabId)" in block
    assert "chrome.tabs.query" not in block


def test_unbound_provider_events_are_ignored():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    assert background.count("boundTabId == null") >= 2


def test_recovery_rebinds_only_after_active_tab_validation():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'command.action === "recovery_prepare"'
    )
    end = background.index(
        'command.action === "recovery_discard"',
        start,
    )

    block = background[start:end]

    assert "inspectActiveLlmTab()" in block
    assert "recoveryProviderId" in block
    assert "pinLlmTab(found.tab.id)" in block
    assert "tab_id: found.tab.id" in block
    assert "provider: found.provider.id" in block


def test_generic_send_text_does_not_rebind_workflow():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'command.action === "send_text"'
    )
    end = background.index(
        "let bound = null",
        start,
    )

    block = background[start:end]

    assert "inspectActiveLlmTab()" in block
    assert "findActiveLlmTab()" not in block
    assert "pinLlmTab(" not in block



def test_recovery_requires_loaded_context_before_tab_binding():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'command.action === "recovery_prepare"'
    )
    end = background.index(
        'command.action === "recovery_discard"',
        start,
    )

    block = background[start:end]

    context_check = block.index(
        "if (!recoveryProviderId)"
    )
    inspect = block.index(
        "inspectActiveLlmTab()"
    )
    bind = block.index(
        "pinLlmTab(found.tab.id)"
    )

    assert context_check < inspect < bind
