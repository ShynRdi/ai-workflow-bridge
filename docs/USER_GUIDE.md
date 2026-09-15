# AI Workflow Bridge 0.2.1 — Complete User Guide

AI Workflow Bridge connects a web LLM conversation to a guarded local runner. The LLM plans and emits a machine-readable workflow contract; the native host executes only approved/local-safe commands, returns stdout/stderr to the same conversation, and stops whenever a human decision or provider safety condition appears.

## What it is — and what it is not

It **is**:
- a local workflow orchestrator;
- a Chrome extension plus a local Python native host;
- a bridge between a supported web LLM tab and your local project workspace;
- a guarded command runner with approval gates, roadmap enforcement, rate limits and execution budgets.

It is **not**:
- an API wrapper around the LLM provider;
- a login bot;
- a CAPTCHA/security bypass;
- a cookie/session exporter;
- a headless browser farm;
- a system that silently swaps one LLM provider for another.

## Supported web LLM adapters

Support levels describe the Bridge adapter, not the quality of the LLM itself.

| Provider | Status | Typical web domain |
|---|---|---|
| ChatGPT | Stable | chatgpt.com |
| Claude | Beta | claude.ai |
| Gemini | Beta | gemini.google.com |
| DeepSeek | Beta | chat.deepseek.com |
| Grok | Beta | grok.com |
| Perplexity | Beta | perplexity.ai |
| Mistral Vibe | Beta | chat.mistral.ai |
| Microsoft Copilot | Beta | copilot.com |
| Z.ai / GLM | Beta | chat.z.ai |
| Meta AI | Experimental | meta.ai |
| Poe | Experimental | poe.com |
| Qwen | Experimental | qwen.ai / chat.qwen.ai |
| Kimi | Experimental | kimi.com |

Web interfaces change. Beta/Experimental adapters may need selector updates after a provider redesigns its UI.

## Provider vs model

The Bridge separates:
- **Provider**: ChatGPT, Claude, DeepSeek, etc.
- **Model label**: optional text such as `GPT-5.6`, `Claude Sonnet`, `DeepSeek R1`.

The Bridge intentionally does **not** automate model-picker UI. Select the desired model manually inside the provider website, then optionally record the model name in the Side Panel for logs and reports.

---

# 1. Installation

## 1.1 Load the Chrome extension

Open:

```text
chrome://extensions
```

Enable Developer Mode and choose **Load unpacked**. Select the `extension/` directory.

## 1.2 Install the Native Messaging host

From the project root:

```bash
./install_native_host.sh YOUR_EXTENSION_ID
```

Reload the extension in `chrome://extensions`.

The Side Panel should show:

```text
HOST  ONLINE
```

## 1.3 Open your LLM yourself

Open the provider website normally and sign in manually.

The Bridge never signs in for you and never asks for your password or cookies.

---

# 2. Site permissions

Version 0.2.1 does **not** request access to every LLM website at install time.

Choose your Web LLM in **AI Engine + Safety**, then click:

```text
GRANT SITE ACCESS
```

Chrome grants the extension access only to that selected provider's site.

This is deliberate. The extension has no `cookies` permission and does not need access to unrelated websites.

---

# 3. The project lifecycle

The canonical lifecycle is:

```text
SETUP
  ↓
PLANNING
  ↓
READY_TO_ARM
  ↓
RUNNING
  ↓
[CHANGE_REVIEW when requested]
  ↓
RUNNING
  ↓
FINISHING
  ↓
COMPLETE
```

The Bridge distinguishes **stage completion** from **project completion**.

---

# 4. Starting a new project

## Step A — Project Brief

Fill in:

- Project name
- Workspace path
- Project goal / master brief
- Initial phase
- Initial stage

The **Project goal / master brief** is the main human requirement. Put product requirements, constraints, out-of-scope items, technology requirements, deployment rules and anything the LLM must preserve here.

Example:

```text
Build a multi-tenant white-label cafe platform.
Use TypeScript and PostgreSQL.
Runtime AI features use AvalAI.
Do not touch the existing Vivaldi production server.
The product must support tenant branding, menu management, AI recipes,
AI product images, custom domains, Docker deployment and safe server provisioning.
Production/server operations always require approval.
```

Click **SAVE PROJECT**.

## Step B — Choose AI Engine

Choose a provider and optionally enter a model label.

Recommended for first-time testing:

```text
Provider: ChatGPT
Model label: whichever model you selected manually in ChatGPT
```

Keep conservative defaults initially.

## Step C — PLAN PROJECT

Click:

```text
✦ PLAN PROJECT
```

The Bridge generates and sends the initial planning prompt automatically.

No local commands should run during this stage.

The LLM must produce:
- project interpretation;
- architecture;
- scope boundaries;
- security rules;
- testing strategy;
- roadmap and acceptance criteria;
- explicit human decisions;
- a machine-readable canonical roadmap.

The planning response must contain:

```text
<<<AI_WORKFLOW_ROADMAP>>>
{
  "phases": [
    {
      "id": "CP-0",
      "title": "Foundation",
      "stages": ["BOOTSTRAP", "ARCHITECTURE", "VERIFY"]
    }
  ]
}
<<<END_AI_WORKFLOW_ROADMAP>>>
```

and end with:

```text
READY_TO_ARM
```

The Bridge stores that roadmap locally as the canonical allowed sequence.

## Step D — Review before execution

Read the LLM's plan.

If the roadmap is wrong, **do not ARM**. Edit the Project Brief or discuss the plan and run planning again.

If the roadmap is acceptable, click:

```text
⚡ ARM & RUN
```

---

# 5. What the initial planning prompt looks like

The Bridge generates a prompt equivalent to:

```text
AI WORKFLOW BRIDGE — PROJECT START

Project: <PROJECT NAME>
Workspace: <WORKSPACE>
Initial phase/stage: <PHASE> / <STAGE>

MASTER BRIEF
<YOUR PROJECT GOAL>

For this FIRST response, PLAN ONLY.
Do not emit executable AI_WORKFLOW commands.

Produce:
- architecture;
- authoritative roadmap;
- acceptance criteria;
- security/privacy boundaries;
- testing strategy;
- human decisions;
- completion and rollback expectations.

Before READY_TO_ARM include a machine-readable AI_WORKFLOW_ROADMAP.
Do not silently change the roadmap later.

End exactly with:
READY_TO_ARM
```

You normally do not need to copy/paste this prompt yourself; the Side Panel builds it from Project Brief.

---

# 6. ARM & RUN — what happens internally

After you click **ARM & RUN**:

1. The extension pins the current supported LLM tab.
2. The native host sends the controller protocol.
3. The LLM emits an `AI_WORKFLOW` contract.
4. The Bridge validates phase/stage against the stored roadmap.
5. Commands are classified by policy.
6. Low-risk local commands may auto-run if enabled.
7. Protected commands pause for approval.
8. Blocked commands never run.
9. stdout/stderr/exit code/Git state return to the same LLM conversation.
10. The LLM analyzes the real terminal result and emits the next contract.
11. The loop continues until pause, decision, safety brake, budget brake, stage stop, or project finish.

Typical contract:

```text
<<<AI_WORKFLOW>>>
{
  "version": 1,
  "phase": "CP-0",
  "stage": "BOOTSTRAP",
  "summary": "Inspect repository and runtime",
  "decision_required": false,
  "decision_reason": "",
  "downloads": [],
  "commands": [
    {
      "cmd": "git status --short",
      "cwd": ".",
      "purpose": "inspect repository state"
    }
  ],
  "success_conditions": [
    "git status completes successfully"
  ],
  "next_step": "bootstrap the project"
}
<<<END_AI_WORKFLOW>>>
```

Prose is never executable. Only contract commands are considered by the runner.

---

# 7. Automatic roadmap progression

The canonical roadmap is stored after planning.

If the current position is:

```text
CP-0 / BOOTSTRAP
```

and the next canonical stage is:

```text
CP-0 / ARCHITECTURE
```

an LLM contract targeting that exact immediate next stage can advance automatically.

If the LLM attempts:

```text
CP-0 / BOOTSTRAP
→ CP-4 / DEPLOY
```

and that is not the immediate next canonical position, the Bridge stops and asks for approval instead of silently following the model.

This is how the system stays autonomous without letting the LLM rewrite the roadmap on its own.

---

# 8. Changing direction in the middle of a project

Do **not** simply type a new direction into the LLM and expect the runner to follow it.

Use **Change course** in the Side Panel.

Example:

```text
Do not use Redis anymore.
Use PostgreSQL-backed jobs instead, keep completed work if possible,
and explain what roadmap stages must change.
```

Click:

```text
↪ REVIEW COURSE CHANGE
```

The Bridge enters:

```text
CHANGE_REVIEW
```

No project commands run during this review.

The LLM must return a structured change review including:
- summary;
- impact;
- recommendation;
- proposed phase/stage;
- roadmap changes;
- replacement canonical roadmap.

The Bridge then shows a **WAIT! Decision Required** panel.

### If you APPROVE

The Bridge:
- updates canonical phase/stage if required;
- updates the canonical machine-readable roadmap;
- tells the LLM the change was approved;
- requires roadmap/current-state docs to be updated before dependent implementation;
- resumes execution from preserved project state.

### If you REJECT

The Bridge:
- keeps the current roadmap unchanged;
- informs the LLM the course change was rejected;
- continues only within the existing scope.

This prevents a casual chat message from silently invalidating the project plan.

---

# 9. Pausing and resuming

Use:

```text
⏸ PAUSE
```

when you want a manual stop.

A response arriving while paused does not execute commands.

Use:

```text
▶ RESUME
```

for a normal user pause.

Provider-security pauses are different. If the provider shows a rate-limit/auth/security warning, normal Resume is refused until you resolve the warning and explicitly reset the guarded session.

---

# 10. Finishing a project

Project completion is explicit.

Click:

```text
🏁 FINISH PROJECT
```

The Bridge enters:

```text
FINISHING
```

The LLM is instructed not to declare success immediately. It must determine whether final work remains, such as:
- tests;
- build/type-check;
- documentation;
- migration verification;
- Git/worktree inspection;
- final health checks;
- deployment notes;
- remaining limitations.

If final local checks are required, the normal guarded contract loop continues.

Only after required verification is complete should the LLM end with:

```text
<<<AI_WORKFLOW_PROJECT_DONE>>>
```

The Bridge then enters:

```text
COMPLETE
```

and stops execution.

A normal stage stop marker:

```text
<<<AI_WORKFLOW_STOP>>>
```

is **not** the same as project completion.

---

# 11. Account-safe rate limits and autonomy budget

Default safeguards:

```text
Minimum time between AI turns: 8 seconds
Max AI turns per hour:          20
Max AI turns per session:       25
Max autonomous runtime:         90 minutes
```

These are Bridge-side safety limits. They are intentionally independent of provider plan limits.

If a limit is reached, the Bridge stops before sending another prompt.

It does not try to bypass the limit.

It does not automatically switch provider accounts.

Use **RESET RUN BUDGET** only after reviewing why the limit was hit.

For a new provider or an Experimental adapter, use stricter limits during testing.

---

# 12. Provider security signals

The content script conservatively watches provider alert/dialog surfaces for signals such as:
- rate limit / too many requests;
- usage/message limit;
- session expired;
- unusual/suspicious activity;
- security verification;
- CAPTCHA / verify-you-are-human prompts.

If detected:

```text
SHIELD!
```

appears and the workflow immediately pauses.

The Bridge:
- does not auto-retry;
- does not rotate providers;
- does not change accounts;
- does not manipulate security challenges;
- does not hide automation behavior from the provider.

Resolve the issue manually in the provider UI first.

---

# 13. Permissions and secrets

The extension intentionally does not request:
- `cookies`;
- password access;
- browser history;
- all-site access.

Provider access is optional and granted per selected service.

Telegram Bot Token is stored by the native host, not injected into provider pages.

Project secrets should remain in server/local environment files and should not be pasted into the LLM chat unless you explicitly intend to share them with that provider.

---

# 14. Files generated by the LLM

If the LLM generates a file required for execution:

1. The contract declares it in `downloads`.
2. The extension downloads the attachment.
3. The native host copies it into a quarantine/run directory.
4. SHA-256 is recorded.
5. ZIP paths are inspected for traversal/suspicious entries.
6. Commands refer to the safe directory using:

```text
${AI_WORKFLOW_DOWNLOAD_DIR}
```

The LLM must not assume `~/Downloads`.

---

# 15. Command safety

Typical auto-run candidates:
- `pwd`
- `ls`
- `git status`
- `git diff`
- tests/type-check/lint commands already in the allowlist
- non-mutating runtime discovery

Typical approval-required actions:
- dependency installation/removal;
- Git push/merge/rebase;
- migrations;
- SSH/remote access;
- unclassified scripts;
- system package changes;
- compound shell syntax.

Examples of blocked commands include destructive system/Git/disk operations such as recursive forced deletion and `git reset --hard`.

No policy should be interpreted as permission to run production changes without explicit approval.

---

# 16. Multi-LLM behavior

The workflow uses one selected web LLM at a time.

There is no automatic provider fallback.

If ChatGPT is rate-limited, the Bridge does **not** silently move the project to Claude or DeepSeek.

To change provider intentionally:
1. Pause the project.
2. Open/log into the new provider manually.
3. Select the new provider in AI Engine.
4. Grant that provider's site access.
5. Save Project.
6. Prefer a fresh conversation with a current project-state summary, or consciously continue if context was migrated by you.
7. Resume/arm only after checking the model has the canonical roadmap/current state.

Changing provider is a human-controlled operation because model context and privacy boundaries differ across services.

---

# 17. Recommended first-run workflow

For a new project:

```text
1. Create/open local Git workspace
2. Open your chosen LLM web app and sign in manually
3. Fill Project Brief
4. Choose provider + optional model label
5. Set strict safety limits
6. Grant provider site access
7. PLAN PROJECT
8. Review roadmap
9. ARM & RUN
10. Watch the first 2–3 contracts manually
11. Let low-risk execution continue
12. Approve only genuinely understood protected actions
13. Use CHANGE COURSE for scope changes
14. FINISH PROJECT for final verification and closeout
```

---

# 18. Mission Log badges

Common badges:

| Badge | Meaning |
|---|---|
| `PLAN!` | project planning prompt sent |
| `READY!` | roadmap accepted by protocol; ready to arm |
| `ZAP!` | workflow controller being armed |
| `ARMED` | prompt successfully submitted |
| `POP!` | completed LLM response captured |
| `SCAN` | contract validation |
| `BAM!` | local command executing |
| `PASS` / `FAIL` | command result |
| `WHOOSH` | terminal report returned to LLM |
| `WAIT!` | human approval required |
| `NEXT!` | canonical roadmap transition accepted |
| `PIVOT?` | course-change review |
| `COOL` | waiting for minimum turn interval |
| `BRAKE!` | autonomy budget stopped the run |
| `SHIELD!` | provider account-safety signal stopped the run |
| `CHECK!` | project finalization requested |
| `FIN!` | project-wide completion confirmed |

---

# 19. Troubleshooting

## Provider tab not found

Open the selected web provider in a normal Chrome tab. If Auto Detect is enabled, make that tab active.

## Site access not granted

Click **GRANT SITE ACCESS**. The extension does not request all provider origins by default.

## Prompt inserted but not submitted

The provider changed its composer/send-button DOM. Stable/Beta adapters can require selector updates after UI changes.

## Response captured but no command executes

Check Mission Log for:
- invalid/missing workflow contract;
- roadmap mismatch;
- human decision required;
- pause/budget/provider safety state.

## Repeated rate-limit/security message

Stop. Do not keep resetting the budget. Resolve the account/provider condition manually and reduce automation limits before continuing.

---

# 20. Core principle

The design goal is not “make the LLM powerful enough to do anything.”

The design goal is:

```text
LLM reasoning
      ↓
structured intent
      ↓
roadmap validation
      ↓
local policy
      ↓
human approval where needed
      ↓
deterministic execution
      ↓
real terminal evidence
      ↓
LLM reasoning again
```

The LLM proposes. The Bridge constrains. Your machine executes. The human owner remains the final authority.
