(() => {
  const CONTENT_VERSION = "0.2.4";
  if (typeof window.__AI_WORKFLOW_BRIDGE_CLEANUP__ === "function") {
    try { window.__AI_WORKFLOW_BRIDGE_CLEANUP__(); } catch {}
  }
  window.__AI_WORKFLOW_BRIDGE_ACTIVE__ = CONTENT_VERSION;

  const provider = globalThis.AWB_PROVIDER_UTILS?.detectProvider(location.hostname);
  if (!provider) return;

  const CHECK_INTERVAL_MS = 700;
  const STABLE_FOR_MS = provider.id === "chatgpt" ? 1800 : 2600;
  const INITIAL_GRACE_MS = 1200;
  const SUBMIT_CONFIRM_TIMEOUT_MS = 14000;
  const SEND_BUTTON_READY_TIMEOUT_MS = 7000;
  let initialized = false;
  let baselineAssistantCount = 0;
  let candidate = null;
  let lastSentKey = "";
  let generationWasObserved = false;
  let lastPathname = location.pathname;
  let lastCompletedNode = null;
  let lastCompletedKey = "";
  let lastSafetySignal = "";
  const startedAt = Date.now();

  const genericComposer = ['textarea', 'div[contenteditable="true"]'];
  const genericAssistant = ['[data-message-author-role="assistant"]', '[data-testid*="assistant"]', '[data-role="assistant"]', '[data-message-role="assistant"]'];
  const genericUser = ['[data-message-author-role="user"]', '[data-testid*="user-message"]', '[data-role="user"]', '[data-message-role="user"]'];
  const genericStop = ['button[aria-label*="Stop"]', 'button[data-testid*="stop"]'];
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
  function isGenerating() {
    return queryAll([...(provider.stop || []), ...genericStop]).some((node) => {
      const visible = node.getClientRects().length > 0;
      const disabled = Boolean(node.disabled) || node.getAttribute("aria-disabled") === "true";
      return visible && !disabled;
    });
  }
  function extractText(node) {
    if (!node) return "";
    const clone = node.cloneNode(true);
    clone.querySelectorAll('button, svg, textarea, input, nav').forEach((el) => el.remove());
    return (clone.innerText || clone.textContent || "").trim();
  }
  function makeKey(count, text) {
    let hash = 2166136261;
    const raw = `${provider.id}|${location.pathname}|${count}|${text.length}|${text.slice(-240)}`;
    for (let i = 0; i < raw.length; i += 1) { hash ^= raw.charCodeAt(i); hash = Math.imul(hash, 16777619); }
    return `${provider.id}:${count}:${(hash >>> 0).toString(16)}`;
  }
  function resetForNavigation() { const turns = getAssistantTurns(); baselineAssistantCount = turns.length; candidate = null; generationWasObserved = false; lastSentKey = ""; lastCompletedNode = null; lastCompletedKey = ""; }
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
  function prepareForOutboundPrompt() { const turns = getAssistantTurns(); baselineAssistantCount = turns.length; candidate = null; generationWasObserved = false; const current = turns.at(-1); const currentText = extractText(current); if (current && currentText) { lastSentKey = makeKey(turns.length, currentText); lastCompletedNode = current; lastCompletedKey = lastSentKey; } }
  function dispatchEnter(composer) { const init = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }; composer.dispatchEvent(new KeyboardEvent("keydown", init)); composer.dispatchEvent(new KeyboardEvent("keypress", init)); composer.dispatchEvent(new KeyboardEvent("keyup", init)); }
  async function submitComposer() {
    const composer = findComposer(); if (!composer) throw new Error(`${provider.name} composer not found`); const beforeUserCount = getUserTurns().length; const beforeText = composerText(composer).trim(); if (!beforeText) throw new Error(`${provider.name} composer is empty after prompt insertion`);
    const sendButton = await waitForSendButton(); if (sendButton) sendButton.click(); else { const form = composer.closest("form"); if (form && typeof form.requestSubmit === "function") { try { form.requestSubmit(); } catch { dispatchEnter(composer); } } else dispatchEnter(composer); }
    const deadline = Date.now() + SUBMIT_CONFIRM_TIMEOUT_MS; while (Date.now() < deadline) { await new Promise((resolve) => setTimeout(resolve, 140)); const userAdvanced = getUserTurns().length > beforeUserCount; const composerCleared = composerText(findComposer()).trim() === ""; if (userAdvanced || isGenerating() || composerCleared) return true; }
    throw new Error(`Prompt remained unsubmitted on ${provider.name}; composer_chars=${composerText(findComposer()).trim().length}; controls=${JSON.stringify(sendControlSnapshot())}`);
  }
  async function notifyDone(node, text, key) { if (!text || key === lastSentKey) return; lastCompletedNode = node; lastCompletedKey = key; try { const response = await chrome.runtime.sendMessage({ type: "LLM_RESPONSE_DONE", payload: { provider: provider.id, providerName: provider.name, title: document.title || provider.name, text, url: location.href, responseKey: key, observedAt: new Date().toISOString() } }); if (response?.ok) lastSentKey = key; } catch (error) { console.warn("[AI Workflow Bridge] response forwarding failed", error); } }
  function collectLinks(node) { if (!node) return []; const links = []; const seen = new Set(); node.querySelectorAll('a[href]').forEach((anchor) => { const raw = anchor.getAttribute("href") || ""; const absolute = anchor.href || raw; const label = (anchor.innerText || anchor.textContent || anchor.getAttribute("download") || "download").trim(); const looksDownloadable = anchor.hasAttribute("download") || /download|sandbox|\.zip(?:$|\?)|\.patch(?:$|\?)|\.diff(?:$|\?)|\.txt(?:$|\?)/i.test(`${raw} ${absolute} ${label}`); if (!looksDownloadable || !absolute || seen.has(absolute)) return; seen.add(absolute); links.push({ href: absolute, rawHref: raw, label }); }); return links; }
  function safetySignal() { const nodes = queryAll(['[role="alert"]', '[role="dialog"]', '[aria-live="assertive"]', '[data-testid*="toast"]', '[class*="toast"]']); const text = nodes.map((n) => (n.innerText || n.textContent || "").trim()).filter(Boolean).join("\n").slice(0, 12000); if (!text) return null; const patterns = [["rate_limit", /rate limit|too many requests|usage limit|message limit|reached (?:your|the) limit|try again later|come back later/i], ["auth_challenge", /session expired|verify you are human|unusual activity|suspicious activity|captcha|account temporarily|security check/i]]; for (const [kind, rx] of patterns) if (rx.test(text)) return { kind, text: text.slice(0, 700) }; return null; }
  function inspectSafety() { const signal = safetySignal(); if (!signal) return; const key = `${signal.kind}:${signal.text}`; if (key === lastSafetySignal) return; lastSafetySignal = key; chrome.runtime.sendMessage({ type: "LLM_ACCOUNT_SAFETY_SIGNAL", payload: { provider: provider.id, providerName: provider.name, ...signal, url: location.href } }).catch(() => {}); }
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "BRIDGE_PING") { sendResponse({ ok: true, href: location.href, version: CONTENT_VERSION, provider: provider.id, providerName: provider.name, providerStatus: provider.status || "unknown", assistantCount: getAssistantTurns().length, userCount: getUserTurns().length, composerFound: Boolean(findComposer()), generating: isGenerating() }); return true; }
    if (message?.type === "SEND_TO_LLM" || message?.type === "SEND_TO_CHATGPT") { (async () => { try { prepareForOutboundPrompt(); setComposerText(String(message.payload?.text || "")); if (message.payload?.submit === false) return sendResponse({ ok: true, submitted: false, version: CONTENT_VERSION, provider: provider.id }); const submitted = await submitComposer(); sendResponse({ ok: true, submitted: Boolean(submitted), version: CONTENT_VERSION, provider: provider.id }); } catch (error) { sendResponse({ ok: false, submitted: false, error: String(error?.message || error), version: CONTENT_VERSION, provider: provider.id }); } })(); return true; }
    if (message?.type === "GET_RESPONSE_DOWNLOADS") { const requestedKey = message.payload?.responseKey || ""; const node = requestedKey && requestedKey === lastCompletedKey ? lastCompletedNode : getAssistantTurns().at(-1); sendResponse({ links: collectLinks(node), provider: provider.id }); return true; }
    if (message?.type === "CLICK_DOWNLOAD_LINK") { try { const candidate = message.payload || {}; const node = lastCompletedNode || getAssistantTurns().at(-1); if (!node) throw new Error("No completed assistant response is available"); const target = Array.from(node.querySelectorAll('a[href]')).find((anchor) => { const raw = anchor.getAttribute("href") || ""; const absolute = anchor.href || raw; const label = (anchor.innerText || anchor.textContent || anchor.getAttribute("download") || "download").trim(); return absolute === candidate.href || raw === candidate.rawHref || (candidate.label && label === candidate.label); }); if (!target) throw new Error("Attachment link is no longer present in the response"); target.click(); sendResponse({ ok: true }); } catch (error) { sendResponse({ ok: false, error: String(error?.message || error) }); } return true; }
  });
  function tick() { inspectSafety(); if (location.pathname !== lastPathname) { lastPathname = location.pathname; resetForNavigation(); return; } const turns = getAssistantTurns(); const count = turns.length; const generating = isGenerating(); if (!initialized) { baselineAssistantCount = count; initialized = true; return; } if (generating) generationWasObserved = true; const lastTurn = turns[count - 1]; const text = extractText(lastTurn); const hasNewAssistantTurn = count > baselineAssistantCount; if (!hasNewAssistantTurn && !generationWasObserved) return; if (!text) return; const key = makeKey(count, text); const now = Date.now(); if (!candidate || candidate.key !== key) { candidate = { key, text, changedAt: now, node: lastTurn }; return; } if (candidate.text !== text) candidate.changedAt = now; candidate.text = text; candidate.node = lastTurn; if (generating) return; if (now - candidate.changedAt < STABLE_FOR_MS || now - startedAt < INITIAL_GRACE_MS || key === lastSentKey) return; notifyDone(lastTurn, text, key); baselineAssistantCount = Math.max(baselineAssistantCount, count); generationWasObserved = false; }
  const observer = new MutationObserver(tick); observer.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["aria-label", "data-testid", "disabled", "href"] }); const intervalId = setInterval(tick, CHECK_INTERVAL_MS); window.__AI_WORKFLOW_BRIDGE_CLEANUP__ = () => { try { observer.disconnect(); } catch {} clearInterval(intervalId); try { delete window.__AI_WORKFLOW_BRIDGE_CLEANUP__; } catch {} }; tick();
})();
