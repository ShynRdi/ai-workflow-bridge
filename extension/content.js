(() => {
  const CONTENT_VERSION = "0.3.1";
  if (typeof window.__AI_WORKFLOW_BRIDGE_CLEANUP__ === "function") {
    try { window.__AI_WORKFLOW_BRIDGE_CLEANUP__(); } catch {}
  }
  window.__AI_WORKFLOW_BRIDGE_ACTIVE__ = CONTENT_VERSION;

  const provider = globalThis.AWB_PROVIDER_UTILS?.detectProvider(location.hostname);
  if (!provider) return;

  const CHECK_INTERVAL_MS = 500;
  const STABLE_FOR_MS = provider.id === "chatgpt" ? 4000 : 5000;
  const INCOMPLETE_PROTOCOL_GRACE_MS = provider.id === "chatgpt" ? 30000 : 35000;
  const INITIAL_GRACE_MS = 1200;
  const SUBMIT_CONFIRM_TIMEOUT_MS = 14000;
  const SEND_BUTTON_READY_TIMEOUT_MS = 7000;
  const WORKFLOW_END = "<<<END_AI_WORKFLOW>>>";
  const STOP_MARKER = "<<<AI_WORKFLOW_STOP>>>";
  const PROJECT_DONE_MARKER = "<<<AI_WORKFLOW_PROJECT_DONE>>>";
  const ROADMAP_END = "<<<END_AI_WORKFLOW_ROADMAP>>>";
  const CHANGE_END = "<<<END_AI_WORKFLOW_CHANGE_REVIEW>>>";
  let initialized = false;
  let baselineAssistantCount = 0;
  let candidate = null;
  let lastSentKey = "";
  let lastSentNode = null;
  let generationWasObserved = false;
  let expectedResponse = "freeform";
  let lastPathname = location.pathname;
  let lastCompletedNode = null;
  let lastCompletedKey = "";
  let lastSafetySignal = "";
  const startedAt = Date.now();

  const genericComposer = ['textarea', 'div[contenteditable="true"]'];
  const genericAssistant = ['[data-message-author-role="assistant"]', '[data-testid*="assistant"]', '[data-role="assistant"]', '[data-message-role="assistant"]'];
  const genericUser = ['[data-message-author-role="user"]', '[data-testid*="user-message"]', '[data-role="user"]', '[data-message-role="user"]'];
  const genericStop = ['button[aria-label*="Stop"]', 'button[data-testid*="stop"]', '[data-testid="stop-button"]'];
  const genericSend = ['button[aria-label*="Send"]', 'button[data-testid*="send"]', 'button[type="submit"]'];

  function queryAll(selectors) {
    const out = [];
    const seen = new Set();
    for (const selector of selectors || []) {
      try {
        document.querySelectorAll(selector).forEach((node) => {
          if (!seen.has(node)) { seen.add(node); out.push(node); }
        });
      } catch {}
    }
    return out;
  }

  function topLevelNodes(nodes) { return nodes.filter((node, idx) => !nodes.some((other, j) => j !== idx && other.contains(node))); }
  function getTurnsByRole(role) {
    const selectors = role === "assistant" ? [...(provider.assistant || []), ...genericAssistant] : [...(provider.user || []), ...genericUser];
    const direct = topLevelNodes(queryAll(selectors));
    if (direct.length) return direct;
    if (provider.id === "chatgpt") return Array.from(document.querySelectorAll('article[data-testid^="conversation-turn-"]')).filter((node) => node.querySelector(`[data-message-author-role="${role}"]`));
    return [];
  }
  function getAssistantTurns() { return getTurnsByRole("assistant"); }
  function getUserTurns() { return getTurnsByRole("user"); }
  function visible(node) {
    return Boolean(node && (node.getClientRects().length > 0 || getComputedStyle(node).position === "fixed"));
  }
  function isGenerating() {
    const stopVisible = queryAll([...(provider.stop || []), ...genericStop]).some((node) => {
      const disabled = Boolean(node.disabled) || node.getAttribute("aria-disabled") === "true";
      return visible(node) && !disabled;
    });
    if (stopVisible) return true;
    if (provider.id === "chatgpt") {
      const busy = document.querySelector('[aria-busy="true"], [data-is-streaming="true"], [data-testid*="streaming"]');
      if (busy && visible(busy)) return true;
    }
    return false;
  }
  function extractText(node) {
    if (!node) return "";
    const clone = node.cloneNode(true);
    clone.querySelectorAll('button, svg, textarea, input, nav').forEach((el) => el.remove());
    return (clone.innerText || clone.textContent || "").trim();
  }
  function makeKey(count, text) {
    let hash = 2166136261;
    const raw = `${provider.id}|${location.pathname}|${count}|${text.length}|${text.slice(-320)}`;
    for (let i = 0; i < raw.length; i += 1) { hash ^= raw.charCodeAt(i); hash = Math.imul(hash, 16777619); }
    return `${provider.id}:${count}:${(hash >>> 0).toString(16)}`;
  }
  function trailing(text, marker) { return String(text || "").trimEnd().endsWith(marker); }
  function inferExpectation(prompt) {
    const text = String(prompt || "");
    if (text.includes("AI WORKFLOW BRIDGE — PROJECT START")) return "planning";
    if (text.includes("AI WORKFLOW BRIDGE — COURSE CHANGE REVIEW")) return "change_review";
    if (text.includes("AI WORKFLOW BRIDGE — FINISH PROJECT REQUEST")) return "finishing";
    if (text.includes("AI WORKFLOW BRIDGE — STRICT RESPONSE PROTOCOL") || text.includes("AI WORKFLOW BRIDGE — EXECUTION REPORT") || text.includes("AI WORKFLOW BRIDGE — PROTOCOL RECOVERY")) return "workflow";
    return "freeform";
  }
  function protocolComplete(text) {
    const value = String(text || "");
    if (!value.trim()) return false;
    if (expectedResponse === "freeform") return true;
    if (expectedResponse === "planning") return value.includes(ROADMAP_END) && trailing(value, "READY_TO_ARM");
    if (expectedResponse === "change_review") return trailing(value, CHANGE_END);
    if (expectedResponse === "finishing") return trailing(value, WORKFLOW_END) || trailing(value, STOP_MARKER) || trailing(value, PROJECT_DONE_MARKER);
    return trailing(value, WORKFLOW_END) || trailing(value, STOP_MARKER) || trailing(value, PROJECT_DONE_MARKER);
  }
  function protocolDiagnostics(text) {
    const value = String(text || "");
    return { expectation: expectedResponse, textLength: value.length, workflowStart: value.includes("<<<AI_WORKFLOW>>>"), workflowEnd: trailing(value, WORKFLOW_END), stopMarker: trailing(value, STOP_MARKER), projectDoneMarker: trailing(value, PROJECT_DONE_MARKER), roadmapEnd: value.includes(ROADMAP_END), readyToArm: trailing(value, "READY_TO_ARM"), changeReviewEnd: trailing(value, CHANGE_END), protocolComplete: protocolComplete(value) };
  }
  function resetForNavigation() { const turns = getAssistantTurns(); baselineAssistantCount = turns.length; candidate = null; generationWasObserved = false; lastSentKey = ""; lastSentNode = null; lastCompletedNode = null; lastCompletedKey = ""; }
  function findFirst(selectors) { for (const selector of selectors || []) { try { const node = document.querySelector(selector); if (node) return node; } catch {} } return null; }
  function findComposer() { return findFirst([...(provider.composer || []), ...genericComposer]); }
  function composerText(composer = findComposer()) { if (!composer) return ""; if (composer instanceof HTMLTextAreaElement || composer instanceof HTMLInputElement) return composer.value || ""; return composer.innerText || composer.textContent || ""; }
  function setComposerText(text) {
    const composer = findComposer(); if (!composer) throw new Error(`${provider.name} composer not found`); composer.focus();
    if (composer instanceof HTMLTextAreaElement || composer instanceof HTMLInputElement) {
      const proto = composer instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set; if (setter) setter.call(composer, text); else composer.value = text;
      composer.dispatchEvent(new Event("input", { bubbles: true })); composer.dispatchEvent(new Event("change", { bubbles: true })); return composer;
    }
    try {
      const selection = window.getSelection(); const range = document.createRange(); range.selectNodeContents(composer); selection?.removeAllRanges(); selection?.addRange(range);
      const inserted = document.execCommand("insertText", false, text); selection?.removeAllRanges();
      if (inserted && composerText(composer).trim()) { composer.dispatchEvent(new Event("input", { bubbles: true })); return composer; }
    } catch {}
    composer.replaceChildren(); String(text).split("\n").forEach((line) => { const p = document.createElement("p"); if (line) p.textContent = line; else p.appendChild(document.createElement("br")); composer.appendChild(p); });
    composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text })); return composer;
  }
  function sendSelectors() { return [...(provider.send || []), ...genericSend]; }
  function isUsableSendButton(button) { if (!button) return false; const ariaDisabled = String(button.getAttribute("aria-disabled") || "").toLowerCase() === "true"; const disabled = Boolean(button.disabled) || ariaDisabled; const visible = button.getClientRects().length > 0 || getComputedStyle(button).position === "fixed"; return !disabled && visible; }
  function findSendButton() { for (const selector of sendSelectors()) { const buttons = queryAll([selector]); const usable = buttons.find(isUsableSendButton); if (usable) return usable; } return null; }
  async function waitForSendButton(timeoutMs = SEND_BUTTON_READY_TIMEOUT_MS) { const deadline = Date.now() + timeoutMs; while (Date.now() < deadline) { const button = findSendButton(); if (button) return button; await new Promise((resolve) => setTimeout(resolve, 120)); } return null; }
  function sendControlSnapshot() { const details = []; const seen = new Set(); for (const selector of sendSelectors()) queryAll([selector]).forEach((button) => { if (seen.has(button)) return; seen.add(button); details.push({ selector, id: button.id || "", testid: button.getAttribute("data-testid") || "", aria: button.getAttribute("aria-label") || "", disabled: Boolean(button.disabled), ariaDisabled: button.getAttribute("aria-disabled") || "", visible: button.getClientRects().length > 0 }); }); return details.slice(0, 10); }
  function prepareForOutboundPrompt(prompt) { expectedResponse = inferExpectation(prompt); const turns = getAssistantTurns(); baselineAssistantCount = turns.length; candidate = null; generationWasObserved = false; const current = turns.at(-1); const currentText = extractText(current); if (current && currentText) { lastSentKey = makeKey(turns.length, currentText); lastSentNode = current; lastCompletedNode = current; lastCompletedKey = lastSentKey; } }
  function dispatchEnter(composer) { const init = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }; composer.dispatchEvent(new KeyboardEvent("keydown", init)); composer.dispatchEvent(new KeyboardEvent("keypress", init)); composer.dispatchEvent(new KeyboardEvent("keyup", init)); }
  async function submitComposer() {
    const composer = findComposer(); if (!composer) throw new Error(`${provider.name} composer not found`); const beforeUserCount = getUserTurns().length; const beforeText = composerText(composer).trim(); if (!beforeText) throw new Error(`${provider.name} composer is empty after prompt insertion`);
    const sendButton = await waitForSendButton(); if (sendButton) sendButton.click(); else { const form = composer.closest("form"); if (form && typeof form.requestSubmit === "function") { try { form.requestSubmit(); } catch { dispatchEnter(composer); } } else dispatchEnter(composer); }
    const deadline = Date.now() + SUBMIT_CONFIRM_TIMEOUT_MS; while (Date.now() < deadline) { await new Promise((resolve) => setTimeout(resolve, 140)); const userAdvanced = getUserTurns().length > beforeUserCount; const composerCleared = composerText(findComposer()).trim() === ""; if (userAdvanced || isGenerating() || composerCleared) return true; }
    throw new Error(`Prompt remained unsubmitted on ${provider.name}; composer_chars=${composerText(findComposer()).trim().length}; controls=${JSON.stringify(sendControlSnapshot())}`);
  }
  async function notifyDone(node, text, key, completionReason) { if (!text || (key === lastSentKey && node === lastSentNode)) return; lastCompletedNode = node; lastCompletedKey = key; try { const response = await chrome.runtime.sendMessage({ type: "LLM_RESPONSE_DONE", payload: { provider: provider.id, providerName: provider.name, title: document.title || provider.name, text, url: location.href, responseKey: key, observedAt: new Date().toISOString(), completionReason, protocolDiagnostics: protocolDiagnostics(text) } }); if (response?.ok) { lastSentKey = key; lastSentNode = node; } } catch (error) { console.warn("[AI Workflow Bridge] response forwarding failed", error); } }
  function collectLinks(node) { if (!node) return []; const links = []; const seen = new Set(); node.querySelectorAll('a[href]').forEach((anchor) => { const raw = anchor.getAttribute("href") || ""; const absolute = anchor.href || raw; const label = (anchor.innerText || anchor.textContent || anchor.getAttribute("download") || "download").trim(); const looksDownloadable = anchor.hasAttribute("download") || /download|sandbox|\.zip(?:$|\?)|\.patch(?:$|\?)|\.diff(?:$|\?)|\.txt(?:$|\?)/i.test(`${raw} ${absolute} ${label}`); if (!looksDownloadable || !absolute || seen.has(absolute)) return; seen.add(absolute); links.push({ href: absolute, rawHref: raw, label }); }); return links; }
  function safetySignal() { const nodes = queryAll(['[role="alert"]', '[role="dialog"]', '[aria-live="assertive"]', '[data-testid*="toast"]', '[class*="toast"]']); const text = nodes.map((n) => (n.innerText || n.textContent || "").trim()).filter(Boolean).join("\n").slice(0, 12000); if (!text) return null; const patterns = [["rate_limit", /rate limit|too many requests|usage limit|message limit|reached (?:your|the) limit|try again later|come back later/i], ["auth_challenge", /session expired|verify you are human|unusual activity|suspicious activity|captcha|account temporarily|security check/i]]; for (const [kind, rx] of patterns) if (rx.test(text)) return { kind, text: text.slice(0, 700) }; return null; }
  function inspectSafety() { const signal = safetySignal(); if (!signal) return; const key = `${signal.kind}:${signal.text}`; if (key === lastSafetySignal) return; lastSafetySignal = key; chrome.runtime.sendMessage({ type: "LLM_ACCOUNT_SAFETY_SIGNAL", payload: { provider: provider.id, providerName: provider.name, ...signal, url: location.href } }).catch(() => {}); }
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "BRIDGE_PING") { sendResponse({ ok: true, href: location.href, version: CONTENT_VERSION, provider: provider.id, providerName: provider.name, providerStatus: provider.status || "unknown", assistantCount: getAssistantTurns().length, userCount: getUserTurns().length, composerFound: Boolean(findComposer()), generating: isGenerating(), expectedResponse }); return true; }
    if (message?.type === "SEND_TO_LLM" || message?.type === "SEND_TO_CHATGPT") { (async () => { try { const outbound = String(message.payload?.text || ""); prepareForOutboundPrompt(outbound); setComposerText(outbound); if (message.payload?.submit === false) return sendResponse({ ok: true, submitted: false, version: CONTENT_VERSION, provider: provider.id }); const submitted = await submitComposer(); sendResponse({ ok: true, submitted: Boolean(submitted), version: CONTENT_VERSION, provider: provider.id, expectedResponse }); } catch (error) { sendResponse({ ok: false, submitted: false, error: String(error?.message || error), version: CONTENT_VERSION, provider: provider.id }); } })(); return true; }
    if (message?.type === "GET_RESPONSE_DOWNLOADS") { const requestedKey = message.payload?.responseKey || ""; const node = requestedKey && requestedKey === lastCompletedKey ? lastCompletedNode : getAssistantTurns().at(-1); sendResponse({ links: collectLinks(node), provider: provider.id }); return true; }
    if (message?.type === "CLICK_DOWNLOAD_LINK") { try { const candidate = message.payload || {}; const node = lastCompletedNode || getAssistantTurns().at(-1); if (!node) throw new Error("No completed assistant response is available"); const target = Array.from(node.querySelectorAll('a[href]')).find((anchor) => { const raw = anchor.getAttribute("href") || ""; const absolute = anchor.href || raw; const label = (anchor.innerText || anchor.textContent || anchor.getAttribute("download") || "download").trim(); return absolute === candidate.href || raw === candidate.rawHref || (candidate.label && label === candidate.label); }); if (!target) throw new Error("Attachment link is no longer present in the response"); target.click(); sendResponse({ ok: true }); } catch (error) { sendResponse({ ok: false, error: String(error?.message || error) }); } return true; }
  });
  function tick() {
    inspectSafety();
    if (location.pathname !== lastPathname) { lastPathname = location.pathname; resetForNavigation(); return; }
    const turns = getAssistantTurns(); const count = turns.length; const generating = isGenerating();
    if (!initialized) { baselineAssistantCount = count; initialized = true; return; }
    if (generating) generationWasObserved = true;
    const lastTurn = turns[count - 1]; const text = extractText(lastTurn); const hasNewAssistantTurn = count > baselineAssistantCount;
    const samePreviouslySentNodeChanged = Boolean(lastTurn && lastTurn === lastSentNode && text && makeKey(count, text) !== lastSentKey);
    if (!hasNewAssistantTurn && !generationWasObserved && !samePreviouslySentNodeChanged) return;
    if (!text) return;
    const key = makeKey(count, text); const now = Date.now();
    if (!candidate || candidate.node !== lastTurn || candidate.key !== key) { candidate = { key, text, firstSeenAt: now, changedAt: now, node: lastTurn }; return; }
    if (candidate.text !== text) { candidate.changedAt = now; candidate.key = key; }
    candidate.text = text; candidate.node = lastTurn;
    if (generating) return;
    if (now - candidate.changedAt < STABLE_FOR_MS || now - startedAt < INITIAL_GRACE_MS) return;
    const complete = protocolComplete(text);
    if (!complete && expectedResponse !== "freeform" && now - candidate.firstSeenAt < INCOMPLETE_PROTOCOL_GRACE_MS) return;
    const reason = complete ? "protocol_complete" : (expectedResponse === "freeform" ? "stable_freeform" : "incomplete_protocol_grace_expired");
    notifyDone(lastTurn, text, key, reason);
    if (complete || expectedResponse === "freeform") baselineAssistantCount = Math.max(baselineAssistantCount, count);
    generationWasObserved = false;
  }
  const observer = new MutationObserver(tick); observer.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["aria-label", "aria-busy", "data-testid", "data-is-streaming", "disabled", "href"] }); const intervalId = setInterval(tick, CHECK_INTERVAL_MS); window.__AI_WORKFLOW_BRIDGE_CLEANUP__ = () => { try { observer.disconnect(); } catch {} clearInterval(intervalId); try { delete window.__AI_WORKFLOW_BRIDGE_CLEANUP__; } catch {} }; tick();
})();
