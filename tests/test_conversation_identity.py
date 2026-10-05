from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "conversation-identity.js"


def run_identity(provider: str, url: str) -> dict:
    code = f"""
require({json.dumps(str(SCRIPT))});
const result =
  globalThis.AWB_CONVERSATION_IDENTITY
    .conversationIdentity(
      {json.dumps(provider)},
      {json.dumps(url)}
    );
process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", code],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    return json.loads(completed.stdout)


def test_query_and_fragment_do_not_affect_identity():
    first = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/abc123"
        "?token=SECRET_ONE#private-fragment",
    )

    second = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/abc123"
        "?different=SECRET_TWO#other",
    )

    assert first["key"] == second["key"]
    assert first["pathname"] == "/c/abc123"

    serialized = json.dumps(first)

    assert "SECRET_ONE" not in serialized
    assert "private-fragment" not in serialized


def test_different_conversation_paths_have_different_identity():
    first = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/conversation-a",
    )

    second = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/conversation-b",
    )

    assert first["key"] != second["key"]


def test_provider_is_part_of_identity():
    chatgpt = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/abc",
    )

    claude = run_identity(
        "claude",
        "https://claude.ai/c/abc",
    )

    assert chatgpt["key"] != claude["key"]


def test_provider_aware_new_chat_paths_are_provisional():
    cases = [
        (
            "chatgpt",
            "https://chatgpt.com/",
        ),
        (
            "claude",
            "https://claude.ai/new",
        ),
        (
            "gemini",
            "https://gemini.google.com/app",
        ),
    ]

    for provider, url in cases:
        result = run_identity(
            provider,
            url,
        )

        assert result["kind"] == "provisional"
        assert result["provisional"] is True
        assert result["autoSealable"] is False


def test_generic_app_and_chat_paths_are_not_auto_sealable():
    for url in [
        "https://example.test/app",
        "https://example.test/chat",
        "https://example.test/settings",
        "https://example.test/account",
    ]:
        result = run_identity(
            "provider",
            url,
        )

        assert result["kind"] == "other"
        assert result["provisional"] is False
        assert result["autoSealable"] is False


def test_existing_conversation_path_is_auto_sealable():
    result = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/abc123",
    )

    assert result["kind"] == "conversation"
    assert result["provisional"] is False
    assert result["autoSealable"] is True


def test_settings_path_is_never_auto_sealed():
    result = run_identity(
        "chatgpt",
        "https://chatgpt.com/settings",
    )

    assert result["kind"] == "other"
    assert result["autoSealable"] is False


def test_trailing_slash_normalization_is_stable():
    first = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/abc/",
    )

    second = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/abc",
    )

    assert first["key"] == second["key"]
    assert first["pathname"] == "/c/abc"
