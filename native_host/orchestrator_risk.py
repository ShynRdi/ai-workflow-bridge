from __future__ import annotations

from dataclasses import asdict
from typing import Any

from checkpoint import build_checkpoint_metadata
from checkpoint_snapshot import (
    create_workspace_snapshot,
    remove_workspace_snapshot,
)
from policy import classify, merge_risk
from redaction import redact_text
from runner import git_snapshot, run_command


class RiskAwareExecutionMixin:
    @staticmethod
    def _risk_requires_checkpoint(
        risk_level: str,
    ) -> bool:
        return (
            str(risk_level or "")
            .strip()
            .upper()
            in {"R2", "R3"}
        )

    def _create_command_checkpoint(
        self,
        *,
        contract,
        spec,
        index: int,
        workspace: str,
        risk,
    ) -> dict[str, Any]:
        git_state = git_snapshot(
            workspace
        )

        summary = str(
            spec.purpose
            or contract.summary
            or "Protected workspace mutation"
        ).strip()

        reason = (
            f"Effective risk {risk.risk_level} "
            "requires a workspace-file checkpoint "
            "before command execution."
        )

        provisional = build_checkpoint_metadata(
            workspace_root=workspace,
            lifecycle=str(
                getattr(
                    self,
                    "lifecycle",
                    "",
                )
            ),
            phase=str(
                self.config.get(
                    "phase"
                )
                or ""
            ),
            stage=str(
                self.config.get(
                    "stage"
                )
                or ""
            ),
            command_index=index,
            command_summary=summary,
            risk_level=str(
                risk.risk_level
            ),
            reason=reason,
            git=git_state,
            snapshot_metadata={
                "kind": "pending",
                "rollback_scope": (
                    "workspace_files_only"
                ),
            },
        )

        checkpoint_id = str(
            provisional[
                "checkpoint_id"
            ]
        )

        snapshot = None

        try:
            snapshot = create_workspace_snapshot(
                checkpoint_id=checkpoint_id,
                workspace_root=workspace,
            )

            snapshot = {
                **snapshot,
                "rollback_scope": (
                    "workspace_files_only"
                ),
                "rollback_limitations": [
                    (
                        "Git metadata under .git "
                        "is not captured."
                    ),
                    (
                        "Native-owned .ai-workflow "
                        "state is not captured."
                    ),
                    (
                        "Remote, database, system, "
                        "and other external side effects "
                        "are outside this checkpoint."
                    ),
                    (
                        "Excluded volatile directories "
                        "are outside this checkpoint."
                    ),
                ],
            }

            checkpoint = (
                build_checkpoint_metadata(
                    workspace_root=workspace,
                    lifecycle=str(
                        getattr(
                            self,
                            "lifecycle",
                            "",
                        )
                    ),
                    phase=str(
                        self.config.get(
                            "phase"
                        )
                        or ""
                    ),
                    stage=str(
                        self.config.get(
                            "stage"
                        )
                        or ""
                    ),
                    command_index=index,
                    command_summary=summary,
                    risk_level=str(
                        risk.risk_level
                    ),
                    reason=reason,
                    git=git_state,
                    snapshot_metadata=snapshot,
                    checkpoint_id=checkpoint_id,
                    created_at=str(
                        provisional[
                            "created_at"
                        ]
                    ),
                )
            )

            self.store.put_checkpoint(
                checkpoint
            )

            return checkpoint

        except Exception:
            try:
                remove_workspace_snapshot(
                    checkpoint_id=checkpoint_id
                )
            except Exception:
                pass

            raise

    def _run_command_and_continue(
        self,
        contract,
        index: int,
        accumulated: list[dict[str, Any]] | None = None,
        download_bundle: dict[str, Any] | None = None,
        approved_index: int | None = None,
    ) -> None:
        if bool(
            getattr(
                self,
                "command_execution_active",
                False,
            )
        ):
            raise RuntimeError(
                "A command execution window is "
                "already active"
            )

        self.command_execution_active = True

        try:
            return self._run_command_and_continue_impl(
                contract,
                index,
                accumulated,
                download_bundle,
                approved_index,
            )
        finally:
            self.command_execution_active = False

    def _run_command_and_continue_impl(
        self,
        contract,
        index: int,
        accumulated: list[dict[str, Any]] | None = None,
        download_bundle: dict[str, Any] | None = None,
        approved_index: int | None = None,
    ) -> None:
        accumulated = list(accumulated or [])
        workspace = str(self.config.get("workspace_root") or "")
        before = git_snapshot(workspace)

        while index < len(contract.commands):
            spec = contract.commands[index]
            local = classify(spec.cmd, workspace)
            risk = merge_risk(local, spec.risk_assessment)
            display_command = redact_text(spec.cmd)

            if spec.risk_assessment is not None or risk.escalated_by_llm:
                llm = risk.llm_risk_level or "n/a"
                suffix = " — escalated by LLM" if risk.escalated_by_llm else ""
                self.emit_event({
                    "kind": "step",
                    "badge": "RISK",
                    "status": "validating",
                    "text": f"{display_command} → local {risk.local_risk_level}, LLM {llm}, effective {risk.risk_level}{suffix}",
                })

            if risk.level == "blocked":
                self.status = "blocked"
                self.emit_event({"kind": "error", "text": f"Blocked command: {display_command}\n{risk.reason}"})
                self._send_result_to_chatgpt(
                    f"Bridge policy BLOCKED this command:\n{display_command}\n{risk.reason}\n"
                    "The LLM risk opinion cannot lower or bypass local policy. Propose a safer alternative within the current roadmap."
                )
                return

            already_approved = approved_index is not None and index == approved_index
            if (risk.level == "approval" or not bool(self.config.get("auto_run_low_risk", True))) and not already_approved:
                self._request_decision(
                    contract,
                    command=display_command,
                    summary=spec.purpose or contract.summary or "Protected command",
                    impact=risk.reason,
                    continuation={
                        "kind": "command",
                        "contract": contract,
                        "index": index,
                        "accumulated": accumulated,
                        "download_bundle": download_bundle,
                    },
                )
                return

            checkpoint = None

            if self._risk_requires_checkpoint(
                risk.risk_level
            ):
                self.status = "checkpointing"
                self.current_step = (
                    spec.purpose
                    or display_command
                )

                self.emit_event({
                    "kind": "step",
                    "badge": "SAVE",
                    "status": "checkpointing",
                    "text": (
                        "Creating a workspace-file "
                        "checkpoint before protected "
                        f"{risk.risk_level} execution."
                    ),
                })

                try:
                    checkpoint = (
                        self._create_command_checkpoint(
                            contract=contract,
                            spec=spec,
                            index=index,
                            workspace=workspace,
                            risk=risk,
                        )
                    )
                except Exception as error:
                    self.status = "failed"
                    self.current_step = (
                        "Checkpoint creation failed"
                    )

                    detail = redact_text(
                        str(error)
                    )

                    self.emit_event({
                        "kind": "error",
                        "badge": "SAVE!",
                        "status": "failed",
                        "text": (
                            "Checkpoint creation failed; "
                            "the protected command was "
                            f"NOT executed: {detail}"
                        ),
                    })

                    self._send_result_to_chatgpt(
                        "Bridge could not create the "
                        "required pre-mutation workspace "
                        "checkpoint. The command was NOT "
                        f"executed. Error: {detail}"
                    )

                    return

                snapshot = dict(
                    checkpoint.get(
                        "snapshot"
                    )
                    or {}
                )

                self.emit_event({
                    "kind": "checkpoint",
                    "badge": "SAVE",
                    "status": "checkpoint_ready",
                    "checkpoint_id": str(
                        checkpoint.get(
                            "checkpoint_id"
                        )
                        or ""
                    ),
                    "risk_level": str(
                        risk.risk_level
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
                    "text": (
                        "Workspace-file checkpoint "
                        "created. External, database, "
                        "system, Git-metadata, and "
                        "native lifecycle side effects "
                        "are not represented as fully "
                        "transactional."
                    ),
                })

            self.status = "running"
            self.current_step = (
                spec.purpose
                or display_command
            )

            self.emit_event({
                "kind": "step",
                "badge": "BAM!",
                "status": "running",
                "text": self.current_step,
            })

            # Explicit crash boundary: checkpoint creation
            # and checkpoint metadata persistence, when
            # required, must already be complete before the
            # local process receives any opportunity to mutate.
            self._persist_runtime_state()

            try:
                result = run_command(
                    spec.cmd,
                    workspace,
                    spec.cwd,
                    int(self.config.get("command_timeout_seconds", 900)),
                    int(self.config.get("max_output_chars", 24000)),
                    str((download_bundle or {}).get("download_dir") or ""),
                )
            except Exception as error:
                accumulated.append({"command": display_command, "error": redact_text(str(error))})
                self.emit_event({"kind": "error", "text": f"Command failed to run: {redact_text(str(error))}"})
                break

            item = asdict(result)
            item["risk"] = {
                "local": risk.local_risk_level,
                "llm": risk.llm_risk_level,
                "effective": risk.risk_level,
                "escalated_by_llm": risk.escalated_by_llm,
            }
            accumulated.append(item)

            if approved_index is not None and index == approved_index:
                approved_index = None
            badge = "PASS" if result.exit_code == 0 else "FAIL"
            self.emit_event({
                "kind": "step",
                "badge": badge,
                "status": "running" if result.exit_code == 0 else "failed",
                "text": f"{display_command} → exit {result.exit_code} in {result.duration_seconds:.1f}s",
            })
            if result.exit_code != 0:
                break
            index += 1

        after = git_snapshot(workspace)
        self.status = "reporting"
        report = self._format_result(contract, accumulated, before, after, download_bundle)
        self.telegram.send_report(self._telegram_summary(contract, accumulated, after))
        self._send_result_to_chatgpt(report)
        self.status = "waiting_llm"
        self.current_step = contract.next_step or f"Waiting for {self.provider_name(self.active_provider)}"
        self.emit_event({
            "kind": "step",
            "badge": "WHOOSH",
            "status": "waiting_llm",
            "text": f"Terminal results sent back to {self.provider_name(self.active_provider)}.",
        })
