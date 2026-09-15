from orchestrator_core import CoreMixin
from orchestrator_messages import MessageMixin
from orchestrator_response import ResponseMixin
from orchestrator_approval import ApprovalMixin
from orchestrator_risk import RiskAwareExecutionMixin
from orchestrator_execution import ExecutionMixin
from orchestrator_reporting import ReportingMixin


class Orchestrator(CoreMixin, MessageMixin, ResponseMixin, ApprovalMixin, RiskAwareExecutionMixin, ExecutionMixin, ReportingMixin):
    def controller_prompt(self) -> str:
        base = CoreMixin.controller_prompt(self)
        marker = "9. Every response that advances automation MUST end with exactly one contract:"
        risk_rules = '''9. For EVERY commands[] item, include a semantic risk_assessment. This is advisory only: the Bridge independently computes local policy risk and the LLM assessment can only raise the effective risk, never lower or bypass local policy. Use this rubric:\n- R0: read-only inspection with no meaningful side effects\n- R1: bounded local verification/build activity with minimal side effects\n- R2: reversible workspace mutation or dependency change\n- R3: sensitive/external/remote/production-significant operation\n- R4: destructive, credential-exposing, security-bypassing, or otherwise forbidden operation\nIf uncertain, choose the higher risk. Include confidence 0..1, concise factors, reversible, recommended_action, and dimensions scored 0..3 for filesystem, network, credentials, database, git_remote, system, production, irreversibility, and data_exfiltration. Do not claim that your assessment authorizes execution.'''
        replacement = risk_rules + "\n\n10. Every response that advances automation MUST end with exactly one contract:"
        base = base.replace(marker, replacement)
        base = base.replace(
            '"commands": [{"cmd": "git status --short", "cwd": ".", "purpose": "inspect repo state"}],',
            '"commands": [{"cmd": "git status --short", "cwd": ".", "purpose": "inspect repo state", "risk_assessment": {"level": "R0", "confidence": 0.99, "factors": ["read-only repository inspection"], "dimensions": {"filesystem": 0, "network": 0, "credentials": 0, "database": 0, "git_remote": 0, "system": 0, "production": 0, "irreversibility": 0, "data_exfiltration": 0}, "reversible": true, "recommended_action": "auto"}}],'
        )
        base = base.replace("10. After every terminal report", "11. After every terminal report")
        base = base.replace("11. Project-wide completion", "12. Project-wide completion")
        return base
