const MAX_ATTACHMENTS = 3;
const SYSTEM_MESSAGE_TYPES = new Set(["SYSTEM", "ROLL_CALL", "BROADCAST"]);

const chatState = {
  interfaces: [],
  buffers: new Map(),
  cursors: new Map(),
  rooms: [],
  availableUsers: [],
  roomDetailCache: new Map(),
  currentMembers: [],
  activeRoomId: null,
  defaultRoomId: null,
  currentUserId: null,
  pollingHandle: null,
  threadListEl: null,
  threadSearchEl: null,
  threadFilterEls: [],
  threadScrollEl: null,
  roomNameEl: null,
  roomMetaEl: null,
  roomPresenceEl: null,
  manageOverlay: null,
  messageWindowEl: null,
  scrollLatestButton: null,
  composerInput: null,
  composerStatusEl: null,
  composerHintEl: null,
  fileInput: null,
  composerAttachments: [],
  composerMentions: new Map(),
  mentionPopover: null,
  mentionOptionsEl: null,
  mentionActiveIndex: 0,
  mentionToken: null,
  mentionCloseTimer: null,
  threadSearchTimer: null,
  mentionOptions: [],
  isAdmin: false,
  roomFilter: "all",
  threadSearchQuery: "",
  shouldStickToBottom: true,
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

async function handleChatSubmit(event, channel) {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form?.querySelector("button[type='submit']");
  const input = form?.querySelector("[data-chat-input]");
  if (!input) return;
  const content = input.value.trim();
  if (!content) {
    updateComposerStatus("Message cannot be empty", true);
    return;
  }
  const roomId = chatState.activeRoomId || chatState.defaultRoomId;
  if (!roomId) return;
  submitButton?.setAttribute("disabled", "disabled");
  updateComposerStatus("Sending…");

  try {
    const attachments = await Promise.all(
      chatState.composerAttachments.map(async (file) => ({
        name: file.name?.slice(0, 160) || "attachment",
        size: file.size,
        type: file.type || "application/octet-stream",
        data: await readFileAsDataURL(file),
      }))
    );
    const mentionIds = collectMentionIdsFromDraft(content);
    const payload = {
      content,
      room_id: roomId,
      mentions: mentionIds,
      attachments,
    };
    const res = await fetch("/api/chat/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || "Unable to send message");
    }
    input.value = "";
    chatState.composerAttachments = [];
    chatState.composerMentions.clear();
    if (chatState.fileInput) {
      chatState.fileInput.value = "";
    }
    updateComposerStatus("");
    hideMentionPopover();
    await loadMessages(true);
  } catch (err) {
    console.error("chat send failed", err);
    updateComposerStatus(err.message || "Unable to send message", true);
  } finally {
    submitButton?.removeAttribute("disabled");
  }
}

function renderMessages(container, roomId) {
  if (!container) return;
  const buffer = chatState.buffers.get(roomId) || [];
  container.innerHTML = "";
  if (!buffer.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No messages yet. Start the conversation.";
    container.appendChild(empty);
    if (chatState.scrollLatestButton) {
      chatState.scrollLatestButton.hidden = true;
    }
    return;
  }

  const fragment = document.createDocumentFragment();
  buffer.forEach((msg) => {
    const isSystem = SYSTEM_MESSAGE_TYPES.has((msg.message_type || "").toUpperCase());
    const isSelf = msg.user_id === chatState.currentUserId;
    const mentions = Array.isArray(msg.metadata?.mentions) ? msg.metadata.mentions : [];
    const mentionsCurrentUser = mentions.some((mention) => mention.id === chatState.currentUserId);

    const row = document.createElement("div");
    row.className = "message-row";
    if (isSelf) row.classList.add("message-row--self");
    if (isSystem) row.classList.add("message-row--system");
    if (mentionsCurrentUser) row.classList.add("message-row--mention");

    if (!isSystem) {
      const avatar = document.createElement("div");
      avatar.className = "message-avatar";
      avatar.textContent = initialsFromName(msg.user_name);
      row.appendChild(avatar);
    }

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    if (!isSystem) {
      const author = document.createElement("p");
      author.className = "message-author";
      author.textContent = msg.user_name || `User ${msg.user_id}`;
      bubble.appendChild(author);
    }

    const body = document.createElement("p");
    body.className = "message-body";
    body.innerHTML = formatMessageBody(msg.content, mentions);
    bubble.appendChild(body);

    const attachments = Array.isArray(msg.metadata?.attachments) ? msg.metadata.attachments : [];
    if (attachments.length) {
      const attachmentList = document.createElement("div");
      attachmentList.className = "message-attachments";
      attachments.forEach((file, index) => {
        if (!file?.data) return;
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = `Download ${file.name || `attachment-${index + 1}`}`;
        button.addEventListener("click", () => downloadAttachment(file));
        attachmentList.appendChild(button);
      });
      bubble.appendChild(attachmentList);
    }

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = formatTimestamp(msg.created_at);
    bubble.appendChild(meta);

    row.appendChild(bubble);
    fragment.appendChild(row);
  });

  container.appendChild(fragment);
  if (chatState.shouldStickToBottom) {
    scrollToLatest();
  }
}


function formatMessageBody(content, mentions = []) {
  let output = escapeHtml(content || "");
  if (!output) return "";
  if (Array.isArray(mentions)) {
    mentions.forEach((mention) => {
      if (!mention?.name) return;
      const pattern = new RegExp(`@${escapeRegExp(mention.name)}`, "gi");
      output = output.replace(
        pattern,
        `<span class="mention-chip">@${escapeHtml(mention.name)}</span>`
      );
    });
  }
  return output;
}

function downloadAttachment(file) {
  if (!file?.data) return;
  const link = document.createElement("a");
  link.href = file.data;
  link.download = file.name || "attachment";
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
  initChatConversationUI();
  initChatRooms();
  if (chatState.interfaces.some((iface) => iface.channel === "team" || iface.channel === "room")) {
    startChatPolling();
  }
});

function initLegacyInterfaces() {
  // Placeholder to maintain compatibility with legacy markup; no-op by default.
}

function initChatConversationUI() {
  chatState.messageWindowEl = document.querySelector("[data-chat-messages='room']");
  chatState.scrollLatestButton = document.querySelector("[data-chat-scroll-latest]");
  chatState.composerInput = document.querySelector("[data-chat-input]");
  chatState.composerStatusEl = document.querySelector("[data-chat-composer-status]");
  chatState.composerHintEl = document.querySelector("[data-chat-composer-hint]");
  chatState.fileInput = document.querySelector("[data-chat-file-input]");
  chatState.mentionPopover = document.querySelector("[data-mention-popover]");
  chatState.mentionOptionsEl = document.querySelector("[data-mention-options]");

  if (chatState.messageWindowEl) {
    chatState.messageWindowEl.addEventListener("scroll", handleMessageScroll, { passive: true });
  }
  if (chatState.scrollLatestButton) {
    chatState.scrollLatestButton.addEventListener("click", () => scrollToLatest(true));
  }
  if (chatState.fileInput) {
    chatState.fileInput.addEventListener("change", handleFileSelection);
  }
  if (chatState.composerInput) {
    chatState.composerInput.addEventListener("input", handleComposerInput);
    chatState.composerInput.addEventListener("keydown", handleComposerKeydown);
  }
  const mentionTrigger = document.querySelector("[data-chat-mention-trigger]");
  mentionTrigger?.addEventListener("click", (event) => {
    event.preventDefault();
    toggleMentionPopover();
  });
}

function initChatRooms() {
  chatState.threadListEl = document.querySelector("[data-chat-thread-list]");
  chatState.threadSearchEl = document.querySelector("[data-chat-thread-search]");
  chatState.threadFilterEls = Array.from(document.querySelectorAll("[data-chat-thread-filter]"));
  chatState.threadScrollEl = document.querySelector("[data-chat-thread-scroll]");
  chatState.roomNameEl = document.querySelector("[data-chat-room-name]");
  chatState.roomMetaEl = document.querySelector("[data-chat-room-meta]");
  chatState.roomPresenceEl = document.querySelector("[data-chat-room-presence]");
  chatState.roomActionButtons = Array.from(document.querySelectorAll("[data-chat-room-action]"));
  chatState.manageOverlay = document.querySelector("[data-chat-manager]");
  const dock = document.getElementById("chat-dock");
  if (dock?.dataset?.userRole) {
    chatState.isAdmin = ["OWNER", "ADMIN"].includes(dock.dataset.userRole);
  }
  if (dock?.dataset?.userId) {
    const id = Number(dock.dataset.userId);
    if (Number.isFinite(id)) {
      chatState.currentUserId = id;
    }
  }
  if (chatState.threadSearchEl) {
    chatState.threadSearchEl.addEventListener("input", handleThreadSearchInput);
  }
  if (chatState.threadFilterEls.length) {
    chatState.threadFilterEls.forEach((button) => {
      button.addEventListener("click", () => setThreadFilter(button.dataset.chatThreadFilter));
    });
  }
  document.addEventListener("click", handleGlobalClick, true);
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
    const query = chatState.threadSearchQuery.trim();
    if (query) {
      url.searchParams.set("search", query);
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
    await hydrateRoomMembers(chatState.activeRoomId);
    updateRoomHeader();
    if (chatState.activeRoomId) {
      chatState.cursors.delete(chatState.activeRoomId);
      await loadMessages(true);
    }
    syncManagerOptions();
  } catch (err) {
    console.error("chat rooms load failed", err);
  }
}

function renderRoomList() {
  if (!chatState.threadListEl) return;
  chatState.threadListEl.innerHTML = "";
  const rooms = chatState.rooms.filter((room) => {
    if (chatState.roomFilter === "unread") return (room.unread_count || 0) > 0;
    if (chatState.roomFilter === "groups") return !room.is_direct;
    if (chatState.roomFilter === "direct") return room.is_direct;
    return true;
  });
  if (!rooms.length) {
    const li = document.createElement("li");
    li.className = "chat-panel-empty";
    li.textContent = chatState.threadSearchQuery ? "No chats match your search" : "No chats yet";
    chatState.threadListEl.appendChild(li);
    return;
  }
  rooms.forEach((room) => {
    const li = document.createElement("li");
    li.className = "chat-thread";
    if (room.id === chatState.activeRoomId) {
      li.classList.add("active");
    }
    li.tabIndex = 0;
    li.addEventListener("click", () => setActiveRoom(room.id));
    li.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setActiveRoom(room.id);
      }
    });

    const avatar = document.createElement("div");
    avatar.className = "chat-thread__avatar";
    avatar.textContent = initialsFromName(room.name);

    const body = document.createElement("div");
    body.className = "chat-thread__body";
    const titleRow = document.createElement("div");
    titleRow.className = "chat-thread__title";
    const title = document.createElement("strong");
    title.textContent = room.name;
    titleRow.appendChild(title);
    const pill = document.createElement("span");
    pill.className = "chat-thread__pill";
    pill.textContent = room.is_direct ? "Direct" : "Group";
    titleRow.appendChild(pill);
    body.appendChild(titleRow);

    const preview = document.createElement("p");
    preview.className = "chat-thread__preview";
    if (room.last_message) {
      const author = room.last_message.author || "";
      const content = truncateContent(room.last_message.content || "");
      preview.textContent = author ? `${author}: ${content}` : content;
    } else {
      preview.textContent = "No messages yet";
    }
    body.appendChild(preview);

    const meta = document.createElement("div");
    meta.className = "chat-thread__meta";
    const timestamp = document.createElement("span");
    timestamp.textContent = formatRelativeTime(room.last_activity);
    meta.appendChild(timestamp);
    if (room.unread_count > 0) {
      const badge = document.createElement("span");
      badge.className = "chat-thread__badge";
      badge.textContent = room.unread_count > 9 ? "9+" : room.unread_count;
      meta.appendChild(badge);
    }

    li.append(avatar, body, meta);
    chatState.threadListEl.appendChild(li);
  });
}

async function setActiveRoom(roomId) {
  if (!roomId || chatState.activeRoomId === roomId) {
    chatState.cursors.delete(roomId);
    await loadMessages(true);
    return;
  }
  chatState.activeRoomId = roomId;
  renderRoomList();
  await hydrateRoomMembers(roomId);
  updateRoomHeader();
  chatState.cursors.delete(roomId);
  await loadMessages(true);
}

function updateRoomHeader() {
  if (!chatState.roomNameEl) return;
  const room = chatState.rooms.find((r) => r.id === chatState.activeRoomId) || chatState.rooms.find((r) => r.id === chatState.defaultRoomId);
  if (!room) return;
  chatState.roomNameEl.textContent = room.name;
  if (chatState.roomMetaEl) {
    const type = room.is_direct ? "Direct chat" : "Group chat";
    const membership = room.member_count ? `${room.member_count} members` : "Membership updating";
    chatState.roomMetaEl.textContent = `${type} • ${membership}`;
  }
  if (chatState.roomPresenceEl) {
    const chips = chatState.currentMembers.slice(0, 4).map((member) => `<span>${escapeHtml(member.name)}</span>`);
    chatState.roomPresenceEl.innerHTML = chips.length ? chips.join(" • ") : "";
  }
  const canManage = Boolean(room.can_manage);
  if (chatState.roomActionButtons?.length) {
    chatState.roomActionButtons.forEach((button) => {
      const action = button.dataset.chatRoomAction;
      if (action === "more") {
        button.disabled = false;
        return;
      }
      button.disabled = !canManage;
    });
  }
}

function handleThreadSearchInput(event) {
  const value = event?.target?.value || "";
  chatState.threadSearchQuery = value;
  if (chatState.threadSearchTimer) {
    clearTimeout(chatState.threadSearchTimer);
  }
  chatState.threadSearchTimer = setTimeout(() => {
    loadRooms({ includeUsers: chatState.isAdmin });
  }, 250);
}

function setThreadFilter(filterValue = "all") {
  const allowed = new Set(["all", "unread", "direct", "groups"]);
  chatState.roomFilter = allowed.has(filterValue) ? filterValue : "all";
  if (chatState.threadFilterEls?.length) {
    chatState.threadFilterEls.forEach((button) => {
      button.classList.toggle("active", button.dataset.chatThreadFilter === chatState.roomFilter);
    });
  }
  if (chatState.threadScrollEl) {
    chatState.threadScrollEl.scrollTo({ top: 0, behavior: "smooth" });
  }
  renderRoomList();
}

async function hydrateRoomMembers(roomId) {
  if (!roomId) {
    chatState.currentMembers = [];
    return;
  }
  if (chatState.roomDetailCache.has(roomId)) {
    const cached = chatState.roomDetailCache.get(roomId);
    chatState.currentMembers = cached.members || [];
    return;
  }
  try {
    const url = new URL(`/api/chat/rooms/${roomId}`, window.location.origin);
    url.searchParams.set("include_members", "1");
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    chatState.roomDetailCache.set(roomId, data);
    chatState.currentMembers = data.members || [];
  } catch (err) {
    console.error("room members hydrate failed", err);
  }
}

function truncateContent(text, limit = 120) {
  if (!text) return "";
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= limit) return clean;
  return `${clean.slice(0, limit - 1)}…`;
}

function formatRelativeTime(value) {
  if (!value) return "";
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return "";
  const diffMs = target.getTime() - Date.now();
  const diffSeconds = Math.round(diffMs / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const units = [
    { limit: 60, divisor: 1, unit: "second" },
    { limit: 3600, divisor: 60, unit: "minute" },
    { limit: 86400, divisor: 3600, unit: "hour" },
    { limit: 604800, divisor: 86400, unit: "day" },
    { limit: 2419200, divisor: 604800, unit: "week" },
  ];
  const absSeconds = Math.abs(diffSeconds);
  for (const range of units) {
    if (absSeconds < range.limit) {
      const valueRounded = Math.round(diffSeconds / range.divisor);
      return formatter.format(valueRounded, range.unit);
    }
  }
  const months = Math.round(diffSeconds / 2629800);
  if (Math.abs(months) < 12) {
    return formatter.format(months, "month");
  }
  const years = Math.round(diffSeconds / 31557600);
  return formatter.format(years, "year");
}

function escapeHtml(value) {
  if (!value) return "";
  return value.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return char;
    }
  });
}

function handleGlobalClick(event) {
  if (!chatState.mentionPopover || chatState.mentionPopover.hidden) return;
  const target = event.target;
  const isPopover = chatState.mentionPopover.contains(target);
  const isComposer = chatState.composerInput && chatState.composerInput.contains(target);
  const isTrigger = target.closest?.("[data-chat-mention-trigger]");
  if (!isPopover && !isComposer && !isTrigger) {
    hideMentionPopover();
  }
}

function hideMentionPopover() {
  if (!chatState.mentionPopover) return;
  chatState.mentionPopover.hidden = true;
  chatState.mentionOptions = [];
  chatState.mentionActiveIndex = 0;
  chatState.mentionToken = null;
}

function handleMessageScroll() {
  if (!chatState.messageWindowEl) return;
  const { scrollTop, scrollHeight, clientHeight } = chatState.messageWindowEl;
  const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);
  chatState.shouldStickToBottom = distanceFromBottom < 120;
  if (chatState.scrollLatestButton) {
    chatState.scrollLatestButton.hidden = chatState.shouldStickToBottom;
  }
}

function scrollToLatest(animate = false) {
  if (!chatState.messageWindowEl) return;
  chatState.shouldStickToBottom = true;
  const behavior = animate ? "smooth" : "auto";
  chatState.messageWindowEl.scrollTo({ top: chatState.messageWindowEl.scrollHeight, behavior });
  if (chatState.scrollLatestButton) {
    chatState.scrollLatestButton.hidden = true;
  }
}

function handleComposerInput() {
  updateComposerStatus();
  updateMentionSuggestions();
}

function handleComposerKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    event.currentTarget?.form?.requestSubmit();
  }
  if (event.key === "Escape" && !chatState.mentionPopover?.hidden) {
    hideMentionPopover();
  }
}

function handleFileSelection(event) {
  const files = Array.from(event.target?.files || []);
  if (!files.length) {
    chatState.composerAttachments = [];
    updateComposerStatus();
    return;
  }
  chatState.composerAttachments = files.slice(0, MAX_ATTACHMENTS);
  if (files.length > MAX_ATTACHMENTS) {
    updateComposerStatus(`Only ${MAX_ATTACHMENTS} attachments are supported.`, true);
  } else {
    updateComposerStatus();
  }
}

function updateComposerStatus(message = "", isError = false) {
  if (!chatState.composerStatusEl) return;
  if (message) {
    chatState.composerStatusEl.textContent = message;
    chatState.composerStatusEl.classList.toggle("is-error", Boolean(isError));
    return;
  }
  chatState.composerStatusEl.classList.remove("is-error");
  const attachmentCount = chatState.composerAttachments.length;
  if (attachmentCount) {
    chatState.composerStatusEl.textContent = `${attachmentCount} attachment${attachmentCount > 1 ? "s" : ""} ready`;
  } else {
    chatState.composerStatusEl.textContent = "";
  }
}

function toggleMentionPopover() {
  if (!chatState.mentionPopover || !chatState.mentionOptionsEl) return;
  const shouldShow = chatState.mentionPopover.hidden;
  if (!shouldShow) {
    hideMentionPopover();
    return;
  }
  chatState.mentionActiveIndex = 0;
  if (!chatState.availableUsers.length) {
    chatState.mentionOptionsEl.innerHTML = "<li class='mention-option muted'>No teammates available</li>";
  } else {
    renderMentionOptions(chatState.availableUsers.slice(0, 8));
  }
  positionMentionPopover();
  chatState.mentionPopover.hidden = false;
}

function renderMentionOptions(options) {
  if (!chatState.mentionOptionsEl) return;
  chatState.mentionOptions = options;
  chatState.mentionOptionsEl.innerHTML = "";
  options.forEach((user, index) => {
    const li = document.createElement("li");
    li.className = "mention-option";
    if (index === chatState.mentionActiveIndex) {
      li.classList.add("is-active");
    }
    li.textContent = user.name;
    li.dataset.userId = user.id;
    li.addEventListener("click", () => insertMention(user));
    chatState.mentionOptionsEl.appendChild(li);
  });
}

function insertMention(user) {
  if (!chatState.composerInput || !user) return;
  const cursorPos = chatState.composerInput.selectionStart || chatState.composerInput.value.length;
  const value = chatState.composerInput.value;
  const before = value.slice(0, cursorPos);
  const after = value.slice(cursorPos);
  const token = `@${user.name} `;
  chatState.composerInput.value = `${before}${token}${after}`;
  chatState.composerMentions.set(user.id, user);
  hideMentionPopover();
  chatState.composerInput.focus();
  handleComposerInput();
}

function updateMentionSuggestions() {
  if (!chatState.composerInput || !chatState.availableUsers.length || !chatState.mentionOptionsEl) return;
  const context = extractMentionToken(chatState.composerInput.value, chatState.composerInput.selectionStart || 0);
  if (!context) {
    hideMentionPopover();
    return;
  }
  chatState.mentionToken = context.token;
  const keyword = context.token.toLowerCase();
  chatState.mentionActiveIndex = 0;
  const matches = chatState.availableUsers.filter((user) =>
    user.name.toLowerCase().includes(keyword)
  );
  if (!chatState.mentionPopover) return;
  positionMentionPopover();
  chatState.mentionPopover.hidden = false;
  if (!matches.length) {
    chatState.mentionOptionsEl.innerHTML = "<li class='mention-option muted'>No matches</li>";
    return;
  }
  renderMentionOptions(matches.slice(0, 8));
}

function extractMentionToken(value, cursor) {
  const uptoCursor = value.slice(0, cursor);
  const atIndex = uptoCursor.lastIndexOf("@");
  if (atIndex === -1) return null;
  if (atIndex > 0 && !/\s/.test(uptoCursor.charAt(atIndex - 1))) {
    return null;
  }
  const token = uptoCursor.slice(atIndex + 1);
  if (token.includes(" ") || token.includes("\n") || token.includes("\t")) {
    return null;
  }
  if (token.length > 32) return null;
  return { token, start: atIndex };
}

function positionMentionPopover() {
  if (!chatState.mentionPopover) return;
  const composerRect = chatState.composerInput?.getBoundingClientRect();
  if (!composerRect) return;
  const top = composerRect.top - 180 + window.scrollY;
  const left = composerRect.left + 20 + window.scrollX;
  chatState.mentionPopover.style.top = `${Math.max(top, 0)}px`;
  chatState.mentionPopover.style.left = `${Math.max(left, 0)}px`;
}

function collectMentionIdsFromDraft(content) {
  if (!content) return [];
  const normalized = content.toLowerCase();
  return Array.from(chatState.composerMentions.entries())
    .filter(([, user]) => user?.name && normalized.includes(`@${user.name.toLowerCase()}`))
    .map(([id]) => id);
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("Unable to read file"));
    reader.readAsDataURL(file);
  });
}

function initChatManager() {
  if (!chatState.manageOverlay) return;
  const trigger = document.querySelector("[data-chat-manage-trigger]");
  const close = document.querySelector("[data-chat-manage-close]");
  const deleteButton = document.querySelector("[data-chat-delete-room]");
  if (trigger) {
    trigger.addEventListener("click", () => toggleChatManager(true));
  }
  if (close) {
    close.addEventListener("click", () => toggleChatManager(false));
  }
  if (deleteButton) {
    deleteButton.addEventListener("click", () => {
      const roomId = Number(deleteButton.dataset.roomId);
      if (!roomId) return;
      const roomName = deleteButton.dataset.roomName || "this group";
      const confirmed = window.confirm(`Delete ${roomName}? This cannot be undone.`);
      if (!confirmed) return;
      deleteRoom(roomId);
    });
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
  const deleteButton = document.querySelector("[data-chat-delete-room]");
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
  if (deleteButton) {
    const allowDelete = room && !room.is_system;
    deleteButton.hidden = !allowDelete;
    deleteButton.disabled = !allowDelete;
    deleteButton.dataset.roomId = allowDelete ? room.id : "";
    deleteButton.dataset.roomName = allowDelete ? room.name : "";
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

async function deleteRoom(roomId) {
  const feedback = document.querySelector("[data-chat-room-feedback]");
  try {
    const res = await fetch(`/api/chat/rooms/${roomId}`, {
      method: "DELETE",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "Unable to delete room");
    }
    setFeedback(feedback, "Room deleted");
    await loadRooms({ includeUsers: chatState.isAdmin });
    if (chatState.manageOverlay?.hidden === false) {
      populateRoomSelect();
    }
  } catch (err) {
    setFeedback(feedback, err.message || "Unable to delete room", true);
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

  dockHandle?.addEventListener("pointerdown", (event) => startDrag(event, "dock"));
  columnHandle?.addEventListener("pointerdown", (event) => startDrag(event, "sidebar"));

  function startDrag(event, target) {
    event.preventDefault();
    const startX = typeof event.clientX === "number" ? event.clientX : null;
    if (startX == null) return;
    const handle = event.currentTarget;
    const pointerId = event.pointerId;
    if (handle && typeof handle.setPointerCapture === "function" && Number.isFinite(pointerId)) {
      handle.setPointerCapture(pointerId);
    }
    const initialDock = dockValue;
    const initialSidebar = sidebarValue;

    const handleMove = (moveEvent) => {
      const currentX = typeof moveEvent.clientX === "number" ? moveEvent.clientX : null;
      if (currentX == null) return;
      const delta = currentX - startX;
      if (target === "dock") {
        const next = clampValue(initialDock - delta, dockRange.min, dockRange.max);
        applyDockWidth(next);
        const maxSidebar = Math.max(sidebarRange.min, dockValue - conversationMin);
        if (sidebarValue > maxSidebar) {
          applySidebarWidth(maxSidebar);
        }
      } else {
        const allowedMax = Math.min(sidebarRange.max, dockValue - conversationMin);
        const clampedMax = Math.max(sidebarRange.min, allowedMax);
        const next = clampValue(initialSidebar + delta, sidebarRange.min, clampedMax);
        applySidebarWidth(next);
      }
    };

    const stop = () => {
      if (handle && typeof handle.releasePointerCapture === "function" && Number.isFinite(pointerId)) {
        handle.releasePointerCapture(pointerId);
      }
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }

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
