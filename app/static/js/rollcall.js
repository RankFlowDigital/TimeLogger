const rollcallPanel = document?.getElementById("rollcall-panel");
const rollcallButton = document?.getElementById("rollcall-respond");
let activeRollCallId = null;
let audio;

async function pollRollCall() {
  try {
    const res = await fetch("/api/me/pending-rollcall");
    if (!res.ok) return;
    const data = await res.json();
    if (data.pending && (!activeRollCallId || data.pending.id !== activeRollCallId)) {
      activeRollCallId = data.pending.id;
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
  if (!audio) {
    audio = new Audio("/static/sounds/rollcall.mp3");
  }
  audio?.play().catch(() => {});
}

function hideRollCall() {
  if (!rollcallPanel) return;
  rollcallPanel.hidden = true;
  activeRollCallId = null;
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
    window.location.reload();
  }
});

setInterval(pollRollCall, 10000);
