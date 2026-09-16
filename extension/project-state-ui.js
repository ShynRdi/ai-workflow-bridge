(() => {
  const byId = (id) => document.getElementById(id);

  function setText(id, value, fallback = "—") {
    const node = byId(id);
    if (node) node.textContent = value || fallback;
  }

  function render(projectState = {}) {
    const current = projectState.current?.label || "NOT PLANNED";
    const next = projectState.next?.label || "—";
    const completed = Number(projectState.completed || 0);
    const total = Number(projectState.total || 0);
    const progress = total > 0 ? `${completed} / ${total} completed` : "No roadmap yet";
    setText("roadmapCurrent", current);
    setText("roadmapNext", next);
    setText("roadmapProgress", progress);
    setText("roadmapPath", projectState.roadmap_path || ".ai-workflow/ROADMAP.md");
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
