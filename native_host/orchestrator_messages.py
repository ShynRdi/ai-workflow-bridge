from __future__ import annotations

import threading
from typing import Any
from config import save_config

class MessageMixin:
    def handle(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type == "ping":
            self.emit({"kind":"host_status","connected":True,"text":"Native host is online"}); self.emit({"kind":"state","state":self.state()})
        elif msg_type == "get_state": self.emit({"kind":"state","state":self.state()})
        elif msg_type == "set_config":
            self.config=save_config(message.get("config") or {})
            if self.lifecycle=="setup": self.active_provider=str(self.config.get("provider_id") or self.active_provider); self.budget.set_provider(self.active_provider)
            self.emit_event({"kind":"info","badge":"SAVED","text":"Local project, provider, and safety configuration updated."}); self.emit({"kind":"state","state":self.state()})
        elif msg_type in {"build_start_prompt","build_controller_prompt","change_course","finish_project"}:
            provider=str(message.get("provider") or self.config.get("provider_id") or self.active_provider); self.active_provider=provider; self.budget.set_provider(provider); self.no_contract_recoveries=0
            if msg_type=="build_start_prompt":
                if not str(self.config.get("project_goal") or "").strip(): self.emit_event({"kind":"error","text":"Project goal/master brief is empty."}); return
                self.lifecycle="planning"; self.status="planning"; self.current_step=f"Planning project with {self.provider_name(provider)}"; self.emit_event({"kind":"step","badge":"PLAN!","status":"planning","text":self.current_step}); self._send_result_to_chatgpt(self.start_prompt()); return
            if msg_type=="build_controller_prompt":
                if self.lifecycle in {"ready_to_arm","setup","idle","protocol_error","protocol_blocked","paused"}:
                    if self.lifecycle in {"ready_to_arm","setup"}: self.budget.reset(provider)
                    self.provider_guard=False; self.paused=False; self.lifecycle="running"
                self.status="arming"; self.current_step=f"Arming {self.provider_name(provider)} workflow"; self.emit_event({"kind":"step","badge":"ZAP!","status":"arming","text":self.current_step}); self._send_result_to_chatgpt(self.controller_prompt()); return
            if msg_type=="change_course":
                request=str(message.get("change_request") or "").strip()
                if not request: self.emit_event({"kind":"error","text":"Course-change request is empty."}); return
                self.paused=False; self.lifecycle="change_review"; self.status="change_review"; self.current_step="Reviewing requested roadmap change"; self.emit_event({"kind":"step","badge":"PIVOT?","status":"change_review","text":self.current_step}); self._send_result_to_chatgpt(self.course_change_prompt(request)); return
            self.paused=False; self.lifecycle="finishing"; self.status="finishing"; self.current_step="Running project closeout and final verification"; self.emit_event({"kind":"step","badge":"CHECK!","status":"finishing","text":self.current_step}); self._send_result_to_chatgpt(self.finish_prompt()); return
        elif msg_type=="pause": self.paused=True; self.lifecycle="paused"; self.status="paused"; self.emit_event({"kind":"step","badge":"HOLD","status":"paused","text":"Workflow paused by user."})
        elif msg_type=="resume":
            if self.provider_guard: self.emit_event({"kind":"error","text":"Provider safety guard is active. Resolve the rate-limit/auth/security warning in the provider UI, then use RESET RUN BUDGET to explicitly start a fresh guarded session."}); return
            self.paused=False; self.lifecycle="running"; self.status="idle"; self.emit_event({"kind":"step","badge":"GO!","status":"idle","text":"Workflow resumed."})
        elif msg_type=="reset_session":
            self.provider_guard=False; self.paused=False; self.budget.reset(self.active_provider); self.status="idle"
            if self.lifecycle in {"paused","budget_exhausted"}: self.lifecycle="running"
            self.emit_event({"kind":"step","badge":"RESET","status":self.lifecycle,"text":"Autonomy budget reset by user. Provider safety cooldown cleared explicitly."}); self.emit({"kind":"state","state":self.state()})
        elif msg_type=="provider_safety_signal":
            payload=message.get("payload") or {}; provider=str(payload.get("provider") or self.active_provider); self.active_provider=provider; reason=f"{payload.get('kind') or 'provider safety warning'}: {payload.get('text') or 'provider asked automation to stop'}"; self.provider_guard=True; self.paused=True; self.lifecycle="paused"; self.status="provider_guard"; self.budget.block(reason); self.current_step="Provider account-safety guard triggered"; self.emit_event({"kind":"step","badge":"SHIELD!","status":"paused","text":f"{self.provider_name(provider)} showed a rate-limit/auth/security warning. Automation stopped immediately; no automatic retry or provider fallback will occur."}); self.telegram.send_report(f"🛡 AI Workflow Bridge paused\nProvider: {self.provider_name(provider)}\nReason: {reason[:700]}\nNo automatic retry/fallback will run.")
        elif msg_type=="assistant_response":
            payload=message.get("payload") or {}; provider=str(payload.get("provider") or self.active_provider); self.active_provider=provider; self.emit_event({"kind":"info","badge":"POP!","text":f"Completed {self.provider_name(provider)} response captured; inspecting workflow protocol."}); threading.Thread(target=self.process_assistant_response,args=(payload,),daemon=True).start()
        elif msg_type=="approval_decision": self.resolve_approval(str(message.get("approval_id") or ""),str(message.get("decision") or ""))
        elif msg_type=="download_result":
            request_id=str(message.get("request_id") or ""); waiter=self.download_waiters.get(request_id)
            if waiter: waiter["response"]=message; waiter["event"].set()
        elif msg_type=="chat_send_ack":
            if message.get("ok") and message.get("submitted",True): self.status="waiting_llm"; self.current_step=f"Prompt submitted; waiting for {self.provider_name(self.active_provider)}"; self.emit_event({"kind":"step","badge":"ARMED","status":self.lifecycle,"text":self.current_step})
            else: self.status="error"; self.current_step="LLM prompt submission failed"; self.emit_event({"kind":"error","text":f"Could not send prompt/result to {self.provider_name(self.active_provider)}: {message.get('error') or 'submission was not confirmed'}"})
        elif msg_type=="chat_response_timeout": self.emit_event({"kind":"info","badge":"STUCK?","text":str(message.get("text") or "No completed LLM response has been detected yet.")})
