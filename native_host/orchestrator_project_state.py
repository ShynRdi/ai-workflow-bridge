from __future__ import annotations

from pathlib import Path
from typing import Any

from config import save_config
from project_state import (
    advance_project_state,
    apply_course_change,
    complete_project_state,
    ensure_project_state,
    initialize_project_state,
    load_project_state,
    project_state_summary,
)


class ProjectStateMixin:
    """Project-local roadmap authority layered over the legacy global config.

    Global config keeps provider/safety/workspace preferences for backward compatibility.
    Once <workspace>/.ai-workflow/ROADMAP.md exists, its current phase/stage and
    roadmap become authoritative for workflow navigation.
    """

    def _workspace_root(self) -> str:
        return str(self.config.get("workspace_root") or "").strip()

    def _sync_from_project_state(self) -> dict[str, Any] | None:
        workspace = self._workspace_root()
        if not workspace or not Path(workspace).expanduser().is_dir():
            return None
        state = load_project_state(workspace)
        if state is None:
            return None
        current = state.get("current") or {}
        roadmap = list(state.get("roadmap") or [])
        self.config["roadmap"] = roadmap
        self.config["phase"] = str(current.get("phase") or "")
        self.config["stage"] = str(current.get("stage") or "")
        return state

    def state(self) -> dict[str, Any]:
        project_state: dict[str, Any] | None = None
        project_state_error = ""
        try:
            state = self._sync_from_project_state()
            workspace = self._workspace_root()
            if workspace and Path(workspace).expanduser().is_dir():
                project_state = project_state_summary(workspace, state)
        except Exception as error:
            project_state_error = str(error)
        base = super().state()
        base["project_state"] = project_state or {
            "exists": False,
            "status": "unplanned",
            "current": None,
            "next": None,
            "completed": 0,
            "total": 0,
            "error": project_state_error,
        }
        if project_state_error:
            base["project_state"]["error"] = project_state_error
        return base

    def start_prompt(self) -> str:
        project = str(self.config.get("project_name") or "Untitled Project").strip()
        goal = str(self.config.get("project_goal") or "").strip()
        workspace = self._workspace_root() or "UNSET"
        return f'''AI WORKFLOW BRIDGE — PROJECT START

Project: {project}
Workspace: {workspace}

MASTER BRIEF
{goal}

For this FIRST response, PLAN ONLY. Do not emit AI_WORKFLOW commands and do not instruct the machine to mutate files.

Produce a concrete technical project plan that includes:
- interpretation of the goal and explicit out-of-scope items;
- proposed architecture and repository strategy;
- an authoritative ordered phase/stage roadmap with acceptance criteria;
- security/privacy/account boundaries;
- testing and verification strategy;
- decisions that genuinely require the human owner;
- start conditions, completion conditions, and rollback/recovery expectations.

The first stage of the first phase becomes the initial current position unless the project already has preserved local state.
The roadmap becomes the source of truth once execution is armed. Do not silently change it later.
AI Workflow Bridge will persist the approved roadmap under <workspace>/.ai-workflow/ and will own lifecycle updates to those files.
If the user changes direction later, AI Workflow Bridge will send a formal COURSE CHANGE request; analyze its impact before any new commands run.

Before READY_TO_ARM, include exactly one machine-readable roadmap:

<<<AI_WORKFLOW_ROADMAP>>>
{{
  "phases": [
    {{"id": "PHASE-ID", "title": "short title", "stages": ["STAGE-1", "STAGE-2"]}}
  ]
}}
<<<END_AI_WORKFLOW_ROADMAP>>>

Phase/stage identifiers must be stable, concise, and ordered.

End the response with exactly:
READY_TO_ARM
Do not put prose after READY_TO_ARM.
'''

    def controller_prompt(self) -> str:
        try:
            state = self._sync_from_project_state()
        except Exception as error:
            raise RuntimeError(f"Project-local roadmap state is invalid: {error}") from error
        base = super().controller_prompt()
        workspace = self._workspace_root()
        if not workspace or not Path(workspace).expanduser().is_dir():
            return base
        summary = project_state_summary(workspace, state)
        current = (summary.get("current") or {}).get("label") or "—"
        nxt = (summary.get("next") or {}).get("label") or "—"
        return base + f'''

PROJECT-LOCAL ROADMAP AUTHORITY
- Canonical roadmap file: {summary.get("roadmap_path")}
- Append-only history file: {summary.get("history_path")}
- Current local position: {current}
- Immediate next position: {nxt}
- Progress: {summary.get("completed", 0)} / {summary.get("total", 0)} stages completed
- These lifecycle files are owned by the native host. You may inspect them with read-only commands, but NEVER edit, replace, delete, move, or generate .ai-workflow/* yourself.
- Propose roadmap transitions only through the contract phase/stage fields. The native host validates and persists accepted transitions.
'''

    def process_assistant_response(self, payload: dict[str, Any]) -> None:
        prior_lifecycle = getattr(self, "lifecycle", "")
        super().process_assistant_response(payload)
        workspace = self._workspace_root()
        if not workspace or not Path(workspace).expanduser().is_dir():
            return
        try:
            if prior_lifecycle == "planning" and self.lifecycle == "ready_to_arm" and self.config.get("roadmap"):
                existing = load_project_state(workspace)
                if existing is None:
                    summary = initialize_project_state(
                        workspace,
                        list(self.config.get("roadmap") or []),
                        str(self.config.get("phase") or ""),
                        str(self.config.get("stage") or ""),
                        reason="approved planning response",
                    )
                else:
                    summary = project_state_summary(workspace, existing)
                current = summary.get("current") or {}
                self.config = save_config({
                    "roadmap": list((load_project_state(workspace) or {}).get("roadmap") or self.config.get("roadmap") or []),
                    "phase": str(current.get("phase") or ""),
                    "stage": str(current.get("stage") or ""),
                })
                self.emit_event({
                    "kind": "info",
                    "badge": "MAP",
                    "text": f"Project-local roadmap initialized at {summary.get('roadmap_path')}",
                })
                self.emit({"kind": "state", "state": self.state()})
            elif prior_lifecycle == "finishing" and self.lifecycle == "complete":
                complete_project_state(workspace)
                self.emit({"kind": "state", "state": self.state()})
        except Exception as error:
            self.paused = True
            self.status = "project_state_error"
            self.current_step = "Project-local roadmap state update failed"
            self.emit_event({
                "kind": "error",
                "text": f"Project-local roadmap state could not be updated: {error}. Automation paused to avoid state drift.",
            })

    def _roadmap_positions(self) -> list[tuple[str, str]]:
        try:
            state = self._sync_from_project_state()
            if state is not None:
                out: list[tuple[str, str]] = []
                for phase in state.get("roadmap") or []:
                    phase_id = str((phase or {}).get("id") or "").strip()
                    stages = [str(x).strip() for x in ((phase or {}).get("stages") or []) if str(x).strip()]
                    if phase_id and stages:
                        out.extend((phase_id, stage) for stage in stages)
                    elif phase_id:
                        out.append((phase_id, ""))
                return out
        except Exception:
            pass
        return super()._roadmap_positions()

    def _maybe_apply_canonical_transition(self, contract) -> bool:
        workspace = self._workspace_root()
        if workspace and Path(workspace).expanduser().is_dir():
            state = load_project_state(workspace)
            if state is not None:
                current = state.get("current") or {}
                current_pair = (str(current.get("phase") or ""), str(current.get("stage") or ""))
                target = (str(contract.phase or "").strip(), str(contract.stage or "").strip())
                if target == current_pair:
                    self.config["phase"], self.config["stage"] = current_pair
                    return False
                summary = advance_project_state(workspace, target[0], target[1])
                next_current = summary.get("current") or {}
                self.config = save_config({
                    "phase": str(next_current.get("phase") or ""),
                    "stage": str(next_current.get("stage") or ""),
                    "roadmap": list((load_project_state(workspace) or {}).get("roadmap") or []),
                })
                self.emit_event({
                    "kind": "step",
                    "badge": "NEXT!",
                    "status": "validating",
                    "text": f"Advanced project-local roadmap: {current_pair[0]}/{current_pair[1] or '-'} → {target[0]}/{target[1] or '-'}",
                })
                self.emit({"kind": "state", "state": self.state()})
                return True
        return super()._maybe_apply_canonical_transition(contract)

    def resolve_approval(self, approval_id: str, decision: str) -> None:
        pending = self.pending.get(approval_id) or {}
        continuation = pending.get("continuation") or {}
        if decision == "approve" and continuation.get("kind") == "course_change":
            review = continuation.get("review") or {}
            workspace = self._workspace_root()
            if workspace and Path(workspace).expanduser().is_dir():
                replacement = review.get("replacement_roadmap") or None
                apply_course_change(
                    workspace,
                    replacement,
                    str(review.get("proposed_phase") or ""),
                    str(review.get("proposed_stage") or ""),
                    summary=str(review.get("summary") or "approved course change"),
                )
                state = load_project_state(workspace) or {}
                current = state.get("current") or {}
                self.config = save_config({
                    "roadmap": list(state.get("roadmap") or []),
                    "phase": str(current.get("phase") or ""),
                    "stage": str(current.get("stage") or ""),
                })
        super().resolve_approval(approval_id, decision)
        if decision == "approve" and continuation.get("kind") == "course_change":
            self.emit({"kind": "state", "state": self.state()})

    @staticmethod
    def _control_path_reference(command: str) -> bool:
        text = str(command or "").lower()
        return ".ai-workflow" in text or "roadmap.md" in text or "history.md" in text

    @staticmethod
    def _control_read_only(command: str) -> bool:
        normalized = " ".join(str(command or "").strip().split()).lower()
        return normalized.startswith(("cat ", "head ", "tail ", "grep ", "rg ", "ls ", "find ", "git diff", "git status"))

    def _execute_contract(self, contract, payload: dict[str, Any] | None = None) -> None:
        for spec in contract.commands:
            if self._control_path_reference(spec.cmd) and not self._control_read_only(spec.cmd):
                self.status = "blocked"
                self.emit_event({
                    "kind": "error",
                    "text": f"Blocked command: {spec.cmd}\n.ai-workflow lifecycle documents are native-host owned and cannot be mutated by LLM commands.",
                })
                self._send_result_to_chatgpt(
                    "Bridge policy BLOCKED direct mutation of .ai-workflow lifecycle documents. "
                    "Do not edit ROADMAP.md or HISTORY.md yourself. Propose the desired transition in the AI_WORKFLOW contract instead."
                )
                return
        super()._execute_contract(contract, payload)
