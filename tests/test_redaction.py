from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"native_host"))
from redaction import redact_text

def test_redacts_key_value_secrets():
    text="API_KEY=super-secret-value\nPATH=/usr/bin"; out=redact_text(text); assert "super-secret-value" not in out; assert "API_KEY=[REDACTED]" in out; assert "PATH=/usr/bin" in out

def test_redacts_bearer_and_telegram_style_tokens():
    fake_bot_token="123456789:"+("A"*27); out=redact_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n"+fake_bot_token); assert "abcdefghijklmnopqrstuvwxyz" not in out; assert fake_bot_token not in out
