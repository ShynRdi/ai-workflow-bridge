from __future__ import annotations

import hashlib
import os
import signal
import shutil
import subprocess
import time
import uuid
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
    execution: dict[str, Any] | None = None


SAFE_ENV_KEYS = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "XDG_RUNTIME_DIR", "NVM_DIR", "VIRTUAL_ENV", "PYTHONPATH",
)

CONTROL_DIR_NAME = ".ai-workflow"


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


def sanitized_environment(download_dir: str = "") -> dict[str, str]:
    """Build a minimal child environment instead of inheriting credentials wholesale."""
    env = {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}
    env["AI_WORKFLOW_BRIDGE"] = "1"
    env["AI_WORKFLOW_DOWNLOAD_DIR"] = download_dir
    return env


def _snapshot_control_dir(root: Path) -> dict[str, bytes] | None:
    control = root / CONTROL_DIR_NAME

    if control.is_symlink():
        raise ValueError(
            "Native-owned .ai-workflow must not be a symbolic link"
        )

    if not control.exists():
        return None

    if not control.is_dir():
        raise ValueError(
            "Native-owned .ai-workflow must be a directory"
        )

    snapshot: dict[str, bytes] = {}

    for path in sorted(control.rglob("*")):
        if path.is_symlink():
            raise ValueError(
                "Native-owned .ai-workflow must not contain symbolic links"
            )

        if path.is_dir():
            continue

        if not path.is_file():
            raise ValueError(
                "Native-owned .ai-workflow contains a non-regular entry"
            )

        snapshot[str(path.relative_to(control))] = path.read_bytes()

    return snapshot


def _remove_control_entry(control: Path) -> None:
    """Remove the control entry without following a directory symlink."""
    if control.is_symlink():
        control.unlink()
        return

    if not control.exists():
        return

    if control.is_dir():
        shutil.rmtree(control)
    else:
        control.unlink()


def _restore_control_dir(root: Path, snapshot: dict[str, bytes] | None) -> bool:
    """Restore native-owned lifecycle files if a project command changed them.

    Returns True when mutation was detected and repaired. Symlinked control
    entries are unlinked rather than traversed.
    """
    control = root / CONTROL_DIR_NAME

    if snapshot is None:
        if not control.exists() and not control.is_symlink():
            return False

        _remove_control_entry(control)
        return True

    try:
        current = _snapshot_control_dir(root)
    except ValueError:
        current = None

    if current == snapshot:
        return False

    _remove_control_entry(control)
    control.mkdir(parents=True, exist_ok=True)

    for relative, content in snapshot.items():
        target = control / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    return True


def _run_process(argv: list[str], *, cwd: str, env: dict[str, str], timeout: int) -> tuple[int, str, str, bool]:
    """Run a command in its own process group and reap the whole group on timeout."""
    proc = subprocess.Popen(
        argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, start_new_session=(os.name == "posix"),
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=max(0.001, float(timeout)))
        return proc.returncode, stdout, stderr, timed_out
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=1.5)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            stdout, stderr = proc.communicate()
        return 124, stdout, (stderr + "\nCommand timed out and its process group was terminated.").strip(), timed_out


def _safe_mount_path(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or path.is_symlink():
        raise ValueError("Container mount must be a real directory")
    value = str(resolved)
    if "," in value or "\n" in value or "\r" in value:
        raise ValueError("Container mount path cannot be represented safely")
    return value


def _docker_run(
    command: str, root: Path, workdir: Path, timeout: int, download_dir: str,
    execution_state: dict[str, Any],
) -> tuple[int, str, str, dict[str, Any]]:
    root = root.resolve(strict=True)
    if root == Path("/"):
        raise ValueError("Filesystem root cannot be used as a container workspace")
    if not root.is_dir():
        raise ValueError("Container workspace must be an existing directory")
    settings = execution_state["container"]
    image = settings["image"]
    # Imported lazily to avoid the project_state -> git_evidence -> runner
    # import chain cycling through the state module during startup.
    from execution_state import validate_image

    validate_image(image)
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker executable is unavailable")
    env = sanitized_environment()
    for args, failure in (([docker, "info", "--format", "{{.ServerVersion}}"], "Docker daemon is unavailable"),
                          ([docker, "image", "inspect", image], "Configured Docker image is unavailable locally")):
        code, _out, _err, timed_out = _run_process(args, cwd=str(root), env=env, timeout=min(timeout, 10))
        if code != 0 or timed_out:
            raise RuntimeError(failure)

    workspace_mount = _safe_mount_path(root)
    control = root / CONTROL_DIR_NAME
    if control.exists() or control.is_symlink():
        control_mount = _safe_mount_path(control)
    else:
        raise RuntimeError("Workspace mount cannot be proven safe without native control directory")
    relative_cwd = workdir.relative_to(root).as_posix()
    container_cwd = "/workspace" if relative_cwd == "." else "/workspace/" + relative_cwd
    argv = [docker, "run", "--name", "aiwb-" + uuid.uuid4().hex,
            "--label", "ai-workflow-bridge.managed=true",
            "--label", "ai-workflow-bridge.workspace=" + hashlib.sha256(workspace_mount.encode()).hexdigest(),
            "--pull=never", "--network", "none", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges", "--init", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--cpus", str(settings["cpus"]), "--memory", f'{settings["memory_mb"]}m',
            "--pids-limit", str(settings["pids_limit"]),
            "--mount", f"type=bind,src={workspace_mount},dst=/workspace",
            "--mount", f"type=bind,src={control_mount},dst=/workspace/.ai-workflow,readonly",
            "--workdir", container_cwd]
    if os.name == "posix":
        argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
    container_download = ""
    if download_dir:
        source = Path(download_dir).expanduser()
        try:
            source = Path(_safe_mount_path(source))
        except (OSError, ValueError) as error:
            raise RuntimeError("Bridge download directory is unsafe") from error
        argv += ["--mount", f"type=bind,src={source},dst=/bridge-downloads,readonly"]
        container_download = "/bridge-downloads"
    argv += ["--env", "AI_WORKFLOW_BRIDGE=1", "--env", f"AI_WORKFLOW_DOWNLOAD_DIR={container_download}",
             "--env", "HOME=/tmp", image, "/bin/bash", "-lc", command]
    name = argv[argv.index("--name") + 1]
    run_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    cleanup_code = 0
    cleanup_err = ""
    run_code, stdout, stderr, timed_out = 1, "", "", False
    try:
        run_code, stdout, stderr, timed_out = _run_process(
            argv, cwd=str(root), env=sanitized_environment(), timeout=timeout
        )
    except BaseException as error:
        run_error = error
    finally:
        # The unique name is the only cleanup identity. This finally path also
        # runs when the subprocess wrapper raises after Docker may have started.
        try:
            cleanup_code, _cleanup_out, cleanup_err, _cleanup_timeout = _run_process(
                [docker, "rm", "-f", name], cwd=str(root), env=env, timeout=10
            )
        except BaseException as error:
            cleanup_error = error
            cleanup_code = 1
            cleanup_err = str(error)
    if run_error is not None:
        run_error.container_cleanup = {
            "container_name": name, "attempted": True,
            "succeeded": cleanup_code == 0 and cleanup_error is None,
            "exit_code": cleanup_code,
            "error": str(cleanup_error) if cleanup_error is not None else cleanup_err,
        }
        if (cleanup_error is not None or cleanup_code != 0) and hasattr(run_error, "add_note"):
            detail = str(cleanup_error) if cleanup_error is not None else cleanup_err
            run_error.add_note(f"Exact-name container cleanup failed (exit {cleanup_code}): {detail}")
        raise run_error
    if cleanup_code != 0:
        stderr = (stderr + "\nContainer cleanup failed: " + cleanup_err).strip()
        run_code = run_code or 1
    evidence = {
        "mode": "container", "runtime": "docker", "network": "none", "image": image,
        "resource_budget": {"cpus": settings["cpus"], "memory_mb": settings["memory_mb"], "pids_limit": settings["pids_limit"]},
        "container_name": name, "cleanup_attempted": True,
        "cleanup_succeeded": cleanup_code == 0,
        "parent_crash_recovery": "phase-2-hook-required",
    }
    if timed_out:
        stderr = (stderr + "\nContainer command timed out.").strip()
        run_code = 124
    return run_code, stdout, stderr, evidence


def run_command(command: str, workspace_root: str, cwd: str, timeout: int, max_output_chars: int, download_dir: str = "", execution_state: dict[str, Any] | None = None) -> CommandResult:
    requested_root = Path(workspace_root).expanduser()
    if requested_root.is_symlink():
        raise ValueError("Workspace mount must not be a symbolic link")
    root = requested_root.resolve()
    workdir = resolve_cwd(workspace_root, cwd)
    control_snapshot = _snapshot_control_dir(root)
    started = time.monotonic()
    mutation_restored = False
    try:
        # Resolve configuration from the canonical workspace file at the
        # backend boundary too. A caller cannot inject mode or resource
        # settings through the execution API.
        from execution_state import load_execution_state

        canonical_state = load_execution_state(str(root))
        if execution_state is not None and execution_state != canonical_state:
            raise ValueError("Execution state changed or was not loaded from canonical workspace state")
        state = canonical_state
        evidence: dict[str, Any] = {"mode": "host", "runtime": "host"}
        if state.get("mode") == "container":
            code, stdout_raw, stderr_raw, evidence = _docker_run(command, root, workdir, timeout, download_dir, state)
        elif state.get("mode") == "host":
            code, stdout_raw, stderr_raw, _timed_out = _run_process(
                ["/bin/bash", "-lc", command], cwd=str(workdir),
                env=sanitized_environment(download_dir), timeout=timeout,
            )
        else:
            raise ValueError("Unsupported execution mode")
    finally:
        mutation_restored = _restore_control_dir(root, control_snapshot)
    duration = time.monotonic() - started
    if state.get("mode") == "host" and _timed_out:
        # Preserve the legacy timeout exception contract after the process
        # group is fully reaped and native state has been restored.
        raise subprocess.TimeoutExpired(command, timeout, output=stdout_raw, stderr=stderr_raw)
    if mutation_restored:
        raise RuntimeError(
            "Project command attempted to mutate native-owned .ai-workflow lifecycle files; changes were restored"
        )
    stdout = redact_text(stdout_raw[-max_output_chars:])
    stderr = redact_text(stderr_raw[-max_output_chars:])
    return CommandResult(redact_text(command), str(workdir), code, duration, stdout, stderr, evidence)


def _git_digest(
    value: bytes | None,
) -> str:
    if value is None:
        return ""

    return hashlib.sha256(
        value
    ).hexdigest()


def git_snapshot(
    workspace_root: str,
) -> dict[str, Any]:
    """Capture read-only Git evidence without modifying .git.

    This is review metadata only. It is not a restorable Git
    transaction and must never be used to rewrite refs/index state.
    """
    root = (
        Path(
            workspace_root
        )
        .expanduser()
        .resolve()
    )

    git_marker = root / ".git"

    if (
        not git_marker.exists()
        and not git_marker.is_file()
    ):
        return {
            "version": 2,
            "is_git": False,
            "git_metadata_restorable": False,
        }

    def run_bytes(
        *args: str,
    ) -> bytes | None:
        try:
            proc = subprocess.run(
                [
                    "git",
                    *args,
                ],
                cwd=str(root),
                text=False,
                capture_output=True,
                timeout=20,
                env=sanitized_environment(),
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ):
            return None

        if proc.returncode != 0:
            return None

        return bytes(
            proc.stdout
        )

    def run_text(
        *args: str,
    ) -> str:
        raw = run_bytes(
            *args
        )

        if raw is None:
            return ""

        return redact_text(
            raw.decode(
                "utf-8",
                errors="replace",
            ).strip()
        )

    status_raw = run_bytes(
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )

    index_raw = run_bytes(
        "diff",
        "--cached",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-ext-diff",
    )

    worktree_raw = run_bytes(
        "diff",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-ext-diff",
    )

    untracked_raw = run_bytes(
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )

    conflicts_raw = run_bytes(
        "diff",
        "--name-only",
        "--diff-filter=U",
        "-z",
    )

    head = run_text(
        "rev-parse",
        "HEAD",
    )

    branch = run_text(
        "branch",
        "--show-current",
    )

    def presence(
        value: bytes | None,
    ) -> bool | None:
        if value is None:
            return None

        return bool(value)

    return {
        "version": 2,
        "is_git": True,

        # Preserve existing public/reporting keys.
        "head": head,
        "branch": branch,
        "status": run_text(
            "status",
            "--short",
        ),
        "diff_stat": run_text(
            "diff",
            "--stat",
        ),

        # Structured checkpoint evidence.
        "head_oid": head,
        "detached": bool(
            head
            and not branch
        ),
        "dirty": presence(
            status_raw
        ),
        "has_staged_changes": presence(
            index_raw
        ),
        "has_unstaged_changes": presence(
            worktree_raw
        ),
        "has_untracked_files": presence(
            untracked_raw
        ),
        "has_conflicts": presence(
            conflicts_raw
        ),

        # Digests allow comparison without storing diff contents.
        "status_digest": _git_digest(
            status_raw
        ),
        "index_digest": _git_digest(
            index_raw
        ),
        "worktree_digest": _git_digest(
            worktree_raw
        ),

        # Explicit semantic boundary.
        "git_metadata_restorable": False,
    }


def compare_git_snapshots(
    checkpoint: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare checkpoint Git evidence conservatively.

    The result is advisory/review-only. It must never cause an
    automatic Git reset, checkout, index rewrite, or ref mutation.
    """
    before = (
        checkpoint
        if isinstance(
            checkpoint,
            dict,
        )
        else {}
    )

    after = (
        current
        if isinstance(
            current,
            dict,
        )
        else {}
    )

    before_is_git = bool(
        before.get(
            "is_git"
        )
    )

    after_is_git = bool(
        after.get(
            "is_git"
        )
    )

    repository_identity_changed = (
        before_is_git
        != after_is_git
    )

    if (
        not before_is_git
        and not after_is_git
    ):
        return {
            "comparable": True,
            "repository_identity_changed": False,
            "head_changed": False,
            "branch_changed": False,
            "index_changed": False,
            "worktree_status_changed": False,
            "git_metadata_changed": False,
            "dirty_before": False,
            "dirty_after": False,
            "requires_git_review": False,
            "git_metadata_restored": False,
        }

    if repository_identity_changed:
        return {
            "comparable": False,
            "repository_identity_changed": True,
            "head_changed": None,
            "branch_changed": None,
            "index_changed": None,
            "worktree_status_changed": None,
            "git_metadata_changed": True,
            "dirty_before": before.get(
                "dirty"
            ),
            "dirty_after": after.get(
                "dirty"
            ),
            "requires_git_review": True,
            "git_metadata_restored": False,
        }

    def digest_changed(
        key: str,
    ) -> bool | None:
        left = str(
            before.get(
                key
            )
            or ""
        )

        right = str(
            after.get(
                key
            )
            or ""
        )

        if (
            not left
            or not right
        ):
            return None

        return left != right

    head_changed = (
        str(
            before.get(
                "head_oid",
                before.get(
                    "head",
                    "",
                ),
            )
            or ""
        )
        !=
        str(
            after.get(
                "head_oid",
                after.get(
                    "head",
                    "",
                ),
            )
            or ""
        )
    )

    branch_changed = (
        str(
            before.get(
                "branch"
            )
            or ""
        )
        !=
        str(
            after.get(
                "branch"
            )
            or ""
        )
    )

    index_changed = (
        digest_changed(
            "index_digest"
        )
    )

    worktree_status_changed = (
        digest_changed(
            "status_digest"
        )
    )

    unknown = any(
        value is None
        for value in {
            index_changed,
            worktree_status_changed,
        }
    )

    git_metadata_changed = (
        head_changed
        or branch_changed
        or index_changed is True
    )

    requires_git_review = (
        git_metadata_changed
        or worktree_status_changed is True
        or unknown
    )

    return {
        "comparable": not unknown,
        "repository_identity_changed": False,
        "head_changed": head_changed,
        "branch_changed": branch_changed,
        "index_changed": index_changed,
        "worktree_status_changed": (
            worktree_status_changed
        ),
        "git_metadata_changed": (
            git_metadata_changed
        ),
        "dirty_before": before.get(
            "dirty"
        ),
        "dirty_after": after.get(
            "dirty"
        ),
        "requires_git_review": (
            requires_git_review
        ),
        "git_metadata_restored": False,
    }
