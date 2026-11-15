from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))

from policy import classify, merge_risk
from policy_profiles import (
    BALANCED,
    ISOLATED_DEVELOPMENT,
    STRICT,
    validate_profile,
)


def test_balanced_preserves_baseline_decisions(tmp_path: Path):
    root = str(tmp_path)
    for command, expected in [
        ("git status --short", "low"),
        ("python3 -m pytest -q", "approval"),
        ("git push origin main", "approval"),
        ("cat /etc/hosts", "approval"),
    ]:
        assert classify(command, root).level == expected
        assert classify(command, root, BALANCED).level == expected


def test_strict_is_never_less_restrictive_and_blocks_boundaries(tmp_path: Path):
    root = str(tmp_path)
    for command in ["git status --short", "python3 -m pytest -q", "git push origin main", "cat /etc/hosts"]:
        baseline = classify(command, root, BALANCED)
        strict = classify(command, root, STRICT)
        rank = {"low": 0, "approval": 1, "blocked": 2}
        assert rank[strict.level] >= rank[baseline.level]
    assert classify("git push origin main", root, STRICT).level == "blocked"
    assert classify("cat /etc/hosts", root, STRICT).level == "blocked"


@pytest.mark.parametrize("command", [
    "sudo true", "rm -rf /tmp/nope", "git reset --hard HEAD", "cat ~/.ssh/id_rsa",
])
def test_immutable_blocks_apply_to_every_profile(command: str, tmp_path: Path):
    for profile in [BALANCED, STRICT, ISOLATED_DEVELOPMENT]:
        decision = classify(command, str(tmp_path), profile)
        assert decision.level == "blocked"
        assert decision.immutable_block is True


def test_isolated_development_only_relaxes_path_proven_setup(tmp_path: Path):
    assert classify("mkdir -p build/cache", str(tmp_path), BALANCED).level == "approval"
    allowed = classify("mkdir -p build/cache", str(tmp_path), ISOLATED_DEVELOPMENT)
    assert allowed.level == "low"
    assert allowed.risk_level == "R1"
    assert classify("touch .ai-workflow/POLICY.json", str(tmp_path), ISOLATED_DEVELOPMENT).level == "approval"
    for command in [
        "python3 app.py", "npm test", "curl https://example.invalid", "git push origin main", "ssh host true",
    ]:
        assert classify(command, str(tmp_path), ISOLATED_DEVELOPMENT).level != "low"


def test_invalid_profile_fails_closed():
    with pytest.raises(ValueError, match="Unknown security policy profile"):
        validate_profile("unsafe")


def test_llm_can_escalate_but_cannot_downgrade_profile_decision(tmp_path: Path):
    local = classify("git push origin main", str(tmp_path), STRICT)
    assert merge_risk(local, {"level": "R0"}).level == "blocked"
    low = classify("git status --short", str(tmp_path), BALANCED)
    assert merge_risk(low, {"level": "R4"}).level == "blocked"
