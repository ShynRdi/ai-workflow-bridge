# Changelog

All notable public changes will be documented here. This project follows Semantic Versioning where Chrome extension version constraints allow it.

## [0.2.3] - 2026-09-15

### Security hardening

- Changed project-controlled test/build/lint/interpreter commands from auto-run to explicit approval.
- Child processes now receive a minimal allowlisted environment instead of inheriting arbitrary user secrets.
- Expanded output/command redaction for GitHub, OpenAI-style, AWS, Google, Slack, JWT, URL credentials and token query parameters.
- AI_WORKFLOW contracts now fail closed when phase/stage are empty and cap commands per contract.
- Added download bundle, individual file, ZIP entry, uncompressed-size, compression-ratio and symlink limits.
- Completion/stop/READY markers must now be exact trailing markers instead of appearing anywhere in a response.
- Redacted command text in execution reports and blocked/error paths.
- Synchronized content-script and extension versions and exposed provider maturity in health pings.
- Added regression coverage for all hardening items.

## [0.2.2] - 2026-09-15

### Risk intelligence

- Added optional semantic `risk_assessment` data to command contracts.
- Effective risk is `max(local policy, LLM assessment)`; the LLM can only escalate, never downgrade policy.
- R2/R3 require approval and R4 is blocked.

## [0.2.1] - 2026-09-15

### Public preview

- Prepared the first open-source release structure.
- Added Apache-2.0 licensing, contribution/security policies, issue/PR templates and CI.
- Renamed the native messaging host to `io.github.shynrdi.ai_workflow_bridge` for the public package.
- Added sensitive credential-path blocking and outside-workspace review for low-risk reads.
- Prevented arbitrary environment dumps from being classified as low-risk.
- Added defense-in-depth stdout/stderr secret redaction.
- Hardened local Bridge state/config file permissions on supported Unix-like systems.
- Added public-tree hygiene checks and reproducible extension/source packaging scripts.

### Existing 0.2 capabilities

- Multi-web-LLM provider registry.
- Explicit Plan → Arm → Run → Course Change → Finish lifecycle.
- Machine-readable roadmap enforcement.
- Command approvals, rate limits and autonomy budgets.
- Optional per-provider Chrome site permissions.
- Immediate pause on provider rate/auth/security signals.
