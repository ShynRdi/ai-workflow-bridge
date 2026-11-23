from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))

import execution_runtime as runtime
import execution_state
import runner
from execution_state import load_execution_state, update_execution_state
from orchestrator_project_state import ProjectStateMixin


def _owned(record, container_id="a" * 64):
    return {"container_id": container_id, "container_name": record["container_name"],
            "labels": {"ai-workflow-bridge.managed": "true",
                       "ai-workflow-bridge.execution": record["execution_id"],
                       "ai-workflow-bridge.workspace": record["workspace_identity"]},
            "ownership_status": "owned", "inspection": "owned"}


def _record(root: Path):
    value = runtime.create_runtime_record(root)
    return runtime.write_runtime_record(root, value)


def test_runtime_journal_absent_and_survives_reload(tmp_path):
    assert runtime.load_runtime_record(tmp_path) is None
    record = _record(tmp_path)
    assert runtime.load_runtime_record(tmp_path) == record
    assert record["mode"] == "container" and record["runtime"] == "docker"
    assert record["workspace_identity"] == runtime.workspace_identity(tmp_path)


@pytest.mark.parametrize("raw", [b"{", b"{}", b'{"version":1}'])
def test_malformed_runtime_journal_fails_closed(tmp_path, raw):
    control = tmp_path / ".ai-workflow"
    control.mkdir()
    (control / runtime.RUNTIME_FILE).write_bytes(raw)
    with pytest.raises(ValueError):
        runtime.load_runtime_record(tmp_path)
    with pytest.raises(ValueError):
        runner.run_command("true", str(tmp_path), ".", 2, 100)


def test_symlink_and_oversized_runtime_journals_fail_closed(tmp_path):
    control = tmp_path / ".ai-workflow"
    control.mkdir()
    target = tmp_path / "target"
    target.write_text("{}")
    (control / runtime.RUNTIME_FILE).symlink_to(target)
    with pytest.raises(ValueError, match="symbolic"):
        runtime.load_runtime_record(tmp_path)
    (control / runtime.RUNTIME_FILE).unlink()
    (control / runtime.RUNTIME_FILE).write_bytes(b" " * (runtime.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="maximum"):
        runtime.load_runtime_record(tmp_path)


def test_write_before_docker_run_and_normal_cleanup_clears_journal(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"], image="python:3.12")
    real_write = runtime.write_runtime_record
    seen = []
    def write(root, record, **kwargs):
        result = real_write(root, record, **kwargs)
        seen.append(("journal", result["state"]))
        return result
    def process(argv, **kwargs):
        if argv[1] == "info" or argv[1:3] == ["image", "inspect"]:
            return 0, "ok", "", False
        if argv[1] == "run":
            assert runtime.load_runtime_record(tmp_path) is not None
            seen.append(("run", argv[argv.index("--name") + 1]))
            return 0, "ok", "", False
        if argv[1:3] == ["rm", "-f"]:
            return 0, "", "", False
        raise AssertionError(argv)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", process)
    monkeypatch.setattr(runtime, "write_runtime_record", write)
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: _owned(record))
    monkeypatch.setattr(runtime, "inspect_container_id", lambda _root, _id: {"inspection": "absent"})
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    code, *_rest = runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert code == 0
    assert seen[0] == ("journal", "starting")
    assert next(i for i, item in enumerate(seen) if item[0] == "journal") < next(i for i, item in enumerate(seen) if item[0] == "run")
    assert runtime.load_runtime_record(tmp_path) is None


def test_normal_cleanup_refuses_name_collision_with_unowned_container(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"], image="python:3.12")
    calls = []
    def process(argv, **kwargs):
        calls.append(argv)
        return 0, "", "", False
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", process)
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: {**_owned(record), "inspection": "labels_mismatch", "ownership_status": "labels_mismatch"})
    _code, _out, stderr, evidence = runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert "uncertain" in stderr and evidence["runtime_recovery_required"]
    assert not any(call[1:3] == ["rm", "-f"] for call in calls)
    assert runtime.load_runtime_record(tmp_path) is not None


def test_cleanup_uncertainty_retains_record_and_blocks_host_and_container(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"], image="python:3.12")
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", lambda argv, **kw: (0, "", "", False))
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: {**_owned(record), "inspection": "unavailable", "ownership_status": "unavailable"})
    _code, _out, stderr, evidence = runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert "uncertain" in stderr
    assert evidence["runtime_recovery_required"] is True
    record = runtime.load_runtime_record(tmp_path)
    assert record
    with pytest.raises(ValueError, match="recovery"):
        update_execution_state(str(tmp_path), mode="host", expected_revision=load_execution_state(str(tmp_path))["revision"])
    with pytest.raises(RuntimeError, match="recovery"):
        runner.run_command("true", str(tmp_path), ".", 2, 100)


def test_execution_cas_duplicate_and_recovery_gate(tmp_path):
    first = load_execution_state(str(tmp_path))
    second = update_execution_state(str(tmp_path), mode="host", expected_revision=first["revision"])
    with pytest.raises(ValueError, match="stale"):
        update_execution_state(str(tmp_path), mode="host", expected_revision=first["revision"])
    record = _record(tmp_path)
    with pytest.raises(ValueError, match="recovery"):
        update_execution_state(str(tmp_path), mode="host", expected_revision=second["revision"])
    assert runtime.load_runtime_record(tmp_path) == record


def test_runtime_recovery_absent_explicit_clear_and_stale_identity(tmp_path, monkeypatch):
    record = _record(tmp_path)
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: {"inspection": "absent", "ownership_status": "absent"})
    with pytest.raises(ValueError, match="stale"):
        runtime.resolve_runtime_recovery(tmp_path, "0" * 32)
    assert runtime.load_runtime_record(tmp_path) == record
    assert runtime.resolve_runtime_recovery(tmp_path, record["revision"]) == {"resolved": True, "action": "cleared_absent"}
    assert runtime.load_runtime_record(tmp_path) is None
    with pytest.raises(ValueError, match="stale"):
        runtime.resolve_runtime_recovery(tmp_path, record["revision"])


@pytest.mark.parametrize("inspection", ["labels_mismatch", "unavailable"])
def test_uncertain_or_mismatched_recovery_retains_journal(tmp_path, monkeypatch, inspection):
    record = _record(tmp_path)
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: {**_owned(record), "inspection": inspection, "ownership_status": inspection})
    with pytest.raises(ValueError):
        runtime.resolve_runtime_recovery(tmp_path, record["revision"])
    assert runtime.load_runtime_record(tmp_path) == record


def test_owned_recovery_removes_only_exact_name_and_verifies_absence(tmp_path, monkeypatch):
    record = _record(tmp_path)
    commands = []
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: _owned(record))
    monkeypatch.setattr(runtime, "inspect_container_id", lambda _root, _id: {"inspection": "absent"})
    def run(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.resolve_runtime_recovery(tmp_path, record["revision"])["resolved"]
    assert commands == [["/usr/bin/docker", "rm", "-f", "a" * 64]]
    assert runtime.load_runtime_record(tmp_path) is None


def test_same_name_replacement_survives_immutable_id_cleanup(tmp_path, monkeypatch):
    record = _record(tmp_path)
    commands = []
    state = {"name_owner": "a" * 64}
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, current: _owned(current, "a" * 64))
    def remove(argv, **_kwargs):
        commands.append(argv)
        # Simulate B taking the same name between ownership inspection and rm.
        state["name_owner"] = "b" * 64
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(runtime.subprocess, "run", remove)
    monkeypatch.setattr(runtime, "inspect_container_id", lambda _root, cid: {"inspection": "absent"} if cid == "a" * 64 else {"inspection": "present"})
    result = runtime.resolve_runtime_recovery(tmp_path, record["revision"])
    assert commands == [["/usr/bin/docker", "rm", "-f", "a" * 64]]
    assert state["name_owner"] == "b" * 64
    assert result["container_id"] == "a" * 64
    assert len(commands[0][-1]) == 64
    assert re.fullmatch(r"[a-f0-9]{64}", commands[0][-1])


def test_recovery_rechecks_journal_after_inspection_before_removal(tmp_path, monkeypatch):
    record = _record(tmp_path)
    replacement = {**record, "execution_id": "b" * 32, "revision": "c" * 32,
                   "container_name": "aiwb-" + "b" * 32}
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    def replace_while_inspecting(_root, _record):
        path, _lock = runtime._paths(tmp_path)
        path.write_text(json.dumps(replacement))
        return _owned(record)
    monkeypatch.setattr(runtime, "inspect_container_record", replace_while_inspecting)
    removed = []
    monkeypatch.setattr(runtime.subprocess, "run", lambda argv, **_kw: removed.append(argv))
    with pytest.raises(ValueError, match="changed during inspection"):
        runtime.resolve_runtime_recovery(tmp_path, record["revision"])
    assert removed == []
    assert runtime.load_runtime_record(tmp_path) == replacement


def test_runner_cleanup_does_not_clear_replacement_journal(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"], image="python:3.12")
    calls = []
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **_kw):
        calls.append(argv)
        return 0, "ok", "", False
    monkeypatch.setattr(runner, "_run_process", process)
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    replacement = []
    def inspect_then_replace(_root, record):
        new = {**record, "execution_id": "b" * 32, "revision": "c" * 32,
               "container_name": "aiwb-" + "b" * 32}
        path, _lock = runtime._paths(tmp_path)
        path.write_text(json.dumps(new))
        replacement.append(new)
        return _owned(record)
    monkeypatch.setattr(runtime, "inspect_container_record", inspect_then_replace)
    _code, _out, stderr, evidence = runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert evidence["runtime_recovery_required"] and "uncertain" in stderr
    assert not any(argv[1:3] == ["rm", "-f"] for argv in calls)
    assert runtime.load_runtime_record(tmp_path) == replacement[0]


def test_normal_cleanup_removes_inspected_id_if_name_is_reused(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"], image="python:3.12")
    name_owner = {"id": "a" * 64}
    calls = []
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **_kw):
        calls.append(argv)
        if argv[1:3] == ["rm", "-f"]:
            name_owner["id"] = "b" * 64
        return 0, "ok", "", False
    monkeypatch.setattr(runner, "_run_process", process)
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    def inspect(_root, record):
        value = _owned(record, name_owner["id"])
        name_owner["id"] = "b" * 64  # X now refers to B after ID A was captured.
        return value
    monkeypatch.setattr(runtime, "inspect_container_record", inspect)
    monkeypatch.setattr(runtime, "inspect_container_id", lambda _root, cid: {"inspection": "absent"} if cid == "a" * 64 else {"inspection": "present"})
    _code, _out, _err, evidence = runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert ["/usr/bin/docker", "rm", "-f", "a" * 64] in calls
    assert all(argv[3] != "b" * 64 for argv in calls if argv[1:3] == ["rm", "-f"])
    assert name_owner["id"] == "b" * 64
    assert evidence["cleanup_succeeded"]
    assert all(len(argv[-1]) == 64 and re.fullmatch(r"[a-f0-9]{64}", argv[-1])
               for argv in calls if argv[1:3] == ["rm", "-f"])


def test_normal_cleanup_retains_journal_when_id_absence_is_uncertain(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"], image="python:3.12")
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", lambda *_args, **_kwargs: (0, "", "", False))
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: _owned(record))
    monkeypatch.setattr(runtime, "inspect_container_id", lambda _root, _cid: {"inspection": "unavailable"})
    _code, _out, stderr, evidence = runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert "uncertain" in stderr and evidence["runtime_recovery_required"]
    assert runtime.load_runtime_record(tmp_path) is not None


def test_directory_fsync_precedes_docker_run_and_fsync_failure_blocks_run(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=load_execution_state(str(tmp_path))["revision"], image="python:3.12")
    events = []
    real_fsync = os.fsync
    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode): events.append("directory_fsync")
        return real_fsync(fd)
    def process(argv, **_kw):
        if argv[1] == "run": events.append("docker_run")
        return 0, "ok", "", False
    monkeypatch.setattr(runtime.os, "fsync", fsync)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", process)
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: _owned(record))
    monkeypatch.setattr(runtime, "inspect_container_id", lambda _root, _id: {"inspection": "absent"})
    runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert events.index("directory_fsync") < events.index("docker_run")

    events.clear()
    def fail_directory_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory fsync failed")
        return real_fsync(fd)
    monkeypatch.setattr(runtime.os, "fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="directory fsync failed"):
        runner._docker_run("true", tmp_path, tmp_path, 5, "", state)
    assert "docker_run" not in events


def test_launch_claim_serializes_with_execution_configuration_change(tmp_path, monkeypatch):
    (tmp_path / ".ai-workflow").mkdir()
    initial = load_execution_state(str(tmp_path))
    state = update_execution_state(str(tmp_path), mode="container", expected_revision=initial["revision"], image="python:3.12")
    claim_started = threading.Event()
    run_started = threading.Event()
    allow_run = threading.Event()
    real_write = runtime._durable_runtime_write
    def write(path, text):
        result = real_write(path, text)
        claim_started.set()
        return result
    def process(argv, **_kw):
        if argv[1] == "run":
            run_started.set()
            allow_run.wait(3)
        return 0, "ok", "", False
    monkeypatch.setattr(runtime, "_durable_runtime_write", write)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_run_process", process)
    monkeypatch.setattr(runner, "_safe_mount_path", lambda path: str(path.resolve()))
    monkeypatch.setattr(runtime, "inspect_container_record", lambda _root, record: {**_owned(record), "inspection": "absent", "ownership_status": "absent"})
    outcomes = []
    launch = threading.Thread(target=lambda: outcomes.append(runner._docker_run("true", tmp_path, tmp_path, 5, "", state)))
    launch.start()
    assert claim_started.wait(2) and run_started.wait(2)
    config_errors = []
    change = threading.Thread(target=lambda: _capture_update_error(tmp_path, state, config_errors))
    change.start()
    change.join(2)
    assert not change.is_alive()
    assert config_errors and "recovery" in config_errors[0].lower()
    allow_run.set()
    launch.join(3)
    assert not launch.is_alive() and outcomes


def _capture_update_error(root, state, errors):
    try:
        update_execution_state(str(root), mode="host", expected_revision=state["revision"])
    except ValueError as error:
        errors.append(str(error))


def test_duplicate_concurrent_recovery_only_one_succeeds(tmp_path, monkeypatch):
    record = _record(tmp_path)
    first_inspection = threading.Event()
    continue_inspection = threading.Event()
    count = 0
    count_lock = threading.Lock()
    def inspect(_root, current):
        nonlocal count
        with count_lock:
            count += 1
            first = count == 1
        if first:
            first_inspection.set()
            continue_inspection.wait(2)
        return _owned(current)
    monkeypatch.setattr(runtime, "inspect_container_record", inspect)
    monkeypatch.setattr(runtime, "inspect_container_id", lambda _root, _id: {"inspection": "absent"})
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(runtime.subprocess, "run", lambda argv, **_kw: subprocess.CompletedProcess(argv, 0, "", ""))
    outcomes = []
    def resolve():
        try: outcomes.append(("ok", runtime.resolve_runtime_recovery(tmp_path, record["revision"])))
        except ValueError as error: outcomes.append(("error", str(error)))
    one = threading.Thread(target=resolve); two = threading.Thread(target=resolve)
    one.start(); assert first_inspection.wait(2); two.start(); continue_inspection.set()
    one.join(3); two.join(3)
    assert [status for status, _ in outcomes].count("ok") == 1
    assert [status for status, _ in outcomes].count("error") == 1
    assert runtime.load_runtime_record(tmp_path) is None


@pytest.mark.parametrize("labels_ok", [True, False])
def test_inspection_uses_required_label_subset_and_returns_immutable_id(tmp_path, monkeypatch, labels_ok):
    record = _record(tmp_path)
    required = {"ai-workflow-bridge.managed": "true", "ai-workflow-bridge.execution": record["execution_id"],
                "ai-workflow-bridge.workspace": record["workspace_identity"]}
    labels = {**required, "docker.system": "extra"}
    if not labels_ok:
        labels["ai-workflow-bridge.workspace"] = "0" * 64
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **_kw):
        if argv[1] == "info": return 0, "27", "", False
        return 0, json.dumps({"Id": "d" * 64, "Name": "/" + record["container_name"], "Config": {"Labels": labels}}), "", False
    monkeypatch.setattr(runner, "_run_process", process)
    result = runtime.inspect_container_record(tmp_path, record)
    assert result["container_id"] == "d" * 64
    assert result["ownership_status"] == ("owned" if labels_ok else "labels_mismatch")


@pytest.mark.parametrize("container_id, accepted", [
    ("a" * 64, True),
    ("A" * 64, True),
    ("a" * 12, False),
    ("a" * 63, False),
    ("a" * 65, False),
    ("g" + "a" * 63, False),
    (" " + "a" * 64, False),
    ("a" * 64 + " ", False),
])
def test_inspection_requires_exact_full_hex_container_id(tmp_path, monkeypatch, container_id, accepted):
    record = _record(tmp_path)
    labels = {"ai-workflow-bridge.managed": "true",
              "ai-workflow-bridge.execution": record["execution_id"],
              "ai-workflow-bridge.workspace": record["workspace_identity"]}
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **_kw):
        if argv[1] == "info": return 0, "27", "", False
        return 0, json.dumps({"Id": container_id, "Name": "/" + record["container_name"],
                              "Config": {"Labels": labels}}), "", False
    monkeypatch.setattr(runner, "_run_process", process)
    result = runtime.inspect_container_record(tmp_path, record)
    if accepted:
        assert result["ownership_status"] == "owned"
        assert result["container_id"] == container_id.lower()
    else:
        assert result["ownership_status"] == "unavailable"
        assert result["container_id"] is None


@pytest.mark.parametrize("missing", ["managed", "execution", "workspace"])
def test_missing_or_mismatched_required_bridge_label_is_not_owned(tmp_path, monkeypatch, missing):
    record = _record(tmp_path)
    labels = {"ai-workflow-bridge.managed": "true", "ai-workflow-bridge.execution": record["execution_id"],
              "ai-workflow-bridge.workspace": record["workspace_identity"], "docker.extra": "allowed"}
    if missing == "managed": labels.pop("ai-workflow-bridge.managed")
    else: labels["ai-workflow-bridge." + missing] = "wrong"
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **_kw):
        if argv[1] == "info": return 0, "27", "", False
        return 0, json.dumps({"Id": "e" * 64, "Name": "/" + record["container_name"], "Config": {"Labels": labels}}), "", False
    monkeypatch.setattr(runner, "_run_process", process)
    assert runtime.inspect_container_record(tmp_path, record)["ownership_status"] == "labels_mismatch"


def test_diagnostics_use_only_bounded_read_only_docker_commands(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(execution_state.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] <= 8
        return 0, "27.0.1/27.0.1" if argv[1] == "version" else "sha256:x", "sensitive detail", False
    monkeypatch.setattr(runner, "_run_process", process)
    result = execution_state.docker_readiness(str(tmp_path), "python:3.12")
    assert result["ready"] and result["image_local"] is True
    verbs = [call[1:3] for call in calls]
    assert verbs == [["version", "--format"], ["image", "inspect"]]
    assert not any(call[1] in {"pull", "build", "login", "run", "rm", "prune"} for call in calls)
    assert "sensitive detail" not in json.dumps(result)


def test_diagnostics_report_missing_cli_and_runtime_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_state.shutil, "which", lambda _name: None)
    assert execution_state.docker_readiness(str(tmp_path), "python:3.12")["cli_available"] is False
    record = _record(tmp_path)
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)
    report = runtime.inspect_runtime(tmp_path)
    assert report["required"] and report["inspection"] == "unavailable"
    assert report["revision"] == record["revision"]


def test_runtime_diagnostics_inspect_only_and_report_immutable_id(tmp_path, monkeypatch):
    record = _record(tmp_path)
    calls = []
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    labels = {"ai-workflow-bridge.managed": "true", "ai-workflow-bridge.execution": record["execution_id"],
              "ai-workflow-bridge.workspace": record["workspace_identity"]}
    def process(argv, **_kw):
        calls.append(argv)
        if argv[1] == "info": return 0, "27", "", False
        return 0, json.dumps({"Id": "f" * 64, "Name": "/" + record["container_name"], "Config": {"Labels": labels}}), "", False
    monkeypatch.setattr(runner, "_run_process", process)
    report = runtime.inspect_runtime(tmp_path)
    assert report["container_id"] == "f" * 64
    assert all(argv[1] in {"info", "inspect"} for argv in calls)


@pytest.mark.parametrize("server,image_code,expected", [
    (1, 0, "Docker daemon is unavailable"),
    (0, 1, "not available locally"),
])
def test_diagnostics_distinguish_daemon_and_missing_image(tmp_path, monkeypatch, server, image_code, expected):
    monkeypatch.setattr(execution_state.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **kwargs):
        return (server if argv[1] == "version" else image_code), "", "private error detail", False
    monkeypatch.setattr(runner, "_run_process", process)
    result = execution_state.docker_readiness(str(tmp_path), "private/image:tag")
    assert expected in result["summary"]
    assert "private error detail" not in json.dumps(result)


@pytest.mark.parametrize("managed,expected", [
    ("true", "owned"),
    ("false", "labels_mismatch"),
])
def test_inspection_requires_exact_bridge_labels(tmp_path, monkeypatch, managed, expected):
    record = _record(tmp_path)
    labels = json.dumps({"ai-workflow-bridge.managed": managed, "ai-workflow-bridge.execution": record["execution_id"],
                         "ai-workflow-bridge.workspace": record["workspace_identity"]})
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    def process(argv, **kwargs):
        if argv[1] == "info": return 0, "27", "", False
        obj = {"Id": "a" * 64, "Name": "/" + record["container_name"],
               "Config": {"Labels": {**json.loads(labels), "com.docker.system": "extra"}}}
        return 0, json.dumps(obj), "", False
    monkeypatch.setattr(runner, "_run_process", process)
    assert runtime.inspect_runtime(tmp_path)["inspection"] == expected


class _ExecutionBridge(ProjectStateMixin):
    def __init__(self, workspace, lifecycle="paused"):
        self.config = {"workspace_root": str(workspace)}
        self.lifecycle = lifecycle
        self.status = lifecycle
        self.command_execution_active = False
        self.pending = {}
        self.download_waiters = {}
        self.pending_send_timer = None
        self.checkpoint_recovery_context = None
        self.events = []
    def emit_event(self, event): self.events.append(event)
    def emit(self, event): self.events.append(event)
    def state(self): return {"lifecycle": self.lifecycle}


def test_human_execution_api_is_lifecycle_gated_and_workspace_bound(tmp_path):
    bridge = _ExecutionBridge(tmp_path)
    state = load_execution_state(str(tmp_path))
    payload = {"expected_execution_revision": state["revision"], "expected_workspace": str(tmp_path),
               "mode": "host", "image": "", "cpus": 2, "memory_mb": 2048, "pids_limit": 256}
    bridge.change_execution_configuration(payload)
    assert bridge.lifecycle == "paused"
    assert load_execution_state(str(tmp_path))["revision"] != state["revision"]
    stale_workspace = _ExecutionBridge(tmp_path)
    with pytest.raises(ValueError, match="workspace changed"):
        stale_workspace.change_execution_configuration({**payload, "expected_execution_revision": load_execution_state(str(tmp_path))["revision"],
                                                        "expected_workspace": str(tmp_path / "other")})
    blocked = _ExecutionBridge(tmp_path, lifecycle="running")
    current = load_execution_state(str(tmp_path))
    with pytest.raises(ValueError, match="inert"):
        blocked.change_execution_configuration({**payload, "expected_execution_revision": current["revision"]})


def test_host_switch_does_not_require_docker_but_container_apply_does(tmp_path, monkeypatch):
    state = load_execution_state(str(tmp_path))
    monkeypatch.setattr(execution_state, "docker_readiness", lambda *_args, **_kwargs: {"ready": False, "summary": "offline"})
    host = execution_state.apply_execution_configuration(str(tmp_path), mode="host", expected_revision=state["revision"])
    assert host["mode"] == "host"
    with pytest.raises(ValueError, match="offline"):
        execution_state.apply_execution_configuration(str(tmp_path), mode="container", expected_revision=host["revision"], image="python:3.12")
    assert load_execution_state(str(tmp_path))["revision"] == host["revision"]


def test_generic_config_and_llm_message_cannot_clear_runtime_journal(tmp_path, monkeypatch):
    record = _record(tmp_path)
    config_text = (Path(__file__).parents[1] / "native_host" / "config.py").read_text()
    assert "EXECUTION_RUNTIME" not in config_text
    from orchestrator_messages import MessageMixin
    class MessageBridge(MessageMixin):
        def __init__(self): self.lifecycle = "idle"; self.events = []; self.config = {"workspace_root": str(tmp_path)}; self.called = False
        def emit_event(self, event): self.events.append(event)
        def emit(self, event): self.events.append(event)
        def state(self): return {"lifecycle": self.lifecycle}
    bridge = MessageBridge()
    bridge.handle({"type": "clear_runtime", "expected_runtime_revision": record["revision"]})
    import orchestrator_messages
    monkeypatch.setattr(orchestrator_messages, "save_config", lambda value: value)
    bridge.handle({"type": "set_config", "config": {"workspace_root": str(tmp_path),
                  "execution": {"mode": "host"}, "execution_recovery": None}})
    assert runtime.load_runtime_record(tmp_path) == record


def test_runtime_journal_contains_no_command_or_workspace_path(tmp_path):
    record = _record(tmp_path)
    raw = (tmp_path / ".ai-workflow" / runtime.RUNTIME_FILE).read_text()
    assert str(tmp_path) not in raw
    assert "command" not in record and "secret" not in raw
    assert "workspace=" + str(tmp_path) not in raw


def test_runtime_journal_copy_to_different_workspace_is_not_recoverable(tmp_path):
    original = tmp_path / "original"
    copied = tmp_path / "copied"
    original.mkdir(); copied.mkdir()
    record = _record(original)
    destination = copied / ".ai-workflow"
    destination.mkdir()
    (destination / runtime.RUNTIME_FILE).write_text(json.dumps(record))
    report = runtime.inspect_runtime(copied)
    assert report["inspection"] == "invalid" and report["required"]


def test_execution_identity_helper_keeps_rendered_revision_and_workspace():
    helper = Path(__file__).parents[1] / "extension" / "execution-identity.js"
    script = f'''require({json.dumps(str(helper))});
const button={{dataset:{{}}}};
AWB_EXECUTION_IDENTITY.bind(button,{{revision:"RA"}},"/workspace/A");
const action=AWB_EXECUTION_IDENTITY.actionPayload(button,{{mode:"container"}});
AWB_EXECUTION_IDENTITY.bind(button,{{revision:"RB"}},"/workspace/B");
if(action.expected_execution_revision!=="RA"||action.expected_workspace!=="/workspace/A")process.exit(2);
const recovery={{dataset:{{}}}};
AWB_EXECUTION_IDENTITY.bindRecovery(recovery,{{revision:"REC-A"}},"/workspace/A");
const cleanup=AWB_EXECUTION_IDENTITY.recoveryPayload(recovery);
AWB_EXECUTION_IDENTITY.bindRecovery(recovery,{{revision:"REC-B"}},"/workspace/B");
if(cleanup.expected_runtime_revision!=="REC-A"||cleanup.expected_workspace!=="/workspace/A")process.exit(3);
'''
    subprocess.run(["node", "-e", script], check=True)


def test_recovery_commands_are_exact_and_no_broad_cleanup_exists():
    source = (Path(__file__).parents[1] / "native_host" / "execution_runtime.py").read_text()
    assert '[docker, "rm", "-f", container_id]' in source
    assert "docker system prune" not in source
    assert "docker container prune" not in source
