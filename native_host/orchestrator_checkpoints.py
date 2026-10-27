from __future__ import annotations

from pathlib import Path
from typing import Any

from checkpoint_restore import (
    restore_workspace_snapshot,
)
from recovery import recovery_summary
from redaction import redact_text
from runner import (
    compare_git_snapshots,
    git_snapshot,
)


class CheckpointControlMixin:
    def _checkpoint_workspace(
        self,
    ) -> str:
        raw = str(
            self.config.get(
                "workspace_root"
            )
            or ""
        ).strip()

        if not raw:
            raise ValueError(
                "Workspace root is not configured"
            )

        return str(
            Path(
                raw
            ).expanduser().resolve()
        )

    def _latest_ready_checkpoint(
        self,
    ) -> dict[str, Any] | None:
        workspace = (
            self._checkpoint_workspace()
        )

        items = self.store.list_checkpoints(
            workspace_root=workspace,
            status="ready",
            limit=1,
        )

        if not items:
            return None

        return items[0]

    def _ready_checkpoint_by_id(
        self,
        checkpoint_id: str,
    ) -> dict[str, Any] | None:
        selected_id = str(
            checkpoint_id or ""
        ).strip()

        if not selected_id:
            raise ValueError(
                "Checkpoint id is required"
            )

        checkpoint = (
            self.store.get_checkpoint(
                selected_id
            )
        )

        if checkpoint is None:
            return None

        workspace = (
            self._checkpoint_workspace()
        )

        checkpoint_workspace = str(
            Path(
                str(
                    checkpoint.get(
                        "workspace_root"
                    )
                    or ""
                )
            ).expanduser().resolve()
        )

        if checkpoint_workspace != workspace:
            return None

        if (
            str(
                checkpoint.get(
                    "status"
                )
                or ""
            )
            != "ready"
        ):
            return None

        return checkpoint

    def _checkpoint_control_error(
        self,
        text: str,
    ) -> None:
        self.emit_event({
            "kind": "error",
            "badge": "CHECKPOINT",
            "status": str(
                getattr(
                    self,
                    "status",
                    "idle",
                )
            ),
            "text": str(text),
        })

    def public_checkpoint_state(
        self,
    ) -> dict[str, Any]:
        try:
            workspace = (
                self._checkpoint_workspace()
            )

            ready = (
                self.store.list_checkpoints(
                    workspace_root=workspace,
                    status="ready",
                    limit=1,
                )
            )

            if ready:
                checkpoint = ready[0]
            else:
                latest = (
                    self.store.list_checkpoints(
                        workspace_root=workspace,
                        limit=1,
                    )
                )

                if not latest:
                    return {
                        "available": False,
                    }

                checkpoint = latest[0]

            command = dict(
                checkpoint.get(
                    "command"
                )
                or {}
            )

            snapshot = dict(
                checkpoint.get(
                    "snapshot"
                )
                or {}
            )

            limitations = (
                snapshot.get(
                    "rollback_limitations"
                )
            )

            if not isinstance(
                limitations,
                list,
            ):
                limitations = []

            status = str(
                checkpoint.get(
                    "status"
                )
                or ""
            )

            git_state = dict(
                checkpoint.get(
                    "git"
                )
                or {}
            )

            git_review = dict(
                checkpoint.get(
                    "git_review"
                )
                or {}
            )

            public_git = {
                "is_git": bool(
                    git_state.get(
                        "is_git"
                    )
                ),
                "branch": str(
                    git_state.get(
                        "branch"
                    )
                    or ""
                ),
                "head_short": str(
                    git_state.get(
                        "head_oid",
                        git_state.get(
                            "head",
                            "",
                        ),
                    )
                    or ""
                )[:12],
                "detached": bool(
                    git_state.get(
                        "detached"
                    )
                ),
                "dirty": (
                    git_state.get(
                        "dirty"
                    )
                ),
                "has_staged_changes": (
                    git_state.get(
                        "has_staged_changes"
                    )
                ),
                "has_unstaged_changes": (
                    git_state.get(
                        "has_unstaged_changes"
                    )
                ),
                "has_untracked_files": (
                    git_state.get(
                        "has_untracked_files"
                    )
                ),
                "has_conflicts": (
                    git_state.get(
                        "has_conflicts"
                    )
                ),
                "git_metadata_restorable": False,
            }

            public_git_review = {}

            if git_review:
                public_git_review = {
                    "comparable": (
                        git_review.get(
                            "comparable"
                        )
                    ),
                    "repository_identity_changed": (
                        git_review.get(
                            "repository_identity_changed"
                        )
                    ),
                    "head_changed": (
                        git_review.get(
                            "head_changed"
                        )
                    ),
                    "branch_changed": (
                        git_review.get(
                            "branch_changed"
                        )
                    ),
                    "index_changed": (
                        git_review.get(
                            "index_changed"
                        )
                    ),
                    "worktree_status_changed": (
                        git_review.get(
                            "worktree_status_changed"
                        )
                    ),
                    "git_metadata_changed": (
                        git_review.get(
                            "git_metadata_changed"
                        )
                    ),
                    "dirty_before": (
                        git_review.get(
                            "dirty_before"
                        )
                    ),
                    "dirty_after": (
                        git_review.get(
                            "dirty_after"
                        )
                    ),
                    "requires_git_review": bool(
                        git_review.get(
                            "requires_git_review"
                        )
                    ),
                    "git_metadata_restored": False,
                    "inspection_error": bool(
                        git_review.get(
                            "inspection_error"
                        )
                    ),
                }

            execution_active = bool(
                getattr(
                    self,
                    "command_execution_active",
                    False,
                )
            )

            recovery_required = (
                str(
                    getattr(
                        self,
                        "lifecycle",
                        "",
                    )
                )
                == "recovery_required"
            )

            paused = bool(
                getattr(
                    self,
                    "paused",
                    False,
                )
            )

            return {
                "available": True,
                "checkpoint_id": str(
                    checkpoint.get(
                        "checkpoint_id"
                    )
                    or ""
                ),
                "created_at": str(
                    checkpoint.get(
                        "created_at"
                    )
                    or ""
                ),
                "status": status,
                "command_summary": str(
                    command.get(
                        "summary"
                    )
                    or ""
                ),
                "risk_level": str(
                    command.get(
                        "risk_level"
                    )
                    or ""
                ),
                "rollback_scope": str(
                    snapshot.get(
                        "rollback_scope"
                    )
                    or "workspace_files_only"
                ),
                "file_count": int(
                    snapshot.get(
                        "file_count"
                    )
                    or 0
                ),
                "total_bytes": int(
                    snapshot.get(
                        "total_bytes"
                    )
                    or 0
                ),
                "limitations": [
                    str(item)
                    for item in limitations
                    if str(item).strip()
                ],
                "can_accept": (
                    status == "ready"
                    and not execution_active
                    and not recovery_required
                ),
                "can_rollback": (
                    status == "ready"
                    and paused
                    and not execution_active
                    and not recovery_required
                ),
                "rollback_requires_pause": (
                    status == "ready"
                    and not paused
                ),
                "execution_active": (
                    execution_active
                ),
                "git": public_git,
                "git_review_available": bool(
                    public_git_review
                ),
                "git_review": (
                    public_git_review
                ),
            }

        except Exception as error:
            return {
                "available": False,
                "error": redact_text(
                    str(error)
                ),
            }


    def accept_checkpoint(
        self,
        checkpoint_id: str,
    ) -> bool:
        if bool(
            getattr(
                self,
                "command_execution_active",
                False,
            )
        ):
            self._checkpoint_control_error(
                "A local command is currently executing. "
                "The checkpoint cannot be accepted until "
                "that command finishes."
            )
            return False

        with self.lock:
            if bool(
                getattr(
                    self,
                    "command_execution_active",
                    False,
                )
            ):
                self._checkpoint_control_error(
                    "A local command started before the "
                    "checkpoint action could be completed."
                )
                return False

            try:
                checkpoint = (
                    self._ready_checkpoint_by_id(
                        checkpoint_id
                    )
                )
            except Exception as error:
                self._checkpoint_control_error(
                    "Could not inspect checkpoints: "
                    + redact_text(
                        str(error)
                    )
                )
                return False

            if checkpoint is None:
                self._checkpoint_control_error(
                    "The requested checkpoint is not ready "
                    "for the current workspace. Refresh "
                    "Mission Control before deciding."
                )
                return False

            checkpoint_id = str(
                checkpoint[
                    "checkpoint_id"
                ]
            )

            if not self.store.transition_checkpoint_status(
                checkpoint_id,
                expected_status="ready",
                new_status="accepted",
            ):
                self._checkpoint_control_error(
                    "Checkpoint state changed before it "
                    "could be accepted. Refresh and review "
                    "the current checkpoint state."
                )
                return False

            self.emit_event({
                "kind": "checkpoint_accepted",
                "badge": "KEEP",
                "status": "accepted",
                "checkpoint_id": checkpoint_id,
                "text": (
                    "Checkpoint accepted. The current "
                    "workspace state is being kept."
                ),
            })

            self.emit({
                "kind": "state",
                "state": self.state(),
            })

            return True

    def rollback_checkpoint(
        self,
        checkpoint_id: str,
    ) -> bool:
        if bool(
            getattr(
                self,
                "command_execution_active",
                False,
            )
        ):
            self._checkpoint_control_error(
                "Rollback is forbidden while a local "
                "command is executing."
            )
            return False

        if not bool(
            getattr(
                self,
                "paused",
                False,
            )
        ):
            self._checkpoint_control_error(
                "Pause the workflow before rollback. "
                "Rollback never interrupts an active run."
            )
            return False

        with self.lock:
            if bool(
                getattr(
                    self,
                    "command_execution_active",
                    False,
                )
            ):
                self._checkpoint_control_error(
                    "Rollback is forbidden while a local "
                    "command is executing."
                )
                return False

            if not bool(
                getattr(
                    self,
                    "paused",
                    False,
                )
            ):
                self._checkpoint_control_error(
                    "The workflow is no longer paused. "
                    "Rollback was not started."
                )
                return False

            try:
                checkpoint = (
                    self._ready_checkpoint_by_id(
                        checkpoint_id
                    )
                )
            except Exception as error:
                self._checkpoint_control_error(
                    "Could not inspect checkpoints: "
                    + redact_text(
                        str(error)
                    )
                )
                return False

            if checkpoint is None:
                self._checkpoint_control_error(
                    "The requested checkpoint is not ready "
                    "for the current workspace. Refresh "
                    "Mission Control before deciding."
                )
                return False

            checkpoint_id = str(
                checkpoint[
                    "checkpoint_id"
                ]
            )

            snapshot = dict(
                checkpoint.get(
                    "snapshot"
                )
                or {}
            )

            workspace = (
                self._checkpoint_workspace()
            )

            previous = {
                "paused": self.paused,
                "lifecycle": self.lifecycle,
                "status": self.status,
                "current_step": self.current_step,
            }

            # Crash boundary for rollback itself. A restart
            # from this point must require explicit recovery
            # review and must never replay the rollback.
            self.paused = True
            self.lifecycle = "recovering"
            self.status = "recovering"
            self.current_step = (
                "Rolling back workspace checkpoint"
            )

            self._persist_runtime_state()

            claimed = (
                self.store.transition_checkpoint_status(
                    checkpoint_id,
                    expected_status="ready",
                    new_status="rolling_back",
                )
            )

            if not claimed:
                self.paused = bool(
                    previous["paused"]
                )
                self.lifecycle = str(
                    previous["lifecycle"]
                )
                self.status = str(
                    previous["status"]
                )
                self.current_step = str(
                    previous["current_step"]
                )

                self._persist_runtime_state()

                self._checkpoint_control_error(
                    "Checkpoint state changed before "
                    "rollback could claim it. No rollback "
                    "was performed."
                )
                return False

            command = dict(
                checkpoint.get(
                    "command"
                )
                or {}
            )

            self.checkpoint_recovery_context = {
                "checkpoint_id": checkpoint_id,
                "status": "rolling_back",
                "rollback_scope": str(
                    snapshot.get(
                        "rollback_scope"
                    )
                    or "workspace_files_only"
                ),
                "command_summary": str(
                    command.get(
                        "summary"
                    )
                    or ""
                ),
                "risk_level": str(
                    command.get(
                        "risk_level"
                    )
                    or ""
                ),
                "uncertain": True,
                "note": (
                    "Rollback was claimed but its "
                    "completion is not yet durable."
                ),
            }

            # Second crash boundary: the checkpoint identity
            # and rolling_back state are persisted before any
            # workspace restoration begins.
            self._persist_runtime_state()

            try:
                report = (
                    restore_workspace_snapshot(
                        metadata=snapshot,
                        workspace_root=workspace,
                    )
                )

                checkpoint_git = dict(
                    checkpoint.get(
                        "git"
                    )
                    or {}
                )

                try:
                    current_git = git_snapshot(
                        workspace
                    )

                    git_review = (
                        compare_git_snapshots(
                            checkpoint_git,
                            current_git,
                        )
                    )

                    git_review[
                        "inspection_error"
                    ] = False

                except Exception as git_error:
                    # Git inspection is advisory. A successful
                    # workspace restore must not be converted into
                    # rollback failure merely because Git evidence
                    # could not be inspected.
                    git_review = {
                        "comparable": False,
                        "repository_identity_changed": None,
                        "head_changed": None,
                        "branch_changed": None,
                        "index_changed": None,
                        "worktree_status_changed": None,
                        "git_metadata_changed": None,
                        "dirty_before": (
                            checkpoint_git.get(
                                "dirty"
                            )
                        ),
                        "dirty_after": None,
                        "requires_git_review": True,
                        "git_metadata_restored": False,
                        "inspection_error": True,
                        "inspection_error_detail": (
                            redact_text(
                                str(
                                    git_error
                                )
                            )
                        ),
                    }

                report[
                    "git_review"
                ] = git_review

                checkpoint_with_review = {
                    **checkpoint,
                    "status": "rolling_back",
                    "git_review": git_review,
                }

                # Preserve post-restore Git evidence in the
                # checkpoint record before marking rollback
                # durably complete. This is review metadata
                # only and never rewrites .git.
                self.store.put_checkpoint(
                    checkpoint_with_review
                )

                completed = (
                    self.store.transition_checkpoint_status(
                        checkpoint_id,
                        expected_status="rolling_back",
                        new_status="rolled_back",
                    )
                )

                if not completed:
                    raise RuntimeError(
                        "Rollback restored the workspace, "
                        "but checkpoint completion could "
                        "not be persisted"
                    )

            except Exception as error:
                try:
                    self.store.transition_checkpoint_status(
                        checkpoint_id,
                        expected_status="rolling_back",
                        new_status="rollback_failed",
                    )
                except Exception:
                    pass

                # Fail closed. Do not retry or continue the
                # interrupted workflow automatically.
                self.status = "rollback_failed"
                self.lifecycle = "recovering"
                self.current_step = (
                    "Checkpoint rollback requires "
                    "recovery review"
                )
                self.paused = True

                self.checkpoint_recovery_context = {
                    **dict(
                        self.checkpoint_recovery_context
                        or {}
                    ),
                    "checkpoint_id": checkpoint_id,
                    "status": "rollback_failed",
                    "uncertain": True,
                    "note": (
                        "Rollback failed or its completion "
                        "could not be persisted safely."
                    ),
                }

                failed_snapshot = (
                    self._runtime_snapshot()
                )

                self.recovery_context = (
                    recovery_summary(
                        failed_snapshot
                    )
                )

                self.lifecycle = (
                    "recovery_required"
                )
                self.status = (
                    "recovery_required"
                )

                detail = redact_text(
                    str(error)
                )

                self.emit_event({
                    "kind": "error",
                    "badge": "ROLLBACK!",
                    "status": (
                        "recovery_required"
                    ),
                    "checkpoint_id": (
                        checkpoint_id
                    ),
                    "text": (
                        "Checkpoint rollback did not "
                        "complete safely. Automation is "
                        "stopped and explicit recovery "
                        "review is required. No automatic "
                        f"retry will occur. Error: {detail}"
                    ),
                })

                self.emit({
                    "kind": "state",
                    "state": self.state(),
                })

                return False

            self.checkpoint_recovery_context = None

            self.paused = True
            self.lifecycle = "paused"
            self.status = "paused"
            self.current_step = (
                "Workspace checkpoint rolled back; "
                "review before resuming"
            )

            git_review = dict(
                report.get(
                    "git_review"
                )
                or {}
            )

            requires_git_review = bool(
                git_review.get(
                    "requires_git_review"
                )
            )

            if requires_git_review:
                rollback_text = (
                    "Workspace-file rollback completed, "
                    "but Git state differs from or could "
                    "not be safely compared with the "
                    "checkpoint. Git metadata was NOT "
                    "restored. Review Git state manually "
                    "before resuming."
                )
            else:
                rollback_text = (
                    "Workspace-file rollback completed. "
                    "Recorded Git evidence matches the "
                    "checkpoint, but Git metadata was NOT "
                    "rewritten or restored. Remote, "
                    "database, system, and native "
                    "lifecycle side effects remain "
                    "outside rollback scope."
                )

            self.emit_event({
                "kind": "checkpoint_rolled_back",
                "badge": (
                    "GIT?"
                    if requires_git_review
                    else "UNDO"
                ),
                "status": "rolled_back",
                "checkpoint_id": checkpoint_id,
                "rollback_scope": str(
                    report.get(
                        "rollback_scope"
                    )
                    or "workspace_files_only"
                ),
                "restored_files": int(
                    report.get(
                        "restored_files"
                    )
                    or 0
                ),
                "removed_entries": int(
                    report.get(
                        "removed_entries"
                    )
                    or 0
                ),
                "git_review": git_review,
                "git_review_required": (
                    requires_git_review
                ),
                "git_metadata_restored": False,
                "text": rollback_text,
            })

            self.emit({
                "kind": "state",
                "state": self.state(),
            })

            return True
