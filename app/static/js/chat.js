const chatState = {
  interfaces: [],
  buffer: [],
  lastTimestamp: null,
  pollingHandle: null,
};

function registerInterface(channel, form, messages) {
  if (!messages) return false;
  chatState.interfaces.push({ channel, form, messages });
  if (form) {
    form.addEventListener("submit", (event) => handleChatSubmit(event, channel));
  }
  return true;
}

function initDataAttributeInterfaces() {
  const containers = document.querySelectorAll("[data-chat-messages]");
  containers.forEach((messages) => {
    const channel = messages.dataset.chatMessages || "team";
    const form = document.querySelector(`[data-chat-form="${channel}"]`);
    registerInterface(channel, form, messages);
  });
}

function initLegacyInterfaces() {
  const legacyInterfaces = [
    { channel: "team", formId: "chat-form", messagesId: "chat-messages" },
  ];
  legacyInterfaces.forEach(({ channel, formId, messagesId }) => {
    const form = document.getElementById(formId);
    const messages = document.getElementById(messagesId);
    if (messages && !chatState.interfaces.some((i) => i.messages === messages)) {
      registerInterface(channel, form, messages);
    }
  });
}

async function handleChatSubmit(event, channel) {
  event.preventDefault();
  if (channel !== "team") return;
  const form = event.currentTarget;
  const formData = new FormData(form);
  const content = (formData.get("content") || "").trim();
  if (!content) return;
  try {
    const res = await fetch("/api/chat/messages", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ content }),
    });
    if (res.ok) {
      form.reset();
      chatState.lastTimestamp = null;
      await loadMessages(true);
    }
  } catch (err) {
    console.error("chat send failed", err);
  }
}

async function loadMessages(forceRefresh = false) {
  if (!chatState.interfaces.length) return;
  try {
    const url = new URL("/api/chat/messages", window.location.origin);
    if (!forceRefresh && chatState.lastTimestamp) {
      url.searchParams.set("since", chatState.lastTimestamp);
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    const incoming = Array.isArray(data.messages) ? data.messages : [];
    if (forceRefresh) {
      chatState.buffer = [];
    }
    if (incoming.length) {
      chatState.buffer = chatState.buffer.concat(incoming);
      chatState.lastTimestamp = incoming[incoming.length - 1].created_at;
    }
    if (forceRefresh || incoming.length) {
      chatState.interfaces
        .filter((iface) => iface.channel === "team")
        .forEach(({ messages }) => renderMessages(messages));
    }
  } catch (err) {
    console.error("chat load failed", err);
  }
}

function renderMessages(container) {
  container.innerHTML = "";
  chatState.buffer.forEach((msg) => {
    const div = document.createElement("div");
    div.className = "message";
    const author = document.createElement("div");
    author.className = "author";
    const name = msg.user_name || `User ${msg.user_id}`;
    author.textContent = name;
    const body = document.createElement("div");
    body.className = "body";
    body.textContent = msg.content;
    const stamp = document.createElement("div");
    stamp.className = "timestamp";
    stamp.textContent = formatTimestamp(msg.created_at);
    div.append(author, body, stamp);
    container.appendChild(div);
  });
  container.scrollTop = container.scrollHeight;
}

function formatTimestamp(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (window.dashboardRuntime?.getDisplayTimezone) {
    try {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: window.dashboardRuntime.getDisplayTimezone(),
      }).format(date);
    } catch (err) {
      console.error("timestamp format failed", err);
    }
  }
  return date.toLocaleString();
}

function setupChatTabs() {
  const tabs = document.querySelectorAll(".chat-tab");
  const panels = document.querySelectorAll(".chat-panel");
  if (!tabs.length || !panels.length) return;
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.chatTab;
      tabs.forEach((t) => t.classList.toggle("active", t === tab));
      panels.forEach((panel) => {
        const isActive = panel.dataset.chatPanel === target;
        panel.classList.toggle("active", isActive);
        panel.setAttribute("aria-hidden", String(!isActive));
      });
    });
  });
}

function startChatPolling() {
  loadMessages(true);
  if (!chatState.pollingHandle) {
    chatState.pollingHandle = setInterval(() => loadMessages(), 8000);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initDataAttributeInterfaces();
  initLegacyInterfaces();
  setupChatTabs();
  initInviteForm();
  if (chatState.interfaces.some((iface) => iface.channel === "team")) {
    startChatPolling();
  }
});

function initInviteForm() {
  const form = document.querySelector("[data-invite-form]");
  if (!form) return;
  const feedback = form.querySelector("[data-invite-feedback]");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = {
      full_name: formData.get("full_name")?.trim(),
      email: formData.get("email")?.trim(),
      role: formData.get("role") || "MEMBER",
      timezone: formData.get("timezone") || null,
    };
    if (!payload.full_name || !payload.email) return;
    try {
      const res = await fetch("/api/users/invite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.detail || "Invite failed");
      }
      const data = await res.json();
      form.reset();
      if (feedback) {
        feedback.textContent = `Invite sent. Temporary password: ${data.temp_password}`;
      }
      window.dashboardRuntime?.refresh();
    } catch (err) {
      console.error(err);
      if (feedback) {
        feedback.textContent = err.message || "Unable to send invite";
        feedback.style.color = "#b91c1c";
      }
    }
    setTimeout(() => {
      if (feedback) {
        feedback.textContent = "";
        feedback.style.color = "";
      }
    }, 6000);
  });
}
