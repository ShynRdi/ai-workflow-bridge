# Changelog

All notable public changes will be documented here. This project follows Semantic Versioning where Chrome extension version constraints allow it.

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
