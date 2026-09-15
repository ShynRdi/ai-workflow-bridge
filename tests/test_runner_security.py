import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))
from runner import run_command, sanitized_environment


def test_child_environment_does_not_inherit_arbitrary_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPER_SECRET_API_KEY", "should-not-pass")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    env = sanitized_environment()
    assert "SUPER_SECRET_API_KEY" not in env
    result = run_command("printenv SUPER_SECRET_API_KEY", str(tmp_path), ".", 10, 1000)
    assert "should-not-pass" not in result.stdout
    assert result.exit_code != 0


def test_command_text_is_redacted_before_reporting(monkeypatch, tmp_path):
    token = "sk-" + "A" * 30
    result = run_command(f"printf '%s' '{token}'", str(tmp_path), ".", 10, 1000)
    assert token not in result.command
    assert token not in result.stdout
