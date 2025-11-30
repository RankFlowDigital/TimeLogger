const DEVICE_TIMEZONE = "__device__";

function resolveDeviceTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch (err) {
    console.warn("Unable to resolve device timezone", err);
    return "UTC";
  }
}

const dashboardRuntime = (() => {
  const bootstrapEl = document.getElementById("dashboard-state");
  let bootstrapState = null;
  if (bootstrapEl) {
    try {
      bootstrapState = JSON.parse(bootstrapEl.textContent || "{}");
    } catch (err) {
      console.error("Failed to parse dashboard bootstrap", err);
    }
  }

  let state = bootstrapState;
  let displayTimezone = state?.user?.timezone || resolveDeviceTimezone();
  const listeners = new Set();

  const notify = () => {
    if (!state) return;
    listeners.forEach((cb) => {
      try {
        cb(state);
      } catch (err) {
        console.error("dashboard listener failed", err);
      }
    });
  };

  const refresh = async () => {
    try {
      const res = await fetch("/api/dashboard/state");
      if (!res.ok) return;
      state = await res.json();
      notify();
    } catch (err) {
      console.error("dashboard refresh failed", err);
    }
  };

  return {
    hasBootstrap: Boolean(state),
    getState: () => state,
    subscribe: (cb) => {
      if (typeof cb !== "function") return () => undefined;
      listeners.add(cb);
      if (state) {
        cb(state);
      }
      return () => listeners.delete(cb);
    },
    refresh,
    getDisplayTimezone: () => displayTimezone || resolveDeviceTimezone(),
    setDisplayTimezone: (tz) => {
      displayTimezone = tz || null;
      if (state) {
        notify();
      }
    },
  };
})();

window.dashboardRuntime = dashboardRuntime;

const controlStore = {
  buttons: new Map(),
  feedbackEl: null,
  timeout: null,
};
const actionSuccessMessages = {
  "start-work": "Work session started",
  "stop-work": "Work session ended",
  "start-lunch": "Lunch started",
  "end-lunch": "Lunch ended",
  "start-break": "Break started",
  "end-break": "Break ended",
};

const statusTicker = {
  handle: null,
  startAt: null,
  target: null,
  offsetMs: 0,
};
let dashboardRefreshHandle = null;

const rollcallStatusLabels = {
  PENDING: "Awaiting",
  PASSED: "Cleared",
  LATE: "Late",
  MISSED: "Missed",
};

function formatDateTime(value, { includeDate = false } = {}) {
  if (!value) return "--";
  const date = value instanceof Date ? value : new Date(value);
  const options = includeDate
    ? { dateStyle: "medium", timeStyle: "short" }
    : { timeStyle: "short" };
  return formatWithTimezone(date, options);
}

function formatDurationUntil(value) {
  if (!value) return "";
  const target = new Date(value);
  const diff = Math.max(0, Math.floor((target - new Date()) / 1000));
  const minutes = Math.floor(diff / 60);
  const seconds = String(diff % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function toTitleCase(value) {
  if (!value) return "";
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();
}

function initialsFromName(name) {
  if (!name) return "--";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("") || "--";
}

function classifyPresenceStatus(status) {
  const normalized = (status || "OFFLINE").toUpperCase();
  if (normalized === "WORK") {
    return { label: "Working", token: "present" };
  }
  if (normalized === "LUNCH") {
    return { label: "On lunch", token: "break" };
  }
  if (normalized === "SHORT_BREAK") {
    return { label: "On break", token: "break" };
  }
  if (normalized === "OFFLINE") {
    return { label: "Offline", token: "offline" };
  }
  return { label: toTitleCase(normalized) || "Active", token: "present" };
}

function renderStatus(state) {
  const badge = document.querySelector("[data-status-badge]");
  const meta = document.querySelector("[data-status-meta]");
  statusTicker.target = document.querySelector("[data-status-duration]");
  if (!badge || !meta) return;
  const open = state?.open_session;
  const status = open ? open.type : "OFFLINE";
  const since = open ? formatDateTime(open.started_at) : "";
  badge.textContent = status.replace(/_/g, " ");
  badge.dataset.status = status;
  badge.classList.toggle("offline", !open);
  meta.textContent = open ? `Since ${since}` : "No active session";
  if (open) {
    statusTicker.startAt = new Date(open.started_at);
    statusTicker.offsetMs = open.type === "WORK" ? (state?.work_carry_seconds || 0) * 1000 : 0;
    startStatusTicker();
  } else {
    stopStatusTicker();
  }
}

function renderSummary(state) {
  const metrics = state?.summary || {};
  document.querySelectorAll("[data-summary-metric]").forEach((node) => {
    const key = node.getAttribute("data-summary-metric");
    if (!key) return;
    let value = metrics[key];
    if (key === "net_hours" && typeof value === "number") {
      node.textContent = value.toFixed(2);
    } else if (typeof value === "number") {
      node.textContent = value.toLocaleString();
    }
  });
  const netDisplay = document.querySelector("[data-summary-net-hours-display]");
  if (netDisplay) {
    const workMinutes = Number(metrics.work_minutes) || 0;
    const overbreak = Number(metrics.overbreak_minutes) || 0;
    const rollcall = Number(metrics.rollcall_deduction_minutes) || 0;
    const cappedWork = Math.min(480, Math.max(0, workMinutes));
    const netMinutes = Math.max(0, cappedWork - overbreak - rollcall);
    netDisplay.textContent = formatHoursMinutes(netMinutes);
  }
}

function renderActivityLog(state) {
  const log = document.querySelector("[data-activity-log]");
  if (!log) return;
  log.innerHTML = "";
  const sessions = state?.sessions || [];
  sessions
    .slice()
    .reverse()
    .slice(0, 6)
    .forEach((session) => {
      const li = document.createElement("li");
      li.innerHTML = `<span>${formatDateTime(session.started_at, { includeDate: true })}</span>${session.type.replace(/_/g, " ")} • ${session.duration_minutes || 0} mins`;
      log.appendChild(li);
    });
  if (!log.children.length) {
    const li = document.createElement("li");
    li.textContent = "No recorded sessions today";
    log.appendChild(li);
  }
}

function renderRoster(state) {
  const roster = document.querySelector("[data-team-roster]");
  if (!roster) return;
  roster.innerHTML = "";
  (state?.team_roster || []).forEach((member) => {
    const li = document.createElement("li");
    li.className = "presence-member";

    const avatar = document.createElement("span");
    avatar.className = "presence-avatar";
    avatar.textContent = initialsFromName(member.name);

    const meta = document.createElement("div");
    meta.className = "presence-meta";
    const name = document.createElement("strong");
    name.textContent = member.name;
    const details = document.createElement("span");
    const detailParts = [toTitleCase(member.role), member.timezone].filter(Boolean);
    details.textContent = detailParts.join(" • ") || "Role pending";
    meta.append(name, details);

    const indicator = document.createElement("span");
    const presence = classifyPresenceStatus(member.status);
    indicator.className = "presence-state";
    indicator.dataset.state = presence.token;
    indicator.textContent = presence.label;
    if (member.since && presence.token !== "offline") {
      const since = document.createElement("small");
      since.textContent = `since ${formatDateTime(member.since)}`;
      indicator.appendChild(since);
    }

    li.append(avatar, meta, indicator);
    roster.appendChild(li);
  });
  if (!roster.children.length) {
    const li = document.createElement("li");
    li.className = "presence-member muted";
    li.textContent = "No teammates yet";
    roster.appendChild(li);
  }
}

function renderRollCallHistory(state) {
  const list = document.querySelector("[data-rollcall-log]");
  if (!list) return;
  list.innerHTML = "";
  const entries = state?.org_roll_call_history || [];
  entries.forEach((rc) => {
    const li = document.createElement("li");
    li.className = "rollcall-entry";
    if (rc.result === "PENDING") {
      li.classList.add("rollcall-entry--pending");
    }
    const meta = document.createElement("div");
    meta.className = "rollcall-meta";
    const name = document.createElement("strong");
    name.textContent = rc.user_name;
    const stamp = document.createElement("span");
    stamp.textContent = formatDateTime(rc.triggered_at, { includeDate: true });
    meta.append(name, stamp);

    const status = document.createElement("span");
    const resultKey = (rc.result || "UNKNOWN").toUpperCase();
    status.className = "rollcall-status";
    status.dataset.state = resultKey;
    if (resultKey === "PENDING" && rc.deadline_at) {
      status.textContent = `Awaiting • ${formatDurationUntil(rc.deadline_at)}`;
    } else {
      status.textContent = rollcallStatusLabels[resultKey] || resultKey.toLowerCase();
    }

    li.append(meta, status);
    list.appendChild(li);
  });
  if (!list.children.length) {
    const li = document.createElement("li");
    li.textContent = "No recent roll calls";
    list.appendChild(li);
  }
}

function renderTimezoneLabel() {
  const label = document.querySelector("[data-timezone-display]");
  if (!label) return;
  label.textContent = dashboardRuntime.getDisplayTimezone();
}

function startClock() {
  const clock = document.querySelector("[data-live-clock]");
  if (!clock) return;
  const tick = () => {
    clock.textContent = formatWithTimezone(new Date(), { timeStyle: "short" });
  };
  tick();
  setInterval(tick, 1000);
}

function populateTimezoneOptions(select, { includeDevice } = {}) {
  if (!select) return;
  const existing = new Set();
  select.innerHTML = "";
  if (includeDevice) {
    const opt = document.createElement("option");
    opt.value = DEVICE_TIMEZONE;
    opt.textContent = `Device (${resolveDeviceTimezone()})`;
    select.appendChild(opt);
  }
  let zones = [];
  if (typeof Intl.supportedValuesOf === "function") {
    try {
      zones = Intl.supportedValuesOf("timeZone");
    } catch (err) {
      console.warn("supportedValuesOf failed", err);
    }
  }
  if (!zones.length) {
    zones = [
      "UTC",
      "America/New_York",
      "America/Chicago",
      "America/Los_Angeles",
      "Europe/London",
      "Europe/Paris",
      "Asia/Singapore",
      "Asia/Manila",
      "Australia/Sydney",
    ];
  }
  zones.forEach((tz) => {
    if (existing.has(tz)) return;
    existing.add(tz);
    const opt = document.createElement("option");
    opt.value = tz;
    opt.textContent = tz;
    select.appendChild(opt);
  });
}

function initTimezoneControls() {
  const select = document.querySelector("[data-timezone-select]");
  if (!select) return;
  populateTimezoneOptions(select, { includeDevice: true });
  const inviteSelects = document.querySelectorAll("[data-invite-timezone]");
  inviteSelects.forEach((el) => populateTimezoneOptions(el));
  const current = dashboardRuntime.getDisplayTimezone();
  select.value = current && Array.from(select.options).some((opt) => opt.value === current)
    ? current
    : DEVICE_TIMEZONE;
  select.addEventListener("change", () => {
    const value = select.value === DEVICE_TIMEZONE ? null : select.value;
    dashboardRuntime.setDisplayTimezone(value);
    renderTimezoneLabel();
  });
  const reset = document.querySelector("[data-timezone-reset]");
  reset?.addEventListener("click", () => {
    select.value = DEVICE_TIMEZONE;
    dashboardRuntime.setDisplayTimezone(null);
    renderTimezoneLabel();
  });
  const feedback = document.querySelector("[data-timezone-feedback]");
  const save = document.querySelector("[data-timezone-save]");
  save?.addEventListener("click", async () => {
    const value = select.value === DEVICE_TIMEZONE ? null : select.value;
    try {
      const res = await fetch("/api/users/timezone", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timezone: value }),
      });
      if (!res.ok) throw new Error("Timezone save failed");
      const data = await res.json();
      dashboardRuntime.setDisplayTimezone(data.timezone);
      renderTimezoneLabel();
      if (feedback) feedback.textContent = "Preference saved";
    } catch (err) {
      console.error(err);
      if (feedback) feedback.textContent = "Unable to save preference";
    }
    setTimeout(() => {
      if (feedback) feedback.textContent = "";
    }, 4000);
  });
  renderTimezoneLabel();
}

function wireSessionButtons() {
  const actionButtons = document.querySelectorAll("[data-action]");
  if (!actionButtons.length) return;
  controlStore.feedbackEl = document.querySelector("[data-control-feedback]");
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
      btn.disabled = true;
      btn.dataset.loading = "true";
      try {
        const payload = action === "start-work" ? { task_description: "" } : undefined;
        const res = await fetch(`/api/sessions/${endpoint}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload ? JSON.stringify(payload) : undefined,
        });
        if (!res.ok) {
          let message = "Unable to process action";
          try {
            const data = await res.json();
            message = data?.detail || data?.error || message;
          } catch (err) {
            console.warn("Failed to parse error payload", err);
          }
          throw new Error(message);
        }
        await dashboardRuntime.refresh();
        showControlFeedback(actionSuccessMessages[action] || "Session updated", "success");
      } catch (err) {
        console.error(err);
        showControlFeedback(err.message || "Unable to update session", "error");
      } finally {
        btn.disabled = false;
        delete btn.dataset.loading;
        updateControlStates(dashboardRuntime.getState());
      }
    });
    const action = btn.getAttribute("data-action");
    if (action) {
      controlStore.buttons.set(action, btn);
    }
  });
  updateControlStates(dashboardRuntime.getState());
}

function hydrateDashboard() {
  if (!dashboardRuntime.hasBootstrap) return;
  dashboardRuntime.subscribe((state) => {
    renderStatus(state);
    renderSummary(state);
    renderActivityLog(state);
    renderRoster(state);
    renderRollCallHistory(state);
    renderTimezoneLabel();
    updateControlStates(state);
  });
  wireSessionButtons();
  startClock();
}

function startDashboardAutoRefresh() {
  if (dashboardRefreshHandle || !dashboardRuntime.hasBootstrap) return;
  dashboardRefreshHandle = setInterval(() => {
    dashboardRuntime.refresh();
  }, 15000);
}

document.addEventListener("DOMContentLoaded", () => {
  hydrateDashboard();
  startDashboardAutoRefresh();
  initProfilePage();
  initTimezoneControls();
});

function startStatusTicker() {
  if (!statusTicker.target || !statusTicker.startAt) {
    stopStatusTicker();
    return;
  }
  updateStatusDuration();
  if (!statusTicker.handle) {
    statusTicker.handle = setInterval(updateStatusDuration, 1000);
  }
}

function stopStatusTicker() {
  if (statusTicker.handle) {
    clearInterval(statusTicker.handle);
  }
  statusTicker.handle = null;
  statusTicker.startAt = null;
  statusTicker.offsetMs = 0;
  if (statusTicker.target) {
    statusTicker.target.textContent = "";
  }
}

function updateStatusDuration() {
  if (!statusTicker.target || !statusTicker.startAt) return;
  const now = new Date();
  const diffMs = now - statusTicker.startAt;
  const totalMs = diffMs + (statusTicker.offsetMs || 0);
  if (totalMs < 0) {
    statusTicker.target.textContent = "• 00:00:00";
    return;
  }
  const totalSeconds = Math.floor(totalMs / 1000);
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  statusTicker.target.textContent = `• ${hours}:${minutes}:${seconds}`;
}

function showControlFeedback(message, variant = "info") {
  const el = controlStore.feedbackEl;
  if (!el) return;
  if (controlStore.timeout) {
    clearTimeout(controlStore.timeout);
    controlStore.timeout = null;
  }
  el.textContent = message || "";
  if (message) {
    el.dataset.variant = variant;
    controlStore.timeout = setTimeout(() => {
      el.textContent = "";
      el.dataset.variant = "";
    }, 5000);
  } else {
    el.dataset.variant = "";
  }
}

function setButtonAvailability(action, enabled) {
  const btn = controlStore.buttons.get(action);
  if (!btn || btn.dataset.loading === "true") return;
  btn.disabled = !enabled;
}

function updateControlStates(state) {
  if (!state) return;
  const openType = state?.open_session?.type || null;
  const hasOpen = Boolean(openType);
  setButtonAvailability("start-work", !hasOpen);
  setButtonAvailability("stop-work", openType === "WORK");
  setButtonAvailability("start-lunch", openType === "WORK");
  setButtonAvailability("end-lunch", openType === "LUNCH");
  setButtonAvailability("start-break", openType === "WORK");
  setButtonAvailability("end-break", openType === "SHORT_BREAK");
}

function formatWithTimezone(date, baseOptions) {
  const options = baseOptions || {};
  try {
    return new Intl.DateTimeFormat(undefined, {
      ...options,
      timeZone: dashboardRuntime.getDisplayTimezone(),
    }).format(date);
  } catch (err) {
    console.error("format failed", err);
    return date.toLocaleString();
  }
}

function formatHoursMinutes(totalMinutes) {
  const safeMinutes = Math.max(0, Math.round(totalMinutes));
  const hours = Math.floor(safeMinutes / 60);
  const minutes = String(safeMinutes % 60).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function initProfilePage() {
  const root = document.querySelector("[data-profile-page]");
  if (!root) return;
  const preferredTimezone = root.getAttribute("data-user-timezone");
  dashboardRuntime.setDisplayTimezone(preferredTimezone || null);
  wirePasswordForm(root);
  wireReportForm(root);
}

function wirePasswordForm(root) {
  const form = root.querySelector("[data-password-form]");
  if (!form) return;
  const feedback = root.querySelector("[data-password-feedback]");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setFormFeedback(feedback, "");
    const formData = new FormData(form);
    const currentPassword = (formData.get("current_password") || "").trim();
    const newPassword = (formData.get("new_password") || "").trim();
    const confirmPassword = (formData.get("confirm_password") || "").trim();
    if (!currentPassword || !newPassword) {
      setFormFeedback(feedback, "Please provide both current and new passwords.", "error");
      return;
    }
    if (newPassword !== confirmPassword) {
      setFormFeedback(feedback, "New passwords do not match.", "error");
      return;
    }
    const submitBtn = form.querySelector("button[type='submit']");
    if (submitBtn) submitBtn.disabled = true;
    try {
      const res = await fetch("/api/users/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!res.ok) {
        const message = await extractErrorMessage(res, "Unable to update password");
        throw new Error(message);
      }
      setFormFeedback(feedback, "Password updated successfully.", "success");
      form.reset();
    } catch (err) {
      console.error(err);
      setFormFeedback(feedback, err.message || "Unable to update password.", "error");
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

function wireReportForm(root) {
  const form = root.querySelector("[data-report-form]");
  if (!form) return;
  const feedback = root.querySelector("[data-report-feedback]");
  const rangeLabel = root.querySelector("[data-report-range]");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setFormFeedback(feedback, "");
    const formData = new FormData(form);
    const startDate = formData.get("start_date");
    const endDate = formData.get("end_date");
    if (!startDate || !endDate) {
      setFormFeedback(feedback, "Select both start and end dates.", "error");
      return;
    }
    const submitBtn = form.querySelector("button[type='submit']");
    if (submitBtn) submitBtn.disabled = true;
    try {
      const res = await fetch("/api/users/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_date: startDate, end_date: endDate }),
      });
      if (!res.ok) {
        const message = await extractErrorMessage(res, "Unable to generate report");
        throw new Error(message);
      }
      const data = await res.json();
      updateReportMetrics(root, data);
      if (rangeLabel) {
        rangeLabel.textContent = `${startDate} – ${endDate}`;
      }
      setFormFeedback(feedback, "Report updated.", "success");
    } catch (err) {
      console.error(err);
      setFormFeedback(feedback, err.message || "Unable to generate report.", "error");
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

function updateReportMetrics(root, report) {
  if (!report || !root) return;
  const numericTwoDecimal = new Set(["total_hours", "net_hours"]);
  root.querySelectorAll("[data-report-metric]").forEach((node) => {
    const key = node.getAttribute("data-report-metric");
    if (!key || !(key in report)) return;
    let value = report[key];
    if (numericTwoDecimal.has(key)) {
      value = Number(value || 0).toFixed(2);
    } else if (typeof value === "number") {
      value = value.toLocaleString();
    } else {
      value = value || 0;
    }
    node.textContent = value;
  });
}

async function extractErrorMessage(response, fallback) {
  let message = fallback;
  try {
    const data = await response.json();
    message = data?.detail || data?.error || message;
  } catch (err) {
    console.warn("Failed to parse error payload", err);
  }
  return message;
}

function setFormFeedback(target, message, variant = "success") {
  if (!target) return;
  target.textContent = message || "";
  if (message) {
    target.dataset.variant = variant;
  } else {
    delete target.dataset.variant;
  }
}
