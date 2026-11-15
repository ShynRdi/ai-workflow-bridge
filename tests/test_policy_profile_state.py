from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))

from project_policy import change_policy_profile, ensure_policy_state, load_policy_state, policy_summary


def test_missing_legacy_policy_resolves_to_balanced_without_writing(tmp_path: Path):
    state = load_policy_state(str(tmp_path))
    assert state["profile"] == "balanced"
    assert state["persisted"] is False
    assert not (tmp_path / ".ai-workflow" / "POLICY.json").exists()


def test_ensure_and_compare_and_set_profile_state(tmp_path: Path):
    first = ensure_policy_state(str(tmp_path))
    assert first["profile"] == "balanced"
    assert first["persisted"] is True
    changed = change_policy_profile(str(tmp_path), "strict", first["revision"])
    assert changed["profile"] == "strict"
    assert changed["revision"] != first["revision"]
    with pytest.raises(ValueError, match="stale"):
        change_policy_profile(str(tmp_path), "balanced", first["revision"])
    assert policy_summary(str(tmp_path))["profile"] == "strict"
    history = (tmp_path / ".ai-workflow" / "HISTORY.md").read_text(encoding="utf-8")
    assert "balanced -> strict" in history
    assert "explicit human Mission Control action" in history


def test_policy_state_rejects_symlink_and_corruption(tmp_path: Path):
    control = tmp_path / ".ai-workflow"
    control.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    (control / "POLICY.json").symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        load_policy_state(str(tmp_path))

    (control / "POLICY.json").unlink()
    (control / "POLICY.json").write_text(json.dumps({"profile": "unsafe"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy_state(str(tmp_path))


def test_invalid_desired_profile_changes_nothing(tmp_path: Path):
    state = ensure_policy_state(str(tmp_path))
    with pytest.raises(ValueError, match="Unknown"):
        change_policy_profile(str(tmp_path), "unsafe", state["revision"])
    assert load_policy_state(str(tmp_path))["revision"] == state["revision"]
