(() => {
  function text(value) { return String(value || "").trim(); }

  function bind(button, policy) {
    if (!button) return;
    button.dataset.policyRevision = text(policy?.revision);
    button.dataset.policyProfile = text(policy?.profile);
  }

  function actionPayload(button, desiredProfile) {
    const expected_policy_revision = text(button?.dataset?.policyRevision);
    const desired_profile = text(desiredProfile).toLowerCase();
    if (!expected_policy_revision || !desired_profile) {
      throw new Error("Displayed policy identity is missing. Refresh Mission Control and retry.");
    }
    return { desired_profile, expected_policy_revision };
  }

  globalThis.AWB_POLICY_PROFILE_IDENTITY = { bind, actionPayload };
})();
