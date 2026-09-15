# Contributing to AI Workflow Bridge

Thanks for helping improve the project. The Bridge sits between a web LLM and a local shell, so changes that look small can have meaningful security or account-safety consequences.

## Before you start

- Search existing issues first.
- For large architecture changes, open an issue before implementing.
- For security vulnerabilities, follow `SECURITY.md` and **do not** open a public exploit report.
- Never include provider cookies, session data, credentials, private prompts, or user project secrets in issues/tests/fixtures.

## Local development

Requirements:

- Python 3.11+
- Node.js 20+ (syntax checks only; the extension has no npm runtime dependency)
- Chrome/Chromium for manual extension testing

Setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
make check
make test
```

## Pull requests

Keep PRs focused. A PR that changes provider selectors should not also redesign the policy engine.

Every PR should explain:

1. what behavior changed;
2. why the change is needed;
3. the safety/account impact;
4. how it was validated.

### Changes that need extra scrutiny

The following areas require explicit tests and rationale:

- command policy/risk classification;
- secret/output redaction;
- provider permissions;
- login/session/cookie behavior;
- native-host execution;
- automatic retries/rate limits;
- course-change/roadmap enforcement;
- downloads or generated-file execution.

## Provider adapters

Provider web UIs are unstable dependencies. New adapters start as **Experimental**. Promote them only after manual verification of composer detection, submission confirmation, streaming/completion detection, response capture, and security/rate-limit pause behavior.

Do not add login automation, CAPTCHA bypass, stealth/headless evasion, cookie extraction, account rotation, or automatic cross-provider fallback.

## Style

- Python: clear standard-library-first code; type hints where useful.
- JavaScript: dependency-free MV3 code unless a dependency has a strong justification.
- Prefer deterministic local policy over LLM-generated risk labels.
- Keep permissions least-privileged.

## License

By contributing, you agree that your contributions are licensed under the repository's Apache License 2.0.
