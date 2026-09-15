import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native_host"))

from contracts import extract_contract
from policy import PolicyDecision, merge_risk


def test_contract_parses_llm_risk_assessment():
    text = '''<<<AI_WORKFLOW>>>
{"version":1,"phase":"P","stage":"S","summary":"x","commands":[{"cmd":"git status --short","risk_assessment":{"level":"R1","confidence":0.91,"factors":["verification"],"dimensions":{"filesystem":1,"network":0},"reversible":true,"recommended_action":"auto"}}]}
<<<END_AI_WORKFLOW>>>'''
    contract = extract_contract(text)
    assessment = contract.commands[0].risk_assessment
    assert assessment is not None
    assert assessment.level == "R1"
    assert assessment.confidence == 0.91
    assert assessment.dimensions["filesystem"] == 1


def test_invalid_llm_risk_is_ignored_fail_safe():
    text = '''<<<AI_WORKFLOW>>>
{"version":1,"phase":"P","stage":"S","summary":"x","commands":[{"cmd":"git status --short","risk_assessment":{"level":"SAFE"}}]}
<<<END_AI_WORKFLOW>>>'''
    contract = extract_contract(text)
    assert contract.commands[0].risk_assessment is None


def test_llm_can_escalate_but_not_downgrade_local_risk():
    local = PolicyDecision("approval", "remote publish", "R3")
    downgraded = merge_risk(local, {"level": "R0", "factors": ["looks safe"]})
    assert downgraded.risk_level == "R3"
    assert downgraded.level == "approval"
    assert not downgraded.escalated_by_llm

    low_local = PolicyDecision("low", "inspection", "R0")
    escalated = merge_risk(low_local, {"level": "R3", "factors": ["context says production"]})
    assert escalated.risk_level == "R3"
    assert escalated.level == "approval"
    assert escalated.escalated_by_llm


def test_llm_r4_blocks_even_when_local_policy_is_low():
    local = PolicyDecision("low", "inspection", "R0")
    effective = merge_risk(local, {"level": "R4", "factors": ["credential exposure"]})
    assert effective.level == "blocked"
    assert effective.risk_level == "R4"


def test_missing_llm_assessment_never_weakens_local_policy():
    local = PolicyDecision("approval", "unknown command", "R2")
    effective = merge_risk(local, None)
    assert effective.level == "approval"
    assert effective.risk_level == "R2"
    assert effective.llm_risk_level is None
