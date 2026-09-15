# Architecture

AI Workflow Bridge is intentionally split into a browser-facing control plane and a local deterministic execution plane.

```text
Supported web LLM tab
        │
        │ provider adapter / DOM events
        ▼
Chrome MV3 extension
  ├─ provider registry
  ├─ side-panel Mission Control
  ├─ optional host permissions
  ├─ response/attachment capture
  └─ Native Messaging client
        │
        ▼
Local Python native host
  ├─ lifecycle + roadmap state
  ├─ workflow contract parser
  ├─ command policy engine
  ├─ approvals
  ├─ rate/autonomy budget
  ├─ sensitive-path guard
  ├─ output redaction
  ├─ local runner
  ├─ SQLite audit/event store
  └─ optional Telegram reporting
        │
        ▼
Configured local workspace
```

## Design principles

1. **The LLM proposes; local code decides what may run.** LLM-provided risk labels are not trusted.
2. **Human approval remains a first-class state.** Protected operations stop execution.
3. **Roadmap state is canonical outside the LLM conversation.** Silent phase jumps are rejected/reviewed.
4. **Provider access is least-privileged.** Sites are optional host permissions, not blanket install permissions.
5. **Account safety beats continuity.** Rate/auth/security signals pause instead of retrying aggressively or switching providers.
6. **No provider API is required for orchestration.** The Bridge works with the user's already-open web session.

## Trust boundaries

### Web LLM output

Untrusted instructions. Only structured `AI_WORKFLOW` contracts are considered for execution, then validated locally.

### Browser extension

Trusted project code, but it operates in changing third-party DOMs. Provider selectors are therefore version-sensitive and support levels are explicit.

### Native host

High-trust component. It has the user's local permissions and must remain conservative.

### Local workspace

The configured command working directory is confined to the selected workspace. Public Preview 0.2.1 also escalates low-risk reads that explicitly reference paths outside that workspace.

## Native Messaging

The Chrome extension connects to `io.github.shynrdi.ai_workflow_bridge`. `install_native_host.sh` writes the native-host manifest for the specific loaded extension ID.

## Persistence

State lives under `AI_WORKFLOW_BRIDGE_HOME`, defaulting to the user's config directory (`~/.config/ai-workflow-bridge` on typical Linux systems). It contains configuration, SQLite event/approval data and logs.

## Provider architecture

`extension/providers.js` contains provider metadata and DOM selector sets. The generic content script implements insertion, submission verification, response stability detection, download candidate discovery and provider-safety signal detection.

See `docs/PROVIDERS.md` for adapter maintenance rules.
