from __future__ import annotations

import shlex
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


BALANCED = "balanced"
STRICT = "strict"
ISOLATED_DEVELOPMENT = "isolated_development"
DEFAULT_PROFILE = BALANCED


@dataclass(frozen=True)
class PolicyProfile:
    profile_id: str
    label: str
    description: str
    warning: str = ""


PROFILES = {
    STRICT: PolicyProfile(
        STRICT,
        "Strict",
        "Maximum supervision. Stronger restrictions for network, outside-workspace, remote, and external-state actions.",
    ),
    BALANCED: PolicyProfile(
        BALANCED,
        "Balanced",
        "Recommended default. Preserves normal guarded development behavior.",
    ),
    ISOLATED_DEVELOPMENT: PolicyProfile(
        ISOLATED_DEVELOPMENT,
        "Isolated Development",
        "Reduced friction for narrowly proven workspace-local actions.",
        "This profile does not create an OS/container sandbox.",
    ),
}


def validate_profile(value: str | None) -> str:
    profile = str(value or "").strip().lower()
    if profile not in PROFILES:
        raise ValueError("Unknown security policy profile")
    return profile


def public_profiles() -> list[dict[str, str]]:
    return [
        {
            "id": item.profile_id,
            "label": item.label,
            "description": item.description,
            "warning": item.warning,
        }
        for item in PROFILES.values()
    ]


def _workspace_setup(command: str, workspace_root: str) -> bool:
    """Recognize only two non-executing local setup primitives."""
    if not workspace_root:
        return False
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return False
    if not parts:
        return False
    executable, values = parts[0], parts[1:]
    if executable == "mkdir":
        if not values or values[0] != "-p":
            return False
        values = values[1:]
    elif executable != "touch":
        return False
    if not values or any(value.startswith("-") for value in values):
        return False

    root = Path(workspace_root).expanduser().resolve()
    for value in values:
        if value.startswith(("~", "$", "/")) or ".." in Path(value).parts:
            return False
        path = (root / value).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError:
            return False
        if ".ai-workflow" in path.relative_to(root).parts:
            return False
    return True


def apply_profile(
    profile: str,
    command: str,
    workspace_root: str,
    base: Any,
) -> Any:
    """Return a monotonic profile adjustment for a deterministic decision."""
    profile = validate_profile(profile)
    if getattr(base, "immutable_block", False) or profile == BALANCED:
        return replace(base, profile=profile)

    lower = " ".join(str(command or "").strip().lower().split())
    if profile == STRICT:
        external = (
            lower.startswith("git push")
            or lower.startswith(("ssh ", "scp ", "rsync ", "curl ", "wget "))
            or "outside the configured workspace" in str(getattr(base, "reason", ""))
        )
        if external:
            return replace(
                base,
                level="blocked",
                risk_level="R3",
                reason="Strict policy forbids remote, network, or outside-workspace actions",
                profile=profile,
                category="strict_external_boundary",
                external_state=True,
            )
        return replace(base, profile=profile)

    # This is deliberately not an isolation claim. It does not trust project
    # code and only permits path-proven filesystem setup primitives.
    if (
        profile == ISOLATED_DEVELOPMENT
        and getattr(base, "level", "") == "approval"
        and _workspace_setup(command, workspace_root)
    ):
        return replace(
            base,
            level="low",
            risk_level="R1",
            reason="Isolated Development permits this path-proven workspace-local setup action",
            profile=profile,
            category="workspace_setup",
            workspace_mutation=True,
        )
    return replace(base, profile=profile)
