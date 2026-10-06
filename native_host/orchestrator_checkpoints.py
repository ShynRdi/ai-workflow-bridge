from __future__ import annotations

from pathlib import Path
from typing import Any

from checkpoint_restore import (
    restore_workspace_snapshot,
)
from recovery import recovery_summary
from redaction import redact_text


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

    def accept_latest_checkpoint(
        self,
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
                    self._latest_ready_checkpoint()
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
                    "There is no ready checkpoint for "
                    "the current workspace."
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

    def rollback_latest_checkpoint(
        self,
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
                    self._latest_ready_checkpoint()
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
                    "There is no ready checkpoint for "
                    "the current workspace."
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

            self.emit_event({
                "kind": "checkpoint_rolled_back",
                "badge": "UNDO",
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
                "text": (
                    "Workspace-file rollback completed. "
                    "Git metadata, remote effects, "
                    "database changes, system changes, "
                    "and native lifecycle state were "
                    "not reversed."
                ),
            })

            self.emit({
                "kind": "state",
                "state": self.state(),
            })

            return True
