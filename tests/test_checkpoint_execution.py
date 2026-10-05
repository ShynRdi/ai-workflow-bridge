from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))

import orchestrator_risk
from contracts import CommandSpec, WorkflowContract
from runner import CommandResult


class Telegram:
    def send_report(self, _text):
        pass


def contract_for(command: str, purpose: str) -> WorkflowContract:
    return WorkflowContract(
        version=1,
        phase="P1",
        stage="S1",
        summary="checkpoint execution test",
        commands=[
            CommandSpec(
                cmd=command,
                purpose=purpose,
            )
        ],
    )


def risk(
    *,
    level: str,
    risk_level: str,
    reason: str,
):
    return SimpleNamespace(
        level=level,
        local_risk_level=risk_level,
        llm_risk_level=None,
        risk_level=risk_level,
        escalated_by_llm=False,
        reason=reason,
    )


def test_r2_checkpoint_is_durable_before_command_execution(
    monkeypatch,
    tmp_path,
):
    trace = []

    monkeypatch.setattr(
        orchestrator_risk,
        "git_snapshot",
        lambda _workspace: {
            "is_git": False,
        },
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "classify",
        lambda _cmd, _workspace:
        SimpleNamespace(level="approval"),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "merge_risk",
        lambda _local, _llm:
        risk(
            level="approval",
            risk_level="R2",
            reason="workspace mutation",
        ),
    )

    def fake_snapshot(
        *,
        checkpoint_id,
        workspace_root,
    ):
        trace.append("snapshot")

        return {
            "version": 1,
            "kind": "workspace_tar_v1",
            "checkpoint_id": checkpoint_id,
            "workspace_root": workspace_root,
            "archive_path": "/tmp/fake-checkpoint.tar.gz",
            "archive_sha256": "abc123",
            "file_count": 2,
            "total_bytes": 10,
            "excluded_paths": [],
        }

    monkeypatch.setattr(
        orchestrator_risk,
        "create_workspace_snapshot",
        fake_snapshot,
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "remove_workspace_snapshot",
        lambda **_kwargs:
        trace.append("cleanup"),
    )

    def fake_run_command(*_args, **_kwargs):
        trace.append("run_command")

        return CommandResult(
            command="python mutate.py",
            cwd=str(tmp_path),
            exit_code=0,
            duration_seconds=0.01,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(
        orchestrator_risk,
        "run_command",
        fake_run_command,
    )

    class Store:
        def put_checkpoint(self, payload):
            assert payload["status"] == "ready"

            assert (
                payload["snapshot"]["rollback_scope"]
                == "workspace_files_only"
            )

            trace.append("checkpoint_store")

    class Bridge(
        orchestrator_risk.RiskAwareExecutionMixin
    ):
        def __init__(self):
            self.config = {
                "workspace_root": str(tmp_path),
                "auto_run_low_risk": True,
                "phase": "P1",
                "stage": "S1",
            }

            self.lifecycle = "running"
            self.status = "idle"
            self.current_step = ""
            self.active_provider = "chatgpt"
            self.telegram = Telegram()
            self.store = Store()

        def emit_event(self, event):
            trace.append(
                f"event:{event.get('kind')}"
            )

        def _persist_runtime_state(self):
            trace.append("runtime_persist")

        def _format_result(self, *_args, **_kwargs):
            return "report"

        def _telegram_summary(self, *_args, **_kwargs):
            return "summary"

        def _send_result_to_chatgpt(self, _text):
            trace.append("report_send")

        @staticmethod
        def provider_name(value):
            return value

    Bridge()._run_command_and_continue(
        contract_for(
            "python mutate.py",
            "Mutate project file",
        ),
        0,
        approved_index=0,
    )

    assert trace.index("snapshot") < trace.index(
        "checkpoint_store"
    )

    assert trace.index(
        "checkpoint_store"
    ) < trace.index(
        "runtime_persist"
    )

    assert trace.index(
        "runtime_persist"
    ) < trace.index(
        "run_command"
    )

    assert "cleanup" not in trace


def test_checkpoint_failure_prevents_command_execution(
    monkeypatch,
    tmp_path,
):
    trace = []

    monkeypatch.setattr(
        orchestrator_risk,
        "git_snapshot",
        lambda _workspace: {
            "is_git": False,
        },
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "classify",
        lambda _cmd, _workspace:
        SimpleNamespace(level="approval"),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "merge_risk",
        lambda _local, _llm:
        risk(
            level="approval",
            risk_level="R2",
            reason="workspace mutation",
        ),
    )

    def fail_snapshot(**_kwargs):
        trace.append("snapshot")
        raise RuntimeError(
            "snapshot unavailable"
        )

    monkeypatch.setattr(
        orchestrator_risk,
        "create_workspace_snapshot",
        fail_snapshot,
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "remove_workspace_snapshot",
        lambda **_kwargs:
        trace.append("cleanup"),
    )

    def forbidden_run(*_args, **_kwargs):
        raise AssertionError(
            "command must not execute"
        )

    monkeypatch.setattr(
        orchestrator_risk,
        "run_command",
        forbidden_run,
    )

    class Store:
        def put_checkpoint(self, _payload):
            raise AssertionError(
                "checkpoint must not persist"
            )

    class Bridge(
        orchestrator_risk.RiskAwareExecutionMixin
    ):
        def __init__(self):
            self.config = {
                "workspace_root": str(tmp_path),
                "auto_run_low_risk": True,
                "phase": "P1",
                "stage": "S1",
            }

            self.lifecycle = "running"
            self.status = "idle"
            self.current_step = ""
            self.active_provider = "chatgpt"
            self.telegram = Telegram()
            self.store = Store()

        def emit_event(self, event):
            trace.append(
                f"event:{event.get('kind')}"
            )

        def _persist_runtime_state(self):
            trace.append("runtime_persist")

        def _format_result(self, *_args, **_kwargs):
            return "report"

        def _telegram_summary(self, *_args, **_kwargs):
            return "summary"

        def _send_result_to_chatgpt(self, text):
            trace.append("report_send")
            assert "NOT executed" in text

        @staticmethod
        def provider_name(value):
            return value

    bridge = Bridge()

    bridge._run_command_and_continue(
        contract_for(
            "python mutate.py",
            "Mutate project file",
        ),
        0,
        approved_index=0,
    )

    assert bridge.status == "failed"
    assert "snapshot" in trace
    assert "cleanup" in trace
    assert "report_send" in trace
    assert "run_command" not in trace


def test_r0_command_does_not_create_checkpoint(
    monkeypatch,
    tmp_path,
):
    trace = []

    monkeypatch.setattr(
        orchestrator_risk,
        "git_snapshot",
        lambda _workspace: {
            "is_git": False,
        },
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "classify",
        lambda _cmd, _workspace:
        SimpleNamespace(level="low"),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "merge_risk",
        lambda _local, _llm:
        risk(
            level="low",
            risk_level="R0",
            reason="read only",
        ),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "create_workspace_snapshot",
        lambda **_kwargs:
        (_ for _ in ()).throw(
            AssertionError(
                "R0 must not create checkpoint"
            )
        ),
    )

    def fake_run_command(*_args, **_kwargs):
        trace.append("run_command")

        return CommandResult(
            command="git status",
            cwd=str(tmp_path),
            exit_code=0,
            duration_seconds=0.01,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        orchestrator_risk,
        "run_command",
        fake_run_command,
    )

    class Bridge(
        orchestrator_risk.RiskAwareExecutionMixin
    ):
        def __init__(self):
            self.config = {
                "workspace_root": str(tmp_path),
                "auto_run_low_risk": True,
            }

            self.status = "idle"
            self.current_step = ""
            self.active_provider = "chatgpt"
            self.telegram = Telegram()

        def emit_event(self, _event):
            pass

        def _persist_runtime_state(self):
            trace.append("runtime_persist")

        def _format_result(self, *_args, **_kwargs):
            return "report"

        def _telegram_summary(self, *_args, **_kwargs):
            return "summary"

        def _send_result_to_chatgpt(self, _text):
            pass

        @staticmethod
        def provider_name(value):
            return value

    Bridge()._run_command_and_continue(
        contract_for(
            "git status",
            "Inspect repo",
        ),
        0,
    )

    assert trace == [
        "runtime_persist",
        "run_command",
    ]


def test_checkpoint_waits_until_required_approval(
    monkeypatch,
    tmp_path,
):
    trace = []

    monkeypatch.setattr(
        orchestrator_risk,
        "git_snapshot",
        lambda _workspace: {
            "is_git": False,
        },
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "classify",
        lambda _cmd, _workspace:
        SimpleNamespace(level="approval"),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "merge_risk",
        lambda _local, _llm:
        risk(
            level="approval",
            risk_level="R2",
            reason="approval needed",
        ),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "create_workspace_snapshot",
        lambda **_kwargs:
        (_ for _ in ()).throw(
            AssertionError(
                "checkpoint must wait for approval"
            )
        ),
    )

    class Bridge(
        orchestrator_risk.RiskAwareExecutionMixin
    ):
        def __init__(self):
            self.config = {
                "workspace_root": str(tmp_path),
                "auto_run_low_risk": True,
            }

            self.status = "idle"
            self.current_step = ""

        def emit_event(self, _event):
            pass

        def _request_decision(
            self,
            *_args,
            **_kwargs,
        ):
            trace.append("approval")

    Bridge()._run_command_and_continue(
        contract_for(
            "python mutate.py",
            "Mutate project",
        ),
        0,
    )

    assert trace == ["approval"]


def test_r3_checkpoint_explicitly_limits_rollback_scope(
    monkeypatch,
    tmp_path,
):
    captured = {}

    monkeypatch.setattr(
        orchestrator_risk,
        "git_snapshot",
        lambda _workspace: {
            "is_git": True,
            "head": "abc123",
            "branch": "feature/test",
            "status": "",
            "diff_stat": "",
        },
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "create_workspace_snapshot",
        lambda *,
        checkpoint_id,
        workspace_root: {
            "version": 1,
            "kind": "workspace_tar_v1",
            "checkpoint_id": checkpoint_id,
            "workspace_root": workspace_root,
            "archive_path": (
                "/tmp/fake-r3-checkpoint.tar.gz"
            ),
            "archive_sha256": "abc123",
            "file_count": 1,
            "total_bytes": 10,
            "excluded_paths": [
                ".git",
                ".ai-workflow",
            ],
        },
    )

    class Store:
        def put_checkpoint(
            self,
            payload,
        ):
            captured.update(
                payload
            )

    class Bridge(
        orchestrator_risk.RiskAwareExecutionMixin
    ):
        def __init__(self):
            self.config = {
                "workspace_root": str(
                    tmp_path
                ),
                "phase": "P1",
                "stage": "S1",
            }

            self.lifecycle = "running"
            self.store = Store()

    contract = contract_for(
        "git push origin feature/test",
        "Publish branch to remote",
    )

    risk_info = SimpleNamespace(
        risk_level="R3",
    )

    checkpoint = (
        Bridge()._create_command_checkpoint(
            contract=contract,
            spec=contract.commands[0],
            index=0,
            workspace=str(tmp_path),
            risk=risk_info,
        )
    )

    snapshot = checkpoint[
        "snapshot"
    ]

    assert (
        snapshot["rollback_scope"]
        == "workspace_files_only"
    )

    limitations = " ".join(
        snapshot[
            "rollback_limitations"
        ]
    ).lower()

    assert "git metadata" in limitations
    assert "remote" in limitations
    assert "database" in limitations
    assert "system" in limitations
    assert "external side effects" in limitations

    assert (
        checkpoint["command"][
            "risk_level"
        ]
        == "R3"
    )

    assert (
        captured[
            "checkpoint_id"
        ]
        == checkpoint[
            "checkpoint_id"
        ]
    )


def test_command_execution_flag_is_active_only_inside_execution_window(
    monkeypatch,
    tmp_path,
):
    observed = []

    monkeypatch.setattr(
        orchestrator_risk,
        "git_snapshot",
        lambda _workspace: {
            "is_git": False,
        },
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "classify",
        lambda _cmd, _workspace:
        SimpleNamespace(
            level="low",
        ),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "merge_risk",
        lambda _local, _llm:
        risk(
            level="low",
            risk_level="R0",
            reason="read only",
        ),
    )

    class LocalTelegram:
        def send_report(
            self,
            _text,
        ):
            pass

    class Bridge(
        orchestrator_risk.RiskAwareExecutionMixin
    ):
        def __init__(
            self,
        ):
            self.config = {
                "workspace_root": str(
                    tmp_path
                ),
                "auto_run_low_risk": True,
            }

            self.command_execution_active = False
            self.status = "idle"
            self.current_step = ""
            self.active_provider = "chatgpt"
            self.telegram = LocalTelegram()

        def emit_event(
            self,
            _event,
        ):
            pass

        def _persist_runtime_state(
            self,
        ):
            pass

        def _format_result(
            self,
            *_args,
            **_kwargs,
        ):
            return "report"

        def _telegram_summary(
            self,
            *_args,
            **_kwargs,
        ):
            return "summary"

        def _send_result_to_chatgpt(
            self,
            _text,
        ):
            pass

        @staticmethod
        def provider_name(
            value,
        ):
            return value

    bridge = Bridge()

    def fake_run(
        *_args,
        **_kwargs,
    ):
        observed.append(
            bridge.command_execution_active
        )

        return CommandResult(
            command="git status",
            cwd=str(tmp_path),
            exit_code=0,
            duration_seconds=0.01,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        orchestrator_risk,
        "run_command",
        fake_run,
    )

    bridge._run_command_and_continue(
        contract_for(
            "git status",
            "Inspect repository",
        ),
        0,
    )

    assert observed == [
        True
    ]

    assert (
        bridge.command_execution_active
        is False
    )
