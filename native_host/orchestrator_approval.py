from __future__ import annotations

import uuid
from typing import Any
from config import save_config
from contracts import WorkflowContract

class ApprovalMixin:
    def _request_decision(self, contract: WorkflowContract, command: str, summary: str, impact: str, continuation: dict[str, Any]) -> None:
        approval_id=uuid.uuid4().hex[:12]; data={"approval_id":approval_id,"summary":summary,"command":command,"impact":impact,"continuation":continuation}; self.pending[approval_id]=data; self.store.put_approval(approval_id,{k:v for k,v in data.items() if k!="continuation"}); self.status="waiting_approval"; self.emit_event({"kind":"approval_required","approval_id":approval_id,"summary":summary,"command":command,"impact":impact}); self.telegram.send_approval(approval_id,summary,command,impact)

    def resolve_approval(self, approval_id: str, decision: str) -> None:
        with self.lock:
            pending=self.pending.pop(approval_id,None)
            if not pending: return
            decision="approve" if decision=="approve" else "reject"; self.store.resolve_approval(approval_id,decision); self.emit_event({"kind":"approval_resolved","approval_id":approval_id,"decision":decision,"summary":pending.get("summary","")}); continuation=pending.get("continuation") or {}
            if decision!="approve":
                self.status="idle"
                if continuation.get("kind")=="course_change": self.lifecycle="running"; self._send_result_to_chatgpt("COURSE CHANGE REJECTED by the human. Preserve the current approved roadmap, phase, and stage. Continue only with the existing scope and emit a fresh AI_WORKFLOW contract if work remains.")
                else: self._send_result_to_chatgpt("Human decision: REJECTED. Do not execute the proposed protected action. Stay on the current roadmap and propose a safer/in-scope next step.")
                return
            if continuation.get("kind")=="command":
                self._run_command_and_continue(continuation["contract"],int(continuation["index"]),accumulated=list(continuation.get("accumulated") or []),download_bundle=continuation.get("download_bundle"),approved_index=int(continuation["index"]))
            elif continuation.get("kind")=="contract":
                contract=continuation.get("contract")
                if isinstance(contract,WorkflowContract): self._send_result_to_chatgpt("Human approval received for the decision checkpoint. Continue within the approved scope. Emit a fresh AI_WORKFLOW contract for any commands; do not assume unmentioned choices."); self.status="idle"
            elif continuation.get("kind")=="course_change":
                review=continuation.get("review") or {}; patch={}
                if str(review.get("proposed_phase") or "").strip(): patch["phase"]=str(review.get("proposed_phase")).strip()
                if str(review.get("proposed_stage") or "").strip(): patch["stage"]=str(review.get("proposed_stage")).strip()
                replacement=review.get("replacement_roadmap") or []
                if replacement: patch["roadmap"]=replacement
                if patch: self.config=save_config(patch)
                self.lifecycle="running"; self.status="idle"; self.paused=False; changes="; ".join(review.get("roadmap_changes") or []); self._send_result_to_chatgpt("COURSE CHANGE APPROVED by the human. Update the authoritative roadmap/current-state documents before dependent implementation. "+f"Approved summary: {review.get('summary') or 'course change'}. "+f"Approved roadmap changes: {changes or 'as described in your review'}. "+f"The Bridge now expects phase={self.config.get('phase') or '-'}, stage={self.config.get('stage') or '-'}. "+"Continue from the preserved project state and emit a fresh AI_WORKFLOW contract for the next safe step."); self.emit({"kind":"state","state":self.state()})
