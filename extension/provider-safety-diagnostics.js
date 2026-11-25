(() => {
  // One-shot inspection only. Never installs the workflow content script.
  function inspectVisibleWarnings(providerId) {
    const nodes = Array.from(document.querySelectorAll('[role="alert"], [role="dialog"], [aria-live="assertive"], [data-testid*="toast"], [class*="toast"]'));
    const text = nodes.filter(node => {
      const style = getComputedStyle(node);
      return node.getClientRects().length > 0 && style.visibility !== "hidden" && style.display !== "none";
    }).map(node => (node.innerText || "").trim()).filter(Boolean).join("\n").slice(0, 12000);
    if (/session expired|verify you are human|unusual activity|suspicious activity|captcha|account temporarily|security check|security verification|drag the slider to complete the puzzle/i.test(text)) return "auth_challenge";
    if (/rate limit|too many requests|usage limit|message limit|reached (?:your|the) limit|try again later|come back later/i.test(text)) return "rate_limit";
    if (providerId === "glm") {
      const page = String(document.body?.innerText || "").replace(/\s+/g, " ");
      if (/please complete security verification/i.test(page) && /please drag the slider to complete the puzzle/i.test(page)) return "auth_challenge";
    }
    return "not_observed";
  }

  async function checkProviderSafety() {
    const button = $("checkProviderSafety");
    const status = $("providerSafetyResult");
    button.disabled = true;
    status.textContent = "Inspecting visible warnings…";
    try {
      const lifecycle = lastState?.lifecycle || lastState?.status;
      if (!["setup", "idle", "paused", "complete"].includes(lifecycle)) {
        throw new Error("Pause the workflow and resolve recovery before checking.");
      }
      const provider = await effectiveProvider();
      if (!await chrome.permissions.contains({ origins: provider.origins })) {
        throw new Error("Existing site access is required.");
      }
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id || !tab.url || utils.detectProvider(new URL(tab.url).hostname)?.id !== provider.id) {
        throw new Error("Activate the selected provider tab first.");
      }
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: inspectVisibleWarnings,
        args: [provider.id],
      });
      const [current] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (current?.id !== tab.id || current?.url !== tab.url) throw new Error("Tab changed during inspection.");
      const result = results?.[0]?.result;
      if (result === "auth_challenge" || result === "rate_limit") {
        status.textContent = "WARNING · " + provider.name + " · " + result + " · Keep workflow paused; manual review required.";
        addLog("SHIELD!", status.textContent);
      } else if (result === "not_observed") {
        status.textContent = "INCONCLUSIVE · No visible warning detected in the top frame. This is not clearance to resume.";
      } else {
        throw new Error("No valid inspection result.");
      }
    } catch (error) {
      status.textContent = "UNKNOWN · " + String(error?.message || error) + " · Keep workflow paused.";
    } finally {
      button.disabled = false;
    }
  }

  $("checkProviderSafety")?.addEventListener("click", checkProviderSafety);
  for (const id of ["providerId", "providerAuto"]) {
    $(id)?.addEventListener("change", () => {
      $("providerSafetyResult").textContent = "Not checked for this selection.";
    });
  }
})();
