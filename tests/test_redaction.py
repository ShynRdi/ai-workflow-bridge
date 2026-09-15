from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"native_host"))
from redaction import redact_text


def test_redacts_key_value_secrets():
    text="API_KEY=super-secret-value\nPATH=/usr/bin"; out=redact_text(text); assert "super-secret-value" not in out; assert "API_KEY=[REDACTED]" in out; assert "PATH=/usr/bin" in out


def test_redacts_bearer_and_telegram_style_tokens():
    fake_bot_token="123456789:"+("A"*27); out=redact_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n"+fake_bot_token); assert "abcdefghijklmnopqrstuvwxyz" not in out; assert fake_bot_token not in out


def test_redacts_common_raw_token_formats():
    samples = [
        "github_pat_" + "A" * 30,
        "ghp_" + "B" * 30,
        "sk-" + "C" * 30,
        "AKIA" + "D" * 16,
        "AIza" + "E" * 35,
        "xoxb-" + "F" * 24,
        "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
    ]
    for value in samples:
        assert value not in redact_text(f"raw={value}")


def test_redacts_credentials_in_urls_and_query_params():
    text = "https://alice:secretpass@example.com/x?token=verysecret&ok=1"
    out = redact_text(text)
    assert "secretpass" not in out
    assert "verysecret" not in out
