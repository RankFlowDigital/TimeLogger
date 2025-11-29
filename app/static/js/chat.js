const chatState = {
  interfaces: [],
  buffers: new Map(),
  cursors: new Map(),
  rooms: [],
  availableUsers: [],
  activeRoomId: null,
  defaultRoomId: null,
  pollingHandle: null,
  threadListEl: null,
  roomNameEl: null,
  roomMetaEl: null,
  manageOverlay: null,
  isAdmin: false,
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
  const form = event.currentTarget;
  const formData = new FormData(form);
  const content = (formData.get("content") || "").trim();
  if (!content) return;

  let roomId = Number(formData.get("room_id")) || null;
  if (channel === "team" || channel === "room") {
    roomId = chatState.activeRoomId || roomId || chatState.defaultRoomId;
    if (!roomId) return;
  }

  try {
    const res = await fetch("/api/chat/messages", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ content, room_id: roomId ?? "" }),
    });
    if (res.ok) {
      form.reset();
      chatState.cursors.delete(roomId);
      await loadMessages(true);
    }
  } catch (err) {
    console.error("chat send failed", err);
  }
}

async function loadMessages(forceRefresh = false) {
  if (!chatState.interfaces.length) return;
  const roomId = chatState.activeRoomId || chatState.defaultRoomId;
  if (!roomId) return;
  try {
    const url = new URL("/api/chat/messages", window.location.origin);
    url.searchParams.set("room_id", roomId);
    if (!forceRefresh && chatState.cursors.has(roomId)) {
      url.searchParams.set("since", chatState.cursors.get(roomId));
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    const incoming = Array.isArray(data.messages) ? data.messages : [];
    const buffer = forceRefresh ? [] : chatState.buffers.get(roomId) || [];
    if (incoming.length) {
      incoming.forEach((message) => buffer.push(message));
      chatState.cursors.set(roomId, incoming[incoming.length - 1].created_at);
    }
    chatState.buffers.set(roomId, buffer);
    if (forceRefresh || incoming.length) {
      chatState.interfaces
        .filter((iface) => iface.channel === "team" || iface.channel === "room")
        .forEach(({ messages }) => renderMessages(messages, roomId));
    }
  } catch (err) {
    console.error("chat load failed", err);
  }
}

function renderMessages(container, roomId) {
  const buffer = chatState.buffers.get(roomId) || [];
  container.innerHTML = "";
  if (!buffer.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No messages yet. Start the conversation.";
    container.appendChild(empty);
    return;
  }
  buffer.forEach((msg) => {
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
  initChatWidthControl();
  initChatRooms();
  if (chatState.interfaces.some((iface) => iface.channel === "team" || iface.channel === "room")) {
    startChatPolling();
  }
});

function initChatRooms() {
  chatState.threadListEl = document.querySelector("[data-chat-thread-list]");
  chatState.roomNameEl = document.querySelector("[data-chat-room-name]");
  chatState.roomMetaEl = document.querySelector("[data-chat-room-meta]");
  chatState.manageOverlay = document.querySelector("[data-chat-manager]");
  const dock = document.getElementById("chat-dock");
  if (dock?.dataset?.userRole) {
    chatState.isAdmin = ["OWNER", "ADMIN"].includes(dock.dataset.userRole);
  }
  if (!chatState.threadListEl) return;
  loadRooms({ includeUsers: chatState.isAdmin });
  initChatManager();
}

async function loadRooms({ includeUsers = false } = {}) {
  try {
    const url = new URL("/api/chat/rooms", window.location.origin);
    if (includeUsers) {
      url.searchParams.set("include_users", "1");
    }
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    chatState.rooms = Array.isArray(data.rooms) ? data.rooms : [];
    chatState.defaultRoomId = data.default_room_id || chatState.defaultRoomId;
    if (includeUsers && Array.isArray(data.users)) {
      chatState.availableUsers = data.users;
    }
    if (!chatState.activeRoomId || !chatState.rooms.some((room) => room.id === chatState.activeRoomId)) {
      chatState.activeRoomId = data.active_room_id || chatState.defaultRoomId || chatState.rooms[0]?.id || null;
    }
    renderRoomList();
    updateRoomHeader();
    if (chatState.activeRoomId) {
      loadMessages(true);
    }
    syncManagerOptions();
  } catch (err) {
    console.error("chat rooms load failed", err);
  }
}

function renderRoomList() {
  if (!chatState.threadListEl) return;
  chatState.threadListEl.innerHTML = "";
  if (!chatState.rooms.length) {
    const li = document.createElement("li");
    li.className = "chat-panel-empty";
    li.textContent = "No chats yet";
    chatState.threadListEl.appendChild(li);
    return;
  }
  chatState.rooms.forEach((room) => {
    const li = document.createElement("li");
    li.className = "chat-thread";
    if (room.id === chatState.activeRoomId) {
      li.classList.add("active");
    }
    const button = document.createElement("button");
    button.type = "button";
    button.addEventListener("click", () => setActiveRoom(room.id));

    const avatar = document.createElement("div");
    avatar.className = "thread-avatar";
    avatar.textContent = initialsFromName(room.name);

    const body = document.createElement("div");
    body.className = "thread-body";
    const title = document.createElement("strong");
    title.textContent = room.name;
    body.appendChild(title);
    const pill = document.createElement("span");
    pill.className = "chat-room-pill";
    pill.textContent = room.is_direct ? "Direct" : "Group";
    body.appendChild(pill);

    const meta = document.createElement("div");
    meta.className = "thread-meta";
    meta.textContent = room.member_count ? `${room.member_count} members` : "--";

    button.append(avatar, body, meta);
    li.appendChild(button);
    chatState.threadListEl.appendChild(li);
  });
}

function setActiveRoom(roomId) {
  if (chatState.activeRoomId === roomId) return;
  chatState.activeRoomId = roomId;
  renderRoomList();
  updateRoomHeader();
  chatState.cursors.delete(roomId);
  loadMessages(true);
}

function updateRoomHeader() {
  if (!chatState.roomNameEl) return;
  const room = chatState.rooms.find((r) => r.id === chatState.activeRoomId) || chatState.rooms.find((r) => r.id === chatState.defaultRoomId);
  if (!room) return;
  chatState.roomNameEl.textContent = room.name;
  if (chatState.roomMetaEl) {
    const type = room.is_direct ? "Direct chat" : "Group chat";
    const membership = room.member_count ? `${room.member_count} members` : "Members updating";
    chatState.roomMetaEl.textContent = `${type} • ${membership}`;
  }
}

function initChatManager() {
  if (!chatState.manageOverlay) return;
  const trigger = document.querySelector("[data-chat-manage-trigger]");
  const close = document.querySelector("[data-chat-manage-close]");
  if (trigger) {
    trigger.addEventListener("click", () => toggleChatManager(true));
  }
  if (close) {
    close.addEventListener("click", () => toggleChatManager(false));
  }
  const overlay = chatState.manageOverlay;
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) {
      toggleChatManager(false);
    }
  });

  const createForm = document.querySelector("[data-chat-create-form]");
  const addMemberForm = document.querySelector("[data-chat-add-member-form]");
  const renameForm = document.querySelector("[data-chat-rename-form]");
  if (createForm) {
    createForm.addEventListener("submit", handleCreateRoom);
  }
  if (addMemberForm) {
    addMemberForm.addEventListener("submit", handleAddMember);
  }
  if (renameForm) {
    renameForm.addEventListener("submit", handleRoomSettingsUpdate);
  }

  const roomSelect = document.querySelector("[data-chat-room-select]");
  if (roomSelect) {
    roomSelect.addEventListener("change", (event) => {
      const selected = Number(event.target.value) || null;
      if (selected) {
        loadRoomDetails(selected);
      }
    });
  }
  const memberList = document.querySelector("[data-chat-member-list]");
  if (memberList) {
    memberList.addEventListener("click", (event) => {
      const btn = event.target.closest("button[data-member-id]");
      if (!btn) return;
      const roomId = Number(document.querySelector("[data-chat-room-select]")?.value);
      const memberId = Number(btn.dataset.memberId);
      if (roomId && memberId) {
        removeMember(roomId, memberId);
      }
    });
  }
}

function toggleChatManager(open) {
  if (!chatState.manageOverlay) return;
  if (open) {
    chatState.manageOverlay.hidden = false;
    populateCreateMemberOptions();
    populateRoomSelect();
  } else {
    chatState.manageOverlay.hidden = true;
  }
}

function populateCreateMemberOptions() {
  const select = document.querySelector("[data-chat-create-members]");
  if (!select) return;
  select.innerHTML = "";
  chatState.availableUsers.forEach((user) => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = `${user.name} (${user.role})`;
    select.appendChild(option);
  });
}

function populateRoomSelect() {
  const select = document.querySelector("[data-chat-room-select]");
  const adminSection = document.querySelector("[data-chat-room-admin]");
  if (!select || !adminSection) return;
  const manageable = chatState.rooms.filter((room) => room.can_manage);
  if (!manageable.length) {
    adminSection.hidden = true;
    return;
  }
  adminSection.hidden = false;
  select.innerHTML = "";
  manageable.forEach((room) => {
    const option = document.createElement("option");
    option.value = room.id;
    option.textContent = room.name;
    select.appendChild(option);
  });
  const firstRoom = Number(select.value) || manageable[0].id;
  select.value = String(firstRoom);
  loadRoomDetails(firstRoom);
}

function syncManagerOptions() {
  if (!chatState.isAdmin || chatState.manageOverlay?.hidden !== false) return;
  populateCreateMemberOptions();
  populateRoomSelect();
}

async function handleCreateRoom(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const feedback = document.querySelector("[data-chat-create-feedback]");
  const formData = new FormData(form);
  const name = formData.get("name")?.toString().trim();
  if (!name) return;
  const memberIds = Array.from(formData.getAll("members")).map((id) => Number(id));
  const payload = {
    name,
    member_ids: memberIds,
    settings: {
      allow_media: formData.get("allow_media") !== null,
      allow_mentions: formData.get("allow_mentions") !== null,
      allow_replies: formData.get("allow_replies") !== null,
    },
  };
  try {
    const res = await fetch("/api/chat/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "Unable to create chat");
    }
    form.reset();
    setFeedback(feedback, "Group chat created");
    await loadRooms({ includeUsers: chatState.isAdmin });
  } catch (err) {
    setFeedback(feedback, err.message || "Unable to create chat", true);
  }
}

async function loadRoomDetails(roomId) {
  try {
    const url = new URL(`/api/chat/rooms/${roomId}`, window.location.origin);
    url.searchParams.set("include_members", "1");
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    renderRoomAdmin(data);
  } catch (err) {
    console.error("room detail load failed", err);
  }
}

function renderRoomAdmin(payload) {
  const room = payload.room;
  const members = payload.members || [];
  const renameForm = document.querySelector("[data-chat-rename-form]");
  const addMemberForm = document.querySelector("[data-chat-add-member-form]");
  const memberList = document.querySelector("[data-chat-member-list]");
  if (renameForm) {
    const nameInput = renameForm.querySelector("input[name='name']");
    if (nameInput && room) {
      nameInput.value = room.name;
      renameForm.dataset.roomId = room.id;
    }
    const settings = renameForm.querySelector(".chat-manager__settings");
    if (settings) {
      settings.querySelectorAll("input[type='checkbox']").forEach((input) => {
        const key = input.name;
        input.checked = room.settings?.[key] !== false;
      });
    }
    renameForm.hidden = room.is_system;
  }
  if (addMemberForm) {
    addMemberForm.dataset.roomId = room.id;
    addMemberForm.hidden = room.is_system;
    const select = addMemberForm.querySelector("[data-chat-add-member-options]");
    if (select) {
      select.innerHTML = "";
      chatState.availableUsers
        .filter((user) => !members.some((member) => member.id === user.id))
        .forEach((user) => {
          const option = document.createElement("option");
          option.value = user.id;
          option.textContent = `${user.name} (${user.role})`;
          select.appendChild(option);
        });
    }
  }
  if (memberList) {
    memberList.innerHTML = "";
    members.forEach((member) => {
      const row = document.createElement("div");
      row.className = "chat-member";
      const meta = document.createElement("div");
      meta.innerHTML = `<strong>${member.name}</strong> <span>${member.role}${member.is_moderator ? " • Moderator" : ""}</span>`;
      row.appendChild(meta);
      if (!room.is_system) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.memberId = member.id;
        button.textContent = "Remove";
        row.appendChild(button);
      }
      memberList.appendChild(row);
    });
  }
}

async function handleRoomSettingsUpdate(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const roomId = Number(form.dataset.roomId);
  if (!roomId) return;
  const feedback = document.querySelector("[data-chat-room-feedback]");
  const formData = new FormData(form);
  const payload = {
    name: formData.get("name")?.toString().trim() || undefined,
    settings: {
      allow_media: formData.get("allow_media") !== null,
      allow_mentions: formData.get("allow_mentions") !== null,
      allow_replies: formData.get("allow_replies") !== null,
    },
  };
  try {
    const res = await fetch(`/api/chat/rooms/${roomId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Unable to update room");
    }
    setFeedback(feedback, "Room updated");
    await loadRooms({ includeUsers: chatState.isAdmin });
    await loadRoomDetails(roomId);
  } catch (err) {
    setFeedback(feedback, err.message || "Unable to update room", true);
  }
}

async function handleAddMember(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const roomId = Number(form.dataset.roomId);
  if (!roomId) return;
  const select = form.querySelector("[data-chat-add-member-options]");
  const feedback = document.querySelector("[data-chat-room-feedback]");
  const userId = Number(select?.value);
  if (!userId) return;
  try {
    const res = await fetch(`/api/chat/rooms/${roomId}/members`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_ids: [userId] }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Unable to add member");
    }
    setFeedback(feedback, "Member added");
    await loadRooms({ includeUsers: chatState.isAdmin });
    await loadRoomDetails(roomId);
  } catch (err) {
    setFeedback(feedback, err.message || "Unable to add member", true);
  }
}

async function removeMember(roomId, memberId) {
  const feedback = document.querySelector("[data-chat-room-feedback]");
  try {
    const res = await fetch(`/api/chat/rooms/${roomId}/members/${memberId}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Unable to remove member");
    }
    setFeedback(feedback, "Member removed");
    await loadRooms({ includeUsers: chatState.isAdmin });
    await loadRoomDetails(roomId);
  } catch (err) {
    setFeedback(feedback, err.message || "Unable to remove member", true);
  }
}

function setFeedback(element, message, isError = false) {
  if (!element) return;
  element.textContent = message;
  element.style.color = isError ? "#b91c1c" : "#059669";
  setTimeout(() => {
    element.textContent = "";
    element.style.color = "";
  }, 4000);
}

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

function initChatWidthControl() {
  const root = document.documentElement;
  const shell = document.querySelector("[data-chat-shell]");
  const dockHandle = document.querySelector("[data-chat-dock-resizer]");
  const columnHandle = document.querySelector("[data-chat-column-resizer]");
  if (!shell || (!dockHandle && !columnHandle)) return;

  const dockRange = { min: 460, max: 1100 };
  const sidebarRange = { min: 260, max: 420 };
  const conversationMin = 420;

  let dockValue = clampValue(
    parseInt(localStorage.getItem("chatDockWidth"), 10),
    dockRange.min,
    dockRange.max,
    shell.clientWidth || 720
  );
  let sidebarValue = clampValue(
    parseInt(localStorage.getItem("chatSidebarWidth"), 10),
    sidebarRange.min,
    sidebarRange.max,
    320
  );

  applyDockWidth(dockValue);
  applySidebarWidth(sidebarValue);

  dockHandle?.addEventListener("pointerdown", (event) => {
    const initialDock = dockValue;
    startDrag(event, (delta) => {
      const next = clampValue(initialDock - delta, dockRange.min, dockRange.max);
      applyDockWidth(next);
    });
  });

  columnHandle?.addEventListener("pointerdown", (event) => {
    const initialSidebar = sidebarValue;
    startDrag(event, (delta) => {
      const maxSidebar = Math.min(sidebarRange.max, dockValue - conversationMin);
      const next = clampValue(initialSidebar + delta, sidebarRange.min, Math.max(sidebarRange.min, maxSidebar));
      applySidebarWidth(next);
    });
  });

  function applyDockWidth(value) {
    dockValue = value;
    root.style.setProperty("--chat-dock-width", `${value}px`);
    localStorage.setItem("chatDockWidth", value);
  }

  function applySidebarWidth(value) {
    sidebarValue = value;
    root.style.setProperty("--chat-sidebar-width", `${value}px`);
    localStorage.setItem("chatSidebarWidth", value);
  }

  function startDrag(event, onMove) {
    event.preventDefault();
    const startX = event.clientX;
    const pointerId = event.pointerId;
    const handle = event.currentTarget;
    handle.setPointerCapture(pointerId);

    const moveListener = (moveEvent) => {
      const delta = moveEvent.clientX - startX;
      onMove(delta);
    };

    const upListener = () => {
      handle.releasePointerCapture(pointerId);
      document.removeEventListener("pointermove", moveListener);
      document.removeEventListener("pointerup", upListener);
    };

    document.addEventListener("pointermove", moveListener);
    document.addEventListener("pointerup", upListener);
  }

  function clampValue(value, min, max, fallback = min) {
    const target = Number.isFinite(value) ? value : fallback;
    return Math.max(min, Math.min(max, target));
  }
}

function initialsFromName(name) {
  if (!name) return "?";
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("") || name.slice(0, 2).toUpperCase()
  );
}
