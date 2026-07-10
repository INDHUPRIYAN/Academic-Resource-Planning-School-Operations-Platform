// Reports page (Phase 7).
// Talks to: GET /reports/{teacher-workload,subject-coverage,resource-usage,leave-summary,timetable}
//           GET /reports/export/{same} (PDF/Excel download, auth'd blob fetch — apiRequest can't be used
//           since it always parses JSON, so downloadReport() below does its own fetch())

const REPORT_TABS = [
  ["teacher-workload", "Teacher Workload"],
  ["subject-coverage", "Subject Coverage"],
  ["resource-usage", "Resource Usage"],
  ["leave-summary", "Leave Summary"],
  ["timetable", "Timetables"],
];

function initReportsPage() {
  const root = document.getElementById("reportsRoot");
  root.innerHTML = `<div class="loading-state">Loading...</div>`;

  apiRequest("/auth/me").then(async (me) => {
    if (me.role === "teacher") {
      root.innerHTML = `<div class="empty-state">Reports are only available to school admins and super admins.</div>`;
      return;
    }
    try {
      const schools = (await apiRequest("/schools?limit=100")).items;
      renderReportsShell(me, schools);
    } catch (e) {
      root.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }).catch((e) => {
    root.innerHTML = `<div class="empty-state">${e.message}</div>`;
  });
}

async function downloadReport(path, filenameFallback) {
  const token = localStorage.getItem("token");
  const res = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Export failed");
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : filenameFallback;
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

async function renderReportsShell(me, schools) {
  const root = document.getElementById("reportsRoot");
  if (!schools.length) {
    root.innerHTML = `<div class="empty-state">No schools found. Ask a super admin to create one first.</div>`;
    return;
  }
  const state = { schoolId: me.role === "super_admin" ? schools[0].id : me.school_id, tab: "teacher-workload" };

  async function draw() {
    let config = {};
    try {
      const cfgRes = await apiRequest(`/schools/${state.schoolId}/config`);
      config = JSON.parse(cfgRes.config);
    } catch (e) {}

    let activeTabs = [...REPORT_TABS];
    const enabledModules = config.enabled_modules || ["timetables", "leaves", "swaps", "exams", "reports"];
    if (config.resources && (config.resources.enabled === false || config.resources === false)) {
      activeTabs = activeTabs.filter((t) => t[0] !== "resource-usage");
    }
    if (!enabledModules.includes("leaves")) {
      activeTabs = activeTabs.filter((t) => t[0] !== "leave-summary");
    }
    if (!enabledModules.includes("timetables")) {
      activeTabs = activeTabs.filter((t) => t[0] !== "timetable");
    }

    // Fallback if current tab is no longer active
    if (!activeTabs.map((t) => t[0]).includes(state.tab)) {
      state.tab = activeTabs[0][0];
    }

    root.innerHTML = `
      ${me.role === "super_admin" ? `
        <div class="tt-field" style="max-width:280px; margin-bottom:14px">
          <label>School</label>
          <select id="schoolSelect">${schools.map((s) => `<option value="${s.id}" ${s.id === state.schoolId ? "selected" : ""}>${s.name}</option>`).join("")}</select>
        </div>` : ""}
      <div class="filter-tabs" id="reportTabs">
        ${activeTabs.map(([key, label]) => `<button data-tab="${key}" class="${state.tab === key ? "active" : ""}">${label}</button>`).join("")}
      </div>
      <div id="reportContent"><div class="loading-state">Loading...</div></div>
    `;

    const schoolSelect = document.getElementById("schoolSelect");
    if (schoolSelect) {
      schoolSelect.addEventListener("change", async () => {
        state.schoolId = parseInt(schoolSelect.value);
        await draw();
      });
    }

    document.getElementById("reportTabs").querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => {
        document.querySelectorAll("#reportTabs button").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        state.tab = b.dataset.tab;
        renderTab(state);
      })
    );

    renderTab(state);
  }

  await draw();
}

function renderTab(state) {
  const content = document.getElementById("reportContent");
  content.innerHTML = `<div class="loading-state">Loading...</div>`;
  if (state.tab === "teacher-workload") return renderTeacherWorkload(state, content);
  if (state.tab === "subject-coverage") return renderSubjectCoverage(state, content);
  if (state.tab === "resource-usage") return renderResourceUsage(state, content);
  if (state.tab === "leave-summary") return renderLeaveSummary(state, content);
  if (state.tab === "timetable") return renderTimetableReport(state, content);
}

function exportBar(idPrefix, onExport) {
  return `
    <div style="display:flex; gap:8px; margin:10px 0 16px; align-items:center">
      <button class="btn btn-ghost" id="${idPrefix}ExportPdf">Export PDF</button>
      <button class="btn btn-ghost" id="${idPrefix}ExportXlsx">Export Excel</button>
      <button class="btn btn-ghost" id="${idPrefix}Narrate">Explain Report with AI</button>
      <div class="msg" id="${idPrefix}ExportMsg" style="margin:0"></div>
    </div>
    <div class="msg info" id="${idPrefix}NarrationBox" style="display:none; background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:16px; font-size:13px; line-height:1.5; color:#334155; margin-bottom: 16px; max-width:100%; white-space:pre-line"></div>
  `;
}

function wireExportBar(idPrefix, buildPath, reportType, state) {
  const msg = document.getElementById(`${idPrefix}ExportMsg`);
  async function doExport(fmt) {
    msg.className = "msg"; msg.textContent = "Preparing download...";
    try {
      await downloadReport(buildPath(fmt), `report.${fmt}`);
      msg.className = "msg success"; msg.textContent = "Downloaded.";
    } catch (e) {
      msg.className = "msg error"; msg.textContent = e.message;
    }
  }
  document.getElementById(`${idPrefix}ExportPdf`).addEventListener("click", () => doExport("pdf"));
  document.getElementById(`${idPrefix}ExportXlsx`).addEventListener("click", () => doExport("xlsx"));

  const narrateBtn = document.getElementById(`${idPrefix}Narrate`);
  const narrationBox = document.getElementById(`${idPrefix}NarrationBox`);
  if (narrateBtn && narrationBox) {
    narrateBtn.addEventListener("click", async () => {
      narrationBox.style.display = "block";
      narrationBox.textContent = "AI is analyzing report data and generating prose summary...";
      try {
        const body = {
          report_type: reportType,
          school_id: state.schoolId
        };
        if (reportType === "leave-summary") {
          body.start_date = state.leaveStart;
          body.end_date = state.leaveEnd;
        }
        const res = await apiRequest("/assistant/narrate-report", {
          method: "POST",
          body
        });
        narrationBox.innerHTML = `<strong>AI Narration Summary:</strong><br>${res.narrative.replace(/\n/g, "<br>")}`;
      } catch (e) {
        narrationBox.textContent = `Failed to generate narration: ${e.message}`;
      }
    });
  }
}


// ---------------- Teacher Workload ----------------
async function renderTeacherWorkload(state, content) {
  try {
    const data = await apiRequest(`/reports/teacher-workload?school_id=${state.schoolId}`);
    content.innerHTML = `
      <p style="font-size:12px; color:var(--muted)">
        ${data.summary.teacher_count} teacher(s) · avg utilization ${data.summary.avg_utilization_pct}% ·
        ${data.summary.overloaded_count} overloaded
      </p>
      ${exportBar("tw", () => {})}
      <table>
        <thead><tr><th>Teacher</th><th>Department</th><th>Scheduled/wk</th><th>Max Hrs/wk</th><th>Utilization</th><th>Sections</th><th>Subjects</th><th>Status</th></tr></thead>
        <tbody>
          ${data.teachers.map((t) => `<tr>
            <td>${t.teacher_name}</td>
            <td>${t.department || "—"}</td>
            <td>${t.scheduled_periods}</td>
            <td>${t.max_weekly_hours}</td>
            <td>${t.utilization_pct !== null ? t.utilization_pct + "%" : "—"}</td>
            <td>${t.sections_taught}</td>
            <td>${t.subjects_taught}</td>
            <td>${t.overloaded ? `<span class="status-badge rejected">overloaded</span>` : `<span class="status-badge approved">ok</span>`}</td>
          </tr>`).join("") || `<tr><td colspan="8">No teachers found.</td></tr>`}
        </tbody>
      </table>
    `;
    wireExportBar("tw", (fmt) => `/reports/export/teacher-workload?school_id=${state.schoolId}&format=${fmt}`, "teacher-workload", state);
  } catch (e) {
    content.innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}

// ---------------- Subject Coverage ----------------
async function renderSubjectCoverage(state, content) {
  try {
    const data = await apiRequest(`/reports/subject-coverage?school_id=${state.schoolId}`);
    content.innerHTML = `
      <p style="font-size:12px; color:var(--muted)">
        ${data.summary.pair_count} section/subject pair(s) · ${data.summary.under_covered_count} under-covered
      </p>
      ${exportBar("sc", () => {})}
      <table>
        <thead><tr><th>Section</th><th>Subject</th><th>Required Hrs/wk</th><th>Scheduled/wk</th><th>Coverage</th><th>Gap</th></tr></thead>
        <tbody>
          ${data.rows.map((r) => `<tr>
            <td>${r.section_name}</td>
            <td>${r.subject_name}</td>
            <td>${r.required_weekly_hours}</td>
            <td>${r.scheduled_periods}</td>
            <td>${r.coverage_pct !== null ? r.coverage_pct + "%" : "—"}</td>
            <td>${r.gap > 0 ? `<span class="status-badge rejected">${r.gap}</span>` : `<span class="status-badge approved">0</span>`}</td>
          </tr>`).join("") || `<tr><td colspan="6">No subject coverage data — generate a master timetable first.</td></tr>`}
        </tbody>
      </table>
    `;
    wireExportBar("sc", (fmt) => `/reports/export/subject-coverage?school_id=${state.schoolId}&format=${fmt}`, "subject-coverage", state);
  } catch (e) {
    content.innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}

// ---------------- Resource Usage ----------------
async function renderResourceUsage(state, content) {
  try {
    const data = await apiRequest(`/reports/resource-usage?school_id=${state.schoolId}`);
    content.innerHTML = `
      <p style="font-size:12px; color:var(--muted)">
        ${data.summary.resource_count} resource(s) · ${data.summary.unused_count} unused
      </p>
      ${exportBar("ru", () => {})}
      <table>
        <thead><tr><th>Resource</th><th>Type</th><th>Capacity</th><th>Timetable Bookings/wk</th><th>Exam Bookings</th><th>Utilization</th></tr></thead>
        <tbody>
          ${data.resources.map((r) => `<tr>
            <td>${r.name}</td>
            <td>${r.type || "—"}</td>
            <td>${r.capacity ?? "—"}</td>
            <td>${r.timetable_bookings_per_week}</td>
            <td>${r.exam_bookings}</td>
            <td>${r.utilization_pct !== null ? r.utilization_pct + "%" : "—"}</td>
          </tr>`).join("") || `<tr><td colspan="6">No resources found.</td></tr>`}
        </tbody>
      </table>
    `;
    wireExportBar("ru", (fmt) => `/reports/export/resource-usage?school_id=${state.schoolId}&format=${fmt}`, "resource-usage", state);
  } catch (e) {
    content.innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}

// ---------------- Leave Summary ----------------
async function renderLeaveSummary(state, content) {
  const today = new Date();
  const monthAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);
  const fmt = (d) => d.toISOString().slice(0, 10);
  if (!state.leaveStart) state.leaveStart = fmt(monthAgo);
  if (!state.leaveEnd) state.leaveEnd = fmt(today);

  content.innerHTML = `
    <div class="leave-form-row" style="margin-bottom:12px">
      <div class="tt-field"><label>Start date</label><input type="date" id="lsStart" value="${state.leaveStart}" /></div>
      <div class="tt-field"><label>End date</label><input type="date" id="lsEnd" value="${state.leaveEnd}" /></div>
      <button class="btn btn-primary" id="lsApply" style="align-self:flex-end">Apply</button>
    </div>
    <div id="lsBody"><div class="loading-state">Loading...</div></div>
  `;
  document.getElementById("lsApply").addEventListener("click", () => {
    state.leaveStart = document.getElementById("lsStart").value;
    state.leaveEnd = document.getElementById("lsEnd").value;
    loadBody();
  });

  async function loadBody() {
    const body = document.getElementById("lsBody");
    body.innerHTML = `<div class="loading-state">Loading...</div>`;
    try {
      const data = await apiRequest(`/reports/leave-summary?school_id=${state.schoolId}&start_date=${state.leaveStart}&end_date=${state.leaveEnd}`);
      body.innerHTML = `
        <p style="font-size:12px; color:var(--muted)">
          ${data.total_requests} request(s) — ${data.by_status.approved || 0} approved, ${data.by_status.pending || 0} pending, ${data.by_status.rejected || 0} rejected ·
          coverage rate: ${data.coverage_rate_pct !== null ? data.coverage_rate_pct + "%" : "n/a (no scheduled slots on leave dates)"}
        </p>
        ${exportBar("ls", () => {})}
        <table>
          <thead><tr><th>Teacher</th><th>Requests</th><th>Approved</th><th>Pending</th><th>Rejected</th><th>Approved Days in Range</th></tr></thead>
          <tbody>
            ${data.per_teacher.map((t) => `<tr>
              <td>${t.teacher_name}</td>
              <td>${t.requests}</td>
              <td>${t.approved || 0}</td>
              <td>${t.pending || 0}</td>
              <td>${t.rejected || 0}</td>
              <td>${t.approved_days}</td>
            </tr>`).join("") || `<tr><td colspan="6">No leave requests in this date range.</td></tr>`}
          </tbody>
        </table>
      `;
      wireExportBar("ls", (f) => `/reports/export/leave-summary?school_id=${state.schoolId}&start_date=${state.leaveStart}&end_date=${state.leaveEnd}&format=${f}`, "leave-summary", state);
    } catch (e) {
      body.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }
  loadBody();
}

// ---------------- Timetables ----------------
async function renderTimetableReport(state, content) {
  content.innerHTML = `<div class="loading-state">Loading sections/teachers...</div>`;
  try {
    const [classesRes, sectionsRes, teachersRes] = await Promise.all([
      apiRequest("/classes?limit=100"),
      apiRequest("/sections?limit=200"),
      apiRequest("/teachers?limit=200"),
    ]);
    const classById = Object.fromEntries(classesRes.items.filter((c) => c.school_id === state.schoolId).map((c) => [c.id, c]));
    const sections = sectionsRes.items.filter((s) => classById[s.class_id]);
    const teachers = teachersRes.items.filter((t) => t.school_id === state.schoolId);

    if (!state.ttMode) state.ttMode = "section";
    content.innerHTML = `
      <div class="leave-form-row" style="margin-bottom:12px">
        <div class="tt-field">
          <label>View by</label>
          <select id="ttMode">
            <option value="section" ${state.ttMode === "section" ? "selected" : ""}>Section</option>
            <option value="teacher" ${state.ttMode === "teacher" ? "selected" : ""}>Teacher</option>
          </select>
        </div>
        <div class="tt-field" id="ttTargetWrap"></div>
        <button class="btn btn-primary" id="ttLoad" style="align-self:flex-end">Show Timetable</button>
      </div>
      <div id="ttBody"></div>
    `;

    function renderTargetSelect() {
      const wrap = document.getElementById("ttTargetWrap");
      if (state.ttMode === "section") {
        wrap.innerHTML = `<label>Section</label><select id="ttTarget">${sections.map((s) => `<option value="${s.id}">${classById[s.class_id].name} ${s.name}</option>`).join("")}</select>`;
      } else {
        wrap.innerHTML = `<label>Teacher</label><select id="ttTarget">${teachers.map((t) => `<option value="${t.id}">${t.name}</option>`).join("")}</select>`;
      }
    }
    renderTargetSelect();

    document.getElementById("ttMode").addEventListener("change", (e) => {
      state.ttMode = e.target.value;
      renderTargetSelect();
    });
    document.getElementById("ttLoad").addEventListener("click", loadGrid);

    async function loadGrid() {
      const targetId = document.getElementById("ttTarget").value;
      if (!targetId) return;
      const param = state.ttMode === "section" ? `section_id=${targetId}` : `teacher_id=${targetId}`;
      const body = document.getElementById("ttBody");
      body.innerHTML = `<div class="loading-state">Loading...</div>`;
      try {
        const data = await apiRequest(`/reports/timetable?${param}`);
        const dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].slice(0, data.working_days);
        body.innerHTML = `
          <p style="font-size:12px; color:var(--muted)">${data.subtitle}</p>
          ${exportBar("tt", () => {})}
          <table class="tt-grid">
            <thead><tr><th></th>${dayNames.map((d) => `<th>${d}</th>`).join("")}</tr></thead>
            <tbody>
              ${data.grid.map((row) => `<tr>
                <td class="tt-period-label">Period ${row.period}</td>
                ${row.days.map((d) => `<td style="padding:8px; font-size:12px; white-space:pre-line; text-align:center">${d || "—"}</td>`).join("")}
              </tr>`).join("")}
            </tbody>
          </table>
        `;
        wireExportBar("tt", (fmt) => `/reports/export/timetable?${param}&format=${fmt}`, "timetables", state);
      } catch (e) {
        body.innerHTML = `<div class="empty-state">${e.message}</div>`;
      }
    }
    loadGrid();
  } catch (e) {
    content.innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}
