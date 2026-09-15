from __future__ import annotations

import os
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


def run_command(command: str, workspace_root: str, cwd: str, timeout: int, max_output_chars: int, download_dir: str = "") -> CommandResult:
    workdir = resolve_cwd(workspace_root, cwd)
    started = time.monotonic()
    proc = subprocess.run(
        ["/bin/bash", "-lc", command],
        cwd=str(workdir),
        text=True,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, "AI_WORKFLOW_BRIDGE": "1", "AI_WORKFLOW_DOWNLOAD_DIR": download_dir},
    )
    duration = time.monotonic() - started
    stdout = redact_text(proc.stdout[-max_output_chars:])
    stderr = redact_text(proc.stderr[-max_output_chars:])
    return CommandResult(command, str(workdir), proc.returncode, duration, stdout, stderr)


def git_snapshot(workspace_root: str) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not (root / ".git").exists() and not (root / ".git").is_file():
        return {"is_git": False}

    def run(*args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=str(root), text=True, capture_output=True, timeout=20)
        return proc.stdout.strip()

    return {"is_git": True, "head": run("rev-parse", "HEAD"), "branch": run("branch", "--show-current"), "status": run("status", "--short"), "diff_stat": run("diff", "--stat")}
