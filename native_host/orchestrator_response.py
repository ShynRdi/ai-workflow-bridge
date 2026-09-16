from __future__ import annotations

from dataclasses import asdict
from typing import Any
from config import save_config
from contracts import WorkflowContract, extract_contract

PROJECT_DONE_MARKER = "<<<AI_WORKFLOW_PROJECT_DONE>>>"
STAGE_STOP_MARKER = "<<<AI_WORKFLOW_STOP>>>"
WORKFLOW_START_MARKER = "<<<AI_WORKFLOW>>>"
WORKFLOW_END_MARKER = "<<<END_AI_WORKFLOW>>>"


def has_exact_trailing_marker(text: str, marker: str) -> bool:
    return str(text or "").rstrip().endswith(marker)


def protocol_diagnostics(text: str, supplied: Any = None) -> dict[str, Any]:
    value=str(text or ""); data={"text_length":len(value),"workflow_start":WORKFLOW_START_MARKER in value,"workflow_end":WORKFLOW_END_MARKER in value,"stop_marker":has_exact_trailing_marker(value,STAGE_STOP_MARKER),"project_done_marker":has_exact_trailing_marker(value,PROJECT_DONE_MARKER)}
    if isinstance(supplied,dict): data["capture"]={str(k):v for k,v in supplied.items() if isinstance(v,(str,int,float,bool,type(None)))}
    return data


class ResponseMixin:
    def _recover_protocol_failure(self, text: str, payload: dict[str, Any], reason: str) -> bool:
        recoverable={"waiting_llm","waiting_chatgpt","reporting","recovering","arming","finishing"}
        if self.status not in recoverable:
            return False

        diag=protocol_diagnostics(text,payload.get("protocolDiagnostics"))
        diag["reason"]=str(reason or "incomplete workflow protocol")[:500]

        try:
            self.store.event("protocol_failure",diag)
        except Exception:
            pass

        if self.no_contract_recoveries<2:
            self.no_contract_recoveries+=1
            self.status="recovering"
            self.current_step="Recovering invalid or incomplete workflow protocol"
            self.emit_event({
                "kind":"step",
                "badge":"NUDGE!",
                "status":"recovering",
                "text":f"{self.provider_name(self.active_provider)} response did not contain a valid complete workflow protocol; requesting bounded recovery ({self.no_contract_recoveries}/2)."
            })
            self._send_result_to_chatgpt(self.protocol_recovery_prompt(diag))
            return True

        self.status="protocol_blocked"
        self.lifecycle="protocol_blocked"
        self.paused=True
        self.current_step="Workflow protocol blocked"
        self.emit_event({
            "kind":"error",
            "badge":"BLOCKED",
            "status":"protocol_blocked",
            "text":f"{self.provider_name(self.active_provider)} did not provide a valid complete workflow protocol after two bounded recovery attempts. Automation is paused; no further prompt will be sent automatically."
        })
        self.emit({"kind":"state","state":self.state()})
        return True

    def process_assistant_response(self, payload: dict[str, Any]) -> None:
        try:
            with self.lock:
                if not hasattr(self,"lifecycle"): self.lifecycle="running"
                if not hasattr(self,"active_provider"): self.active_provider=str(self.config.get("provider_id") or "chatgpt")
                if self.paused:
                    self.emit_event({"kind":"info","badge":"HOLD","text":f"A {self.provider_name(self.active_provider)} response arrived while the bridge is paused; no actions were executed."}); return
                text=str(payload.get("text") or "")
                if self.lifecycle=="planning":
                    try: roadmap=self.extract_roadmap(text)
                    except Exception as error: self.emit_event({"kind":"error","text":f"Planning roadmap JSON is invalid: {error}"}); return
                    if has_exact_trailing_marker(text,"READY_TO_ARM") and roadmap:
                        self.config=save_config({"roadmap":roadmap}); self.status="ready_to_arm"; self.lifecycle="ready_to_arm"; self.current_step="Project plan ready; waiting for ARM & RUN"; self.emit_event({"kind":"step","badge":"READY!","status":"ready_to_arm","text":f"Planning completed with {len(roadmap)} roadmap phase(s). Review the plan, then click ARM & RUN."})
                    else: self.status="planning_error"; self.emit_event({"kind":"error","text":"Planning response must include both AI_WORKFLOW_ROADMAP and end exactly with READY_TO_ARM. No execution was armed."})
                    self.emit({"kind":"state","state":self.state()}); return
                if self.lifecycle=="change_review":
                    try: review=self.extract_change_review(text)
                    except Exception as error: self.emit_event({"kind":"error","text":f"Invalid course-change review: {error}"}); return
                    if not review: self.emit_event({"kind":"error","text":"Course-change review did not include the required AI_WORKFLOW_CHANGE_REVIEW block. No roadmap changes were applied."}); return
                    impact_parts=[review.get("impact") or "",review.get("recommended") or ""]
                    if review.get("roadmap_changes"): impact_parts.append("Roadmap changes: "+"; ".join(review["roadmap_changes"]))
                    dummy=WorkflowContract(version=1,phase=str(self.config.get("phase") or ""),stage=str(self.config.get("stage") or ""),summary=review.get("summary") or "Course change")
                    self._request_decision(dummy,command="COURSE CHANGE",summary=review.get("summary") or "Review requested course change",impact="\n".join([x for x in impact_parts if x]),continuation={"kind":"course_change","review":review}); return
                if self.lifecycle=="finishing" and has_exact_trailing_marker(text,PROJECT_DONE_MARKER):
                    self.no_contract_recoveries=0; self.status="complete"; self.lifecycle="complete"; self.current_step="Project closed out"; self.paused=True; self.emit_event({"kind":"step","badge":"FIN!","status":"complete","text":"Project-wide closeout marker received after final verification. Workflow is complete and stopped."}); self.telegram.send_report(f"🏁 AI Workflow Bridge — project complete\n{self.config.get('project_name') or 'Project'}\nProvider: {self.provider_name(self.active_provider)}"); self.emit({"kind":"state","state":self.state()}); return
                try:
                    contract=extract_contract(text)
                except Exception as error:
                    reason=f"invalid AI_WORKFLOW contract: {type(error).__name__}: {error}"
                    if self._recover_protocol_failure(text,payload,reason):
                        return
                    self.emit_event({"kind":"error","text":f"Invalid AI_WORKFLOW contract: {error}"})
                    return

                if contract is None:
                    if has_exact_trailing_marker(text,STAGE_STOP_MARKER):
                        self.no_contract_recoveries=0
                        self.status="idle"
                        if self.lifecycle!="finishing":
                            self.lifecycle="idle"
                        self.current_step="Current workflow stage completed"
                        self.emit_event({
                            "kind":"step",
                            "badge":"DONE!",
                            "status":"idle",
                            "text":"The current phase/stage was explicitly marked complete. Automation stopped cleanly; update Project HQ before arming a different phase/stage."
                        })
                        return

                    if self._recover_protocol_failure(
                        text,
                        payload,
                        "missing or incomplete AI_WORKFLOW contract",
                    ):
                        return

                    self.emit_event({
                        "kind":"info",
                        "badge":"FYI",
                        "text":"LLM response had no workflow contract while no automated step was pending; treated as report-only."
                    })
                    return
                self.no_contract_recoveries=0; self.store.event("contract",asdict(contract)); self.status="validating"
                if self.lifecycle not in {"finishing"}: self.lifecycle="running"
                self.current_step=contract.summary or "Validating workflow contract"; self.emit_event({"kind":"step","badge":"SCAN","status":"validating","text":self.current_step})
                self._maybe_apply_canonical_transition(contract); roadmap_problem=self._roadmap_mismatch(contract)
                if roadmap_problem:
                    self._request_decision(contract,command="ROADMAP CHANGE",summary="The LLM proposed a step outside the configured roadmap.",impact=roadmap_problem,continuation={"kind":"contract","contract":contract}); return
                if contract.decision_required:
                    self._request_decision(contract,command="HUMAN DECISION",summary=contract.summary or "The LLM requested a human decision.",impact=contract.decision_reason or "The workflow will not continue automatically.",continuation={"kind":"contract","contract":contract}); return
                self._execute_contract(contract,payload)
        except Exception as error:
            self.status="error"; self.current_step="Assistant response processing failed"
            try: self.emit_event({"kind":"error","text":f"Could not process AI_WORKFLOW response: {type(error).__name__}: {error}"})
            except Exception: self.emit({"kind":"error","text":f"Could not process AI_WORKFLOW response: {type(error).__name__}: {error}"})

    def _roadmap_positions(self) -> list[tuple[str,str]]:
        out=[]
        for phase in self.config.get("roadmap") or []:
            pid=str((phase or {}).get("id") or "").strip(); stages=list((phase or {}).get("stages") or [])
            if not stages: out.append((pid,""))
            else: out.extend((pid,str(stage).strip()) for stage in stages if str(stage).strip())
        return [item for item in out if item[0]]

    def _maybe_apply_canonical_transition(self, contract: WorkflowContract) -> bool:
        current=(str(self.config.get("phase") or "").strip(),str(self.config.get("stage") or "").strip()); target=(str(contract.phase or "").strip(),str(contract.stage or "").strip())
        if not target[0] or target==current: return False
        positions=self._roadmap_positions()
        if not positions or current not in positions: return False
        idx=positions.index(current)
        if idx+1<len(positions) and positions[idx+1]==target:
            self.config=save_config({"phase":target[0],"stage":target[1]}); self.emit_event({"kind":"step","badge":"NEXT!","status":"validating","text":f"Advanced along the approved roadmap: {current[0]}/{current[1] or '-'} → {target[0]}/{target[1] or '-'}"}); self.emit({"kind":"state","state":self.state()}); return True
        return False

    def _roadmap_mismatch(self, contract: WorkflowContract) -> str:
        phase=str(self.config.get("phase") or "").strip(); stage=str(self.config.get("stage") or "").strip(); problems=[]
        if phase and contract.phase and phase!=contract.phase: problems.append(f"Configured phase is {phase}, proposed phase is {contract.phase}.")
        if stage and contract.stage and stage!=contract.stage: problems.append(f"Configured stage is {stage}, proposed stage is {contract.stage}.")
        return " ".join(problems)
