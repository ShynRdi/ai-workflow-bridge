# Public Roadmap

This roadmap is directional and does not promise dates.

## 0.3.2 — Install confidence and project visibility

- Read-only system diagnostics for native host, Python, local state, workspace, Git and browser integration.
- Active-tab workflow binding to prevent cross-conversation execution when multiple provider tabs are open.
- Canonical-roadmap project progress bar with completed and remaining stages.

## 0.3.3 — Crash and restart recovery

- Restore in-progress workflow state after Chrome/service-worker/native-host restart.
- Preserve pending approvals and bound workflow context safely.
- Explicit recovery state instead of silently resuming execution.

## 0.3.4 — Checkpoint and rollback

- Project checkpoints before meaningful mutations.
- User-visible rollback boundaries.
- Git-aware recovery where available without assuming every workspace uses Git.

## 0.3.5 — Diff review and acceptance criteria

- Structured review of changed files before stage completion.
- Machine-readable acceptance criteria tied to roadmap stages.
- Clear distinction between command success and product acceptance.

## 0.3.6 — Security policy profiles

- Strict / Balanced / isolated-development profiles.
- Per-project execution policy.
- Stronger path, network, external-state and production boundaries.

## 0.4 — Execution isolation

- Optional containerized runner.
- Dedicated workspace mounts.
- Process-tree termination and resource budgets.
- Network restrictions where supported.

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
