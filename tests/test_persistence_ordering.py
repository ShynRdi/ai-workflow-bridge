from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"

if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))

import orchestrator_risk
from contracts import CommandSpec, WorkflowContract
from orchestrator_execution import ExecutionMixin
from orchestrator_reporting import ReportingMixin
from runner import CommandResult
from safety import RunBudget


def test_command_state_is_persisted_before_process_execution(
    monkeypatch,
    tmp_path,
):
    trace = []

    monkeypatch.setattr(
        orchestrator_risk,
        "git_snapshot",
        lambda _workspace: {"is_git": False},
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "classify",
        lambda _cmd, _workspace: SimpleNamespace(
            level="auto",
        ),
    )

    monkeypatch.setattr(
        orchestrator_risk,
        "merge_risk",
        lambda _local, _llm: SimpleNamespace(
            level="auto",
            local_risk_level="R0",
            llm_risk_level=None,
            risk_level="R0",
            escalated_by_llm=False,
            reason="read only",
        ),
    )

    def fake_run_command(*_args, **_kwargs):
        assert trace[-1] == "persist"
        trace.append("run_command")

        return CommandResult(
            command="echo ok",
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

    class Telegram:
        def send_report(self, _text):
            pass

    class Bridge(orchestrator_risk.RiskAwareExecutionMixin):
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
            trace.append("event")

        def _persist_runtime_state(self):
            trace.append("persist")

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

        def _send_result_to_chatgpt(self, _text):
            trace.append("report_send")

        @staticmethod
        def provider_name(value):
            return value

    bridge = Bridge()

    contract = WorkflowContract(
        version=1,
        phase="P1",
        stage="S1",
        summary="test",
        commands=[
            CommandSpec(
                cmd="echo ok",
                purpose="test command",
            )
        ],
    )

    orchestrator_risk.RiskAwareExecutionMixin \
        ._run_command_and_continue(
            bridge,
            contract,
            0,
        )

    assert trace.index("persist") < trace.index(
        "run_command"
    )


def test_download_state_is_persisted_before_browser_request():
    trace = []

    class Bridge(ExecutionMixin):
        def __init__(self):
            self.download_waiters = {}

        def _persist_runtime_state(self):
            trace.append("persist")

        def emit(self, message):
            assert message["kind"] == "download_request"
            assert trace[-1] == "persist"

            trace.append("download_request")

            waiter = self.download_waiters[
                message["request_id"]
            ]

            waiter["response"] = {
                "ok": True,
                "files": [
                    {
                        "filename": "artifact.txt",
                    }
                ],
            }

            waiter["event"].set()

    bridge = Bridge()

    files = bridge._request_downloads(
        [{"href": "https://example.invalid/a"}],
        42,
    )

    assert files
    assert trace == [
        "persist",
        "download_request",
    ]


def test_budget_is_persisted_before_outbound_llm_send():
    trace = []

    class Bridge(ReportingMixin):
        def __init__(self):
            self.config = {}
            self.provider_guard = False
            self.paused = False
            self.active_provider = "chatgpt"
            self.pending_send_timer = None
            self.lock = threading.RLock()
            self.budget = RunBudget()
            self.budget.reset("chatgpt")

        def decorate_outbound_prompt(self, text):
            return text

        def _persist_runtime_state(self):
            trace.append("persist")

        def emit(self, message):
            kind = message.get("kind")

            if kind == "send_to_llm":
                assert trace[-1] == "persist"
                trace.append("send_to_llm")

        def emit_event(self, _event):
            trace.append("event")

        def state(self):
            return {}

        @staticmethod
        def provider_name(value):
            return value

    bridge = Bridge()

    bridge._send_result_to_chatgpt(
        "test prompt"
    )

    assert trace[:2] == [
        "persist",
        "send_to_llm",
    ]

    assert (
        bridge.budget.public({})["session_turns"]
        == 1
    )
