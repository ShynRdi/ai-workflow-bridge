from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from config import APP_DIR, CONFIG_PATH


SUPPORTED_PLATFORMS = {"Linux", "Darwin"}


def _check(
    check_id: str,
    label: str,
    status: str,
    detail: str,
    remediation: str = "",
) -> dict[str, str]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
        "remediation": remediation,
    }


def _overall_status(checks: list[dict[str, str]]) -> str:
    statuses = {item["status"] for item in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _git_workspace_check(workspace: Path) -> dict[str, str]:
    git_bin = shutil.which("git")
    if not git_bin:
        return _check(
            "git",
            "Git",
            "warn",
            "Git was not found on PATH.",
            "Install Git if this project uses Git-backed workflow checks.",
        )

    try:
        result = subprocess.run(
            [
                git_bin,
                "-C",
                str(workspace),
                "rev-parse",
                "--is-inside-work-tree",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _check(
            "git",
            "Git",
            "warn",
            f"Git workspace inspection failed: {type(exc).__name__}.",
            "Verify Git is installed and the workspace is accessible.",
        )

    if result.returncode == 0 and result.stdout.strip() == "true":
        return _check(
            "git",
            "Git workspace",
            "pass",
            "Configured workspace is inside a Git work tree.",
        )

    return _check(
        "git",
        "Git workspace",
        "warn",
        "Configured workspace is not inside a Git work tree.",
        "Initialize Git if version-control safeguards are expected.",
    )


def collect_diagnostics(config: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    python_version = ".".join(str(part) for part in sys.version_info[:3])
    checks.append(
        _check(
            "python",
            "Python",
            "pass" if sys.version_info >= (3, 11) else "fail",
            f"Python {python_version} is running the native host.",
            "Install Python 3.11+ and reinstall the native host."
            if sys.version_info < (3, 11)
            else "",
        )
    )

    system = platform.system() or "Unknown"
    checks.append(
        _check(
            "platform",
            "Operating system",
            "pass" if system in SUPPORTED_PLATFORMS else "fail",
            f"Detected platform: {system}.",
            "AI Workflow Bridge currently supports Linux and macOS."
            if system not in SUPPORTED_PLATFORMS
            else "",
        )
    )

    app_dir_ok = APP_DIR.is_dir()
    checks.append(
        _check(
            "app_dir",
            "Bridge local state",
            "pass" if app_dir_ok else "fail",
            "Bridge application directory is available."
            if app_dir_ok
            else "Bridge application directory is missing.",
            "Reinstall or restart the native host."
            if not app_dir_ok
            else "",
        )
    )

    state_access_ok = (
        app_dir_ok
        and os.access(APP_DIR, os.R_OK)
        and os.access(APP_DIR, os.W_OK)
    )
    checks.append(
        _check(
            "app_dir_access",
            "Local state permissions",
            "pass" if state_access_ok else "fail",
            "Bridge local state is readable and writable."
            if state_access_ok
            else "Bridge local state is not both readable and writable.",
            "Check ownership and permissions of the Bridge local state directory."
            if not state_access_ok
            else "",
        )
    )

    checks.append(
        _check(
            "config",
            "Local configuration",
            "pass" if CONFIG_PATH.is_file() else "warn",
            "Local configuration file exists."
            if CONFIG_PATH.is_file()
            else "No persisted configuration file exists yet.",
            "Save a project configuration from Mission Control."
            if not CONFIG_PATH.is_file()
            else "",
        )
    )

    workspace_value = str(config.get("workspace_root") or "").strip()

    if not workspace_value:
        checks.append(
            _check(
                "workspace",
                "Workspace",
                "warn",
                "No workspace is configured.",
                "Set an absolute workspace path in Project Brief and save it.",
            )
        )
    else:
        workspace = Path(workspace_value).expanduser()

        if not workspace.exists():
            checks.append(
                _check(
                    "workspace",
                    "Workspace",
                    "fail",
                    "Configured workspace does not exist.",
                    "Correct the workspace path or create the directory.",
                )
            )
        elif not workspace.is_dir():
            checks.append(
                _check(
                    "workspace",
                    "Workspace",
                    "fail",
                    "Configured workspace is not a directory.",
                    "Choose a project directory as the workspace.",
                )
            )
        else:
            readable = os.access(workspace, os.R_OK)
            writable = os.access(workspace, os.W_OK)

            checks.append(
                _check(
                    "workspace",
                    "Workspace",
                    "pass" if readable and writable else "fail",
                    "Workspace is readable and writable."
                    if readable and writable
                    else "Workspace does not have the required read/write access.",
                    "Fix workspace ownership or permissions."
                    if not (readable and writable)
                    else "",
                )
            )

            checks.append(_git_workspace_check(workspace))

    result = {
        "schema_version": 1,
        "overall": _overall_status(checks),
        "host": {
            "python_version": python_version,
            "platform": system,
        },
        "checks": checks,
    }

    return result
