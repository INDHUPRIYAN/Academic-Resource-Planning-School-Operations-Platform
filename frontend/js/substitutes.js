// Substitute Schedule page.
// Talks to: GET /substitutions/schedule?date=&section_id=&teacher_id=
//           GET /substitutions?date=  (management list)
//           PUT /substitutions/{id}   DELETE /substitutions/{id}
//           GET /classes /sections /teachers (for the pickers)

function initSubstitutesPage() {
  const root = document.getElementById("subRoot");
  const state = {
    me: null,
    isAdmin: false,
    classes: [],
    sections: [],
    teachers: [],
    date: new Date().toISOString().slice(0, 10),
    sectionId: null,
    teacherId: null,
  };

  root.innerHTML = `<div class="loading-state">Loading...</div>`;

  boot();

  async function boot() {
    try {
      state.me = await apiRequest("/auth/me");
      state.isAdmin = state.me.role === "super_admin" || state.me.role === "school_admin";
      const [classesRes, sectionsRes, teachersRes] = await Promise.all([
        apiRequest("/classes?limit=100"),
        apiRequest("/sections?limit=100"),
        apiRequest("/teachers?limit=100"),
      ]);
      state.classes = classesRes.items;
      state.sections = sectionsRes.items;
      state.teachers = teachersRes.items;
      render();
      load();
    } catch (e) {
      root.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }

  function sectionLabel(s) {
    const c = state.classes.find((c) => c.id === s.class_id);
    return `${c ? c.name : "?"} ${s.name}`;
  }

  function render() {
    root.innerHTML = `
      <div class="tt-toolbar">
        <div class="tt-field"><label>Date</label><input type="date" id="schedDate" value="${state.date}" /></div>
        <div class="tt-field"><label>Section</label>
          <select id="sectionSelect"><option value="">All sections</option>
            ${state.sections.map((s) => `<option value="${s.id}">${sectionLabel(s)}</option>`).join("")}
          </select>
        </div>
        <div class="tt-field"><label>Teacher</label>
          <select id="teacherSelect"><option value="">All teachers</option>
            ${state.teachers.map((t) => `<option value="${t.id}">${t.name}</option>`).join("")}
          </select>
        </div>
        <button class="btn btn-primary" id="viewBtn">View</button>
      </div>
      <div class="sched-legend">
        <span><span class="tt-legend-swatch" style="background:#fff; border:1px solid var(--border)"></span>Normal</span>
        <span><span class="tt-legend-swatch" style="background:#fef9c3"></span>Substituted</span>
        <span><span class="tt-legend-swatch" style="background:#ede9fe"></span>Swapped</span>
      </div>
      <div id="schedWrap"><div class="loading-state">Loading schedule...</div></div>
      <h3 style="margin:24px 0 10px">Manage Substitutions</h3>
      <div id="mgmtWrap"><div class="loading-state">Loading...</div></div>
    `;
    document.getElementById("viewBtn").addEventListener("click", () => {
      state.date = document.getElementById("schedDate").value || state.date;
      state.sectionId = document.getElementById("sectionSelect").value || null;
      state.teacherId = document.getElementById("teacherSelect").value || null;
      load();
    });
  }

  async function load() {
    await Promise.all([loadSchedule(), loadManagementList()]);
  }

  async function loadSchedule() {
    const wrap = document.getElementById("schedWrap");
    wrap.innerHTML = `<div class="loading-state">Loading schedule...</div>`;
    try {
      const q = new URLSearchParams({ date: state.date });
      if (state.sectionId) q.set("section_id", state.sectionId);
      if (state.teacherId) q.set("teacher_id", state.teacherId);
      const slots = await apiRequest(`/substitutions/schedule?${q}`);
      if (!slots.length) { wrap.innerHTML = `<div class="empty-state">No timetable slots for this day (weekend, or nothing generated yet).</div>`; return; }
      slots.sort((a, b) => a.period - b.period || a.section_name.localeCompare(b.section_name));
      wrap.innerHTML = `<div class="sched-day-list">${slots.map((s) => `
        <div class="sched-row ${s.is_substituted ? "substituted" : (s.is_swapped ? "swapped" : "")}">
          <div class="sched-period">Period ${s.period}</div>
          <div class="sched-main">
            <strong>${s.kind === "free" ? "Free" : (s.subject_name || s.activity_name)}</strong>
            ${s.section_name ? " · " + s.section_name : ""}
            ${s.is_substituted ? ` <span class="method-badge manual">covered</span>` : ""}
            ${s.is_swapped ? ` <span class="method-badge swap">swapped${s.swap_partner_label ? " with " + s.swap_partner_label : ""}</span>` : ""}
          </div>
          <div class="sched-teacher">
            ${s.teacher_name ? (s.is_substituted ? `${s.teacher_name} <span style="color:var(--muted)">(sub for ${s.original_teacher_name})</span>` : s.teacher_name) : ""}
          </div>
        </div>
      `).join("")}</div>`;
    } catch (e) {
      wrap.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }

  async function loadManagementList() {
    const wrap = document.getElementById("mgmtWrap");
    wrap.innerHTML = `<div class="loading-state">Loading...</div>`;
    try {
      const q = new URLSearchParams({ date: state.date, limit: 50 });
      const data = await apiRequest(`/substitutions?${q}`);
      if (!data.items.length) { wrap.innerHTML = `<div class="empty-state">No substitutions recorded for this date.</div>`; return; }
      wrap.innerHTML = `<table><thead><tr>
        <th>Period</th><th>Section</th><th>Subject/Activity</th><th>Original teacher</th><th>Substitute</th><th>Method</th><th></th>
      </tr></thead><tbody>
        ${data.items.map((s) => `<tr data-row="${s.id}">
          <td>${s.period}</td>
          <td>${s.section_name}</td>
          <td>${s.subject_name || s.activity_name || "—"}</td>
          <td>${s.original_teacher_name}</td>
          <td>
            ${state.isAdmin ? `<select data-reassign="${s.id}">
              ${state.teachers.map((t) => `<option value="${t.id}" ${t.id === s.substitute_teacher_id ? "selected" : ""}>${t.name}</option>`).join("")}
            </select>` : s.substitute_teacher_name}
          </td>
          <td>${methodBadgeLocal(s.method)}</td>
          <td class="actions">${state.isAdmin ? `<button class="btn btn-danger" data-delete="${s.id}">Remove</button>` : ""}</td>
        </tr>`).join("")}
      </tbody></table>`;

      if (state.isAdmin) {
        wrap.querySelectorAll("[data-reassign]").forEach((sel) =>
          sel.addEventListener("change", async () => {
            try {
              await apiRequest(`/substitutions/${sel.dataset.reassign}`, {
                method: "PUT",
                body: { substitute_teacher_id: parseInt(sel.value) },
              });
              load();
            } catch (e) {
              alert(e.message);
              load();
            }
          })
        );
        wrap.querySelectorAll("[data-delete]").forEach((b) =>
          b.addEventListener("click", async () => {
            if (!confirm("Remove this substitute assignment?")) return;
            await apiRequest(`/substitutions/${b.dataset.delete}`, { method: "DELETE" });
            load();
          })
        );
      }
    } catch (e) {
      wrap.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }

  function methodBadgeLocal(method) {
    if (!method) return "—";
    return `<span class="method-badge ${method}">${method.replace("_", " ")}</span>`;
  }
}
