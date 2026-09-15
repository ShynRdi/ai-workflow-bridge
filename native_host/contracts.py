from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

START = "<<<AI_WORKFLOW>>>"
END = "<<<END_AI_WORKFLOW>>>"
VALID_RISK_LEVELS = {"R0", "R1", "R2", "R3", "R4"}
RISK_DIMENSIONS = {
    "filesystem", "network", "credentials", "database", "git_remote", "system",
    "production", "irreversibility", "data_exfiltration",
}
MAX_COMMANDS_PER_CONTRACT = 100


@dataclass
class RiskAssessment:
    level: str
    confidence: float | None = None
    factors: list[str] = field(default_factory=list)
    dimensions: dict[str, int] = field(default_factory=dict)
    reversible: bool | None = None
    recommended_action: str = ""


@dataclass
class CommandSpec:
    cmd: str
    purpose: str = ""
    cwd: str = "."
    risk_assessment: RiskAssessment | None = None


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


def _parse_risk_assessment(value: Any) -> RiskAssessment | None:
    if not isinstance(value, dict):
        return None
    level = str(value.get("level") or "").upper().strip()
    if level not in VALID_RISK_LEVELS:
        return None

    confidence: float | None = None
    raw_confidence = value.get("confidence")
    if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
        confidence = max(0.0, min(1.0, float(raw_confidence)))

    factors = [str(x).strip() for x in (value.get("factors") or []) if str(x).strip()][:12]
    dimensions: dict[str, int] = {}
    raw_dimensions = value.get("dimensions")
    for key, raw in raw_dimensions.items() if isinstance(raw_dimensions, dict) else []:
        name = str(key)
        if name not in RISK_DIMENSIONS:
            continue
        try:
            score = int(raw)
        except (TypeError, ValueError):
            continue
        dimensions[name] = max(0, min(3, score))

    reversible = value.get("reversible") if isinstance(value.get("reversible"), bool) else None
    return RiskAssessment(
        level=level,
        confidence=confidence,
        factors=factors,
        dimensions=dimensions,
        reversible=reversible,
        recommended_action=str(value.get("recommended_action") or "").strip(),
    )


def extract_contract(text: str) -> WorkflowContract | None:
    if START not in text or END not in text:
        return None
    start = text.rfind(START) + len(START)
    end = text.find(END, start)
    if end < start:
        return None
    raw = text[start:end].strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    data = json.loads(raw)
    if int(data.get("version", 0)) != 1:
        raise ValueError("Unsupported AI_WORKFLOW contract version")

    phase = str(data.get("phase") or "").strip()
    stage = str(data.get("stage") or "").strip()
    if not phase or not stage:
        raise ValueError("AI_WORKFLOW contracts must include non-empty phase and stage")

    raw_commands = data.get("commands") or []
    if not isinstance(raw_commands, list):
        raise ValueError("commands must be a list")
    if len(raw_commands) > MAX_COMMANDS_PER_CONTRACT:
        raise ValueError(f"commands exceeds maximum of {MAX_COMMANDS_PER_CONTRACT}")

    commands: list[CommandSpec] = []
    for item in raw_commands:
        if isinstance(item, str):
            cmd = item.strip()
            if cmd:
                commands.append(CommandSpec(cmd=cmd))
        elif isinstance(item, dict) and str(item.get("cmd") or "").strip():
            commands.append(
                CommandSpec(
                    cmd=str(item["cmd"]).strip(),
                    purpose=str(item.get("purpose") or ""),
                    cwd=str(item.get("cwd") or "."),
                    risk_assessment=_parse_risk_assessment(item.get("risk_assessment")),
                )
            )

    downloads = data.get("downloads") or []
    if not isinstance(downloads, list):
        raise ValueError("downloads must be a list")

    return WorkflowContract(
        version=1,
        phase=phase,
        stage=stage,
        summary=str(data.get("summary") or ""),
        decision_required=bool(data.get("decision_required", False)),
        decision_reason=str(data.get("decision_reason") or ""),
        commands=commands,
        success_conditions=[str(x) for x in (data.get("success_conditions") or [])],
        next_step=str(data.get("next_step") or ""),
        downloads=list(downloads),
    )
