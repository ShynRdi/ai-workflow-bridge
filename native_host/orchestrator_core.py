from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from config import load_config, public_config, save_config
from contracts import WorkflowContract, extract_contract
from files import quarantine_downloads
from policy import classify
from runner import git_snapshot, run_command
from safety import RunBudget
from storage import Store
from telegram import TelegramClient

class CoreMixin:
    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self.emit = emit
        self.store = Store()
        self.config = load_config()
        self.paused = False
        self.status = "idle"
        self.current_step = ""
        self.pending: dict[str, dict[str, Any]] = {}
        self.download_waiters: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.telegram = TelegramClient(lambda: self.config, self.resolve_approval)
        self.no_contract_recoveries = 0
        self.lifecycle = "setup"
        self.active_provider = str(self.config.get("provider_id") or "chatgpt")
        self.provider_guard = False
        self.budget = RunBudget()
        self.budget.reset(self.active_provider)
        self.pending_send_timer: threading.Timer | None = None

    def emit_event(self, event: dict[str, Any]) -> None:
        self.store.event(event.get("kind", "event"), event)
        self.emit(event)

    def state(self) -> dict[str, Any]:
        return {"paused": self.paused, "status": self.status, "lifecycle": self.lifecycle, "current_step": self.current_step, "config": public_config(self.config), "budget": self.budget.public(self.config), "active_provider": self.active_provider, "active_provider_name": self.provider_name(self.active_provider), "pending_approvals": list(self.pending)}

    @staticmethod
    def provider_name(provider_id: str) -> str:
        names = {"chatgpt":"ChatGPT","claude":"Claude","gemini":"Gemini","deepseek":"DeepSeek","grok":"Grok","perplexity":"Perplexity","mistral":"Mistral Vibe","copilot":"Microsoft Copilot","meta":"Meta AI","poe":"Poe","qwen":"Qwen","glm":"Z.ai / GLM","kimi":"Kimi"}
        return names.get(provider_id, provider_id or "Web LLM")

    def protocol_rules(self) -> str:
        phase=str(self.config.get("phase") or "UNSET").strip()
        stage=str(self.config.get("stage") or "UNSET").strip()
        return f"""AI WORKFLOW BRIDGE — STRICT RESPONSE PROTOCOL

These rules constrain response format, safety, and roadmap discipline only.
You remain free to choose the technically best next step from the current evidence.
Do not follow a predetermined implementation path merely to satisfy this protocol.

TERMINAL RESPONSE RULE
- If executable local work remains, the response MUST end with exactly one complete
  <<<AI_WORKFLOW>>> ... <<<END_AI_WORKFLOW>>> block.
- If a genuine human product/architecture/scope decision is required before dependent work,
  set decision_required=true and include no commands that depend on that unresolved choice.
- If the current configured phase/stage is intentionally complete or there is no executable
  next action, end exactly with <<<AI_WORKFLOW_STOP>>>.
- Only during FINISH PROJECT, after all required verification succeeds and no required work
  remains, end exactly with <<<AI_WORKFLOW_PROJECT_DONE>>>.
- Never emit two AI_WORKFLOW blocks.
- Never omit all terminal protocol markers.
- Never put prose after the final terminal marker.

GENERAL WORKFLOW DISCIPLINE
- Current configured position is phase={phase}, stage={stage}.
- Preserve the approved roadmap and user decisions.
- Do not silently change phase, stage, scope, architecture commitments, or completed work.
- Choose the next step from actual evidence; do not repeat completed work unless new evidence
  makes re-verification necessary.
- Human-readable prose is never executable.
- Every commands[] item must be exactly one atomic shell command.
- Do not chain commands with &&, ||, ;, pipes, redirections, command substitution, or multiline shell.
- Every command must include cwd, purpose, and semantic risk_assessment.
- The LLM risk assessment is advisory only and can never authorize or lower local policy risk.
- Never request login automation, CAPTCHA/MFA/security bypass, cookie/session extraction,
  rate-limit circumvention, credential disclosure, or destructive shortcuts.

RISK RUBRIC
- R0: read-only local inspection with no meaningful side effect.
- R1: bounded verification or read-only external metadata lookup with minimal side effect.
- R2: reversible workspace mutation, dependency change, or execution of project-controlled code.
- R3: sensitive, remote, external-state, credential-adjacent, or production-significant operation.
- R4: destructive, credential-exposing, security-bypassing, or otherwise forbidden operation.
When uncertain, choose the higher risk.

REQUIRED CONTRACT SHAPE
<<<AI_WORKFLOW>>>
{{
  "version": 1,
  "phase": "{phase}",
  "stage": "{stage}",
  "summary": "short description of this step",
  "decision_required": false,
  "decision_reason": "",
  "downloads": [],
  "commands": [
    {{
      "cmd": "one atomic shell command",
      "cwd": ".",
      "purpose": "why this command is needed",
      "risk_assessment": {{
        "level": "R0",
        "confidence": 0.99,
        "factors": ["concise evidence-based reason"],
        "dimensions": {{
          "filesystem": 0,
          "network": 0,
          "credentials": 0,
          "database": 0,
          "git_remote": 0,
          "system": 0,
          "production": 0,
          "irreversibility": 0,
          "data_exfiltration": 0
        }},
        "reversible": true,
        "recommended_action": "auto"
      }}
    }}
  ],
  "success_conditions": ["observable evidence that proves this step succeeded"],
  "next_step": "what should be considered after this step succeeds"
}}
<<<END_AI_WORKFLOW>>>
"""

    def decorate_outbound_prompt(self, text: str) -> str:
        value=str(text or "").rstrip()
        if "AI WORKFLOW BRIDGE — PROJECT START" in value:
            return value + """

AI WORKFLOW BRIDGE — PLANNING OUTPUT DISCIPLINE
These rules constrain output format, not your technical reasoning.
Planning is reasoning-only: do not emit an executable AI_WORKFLOW block.
Create the technically appropriate roadmap from the master brief and evidence.
Include exactly one AI_WORKFLOW_ROADMAP block containing the configured initial phase/stage.
End the entire response with exactly READY_TO_ARM.
Do not put prose after READY_TO_ARM.
"""
        if "AI WORKFLOW BRIDGE — COURSE CHANGE REVIEW" in value:
            return value + """

AI WORKFLOW BRIDGE — COURSE-CHANGE OUTPUT DISCIPLINE
These rules constrain output format, not your technical recommendation.
This turn is review-only: do not emit executable commands.
Analyze the requested change from the current evidence and preserved project state.
Return exactly one AI_WORKFLOW_CHANGE_REVIEW block.
End the entire response with exactly <<<END_AI_WORKFLOW_CHANGE_REVIEW>>>.
Do not put prose after the end marker.
"""
        return value + "\n\n" + self.protocol_rules()

    def protocol_recovery_prompt(self, diagnostics: dict[str, Any]) -> str:
        return f"""AI WORKFLOW BRIDGE — PROTOCOL RECOVERY
The previously captured response did not contain a complete terminal workflow protocol.
Capture diagnostics: {json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)}

Use the current conversation, canonical roadmap, and latest terminal evidence.
Do not restart the task and do not repeat completed commands merely because recovery was requested.
Choose the technically best next step yourself; only output format, safety, and roadmap discipline are constrained.
"""

    def start_prompt(self) -> str:
        project=str(self.config.get("project_name") or "Untitled Project").strip(); goal=str(self.config.get("project_goal") or "").strip(); phase=str(self.config.get("phase") or "UNSET").strip(); stage=str(self.config.get("stage") or "UNSET").strip(); workspace=str(self.config.get("workspace_root") or "UNSET").strip()
        return f'''AI WORKFLOW BRIDGE — PROJECT START

Project: {project}
Workspace: {workspace}
Initial phase/stage: {phase} / {stage}

MASTER BRIEF
{goal}

For this FIRST response, PLAN ONLY. Do not emit AI_WORKFLOW commands and do not instruct the machine to mutate files.

Produce a concrete technical project plan that includes:
- interpretation of the goal and explicit out-of-scope items;
- proposed architecture and repository strategy;
- an authoritative phase/stage roadmap with acceptance criteria;
- security/privacy/account boundaries;
- testing and verification strategy;
- decisions that genuinely require the human owner;
- start conditions, completion conditions, and rollback/recovery expectations.

The roadmap becomes the source of truth once execution is armed. Do not silently change it later.
If the user changes direction later, AI Workflow Bridge will send a formal COURSE CHANGE request; analyze its impact before any new commands run.

Before READY_TO_ARM, include exactly one machine-readable roadmap:

<<<AI_WORKFLOW_ROADMAP>>>
{{
  "phases": [
    {{"id": "PHASE-ID", "title": "short title", "stages": ["STAGE-1", "STAGE-2"]}}
  ]
}}
<<<END_AI_WORKFLOW_ROADMAP>>>

Phase/stage identifiers must be stable and concise. Include the configured initial phase/stage in this roadmap.

End the response with exactly:
READY_TO_ARM
Do not put prose after READY_TO_ARM.
'''

    def controller_prompt(self) -> str:
        phase=self.config.get("phase") or "UNSET"; stage=self.config.get("stage") or "UNSET"; workspace=self.config.get("workspace_root") or "UNSET"; provider_id=getattr(self,"active_provider",str(self.config.get("provider_id") or "chatgpt")); provider=self.provider_name(provider_id); model_label=str(self.config.get("model_label") or "unspecified / selected manually in provider UI"); roadmap=json.dumps(self.config.get("roadmap") or [],ensure_ascii=False)
        return f'''You are the sole reasoning LLM controlling a guarded LOCAL workflow through AI Workflow Bridge.

ACTIVE WEB LLM: {provider}
MODEL LABEL: {model_label}
CONFIGURED WORKSPACE: {workspace}
CURRENT ROADMAP POSITION: phase={phase}, stage={stage}
CANONICAL ROADMAP JSON: {roadmap}

NON-NEGOTIABLE RULES
1. You are the only LLM in this workflow. Do not ask the bridge to call another model/API for development reasoning.
2. Stay on the approved roadmap and current phase/stage. A direction change must go through the Bridge COURSE CHANGE flow.
3. Prefer verification and minimal scoped fixes. Do not introduce unrelated refactors.
4. Human-readable prose is NEVER executable. The bridge executes only machine-readable commands declared in the contract.
5. If a product/architecture/scope choice is genuinely required, set decision_required=true and include no commands that depend on an unapproved choice.
6. Generated files needed by commands must be declared in downloads and referenced only through ${{AI_WORKFLOW_DOWNLOAD_DIR}}.
7. Every commands[] item must be ONE atomic shell command. Do not chain with &&, ||, ;, pipes, redirections, command substitution, or multiline shell.
8. Never request login automation, CAPTCHA/security bypass, cookie/session extraction, or rate-limit circumvention.
9. Every response that advances automation MUST end with exactly one contract:

<<<AI_WORKFLOW>>>
{{
  "version": 1,
  "phase": "{phase}",
  "stage": "{stage}",
  "summary": "short description of this step",
  "decision_required": false,
  "decision_reason": "",
  "downloads": [],
  "commands": [{{"cmd": "git status --short", "cwd": ".", "purpose": "inspect repo state"}}],
  "success_conditions": ["what output proves this step succeeded"],
  "next_step": "what follows if this passes"
}}
<<<END_AI_WORKFLOW>>>

10. After every terminal report, end with exactly one AI_WORKFLOW contract if work remains. When the current stage is complete and the canonical roadmap has a next stage, move to that immediate next stage in the next contract; the Bridge will validate that transition. Use <<<AI_WORKFLOW_STOP>>> only for an intentional clean pause or when no executable next stage exists.
11. Project-wide completion is different from stage completion. Only when the user has requested FINISH PROJECT, all final verification is complete, and no known required work remains, end with exactly <<<AI_WORKFLOW_PROJECT_DONE>>>.

Continue from the current conversation context now. If the next safe in-roadmap action requires repository state, emit low-risk inspection commands. Do not merely acknowledge this controller message.'''

    @staticmethod
    def extract_roadmap(text: str) -> list[dict[str, Any]] | None:
        start_marker="<<<AI_WORKFLOW_ROADMAP>>>"; end_marker="<<<END_AI_WORKFLOW_ROADMAP>>>"
        if start_marker not in text or end_marker not in text: return None
        raw=text.rsplit(start_marker,1)[1].split(end_marker,1)[0].strip(); raw=re.sub(r"^```(?:json)?\s*|\s*```$","",raw,flags=re.I|re.S).strip(); data=json.loads(raw); phases=[]
        for item in data.get("phases") or []:
            if not isinstance(item,dict) or not str(item.get("id") or "").strip(): continue
            stages=[str(x).strip() for x in (item.get("stages") or []) if str(x).strip()]; phases.append({"id":str(item["id"]).strip(),"title":str(item.get("title") or "").strip(),"stages":stages})
        return phases or None

    def course_change_prompt(self, request: str) -> str:
        return f'''AI WORKFLOW BRIDGE — COURSE CHANGE REVIEW

Current approved phase/stage: {self.config.get('phase') or '-'} / {self.config.get('stage') or '-'}
User requested this change:
{request}

Do NOT emit executable commands yet. Analyze the effect on scope, architecture, completed work, risks, schedule, and roadmap. Preserve completed work where possible.
Return concise prose plus exactly one machine-readable review:

<<<AI_WORKFLOW_CHANGE_REVIEW>>>
{{
  "summary": "what is changing",
  "impact": "what this changes and what stays intact",
  "recommended": "recommended handling",
  "proposed_phase": "phase to use after approval, usually current phase unless truly changed",
  "proposed_stage": "stage to use after approval",
  "roadmap_changes": ["specific roadmap edits"],
  "replacement_roadmap": {{"phases": [{{"id": "PHASE-ID", "title": "title", "stages": ["STAGE-1"]}}]}}
}}
<<<END_AI_WORKFLOW_CHANGE_REVIEW>>>

No commands may run until the human approves this review.'''

    def finish_prompt(self) -> str:
        return f'''AI WORKFLOW BRIDGE — FINISH PROJECT REQUEST

Project: {self.config.get('project_name') or 'project'}
Current phase/stage: {self.config.get('phase') or '-'} / {self.config.get('stage') or '-'}

The human requested project closeout. Do not declare success casually.
First determine whether final verification, documentation, tests, build checks, or safe cleanup are still required. If local verification is needed, emit a normal AI_WORKFLOW contract and continue the guarded loop.
Summarize completed work, known limitations, remaining optional/future work, operational/deployment notes, and how to resume later.
Only after required verification succeeds and there is no known required work left, end the final response with exactly:
<<<AI_WORKFLOW_PROJECT_DONE>>>
'''

    @staticmethod
    def extract_change_review(text: str) -> dict[str, Any] | None:
        start_marker="<<<AI_WORKFLOW_CHANGE_REVIEW>>>"; end_marker="<<<END_AI_WORKFLOW_CHANGE_REVIEW>>>"
        if start_marker not in text or end_marker not in text: return None
        raw=text.rsplit(start_marker,1)[1].split(end_marker,1)[0].strip(); raw=re.sub(r"^```(?:json)?\s*|\s*```$","",raw,flags=re.I|re.S).strip(); data=json.loads(raw)
        return {"summary":str(data.get("summary") or "Course change"),"impact":str(data.get("impact") or ""),"recommended":str(data.get("recommended") or ""),"proposed_phase":str(data.get("proposed_phase") or ""),"proposed_stage":str(data.get("proposed_stage") or ""),"roadmap_changes":[str(x) for x in (data.get("roadmap_changes") or [])],"replacement_roadmap":list((data.get("replacement_roadmap") or {}).get("phases") or [])}
