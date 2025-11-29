(function () {
  const PAGE_SIZE = 10;
  const numericFields = new Set([
    "total_hours",
    "total_minutes",
    "lunch_minutes",
    "break_minutes",
    "overbreak_minutes",
    "rollcall_minutes",
    "net_minutes",
    "sessions",
    "rollcall_total",
  ]);

  function parseJSON(nodeId) {
    const el = document.getElementById(nodeId);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "null");
    } catch (err) {
      console.warn(`Failed to parse ${nodeId}`, err);
      return null;
    }
  }

  function formatDuration(minutes) {
    const clamped = Math.max(0, Math.round(minutes || 0));
    const hours = Math.floor(clamped / 60);
    const mins = String(clamped % 60).padStart(2, "0");
    return `${hours}:${mins}`;
  }

  function formatNumber(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return "0";
    return value.toFixed(2);
  }

  function formatLocalDate(date) {
    const tzOffset = date.getTimezoneOffset();
    const localTime = new Date(date.getTime() - tzOffset * 60000);
    return localTime.toISOString().split("T")[0];
  }

  function initReportPage() {
    const root = document.querySelector("[data-report-page]");
    if (!root) return;
    const tableBody = root.querySelector("[data-report-table]");
    const pagination = root.querySelector("[data-report-pagination]");
    const emptyState = root.querySelector(".empty-state");
    const rows = parseJSON("report-data");
    const state = {
      rows: Array.isArray(rows) ? rows : [],
      sortKey: "user",
      sortDir: "asc",
      page: 1,
      pageSize: PAGE_SIZE,
    };

    function sortRows() {
      const sorted = state.rows.slice();
      const key = state.sortKey;
      const dir = state.sortDir === "desc" ? -1 : 1;
      sorted.sort((a, b) => {
        const aVal = a[key];
        const bVal = b[key];
        if (numericFields.has(key)) {
          return (Number(aVal) - Number(bVal)) * dir;
        }
        const aText = String(aVal || "").toLowerCase();
        const bText = String(bVal || "").toLowerCase();
        if (aText < bText) return -1 * dir;
        if (aText > bText) return 1 * dir;
        return 0;
      });
      return sorted;
    }

    function renderTable() {
      if (!tableBody) return;
      const sorted = sortRows();
      const total = sorted.length;
      const startIndex = (state.page - 1) * state.pageSize;
      const pageRows = sorted.slice(startIndex, startIndex + state.pageSize);
      tableBody.innerHTML = pageRows
        .map(
          (row) => `
            <tr>
              <td>${row.user}</td>
              <td>${formatNumber(row.total_hours)}</td>
              <td>${row.lunch_minutes}</td>
              <td>${row.break_minutes}</td>
              <td>${row.overbreak_minutes}</td>
              <td>${row.rollcall_minutes}</td>
              <td>${formatDuration(row.net_minutes)}</td>
              <td>${row.sessions}</td>
              <td>P: ${row.rollcall_passed} / L: ${row.rollcall_late} / M: ${row.rollcall_missed}</td>
            </tr>`
        )
        .join("");
      if (emptyState) {
        emptyState.hidden = total > 0;
      }
      renderPagination(total);
      updateSortIndicators();
    }

    function renderPagination(total) {
      if (!pagination) return;
      if (!total) {
        pagination.innerHTML = "";
        return;
      }
      const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
      if (state.page > totalPages) state.page = totalPages;
      const startNum = (state.page - 1) * state.pageSize + 1;
      const endNum = Math.min(total, startNum + state.pageSize - 1);
      pagination.innerHTML = `
        <span>Showing ${startNum}-${endNum} of ${total}</span>
        <div>
          <button type="button" data-page="prev" ${state.page === 1 ? "disabled" : ""}>Prev</button>
          <button type="button" data-page="next" ${state.page === totalPages ? "disabled" : ""}>Next</button>
        </div>`;
      pagination.querySelectorAll("button").forEach((btn) => {
        btn.addEventListener("click", () => {
          const dir = btn.getAttribute("data-page") === "next" ? 1 : -1;
          state.page = Math.min(totalPages, Math.max(1, state.page + dir));
          renderTable();
        });
      });
    }

    function updateSortIndicators() {
      root.querySelectorAll("thead th[data-sort]").forEach((th) => {
        const key = th.getAttribute("data-sort");
        if (!key) return;
        const active = key === state.sortKey;
        th.setAttribute("aria-sort", active ? state.sortDir : "none");
        th.classList.toggle("sorted", active);
      });
    }

    function attachSortHandlers() {
      root.querySelectorAll("thead th[data-sort]").forEach((th) => {
        th.addEventListener("click", () => {
          const key = th.getAttribute("data-sort");
          if (!key) return;
          if (state.sortKey === key) {
            state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
          } else {
            state.sortKey = key;
            state.sortDir = numericFields.has(key) ? "desc" : "asc";
          }
          state.page = 1;
          renderTable();
        });
      });
    }

    function initQuickRanges() {
      const presetField = document.getElementById("report-preset");
      const startInput = document.getElementById("report-start");
      const endInput = document.getElementById("report-end");
      const buttons = root.querySelectorAll("[data-range-shortcut]");
      buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
          if (!startInput || !endInput) return;
          const preset = btn.getAttribute("data-range-shortcut");
          const today = new Date();
          const startDate = new Date(today);
          if (preset === "week") {
            startDate.setDate(startDate.getDate() - 6);
          }
          startInput.value = formatLocalDate(startDate);
          endInput.value = formatLocalDate(today);
          if (presetField) presetField.value = preset || "custom";
          buttons.forEach((b) => b.classList.toggle("active", b === btn));
        });
      });
      [startInput, endInput].forEach((input) => {
        if (!input) return;
        input.addEventListener("input", () => {
          if (presetField) presetField.value = "custom";
          buttons.forEach((b) => b.classList.remove("active"));
        });
      });
    }

    function initExport() {
      const exportBtn = root.querySelector("[data-report-export]");
      const form = document.getElementById("report-filter-form");
      if (!exportBtn || !form) return;
      exportBtn.addEventListener("click", () => {
        const params = new URLSearchParams(new FormData(form));
        const presetValue = document.getElementById("report-preset")?.value;
        if (presetValue) {
          params.set("preset", presetValue);
        }
        window.location.href = `/reports/export?${params.toString()}`;
      });
    }

    function updateSummaryValues() {
      const summary = parseJSON("report-summary") || {};
      const totalUsers = root.querySelector("[data-summary-users]");
      const avgNet = root.querySelector("[data-summary-avg]");
      const deductions = root.querySelector("[data-summary-deductions]");
      if (totalUsers) totalUsers.textContent = summary.total_users ?? 0;
      if (avgNet) avgNet.textContent = formatNumber(summary.avg_net_hours ?? 0);
      if (deductions) deductions.textContent = summary.total_deductions ?? 0;
    }

    attachSortHandlers();
    initQuickRanges();
    initExport();
    updateSummaryValues();
    renderTable();
  }

  document.addEventListener("DOMContentLoaded", initReportPage);
})();
