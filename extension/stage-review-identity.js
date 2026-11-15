(() => {
  function text(value) {
    return String(value || "").trim();
  }

  function bindActionIdentity(button, review) {
    if (!button) return;
    button.dataset.reviewId = text(review?.review_id);
    button.dataset.reviewPhase = text(review?.phase);
    button.dataset.reviewStage = text(review?.stage);
  }

  function actionPayload(button, decision) {
    const reviewId = text(button?.dataset?.reviewId);
    const phase = text(button?.dataset?.reviewPhase);
    const stage = text(button?.dataset?.reviewStage);
    const value = text(decision).toLowerCase();

    if (!reviewId || !phase || !stage) {
      throw new Error(
        "Displayed stage-review identity is missing. Refresh Mission Control and retry.",
      );
    }

    if (![
      "accept",
      "reject",
    ].includes(value)) {
      throw new Error("Stage review decision must be accept or reject.");
    }

    return {
      review_id: reviewId,
      phase,
      stage,
      decision: value,
    };
  }

  globalThis.AWB_STAGE_REVIEW_IDENTITY = {
    bindActionIdentity,
    actionPayload,
  };
})();
