from __future__ import annotations

import json
import threading
import uuid
from typing import Any
from contracts import WorkflowContract

class ReportingMixin:
    def _format_result(self, contract: WorkflowContract, results: list[dict[str,Any]], before: dict, after: dict, download_bundle: dict[str,Any]|None=None) -> str:
        lines=["AI WORKFLOW BRIDGE — EXECUTION REPORT",f"Roadmap: phase {self.config.get('phase') or '-'} / stage {self.config.get('stage') or '-'}",f"Step: {contract.summary}","","GENERATED FILES"]
        if download_bundle:
            lines.append(f"AI_WORKFLOW_DOWNLOAD_DIR={download_bundle.get('download_dir')}")
            for file in download_bundle.get("files") or []:
                lines.append(f"- {file.get('name')} sha256={file.get('sha256')} size={file.get('size')}"); inv=file.get("zip_inventory")
                if inv: lines.append(f"  zip_entries={inv.get('entry_count')} suspicious_paths={len(inv.get('suspicious_paths') or [])}")
        else: lines.append("(None)")
        lines += ["","COMMAND RESULTS"]
        if not results: lines.append("(No commands were executed.)")
        for idx,item in enumerate(results,1):
            lines.append(f"\n[{idx}] {item.get('command','')}")
            if "error" in item: lines.append(f"RUNNER ERROR: {item['error']}"); continue
            lines.append(f"exit_code={item.get('exit_code')} duration={item.get('duration_seconds',0):.2f}s")
            if item.get("stdout"): lines.append("STDOUT:\n"+item["stdout"])
            if item.get("stderr"): lines.append("STDERR:\n"+item["stderr"])
        lines += ["","GIT STATE BEFORE:",json.dumps(before,ensure_ascii=False,indent=2),"","GIT STATE AFTER:",json.dumps(after,ensure_ascii=False,indent=2),"","SUCCESS CONDITIONS DECLARED BY YOU:",*[f"- {x}" for x in contract.success_conditions],"","Use this report as authoritative. Summarize what actually happened and keep the current roadmap. Your response MUST end with exactly one AI_WORKFLOW contract if another execution or decision step is needed; otherwise, only when the CURRENT configured phase/stage is genuinely complete, end with exactly <<<AI_WORKFLOW_STOP>>>. Do not omit both."]
        return "\n".join(lines)

    def _telegram_summary(self, contract: WorkflowContract, results: list[dict[str,Any]], after: dict) -> str:
        ok=all(item.get("exit_code")==0 and "error" not in item for item in results) if results else True; icon="✅" if ok else "❌"; lines=[f"{icon} AI Workflow Bridge",f"{contract.phase}/{contract.stage} — {contract.summary}"]
        for item in results[-5:]: lines.append(f"• ERROR — {item['error']}" if "error" in item else f"• exit {item.get('exit_code')} — {item.get('command','')[:120]}")
        if after.get("is_git"): lines.append(f"Git: {after.get('branch') or '(detached)'} @ {str(after.get('head') or '')[:8]}")
        lines.append(f"Next: {contract.next_step or 'wait for selected LLM'}"); return "\n".join(lines)

    def _send_result_to_chatgpt(self, text: str) -> None:
        text=self.decorate_outbound_prompt(text)
        if self.provider_guard: self.emit_event({"kind":"error","text":"Provider safety guard is active; outbound LLM messages are blocked."}); return
        decision=self.budget.decision(self.config)
        if not decision.get("allowed"):
            self.paused=True; self.lifecycle="budget_exhausted"; self.status="budget_exhausted"; self.current_step=str(decision.get("reason") or "AI-turn budget exhausted"); self.emit_event({"kind":"step","badge":"BRAKE!","status":"budget_exhausted","text":f"Automation stopped before sending another {self.provider_name(self.active_provider)} turn: {self.current_step}. Use RESET RUN BUDGET only after reviewing the run."}); self.emit({"kind":"state","state":self.state()}); return
        def dispatch() -> None:
            with self.lock:
                self.pending_send_timer=None
                if self.paused or self.provider_guard: return
                second=self.budget.decision(self.config)
                if not second.get("allowed"): self.paused=True; self.lifecycle="budget_exhausted"; self.status="budget_exhausted"; self.current_step=str(second.get("reason") or "AI-turn budget exhausted"); self.emit_event({"kind":"step","badge":"BRAKE!","status":"budget_exhausted","text":self.current_step}); return
                self.budget.record_send(); self.emit({"kind":"send_to_llm","request_id":str(uuid.uuid4()),"text":text}); self.emit({"kind":"state","state":self.state()})
        delay=float(decision.get("delay") or 0.0)
        if delay>0.05:
            if self.pending_send_timer is not None: self.pending_send_timer.cancel()
            self.status="cooldown"; self.current_step=f"Waiting {delay:.1f}s before the next AI turn"; self.emit_event({"kind":"step","badge":"COOL","status":"cooldown","text":self.current_step}); self.pending_send_timer=threading.Timer(delay,dispatch); self.pending_send_timer.daemon=True; self.pending_send_timer.start()
        else: dispatch()
