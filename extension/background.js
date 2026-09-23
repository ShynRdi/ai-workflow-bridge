importScripts("providers.js");

const NATIVE_HOST = "io.github.shynrdi.ai_workflow_bridge";
const PINNED_TAB_STORAGE_KEY = "pinnedLlmTabId";
let nativePort = null;
let nativeReady = false;
let reconnectTimer = null;
let nativeHandshakeTimer = null;
let nativeDisconnectReason = "";
let reconnectAttempt = 0;
let lastLlmTabId = null;
let responseWatchdog = null;

const NATIVE_HANDSHAKE_TIMEOUT_MS = 8000;
const NATIVE_RECONNECT_DELAYS_MS = [2500, 5000, 10000, 20000, 30000];
const DIAGNOSTICS_TIMEOUT_MS = 6000;
const pendingDiagnostics = new Map();

const providers = globalThis.AWB_PROVIDERS || [];
const utils = globalThis.AWB_PROVIDER_UTILS;

function broadcast(message) {
  chrome.runtime.sendMessage({ type: "BRIDGE_EVENT", payload: message }).catch(() => {});
}

function clearNativeHandshakeTimer() {
  if (nativeHandshakeTimer) clearTimeout(nativeHandshakeTimer);
  nativeHandshakeTimer = null;
}

function markNativeReady(message) {
  if (nativeReady) return;

  nativeReady = true;
  reconnectAttempt = 0;
  nativeDisconnectReason = "";
  clearNativeHandshakeTimer();

  if (message?.kind !== "host_status") {
    broadcast({
      kind: "host_status",
      connected: true,
      text: "Native host connected",
    });
  }
}

function handleNativeDisconnect(port, reason = "") {
  if (nativePort !== port) return;

  clearNativeHandshakeTimer();

  nativePort = null;
  nativeReady = false;

  const text =
    reason ||
    nativeDisconnectReason ||
    "Native host disconnected";

  nativeDisconnectReason = "";

  broadcast({
    kind: "host_status",
    connected: false,
    text,
  });

  scheduleReconnect();
}

function connectNative() {
  if (nativePort) return;

  nativeReady = false;
  nativeDisconnectReason = "";

  broadcast({
    kind: "host_status",
    connected: false,
    connecting: true,
    text: "Connecting to native host…",
  });

  try {
    const port = chrome.runtime.connectNative(NATIVE_HOST);
    nativePort = port;

    port.onMessage.addListener((message) => {
      if (nativePort !== port) return;
      handleNativeMessage(message);
    });

    port.onDisconnect.addListener(() => {
      const error =
        chrome.runtime.lastError?.message ||
        nativeDisconnectReason ||
        "Native host disconnected";

      handleNativeDisconnect(port, error);
    });

    nativeHandshakeTimer = setTimeout(() => {
      if (nativePort !== port || nativeReady) return;

      nativeDisconnectReason = "Native host handshake timed out";

      try {
        port.disconnect();
      } catch {}

      handleNativeDisconnect(
        port,
        "Native host handshake timed out",
      );
    }, NATIVE_HANDSHAKE_TIMEOUT_MS);
  } catch (error) {
    nativePort = null;
    nativeReady = false;

    broadcast({
      kind: "host_status",
      connected: false,
      text: String(error),
    });

    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return;

  const index = Math.min(
    reconnectAttempt,
    NATIVE_RECONNECT_DELAYS_MS.length - 1,
  );

  const delay = NATIVE_RECONNECT_DELAYS_MS[index];

  reconnectAttempt = Math.min(
    reconnectAttempt + 1,
    NATIVE_RECONNECT_DELAYS_MS.length - 1,
  );

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectNative();
  }, delay);
}

function sendNative(message) {
  connectNative();

  if (!nativePort) {
    throw new Error("Native host is not connected");
  }

  nativePort.postMessage(message);
}

function providerForUrl(url = "") {
  try { return utils?.detectProvider(new URL(url).hostname) || null; } catch { return null; }
}

async function selectedProviderConfig() {
  const stored = await chrome.storage.local.get(["providerMode", "providerId"]);
  return { mode: stored.providerMode || "manual", id: stored.providerId || "chatgpt" };
}

async function pinLlmTab(tabId) {
  if (tabId == null) return;
  lastLlmTabId = tabId;
  try { await chrome.storage.session.set({ [PINNED_TAB_STORAGE_KEY]: tabId }); } catch {}
}

async function getPinnedLlmTabId() {
  if (lastLlmTabId != null) return lastLlmTabId;
  try {
    const stored = await chrome.storage.session.get(PINNED_TAB_STORAGE_KEY);
    const value = stored?.[PINNED_TAB_STORAGE_KEY];
    if (Number.isInteger(value)) { lastLlmTabId = value; return value; }
  } catch {}
  return null;
}

async function findActiveLlmTab() {
  const selection = await selectedProviderConfig();
  const wanted =
    selection.mode === "auto"
      ? null
      : utils.getProvider(selection.id);

  const tabs = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });

  const tab = tabs[0] || null;

  if (!tab?.id) {
    throw new Error(
      "No active browser tab is available.",
    );
  }

  const provider = providerForUrl(tab.url || "");

  if (!provider) {
    throw new Error(
      "The active tab is not a supported LLM. Activate the intended LLM tab first.",
    );
  }

  if (wanted && provider.id !== wanted.id) {
    throw new Error(
      `The active tab is ${provider.name}, but Mission Control is configured for ${wanted.name}. Activate the intended ${wanted.name} tab or change the provider selection.`,
    );
  }

  await pinLlmTab(tab.id);

  return {
    tab,
    provider,
  };
}

async function findLlmTab(preferredTabId = null) {
  const selection = await selectedProviderConfig();
  const wanted = selection.mode === "auto" ? null : utils.getProvider(selection.id);
  const acceptable = (tab) => {
    const p = providerForUrl(tab?.url || "");
    return Boolean(p && (!wanted || p.id === wanted.id));
  };

  for (const tabId of [preferredTabId, await getPinnedLlmTabId()]) {
    if (tabId == null) continue;
    try {
      const tab = await chrome.tabs.get(tabId);
      if (acceptable(tab)) { await pinLlmTab(tab.id); return { tab, provider: providerForUrl(tab.url) }; }
    } catch {}
  }

  const activeTabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const active = activeTabs.find(acceptable);
  if (active?.id != null) { await pinLlmTab(active.id); return { tab: active, provider: providerForUrl(active.url) }; }

  const patterns = wanted ? wanted.origins : utils.allOrigins();
  const tabs = await chrome.tabs.query({ url: patterns });
  const tab = tabs.find((item) => item.active && acceptable(item)) || tabs.find(acceptable);
  if (!tab?.id) return null;
  await pinLlmTab(tab.id);
  return { tab, provider: providerForUrl(tab.url) };
}

function receiverMissing(error) {
  const message = String(error?.message || error || "");
  return message.includes("Receiving end does not exist") || message.includes("Could not establish connection") || message.includes("The message port closed");
}

async function ensureProviderPermission(provider) {
  if (!provider) throw new Error("No supported LLM provider detected for this tab");
  const allowed = await chrome.permissions.contains({ origins: provider.origins });
  if (!allowed) throw new Error(`Site access for ${provider.name} has not been granted. Use the AI Engine card to grant access first.`);
}

async function ensureContentScript(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const provider = providerForUrl(tab?.url || "");
  await ensureProviderPermission(provider);
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: "BRIDGE_PING" });
    if (pong?.ok && pong.provider === provider.id) return pong;
  } catch (error) { if (!receiverMissing(error)) throw error; }

  await chrome.scripting.executeScript({ target: { tabId }, files: ["providers.js", "content.js"] });
  await new Promise((resolve) => setTimeout(resolve, 180));
  return chrome.tabs.sendMessage(tabId, { type: "BRIDGE_PING" });
}

async function sendToContent(tabId, message) {
  try { return await chrome.tabs.sendMessage(tabId, message); }
  catch (error) {
    if (!receiverMissing(error)) throw error;
    await ensureContentScript(tabId);
    return chrome.tabs.sendMessage(tabId, message);
  }
}

async function sendTextToLlm(text, submit = true, preferredTabId = null) {
  const found = await findLlmTab(preferredTabId || lastLlmTabId);
  if (!found?.tab?.id) throw new Error("No matching supported LLM tab found. Open the selected provider first.");
  await pinLlmTab(found.tab.id);
  await ensureContentScript(found.tab.id);
  const result = await sendToContent(found.tab.id, { type: "SEND_TO_LLM", payload: { text, submit } });
  if (!result?.ok) throw new Error(result?.error || `${found.provider.name} content script rejected the prompt`);
  if (submit && result?.submitted !== true) throw new Error(`${found.provider.name} prompt was not confirmed as submitted`);
  return { ...result, provider: found.provider.id, providerName: found.provider.name, tabId: found.tab.id };
}

function clearResponseWatchdog() { if (responseWatchdog) clearTimeout(responseWatchdog); responseWatchdog = null; }
function startResponseWatchdog(providerName = "LLM") {
  clearResponseWatchdog();
  responseWatchdog = setTimeout(() => {
    responseWatchdog = null;
    try { sendNative({ type: "chat_response_timeout", text: `No completed ${providerName} response has been detected. If it is still generating, keep waiting; otherwise refresh the provider tab.` }); } catch {}
  }, 120000);
}

async function waitForDownload(downloadId, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const items = await chrome.downloads.search({ id: downloadId });
    const item = items?.[0];
    if (item?.state === "complete") return item;
    if (item?.state === "interrupted") throw new Error(`Download interrupted: ${item.error || "unknown"}`);
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error(`Download timed out: ${downloadId}`);
}

function captureNextProviderDownload(provider, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { chrome.downloads.onCreated.removeListener(listener); reject(new Error("No browser download was created after clicking the attachment")); }, timeoutMs);
    function listener(item) {
      const ref = String(item.referrer || ""); const url = String(item.url || "");
      const matches = provider.domains.some((d) => ref.includes(d) || url.includes(d));
      if (!matches) return;
      clearTimeout(timeout); chrome.downloads.onCreated.removeListener(listener); resolve(item.id);
    }
    chrome.downloads.onCreated.addListener(listener);
  });
}

async function downloadOneCandidate(candidate, tabId, provider) {
  const href = String(candidate?.href || "");
  let downloadId = null;
  if (/^https?:\/\//i.test(href)) downloadId = await chrome.downloads.download({ url: href, saveAs: false, conflictAction: "uniquify" });
  else {
    const capture = captureNextProviderDownload(provider);
    const clickResult = await sendToContent(tabId, { type: "CLICK_DOWNLOAD_LINK", payload: candidate });
    if (!clickResult?.ok) throw new Error(clickResult?.error || "Could not click attachment link");
    downloadId = await capture;
  }
  const item = await waitForDownload(downloadId);
  return { id: item.id, filename: item.filename, url: item.url, finalUrl: item.finalUrl || item.url, mime: item.mime || "", fileSize: item.fileSize, danger: item.danger, label: candidate?.label || "download" };
}

async function handleDownloadRequest(message) {
  const found = await findLlmTab(message.tab_id || lastLlmTabId);
  if (!found?.tab?.id) throw new Error("No provider tab found for attachment download");
  const results = [];
  for (const candidate of Array.isArray(message.candidates) ? message.candidates : []) results.push(await downloadOneCandidate(candidate, found.tab.id, found.provider));
  return results;
}

function diagnosticCheck(id, label, status, detail, remediation = "") {
  return { id, label, status, detail, remediation };
}

function diagnosticsOverall(checks) {
  const statuses = new Set(checks.map((item) => item.status));
  if (statuses.has("fail")) return "fail";
  if (statuses.has("warn")) return "warn";
  return "pass";
}

function diagnosticRequestId() {
  return `diag-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function requestNativeDiagnostics() {
  const requestId = diagnosticRequestId();

  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingDiagnostics.delete(requestId);
      reject(new Error("Native host diagnostics timed out"));
    }, DIAGNOSTICS_TIMEOUT_MS);

    pendingDiagnostics.set(requestId, {
      resolve(value) {
        clearTimeout(timeout);
        resolve(value);
      },
      reject(error) {
        clearTimeout(timeout);
        reject(error);
      },
    });

    try {
      sendNative({
        type: "diagnostics",
        request_id: requestId,
      });
    } catch (error) {
      clearTimeout(timeout);
      pendingDiagnostics.delete(requestId);
      reject(error);
    }
  });
}

async function diagnosticProviderSelection() {
  const selection = await selectedProviderConfig();

  if (selection.mode !== "auto") {
    return {
      selection,
      provider: utils.getProvider(selection.id),
      activeTab: null,
    };
  }

  const tabs = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });

  const activeTab = tabs[0] || null;
  const provider = providerForUrl(activeTab?.url || "");

  return { selection, provider, activeTab };
}

async function findDiagnosticProviderTab(
  provider,
  preferredTab = null,
) {
  if (!provider) return null;

  if (
    preferredTab?.id != null &&
    preferredTab.active === true &&
    providerForUrl(preferredTab.url || "")?.id === provider.id
  ) {
    return preferredTab;
  }

  const tabs = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });

  const tab = tabs[0] || null;

  if (
    !tab?.id ||
    providerForUrl(tab.url || "")?.id !== provider.id
  ) {
    return null;
  }

  return tab;
}

async function collectBrowserDiagnostics() {
  const checks = [];
  const manifest = chrome.runtime.getManifest();
  const extensionVersion = String(manifest.version || "unknown");

  checks.push(
    diagnosticCheck(
      "extension",
      "Browser extension",
      "pass",
      `AI Workflow Bridge ${extensionVersion} is running.`,
    ),
  );

  let providerInfo;

  try {
    providerInfo = await diagnosticProviderSelection();
  } catch (error) {
    checks.push(
      diagnosticCheck(
        "provider_config",
        "Provider configuration",
        "fail",
        `Could not inspect provider configuration: ${String(
          error?.message || error,
        )}`,
        "Reload the extension and retry diagnostics.",
      ),
    );

    return {
      schema_version: 1,
      extension_version: extensionVersion,
      checks,
      overall: diagnosticsOverall(checks),
    };
  }

  const { selection, provider, activeTab } = providerInfo;

  if (!provider) {
    checks.push(
      diagnosticCheck(
        "provider_config",
        "Provider configuration",
        "warn",
        selection.mode === "auto"
          ? "Auto-detect is enabled, but the active tab is not a supported LLM."
          : `Configured provider "${selection.id}" is not registered.`,
        selection.mode === "auto"
          ? "Open a supported LLM tab and run diagnostics again."
          : "Choose a supported provider in Mission Control.",
      ),
    );

    return {
      schema_version: 1,
      extension_version: extensionVersion,
      checks,
      overall: diagnosticsOverall(checks),
    };
  }

  checks.push(
    diagnosticCheck(
      "provider_config",
      "Provider configuration",
      "pass",
      selection.mode === "auto"
        ? `Auto-detected ${provider.name}.`
        : `${provider.name} is selected.`,
    ),
  );

  let permissionGranted = false;

  try {
    permissionGranted = await chrome.permissions.contains({
      origins: provider.origins,
    });
  } catch (error) {
    checks.push(
      diagnosticCheck(
        "provider_permission",
        "Provider site access",
        "fail",
        `Could not inspect ${provider.name} site access: ${String(
          error?.message || error,
        )}`,
        "Reload the extension and retry diagnostics.",
      ),
    );
  }

  if (!checks.some((item) => item.id === "provider_permission")) {
    checks.push(
      diagnosticCheck(
        "provider_permission",
        "Provider site access",
        permissionGranted ? "pass" : "warn",
        permissionGranted
          ? `${provider.name} site access is granted.`
          : `${provider.name} site access has not been granted.`,
        permissionGranted
          ? ""
          : `Use GRANT SITE ACCESS for ${provider.name}.`,
      ),
    );
  }

  let tab = null;

  try {
    tab = await findDiagnosticProviderTab(provider, activeTab);
  } catch (error) {
    checks.push(
      diagnosticCheck(
        "provider_tab",
        "Provider tab",
        "warn",
        `Could not inspect ${provider.name} tabs: ${String(
          error?.message || error,
        )}`,
        `Open ${provider.name} in a browser tab and retry diagnostics.`,
      ),
    );
  }

  if (!checks.some((item) => item.id === "provider_tab")) {
    checks.push(
      diagnosticCheck(
        "provider_tab",
        "Provider tab",
        tab ? "pass" : "warn",
        tab
          ? `A ${provider.name} tab is available.`
          : `No matching ${provider.name} tab is open.`,
        tab
          ? ""
          : `Open ${provider.name} and retry diagnostics.`,
      ),
    );
  }

  if (!permissionGranted || !tab?.id) {
    checks.push(
      diagnosticCheck(
        "content_script",
        "Content script",
        "warn",
        !permissionGranted
          ? "Content-script health cannot be checked without provider site access."
          : "Content-script health cannot be checked without a provider tab.",
        !permissionGranted
          ? `Grant ${provider.name} site access first.`
          : `Open ${provider.name} and retry diagnostics.`,
      ),
    );

    return {
      schema_version: 1,
      extension_version: extensionVersion,
      provider: provider.id,
      provider_name: provider.name,
      checks,
      overall: diagnosticsOverall(checks),
    };
  }

  try {
    const pong = await chrome.tabs.sendMessage(tab.id, {
      type: "BRIDGE_PING",
    });

    if (!pong?.ok) {
      checks.push(
        diagnosticCheck(
          "content_script",
          "Content script",
          "warn",
          `${provider.name} did not return a valid Bridge ping response.`,
          "Reload the provider tab or start a normal Bridge workflow once.",
        ),
      );
    } else if (pong.provider !== provider.id) {
      checks.push(
        diagnosticCheck(
          "content_script",
          "Content script",
          "fail",
          `Content script reported ${pong.provider || "unknown"} instead of ${provider.id}.`,
          "Reload the provider tab and retry diagnostics.",
        ),
      );
    } else {
      checks.push(
        diagnosticCheck(
          "content_script",
          "Content script",
          "pass",
          `${provider.name} content script responded successfully.`,
        ),
      );

      checks.push(
        diagnosticCheck(
          "content_version",
          "Content version",
          pong.version === extensionVersion ? "pass" : "warn",
          pong.version === extensionVersion
            ? `Content script version matches extension ${extensionVersion}.`
            : `Content script ${pong.version || "unknown"} does not match extension ${extensionVersion}.`,
          pong.version === extensionVersion
            ? ""
            : "Reload the provider tab so the current content script can be loaded.",
        ),
      );

      checks.push(
        diagnosticCheck(
          "composer",
          "Provider composer",
          pong.composerFound ? "pass" : "warn",
          pong.composerFound
            ? `${provider.name} composer was detected.`
            : `${provider.name} composer was not detected on the current page.`,
          pong.composerFound
            ? ""
            : "Open a normal chat/conversation page and retry diagnostics.",
        ),
      );
    }
  } catch (error) {
    const missing = receiverMissing(error);

    checks.push(
      diagnosticCheck(
        "content_script",
        "Content script",
        "warn",
        missing
          ? `AI Workflow Bridge content script is not active in the ${provider.name} tab.`
          : `Content-script ping failed: ${String(error?.message || error)}`,
        missing
          ? "Reload the provider tab or start a normal Bridge action once. Diagnostics will not inject scripts automatically."
          : "Reload the provider tab and retry diagnostics.",
      ),
    );
  }

  return {
    schema_version: 1,
    extension_version: extensionVersion,
    provider: provider.id,
    provider_name: provider.name,
    checks,
    overall: diagnosticsOverall(checks),
  };
}

async function runDiagnostics() {
  const browser = await collectBrowserDiagnostics();

  let native;

  try {
    native = await requestNativeDiagnostics();
  } catch (error) {
    native = {
      schema_version: 1,
      overall: "fail",
      checks: [
        diagnosticCheck(
          "native_host",
          "Native host",
          "fail",
          `Native host diagnostics failed: ${String(error?.message || error)}`,
          "Verify Native Messaging installation and reload the extension.",
        ),
      ],
    };
  }

  const nativeChecks = Array.isArray(native?.checks)
    ? native.checks
    : [];

  const browserChecks = Array.isArray(browser?.checks)
    ? browser.checks
    : [];

  const checks = [...nativeChecks, ...browserChecks];

  return {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    overall: diagnosticsOverall(checks),
    native,
    browser,
    checks,
  };
}

async function handleNativeMessage(message) {
  markNativeReady(message);

  if (message?.kind === "diagnostics_result") {
    const requestId = String(message.request_id || "");
    const pending = pendingDiagnostics.get(requestId);

    if (pending) {
      pendingDiagnostics.delete(requestId);
      pending.resolve(message.diagnostics || {});
    }
  }

  broadcast(message);
  if (message?.kind === "send_to_chatgpt" || message?.kind === "send_to_llm") {
    try {
      const result = await sendTextToLlm(message.text, true, message.tab_id || null);
      sendNative({ type: "chat_send_ack", request_id: message.request_id || null, ok: true, submitted: result.submitted === true, content_version: result.version || null, provider: result.provider });
      startResponseWatchdog(result.providerName);
    } catch (error) {
      clearResponseWatchdog();
      sendNative({ type: "chat_send_ack", request_id: message.request_id || null, ok: false, submitted: false, error: String(error?.message || error) });
    }
  } else if (message?.kind === "download_request") {
    try { sendNative({ type: "download_result", request_id: message.request_id, ok: true, files: await handleDownloadRequest(message) }); }
    catch (error) { sendNative({ type: "download_result", request_id: message.request_id, ok: false, error: String(error?.message || error), files: [] }); }
  }
}

async function getDownloadCandidates(tabId, responseKey) {
  try { return await sendToContent(tabId, { type: "GET_RESPONSE_DOWNLOADS", payload: { responseKey } }); }
  catch { return { links: [] }; }
}

chrome.runtime.onInstalled.addListener(() => { chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {}); connectNative(); });
chrome.runtime.onStartup.addListener(connectNative);
connectNative();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "LLM_RESPONSE_DONE" || message?.type === "CHATGPT_RESPONSE_DONE") {
    const tabId = sender.tab?.id;

    (async () => {
      const boundTabId = await getPinnedLlmTabId();

      if (
        boundTabId != null &&
        tabId != null &&
        tabId !== boundTabId
      ) {
        sendResponse({
          ok: true,
          ignored: true,
          reason: "Response came from a non-bound LLM tab",
        });
        return;
      }

      clearResponseWatchdog();

      if (tabId != null) {
        await pinLlmTab(tabId);
      }
      const downloads = tabId != null ? await getDownloadCandidates(tabId, message.payload?.responseKey) : { links: [] };
      sendNative({ type: "assistant_response", payload: { ...message.payload, tab_id: tabId, downloads: downloads?.links || [] } });
      sendResponse({ ok: true });
    })().catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  if (message?.type === "LLM_ACCOUNT_SAFETY_SIGNAL") {
    (async () => {
      const tabId = sender.tab?.id;
      const boundTabId = await getPinnedLlmTabId();

      if (
        boundTabId != null &&
        tabId != null &&
        tabId !== boundTabId
      ) {
        sendResponse({
          ok: true,
          ignored: true,
          reason: "Safety signal came from a non-bound LLM tab",
        });
        return;
      }

      sendNative({
        type: "provider_safety_signal",
        payload: message.payload || {},
      });

      sendResponse({ ok: true });
    })().catch((error) => {
      sendResponse({
        ok: false,
        error: String(error?.message || error),
      });
    });

    return true;
  }

  if (message?.type === "BRIDGE_COMMAND") {
    const command = message.payload || {};
    (async () => {
      if (command.action === "ping") sendNative({ type: "ping" });
      else if (command.action === "get_state") sendNative({ type: "get_state" });
      else if (command.action === "diagnostics") {
        return {
          ok: true,
          diagnostics: await runDiagnostics(),
        };
      } else if (command.action === "save_config") {
        const cfg = command.config || {};
        await chrome.storage.local.set({ providerMode: cfg.provider_mode || "manual", providerId: cfg.provider_id || "chatgpt" });
        sendNative({ type: "set_config", config: cfg });
      } else if (["plan_project", "arm", "change_course", "finish_project"].includes(command.action)) {
        const found = await findActiveLlmTab();
        if (!found?.tab?.id) throw new Error("Open a supported LLM tab that matches your AI Engine selection first.");
        await ensureContentScript(found.tab.id);
        const typeMap = { plan_project: "build_start_prompt", arm: "build_controller_prompt", change_course: "change_course", finish_project: "finish_project" };
        sendNative({ type: typeMap[command.action], tab_id: found.tab.id, provider: found.provider.id, change_request: command.change_request || "" });
      } else if (command.action === "pause") sendNative({ type: "pause" });
      else if (command.action === "resume") sendNative({ type: "resume" });
      else if (command.action === "reset_session") sendNative({ type: "reset_session" });
      else if (command.action === "approval") sendNative({ type: "approval_decision", approval_id: command.approval_id, decision: command.decision });
      else if (command.action === "send_text") {
        const found = await findActiveLlmTab();

        const value = await sendTextToLlm(
          command.text || "",
          command.submit !== false,
          found.tab.id,
        );

        return {
          ok: true,
          value,
        };
      }
      return { ok: true, nativeConnected: nativeReady, provider: (await findLlmTab(lastLlmTabId))?.provider?.id || null };
    })().then(sendResponse).catch((error) => {
      broadcast({ kind: "error", text: String(error?.message || error) });
      sendResponse({ ok: false, error: String(error?.message || error) });
    });
    return true;
  }
});
