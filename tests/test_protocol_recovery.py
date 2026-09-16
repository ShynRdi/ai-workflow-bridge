from __future__ import annotations
import sys, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; HOST=ROOT/"native_host"
if str(HOST) not in sys.path: sys.path.insert(0,str(HOST))
from orchestrator import Orchestrator

class FakeStore:
    def event(self,*args,**kwargs): return None
class FakeTelegram:
    def send_approval(self,*args,**kwargs): return None

class FakeBudget:
    def public(self, config): return {}

def make_bridge():
    bridge=Orchestrator.__new__(Orchestrator); bridge.lock=threading.RLock(); bridge.paused=False; bridge.status="waiting_chatgpt"; bridge.current_step=""; bridge.no_contract_recoveries=0; bridge.config={"phase":"CP-0","stage":"BOOTSTRAP","workspace_root":"/tmp/project"}; bridge.store=FakeStore(); bridge.telegram=FakeTelegram(); bridge.budget=FakeBudget(); bridge.pending={}; bridge.download_waiters={}; emitted=[]; sent=[]; bridge.emit=emitted.append; bridge.emit_event=emitted.append; bridge._send_result_to_chatgpt=sent.append; return bridge,emitted,sent

def test_missing_contract_triggers_bounded_recovery():
    bridge,emitted,sent=make_bridge(); bridge.process_assistant_response({"text":"I inspected the result and Node is missing."}); assert bridge.status=="recovering"; assert bridge.no_contract_recoveries==1; assert sent and "PROTOCOL RECOVERY" in sent[-1]; assert any(event.get("badge")=="NUDGE!" for event in emitted)

def test_explicit_stop_marker_stops_cleanly():
    bridge,emitted,sent=make_bridge(); bridge.process_assistant_response({"text":"CP-0 stage complete.\n<<<AI_WORKFLOW_STOP>>>"}); assert bridge.status=="idle"; assert not sent; assert any(event.get("badge")=="DONE!" for event in emitted)

def test_missing_contract_blocks_after_two_recovery_attempts():
    bridge, emitted, sent = make_bridge()

    bridge.process_assistant_response({"text": "incomplete response one"})
    assert bridge.status == "recovering"
    assert bridge.no_contract_recoveries == 1

    bridge.process_assistant_response({"text": "incomplete response two"})
    assert bridge.status == "recovering"
    assert bridge.no_contract_recoveries == 2

    bridge.process_assistant_response({"text": "incomplete response three"})
    assert bridge.status == "protocol_blocked"
    assert bridge.lifecycle == "protocol_blocked"
    assert bridge.paused is True
    assert len(sent) == 2
    assert any(event.get("badge") == "BLOCKED" for event in emitted)

def test_invalid_json_contract_uses_bounded_recovery():
    bridge, emitted, sent = make_bridge()

    malformed = """<<<AI_WORKFLOW>>>
{"version": 1, "phase": "CP-0",
<<<END_AI_WORKFLOW>>>"""

    bridge.process_assistant_response({"text": malformed})

    assert bridge.status == "recovering"
    assert bridge.no_contract_recoveries == 1
    assert len(sent) == 1
    assert "PROTOCOL RECOVERY" in sent[0]
    assert any(event.get("badge") == "NUDGE!" for event in emitted)

def test_repeated_invalid_json_contract_eventually_blocks():
    bridge, emitted, sent = make_bridge()

    malformed = """<<<AI_WORKFLOW>>>
{"version":
<<<END_AI_WORKFLOW>>>"""

    bridge.process_assistant_response({"text": malformed})
    bridge.process_assistant_response({"text": malformed})
    bridge.process_assistant_response({"text": malformed})

    assert bridge.status == "protocol_blocked"
    assert bridge.lifecycle == "protocol_blocked"
    assert bridge.paused is True
    assert len(sent) == 2
    assert any(event.get("badge") == "BLOCKED" for event in emitted)
