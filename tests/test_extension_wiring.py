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
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    response_start = background.index(
        'message?.type === "LLM_RESPONSE_DONE"'
    )
    response_end = background.index(
        'message?.type === "LLM_ACCOUNT_SAFETY_SIGNAL"',
        response_start,
    )
    response_block = background[
        response_start:response_end
    ]

    safety_start = response_end
    safety_end = background.index(
        'message?.type === "BRIDGE_COMMAND"',
        safety_start,
    )
    safety_block = background[
        safety_start:safety_end
    ]

    assert "findBoundLlmTab(tabId)" in response_block
    assert "ignored: true" in response_block

    assert "findBoundLlmTab(tabId)" in safety_block
    assert "ignored: true" in safety_block

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

    response_start = background.index(
        'message?.type === "LLM_RESPONSE_DONE"'
    )
    response_end = background.index(
        'message?.type === "LLM_ACCOUNT_SAFETY_SIGNAL"',
        response_start,
    )
    response_block = background[
        response_start:response_end
    ]

    safety_start = response_end
    safety_end = background.index(
        'message?.type === "BRIDGE_COMMAND"',
        safety_start,
    )
    safety_block = background[
        safety_start:safety_end
    ]

    assert (
        "Response came from an unbound LLM tab"
        in response_block
    )
    assert (
        "Safety signal came from an unbound LLM tab"
        in safety_block
    )

    assert "getPinnedLlmTabId()" not in response_block
    assert "getPinnedLlmTabId()" not in safety_block

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
    assert "pinLlmBinding(found)" in block
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
        "const binding =",
        start,
    )

    block = background[start:end]

    assert "inspectActiveLlmTab()" in block
    assert "findActiveLlmTab()" not in block
    assert "pinLlmBinding(" not in block
    assert "authorizeProvisionalSealAfterSubmit(" not in block

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
        "pinLlmBinding(found)"
    )

    assert context_check < inspect < bind


def test_background_loads_conversation_identity_guard():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    identity = (
        EXT / "conversation-identity.js"
    ).read_text(
        encoding="utf-8"
    )

    assert '"conversation-identity.js"' in background
    assert "AWB_CONVERSATION_IDENTITY" in background

    assert "conversationIdentity" in identity
    assert "parsed.pathname" in identity

    assert "parsed.search" not in identity
    assert "parsed.hash" not in identity



def test_binding_persists_conversation_identity_not_only_tab_id():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    assert (
        'CONVERSATION_BINDING_STORAGE_KEY ='
        in background
    )
    assert "buildConversationBinding(found)" in background
    assert "conversationUtils.conversationIdentity(" in background

    start = background.index(
        "function buildConversationBinding("
    )
    end = background.index(
        "async function pinLlmBinding(",
        start,
    )

    block = background[start:end]

    assert "tabId: found.tab.id" in block
    assert "provider: found.provider.id" in block
    assert "pathname: identity.pathname" in block
    assert "key: identity.key" in block
    assert "provisional: identity.provisional" in block


def test_legacy_numeric_binding_is_not_migrated():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        "async function getLlmBinding()"
    )
    end = background.index(
        "async function getPinnedLlmTabId()",
        start,
    )

    block = background[start:end]

    assert "LEGACY_PINNED_TAB_STORAGE_KEY" in block
    assert "lastLlmBinding = binding" in block

    # There must be no construction of a new trusted binding
    # from only the legacy integer.
    assert (
        "tabId: stored"
        not in block
    )


def test_bound_tab_checks_conversation_identity():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        "async function findBoundLlmTab("
    )
    end = background.index(
        "function receiverMissing",
        start,
    )

    block = background[start:end]

    assert "binding.provider" in block
    assert "conversationUtils.conversationIdentity(" in block
    assert "currentIdentity.key !== binding.key" in block
    assert (
        "navigated to a different conversation"
        in block
    )
    assert "clearPinnedLlmTab()" in block


def test_binding_storage_does_not_use_query_or_fragment():
    identity = (
        EXT / "conversation-identity.js"
    ).read_text(
        encoding="utf-8"
    )

    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    assert "parsed.pathname" in identity
    assert "parsed.search" not in identity
    assert "parsed.hash" not in identity

    start = background.index(
        "function buildConversationBinding("
    )
    end = background.index(
        "async function pinLlmBinding(",
        start,
    )

    block = background[start:end]

    assert "tab.url" in block
    assert ".search" not in block
    assert ".hash" not in block


def test_provisional_binding_is_authorized_only_after_confirmed_submission():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        "async function sendTextToFoundLlm("
    )
    end = background.index(
        "async function sendTextToLlm(",
        start,
    )

    block = background[start:end]

    submitted_check = block.index(
        "result?.submitted === true"
    )
    authorization = block.index(
        "authorizeProvisionalSealAfterSubmit("
    )

    assert submitted_check < authorization

def test_draft_only_send_cannot_seal_provisional_binding():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        "async function sendTextToFoundLlm("
    )
    end = background.index(
        "async function sendTextToLlm(",
        start,
    )

    block = background[start:end]

    assert "sealWorkflowBinding = false" in block
    assert "sealWorkflowBinding &&" in block
    assert "submit &&" in block
    assert "result?.submitted === true" in block


def test_provisional_sealing_is_event_driven_and_same_tab_only():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        "function clearProvisionalSealAuthorization()"
    )
    end = background.index(
        "async function findBoundLlmTab(",
        start,
    )

    block = background[start:end]

    assert "PROVISIONAL_SEAL_AUTH_TTL_MS" in background
    assert "trySealAuthorizedProvisionalBinding(" in block
    assert "authorization.tabId !== tabId" in block
    assert "identity.autoSealable" in block

    assert "PROVISIONAL_SEAL_POLL_MS" not in block
    assert "while (Date.now()" not in block

    assert "chrome.tabs.onUpdated.addListener" in background

def test_provisional_sealing_requires_auto_sealable_route():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    identity = (
        EXT / "conversation-identity.js"
    ).read_text(
        encoding="utf-8"
    )

    assert "if (!identity.autoSealable)" in background
    assert 'return "other";' in identity
    assert (
        'autoSealable:'
        in identity
    )

def test_only_bound_workflow_send_can_seal_provisional_binding():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        "async function sendTextToFoundLlm("
    )
    end = background.index(
        "async function sendTextToLlm(",
        start,
    )

    helper = background[start:end]

    assert "sealWorkflowBinding = false" in helper
    assert "sealWorkflowBinding &&" in helper

    start = background.index(
        "async function sendTextToLlm("
    )
    end = background.index(
        "function clearResponseWatchdog",
        start,
    )

    bound_send = background[start:end]

    assert "sendTextToFoundLlm(" in bound_send
    assert "true," in bound_send


def test_generic_send_text_has_no_sealing_authority():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'command.action === "send_text"'
    )
    end = background.index(
        "const binding =",
        start,
    )

    block = background[start:end]

    assert "sendTextToFoundLlm(" in block
    assert "authorizeProvisionalSealAfterSubmit" not in block
    assert "trySealAuthorizedProvisionalBinding" not in block
    assert "pinLlmBinding(" not in block

def test_inbound_assistant_response_validates_full_binding():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'message?.type === "LLM_RESPONSE_DONE"'
    )
    end = background.index(
        'message?.type === "LLM_ACCOUNT_SAFETY_SIGNAL"',
        start,
    )

    block = background[start:end]

    assert "findBoundLlmTab(tabId)" in block
    assert "getPinnedLlmTabId()" not in block
    assert "ignored: true" in block


def test_inbound_safety_signal_validates_full_binding():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'message?.type === "LLM_ACCOUNT_SAFETY_SIGNAL"'
    )
    end = background.index(
        'message?.type === "BRIDGE_COMMAND"',
        start,
    )

    block = background[start:end]

    assert "findBoundLlmTab(tabId)" in block
    assert "getPinnedLlmTabId()" not in block
    assert "ignored: true" in block


def test_same_tab_different_conversation_is_fail_closed():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        "async function findBoundLlmTab("
    )
    end = background.index(
        "function receiverMissing",
        start,
    )

    block = background[start:end]

    assert "currentIdentity.key !== binding.key" in block
    assert "clearPinnedLlmTab()" in block
    assert (
        "navigated to a different conversation"
        in block
    )


def test_conversation_binding_clear_has_one_authoritative_implementation():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    assert (
        background.count(
            "async function clearPinnedLlmTab()"
        )
        == 1
    )

    assert "lastLlmTabId" not in background


def test_read_only_command_status_does_not_validate_or_clear_binding():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'if (message?.type === "BRIDGE_COMMAND")'
    )

    block = background[start:]

    assert "await peekLlmBinding()" in block

    tail = block[
        block.rindex(
            "const binding ="
        ):
    ]

    assert "findBoundLlmTab()" not in tail


def test_same_bound_tab_safety_mismatch_fails_safe():
    background = (EXT / "background.js").read_text(
        encoding="utf-8"
    )

    start = background.index(
        'message?.type === "LLM_ACCOUNT_SAFETY_SIGNAL"'
    )
    end = background.index(
        'message?.type === "BRIDGE_COMMAND"',
        start,
    )

    block = background[start:end]

    assert "await peekLlmBinding()" in block
    assert "binding.tabId !== tabId" in block
    assert "findBoundLlmTab(tabId)" in block
    assert 'type: "provider_safety_signal"' in block
    assert "failClosed:" in block


def test_checkpoint_actions_are_native_only_and_do_not_touch_llm_tab():
    background = (
        EXT /
        "background.js"
    ).read_text(
        encoding="utf-8"
    )

    start = background.index(
        'command.action === "checkpoint_accept"'
    )

    end = background.index(
        'command.action === "diagnostics"',
        start,
    )

    block = background[
        start:end
    ]

    assert (
        'type: "checkpoint_accept"'
        in block
    )

    assert (
        'type: "checkpoint_rollback"'
        in block
    )

    assert (
        "findActiveLlmTab("
        not in block
    )

    assert (
        "inspectActiveLlmTab("
        not in block
    )

    assert (
        "sendTextToLlm("
        not in block
    )

    assert (
        "SEND_TO_LLM"
        not in block
    )

    assert (
        "chrome.permissions"
        not in block
    )
