// Exam Module page (Phase 6).
// Talks to: GET /schools, /classes, /sections, /subjects, /resources, /teachers
//           POST /exams/generate   GET /exams   POST /exams   PUT /exams/{id}   DELETE /exams/{id}

function initExamsPage() {
  const root = document.getElementById("examRoot");
  root.innerHTML = `<div class="loading-state">Loading...</div>`;

  apiRequest("/auth/me").then(async (me) => {
    const isAdmin = me.role === "super_admin" || me.role === "school_admin";
    if (!isAdmin) {
      renderTeacherView(me);
      return;
    }
    try {
      const schools = (await apiRequest("/schools?limit=100")).items;
      renderAdminView(me, schools);
    } catch (e) {
      root.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }).catch((e) => {
    root.innerHTML = `<div class="empty-state">${e.message}</div>`;
  });
}

function renderTeacherView(me) {
  const root = document.getElementById("examRoot");
  root.innerHTML = `
    <div class="filter-tabs" id="filterTabs">
      <button data-range="upcoming" class="active">Upcoming</button>
      <button data-range="all">All</button>
    </div>
    <div id="examsWrap"><div class="loading-state">Loading...</div></div>
  `;
  document.getElementById("filterTabs").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#filterTabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      loadExamsList({ upcomingOnly: b.dataset.range === "upcoming" }, false);
    })
  );
  loadExamsList({ upcomingOnly: true }, false);
}

function renderAdminView(me, schools) {
  const root = document.getElementById("examRoot");
  if (!schools.length) {
    root.innerHTML = `<div class="empty-state">No schools found. Ask a super admin to create one first.</div>`;
    return;
  }
  const state = { schoolId: me.role === "super_admin" ? schools[0].id : me.school_id, sections: [] };

  root.innerHTML = `
    ${me.role === "super_admin" ? `
      <div class="tt-field" style="max-width:280px; margin-bottom:14px">
        <label>School</label>
        <select id="schoolSelect">${schools.map((s) => `<option value="${s.id}">${s.name}</option>`).join("")}</select>
      </div>` : ""}

    <div class="leave-form-card">
      <h3>Generate Exam Timetable</h3>
      <div class="msg" id="genMsg"></div>
      <p style="font-size:12px; color:var(--muted); margin-top:-4px">
        Greedy scheduler — for each section, examines every subject that section is currently taught
        (per the master timetable) and places one exam per subject into the first open slot, avoiding
        double-booking the section, the room, or the invigilator. Requires the master timetable to already
        be generated for the sections you pick.
      </p>
      <div class="leave-form-row">
        <div class="tt-field"><label>Start date</label><input type="date" id="genStart" /></div>
        <div class="tt-field"><label>End date</label><input type="date" id="genEnd" /></div>
        <div class="tt-field"><label>Exams / day</label><input type="number" id="genPerDay" value="2" min="1" style="width:70px" /></div>
      </div>
      <div class="leave-form-row">
        <div class="tt-field"><label>Daily start time</label><input type="time" id="genStartTime" value="09:00" /></div>
        <div class="tt-field"><label>Duration (min)</label><input type="number" id="genDuration" value="90" min="15" style="width:80px" /></div>
        <div class="tt-field"><label>Gap (min)</label><input type="number" id="genGap" value="30" min="0" style="width:70px" /></div>
      </div>
      <label>Sections (leave all unchecked = every section in the school)</label>
      <div id="sectionChecks" style="display:flex; flex-wrap:wrap; gap:8px; margin:6px 0 10px"><span class="loading-state">Loading sections...</span></div>
      <button class="btn btn-primary" id="generateBtn">Generate</button>
    </div>

    <div class="leave-form-card">
      <h3>Schedule a Single Exam</h3>
      <div class="msg" id="manualMsg"></div>
      <div class="leave-form-row">
        <div class="tt-field"><label>Section</label><select id="manSection"></select></div>
        <div class="tt-field"><label>Subject</label><select id="manSubject"></select></div>
      </div>
      <div class="leave-form-row">
        <div class="tt-field"><label>Date</label><input type="date" id="manDate" /></div>
        <div class="tt-field"><label>Start</label><input type="time" id="manStart" value="09:00" /></div>
        <div class="tt-field"><label>End</label><input type="time" id="manEnd" value="10:30" /></div>
      </div>
      <div class="leave-form-row">
        <div class="tt-field"><label>Room (optional)</label><select id="manResource"><option value="">None</option></select></div>
        <div class="tt-field"><label>Invigilator (optional)</label><select id="manInvigilator"><option value="">None</option></select></div>
      </div>
      <button class="btn btn-primary" id="manualBtn">Schedule Exam</button>
    </div>

    <div class="filter-tabs" id="filterTabs">
      <button data-range="upcoming" class="active">Upcoming</button>
      <button data-range="all">All</button>
    </div>
    <div id="examsWrap"><div class="loading-state">Loading...</div></div>
  `;

  const schoolSelect = document.getElementById("schoolSelect");
  if (schoolSelect) {
    schoolSelect.addEventListener("change", () => {
      state.schoolId = parseInt(schoolSelect.value);
      loadSchoolData();
    });
  }

  async function loadSchoolData() {
    const [classesRes, sectionsRes, subjectsRes, resourcesRes, teachersRes] = await Promise.all([
      apiRequest("/classes?limit=100"),
      apiRequest("/sections?limit=200"),
      apiRequest("/subjects?limit=200"),
      apiRequest("/resources?limit=100"),
      apiRequest("/teachers?limit=200"),
    ]);
    const classes = classesRes.items.filter((c) => c.school_id === state.schoolId);
    const classIds = new Set(classes.map((c) => c.id));
    state.sections = sectionsRes.items
      .filter((s) => classIds.has(s.class_id))
      .map((s) => ({ ...s, class_name: (classes.find((c) => c.id === s.class_id) || {}).name || "" }));
    state.subjects = subjectsRes.items.filter((s) => s.school_id === state.schoolId);
    state.resources = resourcesRes.items.filter((r) => r.school_id === state.schoolId);
    state.teachers = teachersRes.items.filter((t) => t.school_id === state.schoolId);

    document.getElementById("sectionChecks").innerHTML = state.sections.length
      ? state.sections.map((s) => `
          <label style="display:flex; align-items:center; gap:4px; font-size:13px; font-weight:400">
            <input type="checkbox" class="sectionCheck" value="${s.id}" /> ${s.class_name} ${s.name}
          </label>`).join("")
      : `<span style="font-size:12px; color:var(--muted)">No sections in this school yet.</span>`;

    const secSel = document.getElementById("manSection");
    secSel.innerHTML = state.sections.length
      ? state.sections.map((s) => `<option value="${s.id}">${s.class_name} ${s.name}</option>`).join("")
      : `<option value="">No sections</option>`;
    const subSel = document.getElementById("manSubject");
    subSel.innerHTML = state.subjects.length
      ? state.subjects.map((s) => `<option value="${s.id}">${s.name}</option>`).join("")
      : `<option value="">No subjects</option>`;
    const resSel = document.getElementById("manResource");
    resSel.innerHTML = `<option value="">None</option>` + state.resources.map((r) => `<option value="${r.id}">${r.name}</option>`).join("");
    const invSel = document.getElementById("manInvigilator");
    invSel.innerHTML = `<option value="">None</option>` + state.teachers.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
  }
  loadSchoolData();

  document.getElementById("generateBtn").addEventListener("click", async () => {
    const msg = document.getElementById("genMsg");
    const start_date = document.getElementById("genStart").value;
    const end_date = document.getElementById("genEnd").value;
    if (!start_date || !end_date) { msg.className = "msg error"; msg.textContent = "Pick both dates."; return; }
    const section_ids = Array.from(document.querySelectorAll(".sectionCheck:checked")).map((c) => parseInt(c.value));
    const body = {
      school_id: state.schoolId,
      section_ids: section_ids.length ? section_ids : null,
      start_date, end_date,
      exams_per_day: parseInt(document.getElementById("genPerDay").value) || 2,
      daily_start_time: document.getElementById("genStartTime").value + ":00",
      duration_minutes: parseInt(document.getElementById("genDuration").value) || 90,
      gap_minutes: parseInt(document.getElementById("genGap").value) || 30,
    };
    try {
      msg.className = "msg"; msg.textContent = "Generating...";
      const res = await apiRequest("/exams/generate", { method: "POST", body });
      msg.className = res.unscheduled.length ? "msg error" : "msg success";
      msg.textContent = res.message;
      loadExamsList({ upcomingOnly: true }, true);
    } catch (e) {
      msg.className = "msg error"; msg.textContent = e.message;
    }
  });

  document.getElementById("manualBtn").addEventListener("click", async () => {
    const msg = document.getElementById("manualMsg");
    const body = {
      section_id: parseInt(document.getElementById("manSection").value),
      subject_id: parseInt(document.getElementById("manSubject").value),
      date: document.getElementById("manDate").value,
      start_time: document.getElementById("manStart").value + ":00",
      end_time: document.getElementById("manEnd").value + ":00",
      resource_id: document.getElementById("manResource").value ? parseInt(document.getElementById("manResource").value) : null,
      invigilator_id: document.getElementById("manInvigilator").value ? parseInt(document.getElementById("manInvigilator").value) : null,
    };
    if (!body.section_id || !body.subject_id || !body.date) {
      msg.className = "msg error"; msg.textContent = "Section, subject and date are required."; return;
    }
    try {
      await apiRequest("/exams", { method: "POST", body });
      msg.className = "msg success"; msg.textContent = "Exam scheduled.";
      loadExamsList({ upcomingOnly: true }, true);
    } catch (e) {
      msg.className = "msg error"; msg.textContent = e.message;
    }
  });

  document.getElementById("filterTabs").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#filterTabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      loadExamsList({ upcomingOnly: b.dataset.range === "upcoming" }, true);
    })
  );

  loadExamsList({ upcomingOnly: true }, true);
}

async function loadExamsList({ upcomingOnly }, canManage) {
  const wrap = document.getElementById("examsWrap");
  wrap.innerHTML = `<div class="loading-state">Loading...</div>`;
  try {
    const q = new URLSearchParams({ limit: 100 });
    if (upcomingOnly) q.set("start_date", new Date().toISOString().slice(0, 10));
    const data = await apiRequest(`/exams?${q}`);
    if (!data.items.length) { wrap.innerHTML = `<div class="empty-state">No exams scheduled here.</div>`; return; }
    wrap.innerHTML = `<table><thead><tr>
        <th>Date</th><th>Time</th><th>Section</th><th>Subject</th><th>Room</th><th>Invigilator</th>${canManage ? "<th></th>" : ""}
      </tr></thead><tbody>
      ${data.items.map((x) => `<tr>
        <td>${x.date}</td>
        <td>${x.start_time.slice(0, 5)}–${x.end_time.slice(0, 5)}</td>
        <td>${x.section_name}</td>
        <td>${x.subject_name}</td>
        <td>${x.resource_name || "—"}</td>
        <td>${x.invigilator_name || "—"}</td>
        ${canManage ? `<td class="actions"><button class="btn btn-danger" data-del="${x.id}">Delete</button></td>` : ""}
      </tr>`).join("")}
    </tbody></table>`;

    wrap.querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", async () => {
        if (!confirm("Delete this exam?")) return;
        try {
          await apiRequest(`/exams/${b.dataset.del}`, { method: "DELETE" });
          loadExamsList({ upcomingOnly }, canManage);
        } catch (e) { alert(e.message); }
      })
    );
  } catch (e) {
    wrap.innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}
