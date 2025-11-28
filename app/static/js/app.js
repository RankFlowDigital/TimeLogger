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

function formatDateTime(value, { includeDate = false } = {}) {
  if (!value) return "--";
  const date = value instanceof Date ? value : new Date(value);
  const options = includeDate
    ? { dateStyle: "medium", timeStyle: "short" }
    : { timeStyle: "short" };
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

function renderStatus(state) {
  const badge = document.querySelector("[data-status-badge]");
  const meta = document.querySelector("[data-status-meta]");
  if (!badge || !meta) return;
  const open = state?.open_session;
  const status = open ? open.type : "OFFLINE";
  const since = open ? formatDateTime(open.started_at) : "";
  badge.textContent = status.replace(/_/g, " ");
  badge.dataset.status = status;
  badge.classList.toggle("offline", !open);
  meta.textContent = open ? `Since ${since}` : "No active session";
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
}

function renderTimeline(state) {
  const list = document.querySelector("[data-timeline]");
  if (!list) return;
  list.innerHTML = "";
  (state?.timeline_events || []).forEach((event) => {
    const item = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = formatDateTime(event.timestamp);
    const label = document.createElement("strong");
    label.textContent = event.label;
    const caption = document.createElement("span");
    caption.textContent = event.type === "ROLL_CALL" ? event.phase : event.type;
    item.append(time, label, caption);
    list.appendChild(item);
  });
  if (!list.children.length) {
    const placeholder = document.createElement("li");
    placeholder.innerHTML = "<strong>No timeline yet</strong><span>Actions will appear here</span>";
    list.appendChild(placeholder);
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
    const label = document.createElement("strong");
    label.textContent = member.name;
    const meta = document.createElement("span");
    const since = member.since ? formatDateTime(member.since) : "";
    meta.textContent = member.status === "OFFLINE" ? "offline" : `${member.status} · ${since}`;
    li.append(label, meta);
    roster.appendChild(li);
  });
  if (!roster.children.length) {
    const li = document.createElement("li");
    li.textContent = "No teammates yet";
    roster.appendChild(li);
  }
}

function renderRollCallHistory(state) {
  const list = document.querySelector("[data-rollcall-log]");
  if (!list) return;
  list.innerHTML = "";
  (state?.roll_calls || []).slice().reverse().slice(0, 5).forEach((rc) => {
    const li = document.createElement("li");
    const status = rc.result.replace(/_/g, " ");
    li.innerHTML = `<strong>${status}</strong><span>${formatDateTime(rc.triggered_at)}</span>`;
    list.appendChild(li);
  });
  if (!list.children.length) {
    const li = document.createElement("li");
    li.textContent = "No roll-calls today";
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
    clock.textContent = formatDateTime(new Date());
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
        if (!res.ok) throw new Error("Action failed");
        await dashboardRuntime.refresh();
      } catch (err) {
        console.error(err);
        alert("Unable to update session. Please try again.");
      } finally {
        btn.disabled = false;
        delete btn.dataset.loading;
      }
    });
  });
}

function hydrateDashboard() {
  if (!dashboardRuntime.hasBootstrap) return;
  dashboardRuntime.subscribe((state) => {
    renderStatus(state);
    renderSummary(state);
    renderTimeline(state);
    renderActivityLog(state);
    renderRoster(state);
    renderRollCallHistory(state);
    renderTimezoneLabel();
  });
  wireSessionButtons();
  initTimezoneControls();
  startClock();
}

document.addEventListener("DOMContentLoaded", () => {
  hydrateDashboard();
});
