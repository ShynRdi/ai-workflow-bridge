from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redaction import redact_text


@dataclass
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    duration_seconds: float
    stdout: str
    stderr: str


SAFE_ENV_KEYS = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "XDG_RUNTIME_DIR", "NVM_DIR", "VIRTUAL_ENV", "PYTHONPATH",
)

CONTROL_DIR_NAME = ".ai-workflow"


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_cwd(workspace_root: str, relative: str) -> Path:
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Workspace does not exist: {root}")
    cwd = (root / relative).resolve()
    if not _inside(root, cwd):
        raise ValueError("Command cwd escapes the configured workspace")
    if not cwd.is_dir():
        raise ValueError(f"Command cwd does not exist: {cwd}")
    return cwd


def sanitized_environment(download_dir: str = "") -> dict[str, str]:
    """Build a minimal child environment instead of inheriting credentials wholesale."""
    env = {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}
    env["AI_WORKFLOW_BRIDGE"] = "1"
    env["AI_WORKFLOW_DOWNLOAD_DIR"] = download_dir
    return env


def _snapshot_control_dir(root: Path) -> dict[str, bytes] | None:
    control = root / CONTROL_DIR_NAME
    if not control.is_dir():
        return None
    snapshot: dict[str, bytes] = {}
    for path in sorted(control.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(control))] = path.read_bytes()
    return snapshot


def _restore_control_dir(root: Path, snapshot: dict[str, bytes] | None) -> bool:
    """Restore native-owned lifecycle files if a project command changed them.

    Returns True when mutation was detected and repaired.
    """
    control = root / CONTROL_DIR_NAME
    if snapshot is None:
        if not control.exists():
            return False
        if control.is_dir():
            shutil.rmtree(control)
        else:
            control.unlink()
        return True
    current = _snapshot_control_dir(root)
    if current == snapshot:
        return False
    if control.exists():
        shutil.rmtree(control)
    control.mkdir(parents=True, exist_ok=True)
    for relative, content in snapshot.items():
        target = control / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return True


def run_command(command: str, workspace_root: str, cwd: str, timeout: int, max_output_chars: int, download_dir: str = "") -> CommandResult:
    root = Path(workspace_root).expanduser().resolve()
    workdir = resolve_cwd(workspace_root, cwd)
    control_snapshot = _snapshot_control_dir(root)
    started = time.monotonic()
    mutation_restored = False
    try:
        proc = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=str(workdir),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=sanitized_environment(download_dir),
        )
    finally:
        mutation_restored = _restore_control_dir(root, control_snapshot)
    duration = time.monotonic() - started
    if mutation_restored:
        raise RuntimeError(
            "Project command attempted to mutate native-owned .ai-workflow lifecycle files; changes were restored"
        )
    stdout = redact_text(proc.stdout[-max_output_chars:])
    stderr = redact_text(proc.stderr[-max_output_chars:])
    return CommandResult(redact_text(command), str(workdir), proc.returncode, duration, stdout, stderr)


def git_snapshot(workspace_root: str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not (root / ".git").exists() and not (root / ".git").is_file():
        return {"is_git": False}

    def run(*args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=str(root), text=True, capture_output=True, timeout=20, env=sanitized_environment())
        return redact_text(proc.stdout.strip())

    return {"is_git": True, "head": run("rev-parse", "HEAD"), "branch": run("branch", "--show-current"), "status": run("status", "--short"), "diff_stat": run("diff", "--stat")}
