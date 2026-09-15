# Account Safety Model

AI Workflow Bridge is intentionally conservative around web LLM accounts.

## Hard principles

- The user logs in manually.
- The Bridge never asks for, stores, exports, or injects account passwords.
- The extension does not request Chrome `cookies` permission.
- The Bridge does not export session cookies/tokens.
- No CAPTCHA, verify-human, MFA, unusual-activity, or security-warning bypass is attempted.
- No stealth/headless evasion is implemented.
- No automatic account rotation is implemented.
- No automatic provider fallback is implemented.
- Provider access is granted one provider at a time through optional host permissions.
- Provider security/rate-limit signals pause the workflow immediately.

## Rate controls

The Bridge enforces local limits even when the provider would permit more usage:

- minimum delay between AI turns;
- maximum turns per hour;
- maximum turns per session;
- maximum autonomous runtime.

These limits are designed to reduce accidental loops and aggressive traffic. They are not intended to approximate or bypass provider limits.

## What happens on a provider warning

When the provider UI surfaces an alert that resembles rate limiting, security verification, expired session, unusual activity, or CAPTCHA:

1. The content script sends a safety signal.
2. The native host activates the provider guard.
3. Outbound prompts stop.
4. No automatic retry occurs.
5. No other provider is selected.
6. The user resolves the account/provider condition manually.
7. A fresh guarded run can only be started through explicit user action.

## Why model selection is manual

Automating provider model pickers increases DOM fragility and can interact with plan/account-specific controls. Version 0.2.1 records an optional model label but leaves model selection in the provider UI to the user.

## Store/publication note

If distributed publicly, permissions, data handling and supported provider behavior should be disclosed clearly in the store listing and privacy policy. The adapter should never imply endorsement by the third-party LLM providers.
