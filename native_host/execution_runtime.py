"""Durable identity for a possibly orphaned Bridge Docker execution."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import re
import stat
import uuid
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_state import control_paths, now_iso

RUNTIME_FILE = "EXECUTION_RUNTIME.json"
LOCK_FILE = "EXECUTION_RUNTIME.lock"
COORDINATION_LOCK_FILE = "EXECUTION_COORDINATION.lock"
MAX_BYTES = 4096


def workspace_identity(root: str | Path) -> str:
    return hashlib.sha256(str(Path(root).expanduser().resolve()).encode()).hexdigest()


def _paths(root: str):
    control, _, _ = control_paths(str(root))
    return control / RUNTIME_FILE, control / LOCK_FILE


def _lock_file(root: str | Path, name: str) -> int:
    control, _, _ = control_paths(str(root))
    control.mkdir(parents=True, exist_ok=True)
    path = control / name
    if path.is_symlink():
        raise ValueError(f"{name} must not be a symbolic link")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError(f"{name} must be a regular file")
    return fd


@contextmanager
def coordination_lock(root: str | Path):
    """Lock order is always coordination, then runtime journal."""
    fd = _lock_file(root, COORDINATION_LOCK_FILE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def runtime_lock(root: str | Path):
    fd = _lock_file(root, LOCK_FILE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _durable_runtime_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Execution runtime journal must not be a symbolic link")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _validate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "version", "execution_id", "revision", "container_name", "workspace_identity",
        "mode", "runtime", "created_at", "state",
    }:
        raise ValueError("Execution runtime journal schema is invalid")
    if value["version"] != 1 or isinstance(value["version"], bool):
        raise ValueError("Execution runtime journal version is unsupported")
    for key in ("execution_id", "revision"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{32}", value[key]):
            raise ValueError("Execution runtime journal identity is invalid")
    if value["container_name"] != "aiwb-" + value["execution_id"]:
        raise ValueError("Execution runtime journal container name is invalid")
    if not isinstance(value["workspace_identity"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["workspace_identity"]):
        raise ValueError("Execution runtime journal workspace identity is invalid")
    if value["mode"] != "container" or value["runtime"] != "docker" or value["state"] not in {"starting", "running", "cleanup_required"}:
        raise ValueError("Execution runtime journal values are invalid")
    if not isinstance(value["created_at"], str) or len(value["created_at"]) > 64:
        raise ValueError("Execution runtime journal timestamp is invalid")
    try:
        timestamp = datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Execution runtime journal timestamp is invalid") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError("Execution runtime journal timestamp is invalid")
    return dict(value)


def load_runtime_record(root: str | Path) -> dict[str, Any] | None:
    path, _ = _paths(root)
    if path.is_symlink():
        raise ValueError("Execution runtime journal must not be a symbolic link")
    if not path.exists():
        return None
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Execution runtime journal must be a regular file")
        raw = os.read(fd, MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MAX_BYTES:
        raise ValueError("Execution runtime journal exceeds the maximum allowed size")
    try:
        return _validate(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Execution runtime journal is invalid") from error


def create_runtime_record(root: str | Path) -> dict[str, Any]:
    execution_id = uuid.uuid4().hex
    return {
        "version": 1, "execution_id": execution_id, "revision": uuid.uuid4().hex,
        "container_name": "aiwb-" + execution_id, "workspace_identity": workspace_identity(root),
        "mode": "container", "runtime": "docker", "created_at": now_iso(), "state": "starting",
    }


def write_runtime_record(root: str | Path, record: dict[str, Any], *, expected_revision: str | None = None) -> dict[str, Any]:
    path, lock_path = _paths(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with runtime_lock(root):
        current = load_runtime_record(root)
        if expected_revision is None and current is not None:
            raise ValueError("Unresolved execution runtime recovery exists")
        if expected_revision is not None and (current is None or current["revision"] != expected_revision):
            raise ValueError("Execution runtime recovery identity is stale")
        value = _validate(record)
        _durable_runtime_write(path, json.dumps(value, indent=2) + "\n")
        return value


def clear_runtime_record(root: str | Path, expected_revision: str) -> None:
    with coordination_lock(root):
        with runtime_lock(root):
            current = load_runtime_record(root)
            if current is None or current["revision"] != expected_revision:
                raise ValueError("Execution runtime recovery identity is stale")
            _clear_locked(root, current)


def inspect_container_record(root: str | Path, record: dict[str, Any]) -> dict[str, Any]:
    """Inspect exactly the journal's name and return immutable Docker identity."""
    expected = {"ai-workflow-bridge.managed": "true", "ai-workflow-bridge.execution": record["execution_id"],
                "ai-workflow-bridge.workspace": record["workspace_identity"]}
    result: dict[str, Any] = {"container_id": None, "container_name": record["container_name"],
                              "labels": {}, "ownership_status": "unavailable", "inspection": "unavailable"}
    if record["workspace_identity"] != workspace_identity(root):
        result.update(ownership_status="workspace_mismatch", inspection="invalid")
        return result
    docker = shutil.which("docker")
    if not docker:
        return result
    try:
        from runner import _run_process, sanitized_environment
        code, _out, _err, timed_out = _run_process(
            [docker, "info", "--format", "{{.ServerVersion}}"], cwd=str(root),
            env=sanitized_environment(), timeout=8)
        if code != 0 or timed_out:
            return result
        code, out, err, timed_out = _run_process(
            [docker, "inspect", "--format", "{{json .}}", record["container_name"]],
            cwd=str(root), env=sanitized_environment(), timeout=8)
        if code != 0 and not timed_out and "no such object" in err.lower():
            result.update(ownership_status="absent", inspection="absent")
            return result
        if code != 0 or timed_out:
            return result
        obj = json.loads(out)
        container_id = obj.get("Id")
        container_name = str(obj.get("Name", "")).lstrip("/")
        labels = (obj.get("Config") or {}).get("Labels") or {}
        result.update(container_name=container_name, labels=labels)
        if not isinstance(container_id, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", container_id):
            return result
        # Docker's full immutable ID is the only value safe to use for removal
        # and post-removal inspection. Normalize hex case after exact validation.
        container_id = container_id.lower()
        result["container_id"] = container_id
        if container_name != record["container_name"]:
            result.update(ownership_status="name_mismatch", inspection="name_mismatch")
        elif not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
            result.update(ownership_status="labels_mismatch", inspection="labels_mismatch")
        else:
            result.update(ownership_status="owned", inspection="owned")
        return result
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError):
        return result


def inspect_container_id(root: str | Path, container_id: str) -> dict[str, Any]:
    docker = shutil.which("docker")
    result = {"container_id": container_id, "container_name": None, "labels": {},
              "ownership_status": "unavailable", "inspection": "unavailable"}
    if not docker:
        return result
    try:
        from runner import _run_process, sanitized_environment
        code, out, err, timed_out = _run_process(
            [docker, "inspect", "--format", "{{json .}}", container_id], cwd=str(root),
            env=sanitized_environment(), timeout=8)
        if code != 0 and not timed_out and "no such object" in err.lower():
            result.update(ownership_status="absent", inspection="absent")
            return result
        if code == 0 and not timed_out:
            obj = json.loads(out)
            result.update(container_name=str(obj.get("Name", "")).lstrip("/"),
                          labels=(obj.get("Config") or {}).get("Labels") or {},
                          ownership_status="present", inspection="present")
        return result
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return result


def inspect_runtime(root: str | Path) -> dict[str, Any]:
    try:
        record = load_runtime_record(root)
    except Exception as error:
        return {"required": True, "inspection": "invalid", "summary": str(error)}
    if record is None:
        return {"required": False, "inspection": "none"}
    result = {"required": True, "revision": record["revision"], "execution_id": record["execution_id"],
              "container_name": record["container_name"], "state": record["state"]}
    inspected = inspect_container_record(root, record)
    result.update(container_id=inspected["container_id"], inspection=inspected["inspection"])
    result["summary"] = {
        "absent": "The recorded container is absent; explicit human resolution is required.",
        "owned": "The exact container exists and its required Bridge ownership labels match.",
        "labels_mismatch": "The exact name exists but required Bridge ownership labels do not match; do not delete it.",
        "name_mismatch": "The inspected Docker object name did not match the journal.",
        "invalid": "The runtime journal workspace identity is invalid.",
        "unavailable": "Docker inspection is uncertain; recovery remains required.",
    }.get(inspected["inspection"], "Docker inspection is uncertain; recovery remains required.")
    return result


def _clear_locked(root: str | Path, record: dict[str, Any]) -> None:
    path, _ = _paths(root)
    current = load_runtime_record(root)
    if current is None or current["revision"] != record["revision"] or current != record:
        raise ValueError("Execution recovery journal was replaced; recovery remains required")
    path.unlink()
    dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def resolve_runtime_recovery(root: str | Path, expected_revision: str) -> dict[str, Any]:
    with coordination_lock(root):
        with runtime_lock(root):
            record = load_runtime_record(root)
            if record is None or record["revision"] != expected_revision:
                raise ValueError("Execution recovery identity is stale")
            inspection = inspect_container_record(root, record)
            latest = load_runtime_record(root)
            if latest is None or latest != record:
                raise ValueError("Execution recovery journal changed during inspection; recovery is stale")
            if inspection["inspection"] == "absent":
                _clear_locked(root, record)
                return {"resolved": True, "action": "cleared_absent"}
            if inspection["inspection"] == "labels_mismatch":
                raise ValueError("Container ownership labels do not match; manual review is required and no deletion was performed")
            if inspection["inspection"] != "owned":
                raise ValueError("Docker could not verify the recorded container safely; recovery remains required")
            container_id = inspection["container_id"]
            docker = shutil.which("docker")
            try:
                from runner import sanitized_environment
                removed = subprocess.run([docker, "rm", "-f", container_id], cwd=str(root),
                                          env=sanitized_environment(), capture_output=True, text=True, timeout=10)
                if removed.returncode != 0:
                    raise ValueError("Exact container cleanup failed; recovery remains required")
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError("Exact container cleanup could not be confirmed; recovery remains required") from error
            after = inspect_container_id(root, container_id)
            if after["inspection"] != "absent":
                raise ValueError("Exact container ID absence could not be confirmed; recovery remains required")
            _clear_locked(root, record)
            return {"resolved": True, "action": "removed_owned", "container_id": container_id}
