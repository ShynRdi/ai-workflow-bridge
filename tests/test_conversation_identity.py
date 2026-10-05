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


def test_new_chat_paths_are_provisional():
    for url in [
        "https://chatgpt.com/",
        "https://example.test/new",
        "https://example.test/chat",
        "https://example.test/chat/new",
        "https://example.test/new-chat",
        "https://example.test/app",
    ]:
        result = run_identity(
            "provider",
            url,
        )

        assert result["provisional"] is True


def test_existing_conversation_path_is_sealed():
    result = run_identity(
        "chatgpt",
        "https://chatgpt.com/c/abc123",
    )

    assert result["provisional"] is False


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
