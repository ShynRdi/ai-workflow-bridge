# Public Roadmap

This roadmap is directional and does not promise dates.

## 0.3.2 — Install confidence and project visibility

- Read-only system diagnostics for native host, Python, local state, workspace, Git and browser integration.
- Active-tab workflow binding to prevent cross-conversation execution when multiple provider tabs are open.
- Canonical-roadmap project progress bar with completed and remaining stages.

## 0.3.3 — Crash and restart recovery

- Persist active runtime, provider-safety, and autonomy-budget state across native-host restarts.
- Enter explicit fail-closed recovery after interrupted workflows instead of silently resuming execution.
- Preserve pending-approval review context without restoring executable continuations.
- Require explicit provider/tab rebinding before re-arming a recovered workflow.
- Bind workflows to provider, tab, and conversation identity and fail closed on same-tab conversation changes.
- Checkpoint runtime state before commands, browser downloads, and outbound LLM sends.

## 0.3.4 — Checkpoint and rollback

- Durable workspace-file checkpoints before protected R2/R3 execution.
- Explicit Mission Control acceptance and rollback actions.
- Hardened bounded restore with archive and path validation.
- Crash-safe rollback lifecycle with explicit restart recovery and no automatic replay.
- Clear rollback boundaries for Git metadata, native state and external side effects.

## 0.3.5 — Git-aware review, diff review and acceptance criteria

- Read-only Git checkpoint evidence for HEAD, branch, dirty state, index and working-tree divergence.
- Exact checkpoint identity binding for human accept and rollback actions.
- Post-rollback Git review without rewriting .git, refs, HEAD or index state.
- Structured review of changed files before stage completion.
- Machine-readable acceptance criteria tied to roadmap stages.
- Clear distinction between command success and product acceptance.
- Durable exact-review identity, explicit human accept/reject controls, stale-evidence blocking, and restart-safe pending review recovery.

## 0.3.6 — Security policy profiles

- Strict / Balanced / isolated-development profiles.
- Per-project execution policy.
- Stronger path, network, external-state and production boundaries.
- Explicit revision-bound human profile changes; stale controls fail closed.
- Isolated Development remains a policy profile only. Execution isolation is planned for v0.4.

## 0.4 — Execution isolation

- Human-only, revision-bound per-project host/container configuration in Mission Control; policy remains the independent authority for whether commands may run.
- Docker-only container execution with local-image-only preflight, `network=none`, resource budgets, read-only root and read-only native control mount.
- Read-only Docker and execution diagnostics with bounded timeouts.
- Durable exact-container runtime journal, restart/orphan detection, explicit human-only recovery, and fail-closed execution while recovery remains unresolved.
- Exact-name cleanup with ownership-label verification; no broad Docker cleanup and no automatic command replay.
- Document Docker daemon trust, the macOS Docker Desktop VM, and the fact that container commands are not transactional rollback.

## 0.4.x — Structured capabilities

- Typed actions for common Git, filesystem, test and build operations.
- Capability-based approvals instead of relying only on free-form shell classification.
- Stronger secrets and data-exfiltration controls.

## 0.5 — Project operations

- Multi-project dashboard.
- Audit/replay views.
- Export/import of project state.
- Provider/conversation handoff with explicit human control.
- Additional notification adapters beyond Telegram.

## 0.6 — Verification intelligence

- Better success-condition verification.
- Context-drift detection.
- Optional multi-model review without allowing reviewers to bypass deterministic local policy.
- Human decision/ADR registry.

## 0.7 — Repository workflows

- GitHub workflow integration.
- CI-oriented execution mode.
- Stronger release and branch-protection workflows.

## 0.8 — Team mode

- Shared project governance.
- Role-aware approvals.
- Team audit trails.

## 0.9 — Hardening

- Security review findings.
- Migration/update hardening.
- Packaging and recovery maturity.
- Provider-adapter stabilization.

## 1.0 criteria

A 1.0 release should require:

- documented security review;
- stable lifecycle and workflow-contract formats;
- mature crash/restart recovery;
- reproducible and auditable packaging;
- safe update/migration behavior;
- clear isolation guidance;
- well-tested provider adapters;
- durable project-state and audit semantics.
