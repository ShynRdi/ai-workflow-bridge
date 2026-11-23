(function attachExecutionSender(global) {
  function isTrustedMissionControlSender(sender, extensionId, sidepanelUrl) {
    if (!sender || sender.id !== extensionId || sender.tab != null || !sender.url) return false;
    try {
      const actual = new URL(sender.url);
      const expected = new URL(sidepanelUrl);
      return actual.protocol === "chrome-extension:" && actual.host === expected.host &&
        actual.pathname === expected.pathname;
    } catch (_error) {
      return false;
    }
  }

  global.AWB_EXECUTION_SENDER = { isTrustedMissionControlSender };
})(globalThis);
