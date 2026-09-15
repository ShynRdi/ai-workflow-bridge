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

def make_bridge():
    bridge=Orchestrator.__new__(Orchestrator); bridge.lock=threading.RLock(); bridge.paused=False; bridge.status="waiting_chatgpt"; bridge.current_step=""; bridge.no_contract_recoveries=0; bridge.config={"phase":"CP-0","stage":"BOOTSTRAP","workspace_root":"/tmp/project"}; bridge.store=FakeStore(); bridge.telegram=FakeTelegram(); bridge.pending={}; bridge.download_waiters={}; emitted=[]; sent=[]; bridge.emit=emitted.append; bridge.emit_event=emitted.append; bridge._send_result_to_chatgpt=sent.append; return bridge,emitted,sent

def test_missing_contract_triggers_bounded_recovery():
    bridge,emitted,sent=make_bridge(); bridge.process_assistant_response({"text":"I inspected the result and Node is missing."}); assert bridge.status=="recovering"; assert bridge.no_contract_recoveries==1; assert sent and "PROTOCOL RECOVERY" in sent[-1]; assert any(event.get("badge")=="NUDGE!" for event in emitted)

def test_explicit_stop_marker_stops_cleanly():
    bridge,emitted,sent=make_bridge(); bridge.process_assistant_response({"text":"CP-0 stage complete.\n<<<AI_WORKFLOW_STOP>>>"}); assert bridge.status=="idle"; assert not sent; assert any(event.get("badge")=="DONE!" for event in emitted)
