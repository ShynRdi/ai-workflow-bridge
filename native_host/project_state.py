from __future__ import annotations

import errno
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTROL_DIR = ".ai-workflow"
ROADMAP_FILE = "ROADMAP.md"
HISTORY_FILE = "HISTORY.md"
STATE_BEGIN = "<!-- AI_WORKFLOW_STATE_BEGIN -->"
STATE_END = "<!-- AI_WORKFLOW_STATE_END -->"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_regular_or_missing(path: Path, label: str) -> None:
    """Reject symlink and non-regular state-file entries."""
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    if path.exists() and not path.is_file():
        raise ValueError(f"{label} must be a regular file")


def _validate_control_layout(
    root: Path,
    control: Path,
    roadmap_path: Path,
    history_path: Path,
) -> None:
    """Ensure native-owned state paths cannot escape through symlinks."""
    if control.is_symlink():
        raise ValueError(f"{CONTROL_DIR} must not be a symbolic link")

    if control.exists() and not control.is_dir():
        raise ValueError(f"{CONTROL_DIR} must be a directory")

    try:
        control.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"{CONTROL_DIR} escapes the configured workspace"
        ) from error

    _ensure_regular_or_missing(roadmap_path, ROADMAP_FILE)
    _ensure_regular_or_missing(history_path, HISTORY_FILE)


def control_paths(workspace_root: str) -> tuple[Path, Path, Path]:
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Workspace does not exist: {root}")

    control = root / CONTROL_DIR
    roadmap_path = control / ROADMAP_FILE
    history_path = control / HISTORY_FILE

    _validate_control_layout(
        root,
        control,
        roadmap_path,
        history_path,
    )

    return control, roadmap_path, history_path


def _positions(roadmap: list[dict[str, Any]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for phase in roadmap or []:
        if not isinstance(phase, dict):
            continue
        phase_id = str(phase.get("id") or "").strip()
        if not phase_id:
            continue
        stages = [str(x).strip() for x in (phase.get("stages") or []) if str(x).strip()]
        if stages:
            out.extend((phase_id, stage) for stage in stages)
        else:
            out.append((phase_id, ""))
    return out


def _label(position: tuple[str, str] | None) -> str:
    if not position:
        return "—"
    phase, stage = position
    return f"{phase} / {stage}" if stage else phase


def _safe_read_text(path: Path, label: str) -> str:
    """Read a native-owned regular file without following a final symlink."""
    _ensure_regular_or_missing(path, label)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)

    try:
        fd = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError(
                f"{label} must not be a symbolic link"
            ) from error
        raise

    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError(f"{label} must be a regular file")

        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_regular_or_missing(path, path.name)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        # Re-check before replacement. os.replace replaces a symlink entry
        # rather than following it, but native-owned paths reject symlinks
        # explicitly so corruption is surfaced instead of silently repaired.
        _ensure_regular_or_missing(path, path.name)
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _append_history(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_regular_or_missing(path, HISTORY_FILE)

    if path.exists():
        text = _safe_read_text(path, HISTORY_FILE)
    else:
        text = (
            "# AI Workflow History\n\n"
            "Append-only project lifecycle history managed by "
            "AI Workflow Bridge.\n\n"
        )

    stamp = now_iso()
    appended = [f"## {stamp}"]
    appended.extend(f"- {line}" for line in lines)
    appended.append("")

    if text and not text.endswith("\n"):
        text += "\n"

    _atomic_write(
        path,
        text + "\n".join(appended) + "\n",
    )


def _completed_pairs(state: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in state.get("completed") or []:
        if isinstance(item, dict):
            pair = (str(item.get("phase") or "").strip(), str(item.get("stage") or "").strip())
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            pair = (str(item[0]).strip(), str(item[1]).strip())
        else:
            continue
        if pair[0] and pair not in out:
            out.append(pair)
    return out


def _current_pair(state: dict[str, Any]) -> tuple[str, str] | None:
    current = state.get("current") or {}
    if not isinstance(current, dict):
        return None
    phase = str(current.get("phase") or "").strip()
    stage = str(current.get("stage") or "").strip()
    return (phase, stage) if phase else None


def _next_pair(state: dict[str, Any]) -> tuple[str, str] | None:
    current = _current_pair(state)
    positions = _positions(list(state.get("roadmap") or []))
    if not current or current not in positions:
        return None
    index = positions.index(current)
    return positions[index + 1] if index + 1 < len(positions) else None


def _render_roadmap(state: dict[str, Any]) -> str:
    roadmap = list(state.get("roadmap") or [])
    completed = set(_completed_pairs(state))
    current = _current_pair(state)
    nxt = _next_pair(state)
    positions = _positions(roadmap)
    status = str(state.get("status") or "active")

    lines = [
        "# AI Workflow Roadmap",
        "",
        "> Managed by AI Workflow Bridge. The native host is authoritative for lifecycle changes.",
        "",
        f"**Status:** `{status}`",
        f"**Current:** `{_label(current)}`",
        f"**Next:** `{_label(nxt)}`",
        f"**Progress:** `{len(completed)} / {len(positions)}` stages completed",
        "",
        "## Roadmap",
        "",
    ]
    for phase in roadmap:
        phase_id = str((phase or {}).get("id") or "").strip()
        if not phase_id:
            continue
        title = str((phase or {}).get("title") or "").strip()
        lines.append(f"### {phase_id}{f' — {title}' if title else ''}")
        stages = [str(x).strip() for x in ((phase or {}).get("stages") or []) if str(x).strip()]
        if not stages:
            stages = [""]
        for stage in stages:
            pair = (phase_id, stage)
            marker = "x" if pair in completed else ">" if pair == current else " "
            lines.append(f"- [{marker}] `{_label(pair)}`")
        lines.append("")

    machine = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    lines.extend([
        "## Machine State",
        "",
        "This block is parsed by AI Workflow Bridge. Do not edit it manually while a run is active.",
        "",
        STATE_BEGIN,
        machine,
        STATE_END,
        "",
    ])
    return "\n".join(lines)


def _write_state(workspace_root: str, state: dict[str, Any]) -> None:
    _, roadmap_path, _ = control_paths(workspace_root)
    _atomic_write(roadmap_path, _render_roadmap(state))


def load_project_state(workspace_root: str) -> dict[str, Any] | None:
    _, roadmap_path, _ = control_paths(workspace_root)
    if not roadmap_path.exists():
        return None
    text = _safe_read_text(roadmap_path, ROADMAP_FILE)
    if STATE_BEGIN not in text or STATE_END not in text:
        raise ValueError(f"{ROADMAP_FILE} is missing its machine-state block")
    raw = text.rsplit(STATE_BEGIN, 1)[1].split(STATE_END, 1)[0].strip()
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("roadmap"), list):
        raise ValueError(f"{ROADMAP_FILE} contains invalid project state")
    return data


def project_state_summary(workspace_root: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    control, roadmap_path, history_path = control_paths(workspace_root)
    state = state if state is not None else load_project_state(workspace_root)
    if state is None:
        return {
            "exists": False,
            "status": "unplanned",
            "current": None,
            "next": None,
            "completed": 0,
            "total": 0,
            "control_dir": str(control),
            "roadmap_path": str(roadmap_path),
            "history_path": str(history_path),
        }
    completed = _completed_pairs(state)
    current = _current_pair(state)
    nxt = _next_pair(state)
    positions = _positions(list(state.get("roadmap") or []))
    return {
        "exists": True,
        "status": str(state.get("status") or "active"),
        "revision": int(state.get("revision") or 1),
        "current": {"phase": current[0], "stage": current[1], "label": _label(current)} if current else None,
        "next": {"phase": nxt[0], "stage": nxt[1], "label": _label(nxt)} if nxt else None,
        "completed": len(completed),
        "total": len(positions),
        "control_dir": str(control),
        "roadmap_path": str(roadmap_path),
        "history_path": str(history_path),
    }


def initialize_project_state(
    workspace_root: str,
    roadmap: list[dict[str, Any]],
    preferred_phase: str = "",
    preferred_stage: str = "",
    reason: str = "project planned",
) -> dict[str, Any]:
    positions = _positions(roadmap)
    if not positions:
        raise ValueError("Roadmap has no executable phase/stage positions")
    preferred = (str(preferred_phase or "").strip(), str(preferred_stage or "").strip())
    current = preferred if preferred[0] and preferred in positions else positions[0]
    stamp = now_iso()
    state: dict[str, Any] = {
        "version": 1,
        "revision": 1,
        "status": "active",
        "created_at": stamp,
        "updated_at": stamp,
        "roadmap": roadmap,
        "current": {"phase": current[0], "stage": current[1]},
        "completed": [],
    }
    _write_state(workspace_root, state)
    _, _, history_path = control_paths(workspace_root)
    _append_history(history_path, [f"Roadmap initialized: {reason}.", f"Started `{_label(current)}`."])
    return project_state_summary(workspace_root, state)


def ensure_project_state(
    workspace_root: str,
    roadmap: list[dict[str, Any]] | None = None,
    preferred_phase: str = "",
    preferred_stage: str = "",
) -> dict[str, Any]:
    state = load_project_state(workspace_root)
    if state is None:
        if not roadmap:
            return project_state_summary(workspace_root, None)
        return initialize_project_state(workspace_root, roadmap, preferred_phase, preferred_stage, reason="migrated from Bridge configuration")
    return project_state_summary(workspace_root, state)


def advance_project_state(workspace_root: str, target_phase: str, target_stage: str) -> dict[str, Any]:
    state = load_project_state(workspace_root)
    if state is None:
        raise ValueError("Project-local roadmap state is not initialized")
    positions = _positions(list(state.get("roadmap") or []))
    current = _current_pair(state)
    target = (str(target_phase or "").strip(), str(target_stage or "").strip())
    if not current or current not in positions:
        raise ValueError("Current roadmap position is invalid")
    if target == current:
        return project_state_summary(workspace_root, state)
    index = positions.index(current)
    expected = positions[index + 1] if index + 1 < len(positions) else None
    if target != expected:
        raise ValueError(f"Only the immediate next roadmap position is allowed; expected {_label(expected)}")

    completed = _completed_pairs(state)
    if current not in completed:
        completed.append(current)
    state["completed"] = [{"phase": p, "stage": s} for p, s in completed]
    state["current"] = {"phase": target[0], "stage": target[1]}
    state["status"] = "active"
    state["revision"] = int(state.get("revision") or 1) + 1
    state["updated_at"] = now_iso()
    _write_state(workspace_root, state)
    _, _, history_path = control_paths(workspace_root)
    _append_history(history_path, [f"Completed `{_label(current)}`.", f"Started `{_label(target)}`."])
    return project_state_summary(workspace_root, state)


def complete_project_state(workspace_root: str) -> dict[str, Any]:
    state = load_project_state(workspace_root)
    if state is None:
        raise ValueError("Project-local roadmap state is not initialized")
    current = _current_pair(state)
    completed = _completed_pairs(state)
    if current and current not in completed:
        completed.append(current)
    state["completed"] = [{"phase": p, "stage": s} for p, s in completed]
    state["current"] = None
    state["status"] = "complete"
    state["revision"] = int(state.get("revision") or 1) + 1
    state["updated_at"] = now_iso()
    _write_state(workspace_root, state)
    _, _, history_path = control_paths(workspace_root)
    lines = [f"Completed `{_label(current)}`."] if current else []
    lines.append("Project marked complete after guarded closeout.")
    _append_history(history_path, lines)
    return project_state_summary(workspace_root, state)


def apply_course_change(
    workspace_root: str,
    replacement_roadmap: list[dict[str, Any]] | None,
    proposed_phase: str = "",
    proposed_stage: str = "",
    summary: str = "approved course change",
) -> dict[str, Any]:
    state = load_project_state(workspace_root)
    if state is None:
        if not replacement_roadmap:
            raise ValueError("Project-local roadmap state is not initialized")
        return initialize_project_state(workspace_root, replacement_roadmap, proposed_phase, proposed_stage, reason=summary)

    roadmap = list(replacement_roadmap or state.get("roadmap") or [])
    positions = _positions(roadmap)
    if not positions:
        raise ValueError("Approved replacement roadmap has no positions")
    completed = [pair for pair in _completed_pairs(state) if pair in positions]
    proposed = (str(proposed_phase or "").strip(), str(proposed_stage or "").strip())
    old_current = _current_pair(state)
    if proposed[0] and proposed in positions:
        current = proposed
    elif old_current and old_current in positions and old_current not in completed:
        current = old_current
    else:
        current = next((pair for pair in positions if pair not in completed), positions[0])

    state["roadmap"] = roadmap
    state["completed"] = [{"phase": p, "stage": s} for p, s in completed]
    state["current"] = {"phase": current[0], "stage": current[1]}
    state["status"] = "active"
    state["revision"] = int(state.get("revision") or 1) + 1
    state["updated_at"] = now_iso()
    _write_state(workspace_root, state)
    _, _, history_path = control_paths(workspace_root)
    _append_history(history_path, [f"Course change approved: {summary}.", f"Current roadmap position is `{_label(current)}`."])
    return project_state_summary(workspace_root, state)
