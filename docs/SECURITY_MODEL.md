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

### Per-project security policy profiles

Each workspace has native-host-owned policy state at `<workspace>/.ai-workflow/POLICY.json`. Missing legacy state resolves to the backward-compatible **Balanced** profile. The file is revisioned and protected with the same no-follow/atomic-write discipline as other native state.

**Strict** adds stronger restrictions for remote, network, and outside-workspace actions. **Balanced** preserves normal guarded development behavior and is the backward-compatible default for legacy projects. **Isolated Development** may allow only narrowly proven workspace-local setup actions; it does **not** select or provide execution isolation. Policy determines whether a command may execute. The separate execution configuration determines where an allowed command runs.

Only an explicit human Mission Control action can change a profile. The action is bound to the exact displayed policy revision, so stale UI actions fail closed. LLM contracts and generic configuration cannot select or relax a profile. Profile changes are blocked during recovery, command execution, pending approvals, and active workflow windows; they never replay commands, resume work, or accept checkpoints or stage reviews.

Immutable destructive and credential-path blocks apply to every profile. Compound shell/control/redirection/substitution syntax is rejected before profile lowering. The LLM risk assessment can increase effective risk but cannot lower deterministic policy risk. Profile state survives restart and recovery without replaying or resuming work.

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

### Browser-tab binding

User-initiated lifecycle actions bind the workflow to the currently active supported LLM tab.

Automated follow-up turns continue through that bound tab rather than whichever matching provider tab happens to be active later. Completed responses and provider-safety signals from other supported LLM tabs are ignored for the bound workflow.

This reduces cross-conversation confusion when multiple tabs from the same provider are open.

### Workspace checkpoints and rollback

Protected R2/R3 execution creates a bounded workspace-file checkpoint after required approval and before command execution.

Rollback is always an explicit human action. It cannot run while a local command is executing and requires the workflow to be paused.

Checkpoint restore validates archive integrity, member paths and member types before restoring captured workspace files. Interrupted rollback is treated as uncertain state and is never automatically retried after restart.

Checkpoint metadata also records read-only Git evidence. This includes repository, branch, HEAD and coarse dirty, index and working-tree indicators. Comparison digests are stored instead of raw source diff contents.

After rollback, the Bridge re-inspects Git state and reports whether HEAD, branch, index or working-tree status differs from the checkpoint. This is advisory human-review evidence only. The rollback engine never performs Git reset, checkout, index restoration, ref rewriting or other Git repair.

Checkpoint acceptance and rollback requests include the exact checkpoint identity shown to the user. A stale or mismatched checkpoint identity fails closed rather than applying the action to whichever checkpoint happens to be newest.

### Structured stage diff review

Before an immediate-next-stage transition, the Bridge collects a bounded structured review for the canonical current stage. It records acceptance criteria, changed-file statuses, baseline/current HEAD and branch, attribution confidence, and a unique review identity; it does not persist raw source diffs.

The native host recomputes freshness from read-only Git inspection. A changed branch, baseline, HEAD, worktree evidence, or stage identity makes the review stale. Native-owned `.ai-workflow` paths are excluded from product change evidence. Only an explicit human acceptance of the exact fresh review permits the transition. LLM text, confidence, command output, and successful exit codes are evidence inputs, never product acceptance.

Review collection and inspection use only read-only Git operations. Checkpoint rollback remains workspace-file-only and never rewrites Git refs, HEAD, index, or other metadata.

### Diagnostics

System diagnostics are designed as read-only health inspection. Running diagnostics does not request new provider permissions, inject a content script, submit an LLM prompt or execute a project command.

Diagnostics may report a warning when a provider tab/content script is unavailable rather than mutating browser state to repair it automatically.

### Execution isolation and Docker boundary

The native host owns canonical per-project `<workspace>/.ai-workflow/EXECUTION.json`. Only explicit human Mission Control actions can change host/container mode or image and resource budgets. The action uses compare-and-set against the exact execution revision displayed by the UI and also binds to the displayed workspace. Generic `config.json` and workflow contracts cannot choose execution mode or alter Docker settings. The deterministic policy, approval, and checkpoint sequence remains authoritative and runs before backend selection.

Host mode executes as the current host user and has no OS/container isolation. Container mode supports Docker only, uses `--network none`, local images only, CPU/memory/pids budgets, a read-only root, and a read-only `.ai-workflow` mount. It does not mount `docker.sock`, forward the host environment, or expose arbitrary mounts, capabilities, devices, network modes, Docker arguments, or entrypoints. `--pull=never` and local image inspection prevent intentional registry access during preflight and execution. Docker Desktop on macOS runs Linux containers inside a Linux VM.

The Docker daemon and host remain trusted. This is defense in depth, not a perfect hostile-code or multi-tenant boundary. Docker bugs, kernel/runtime vulnerabilities, resource behavior, and host-level effects remain possible. Docker execution does not roll back workspace files, `.git` metadata, database changes, or external side effects.

### Durable container recovery

Before Docker can create a container, the native host atomically writes a bounded, project-local `<workspace>/.ai-workflow/EXECUTION_RUNTIME.json` containing an opaque execution identity, exact Bridge-generated container name, hashed workspace identity, runtime, timestamp, and state. The file and parent directory are fsynced before Docker launch. It contains no command, secrets, raw environment, Docker auth, host home, or absolute workspace path. All required Bridge ownership labels must match the journal exactly; unrelated Docker labels are allowed. Cleanup uses the full 64-character immutable ID returned by inspection, then verifies that same ID is absent. A same-name container replacement cannot redirect deletion. Configuration updates, launch claims, and explicit recovery share a project-local coordination lock, with runtime journal lock acquired second.

After a restart, a valid journal never resumes the command or silently removes a container. It blocks new command execution in both host and container mode and is shown in Mission Control. Recovery is an explicit human action bound to that exact journal revision. If the exact name is absent, the human can clear the stale record. If it exists, removal is allowed only after exact Bridge labels match, and journal clearing waits for confirmed absence. Label mismatch, malformed journal, or unavailable/uncertain Docker inspection fails closed and retains the record for manual review. Cleanup never enumerates containers for deletion and never uses broad prune operations.

The journal makes container identity recoverable after parent-process failure; it does not make the command transactional. SIGKILL or power loss can interrupt writes or Docker operations. Filesystem changes, Git metadata, databases, and external effects are not automatically undone. No command is automatically replayed.

## Known limitations

### Checkpoint rollback is not transactional

A checkpoint covers only the captured workspace-file scope. It does not restore Git metadata or history under `.git`, native-owned `.ai-workflow` state, excluded volatile directories, remote or API effects, database state, system package changes, or other external side effects.

A crash during rollback may leave the workspace in an uncertain partially restored state. The Bridge therefore requires explicit recovery review instead of automatically retrying rollback.

Git-aware review does not make Git metadata transactional. A workspace-file rollback can restore visible file contents while the Git index, HEAD, branch or refs still reflect post-checkpoint operations. Such divergence is reported for manual review rather than automatically repaired.

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
