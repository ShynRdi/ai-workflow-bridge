"""Canonical, native-owned per-workspace execution configuration."""
from __future__ import annotations

import hashlib
import fcntl
import json
import math
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_state import _atomic_write, control_paths, now_iso

EXECUTION_FILE = "EXECUTION.json"
EXECUTION_LOCK_FILE = "EXECUTION.lock"
EXECUTION_VERSION = 1
MAX_EXECUTION_BYTES = 8192
DEFAULT_CONTAINER = {
    "runtime": "docker",
    "image": "",
    "network": "none",
    "cpus": 2.0,
    "memory_mb": 2048,
    "pids_limit": 256,
}


def _path(workspace_root: str) -> Path:
    control, _, _ = control_paths(workspace_root)
    path = control / EXECUTION_FILE
    if path.is_symlink():
        raise ValueError("EXECUTION.json must not be a symbolic link")
    if path.exists() and not path.is_file():
        raise ValueError("EXECUTION.json must be a regular file")
    return path


def _legacy_revision(workspace_root: str) -> str:
    root = str(Path(workspace_root).expanduser().resolve())
    return "legacy-host-" + hashlib.sha256(root.encode("utf-8")).hexdigest()[:32]


def _number(value: Any, label: str, minimum: float, maximum: float, integer: bool = False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ValueError(f"{label} is outside its allowed range")
    if integer and not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return int(value) if integer else float(value)


_IMAGE_RE = re.compile(
    r"^(?:(?:[a-z0-9.-]+(?::[0-9]{1,5})?/)?"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[a-f0-9]{64})?$"
)


def validate_image(image: Any) -> str:
    if not isinstance(image, str) or len(image) > 255 or not _IMAGE_RE.fullmatch(image):
        raise ValueError("Container image name is invalid")
    # Reject options, whitespace, path traversal, and empty reference components.
    if image.startswith("-") or ".." in image.split("/") or "//" in image or "@@" in image:
        raise ValueError("Container image name is invalid")
    return image


def _validate(value: Any) -> dict[str, Any]:
    version = value.get("version") if isinstance(value, dict) else None
    if not isinstance(value, dict) or not isinstance(version, int) or isinstance(version, bool) or version != EXECUTION_VERSION:
        raise ValueError("EXECUTION.json has an unsupported or invalid version")
    mode = value.get("mode")
    if mode not in {"host", "container"}:
        raise ValueError("EXECUTION.json mode must be host or container")
    revision = value.get("revision")
    updated_at = value.get("updated_at")
    if not isinstance(revision, str) or not re.fullmatch(r"(?:[a-f0-9]{32}|legacy-host-[a-f0-9]{32})", revision):
        raise ValueError("EXECUTION.json revision is invalid")
    try:
        timestamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00")) if isinstance(updated_at, str) else None
    except ValueError:
        timestamp = None
    if timestamp is None or timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError("EXECUTION.json timestamp is invalid")
    raw = value.get("container")
    if not isinstance(raw, dict):
        raise ValueError("EXECUTION.json container settings must be an object")
    if raw.get("runtime") != "docker" or raw.get("network") != "none":
        raise ValueError("Only Docker with network none is supported")
    image = raw.get("image")
    if mode == "container":
        image = validate_image(image)
    elif image:
        image = validate_image(image)
    else:
        image = ""
    return {
        "version": EXECUTION_VERSION,
        "mode": mode,
        "revision": revision,
        "updated_at": updated_at,
        "container": {
            "runtime": "docker", "image": image, "network": "none",
            "cpus": _number(raw.get("cpus"), "cpus", 0.25, 64),
            "memory_mb": _number(raw.get("memory_mb"), "memory_mb", 128, 131072, True),
            "pids_limit": _number(raw.get("pids_limit"), "pids_limit", 32, 4096, True),
        },
        "persisted": True,
    }


def load_execution_state(workspace_root: str) -> dict[str, Any]:
    path = _path(workspace_root)
    if not path.exists():
        return {
            "version": EXECUTION_VERSION, "mode": "host",
            "revision": _legacy_revision(workspace_root), "updated_at": "",
            "container": dict(DEFAULT_CONTAINER), "persisted": False,
        }
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("EXECUTION.json must be a regular file")
        raw = os.read(fd, MAX_EXECUTION_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MAX_EXECUTION_BYTES:
        raise ValueError("EXECUTION.json exceeds the maximum allowed size")
    try:
        return _validate(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("EXECUTION.json is invalid") from error


def update_execution_state(
    workspace_root: str, *, mode: str, expected_revision: str,
    image: str = "", cpus: float = 2.0, memory_mb: int = 2048,
    pids_limit: int = 256,
) -> dict[str, Any]:
    control, _, _ = control_paths(workspace_root)
    control.mkdir(parents=True, exist_ok=True)
    lock_path = control / EXECUTION_LOCK_FILE
    if lock_path.is_symlink():
        raise ValueError("EXECUTION.lock must not be a symbolic link")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("EXECUTION.lock must be a regular file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        # The lock spans the full read/compare/write transaction. Readers need
        # no lock because EXECUTION.json is replaced atomically.
        current = load_execution_state(workspace_root)
        if not isinstance(expected_revision, str) or expected_revision != current["revision"]:
            raise ValueError("Execution state is stale; refresh before changing it")
        state = _validate({
            "version": EXECUTION_VERSION, "mode": mode, "revision": uuid.uuid4().hex,
            "updated_at": now_iso(),
            "container": {
                "runtime": "docker", "image": image, "network": "none",
                "cpus": cpus, "memory_mb": memory_mb, "pids_limit": pids_limit,
            },
        })
        path = _path(workspace_root)
        _atomic_write(path, json.dumps({k: v for k, v in state.items() if k != "persisted"}, indent=2) + "\n")
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    state["persisted"] = True
    return state
