# Provider smoke tests

Provider smoke tests are deliberately user-initiated and account-safe. They do not automate login, CAPTCHA/MFA, provider switching, retries, or security challenges.

## What one smoke test does

1. Uses only the provider site permission the user explicitly granted.
2. Requires the user to already be logged in to an open provider tab.
3. Refuses to start while a project workflow is actively running.
4. Verifies the content bridge and composer are detectable.
5. Sends exactly one fixed prompt asking for `AWB_SMOKE_OK`.
6. Polls the local DOM for completion; it never resends the prompt.
7. Fails immediately if a rate-limit or account-security warning is visible.
8. Records only PASS/FAIL, timestamp, content-script version, and marker presence in extension local storage.

The smoke prompt does not ask the model to browse, call tools, open links, create files, or execute project commands.

## Stable promotion policy

A provider must not be promoted from beta/experimental to stable based on a single successful turn. Before promotion, validate at least: composer detection, real submission, streaming/completion detection, response text capture, navigation resilience, and provider safety-warning handling. Repeat on at least two fresh conversations and document the provider URL/date/model label. Never intentionally trigger account-security challenges simply to test the detector.

## Recommended order

ChatGPT → Claude → Gemini → DeepSeek → Z.ai/GLM. Test one provider at a time. If a provider displays a usage limit, CAPTCHA, unusual-activity message, session-expired state, or security challenge, stop testing that provider for the session.
