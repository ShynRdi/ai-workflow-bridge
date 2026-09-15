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
