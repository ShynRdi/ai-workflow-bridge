# LLM-Assisted Risk Intelligence

AI Workflow Bridge uses two independent risk signals for every command:

1. **Local deterministic policy** — the security authority.
2. **LLM semantic assessment** — context-aware advisory signal.

The effective command risk is the maximum of the two. The LLM can escalate risk but can never lower, bypass, or override a local restriction.

## Risk levels

| Level | Meaning | Default handling |
|---|---|---|
| R0 | read-only inspection | auto-run when enabled |
| R1 | bounded local verification/build | auto-run when enabled + audit |
| R2 | reversible mutation/dependency change | approval |
| R3 | sensitive, external, remote, or production-significant | approval |
| R4 | destructive, credential-exposing, security-bypassing, forbidden | block |

## Contract shape

Each command should include:

```json
{
  "cmd": "git status --short",
  "cwd": ".",
  "purpose": "inspect repository state",
  "risk_assessment": {
    "level": "R0",
    "confidence": 0.99,
    "factors": ["read-only repository inspection"],
    "dimensions": {
      "filesystem": 0,
      "network": 0,
      "credentials": 0,
      "database": 0,
      "git_remote": 0,
      "system": 0,
      "production": 0,
      "irreversibility": 0,
      "data_exfiltration": 0
    },
    "reversible": true,
    "recommended_action": "auto"
  }
}
```

Dimension scores range from 0 (none) to 3 (severe).

## Merge rule

Conceptually:

```text
effective_risk = max(local_risk, llm_risk)
```

Examples:

```text
Local R3 + LLM R0 -> R3 approval
Local R0 + LLM R3 -> R3 approval
Local R0 + LLM R4 -> R4 blocked
Local R4 + LLM R0 -> R4 blocked
```

An invalid or missing LLM assessment is ignored. This is backward-compatible and fail-safe: local policy remains authoritative.

## Threat model

The LLM may be mistaken, overconfident, prompt-injected, or biased toward a command it generated itself. Therefore its assessment is never treated as a security boundary. It exists to catch contextual risks that static command rules may not see, such as a harmless-looking script that the conversation identifies as production-impacting.

Approvals remain exact-once and command-specific. An approval does not change the stored risk classification and does not carry to later commands.
