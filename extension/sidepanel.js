let currentApprovalId = null;
let lastState = {};
const $ = (id) => document.getElementById(id);
const providers = globalThis.AWB_PROVIDERS || [];
const utils = globalThis.AWB_PROVIDER_UTILS;

function addLog(label, text) {
  const timeline = $("timeline");
  const item = document.createElement("div"); item.className = "timeline-item";
  const b = document.createElement("b"); b.textContent = label;
  const span = document.createElement("span"); span.textContent = text;
  item.append(b, span); timeline.prepend(item);
  while (timeline.children.length > 80) timeline.lastChild.remove();
}

async function command(action, extra = {}) {
  return chrome.runtime.sendMessage({ type: "BRIDGE_COMMAND", payload: { action, ...extra } });
}

function selectedProvider() { return utils.getProvider($("providerId").value) || providers[0]; }
function populateProviders() { $("providerId").replaceChildren(); for (const p of providers) { const option = document.createElement("option"); option.value = p.id; option.textContent = `${p.name} — ${p.status.toUpperCase()}`; $("providerId").append(option); } }
function updateProviderCard(provider = selectedProvider()) {
  $("providerName").textContent = provider.name; $("providerStatus").textContent = provider.status.toUpperCase();
  const notes = { stable: "Stable adapter. Still stops on provider security/rate-limit signals.", beta: "Beta web adapter: selectors can change when the provider updates its UI.", experimental: "Experimental adapter: verify the first few turns manually before long runs." };
  $("providerSafetyNote").textContent = `${notes[provider.status] || notes.beta} The Bridge never automates login or exports your session.`;
  $("activeProvider").textContent = provider.name.toUpperCase().slice(0, 13);
  const model = $("modelLabel")?.value?.trim(); $("providerDetail").textContent = model || ($("providerAuto").checked ? "Auto-detect active tab" : `${provider.status} adapter`);
}
async function providerForActiveTab() { const tabs = await chrome.tabs.query({ active: true, currentWindow: true }); const tab = tabs[0]; if (!tab?.url) return null; try { return utils.detectProvider(new URL(tab.url).hostname); } catch { return null; } }
async function effectiveProvider() { if (!$("providerAuto").checked) return selectedProvider(); const p = await providerForActiveTab(); if (!p) throw new Error("The active tab is not a supported LLM. Open one of the supported web LLMs first."); return p; }
async function grantProviderAccess({ quiet = false } = {}) { const provider = await effectiveProvider(); const contains = await chrome.permissions.contains({ origins: provider.origins }); if (contains) { if (!quiet) addLog("SAFE", `${provider.name} site access is already granted.`); return provider; } const granted = await chrome.permissions.request({ origins: provider.origins }); if (!granted) throw new Error(`Site access for ${provider.name} was not granted.`); addLog("UNLOCK", `Granted site access only for ${provider.name}.`); return provider; }
function numberValue(id, fallback) { const value = Number($(id).value); return Number.isFinite(value) ? value : fallback; }
function gatherConfig() { return { project_name: $("projectName").value.trim(), project_goal: $("projectGoal").value.trim(), workspace_root: $("workspaceRoot").value.trim(), provider_mode: $("providerAuto").checked ? "auto" : "manual", provider_id: $("providerId").value, model_label: $("modelLabel").value.trim(), auto_run_low_risk: $("autoRunLowRisk").checked, min_turn_interval_seconds: numberValue("minTurnInterval", 8), max_turns_per_hour: numberValue("maxTurnsHour", 20), max_turns_per_session: numberValue("maxTurnsSession", 25), max_runtime_minutes: numberValue("maxRuntimeMinutes", 90), bot_token: $("botToken").value.trim(), chat_id: $("chatId").value.trim() }; }
async function saveProject({ log = true } = {}) { const config = gatherConfig(); await command("save_config", { config }); if (log) addLog("SAVED", "Project, AI Engine, and safety limits saved locally."); }
function diagnosticCounts(checks = []) {
  return checks.reduce(
    (counts, item) => {
      const status = String(item?.status || "warn").toLowerCase();
      if (status === "pass") counts.pass += 1;
      else if (status === "fail") counts.fail += 1;
      else counts.warn += 1;
      return counts;
    },
    { pass: 0, warn: 0, fail: 0 },
  );
}

function diagnosticBadge(status = "warn") {
  const value = String(status || "warn").toLowerCase();
  if (value === "pass") return "PASS";
  if (value === "fail") return "FAIL";
  return "WARN";
}

function renderDiagnostics(result = {}) {
  const checks = Array.isArray(result.checks) ? result.checks : [];
  const overall = String(result.overall || "warn").toLowerCase();
  const counts = diagnosticCounts(checks);

  $("diagnosticsOverall").textContent = diagnosticBadge(overall);
  $("diagnosticsOverall").dataset.status = overall;

  $("diagnosticsSummary").textContent =
    `${counts.pass} pass · ${counts.warn} warning · ${counts.fail} fail`;

  const list = $("diagnosticsList");
  list.replaceChildren();

  if (!checks.length) {
    const empty = document.createElement("div");
    empty.className = "diagnostic-empty";
    empty.textContent = "No diagnostic results were returned.";
    list.append(empty);
    return;
  }

  for (const item of checks) {
    const status = String(item.status || "warn").toLowerCase();

    const row = document.createElement("div");
    row.className = `diagnostic-row diagnostic-${status}`;

    const statusNode = document.createElement("strong");
    statusNode.className = "diagnostic-status";
    statusNode.textContent = diagnosticBadge(status);

    const body = document.createElement("div");

    const label = document.createElement("b");
    label.textContent = item.label || item.id || "Diagnostic check";

    const detail = document.createElement("p");
    detail.textContent = item.detail || "";

    body.append(label, detail);

    if (item.remediation) {
      const remediation = document.createElement("small");
      remediation.className = "diagnostic-remediation";
      remediation.textContent = `Fix: ${item.remediation}`;
      body.append(remediation);
    }

    row.append(statusNode, body);
    list.append(row);
  }
}

async function runSystemDiagnostics() {
  const button = $("runDiagnostics");

  button.disabled = true;
  button.textContent = "RUNNING…";
  $("diagnosticsOverall").textContent = "RUNNING";
  $("diagnosticsOverall").dataset.status = "running";
  $("diagnosticsSummary").textContent =
    "Inspecting local and browser integration…";

  try {
    const response = await command("diagnostics");

    if (!response?.ok || !response?.diagnostics) {
      throw new Error(
        response?.error || "Diagnostics did not return a result.",
      );
    }

    renderDiagnostics(response.diagnostics);

    const overall = String(
      response.diagnostics.overall || "warn",
    ).toUpperCase();

    addLog(
      overall === "PASS" ? "HEALTHY" : "DIAG",
      `System diagnostics completed: ${overall}.`,
    );
  } catch (error) {
    renderDiagnostics({
      overall: "fail",
      checks: [
        {
          id: "diagnostics_runtime",
          label: "Diagnostics runtime",
          status: "fail",
          detail: String(error?.message || error),
          remediation:
            "Reload AI Workflow Bridge and retry diagnostics.",
        },
      ],
    });

    addLog(
      "CRASH",
      `Diagnostics failed: ${String(error?.message || error)}`,
    );
  } finally {
    button.disabled = false;
    button.textContent = "🩺 RUN DIAGNOSTICS";
  }
}

function formatCheckpointBytes(value) {
  const bytes = Number(value || 0);

  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }

  if (bytes < 1024) {
    return `${Math.round(bytes)} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function renderCheckpoint(state = {}) {
  const checkpoint =
    state.checkpoint || {};

  const available =
    checkpoint.available === true;

  const details =
    $("checkpointDetails");

  details?.classList.toggle(
    "hidden",
    !available,
  );

  if (!available) {
    $("checkpointStatus").textContent =
      "NONE";

    $("checkpointSummary").textContent =
      checkpoint.error ||
      "No workspace checkpoint is available yet.";

    $("acceptCheckpoint").disabled = true;
    $("rollbackCheckpoint").disabled = true;

    $("checkpointActionHint").textContent =
      "Protected checkpoints appear here before meaningful local mutations.";

    return;
  }

  const status = String(
    checkpoint.status || "unknown",
  );

  $("checkpointStatus").textContent =
    status
      .replaceAll("_", " ")
      .toUpperCase();

  $("checkpointSummary").textContent =
    checkpoint.command_summary ||
    "Protected workspace mutation";

  $("checkpointRisk").textContent =
    checkpoint.risk_level || "—";

  $("checkpointScope").textContent =
    String(
      checkpoint.rollback_scope ||
      "workspace_files_only",
    ).replaceAll("_", " ");

  $("checkpointFiles").textContent =
    String(
      checkpoint.file_count || 0,
    );

  $("checkpointBytes").textContent =
    formatCheckpointBytes(
      checkpoint.total_bytes,
    );

  $("checkpointId").textContent =
    checkpoint.checkpoint_id || "—";

  const limitations =
    $("checkpointLimitations");

  limitations.replaceChildren();

  const items = Array.isArray(
    checkpoint.limitations,
  )
    ? checkpoint.limitations
    : [];

  if (!items.length) {
    const row =
      document.createElement("div");

    row.className =
      "diagnostic-empty";

    row.textContent =
      "Rollback is limited to captured workspace files.";

    limitations.append(row);
  } else {
    for (const item of items) {
      const row =
        document.createElement("div");

      row.className =
        "recovery-approval";

      const textNode =
        document.createElement("small");

      textNode.textContent =
        `• ${String(item)}`;

      row.append(textNode);
      limitations.append(row);
    }
  }

  $("acceptCheckpoint").disabled =
    checkpoint.can_accept !== true;

  $("rollbackCheckpoint").disabled =
    checkpoint.can_rollback !== true;

  if (state.lifecycle === "recovery_required") {
    $("checkpointActionHint").textContent =
      "Checkpoint actions are locked until recovery review is resolved.";
  } else if (checkpoint.execution_active) {
    $("checkpointActionHint").textContent =
      "A local command is executing. Checkpoint decisions are temporarily locked.";
  } else if (checkpoint.rollback_requires_pause) {
    $("checkpointActionHint").textContent =
      "Pause the workflow before rolling back. Keeping the current state does not require rollback.";
  } else if (status === "ready") {
    $("checkpointActionHint").textContent =
      "Choose whether to keep the current workspace or restore captured workspace files.";
  } else {
    $("checkpointActionHint").textContent =
      `This checkpoint is ${status.replaceAll("_", " ")} and is no longer actionable.`;
  }
}

function renderRecovery(state = {}) {
  const recovery = state.recovery || null;
  const required =
    state.lifecycle === "recovery_required" &&
    recovery?.required === true;

  const panel = $("recoveryPanel");

  if (!panel) return;

  panel.classList.toggle("hidden", !required);

  if (!required) return;

  $("recoveryLifecycle").textContent =
    String(recovery.previous_lifecycle || "unknown")
      .replaceAll("_", " ")
      .toUpperCase();

  $("recoveryStatus").textContent =
    String(recovery.previous_status || "unknown")
      .replaceAll("_", " ")
      .toUpperCase();

  $("recoveryStep").textContent =
    recovery.previous_step || "No previous step recorded.";

  $("recoveryProvider").textContent =
    String(recovery.active_provider || "unknown")
      .toUpperCase();

  const guard = $("recoveryGuard");

  if (recovery.provider_guard) {
    guard.textContent =
      "Provider safety guard was active before interruption. " +
      "Recovery will not clear that guard automatically.";
    guard.classList.remove("hidden");
  } else {
    guard.textContent = "";
    guard.classList.add("hidden");
  }

  const checkpointRecovery =
    recovery.checkpoint_recovery;

  const checkpointBlock =
    $("recoveryCheckpointBlock");

  const hasCheckpointRecovery =
    checkpointRecovery &&
    typeof checkpointRecovery === "object";

  checkpointBlock?.classList.toggle(
    "hidden",
    !hasCheckpointRecovery,
  );

  if (hasCheckpointRecovery) {
    $("recoveryCheckpointStatus").textContent =
      String(
        checkpointRecovery.status ||
        "unknown",
      )
        .replaceAll("_", " ")
        .toUpperCase();

    $("recoveryCheckpointId").textContent =
      checkpointRecovery.checkpoint_id ||
      "—";

    $("recoveryCheckpointScope").textContent =
      String(
        checkpointRecovery.rollback_scope ||
        "workspace_files_only",
      ).replaceAll("_", " ");

    $("recoveryCheckpointNote").textContent =
      checkpointRecovery.note ||
      "Rollback completion could not be determined safely.";
  }

  const list = $("recoveryApprovals");
  list.replaceChildren();

  const approvals = Array.isArray(
    recovery.pending_approvals,
  )
    ? recovery.pending_approvals
    : [];

  if (!approvals.length) {
    const empty = document.createElement("div");
    empty.className = "diagnostic-empty";
    empty.textContent = "No pending approvals were recorded.";
    list.append(empty);
    return;
  }

  for (const approval of approvals) {
    const row = document.createElement("div");
    row.className = "recovery-approval";

    const summary = document.createElement("b");
    summary.textContent =
      approval.summary || "Protected action";

    const command = document.createElement("code");
    command.textContent =
      approval.command || "No command recorded";

    const impact = document.createElement("small");
    impact.textContent =
      approval.impact || "No impact description recorded.";

    row.append(summary, command, impact);
    list.append(row);
  }
}

function showApproval(event) { currentApprovalId = event.approval_id; $("approvalSummary").textContent = event.summary || "A protected action needs your approval."; $("approvalCommand").textContent = event.command || event.details || ""; $("approvalImpact").textContent = event.impact || "The workflow is paused until you decide."; $("approvalPanel").classList.remove("hidden"); }
function setLifecycleButtons(state) {
  const lifecycle =
    state.lifecycle || state.status || "setup";

  const recoveryRequired =
    lifecycle === "recovery_required";

  $("armWorkflow").disabled =
    recoveryRequired ||
    (
      ![
        "ready_to_arm",
        "idle",
        "paused",
        "protocol_error",
      ].includes(lifecycle) &&
      lifecycle !== "setup"
    );

  $("finishProject").disabled =
    recoveryRequired ||
    ["setup", "planning", "complete"].includes(lifecycle);

  for (const id of [
    "saveConfig",
    "planProject",
    "pauseWorkflow",
    "resumeWorkflow",
    "changeCourse",
    "resetSession",
  ]) {
    const node = $(id);
    if (node) node.disabled = recoveryRequired;
  }

  if ($("prepareRecovery")) {
    $("prepareRecovery").disabled = !recoveryRequired;
  }

  if ($("discardRecovery")) {
    $("discardRecovery").disabled = !recoveryRequired;
  }
}
function fillConfig(config) { if (config.project_name != null) $("projectName").value = config.project_name; if (config.project_goal != null) $("projectGoal").value = config.project_goal; if (config.workspace_root != null) $("workspaceRoot").value = config.workspace_root; if (config.provider_id && utils.getProvider(config.provider_id)) $("providerId").value = config.provider_id; if (config.model_label != null) $("modelLabel").value = config.model_label; $("providerAuto").checked = config.provider_mode === "auto"; $("autoRunLowRisk").checked = config.auto_run_low_risk !== false; if (config.min_turn_interval_seconds != null) $("minTurnInterval").value = config.min_turn_interval_seconds; if (config.max_turns_per_hour != null) $("maxTurnsHour").value = config.max_turns_per_hour; if (config.max_turns_per_session != null) $("maxTurnsSession").value = config.max_turns_per_session; if (config.max_runtime_minutes != null) $("maxRuntimeMinutes").value = config.max_runtime_minutes; if (config.bot_configured && !$("botToken").value) $("botToken").placeholder = "Configured locally — enter only to replace"; if (config.chat_id != null) $("chatId").value = config.chat_id; updateProviderCard(); }
function fillBudget(budget = {}, config = {}) { $("budgetTurns").textContent = `${budget.session_turns || 0} / ${config.max_turns_per_session || 25}`; $("budgetHour").textContent = `${budget.turns_last_hour || 0} / ${config.max_turns_per_hour || 20}`; $("budgetRuntime").textContent = `${Math.round(budget.runtime_minutes || 0)} / ${config.max_runtime_minutes || 90}m`; $("budgetCooldown").textContent = budget.cooldown_until ? "PAUSED" : "READY"; }
function handleEvent(event) { if (!event) return; if (event.kind === "host_status") {
    if (event.connecting) {
      $("hostStatus").textContent = "CONNECTING";
      $("hostStatusDetail").textContent = event.text || "Connecting to Native Messaging";
    } else {
      $("hostStatus").textContent = event.connected ? "ONLINE" : "OFFLINE";
      $("hostStatusDetail").textContent = event.text || "Native Messaging";
      addLog(event.connected ? "KAPOW" : "UH-OH", event.text || "Host status changed");
    }
  } else if (event.kind === "state") { const state = event.state || {}; lastState = state; const lifecycle = state.lifecycle || state.status || "setup"; $("runStatus").textContent = String(lifecycle).replaceAll("_", " ").toUpperCase(); $("runStatusDetail").textContent = state.current_step || "No active workflow"; fillConfig(state.config || {}); fillBudget(state.budget || {}, state.config || {}); renderCheckpoint(state); renderRecovery(state); setLifecycleButtons(state); if (state.active_provider_name) { $("activeProvider").textContent = state.active_provider_name.toUpperCase().slice(0,13); $("providerDetail").textContent = "active browser adapter"; } } else if (event.kind === "recovery_resolved") {
    $("recoveryPanel")?.classList.add("hidden");
    addLog(
      "RECOVERED",
      event.text || "Interrupted workflow reviewed.",
    );
  } else if (event.kind === "checkpoint") {
    addLog(
      "SAVE",
      event.text || "Workspace checkpoint created.",
    );

    setTimeout(
      () => command("get_state").catch(() => {}),
      50,
    );
  } else if (event.kind === "checkpoint_accepted") {
    addLog(
      "KEEP",
      event.text || "Checkpoint accepted.",
    );

    setTimeout(
      () => command("get_state").catch(() => {}),
      50,
    );
  } else if (event.kind === "checkpoint_rolled_back") {
    addLog(
      "UNDO",
      event.text || "Workspace checkpoint rolled back.",
    );

    setTimeout(
      () => command("get_state").catch(() => {}),
      50,
    );
  } else if (event.kind === "approval_required") { showApproval(event); addLog("WAIT!", event.summary || "Approval required"); } else if (event.kind === "approval_resolved") { $("approvalPanel").classList.add("hidden"); currentApprovalId = null; addLog("DECIDED", `${event.decision || "decision"}: ${event.summary || "approval resolved"}`); } else if (event.kind === "step") {
    const stepStatus = String(
      event.status || "running",
    );

    $("runStatus").textContent =
      stepStatus
        .replaceAll("_", " ")
        .toUpperCase();

    $("runStatusDetail").textContent =
      event.title ||
      event.text ||
      "Workflow step";

    addLog(
      event.badge || "BAM",
      event.text ||
      event.title ||
      "Step update",
    );

    // Refresh authoritative native state only after states
    // that can change checkpoint action availability.
    // In particular, waiting_llm arrives immediately before
    // the execution wrapper releases command_execution_active.
    if (
      [
        "paused",
        "waiting_llm",
        "failed",
        "idle",
        "complete",
      ].includes(stepStatus)
    ) {
      setTimeout(
        () => command("get_state").catch(() => {}),
        100,
      );
    }
  } else if (event.kind === "error") { $("runStatus").textContent = "PAUSED"; $("runStatusDetail").textContent = event.text || "Workflow error"; addLog("CRASH", event.text || "Unknown error"); } else if (event.kind === "info") addLog(event.badge || "INFO", event.text || "Update"); }
chrome.runtime.onMessage.addListener((message) => { if (message?.type === "BRIDGE_EVENT") handleEvent(message.payload); });
populateProviders(); $("providerId").value = "chatgpt"; updateProviderCard(); $("providerId").addEventListener("change", updateProviderCard); $("providerAuto").addEventListener("change", updateProviderCard); $("modelLabel").addEventListener("input", updateProviderCard); $("grantProvider").addEventListener("click", () => grantProviderAccess().catch((e) => addLog("NOPE", e.message))); $("saveConfig").addEventListener("click", () => saveProject().then(() => setTimeout(() => command("get_state"), 200)).catch((e) => addLog("CRASH", e.message)));
$("runDiagnostics").addEventListener("click", () => runSystemDiagnostics());

$("prepareRecovery").addEventListener("click", async () => {
  try {
    await command("recovery_prepare");
    addLog(
      "RECOVER",
      "Recovery reviewed and rebound to the active LLM tab. You may now use ARM & RUN.",
    );
  } catch (error) {
    addLog(
      "CRASH",
      String(error?.message || error),
    );
  }
});

$("discardRecovery").addEventListener("click", async () => {
  try {
    await command("recovery_discard");
    addLog(
      "STOP",
      "Interrupted run discarded. No interrupted action was replayed.",
    );
  } catch (error) {
    addLog(
      "CRASH",
      String(error?.message || error),
    );
  }
});
$("acceptCheckpoint").addEventListener(
  "click",
  async () => {
    try {
      const checkpoint =
        lastState?.checkpoint;

      if (
        !checkpoint ||
        checkpoint.can_accept !== true
      ) {
        throw new Error(
          "The checkpoint is not currently available for acceptance.",
        );
      }

      await command(
        "checkpoint_accept",
      );

      addLog(
        "KEEP",
        "Keeping the current workspace state.",
      );

      setTimeout(
        () => command("get_state").catch(() => {}),
        100,
      );
    } catch (error) {
      addLog(
        "CRASH",
        String(
          error?.message || error,
        ),
      );
    }
  },
);

$("rollbackCheckpoint").addEventListener(
  "click",
  async () => {
    try {
      const checkpoint =
        lastState?.checkpoint;

      if (
        !checkpoint ||
        checkpoint.can_rollback !== true
      ) {
        throw new Error(
          "Pause the workflow before rolling back this checkpoint.",
        );
      }

      const confirmed = globalThis.confirm(
        [
          "Roll back captured workspace files?",
          "",
          "This DOES NOT undo:",
          "• Git history or .git metadata",
          "• remote actions such as git push",
          "• database changes",
          "• system/package changes",
          "• .ai-workflow state",
          "• excluded volatile directories",
          "",
          "The workflow will remain paused after rollback.",
        ].join("\n"),
      );

      if (!confirmed) {
        addLog(
          "CANCEL",
          "Workspace rollback cancelled.",
        );
        return;
      }

      await command(
        "checkpoint_rollback",
      );

      addLog(
        "UNDO",
        "Explicit workspace rollback requested.",
      );

      setTimeout(
        () => command("get_state").catch(() => {}),
        100,
      );
    } catch (error) {
      addLog(
        "CRASH",
        String(
          error?.message || error,
        ),
      );
    }
  },
);

$("planProject").addEventListener("click", async () => { try { if (!$("projectGoal").value.trim()) throw new Error("Add a project goal/master brief before planning."); const p = await grantProviderAccess({ quiet: true }); await saveProject({ log: false }); await command("plan_project"); addLog("PLAN!", `Sent the protected project-start prompt to ${p.name}.`); } catch (e) { addLog("CRASH", e.message); } });
$("armWorkflow").addEventListener("click", async () => { try { const p = await grantProviderAccess({ quiet: true }); await saveProject({ log: false }); await command("arm"); addLog("ZAP!", `Arming the current ${p.name} thread.`); } catch (e) { addLog("CRASH", e.message); } });
$("pauseWorkflow").addEventListener("click", () => command("pause")); $("resumeWorkflow").addEventListener("click", () => command("resume")); $("refreshState").addEventListener("click", () => command("get_state")); $("resetSession").addEventListener("click", () => command("reset_session"));
$("changeCourse").addEventListener("click", async () => { try { const text = $("changeRequest").value.trim(); if (!text) throw new Error("Describe the course change first."); await grantProviderAccess({ quiet: true }); await command("change_course", { change_request: text }); addLog("PIVOT?", "Course-change review requested. No project commands will run until you approve the impact."); } catch (e) { addLog("CRASH", e.message); } });
$("finishProject").addEventListener("click", async () => { try { await grantProviderAccess({ quiet: true }); await command("finish_project"); addLog("CHECK!", "Final verification/closeout requested."); } catch (e) { addLog("CRASH", e.message); } });
$("approveButton").addEventListener("click", async () => { if (currentApprovalId) await command("approval", { approval_id: currentApprovalId, decision: "approve" }); });
$("rejectButton").addEventListener("click", async () => { if (currentApprovalId) await command("approval", { approval_id: currentApprovalId, decision: "reject" }); });
command("ping").catch(() => {}); setTimeout(() => command("get_state").catch(() => {}), 250);
