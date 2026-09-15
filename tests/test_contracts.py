import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))
from contracts import extract_contract


def test_extract_contract():
    text = """Human text\n<<<AI_WORKFLOW>>>\n```json\n{"version":1,"phase":"19","stage":"C","summary":"verify","commands":[{"cmd":"git status --short"}]}\n```\n<<<END_AI_WORKFLOW>>>"""
    contract = extract_contract(text)
    assert contract is not None
    assert contract.phase == "19"
    assert contract.stage == "C"
    assert contract.commands[0].cmd == "git status --short"


@pytest.mark.parametrize("phase,stage", [("", "S"), ("P", ""), ("", "")])
def test_contract_rejects_empty_phase_or_stage(phase, stage):
    text = f'''<<<AI_WORKFLOW>>>
{{"version":1,"phase":"{phase}","stage":"{stage}","summary":"x","commands":[{{"cmd":"git status"}}]}}
<<<END_AI_WORKFLOW>>>'''
    with pytest.raises(ValueError, match="phase and stage"):
        extract_contract(text)


def test_contract_caps_command_count():
    commands = ",".join('{"cmd":"git status"}' for _ in range(101))
    text = f'''<<<AI_WORKFLOW>>>
{{"version":1,"phase":"P","stage":"S","summary":"x","commands":[{commands}]}}
<<<END_AI_WORKFLOW>>>'''
    with pytest.raises(ValueError, match="maximum"):
        extract_contract(text)
