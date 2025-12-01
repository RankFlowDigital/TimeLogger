const rollcallPanel = document?.getElementById("rollcall-panel");
const rollcallButton = document?.getElementById("rollcall-respond");
const rollcallDeadlineText = document?.querySelector("[data-rollcall-deadline]");
const rollcallTargetText = document?.querySelector("[data-rollcall-target]");
const rollcallNoteText = document?.querySelector("[data-rollcall-note]");
const ROLLCALL_SOUND_PATH = "/static/sounds/message-alert-190042.mp3";
let activeRollCallId = null;
let orgActiveRollCalls = [];
let audio;
let deadlineAt = null;
let countdownHandle = null;
let dashboardSubscribed = false;

function setRollcallNote(message) {
  if (rollcallNoteText) {
    rollcallNoteText.textContent = message ?? "";
  }
}

function clearCountdown() {
  deadlineAt = null;
  if (countdownHandle) {
    clearInterval(countdownHandle);
    countdownHandle = null;
  }
}

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
    } else if (!data.pending && activeRollCallId) {
      hideRollCall();
    } else if (!data.pending) {
      clearCountdown();
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
      setRollcallNote("");
      clearCountdown();
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
  setRollcallNote(isSelf ? "Only you can clear this alert." : `${current.user_name} must respond.`);
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
  setRollcallNote("Only you can clear this alert.");
  startCountdown();
  if (!audio) {
    audio = new Audio(ROLLCALL_SOUND_PATH);
  }
  try {
    audio.currentTime = 0;
    audio?.play().catch(() => {
      setRollcallNote("Sound blocked by your browser. Click anywhere to enable alerts.");
    });
  } catch (error) {
    console.error("rollcall audio failed", error);
  }
}

function hideRollCall() {
  if (!rollcallPanel) return;
  activeRollCallId = null;
  clearCountdown();
  if (rollcallDeadlineText) {
    rollcallDeadlineText.textContent = "You're clear";
  }
  if (!orgActiveRollCalls.length) {
    rollcallPanel.hidden = true;
    if (rollcallTargetText) {
      rollcallTargetText.textContent = "Waiting for the next call";
    }
    setRollcallNote("");
  }
}

function startCountdown() {
  if (!rollcallDeadlineText) return;
  const update = () => {
    if (!deadlineAt) return;
    const now = new Date();
    const diff = Math.floor((deadlineAt - now) / 1000);
    const magnitude = Math.abs(diff);
    const minutes = Math.floor(magnitude / 60);
    const seconds = magnitude % 60;
    const formatted = `${minutes}:${seconds.toString().padStart(2, "0")}`;
    if (diff >= 0) {
      rollcallDeadlineText.textContent = `Respond within ${formatted}`;
    } else {
      rollcallDeadlineText.textContent = `Overdue ${formatted}`;
    }
  };
  update();
  if (countdownHandle) clearInterval(countdownHandle);
  countdownHandle = setInterval(update, 1000);
}

rollcallButton?.addEventListener("click", async () => {
  if (!activeRollCallId || rollcallButton?.disabled) return;
  const originalLabel = rollcallButton.textContent;
  rollcallButton.disabled = true;
  rollcallButton.textContent = "Sending…";
  try {
    const res = await fetch("/api/roll-calls/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roll_call_id: activeRollCallId }),
    });
    if (res.ok) {
      hideRollCall();
      window.dashboardRuntime?.refresh();
      return;
    }
    const payload = await res.json().catch(() => ({}));
    if (payload?.status === "invalid") {
      setRollcallNote("This roll call already closed. Updating…");
      await pollRollCall();
      return;
    }
    setRollcallNote("Unable to submit response. Please try again.");
  } catch (error) {
    console.error("rollcall respond failed", error);
    setRollcallNote("Network error. Please try again.");
  } finally {
    if (activeRollCallId) {
      rollcallButton.disabled = false;
      rollcallButton.textContent = originalLabel || "I'm here";
    }
  }
});

setInterval(pollRollCall, 10000);
