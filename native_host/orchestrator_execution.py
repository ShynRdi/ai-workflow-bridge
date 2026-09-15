from __future__ import annotations

import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any
from contracts import WorkflowContract
from files import quarantine_downloads
from policy import classify
from runner import git_snapshot, run_command

class ExecutionMixin:
    def _select_download_candidates(self, declared: list[dict[str,Any]], candidates: list[dict[str,Any]]) -> list[dict[str,Any]]:
        if not candidates: return []
        selected=[]; seen=set()
        for spec in declared:
            label=str(spec.get("label") if isinstance(spec,dict) else spec or "").strip().lower(); filename=str(spec.get("filename") if isinstance(spec,dict) else "").strip().lower(); matches=[]
            for candidate in candidates:
                hay=" ".join([str(candidate.get("label") or ""),str(candidate.get("href") or ""),str(candidate.get("rawHref") or "")]).lower()
                if (label and label in hay) or (filename and filename in hay): matches.append(candidate)
            if not matches and len(declared)==1 and len(candidates)==1: matches=candidates
            for candidate in matches:
                key=str(candidate.get("href") or candidate.get("rawHref") or candidate.get("label") or "")
                if key and key not in seen: seen.add(key); selected.append(candidate)
        return selected

    def _request_downloads(self, candidates: list[dict[str,Any]], tab_id: Any) -> list[dict[str,Any]]:
        request_id=uuid.uuid4().hex; event=threading.Event(); self.download_waiters[request_id]={"event":event,"response":None}
        try:
            self.emit({"kind":"download_request","request_id":request_id,"tab_id":tab_id,"candidates":candidates})
            if not event.wait(timeout=120): raise TimeoutError("Browser attachment download timed out")
            response=self.download_waiters[request_id].get("response") or {}
            if not response.get("ok"): raise RuntimeError(response.get("error") or "Browser download failed")
            files=list(response.get("files") or [])
            if not files: raise RuntimeError("Browser reported no downloaded files")
            return files
        finally: self.download_waiters.pop(request_id,None)

    def _execute_contract(self, contract: WorkflowContract, payload: dict[str,Any]|None=None) -> None:
        workspace=str(self.config.get("workspace_root") or "").strip()
        if not workspace: self.emit_event({"kind":"error","text":"Workspace path is not configured."}); return
        if not Path(workspace).expanduser().is_dir(): self.emit_event({"kind":"error","text":f"Workspace does not exist: {workspace}"}); return
        download_bundle=None
        if contract.downloads:
            candidates=self._select_download_candidates(contract.downloads,(payload or {}).get("downloads") or []); required=[d for d in contract.downloads if not isinstance(d,dict) or d.get("required",True)]
            if required and not candidates: self.status="failed"; self._send_result_to_chatgpt("Bridge could not find the file attachment(s) declared in downloads. Re-attach/regenerate the required file and emit a fresh contract. No commands were executed."); return
            if candidates:
                try:
                    browser_files=self._request_downloads(candidates,(payload or {}).get("tab_id")); download_bundle=quarantine_downloads(browser_files); self.emit_event({"kind":"step","badge":"ZIP!","status":"validating","text":f"Quarantined {len(download_bundle['files'])} generated file(s); SHA-256 recorded."})
                except Exception as error:
                    self.status="failed"; self.emit_event({"kind":"error","text":f"Attachment download/quarantine failed: {error}"}); self._send_result_to_chatgpt(f"Bridge failed to prepare the declared attachment(s): {error}. No commands were executed. Regenerate or reattach the file and stay on the current roadmap."); return
        if not contract.commands: self.status="idle"; self._send_result_to_chatgpt(self._format_result(contract,[],git_snapshot(workspace),git_snapshot(workspace),download_bundle)); return
        self._run_command_and_continue(contract,0,accumulated=[],download_bundle=download_bundle)

    def _run_command_and_continue(self, contract: WorkflowContract, index: int, accumulated: list[dict[str,Any]]|None=None, download_bundle: dict[str,Any]|None=None, approved_index: int|None=None) -> None:
        accumulated=list(accumulated or []); workspace=str(self.config.get("workspace_root") or ""); before=git_snapshot(workspace)
        while index<len(contract.commands):
            spec=contract.commands[index]; decision=classify(spec.cmd,workspace)
            if decision.level=="blocked": self.status="blocked"; self.emit_event({"kind":"error","text":f"Blocked command: {spec.cmd}\nReason: {decision.reason}"}); self._send_result_to_chatgpt(f"Bridge policy BLOCKED this command:\n{spec.cmd}\nReason: {decision.reason}\nPropose a safer alternative within the current roadmap."); return
            already_approved=approved_index is not None and index==approved_index
            if (decision.level=="approval" or not bool(self.config.get("auto_run_low_risk",True))) and not already_approved:
                self._request_decision(contract,command=spec.cmd,summary=spec.purpose or contract.summary or "Protected command",impact=decision.reason,continuation={"kind":"command","contract":contract,"index":index,"accumulated":accumulated,"download_bundle":download_bundle}); return
            self.status="running"; self.current_step=spec.purpose or spec.cmd; self.emit_event({"kind":"step","badge":"BAM!","status":"running","text":self.current_step})
            try: result=run_command(spec.cmd,workspace,spec.cwd,int(self.config.get("command_timeout_seconds",900)),int(self.config.get("max_output_chars",24000)),str((download_bundle or {}).get("download_dir") or ""))
            except Exception as error: accumulated.append({"command":spec.cmd,"error":str(error)}); self.emit_event({"kind":"error","text":f"Command failed to run: {error}"}); break
            item=asdict(result); accumulated.append(item)
            if approved_index is not None and index==approved_index: approved_index=None
            badge="PASS" if result.exit_code==0 else "FAIL"; self.emit_event({"kind":"step","badge":badge,"status":"running" if result.exit_code==0 else "failed","text":f"{spec.cmd} → exit {result.exit_code} in {result.duration_seconds:.1f}s"})
            if result.exit_code!=0: break
            index+=1
        after=git_snapshot(workspace); self.status="reporting"; report=self._format_result(contract,accumulated,before,after,download_bundle); self.telegram.send_report(self._telegram_summary(contract,accumulated,after)); self._send_result_to_chatgpt(report); self.status="waiting_llm"; self.current_step=contract.next_step or f"Waiting for {self.provider_name(self.active_provider)}"; self.emit_event({"kind":"step","badge":"WHOOSH","status":"waiting_llm","text":f"Terminal results sent back to {self.provider_name(self.active_provider)}."})
