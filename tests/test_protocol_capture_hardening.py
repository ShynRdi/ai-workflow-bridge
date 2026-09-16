from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_protocol_aware_capture_and_recapture():
    c=(ROOT/"extension/content.js").read_text()
    for x in ["INCOMPLETE_PROTOCOL_GRACE_MS","protocolComplete","protocolDiagnostics","samePreviouslySentNodeChanged","incomplete_protocol_grace_expired"]: assert x in c

def test_central_prompt_discipline():
    c=(ROOT/"native_host/orchestrator_core.py").read_text(); r=(ROOT/"native_host/orchestrator_reporting.py").read_text()
    assert "STRICT RESPONSE PROTOCOL" in c and "technically best next step" in c and "decorate_outbound_prompt" in c
    assert "text=self.decorate_outbound_prompt(text)" in r

def test_protocol_blocked_is_clean_pause():
    r=(ROOT/"native_host/orchestrator_response.py").read_text(); m=(ROOT/"native_host/orchestrator_messages.py").read_text()
    assert 'self.status="protocol_blocked"' in r and "protocol_diagnostics" in r and '"protocol_blocked"' in m

def test_finishing_accepts_clean_stop_marker():
    c=(ROOT/"extension/content.js").read_text()
    assert 'expectedResponse === "finishing"' in c
    assert 'trailing(value, STOP_MARKER)' in c
