from __future__ import annotations

import json
import multiprocessing
import os
import signal
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "native_host"
if str(HOST) not in sys.path:
    sys.path.insert(0, str(HOST))

import runner
import execution_runtime
import orchestrator_risk
from execution_state import load_execution_state, update_execution_state
from contracts import CommandSpec, WorkflowContract, extract_contract


def _mock_owned_cleanup(monkeypatch, container_id="a" * 64):
    def inspect_record(_root, record):
        return {"container_id": container_id, "container_name": record["container_name"],
                "labels": {"ai-workflow-bridge.managed": "true",
                           "ai-workflow-bridge.execution": record["execution_id"],
                           "ai-workflow-bridge.workspace": record["workspace_identity"]},
                "ownership_status": "owned", "inspection": "owned"}
    monkeypatch.setattr(execution_runtime, "inspect_container_record", inspect_record)
    monkeypatch.setattr(execution_runtime, "inspect_container_id", lambda _root, _id: {"inspection": "absent"})


def test_missing_execution_state_is_workspace_bound_host_default(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    state_a = load_execution_state(str(a))
    state_b = load_execution_state(str(b))
    assert state_a["mode"] == state_b["mode"] == "host"
    assert not state_a["persisted"]
    assert state_a["revision"] != state_b["revision"]


@pytest.mark.parametrize("mutation", [
    {"version": 2}, {"version": 1.0}, {"mode": "podman"},
    {"container": {"runtime": "podman"}},
    {"container": {"network": "host"}},
    {"container": {"image": "bad image"}}, {"container": {"image": "abc:::tag"}},
    {"container": {"image": "-v"}},
    {"container": {"cpus": 0}}, {"container": {"cpus": float("nan")}},
    {"container": {"memory_mb": 0}}, {"container": {"pids_limit": 99999}},
])
def test_malformed_execution_state_fails_closed(tmp_path, mutation):
    control = tmp_path / ".ai-workflow"
    control.mkdir()
    value = {
        "version": 1, "mode": "container", "revision": "1" * 32, "updated_at": "2026-11-23T00:00:00+00:00",
        "container": {"runtime": "docker", "image": "python:3.12", "network": "none",
                      "cpus": 2.0, "memory_mb": 2048, "pids_limit": 256},
    }
    for key, item in mutation.items():
        if key == "container": value["container"].update(item)
        else: value[key] = item
    (control / "EXECUTION.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_execution_state(str(tmp_path))


def test_execution_state_rejects_symlink_and_cas_update(tmp_path):
    control = tmp_path / ".ai-workflow"
    control.mkdir()
    other = tmp_path / "other"
    other.write_text("{}")
    (control / "EXECUTION.json").symlink_to(other)
    with pytest.raises(ValueError, match="symbolic link"):
        load_execution_state(str(tmp_path))
    (control / "EXECUTION.json").unlink()
    legacy = load_execution_state(str(tmp_path))
    with pytest.raises(ValueError, match="stale"):
        update_execution_state(str(tmp_path), mode="container", expected_revision="wrong", image="python:3.12")
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=legacy["revision"], image="python:3.12")
    assert state["mode"] == "container" and state["persisted"]


def test_execution_state_requires_image_in_container_mode(tmp_path):
    (tmp_path / ".ai-workflow").mkdir()
    with pytest.raises(ValueError, match="image"):
        update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"])


def _concurrent_execution_update(workspace, expected_revision, barrier, queue, image):
    sys.path.insert(0, str(HOST))
    from execution_state import update_execution_state
    barrier.wait()
    try:
        result = update_execution_state(workspace, mode="container", expected_revision=expected_revision, image=image)
        queue.put(("ok", result["revision"]))
    except ValueError as error:
        queue.put(("error", str(error)))


def test_execution_state_compare_and_set_is_process_atomic(tmp_path):
    (tmp_path / ".ai-workflow").mkdir()
    expected = load_execution_state(str(tmp_path))["revision"]
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [context.Process(target=_concurrent_execution_update,
        args=(str(tmp_path), expected, barrier, queue, f"python:{tag}")) for tag in ("3.11", "3.12")]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    results = [queue.get(timeout=2) for _ in processes]
    assert [result[0] for result in results].count("ok") == 1
    errors = [result[1] for result in results if result[0] == "error"]
    assert len(errors) == 1 and "stale" in errors[0]
    final = load_execution_state(str(tmp_path))
    assert final["mode"] == "container" and final["revision"] != expected


def test_execution_lock_rejects_symlink(tmp_path):
    control = tmp_path / ".ai-workflow"
    control.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("")
    (control / "EXECUTION.lock").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        update_execution_state(str(tmp_path), mode="host", expected_revision=load_execution_state(str(tmp_path))["revision"])


def test_docker_argv_has_required_boundaries_and_no_host_secrets(monkeypatch, tmp_path):
    control = tmp_path / ".ai-workflow"
    control.mkdir()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setenv("SUPER_SECRET_API_KEY", "should-not-forward")
    calls = []
    def fake_process(argv, *, cwd, env, timeout):
        calls.append((argv, cwd, env))
        if argv[1:2] in (["info"], ["image"]):
            return 0, "ok", "", False
        if argv[1:2] == ["run"]:
            return 0, "ok", "", False
        return 0, "", "", False
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", fake_process)
    _mock_owned_cleanup(monkeypatch)
    current = load_execution_state(str(tmp_path))
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=current["revision"],
                                   image="python:3.12", cpus=1.5, memory_mb=768, pids_limit=128)
    result = runner.run_command("echo safe", str(tmp_path), ".", 15, 500, str(downloads), state)
    argv = next(call[0] for call in calls if call[0][1:2] == ["run"])
    assert argv[:2] == ["/usr/bin/docker", "run"]
    pairs = {arg: argv[index + 1] for index, arg in enumerate(argv[:-1])
             if arg in {"--name", "--label", "--network", "--security-opt", "--cpus", "--memory",
                        "--pids-limit", "--mount", "--workdir", "--user", "--env"}}
    assert "--pull=never" in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert "--cap-drop=ALL" in argv
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    assert "--read-only" in argv
    assert argv[argv.index("--cpus") + 1] == "1.5"
    assert argv[argv.index("--memory") + 1] == "768m"
    assert argv[argv.index("--pids-limit") + 1] == "128"
    assert argv[argv.index("--workdir") + 1] == "/workspace"
    mounts = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--mount"]
    assert mounts == [f"type=bind,src={tmp_path.resolve()},dst=/workspace",
                      f"type=bind,src={(tmp_path / '.ai-workflow').resolve()},dst=/workspace/.ai-workflow,readonly",
                      f"type=bind,src={downloads.resolve()},dst=/bridge-downloads,readonly"]
    assert "--env" in argv and "HOME=/tmp" in argv
    assert "--tmpfs" in argv and argv[argv.index("--tmpfs") + 1].startswith("/tmp:rw,")
    assert argv[-4:] == ["python:3.12", "/bin/bash", "-lc", "echo safe"]
    assert argv[-1] == "echo safe"
    assert not any(value.startswith("--") for value in argv[-1:])
    forbidden = {"--privileged", "--network=host", "/var/run/docker.sock", os.environ.get("HOME", "")}
    forbidden.discard("")
    assert forbidden.isdisjoint(argv)
    assert not any(argv[i:i + 2] == ["--network", "host"] for i in range(len(argv) - 1))
    assert "SSH_AUTH_SOCK" not in " ".join(argv)
    assert "--user" in argv
    uid_arg = argv[argv.index("--user") + 1]
    assert uid_arg == f"{os.getuid()}:{os.getgid()}"
    assert "should-not-forward" not in argv
    assert "should-not-forward" not in str(next(call[2] for call in calls if call[0][1:2] == ["run"]))
    assert result.execution["mode"] == "container"
    assert ["/usr/bin/docker", "rm", "-f", "a" * 64] in [call[0] for call in calls]


def test_host_timeout_kills_child_process_group(tmp_path):
    child_file = tmp_path / "child.pid"
    command = f"sleep 30 & echo $! > '{child_file}'; wait"
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run_command(command, str(tmp_path), ".", 0.3, 500)
    child_pid = int(child_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_container_root_workspace_is_rejected_before_docker(monkeypatch):
    calls = []
    monkeypatch.setattr(runner.shutil, "which", lambda _name: calls.append("which") or "/usr/bin/docker")
    with pytest.raises(ValueError, match="Filesystem root"):
        runner._docker_run("true", Path("/"), Path("/"), 5, "", {
            "container": {"image": "python:3.12", "cpus": 1, "memory_mb": 512, "pids_limit": 64}
        })
    assert calls == []


def test_mount_paths_preserve_spaces_and_colons_and_reject_delimiters(tmp_path):
    workspace = tmp_path / "project with:colon"
    workspace.mkdir()
    assert runner._safe_mount_path(workspace) == str(workspace.resolve())
    for unsafe in ("project,comma", "project\nnewline", "project\rreturn"):
        path = tmp_path / unsafe
        path.mkdir()
        with pytest.raises(ValueError, match="represented safely"):
            runner._safe_mount_path(path)


def test_workspace_mount_with_spaces_and_colon_is_one_argv_value(monkeypatch, tmp_path):
    workspace = tmp_path / "project with:colon"
    (workspace / ".ai-workflow").mkdir(parents=True)
    calls = []
    def fake_process(argv, *, cwd, env, timeout):
        calls.append(argv)
        return 0, "ok", "", False
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", fake_process)
    _mock_owned_cleanup(monkeypatch)
    current = load_execution_state(str(workspace))
    state = update_execution_state(str(workspace), mode="container", expected_revision=current["revision"], image="python:3.12")
    runner._docker_run("echo x", workspace, workspace, 5, "", {
        **state
    })
    argv = next(argv for argv in calls if argv[1:2] == ["run"])
    assert argv[argv.index("--mount") + 1] == f"type=bind,src={workspace.resolve()},dst=/workspace"


def test_mount_preparation_failure_aborts_container_without_host_fallback(monkeypatch, tmp_path):
    current = load_execution_state(str(tmp_path))
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=current["revision"], image="python:3.12")
    calls = []
    def fake_process(argv, *, cwd, env, timeout):
        calls.append(argv)
        return 0, "ok", "", False
    original_safe_mount = runner._safe_mount_path
    def fail_control_mount(path):
        if Path(path).name == ".ai-workflow":
            raise ValueError("unsafe control mount")
        return original_safe_mount(path)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", fake_process)
    monkeypatch.setattr(runner, "_safe_mount_path", fail_control_mount)
    with pytest.raises(ValueError, match="unsafe control mount"):
        runner.run_command("echo must-not-run-on-host", str(tmp_path), ".", 5, 100, execution_state=state)
    assert all(argv[1:2] != ["run"] for argv in calls)
    assert all(argv[:2] != ["/bin/bash", "-lc"] for argv in calls)


def test_docker_runner_exception_still_cleans_exact_container(monkeypatch, tmp_path):
    (tmp_path / ".ai-workflow").mkdir()
    current = load_execution_state(str(tmp_path))
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=current["revision"], image="python:3.12")
    calls = []
    def fake_process(argv, *, cwd, env, timeout):
        calls.append(argv)
        if argv[1:2] == ["run"]:
            raise OSError("runner failed unexpectedly")
        return 0, "ok", "", False
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", fake_process)
    _mock_owned_cleanup(monkeypatch)
    with pytest.raises(OSError, match="unexpectedly"):
        runner.run_command("echo x", str(tmp_path), ".", 5, 100, execution_state=state)
    run_argv = next(argv for argv in calls if argv[1:2] == ["run"])
    name = run_argv[run_argv.index("--name") + 1]
    assert ["/usr/bin/docker", "rm", "-f", "a" * 64] in calls


def test_container_failure_never_falls_back_to_host(monkeypatch, tmp_path):
    current = load_execution_state(str(tmp_path))
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=current["revision"], image="python:3.12")
    monkeypatch.setattr(runner, "_docker_run", lambda *_args: (_ for _ in ()).throw(RuntimeError("docker down")))
    with pytest.raises(RuntimeError, match="docker down"):
        runner.run_command("echo x", str(tmp_path), ".", 5, 100, execution_state=state)


def test_container_timeout_removes_only_its_unique_container(monkeypatch, tmp_path):
    (tmp_path / ".ai-workflow").mkdir()
    current = load_execution_state(str(tmp_path))
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=current["revision"], image="python:3.12")
    calls = []
    def fake_process(argv, *, cwd, env, timeout):
        calls.append(argv)
        if argv[1:2] == ["run"]:
            return 124, "", "timed out", True
        return 0, "", "", False
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", fake_process)
    _mock_owned_cleanup(monkeypatch)
    result = runner.run_command("sleep 10", str(tmp_path), ".", 1, 100, execution_state=state)
    run_argv = next(argv for argv in calls if argv[1:2] == ["run"])
    cleanup = [call for call in calls if call[:3] == ["/usr/bin/docker", "rm", "-f"]][-1]
    assert result.exit_code == 124
    assert cleanup == ["/usr/bin/docker", "rm", "-f", "a" * 64]
    assert "ai-workflow-bridge.managed=true" in run_argv


def test_generic_config_and_llm_contract_cannot_select_execution_mode(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(runner, "_docker_run", lambda *_args: called.append("docker"))
    result = runner.run_command("true", str(tmp_path), ".", 5, 100)
    assert result.execution["mode"] == "host"
    assert called == []
    contract = extract_contract('''<<<AI_WORKFLOW>>>{"version":1,"phase":"P1","stage":"S1",
      "summary":"x","execution":{"mode":"container"},"commands":[]}<<<END_AI_WORKFLOW>>>''')
    assert contract is not None
    assert not hasattr(contract, "execution")


def test_runner_rejects_noncanonical_execution_state(tmp_path):
    with pytest.raises(ValueError, match="canonical"):
        runner.run_command("true", str(tmp_path), ".", 5, 100, execution_state={
            "mode": "container", "container": {"image": "python:3.12"},
        })


def _risk(level="approval", risk_level="R2"):
    return SimpleNamespace(level=level, risk_level=risk_level, local_risk_level=risk_level,
                           llm_risk_level=None, escalated_by_llm=False, reason="test")


def _contract():
    return WorkflowContract(version=1, phase="P1", stage="S1", summary="test",
                            commands=[CommandSpec(cmd="touch file")])


class _Bridge(orchestrator_risk.RiskAwareExecutionMixin):
    def __init__(self, workspace):
        self.config = {"workspace_root": str(workspace), "auto_run_low_risk": True,
                       "command_timeout_seconds": 5, "max_output_chars": 500}
        self.status = "idle"
        self.active_provider = "chatgpt"
        self.telegram = type("Telegram", (), {"send_report": lambda *_args: None})()
        self.events = []

    def emit_event(self, event): self.events.append(event)
    def _send_result_to_chatgpt(self, _text): pass
    def _format_result(self, *_args, **_kwargs): return "report"
    def _telegram_summary(self, *_args, **_kwargs): return "summary"
    def _persist_runtime_state(self): pass
    @staticmethod
    def provider_name(value): return value


def test_policy_block_and_approval_happen_before_backend_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator_risk, "git_snapshot", lambda _root: {"is_git": False})
    monkeypatch.setattr(orchestrator_risk, "classify", lambda *_args: SimpleNamespace(level="blocked"))
    monkeypatch.setattr(orchestrator_risk, "merge_risk", lambda *_args: _risk("blocked", "R4"))
    monkeypatch.setattr(orchestrator_risk, "load_execution_state", lambda *_args: (_ for _ in ()).throw(AssertionError("selected before policy")))
    monkeypatch.setattr(orchestrator_risk, "run_command", lambda *_args, **_kw: (_ for _ in ()).throw(AssertionError("runner invoked")))
    _Bridge(tmp_path)._run_command_and_continue(_contract(), 0)

    trace = []
    monkeypatch.setattr(orchestrator_risk, "classify", lambda *_args: SimpleNamespace(level="approval"))
    monkeypatch.setattr(orchestrator_risk, "merge_risk", lambda *_args: _risk("approval"))
    bridge = _Bridge(tmp_path)
    bridge._request_decision = lambda *_args, **_kwargs: trace.append("approval")
    bridge._run_command_and_continue(_contract(), 0)
    assert trace == ["approval"]


def test_checkpoint_completes_before_execution_state_load_and_backend(monkeypatch, tmp_path):
    trace = []
    monkeypatch.setattr(orchestrator_risk, "git_snapshot", lambda _root: {"is_git": False})
    monkeypatch.setattr(orchestrator_risk, "classify", lambda *_args: SimpleNamespace(level="approval"))
    monkeypatch.setattr(orchestrator_risk, "merge_risk", lambda *_args: _risk("approval"))
    monkeypatch.setattr(orchestrator_risk, "load_execution_state", lambda _root: trace.append("execution_state") or {"mode": "host"})
    monkeypatch.setattr(orchestrator_risk, "run_command", lambda *_args, **_kwargs: trace.append("runner") or runner.CommandResult("x", str(tmp_path), 0, 0.01, "", ""))
    bridge = _Bridge(tmp_path)
    bridge._create_command_checkpoint = lambda **_kwargs: trace.append("checkpoint") or {
        "checkpoint_id": "c1", "snapshot": {"rollback_scope": "workspace_files_only"},
    }
    bridge._run_command_and_continue(_contract(), 0, approved_index=0)
    assert trace == ["checkpoint", "execution_state", "runner"]

