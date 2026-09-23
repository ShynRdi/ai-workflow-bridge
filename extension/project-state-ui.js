(() => {
  const byId = (id) => document.getElementById(id);

  function setText(id, value, fallback = "—") {
    const node = byId(id);
    if (node) node.textContent = value || fallback;
  }

  function render(projectState = {}) {
    const current = projectState.current?.label || "NOT PLANNED";
    const next = projectState.next?.label || "—";
    const completed = Math.max(
      0,
      Number(projectState.completed || 0),
    );
    const total = Math.max(
      0,
      Number(projectState.total || 0),
    );
    const boundedCompleted = Math.min(completed, total);
    const remaining = Math.max(total - boundedCompleted, 0);
    const percent = total > 0
      ? Math.min(
          100,
          Math.max(
            0,
            Math.round((boundedCompleted / total) * 100),
          ),
        )
      : 0;

    const progress = total > 0
      ? `${boundedCompleted} / ${total} completed`
      : "No roadmap yet";

    setText("roadmapCurrent", current);
    setText("roadmapNext", next);
    setText("roadmapProgress", progress);
    setText(
      "roadmapProgressPercent",
      total > 0 ? `${percent}%` : "0%",
    );
    setText(
      "roadmapRemaining",
      total > 0
        ? `${remaining} stage${remaining === 1 ? "" : "s"} remaining`
        : "No roadmap yet",
    );
    setText(
      "roadmapPath",
      projectState.roadmap_path || ".ai-workflow/ROADMAP.md",
    );

    const progressBar = byId("roadmapProgressBar");
    const progressFill = byId("roadmapProgressFill");

    if (progressBar) {
      progressBar.setAttribute("aria-valuenow", String(percent));
      progressBar.setAttribute(
        "aria-valuetext",
        total > 0
          ? `${boundedCompleted} of ${total} stages completed`
          : "No roadmap yet",
      );
    }

    if (progressFill) {
      progressFill.style.width = `${percent}%`;
    }
    const error = byId("roadmapError");
    if (error) {
      error.textContent = projectState.error ? `Project state error: ${projectState.error}` : "";
      error.classList.toggle("hidden", !projectState.error);
    }
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== "BRIDGE_EVENT") return;
    const event = message.payload || {};
    if (event.kind === "state") render(event.state?.project_state || {});
  });

  render({});
})();
