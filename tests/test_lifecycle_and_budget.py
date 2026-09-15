from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; HOST=ROOT/"native_host"
if str(HOST) not in sys.path: sys.path.insert(0,str(HOST))
from orchestrator import Orchestrator
from safety import RunBudget


def test_change_review_parser():
    text='''\n<<<AI_WORKFLOW_CHANGE_REVIEW>>>\n{"summary":"pivot","impact":"small","recommended":"yes","proposed_phase":"P1","proposed_stage":"S2","roadmap_changes":["replace queue"]}\n<<<END_AI_WORKFLOW_CHANGE_REVIEW>>>\n'''
    review=Orchestrator.extract_change_review(text); assert review["proposed_phase"]=="P1"; assert review["roadmap_changes"]==["replace queue"]


def test_budget_blocks_after_session_limit():
    budget=RunBudget(); config={"max_turns_per_session":1,"max_turns_per_hour":10,"max_runtime_minutes":90,"min_turn_interval_seconds":3}
    assert budget.decision(config)["allowed"] is True; budget.record_send(); decision=budget.decision(config); assert decision["allowed"] is False; assert "session AI-turn budget" in decision["reason"]


def test_manual_provider_guard_has_no_automatic_retry():
    budget=RunBudget(); budget.block("rate limit")
    decision=budget.decision({"max_turns_per_session":25,"max_turns_per_hour":20,"max_runtime_minutes":90,"min_turn_interval_seconds":8})
    assert decision["allowed"] is False; assert decision["hard"] is True
