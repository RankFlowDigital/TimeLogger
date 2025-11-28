const chatForm = document.getElementById("chat-form");
const chatMessages = document.getElementById("chat-messages");
let lastTimestamp = null;

async function loadMessages() {
  try {
    const url = new URL("/api/chat/messages", window.location.origin);
    if (lastTimestamp) {
      url.searchParams.set("since", lastTimestamp);
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    data.messages.forEach((msg) => appendMessage(msg));
    if (data.messages.length > 0) {
      lastTimestamp = data.messages[data.messages.length - 1].created_at;
    }
  } catch (err) {
    console.error("chat load failed", err);
  }
}

function appendMessage(msg) {
  if (!chatMessages) return;
  const div = document.createElement("div");
  div.className = "message";
  div.innerHTML = `<strong>${msg.user_id}:</strong> ${msg.content} <span>${msg.created_at}</span>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

chatForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(chatForm);
  const content = formData.get("content");
  if (!content) return;
  const res = await fetch("/api/chat/messages", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ content }),
  });
  if (res.ok) {
    chatForm.reset();
    lastTimestamp = null;
    chatMessages.innerHTML = "";
    loadMessages();
  }
});

setInterval(loadMessages, 8000);
