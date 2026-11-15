from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from git_evidence import (
    capture_stage_baseline,
    git_changed_file_evidence,
    public_stage_baseline,
)

CONTROL_DIR = ".ai-workflow"
ROADMAP_FILE = "ROADMAP.md"
HISTORY_FILE = "HISTORY.md"
STATE_BEGIN = "<!-- AI_WORKFLOW_STATE_BEGIN -->"
STATE_END = "<!-- AI_WORKFLOW_STATE_END -->"

MAX_ACCEPTANCE_CRITERIA_PER_STAGE = 20
MAX_ACCEPTANCE_CRITERION_CHARS = 500
REVIEW_VERSION = 1
REVIEW_STATES = {
    "collecting", "review_required", "accepted", "rejected", "stale",
}


def normalize_roadmap(
    roadmap: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for raw_phase in roadmap or []:
        if not isinstance(
            raw_phase,
            dict,
        ):
            continue

        phase_id = str(
            raw_phase.get("id")
            or ""
        ).strip()

        if not phase_id:
            continue

        title = str(
            raw_phase.get("title")
            or ""
        ).strip()

        stages = [
            str(value).strip()
            for value in (
                raw_phase.get("stages")
                or []
            )
            if str(value).strip()
        ]

        raw_criteria = (
            raw_phase.get(
                "acceptance_criteria"
            )
            or {}
        )

        criteria: dict[str, list[str]] = {}

        if isinstance(
            raw_criteria,
            dict,
        ):
            for stage in stages:
                values = raw_criteria.get(
                    stage
                )

                if isinstance(
                    values,
                    str,
                ):
                    values = [
                        values
                    ]

                if not isinstance(
                    values,
                    list,
                ):
                    continue

                cleaned: list[str] = []

                for value in values:
                    criterion = str(
                        value
                        or ""
                    ).strip()

                    if not criterion:
                        continue

                    criterion = criterion[
                        :MAX_ACCEPTANCE_CRITERION_CHARS
                    ]

                    if criterion not in cleaned:
                        cleaned.append(
                            criterion
                        )

                    if (
                        len(cleaned)
                        >= MAX_ACCEPTANCE_CRITERIA_PER_STAGE
                    ):
                        break

                if cleaned:
                    criteria[
                        stage
                    ] = cleaned

        phase: dict[str, Any] = {
            "id": phase_id,
            "title": title,
            "stages": stages,
        }

        if criteria:
            phase[
                "acceptance_criteria"
            ] = criteria

        normalized.append(
            phase
        )

    return normalized


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


def _acceptance_criteria(
    state: dict[str, Any],
    position: tuple[str, str] | None,
) -> list[str]:
    if not position:
        return []

    phase_id, stage = position

    for phase in (
        state.get("roadmap")
        or []
    ):
        if not isinstance(
            phase,
            dict,
        ):
            continue

        if (
            str(
                phase.get("id")
                or ""
            ).strip()
            != phase_id
        ):
            continue

        raw = (
            phase.get(
                "acceptance_criteria"
            )
            or {}
        )

        if not isinstance(
            raw,
            dict,
        ):
            return []

        values = raw.get(
            stage
        )

        if isinstance(
            values,
            str,
        ):
            values = [
                values
            ]

        if not isinstance(
            values,
            list,
        ):
            return []

        return [
            str(value).strip()
            for value in values
            if str(value).strip()
        ]

    return []


def _stable_digest(value: Any) -> str:
    """Hash structured metadata; source diffs never enter lifecycle state."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _baseline_identity(baseline: Any, phase: str, stage: str) -> str:
    public = public_stage_baseline(baseline, phase, stage)
    return _stable_digest(public) if public is not None else ""


def _review_evidence_identity(evidence: dict[str, Any]) -> str:
    """Use only bounded, display-safe Git evidence for freshness binding."""
    return _stable_digest({
        "available": bool(evidence.get("available")),
        "phase": str(evidence.get("phase") or ""),
        "stage": str(evidence.get("stage") or ""),
        "baseline_head": str(evidence.get("baseline_head") or ""),
        "current_head": str(evidence.get("current_head") or ""),
        "baseline_branch": str(evidence.get("baseline_branch") or ""),
        "current_branch": str(evidence.get("current_branch") or ""),
        "current_status_digest": str(evidence.get("current_status_digest") or ""),
        "files": list(evidence.get("files") or []),
        "truncated": bool(evidence.get("truncated")),
    })


def _review_for_current(state: dict[str, Any]) -> dict[str, Any] | None:
    review = state.get("stage_review")
    return dict(review) if isinstance(review, dict) else None


def _review_freshness(
    workspace_root: str,
    state: dict[str, Any],
    review: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    current = _current_pair(state)
    if not current:
        return False, "project has no current stage", {}
    phase, stage = current
    baseline_identity = _baseline_identity(state.get("stage_baseline"), phase, stage)
    if not baseline_identity:
        return False, "current stage has no valid Git baseline identity", {}
    if (str(review.get("phase") or ""), str(review.get("stage") or "")) != current:
        return False, "review belongs to a different canonical stage", {}
    if str(review.get("stage_baseline_identity") or "") != baseline_identity:
        return False, "stage baseline changed after review collection", {}
    evidence = git_changed_file_evidence(workspace_root, state.get("stage_baseline"))
    if not bool(evidence.get("available")):
        return False, "current Git evidence is unavailable", evidence
    if str(review.get("evidence_identity") or "") != _review_evidence_identity(evidence):
        return False, "Git evidence changed after review collection", evidence
    return True, "", evidence


def _public_review(
    workspace_root: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    review = _review_for_current(state)
    if review is None:
        return None
    fresh, reason, evidence = _review_freshness(workspace_root, state, review)
    status = str(review.get("status") or "review_required")
    if not fresh:
        status = "stale"
    result = dict(review)
    result["status"] = status
    result["evidence_freshness"] = "fresh" if fresh else "stale"
    result["stale_reason"] = reason
    # Recomputed evidence is authoritative for display and prevents stale UI data.
    if evidence:
        result["changed_file_evidence"] = evidence
        result["changed_file_count"] = int(evidence.get("total_files") or 0)
        result["attribution_exact"] = bool(evidence.get("attribution_exact"))
    return result


def collect_stage_review(workspace_root: str) -> dict[str, Any]:
    """Create a new human-review record for exactly the canonical current stage."""
    state = load_project_state(workspace_root)
    if state is None:
        raise ValueError("Project-local roadmap state is not initialized")
    current = _current_pair(state)
    if not current:
        raise ValueError("Project has no current stage to review")
    phase, stage = current
    baseline = public_stage_baseline(state.get("stage_baseline"), phase, stage)
    evidence = git_changed_file_evidence(workspace_root, state.get("stage_baseline")) if baseline else {
        "available": False, "reason": "current stage has no valid Git baseline", "files": [],
    }
    stamp = now_iso()
    criteria = _acceptance_criteria(state, current)
    review: dict[str, Any] = {
        "version": REVIEW_VERSION,
        "review_id": uuid.uuid4().hex,
        "phase": phase,
        "stage": stage,
        "stage_baseline_identity": _baseline_identity(state.get("stage_baseline"), phase, stage),
        "stage_baseline": baseline,
        "baseline_head": str((baseline or {}).get("git", {}).get("head_oid") or ""),
        "current_head": str(evidence.get("current_head") or ""),
        "branch": str(evidence.get("current_branch") or ""),
        "changed_file_evidence": evidence,
        "evidence_identity": _review_evidence_identity(evidence),
        "acceptance_criteria": criteria,
        "criterion_assessments": [
            {"criterion": criterion, "status": "unassessed", "verification_evidence": []}
            for criterion in criteria
        ],
        "verification_evidence": [],
        "attribution_exact": bool(evidence.get("attribution_exact")),
        "evidence_freshness": "fresh" if baseline and evidence.get("available") else "stale",
        "stale_reason": "" if baseline and evidence.get("available") else str(evidence.get("reason") or "missing stage baseline"),
        "status": "review_required" if baseline and evidence.get("available") else "stale",
        "created_at": stamp,
        "updated_at": stamp,
    }
    state["stage_review"] = review
    state["revision"] = int(state.get("revision") or 1) + 1
    state["updated_at"] = stamp
    _write_state(workspace_root, state)
    _, _, history_path = control_paths(workspace_root)
    _append_history(history_path, [f"Stage review collected for `{_label(current)}` ({review['review_id']})."])
    return _public_review(workspace_root, state) or review


def resolve_stage_review(
    workspace_root: str,
    review_id: str,
    decision: str,
    expected_phase: str = "",
    expected_stage: str = "",
) -> dict[str, Any]:
    """Apply an explicit human decision only to the exact fresh review shown."""
    state = load_project_state(workspace_root)
    if state is None:
        raise ValueError("Project-local roadmap state is not initialized")
    review = _review_for_current(state)
    if review is None or str(review.get("review_id") or "") != str(review_id or ""):
        raise ValueError("Stage review identity is stale or missing; refresh before deciding")
    if expected_phase and str(review.get("phase") or "") != str(expected_phase):
        raise ValueError("Stage review phase identity is stale or mismatched")
    if expected_stage and str(review.get("stage") or "") != str(expected_stage):
        raise ValueError("Stage review stage identity is stale or mismatched")
    value = str(decision or "").strip().lower()
    if value not in {"accept", "reject"}:
        raise ValueError("Stage review decision must be accept or reject")
    fresh, reason, _ = _review_freshness(workspace_root, state, review)
    if not fresh:
        review["status"] = "stale"
        review["evidence_freshness"] = "stale"
        review["stale_reason"] = reason
        review["updated_at"] = now_iso()
        state["stage_review"] = review
        _write_state(workspace_root, state)
        raise ValueError("Stage review is stale; collect and review current evidence")
    review["status"] = "accepted" if value == "accept" else "rejected"
    review["human_decision"] = value
    review["human_decided_at"] = now_iso()
    review["updated_at"] = review["human_decided_at"]
    state["stage_review"] = review
    state["revision"] = int(state.get("revision") or 1) + 1
    state["updated_at"] = review["updated_at"]
    _write_state(workspace_root, state)
    _, _, history_path = control_paths(workspace_root)
    _append_history(history_path, [f"Human {value}ed stage review `{review['review_id']}` for `{_label(_current_pair(state))}`."])
    return _public_review(workspace_root, state) or review


def current_stage_review_is_accepted(workspace_root: str, state: dict[str, Any] | None = None) -> bool:
    state = state if state is not None else load_project_state(workspace_root)
    if state is None:
        return False
    review = _review_for_current(state)
    if review is None or str(review.get("status") or "") != "accepted":
        return False
    fresh, _, _ = _review_freshness(workspace_root, state, review)
    return fresh


def reconcile_stage_review_freshness(workspace_root: str) -> dict[str, Any] | None:
    """Durably downgrade a stale review; it never upgrades or accepts one."""
    state = load_project_state(workspace_root)
    if state is None:
        return None
    review = _review_for_current(state)
    public = _public_review(workspace_root, state)
    if review is not None and public is not None and public.get("status") == "stale" and review.get("status") != "stale":
        review["status"] = "stale"
        review["evidence_freshness"] = "stale"
        review["stale_reason"] = str(public.get("stale_reason") or "evidence changed")
        review["updated_at"] = now_iso()
        state["stage_review"] = review
        state["revision"] = int(state.get("revision") or 1) + 1
        state["updated_at"] = review["updated_at"]
        _write_state(workspace_root, state)
        return _public_review(workspace_root, state)
    return public


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

            criteria = _acceptance_criteria(
                state,
                pair,
            )

            for criterion in criteria:
                lines.append(
                    f"  - Acceptance: {criterion}"
                )

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
        "current_acceptance_criteria": (
            _acceptance_criteria(
                state,
                current,
            )
        ),
        "stage_baseline": (
            public_stage_baseline(
                state.get("stage_baseline"),
                current[0],
                current[1],
            )
            if current
            else None
        ),
        "stage_review": _public_review(
            workspace_root,
            state,
        ) if current else None,
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
    roadmap = normalize_roadmap(
        roadmap
    )

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
        "stage_baseline": capture_stage_baseline(
            workspace_root,
            current[0],
            current[1],
            stamp,
        ),
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
    if not current_stage_review_is_accepted(workspace_root, state):
        raise ValueError(
            "Current stage requires an exact fresh human-accepted structured review before transition"
        )

    completed = _completed_pairs(state)
    if current not in completed:
        completed.append(current)
    state["completed"] = [{"phase": p, "stage": s} for p, s in completed]
    stamp = now_iso()
    state["current"] = {"phase": target[0], "stage": target[1]}
    state["stage_baseline"] = capture_stage_baseline(
        workspace_root,
        target[0],
        target[1],
        stamp,
    )
    # A review is inseparable from the completed stage and must never travel
    # with the lifecycle cursor.
    state.pop("stage_review", None)
    state["status"] = "active"
    state["revision"] = int(state.get("revision") or 1) + 1
    state["updated_at"] = stamp
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

    roadmap = normalize_roadmap(
        list(
            replacement_roadmap
            or state.get("roadmap")
            or []
        )
    )

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
    stamp = now_iso()
    state["current"] = {"phase": current[0], "stage": current[1]}
    state["stage_baseline"] = capture_stage_baseline(
        workspace_root,
        current[0],
        current[1],
        stamp,
    )
    # Roadmap replacement establishes a new canonical stage identity.
    state.pop("stage_review", None)
    state["status"] = "active"
    state["revision"] = int(state.get("revision") or 1) + 1
    state["updated_at"] = stamp
    _write_state(workspace_root, state)
    _, _, history_path = control_paths(workspace_root)
    _append_history(history_path, [f"Course change approved: {summary}.", f"Current roadmap position is `{_label(current)}`."])
    return project_state_summary(workspace_root, state)
