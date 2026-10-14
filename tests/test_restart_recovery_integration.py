from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"


def run_process(
    script: str,
    bridge_home: Path,
    *,
    check: bool = True,
):
    env = os.environ.copy()

    env["AI_WORKFLOW_BRIDGE_HOME"] = str(
        bridge_home
    )

    existing_pythonpath = env.get(
        "PYTHONPATH",
        "",
    )

    env["PYTHONPATH"] = os.pathsep.join(
        value
        for value in [
            str(HOST),
            existing_pythonpath,
        ]
        if value
    )

    return subprocess.run(
        [
            sys.executable,
            "-c",
            script,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def read_json_process(
    script: str,
    bridge_home: Path,
) -> dict:
    completed = run_process(
        script,
        bridge_home,
    )

    output = completed.stdout.strip()

    assert output, completed.stderr

    return json.loads(
        output.splitlines()[-1]
    )


def test_cross_process_crash_requires_explicit_recovery(
    tmp_path: Path,
):
    bridge_home = tmp_path / "bridge-home"

    # --------------------------------------------------------
    # Process A:
    # persist an in-flight state, then terminate abruptly.
    # --------------------------------------------------------

    writer = r'''
import os

from orchestrator import Orchestrator


bridge = Orchestrator(
    lambda _message: None
)

bridge.lifecycle = "running"
bridge.status = "waiting_approval"
bridge.current_step = "Awaiting protected command approval"
bridge.paused = False
bridge.active_provider = "chatgpt"
bridge.provider_guard = False

bridge.budget.reset("chatgpt")
bridge.budget.record_send()

bridge.pending = {
    "approval-crash-test": {
        "approval_id": "approval-crash-test",
        "summary": "Crash recovery sentinel",
        "command": "DO_NOT_REPLAY",
        "impact": "integration test",
        "continuation": {
            "kind": "command",
            "index": 7,
            "dangerous_internal_state": "MUST_NOT_SURVIVE",
        },
    },
}

bridge.store.put_approval(
    "approval-crash-test",
    {
        "approval_id": "approval-crash-test",
        "summary": "Crash recovery sentinel",
        "command": "DO_NOT_REPLAY",
        "impact": "integration test",
    },
)

bridge._persist_runtime_state()

# Deliberately bypass normal Python cleanup.
os._exit(23)
'''

    crashed = run_process(
        writer,
        bridge_home,
        check=False,
    )

    assert crashed.returncode == 23

    # --------------------------------------------------------
    # Process B:
    # actual new interpreter + new SQLite connection.
    # --------------------------------------------------------

    reader = r'''
import json

from orchestrator import Orchestrator


events = []

bridge = Orchestrator(
    events.append
)

snapshot = bridge.store.get_runtime_state(
    "orchestrator"
)

print(json.dumps({
    "state": bridge.state(),
    "events": events,
    "runtime_snapshot": snapshot,
    "pending_db": bridge.store.list_pending_approvals(),
}))
'''

    recovered = read_json_process(
        reader,
        bridge_home,
    )

    state = recovered["state"]

    assert state["paused"] is True
    assert (
        state["lifecycle"]
        == "recovery_required"
    )
    assert (
        state["status"]
        == "recovery_required"
    )

    recovery = state["recovery"]

    assert recovery["required"] is True
    assert (
        recovery["previous_status"]
        == "waiting_approval"
    )

    # Approval review metadata may survive,
    # executable continuation must not.
    approvals = recovery[
        "pending_approvals"
    ]

    assert len(approvals) == 1
    assert (
        approvals[0]["approval_id"]
        == "approval-crash-test"
    )
    assert (
        approvals[0]["command"]
        == "DO_NOT_REPLAY"
    )
    assert "continuation" not in approvals[0]
    assert (
        "dangerous_internal_state"
        not in approvals[0]
    )

    # Budget must not reset because of restart.
    assert (
        state["budget"]["session_turns"]
        == 1
    )

    # Constructor/recovery startup must not replay anything.
    assert recovered["events"] == []

    assert not any(
        event.get("kind")
        in {
            "send_to_llm",
            "download_request",
            "approval_required",
        }
        for event in recovered["events"]
    )

    # Stale approval exists only as persisted review history
    # until the human explicitly resolves recovery.
    assert len(
        recovered["pending_db"]
    ) == 1

    # --------------------------------------------------------
    # Process C:
    # human explicitly discards interrupted run.
    # --------------------------------------------------------

    discard = r'''
import json

from orchestrator import Orchestrator


events = []

bridge = Orchestrator(
    events.append
)

bridge.handle({
    "type": "recovery_discard",
})

print(json.dumps({
    "state": bridge.state(),
    "events": events,
    "pending_db": bridge.store.list_pending_approvals(),
}))
'''

    discarded = read_json_process(
        discard,
        bridge_home,
    )

    discarded_state = discarded["state"]

    assert discarded_state["paused"] is True
    assert (
        discarded_state["lifecycle"]
        == "paused"
    )
    assert (
        discarded_state["status"]
        == "paused"
    )
    assert (
        discarded_state["recovery"]
        is None
    )

    # Recovery decision expires stale approvals.
    assert discarded["pending_db"] == []

    assert not any(
        event.get("kind")
        in {
            "send_to_llm",
            "download_request",
            "approval_required",
        }
        for event in discarded["events"]
    )

    # --------------------------------------------------------
    # Process D:
    # restart once more and prove recovery resolution itself
    # persisted safely.
    # --------------------------------------------------------

    final_reader = r'''
import json

from orchestrator import Orchestrator


events = []

bridge = Orchestrator(
    events.append
)

print(json.dumps({
    "state": bridge.state(),
    "events": events,
    "pending_db": bridge.store.list_pending_approvals(),
}))
'''

    final = read_json_process(
        final_reader,
        bridge_home,
    )

    final_state = final["state"]

    assert final_state["paused"] is True
    assert (
        final_state["lifecycle"]
        == "paused"
    )
    assert (
        final_state["status"]
        == "paused"
    )
    assert final_state["recovery"] is None

    assert (
        final_state["budget"]["session_turns"]
        == 1
    )

    assert final["pending_db"] == []
    assert final["events"] == []


def test_cross_process_checkpoint_rollback_crash_is_never_replayed(
    tmp_path: Path,
):
    bridge_home = (
        tmp_path /
        "checkpoint-bridge-home"
    )

    workspace = (
        tmp_path /
        "checkpoint-workspace"
    )

    workspace.mkdir()

    workspace_literal = repr(
        str(
            workspace.resolve()
        )
    )

    # --------------------------------------------------------
    # Process A:
    # create a durable checkpoint, claim rollback, persist
    # the recovery boundary, then die abruptly BEFORE restore.
    # --------------------------------------------------------

    writer = rf'''
import os

from checkpoint import build_checkpoint_metadata
from config import save_config
from orchestrator import Orchestrator


workspace = {workspace_literal}

save_config({{
    "workspace_root": workspace,
    "provider_id": "chatgpt",
}})

bridge = Orchestrator(
    lambda _message: None
)

payload = build_checkpoint_metadata(
    workspace_root=workspace,
    lifecycle="running",
    phase="P1",
    stage="S1",
    command_index=0,
    command_summary="Cross-process rollback sentinel",
    risk_level="R2",
    reason="Integration-test rollback boundary",
    git={{
        "is_git": False,
    }},
    snapshot_metadata={{
        "kind": "workspace_tar_v1",
        "checkpoint_id": "cp-cross-process",
        "workspace_root": workspace,
        "archive_path": "/DO_NOT_REPLAY/workspace.tar.gz",
        "archive_sha256": "0" * 64,
        "file_count": 1,
        "total_bytes": 1,
        "excluded_paths": [],
        "rollback_scope": "workspace_files_only",
    }},
    checkpoint_id="cp-cross-process",
)

bridge.store.put_checkpoint(
    payload
)

claimed = (
    bridge.store.transition_checkpoint_status(
        "cp-cross-process",
        expected_status="ready",
        new_status="rolling_back",
    )
)

assert claimed

bridge.paused = True
bridge.lifecycle = "recovering"
bridge.status = "recovering"
bridge.current_step = (
    "Rolling back workspace checkpoint"
)

bridge.checkpoint_recovery_context = {{
    "checkpoint_id": "cp-cross-process",
    "status": "rolling_back",
    "rollback_scope": "workspace_files_only",
    "command_summary": (
        "Cross-process rollback sentinel"
    ),
    "risk_level": "R2",
    "uncertain": True,
    "note": (
        "Process crashed after rollback claim "
        "and before durable completion."
    ),
}}

bridge._persist_runtime_state()

# Deliberately bypass cleanup/finally handlers.
os._exit(31)
'''

    crashed = run_process(
        writer,
        bridge_home,
        check=False,
    )

    assert crashed.returncode == 31

    # --------------------------------------------------------
    # Process B:
    # brand-new interpreter and SQLite connection.
    #
    # Monkeypatch the restore primitive to explode if startup
    # ever attempts to replay rollback automatically.
    # --------------------------------------------------------

    reader = r'''
import json

import orchestrator_checkpoints


def forbidden_restore(**_kwargs):
    raise RuntimeError(
        "ROLLBACK_REPLAYED_DURING_RESTART"
    )


orchestrator_checkpoints.restore_workspace_snapshot = (
    forbidden_restore
)

from orchestrator import Orchestrator


events = []

bridge = Orchestrator(
    events.append
)

checkpoint = bridge.store.get_checkpoint(
    "cp-cross-process"
)

runtime = bridge.store.get_runtime_state(
    "orchestrator"
)

print(json.dumps({
    "state": bridge.state(),
    "events": events,
    "checkpoint": checkpoint,
    "runtime": runtime,
}))
'''

    recovered = read_json_process(
        reader,
        bridge_home,
    )

    state = recovered[
        "state"
    ]

    assert state[
        "paused"
    ] is True

    assert (
        state[
            "lifecycle"
        ]
        == "recovery_required"
    )

    assert (
        state[
            "status"
        ]
        == "recovery_required"
    )

    recovery = state[
        "recovery"
    ]

    assert recovery[
        "required"
    ] is True

    checkpoint_recovery = recovery[
        "checkpoint_recovery"
    ]

    assert (
        checkpoint_recovery[
            "checkpoint_id"
        ]
        == "cp-cross-process"
    )

    assert (
        checkpoint_recovery[
            "status"
        ]
        == "rolling_back"
    )

    assert (
        checkpoint_recovery[
            "rollback_scope"
        ]
        == "workspace_files_only"
    )

    assert (
        checkpoint_recovery[
            "uncertain"
        ]
        is True
    )

    # Sensitive/executable restore material must never be
    # exposed through recovery review state.
    assert (
        "archive_path"
        not in checkpoint_recovery
    )

    assert (
        "continuation"
        not in checkpoint_recovery
    )

    assert (
        recovered[
            "checkpoint"
        ][
            "status"
        ]
        == "rolling_back"
    )

    # Constructor/restart recovery performs no action.
    assert recovered[
        "events"
    ] == []

    assert not any(
        event.get(
            "kind"
        )
        in {
            "send_to_llm",
            "download_request",
            "approval_required",
            "checkpoint_rolled_back",
        }
        for event in recovered[
            "events"
        ]
        if isinstance(
            event,
            dict,
        )
    )

    # --------------------------------------------------------
    # Process C:
    # human explicitly discards the interrupted recovery.
    #
    # Still forbid restore: discard is reconciliation,
    # never rollback replay.
    # --------------------------------------------------------

    discard = r'''
import json

import orchestrator_checkpoints


def forbidden_restore(**_kwargs):
    raise RuntimeError(
        "ROLLBACK_REPLAYED_DURING_DISCARD"
    )


orchestrator_checkpoints.restore_workspace_snapshot = (
    forbidden_restore
)

from orchestrator import Orchestrator


events = []

bridge = Orchestrator(
    events.append
)

bridge.handle({
    "type": "recovery_discard",
})

checkpoint = bridge.store.get_checkpoint(
    "cp-cross-process"
)

runtime = bridge.store.get_runtime_state(
    "orchestrator"
)

print(json.dumps({
    "state": bridge.state(),
    "events": events,
    "checkpoint": checkpoint,
    "runtime": runtime,
}))
'''

    discarded = read_json_process(
        discard,
        bridge_home,
    )

    discarded_state = (
        discarded[
            "state"
        ]
    )

    assert (
        discarded_state[
            "paused"
        ]
        is True
    )

    assert (
        discarded_state[
            "lifecycle"
        ]
        == "paused"
    )

    assert (
        discarded_state[
            "status"
        ]
        == "paused"
    )

    assert (
        discarded_state[
            "recovery"
        ]
        is None
    )

    # An uncertain rolling_back checkpoint is terminally
    # invalidated, not silently treated as rolled_back.
    assert (
        discarded[
            "checkpoint"
        ][
            "status"
        ]
        == "invalid"
    )

    assert not any(
        event.get(
            "kind"
        )
        in {
            "send_to_llm",
            "download_request",
            "approval_required",
            "checkpoint_rolled_back",
        }
        for event in discarded[
            "events"
        ]
        if isinstance(
            event,
            dict,
        )
    )

    # --------------------------------------------------------
    # Process D:
    # restart again. The human reconciliation itself must
    # have persisted and must not create a recovery loop.
    # --------------------------------------------------------

    final_reader = r'''
import json

import orchestrator_checkpoints


def forbidden_restore(**_kwargs):
    raise RuntimeError(
        "ROLLBACK_REPLAYED_AFTER_RESOLUTION"
    )


orchestrator_checkpoints.restore_workspace_snapshot = (
    forbidden_restore
)

from orchestrator import Orchestrator


events = []

bridge = Orchestrator(
    events.append
)

checkpoint = bridge.store.get_checkpoint(
    "cp-cross-process"
)

print(json.dumps({
    "state": bridge.state(),
    "events": events,
    "checkpoint": checkpoint,
}))
'''

    final = read_json_process(
        final_reader,
        bridge_home,
    )

    final_state = final[
        "state"
    ]

    assert (
        final_state[
            "paused"
        ]
        is True
    )

    assert (
        final_state[
            "lifecycle"
        ]
        == "paused"
    )

    assert (
        final_state[
            "status"
        ]
        == "paused"
    )

    assert (
        final_state[
            "recovery"
        ]
        is None
    )

    assert (
        final[
            "checkpoint"
        ][
            "status"
        ]
        == "invalid"
    )

    assert final[
        "events"
    ] == []
