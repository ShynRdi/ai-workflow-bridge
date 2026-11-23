from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from policy_profiles import DEFAULT_PROFILE, PROFILES, public_profiles, validate_profile
from project_state import (
    CONTROL_DIR,
    _append_history,
    _atomic_write,
    _ensure_regular_or_missing,
    control_paths,
    now_iso,
)


POLICY_FILE = "POLICY.json"
POLICY_VERSION = 1
MAX_POLICY_BYTES = 8192


def _policy_path(workspace_root: str) -> Path:
    control, _, _ = control_paths(workspace_root)
    path = control / POLICY_FILE
    _ensure_regular_or_missing(path, POLICY_FILE)
    return path


def _legacy_revision(workspace_root: str) -> str:
    root = str(Path(workspace_root).expanduser().resolve())
    return "legacy-balanced-" + hashlib.sha256(root.encode("utf-8")).hexdigest()[:24]


def _legacy_state(workspace_root: str) -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "profile": DEFAULT_PROFILE,
        "revision": _legacy_revision(workspace_root),
        "updated_at": "",
        "persisted": False,
    }


def _validate_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("POLICY.json must contain an object")
    if value.get("version") != POLICY_VERSION:
        raise ValueError("POLICY.json has an unsupported version")
    profile = validate_profile(value.get("profile"))
    revision = str(value.get("revision") or "").strip()
    updated_at = str(value.get("updated_at") or "").strip()
    if not revision or len(revision) > 128 or not updated_at or len(updated_at) > 128:
        raise ValueError("POLICY.json is missing valid revision or timestamp")
    return {
        "version": POLICY_VERSION,
        "profile": profile,
        "revision": revision,
        "updated_at": updated_at,
        "persisted": True,
    }


def load_policy_state(workspace_root: str) -> dict[str, Any]:
    path = _policy_path(workspace_root)
    if not path.exists():
        return _legacy_state(workspace_root)
    # _safe_read_text is deliberately not used here: retaining a tiny bounded
    # no-follow reader avoids accepting corrupt oversized state as valid.
    import os
    import stat

    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("POLICY.json must be a regular file")
        raw = os.read(fd, MAX_POLICY_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MAX_POLICY_BYTES:
        raise ValueError("POLICY.json exceeds the maximum allowed size")
    try:
        return _validate_state(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("POLICY.json is invalid") from error


def ensure_policy_state(workspace_root: str) -> dict[str, Any]:
    current = load_policy_state(workspace_root)
    if current["persisted"]:
        return current
    state = {
        "version": POLICY_VERSION,
        "profile": DEFAULT_PROFILE,
        "revision": uuid.uuid4().hex,
        "updated_at": now_iso(),
    }
    _atomic_write(_policy_path(workspace_root), json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return _validate_state(state)


def policy_summary(workspace_root: str) -> dict[str, Any]:
    state = load_policy_state(workspace_root)
    profile = PROFILES[state["profile"]]
    return {
        **state,
        "label": profile.label,
        "description": profile.description,
        "warning": profile.warning,
        "profiles": public_profiles(),
        "path": str(_policy_path(workspace_root)),
    }


def change_policy_profile(
    workspace_root: str,
    desired_profile: str,
    expected_revision: str,
) -> dict[str, Any]:
    current = load_policy_state(workspace_root)
    if str(expected_revision or "") != current["revision"]:
        raise ValueError("Policy state is stale; refresh before changing profile")
    desired = validate_profile(desired_profile)
    if desired == current["profile"]:
        return policy_summary(workspace_root)
    state = {
        "version": POLICY_VERSION,
        "profile": desired,
        "revision": uuid.uuid4().hex,
        "updated_at": now_iso(),
    }
    _atomic_write(_policy_path(workspace_root), json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    _, _, history_path = control_paths(workspace_root)
    _append_history(history_path, [
        f"Security policy profile changed: {current['profile']} -> {desired}.",
        f"Policy revision: {state['revision'][:12]}.",
        "Source: explicit human Mission Control action.",
    ])
    return policy_summary(workspace_root)
