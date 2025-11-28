document.addEventListener("DOMContentLoaded", () => {
  const actionButtons = document.querySelectorAll("[data-action]");
  const routeMap = {
    "start-work": "start",
    "stop-work": "stop",
    "start-lunch": "start-lunch",
    "end-lunch": "end-lunch",
    "start-break": "start-break",
    "end-break": "end-break",
  };
  actionButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.getAttribute("data-action");
      const endpoint = routeMap[action];
      if (!endpoint) return;
      const payload = action === "start-work" ? { task_description: "" } : undefined;
      const response = await fetch(`/api/sessions/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload ? JSON.stringify(payload) : undefined,
      });
      if (response.ok) {
        window.location.reload();
      }
    });
  });
});
