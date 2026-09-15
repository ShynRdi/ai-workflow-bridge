# Public Roadmap

This roadmap is directional and does not promise dates.

## 0.2.x — Public preview hardening

- Expand deterministic command capability classification.
- Improve path/secret guards and output redaction.
- Add richer audit export.
- Validate Beta provider adapters against current UIs.
- Improve install diagnostics for Chrome/Chromium/macOS/Linux.

## 0.3 — Provider adapter maturity

- Dedicated adapter modules instead of a single registry-only layer.
- Provider-specific regression fixtures where legally/practically possible.
- Better safety/rate-limit signal classification.
- Clear promotion criteria from Experimental → Beta → Stable.

## 0.4 — Execution isolation options

- Optional containerized runner.
- Dedicated workspace mounts.
- Capability-based command actions for common operations instead of free-form shell where possible.
- Stronger filesystem/network policies.

## 0.5 — Project operations

- Multi-project dashboard.
- Export/import of project state and audit trails.
- More robust crash/restart recovery.
- Optional notification adapters beyond Telegram.

## 1.0 criteria

A 1.0 release should require a documented security review, stable lifecycle/contract format, reproducible packaging, mature update/migration behavior, and at least several well-tested provider adapters.
