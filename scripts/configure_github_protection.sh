#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-ShynRdi/ai-workflow-bridge}"
BRANCH="${2:-main}"

command -v gh >/dev/null || { echo "ERROR: GitHub CLI (gh) is required." >&2; exit 2; }
gh auth status >/dev/null

echo "Applying branch protection to ${REPO}:${BRANCH}"
gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/${REPO}/branches/${BRANCH}/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Python 3.11",
      "Python 3.12",
      "Python 3.13",
      "Extension and public hygiene"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
JSON

echo
echo "Protection summary:"
gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/${REPO}/branches/${BRANCH}/protection" \
  --jq '{required_status_checks, enforce_admins, required_pull_request_reviews, required_conversation_resolution, allow_force_pushes, allow_deletions}'
