const rollcallPanel = document?.getElementById("rollcall-panel");
const rollcallButton = document?.getElementById("rollcall-respond");
const rollcallDeadlineText = document?.querySelector("[data-rollcall-deadline]");
const rollcallTargetText = document?.querySelector("[data-rollcall-target]");
const rollcallNoteText = document?.querySelector("[data-rollcall-note]");
let activeRollCallId = null;
let orgActiveRollCalls = [];
let audio;
let deadlineAt = null;
let countdownHandle = null;
let dashboardSubscribed = false;

document.addEventListener("DOMContentLoaded", () => {
  bindOrgRollCallFeed();
  pollRollCall();
});

async function pollRollCall() {
  try {
    const res = await fetch("/api/me/pending-rollcall");
    if (!res.ok) return;
    const data = await res.json();
    if (data.pending && (!activeRollCallId || data.pending.id !== activeRollCallId)) {
      activeRollCallId = data.pending.id;
      deadlineAt = new Date(data.pending.deadline_at);
      showRollCall();
      window.dashboardRuntime?.refresh?.();
    } else if (!data.pending) {
      hideRollCall();
    }
  } catch (err) {
    console.error("rollcall poll failed", err);
  }
}

function bindOrgRollCallFeed() {
  if (dashboardSubscribed || !window.dashboardRuntime) return;
  dashboardSubscribed = true;
  window.dashboardRuntime.subscribe((state) => {
    updateOrgRollCallPanel(state);
  });
  updateOrgRollCallPanel(window.dashboardRuntime.getState());
}

function updateOrgRollCallPanel(state) {
  if (!rollcallPanel || !state) return;
  const active = state.active_roll_calls || [];
  orgActiveRollCalls = active;
  if (!active.length) {
    if (!activeRollCallId) {
      rollcallPanel.hidden = true;
      if (rollcallTargetText) {
        rollcallTargetText.textContent = "Waiting for the next call";
      }
      if (rollcallNoteText) {
        rollcallNoteText.textContent = "";
      }
    }
    return;
  }
  const current = active[0];
  rollcallPanel.hidden = false;
  const isSelf = current.user_id === state.user?.id;
  if (rollcallTargetText) {
    rollcallTargetText.textContent = isSelf ? "Roll call for you" : `Calling ${current.user_name}`;
  }
  if (rollcallButton) {
    rollcallButton.disabled = !isSelf;
    rollcallButton.hidden = false;
    rollcallButton.textContent = isSelf ? "I'm here" : "Waiting";
  }
  if (rollcallNoteText) {
    rollcallNoteText.textContent = isSelf ? "Only you can clear this alert." : `${current.user_name} must respond.`;
  }
  if (!isSelf && current.deadline_at) {
    deadlineAt = new Date(current.deadline_at);
    startCountdown();
  }
}

function showRollCall() {
  if (!rollcallPanel) return;
  rollcallPanel.hidden = false;
  if (rollcallTargetText) {
    rollcallTargetText.textContent = "Roll call for you";
  }
  if (rollcallNoteText) {
    rollcallNoteText.textContent = "Only you can clear this alert.";
  }
  startCountdown();
  if (!audio) {
    audio = new Audio("/static/sounds/rollcall.mp3");
  }
  audio?.play().catch(() => {});
}

function hideRollCall() {
  if (!rollcallPanel) return;
  activeRollCallId = null;
  deadlineAt = null;
  if (countdownHandle) {
    clearInterval(countdownHandle);
    countdownHandle = null;
  }
  if (rollcallDeadlineText) {
    rollcallDeadlineText.textContent = "You're clear";
  }
  if (!orgActiveRollCalls.length) {
    rollcallPanel.hidden = true;
    if (rollcallTargetText) {
      rollcallTargetText.textContent = "Waiting for the next call";
    }
    if (rollcallNoteText) {
      rollcallNoteText.textContent = "";
    }
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
  if (!activeRollCallId || rollcallButton?.disabled) return;
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
