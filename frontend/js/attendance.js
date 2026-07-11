// Teacher Attendance Calendar — read-only.
// The API derives each day's status from approved Leave / On-Duty, so there is no
// write endpoint at all: this page can only ever display.
// GET /attendance/calendar, /attendance/day, /attendance/substitute-load

const MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];
const DOW = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

function initAttendancePage() {
  const now = new Date();
  const state = {
    me: null,
    isAdmin: false,
    teachers: [],
    teacherId: null,
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  };

  boot();

  async function boot() {
    try {
      state.me = await apiRequest("/auth/me");
      state.isAdmin = ["super_admin", "school_admin", "principal", "vice_principal"].includes(state.me.role);

      if (state.isAdmin) {
        state.teachers = (await apiRequest("/teachers?limit=500")).items;
        state.teacherId = state.teachers[0]?.id ?? null;
        if (!state.teacherId) {
          document.getElementById("attRoot").innerHTML =
            `<div class="empty-state">No teachers found.</div>`;
          return;
        }
      }
      renderToolbar();
      load();
    } catch (err) {
      showMsg("error", err.message);
    }
  }

  function showMsg(kind, text) {
    const el = document.getElementById("attMsg");
    if (!text) { el.style.display = "none"; return; }
    el.className = `msg ${kind}`;
    el.textContent = text;
    el.style.display = "block";
  }

  function renderToolbar() {
    const bar = document.getElementById("attToolbar");
    const teacherPicker = state.isAdmin
      ? `<div class="tt-field"><label>Teacher</label>
           <select id="attTeacher">${state.teachers
             .map((t) => `<option value="${t.id}" ${t.id === state.teacherId ? "selected" : ""}>${t.name}</option>`)
             .join("")}</select></div>`
      : "";

    const years = [];
    for (let y = state.year - 1; y <= state.year + 1; y++) years.push(y);

    bar.innerHTML = `
      ${teacherPicker}
      <div class="tt-field"><label>Month</label>
        <select id="attMonth">${MONTHS
          .map((m, i) => `<option value="${i + 1}" ${i + 1 === state.month ? "selected" : ""}>${m}</option>`)
          .join("")}</select>
      </div>
      <div class="tt-field"><label>Year</label>
        <select id="attYear">${years
          .map((y) => `<option value="${y}" ${y === state.year ? "selected" : ""}>${y}</option>`)
          .join("")}</select>
      </div>
      <div class="tt-spacer"></div>
      <div class="tt-field"><label>&nbsp;</label>
        <button class="btn btn-ghost" id="attLoadBtn">↻ Refresh</button>
      </div>`;

    document.getElementById("attTeacher")?.addEventListener("change", (e) => {
      state.teacherId = Number(e.target.value); load();
    });
    document.getElementById("attMonth").addEventListener("change", (e) => {
      state.month = Number(e.target.value); load();
    });
    document.getElementById("attYear").addEventListener("change", (e) => {
      state.year = Number(e.target.value); load();
    });
    document.getElementById("attLoadBtn").addEventListener("click", load);
  }

  async function load() {
    const root = document.getElementById("attRoot");
    root.innerHTML = `<div class="loading-state">Loading calendar…</div>`;
    showMsg(null);
    try {
      let path = `/attendance/calendar?year=${state.year}&month=${state.month}`;
      if (state.isAdmin && state.teacherId) path += `&teacher_id=${state.teacherId}`;
      const data = await apiRequest(path);
      renderSummary(data);
      renderGrid(data);
    } catch (err) {
      root.innerHTML = `<div class="empty-state">${err.message}</div>`;
    }
  }

  function renderSummary(data) {
    const s = data.summary || {};
    const box = document.getElementById("attSummary");
    const stat = (label, val, colour) =>
      `<div class="att-stat"><b style="color:${colour}">${val || 0}</b>${label}</div>`;
    box.innerHTML =
      stat("Present", s.present, "#16a34a") +
      stat("Leave", s.leave, "#dc2626") +
      stat("On Duty", s.on_duty, "#a16207") +
      stat("Holiday / Non-working", (s.holiday || 0) + (s.non_working || 0), "#64748b");
  }

  function renderGrid(data) {
    const root = document.getElementById("attRoot");
    const days = data.days || [];
    if (!days.length) { root.innerHTML = `<div class="empty-state">No days to show.</div>`; return; }

    // Monday-first offset for the 1st of the month.
    const first = new Date(days[0].date + "T00:00:00");
    const offset = (first.getDay() + 6) % 7;

    let html = `<div class="att-grid">`;
    html += DOW.map((d) => `<div class="att-head">${d}</div>`).join("");
    for (let i = 0; i < offset; i++) html += `<div class="att-cell empty"></div>`;

    days.forEach((d) => {
      const num = Number(d.date.slice(-2));
      const cls = { green: "att-green", red: "att-red", yellow: "att-yellow", grey: "att-grey" }[d.colour] || "att-grey";
      const label = { present: "Present", leave: "Leave", on_duty: "On Duty",
                      holiday: "Holiday", non_working: "—" }[d.status] || d.status;
      const clickable = d.status === "leave" || d.status === "on_duty";
      const sub = clickable && d.affected_periods && d.affected_periods.length
        ? `<span class="att-sub">P${d.affected_periods.join(", P")} covered</span>` : "";
      html += `
        <div class="att-cell ${cls} ${clickable ? "clickable" : ""}" ${clickable ? `data-date="${d.date}"` : ""}>
          <span class="att-day">${num}</span>
          <span class="att-tag">${label}</span>
          ${sub}
        </div>`;
    });
    html += `</div>`;
    root.innerHTML = html;

    root.querySelectorAll("[data-date]").forEach((el) =>
      el.addEventListener("click", () => showDay(el.dataset.date)));
  }

  async function showDay(dateStr) {
    let path = `/attendance/day?date=${dateStr}`;
    if (state.isAdmin && state.teacherId) path += `&teacher_id=${state.teacherId}`;
    let d;
    try { d = await apiRequest(path); }
    catch (err) { showMsg("error", err.message); return; }

    const title = { leave: "On Leave", on_duty: "On Duty (present in school)",
                    present: "Present", holiday: "Holiday" }[d.status] || d.status;
    const rows = (d.substitutes || []).length
      ? `<table style="margin-top:10px"><thead><tr><th>Covered period</th></tr></thead><tbody>
           ${d.substitutes.map((s) => `<tr><td>${s}</td></tr>`).join("")}
         </tbody></table>`
      : `<p style="color:var(--muted); font-size:13px; margin-top:10px">No periods needed covering.</p>`;

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="max-width:520px">
        <h3>${dateStr} — ${title}</h3>
        <p style="color:var(--muted); font-size:13px; margin-top:4px">${d.detail || ""}</p>
        ${d.duty_type ? `<p style="font-size:13px; margin-top:6px"><b>Duty type:</b> ${d.duty_type}</p>` : ""}
        ${d.affected_periods && d.affected_periods.length
          ? `<p style="font-size:13px; margin-top:6px"><b>Affected periods:</b> P${d.affected_periods.join(", P")}</p>` : ""}
        ${rows}
        <div class="modal-actions">
          <button class="btn btn-ghost" id="attClose">Close</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    backdrop.querySelector("#attClose").addEventListener("click", () => backdrop.remove());
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.remove(); });
  }
}
