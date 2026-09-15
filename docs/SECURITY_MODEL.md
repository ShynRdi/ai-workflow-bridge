# Security Model

This document describes the intended controls and known limits of the current public preview.

## Primary risks

- An LLM proposes a destructive shell command.
- A read-only-looking command reads credentials or account data.
- Command output accidentally contains a token and is sent to a web LLM.
- A provider rate/auth challenge triggers unsafe retry behavior.
- A provider DOM change causes the wrong element to be automated.
- A generated/downloaded file contains malicious content.
- A roadmap/model response drifts away from the user's intended project.

## Controls

### Command policy

Commands are classified locally as `low`, `approval`, or `blocked`. The LLM cannot mark its own command safe.

Blocked examples include destructive filesystem operations, hard resets, system power operations, privileged `sudo`, and known credential-store paths.

Protected examples include dependency changes, remote Git publication, migrations, remote machine access, compound shell syntax, secret-looking files, and low-risk reads that explicitly escape the workspace.

### Secret exposure defenses

- Common credential stores are blocked by path guard.
- Arbitrary `env`/`printenv` dumps are not low-risk.
- Shell expansion of non-allowlisted environment variables is not low-risk.
- stdout/stderr is redacted for common secret patterns before being returned to the web LLM.

Redaction is defense-in-depth and cannot recognize every proprietary credential format.

### Provider/account safety

- No login/MFA automation.
- No cookies permission.
- No CAPTCHA bypass or stealth automation.
- No account rotation.
- No automatic cross-provider fallback.
- Rate/auth/security warning detection pauses the workflow.
- Turn/hour/session/runtime budgets limit autonomous loops.

### Generated/downloaded files

Downloads are quarantined into Bridge-controlled run storage; hashes are recorded and ZIP path traversal is rejected before use. A file still requires normal policy/approval controls before executing scripts from it.

## Known limitations

### No OS sandbox

Approved shell commands run as the current user. The Bridge is not a replacement for a container, VM, seccomp policy, macOS sandbox, or dedicated low-privilege account.

### Shell parsing is conservative, not complete

The policy engine intentionally escalates unknown/compound syntax. Shell is too expressive for regex/path heuristics to prove safety in the general case.

### Web UI adapters are fragile dependencies

Provider DOMs can change without notice. Stable/Beta/Experimental labels refer to adapter maturity, not provider security.

## Recommended operating profile

For routine development:

- keep auto-run limited to low-risk commands;
- keep rate limits conservative;
- review every approval prompt;
- work in a clean Git repository;
- keep secrets outside the workspace when possible;
- use a container/VM for higher-risk automation.
