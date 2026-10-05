from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHECKPOINT_VERSION = 1

CHECKPOINT_STATUSES = {
    "ready",
    "accepted",
    "rolled_back",
    "invalid",
}

FORBIDDEN_EXECUTION_KEYS = {
    "continuation",
    "contract",
    "approved_index",
    "execution_cursor",
    "pending_send_timer",
    "download_waiter",
    "download_waiters",
}


def now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _json_copy(
    value: Any,
) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
        )
    )


def _assert_no_executable_state(
    value: Any,
    *,
    path: str = "checkpoint",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key)

            if name in FORBIDDEN_EXECUTION_KEYS:
                raise ValueError(
                    "Checkpoint metadata must not contain "
                    f"executable continuation state: "
                    f"{path}.{name}"
                )

            _assert_no_executable_state(
                item,
                path=f"{path}.{name}",
            )

    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_executable_state(
                item,
                path=f"{path}[{index}]",
            )


def validate_checkpoint_metadata(
    payload: dict[str, Any],
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(
            "Checkpoint metadata must be a mapping"
        )

    if payload.get("version") != CHECKPOINT_VERSION:
        raise ValueError(
            "Unsupported checkpoint metadata version"
        )

    checkpoint_id = str(
        payload.get("checkpoint_id") or ""
    ).strip()

    if not checkpoint_id:
        raise ValueError(
            "Checkpoint id is required"
        )

    workspace_root = str(
        payload.get("workspace_root") or ""
    ).strip()

    if not workspace_root:
        raise ValueError(
            "Checkpoint workspace root is required"
        )

    status = str(
        payload.get("status") or ""
    ).strip()

    if status not in CHECKPOINT_STATUSES:
        raise ValueError(
            f"Invalid checkpoint status: {status}"
        )

    created_at = str(
        payload.get("created_at") or ""
    ).strip()

    if not created_at:
        raise ValueError(
            "Checkpoint creation timestamp is required"
        )

    command = payload.get("command")

    if not isinstance(command, dict):
        raise ValueError(
            "Checkpoint command metadata must be a mapping"
        )

    index = command.get("index")

    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or index < 0
    ):
        raise ValueError(
            "Checkpoint command index must be "
            "a non-negative integer"
        )

    _assert_no_executable_state(
        payload
    )


def build_checkpoint_metadata(
    *,
    workspace_root: str,
    lifecycle: str,
    phase: str,
    stage: str,
    command_index: int,
    command_summary: str,
    risk_level: str,
    reason: str,
    git: dict[str, Any] | None = None,
    snapshot_metadata: dict[str, Any] | None = None,
    checkpoint_id: str | None = None,
    created_at: str | None = None,
    status: str = "ready",
) -> dict[str, Any]:
    root = str(
        Path(
            workspace_root
        ).expanduser().resolve()
    )

    payload = {
        "version": CHECKPOINT_VERSION,
        "checkpoint_id": (
            str(checkpoint_id).strip()
            if checkpoint_id
            else uuid.uuid4().hex
        ),
        "created_at": (
            str(created_at).strip()
            if created_at
            else now_iso()
        ),
        "status": str(status).strip(),
        "workspace_root": root,
        "reason": str(reason or "").strip(),
        "lifecycle": str(
            lifecycle or ""
        ).strip(),
        "project": {
            "phase": str(
                phase or ""
            ).strip(),
            "stage": str(
                stage or ""
            ).strip(),
        },
        "command": {
            "index": int(command_index),
            "summary": str(
                command_summary or ""
            ).strip(),
            "risk_level": str(
                risk_level or ""
            ).strip(),
        },
        "git": _json_copy(
            git or {}
        ),
        "snapshot": _json_copy(
            snapshot_metadata or {}
        ),
    }

    validate_checkpoint_metadata(
        payload
    )

    return payload
