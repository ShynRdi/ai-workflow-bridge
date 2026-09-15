# AI Workflow Bridge

[![CI](https://github.com/ShynRdi/ai-workflow-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ShynRdi/ai-workflow-bridge/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-public%20preview-orange.svg)](CHANGELOG.md)

**A guarded bridge between web LLMs and local development workflows.**

AI Workflow Bridge lets a supported web LLM plan work, emit a structured workflow contract, receive terminal evidence, and continue a project — while a deterministic local runner enforces roadmap state, approvals, rate limits, account-safety rules, and command policy.

> **Public Preview 0.2.1:** this is pre-1.0 developer tooling. It is intentionally conservative, but it is **not an OS sandbox**. Read [SECURITY.md](SECURITY.md) before using it on valuable or sensitive systems.

## Why this exists

A common manual loop looks like this:

```text
LLM gives commands/files
        ↓
You run them locally
        ↓
You paste stdout/stderr back
        ↓
LLM decides the next step
```

AI Workflow Bridge automates that loop without giving the LLM unconditional shell control:

```text
Web LLM
  ↓ structured AI_WORKFLOW contract
Chrome extension
  ↓ Native Messaging
Local policy + roadmap + approvals
  ↓
Local workspace / terminal
  ↓ evidence
Same web LLM conversation
```

## Core behavior

- **Plan → Arm → Run → Change Course → Finish** project lifecycle.
- Machine-readable canonical roadmap stored outside the conversation.
- Multi-web-LLM provider registry with explicit support levels.
- Per-provider optional Chrome site permissions.
- Local command classification: low-risk / approval / blocked.
- Sensitive credential-path guards and output secret redaction.
- Rate limits, autonomy budgets, circuit-style provider safety pauses.
- No automatic provider fallback.
- No login, cookie extraction, CAPTCHA bypass, or account rotation.
- Optional Telegram reporting/approval channel.
- Comic-book Mission Control UI, serious deterministic backend.

## Provider adapters

Adapter status describes **Bridge UI compatibility**, not model quality.

| Provider | Status |
|---|---|
| ChatGPT | Stable regression target |
| Claude | Beta |
| Gemini | Beta |
| DeepSeek | Beta |
| Grok | Beta |
| Perplexity | Beta |
| Mistral | Beta |
| Microsoft Copilot | Beta |
| Z.ai / GLM | Beta |
| Meta AI | Experimental |
| Poe | Experimental |
| Qwen | Experimental |
| Kimi | Experimental |

Web UIs change frequently. Supervise Beta/Experimental adapters before long autonomous runs. See [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Safety model in one minute

The web LLM never gets to declare its own command safe. The native host evaluates commands locally.

```text
LLM contract
   ↓
contract validation
   ↓
roadmap validation
   ↓
command/path/secret policy
   ├─ low-risk → auto-run (if enabled)
   ├─ approval → wait for human
   └─ blocked → never execute
   ↓
redacted stdout/stderr
   ↓
LLM
```

The Bridge also pauses on provider rate-limit/auth/security signals rather than retrying aggressively or switching accounts/providers.

For threat boundaries and limitations, read [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md).

## Installation

### Requirements

- Chrome or Chromium with Manifest V3 + Native Messaging
- Python 3.11+
- Linux or macOS for the current native-host installer

### 1. Load the extension

Open:

```text
chrome://extensions
```

Enable **Developer mode** → **Load unpacked** → choose `extension/`.

Copy the generated extension ID.

### 2. Install the native host

```bash
./install_native_host.sh YOUR_EXTENSION_ID
```

Reload the extension. Mission Control should show the native host as online.

### 3. Open your LLM normally

Sign in manually to the provider website. The Bridge does not handle credentials or login flows.

Choose the provider in **AI Engine + Safety** and grant site access only for that provider.

## Start a project

1. Set the project name, absolute workspace path, project brief, initial phase and stage.
2. Choose the web LLM provider and optionally record the model label you selected manually on the website.
3. Click **PLAN PROJECT**. No local command should execute during planning.
4. Review the returned roadmap. The LLM must finish planning with `READY_TO_ARM` and a machine-readable roadmap.
5. Click **ARM & RUN** only after the roadmap is acceptable.
6. The Bridge executes low-risk work, pauses for protected actions, and returns evidence to the same conversation.
7. Use **CHANGE COURSE** for intentional mid-project direction changes.
8. Use **FINISH PROJECT** to force final verification before the project can enter `COMPLETE`.

Full operating instructions: [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Project lifecycle

```text
SETUP
  ↓
PLANNING
  ↓
READY_TO_ARM
  ↓
RUNNING ─────→ CHANGE_REVIEW ─────→ RUNNING
  ↓
FINISHING
  ↓
COMPLETE
```

A model cannot silently rewrite the roadmap. See [docs/PROJECT_LIFECYCLE.md](docs/PROJECT_LIFECYCLE.md).

## Architecture

The extension handles supported provider DOM interaction and communicates with a local Python process using Chrome Native Messaging. The native host owns lifecycle state, roadmap enforcement, policy, approvals, rate limits, redaction, audit data and shell execution.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt

make check
make test
```

Build an unpacked-store-friendly extension ZIP:

```bash
make package-extension
```

The ZIP is written to `dist/` with `manifest.json` at its root.

## Open-source project files

- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution workflow and safety expectations
- [SECURITY.md](SECURITY.md) — vulnerability reporting and supported security boundaries
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — community expectations
- [CHANGELOG.md](CHANGELOG.md) — public release history
- [docs/ROADMAP.md](docs/ROADMAP.md) — directional public roadmap
- [docs/AUTOMATION_CONTRACT.md](docs/AUTOMATION_CONTRACT.md) — LLM ↔ runner contract
- [docs/ACCOUNT_SAFETY.md](docs/ACCOUNT_SAFETY.md) — provider account protections

## Responsible-use notes

- Use the Bridge only on systems and projects you are authorized to modify.
- Keep approval prompts enabled for sensitive operations.
- Do not use it to bypass provider security controls or usage limits.
- Keep secrets out of prompts and project output whenever possible.
- For higher-risk tasks, combine the Bridge with an OS/container/VM isolation boundary.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
