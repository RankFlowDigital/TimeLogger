const rollcallPanel = document?.getElementById("rollcall-panel");
const rollcallButton = document?.getElementById("rollcall-respond");
const rollcallDeadlineText = document?.querySelector("[data-rollcall-deadline]");
const rollcallTargetText = document?.querySelector("[data-rollcall-target]");
const rollcallNoteText = document?.querySelector("[data-rollcall-note]");
const rollcallModal = document?.getElementById("rollcall-modal");
const rollcallModalText = document?.querySelector("[data-rollcall-modal-text]");
const rollcallModalClose = document?.querySelector("[data-rollcall-modal-close]");
const ROLLCALL_SOUND_PATH = "/static/sounds/message-alert-190042.mp3";
const ROLLCALL_POLL_INTERVAL = 10000;
let activeRollCallId = null;
let orgActiveRollCalls = [];
let audio;
let deadlineAt = null;
let countdownHandle = null;
let dashboardSubscribed = false;
let pendingResponse = false;

function setDeadlineDisplay(text, state = "idle") {
  if (!rollcallDeadlineText) return;
  rollcallDeadlineText.textContent = text;
  rollcallDeadlineText.dataset.state = state;
}

function setRollcallNote(message) {
  if (rollcallNoteText) {
    rollcallNoteText.textContent = message ?? "";
  }
}

function showRollcallModal(message) {
  if (!rollcallModal || !rollcallModalText) return;
  rollcallModalText.textContent = message;
  rollcallModal.hidden = false;
}

function hideRollcallModal() {
  if (!rollcallModal) return;
  rollcallModal.hidden = true;
}

function setButtonState(isSelf) {
  if (!rollcallButton) return;
  if (isSelf) {
    rollcallButton.disabled = false;
    rollcallButton.dataset.mode = "self";
    rollcallButton.textContent = "I'm here";
  } else {
    rollcallButton.disabled = true;
    rollcallButton.dataset.mode = "spectator";
    rollcallButton.textContent = "Waiting";
  }
}

function clearCountdown(options = {}) {
  const { resetText = true } = options;
  deadlineAt = null;
  if (countdownHandle) {
    clearInterval(countdownHandle);
    countdownHandle = null;
  }
  if (resetText) {
    setDeadlineDisplay("You're clear");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  bindOrgRollCallFeed();
  pollRollCall();
});

rollcallModalClose?.addEventListener("click", hideRollcallModal);
rollcallModal?.addEventListener("click", (event) => {
  if (event.target === rollcallModal) {
    hideRollcallModal();
  }
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
    } else if (!data.pending && !orgActiveRollCalls.length) {
      clearCountdown();
    }
    if (window.dashboardRuntime?.refresh) {
      window.dashboardRuntime.refresh();
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
  const targetLabel = isSelf ? "Roll call for you" : `Calling ${current.user_name}`;
  if (rollcallTargetText) {
    rollcallTargetText.textContent = targetLabel;
  }
  setButtonState(isSelf);
  if (rollcallButton) {
    rollcallButton.hidden = false;
  }
  setRollcallNote(isSelf ? "Only you can clear this alert." : `${current.user_name} must respond.`);
  if (!isSelf && current.deadline_at) {
    deadlineAt = new Date(current.deadline_at);
    startCountdown();
  } else if (isSelf && activeRollCallId && current.deadline_at) {
    deadlineAt = new Date(current.deadline_at);
    startCountdown();
  }
}

function showRollCall() {
  if (!rollcallPanel) return;
  rollcallPanel.hidden = false;
  setButtonState(true);
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
  clearCountdown({ resetText: !orgActiveRollCalls.length });
  if (!orgActiveRollCalls.length) {
    rollcallPanel.hidden = true;
    if (rollcallTargetText) {
      rollcallTargetText.textContent = "Waiting for the next call";
    }
    setRollcallNote("");
  }
  hideRollcallModal();
}

function startCountdown() {
  if (!rollcallDeadlineText || !deadlineAt) return;
  const update = () => {
    const now = new Date();
    const diff = Math.floor((deadlineAt - now) / 1000);
    const magnitude = Math.abs(diff);
    const minutes = Math.floor(magnitude / 60);
    const seconds = magnitude % 60;
    const formatted = `${minutes}:${seconds.toString().padStart(2, "0")}`;
    if (diff >= 0) {
      setDeadlineDisplay(`Respond within ${formatted}`, "pending");
    } else {
      setDeadlineDisplay(`Overdue ${formatted}`, "overdue");
    }
  };
  update();
  if (countdownHandle) clearInterval(countdownHandle);
  countdownHandle = setInterval(update, 1000);
}

rollcallButton?.addEventListener("click", async () => {
  if (!activeRollCallId || rollcallButton?.disabled) return;
  if (pendingResponse) return;
  const originalLabel = rollcallButton.textContent;
  rollcallButton.disabled = true;
  rollcallButton.textContent = "Sending…";
  pendingResponse = true;
  showRollcallModal("Sending your response…");
  try {
    const res = await fetch("/api/roll-calls/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roll_call_id: activeRollCallId }),
    });
    if (res.ok) {
      hideRollCall();
      window.dashboardRuntime?.refresh();
      showRollcallModal("Response recorded. You're all set!");
      setTimeout(hideRollcallModal, 2500);
      return;
    }
    const payload = await res.json().catch(() => ({}));
    if (payload?.status === "invalid") {
      setRollcallNote("This roll call already closed. Updating…");
      await pollRollCall();
      showRollcallModal("That roll call already ended.");
      setTimeout(hideRollcallModal, 2500);
      return;
    }
    setRollcallNote("Unable to submit response. Please try again.");
    showRollcallModal("Unable to submit response. Please try again.");
  } catch (error) {
    console.error("rollcall respond failed", error);
    setRollcallNote("Network error. Please try again.");
    showRollcallModal("Network error. Please try again.");
  } finally {
    if (activeRollCallId) {
      rollcallButton.disabled = false;
      rollcallButton.textContent = originalLabel || "I'm here";
    }
    pendingResponse = false;
  }
});

setInterval(pollRollCall, ROLLCALL_POLL_INTERVAL);
