(() => {
  const PROMPT = "AI Workflow Bridge provider compatibility smoke test. Reply with exactly AWB_SMOKE_OK and nothing else. Do not browse, use tools, open links, create files, or explain.";
  const BUSY = new Set(["running", "arming", "reporting", "waiting_llm", "waiting_chatgpt", "recovering", "change_review", "finishing"]);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function currentLifecycle() {
    return String(lastState?.lifecycle || lastState?.status || "setup").toLowerCase();
  }

  async function findProviderTab(provider) {
    const active = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
    if (active?.url) {
      try { if (utils.detectProvider(new URL(active.url).hostname)?.id === provider.id) return active; } catch {}
    }
    const tabs = await chrome.tabs.query({ url: provider.origins });
    return tabs.find((tab) => tab.active) || tabs[0] || null;
  }

  async function ensureBridge(tabId, provider) {
    try {
      const ping = await chrome.tabs.sendMessage(tabId, { type: "BRIDGE_PING" });
      if (ping?.ok && ping.provider === provider.id) return ping;
    } catch {}
    await chrome.scripting.executeScript({ target: { tabId }, files: ["providers.js", "content.js"] });
    await sleep(250);
    const ping = await chrome.tabs.sendMessage(tabId, { type: "BRIDGE_PING" });
    if (!ping?.ok || ping.provider !== provider.id) throw new Error(`${provider.name} adapter did not answer the health ping.`);
    return ping;
  }

  async function inspectProviderDom(tabId, provider) {
    const result = await chrome.scripting.executeScript({
      target: { tabId },
      args: [provider.assistant || []],
      func: (assistantSelectors) => {
        const generic = ['[data-message-author-role="assistant"]', '[data-testid*="assistant"]', '[data-role="assistant"]', '[data-message-role="assistant"]'];
        const seen = new Set(); const nodes = [];
        for (const selector of [...assistantSelectors, ...generic]) {
          try { document.querySelectorAll(selector).forEach((node) => { if (!seen.has(node)) { seen.add(node); nodes.push(node); } }); } catch {}
        }
        const top = nodes.filter((node, idx) => !nodes.some((other, j) => j !== idx && other.contains(node)));
        const last = top.at(-1); const text = (last?.innerText || last?.textContent || "").trim().slice(0, 800);
        const alertNodes = Array.from(document.querySelectorAll('[role="alert"], [role="dialog"], [aria-live="assertive"], [data-testid*="toast"], [class*="toast"]'));
        const alerts = alertNodes.map((n) => (n.innerText || n.textContent || "").trim()).filter(Boolean).join("\n").slice(0, 4000);
        let safety = "";
        if (/rate limit|too many requests|usage limit|message limit|reached (?:your|the) limit|try again later|come back later/i.test(alerts)) safety = "rate_limit";
        else if (/session expired|verify you are human|unusual activity|suspicious activity|captcha|account temporarily|security check/i.test(alerts)) safety = "auth_challenge";
        return { assistantCount: top.length, lastText: text, safety };
      }
    });
    return result?.[0]?.result || { assistantCount: 0, lastText: "", safety: "" };
  }

  async function storeResult(provider, result) {
    const stored = await chrome.storage.local.get("providerSmokeResults");
    const all = stored.providerSmokeResults || {};
    all[provider.id] = { status: result.status, at: new Date().toISOString(), contentVersion: result.contentVersion || "", markerFound: Boolean(result.markerFound) };
    await chrome.storage.local.set({ providerSmokeResults: all });
  }

  async function renderLastResult() {
    const provider = selectedProvider(); const status = $("providerSmokeStatus"); if (!status || !provider) return;
    const stored = await chrome.storage.local.get("providerSmokeResults"); const result = stored.providerSmokeResults?.[provider.id];
    if (!result) { status.textContent = "Not tested on this browser profile yet."; return; }
    const when = new Date(result.at).toLocaleString(); status.textContent = `${result.status === "pass" ? "PASS" : "FAIL"} · ${when}${result.contentVersion ? ` · content ${result.contentVersion}` : ""}`;
  }

  async function runSmokeTest() {
    const button = $("providerSmokeTest"); button.disabled = true; $("providerSmokeStatus").textContent = "Testing one safe turn…";
    let provider = selectedProvider();
    try {
      const lifecycle = currentLifecycle();
      if (BUSY.has(lifecycle)) throw new Error(`Project lifecycle is ${lifecycle}. Pause the workflow before testing an adapter.`);
      provider = await grantProviderAccess({ quiet: true });
      await saveProject({ log: false });
      const tab = await findProviderTab(provider); if (!tab?.id) throw new Error(`Open ${provider.name} in a tab and log in yourself first.`);
      const ping = await ensureBridge(tab.id, provider); if (!ping.composerFound) throw new Error(`${provider.name} composer was not detected.`);
      const before = await inspectProviderDom(tab.id, provider); if (before.safety) throw new Error(`${provider.name} is showing a ${before.safety} safety/account warning. Smoke test stopped.`);
      addLog("TEST", `${provider.name}: one-turn adapter smoke test started. No retries or fallback.`);
      const sent = await chrome.tabs.sendMessage(tab.id, { type: "SEND_TO_LLM", payload: { text: PROMPT, submit: true } });
      if (!sent?.ok || sent.submitted !== true) throw new Error(sent?.error || `${provider.name} did not confirm prompt submission.`);
      const deadline = Date.now() + 90000;
      while (Date.now() < deadline) {
        await sleep(1000);
        const health = await chrome.tabs.sendMessage(tab.id, { type: "BRIDGE_PING" });
        const snapshot = await inspectProviderDom(tab.id, provider);
        if (snapshot.safety) throw new Error(`${provider.name} raised ${snapshot.safety}; no retry was attempted.`);
        if (snapshot.assistantCount > before.assistantCount && !health?.generating) {
          const markerFound = snapshot.lastText.includes("AWB_SMOKE_OK");
          if (!markerFound) throw new Error(`${provider.name} returned a response, but the expected AWB_SMOKE_OK marker was not captured.`);
          await storeResult(provider, { status: "pass", contentVersion: health?.version || sent.version || "", markerFound: true });
          $("providerSmokeStatus").textContent = `PASS · composer, submit, response capture · ${provider.name}`;
          addLog("PASS", `${provider.name} adapter smoke test passed: composer → submit → response capture.`);
          return;
        }
      }
      throw new Error(`${provider.name} did not complete a capturable response within 90 seconds. No retry was attempted.`);
    } catch (error) {
      await storeResult(provider, { status: "fail", markerFound: false }).catch(() => {});
      $("providerSmokeStatus").textContent = `FAIL · ${String(error?.message || error)}`;
      addLog("FAIL", String(error?.message || error));
    } finally { button.disabled = false; }
  }

  $("providerSmokeTest")?.addEventListener("click", runSmokeTest);
  $("providerId")?.addEventListener("change", () => renderLastResult().catch(() => {}));
  renderLastResult().catch(() => {});
})();
