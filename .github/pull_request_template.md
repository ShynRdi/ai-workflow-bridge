## What changed?

Describe the user-visible or internal change.

## Why?

Explain the problem or motivation.

## Safety impact

- [ ] No new site permissions
- [ ] No new access to credentials/cookies/browser sessions
- [ ] No weakening of command approval/block rules
- [ ] New or changed risky behavior is documented and tested

If any box cannot be checked, explain why and include the mitigation.

## Validation

- [ ] `make check`
- [ ] `make test`
- [ ] Manual provider testing, if selectors/adapter behavior changed

## Provider UI changes

If this changes a web adapter, list the provider, tested URL, and behaviors verified (composer, send, streaming, capture, safety alert handling).
