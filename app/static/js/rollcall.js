const rollcallPanel = document?.getElementById("rollcall-panel");
const rollcallButton = document?.getElementById("rollcall-respond");
const rollcallDeadlineText = document?.querySelector("[data-rollcall-deadline]");
let activeRollCallId = null;
let audio;
let deadlineAt = null;
let countdownHandle = null;

async function pollRollCall() {
  try {
    const res = await fetch("/api/me/pending-rollcall");
    if (!res.ok) return;
    const data = await res.json();
    if (data.pending && (!activeRollCallId || data.pending.id !== activeRollCallId)) {
      activeRollCallId = data.pending.id;
      deadlineAt = new Date(data.pending.deadline_at);
      showRollCall();
    } else if (!data.pending) {
      hideRollCall();
    }
  } catch (err) {
    console.error("rollcall poll failed", err);
  }
}

function showRollCall() {
  if (!rollcallPanel) return;
  rollcallPanel.hidden = false;
  startCountdown();
  if (!audio) {
    audio = new Audio("/static/sounds/rollcall.mp3");
  }
  audio?.play().catch(() => {});
}

function hideRollCall() {
  if (!rollcallPanel) return;
  rollcallPanel.hidden = true;
  activeRollCallId = null;
  deadlineAt = null;
  if (countdownHandle) {
    clearInterval(countdownHandle);
    countdownHandle = null;
  }
  if (rollcallDeadlineText) {
    rollcallDeadlineText.textContent = "You're clear";
  }
}

function startCountdown() {
  if (!rollcallDeadlineText) return;
  const update = () => {
    if (!deadlineAt) return;
    const now = new Date();
    const diff = Math.max(0, Math.floor((deadlineAt - now) / 1000));
    const minutes = Math.floor(diff / 60);
    const seconds = diff % 60;
    rollcallDeadlineText.textContent = `Respond within ${minutes}:${seconds.toString().padStart(2, "0")}`;
    if (diff <= 0) {
      rollcallDeadlineText.textContent = "Deadline passed";
    }
  };
  update();
  if (countdownHandle) clearInterval(countdownHandle);
  countdownHandle = setInterval(update, 1000);
}

rollcallButton?.addEventListener("click", async () => {
  if (!activeRollCallId) return;
  const res = await fetch("/api/roll-calls/respond", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ roll_call_id: activeRollCallId }),
  });
  if (res.ok) {
    hideRollCall();
    window.dashboardRuntime?.refresh();
  }
});

setInterval(pollRollCall, 10000);
