#!/usr/bin/env bash
set -euo pipefail
OWNER="${GITHUB_OWNER:-ShynRdi}"; REPO="${GITHUB_REPO:-ai-workflow-bridge}"; FULL="$OWNER/$REPO"
DESCRIPTION="Guarded bridge between web LLMs and local development workflows, with approvals, roadmaps, rate limits, and account-safe automation."
command -v git >/dev/null || { echo "git is required" >&2; exit 2; }
command -v gh >/dev/null || { echo "GitHub CLI (gh) is required: https://cli.github.com/" >&2; exit 2; }
gh auth status >/dev/null
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
python3 scripts/check_public_hygiene.py; python3 -m compileall -q native_host tests; python3 -m pytest -q
for f in extension/*.js; do node --check "$f"; done
bash -n install_native_host.sh native_host/launcher.sh
git init -b main 2>/dev/null || true; git add .
if ! git diff --cached --quiet; then git commit -m "feat: publish AI Workflow Bridge 0.2.1 public preview"; fi
if gh repo view "$FULL" >/dev/null 2>&1; then
  echo "Repository already exists: https://github.com/$FULL"
  if ! git remote get-url origin >/dev/null 2>&1; then git remote add origin "https://github.com/$FULL.git"; fi
  git push -u origin main
else
  gh repo create "$FULL" --public --description "$DESCRIPTION" --source=. --remote=origin --push
fi
gh repo edit "$FULL" --description "$DESCRIPTION" --enable-issues=true --enable-discussions=true --enable-wiki=false
for topic in llm chrome-extension automation developer-tools native-messaging workflow-automation chatgpt claude gemini deepseek python open-source; do gh repo edit "$FULL" --add-topic "$topic" >/dev/null; done
gh label create "provider-adapter" --repo "$FULL" --color "6f42c1" --description "Web LLM provider adapter work" --force >/dev/null
gh label create "security" --repo "$FULL" --color "b60205" --description "Security or safety hardening" --force >/dev/null
gh label create "skip-changelog" --repo "$FULL" --color "ededed" --description "Exclude from generated release notes" --force >/dev/null
gh api --method PUT "repos/$FULL/private-vulnerability-reporting" >/dev/null 2>&1 || true
python3 scripts/package_extension.py >/dev/null; TAG="v0.2.1"
if ! git rev-parse "$TAG" >/dev/null 2>&1; then git tag -a "$TAG" -m "AI Workflow Bridge 0.2.1 Public Preview"; git push origin "$TAG"; fi
if ! gh release view "$TAG" --repo "$FULL" >/dev/null 2>&1; then gh release create "$TAG" --repo "$FULL" --prerelease --title "AI Workflow Bridge 0.2.1 Public Preview" --notes-file docs/releases/v0.2.1.md dist/ai-workflow-bridge-extension-0.2.1.zip; fi
echo; echo "Published: https://github.com/$FULL"; echo "Release:   https://github.com/$FULL/releases/tag/$TAG"; echo "Next: review Settings → Branches/Rules and enable branch protection for main after the first CI run."
