from __future__ import annotations

from dataclasses import asdict
from typing import Any

from policy import classify, merge_risk
from runner import git_snapshot, run_command


class RiskAwareExecutionMixin:
    def _run_command_and_continue(
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

            if spec.risk_assessment is not None or risk.escalated_by_llm:
                llm = risk.llm_risk_level or "n/a"
                suffix = " — escalated by LLM" if risk.escalated_by_llm else ""
                self.emit_event({
                    "kind": "step",
                    "badge": "RISK",
                    "status": "validating",
                    "text": f"{spec.cmd} → local {risk.local_risk_level}, LLM {llm}, effective {risk.risk_level}{suffix}",
                })

            if risk.level == "blocked":
                self.status = "blocked"
                self.emit_event({"kind": "error", "text": f"Blocked command: {spec.cmd}\n{risk.reason}"})
                self._send_result_to_chatgpt(
                    f"Bridge policy BLOCKED this command:\n{spec.cmd}\n{risk.reason}\n"
                    "The LLM risk opinion cannot lower or bypass local policy. Propose a safer alternative within the current roadmap."
                )
                return

            already_approved = approved_index is not None and index == approved_index
            if (risk.level == "approval" or not bool(self.config.get("auto_run_low_risk", True))) and not already_approved:
                self._request_decision(
                    contract,
                    command=spec.cmd,
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

            self.status = "running"
            self.current_step = spec.purpose or spec.cmd
            self.emit_event({"kind": "step", "badge": "BAM!", "status": "running", "text": self.current_step})
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
                accumulated.append({"command": spec.cmd, "error": str(error)})
                self.emit_event({"kind": "error", "text": f"Command failed to run: {error}"})
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
                "text": f"{spec.cmd} → exit {result.exit_code} in {result.duration_seconds:.1f}s",
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
