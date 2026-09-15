import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))
from contracts import extract_contract


def test_extract_contract():
    text = """Human text\n<<<AI_WORKFLOW>>>\n```json\n{"version":1,"phase":"19","stage":"C","summary":"verify","commands":[{"cmd":"git status --short"}]}\n```\n<<<END_AI_WORKFLOW>>>"""
    contract = extract_contract(text)
    assert contract is not None
    assert contract.phase == "19"
    assert contract.stage == "C"
    assert contract.commands[0].cmd == "git status --short"
