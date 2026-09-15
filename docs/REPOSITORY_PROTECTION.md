# Repository protection

`main` should require a pull request and the four CI jobs before merging. Force pushes and branch deletion should remain disabled, and unresolved review conversations should block merge.

The GitHub connector used by the maintainer workflow does not expose administration mutations for branch protection. A repository administrator can apply the intended policy with the checked-in script:

```bash
./scripts/configure_github_protection.sh ShynRdi/ai-workflow-bridge main
```

The script requires an authenticated GitHub CLI session with repository administration permission and then reads the protection settings back for verification.

Required status checks:

- `Python 3.11`
- `Python 3.12`
- `Python 3.13`
- `Extension and public hygiene`

The policy uses zero mandatory external approvals so a solo maintainer is not locked out, but changes still have to pass through a pull request and all required checks. Administrators are included in enforcement.
