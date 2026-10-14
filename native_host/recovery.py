from __future__ import annotations

from typing import Any


RUNTIME_STATE_KEY = "orchestrator"

RECOVERY_LIFECYCLES = {
    "planning",
    "running",
    "change_review",
    "finishing",
    "recovering",
    "recovery_required",
}

RECOVERY_STATUSES = {
    "arming",
    "running",
    "validating",
    "reporting",
    "waiting_llm",
    "waiting_chatgpt",
    "waiting_approval",
    "change_review",
    "finishing",
    "recovering",
    "recovery_required",
    "cooldown",
}


def sanitize_pending_approval(
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "approval_id": str(value.get("approval_id") or ""),
        "summary": str(value.get("summary") or ""),
        "command": str(value.get("command") or ""),
        "impact": str(value.get("impact") or ""),
    }


def sanitize_checkpoint_recovery(
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "checkpoint_id": str(
            value.get("checkpoint_id")
            or ""
        ),
        "status": str(
            value.get("status")
            or ""
        ),
        "rollback_scope": str(
            value.get("rollback_scope")
            or "workspace_files_only"
        ),
        "command_summary": str(
            value.get("command_summary")
            or ""
        ),
        "risk_level": str(
            value.get("risk_level")
            or ""
        ),
        "uncertain": bool(
            value.get("uncertain")
        ),
        "note": str(
            value.get("note")
            or ""
        )[:500],
    }


def build_runtime_snapshot(
    *,
    lifecycle: str,
    status: str,
    current_step: str,
    paused: bool,
    active_provider: str,
    provider_guard: bool,
    pending: dict[str, dict[str, Any]] | None = None,
    budget: dict[str, Any] | None = None,
    checkpoint_recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    approvals = []

    for approval_id, value in (pending or {}).items():
        item = dict(value or {})
        item.setdefault("approval_id", approval_id)
        approvals.append(sanitize_pending_approval(item))

    payload = {
        "version": 2,
        "lifecycle": str(lifecycle or "setup"),
        "status": str(status or "idle"),
        "current_step": str(current_step or ""),
        "paused": bool(paused),
        "active_provider": str(active_provider or "chatgpt"),
        "provider_guard": bool(provider_guard),
        "pending_approvals": approvals,
        "budget": dict(budget or {}),
    }

    if isinstance(
        checkpoint_recovery,
        dict,
    ):
        payload[
            "checkpoint_recovery"
        ] = sanitize_checkpoint_recovery(
            checkpoint_recovery
        )

    return payload


def requires_recovery(
    snapshot: dict[str, Any] | None,
) -> bool:
    if not isinstance(snapshot, dict):
        return False

    lifecycle = str(snapshot.get("lifecycle") or "")
    status = str(snapshot.get("status") or "")

    return (
        lifecycle in RECOVERY_LIFECYCLES
        or status in RECOVERY_STATUSES
    )


def recovery_summary(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    approvals = [
        sanitize_pending_approval(item)
        for item in snapshot.get("pending_approvals") or []
        if isinstance(item, dict)
    ]

    result = {
        "required": True,
        "previous_lifecycle": str(
            snapshot.get("lifecycle") or "unknown"
        ),
        "previous_status": str(
            snapshot.get("status") or "unknown"
        ),
        "previous_step": str(
            snapshot.get("current_step") or ""
        ),
        "active_provider": str(
            snapshot.get("active_provider") or "chatgpt"
        ),
        "provider_guard": bool(
            snapshot.get("provider_guard")
        ),
        "pending_approvals": approvals,
    }

    checkpoint_recovery = (
        snapshot.get(
            "checkpoint_recovery"
        )
    )

    if isinstance(
        checkpoint_recovery,
        dict,
    ):
        result[
            "checkpoint_recovery"
        ] = sanitize_checkpoint_recovery(
            checkpoint_recovery
        )

    return result
