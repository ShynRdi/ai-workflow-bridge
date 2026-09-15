from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

START = "<<<AI_WORKFLOW>>>"
END = "<<<END_AI_WORKFLOW>>>"

@dataclass
class CommandSpec:
    cmd: str
    purpose: str = ""
    cwd: str = "."

@dataclass
class WorkflowContract:
    version: int
    phase: str
    stage: str
    summary: str
    decision_required: bool = False
    decision_reason: str = ""
    commands: list[CommandSpec] = field(default_factory=list)
    success_conditions: list[str] = field(default_factory=list)
    next_step: str = ""
    downloads: list[dict[str, Any]] = field(default_factory=list)

def extract_contract(text: str) -> WorkflowContract | None:
    if START not in text or END not in text: return None
    start = text.rfind(START) + len(START); end = text.find(END, start)
    if end < start: return None
    raw = text[start:end].strip(); raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip(); data = json.loads(raw)
    if int(data.get("version", 0)) != 1: raise ValueError("Unsupported AI_WORKFLOW contract version")
    commands: list[CommandSpec] = []
    for item in data.get("commands") or []:
        if isinstance(item, str): commands.append(CommandSpec(cmd=item))
        elif isinstance(item, dict) and item.get("cmd"): commands.append(CommandSpec(cmd=str(item["cmd"]), purpose=str(item.get("purpose") or ""), cwd=str(item.get("cwd") or ".")))
    return WorkflowContract(version=1, phase=str(data.get("phase") or ""), stage=str(data.get("stage") or ""), summary=str(data.get("summary") or ""), decision_required=bool(data.get("decision_required", False)), decision_reason=str(data.get("decision_reason") or ""), commands=commands, success_conditions=[str(x) for x in (data.get("success_conditions") or [])], next_step=str(data.get("next_step") or ""), downloads=list(data.get("downloads") or []))
