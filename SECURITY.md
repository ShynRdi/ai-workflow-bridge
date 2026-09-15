# Security Policy

AI Workflow Bridge can execute local commands proposed by a web LLM. Treat it as a high-trust developer tool and use conservative settings.

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest public preview only.

## Reporting a vulnerability

Please use GitHub's **Report a vulnerability** / private security advisory flow for this repository. Do not publish exploit details, credentials, provider session information, or private user data in a public issue.

If private vulnerability reporting is temporarily unavailable, open a minimal issue titled `Security contact request` without technical exploit details so a maintainer can establish a private channel.

## Security boundaries

The Bridge intentionally does **not**:

- automate sign-in or MFA;
- read browser cookies;
- export provider session tokens;
- bypass CAPTCHA/security challenges;
- rotate accounts to evade limits;
- automatically fall back to another provider after a safety/rate-limit event;
- execute commands marked blocked by the local policy engine.

Provider site access is requested per provider through optional Chrome host permissions.

## Important limitation: not a sandbox

The native host currently executes approved commands through the user's normal shell account. The policy engine, workspace checks, sensitive-path guards, approvals, output redaction, and rate limits are defense-in-depth controls — **not an OS-level sandbox**.

For high-risk repositories or untrusted prompts, use an isolated VM/container/user account in addition to Bridge controls.

## Local secrets

Optional Telegram credentials are stored locally in the Bridge config, not in the webpage. Public Preview 0.2.1 restricts Bridge state/config permissions on supported Unix-like systems, but users remain responsible for host security and backups.

The output redactor catches common secret formats but cannot guarantee detection of every secret. Do not intentionally ask the LLM to read secret files.
