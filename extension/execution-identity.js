(() => {
  function text(value) { return String(value || "").trim(); }
  function bind(button, execution, workspace) {
    if (!button) return;
    button.dataset.executionRevision = text(execution?.revision);
    button.dataset.executionWorkspace = text(workspace);
  }
  function actionPayload(button, fields) {
    const expected_execution_revision = text(button?.dataset?.executionRevision);
    const expected_workspace = text(button?.dataset?.executionWorkspace);
    if (!expected_execution_revision || !expected_workspace) throw new Error("Displayed execution identity is missing. Refresh Mission Control and retry.");
    return { ...fields, expected_execution_revision, expected_workspace };
  }
  function bindRecovery(button, recovery, workspace) {
    if (!button) return;
    button.dataset.runtimeRevision = text(recovery?.revision);
    button.dataset.runtimeWorkspace = text(workspace);
  }
  function recoveryPayload(button) {
    const expected_runtime_revision = text(button?.dataset?.runtimeRevision);
    const expected_workspace = text(button?.dataset?.runtimeWorkspace);
    if (!expected_runtime_revision || !expected_workspace) throw new Error("Displayed recovery identity is missing. Refresh Mission Control and retry.");
    return { expected_runtime_revision, expected_workspace };
  }
  globalThis.AWB_EXECUTION_IDENTITY = { bind, actionPayload, bindRecovery, recoveryPayload };
})();
