// Timetable Viewer / Generator page.
// Talks to: GET /schools, /classes, /sections, /teachers, /subjects, /activities, /resources
//           POST /timetables/generate, GET /timetables/section/{id}, GET /timetables/teacher/{id}
//           PATCH /timetables/{id}/lock, PUT /timetables/{id}

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function initTimetablePage() {
  const state = {
    me: null,
    isAdmin: false,
    schools: [],
    school: null, // full school object (periods_per_day/working_days)
    classes: [],
    sections: [],
    teachers: [],
    subjects: [],
    activities: [],
    resources: [],
    mode: "section", // "section" | "teacher"
    selectedClassId: null,
    selectedSectionId: null,
    selectedTeacherId: null,
    generating: false,
  };

  boot();

  async function boot() {
    try {
      state.me = await apiRequest("/auth/me");
      state.isAdmin = state.me.role === "super_admin" || state.me.role === "school_admin";
      state.schools = (await apiRequest("/schools?limit=100")).items;
      if (!state.schools.length) {
        renderToolbar();
        showAlert("info", "No schools found. Ask a super admin to create one first.");
        return;
      }
      await selectSchool(state.schools[0].id);
    } catch (err) {
      showAlert("error", err.message);
    }
  }

  async function selectSchool(schoolId) {
    state.school = state.schools.find((s) => s.id === schoolId) || (await apiRequest(`/schools/${schoolId}`));
    state.config = {};
    try {
      const cfgRes = await apiRequest(`/schools/${schoolId}/config`);
      state.config = JSON.parse(cfgRes.config);
    } catch (e) {}
    const [classesRes, teachersRes, subjectsRes, activitiesRes, resourcesRes] = await Promise.all([
      apiRequest("/classes?limit=100"),
      apiRequest("/teachers?limit=100"),
      apiRequest("/subjects?limit=100"),
      apiRequest("/activities?limit=100"),
      apiRequest("/resources?limit=100"),
    ]);
    state.classes = classesRes.items.filter((c) => c.school_id === schoolId);
    state.teachers = teachersRes.items.filter((t) => t.school_id === schoolId);
    state.subjects = subjectsRes.items.filter((s) => s.school_id === schoolId);
    state.activities = activitiesRes.items.filter((a) => a.school_id === schoolId);
    state.resources = resourcesRes.items.filter((r) => r.school_id === schoolId);

    const sectionLists = await Promise.all(
      state.classes.map((c) => apiRequest(`/sections?limit=100&class_id=${c.id}`))
    );
    state.sections = sectionLists.flatMap((res, i) =>
      res.items.map((sec) => ({ ...sec, class_name: state.classes[i].name }))
    );

    state.selectedClassId = state.classes[0]?.id ?? null;
    state.selectedSectionId = state.sections.find((s) => s.class_id === state.selectedClassId)?.id ?? null;
    state.selectedTeacherId = state.teachers[0]?.id ?? null;

    state.selectedVersionId = null;
    state.versions = [];
    if (state.isAdmin) {
      try {
        state.versions = await apiRequest(`/timetables/versions?school_id=${schoolId}`);
      } catch (e) {}
    }

    renderToolbar();
    loadGrid();
  }

  function showAlert(kind, message) {
    const el = document.getElementById("ttAlert");
    if (!message) {
      el.innerHTML = "";
      return;
    }
    const isError = kind === "error";
    el.innerHTML = `
      <div class="tt-alert ${kind}" style="display:flex; justify-content:space-between; align-items:center; width: 100%">
        <span>${message}</span>
        ${isError ? `<button class="btn btn-ghost" style="padding:4px 8px; font-size:11px; margin-left: 12px" onclick="if(window.explainConflict) window.explainConflict('${message.replace(/'/g, "\\'")}')">Explain with AI</button>` : ""}
      </div>
    `;
  }

  function renderToolbar() {
    const bar = document.getElementById("ttToolbar");
    const schoolPicker =
      state.me.role === "super_admin" && state.schools.length > 1
        ? `<div class="tt-field"><label>School</label>
             <select id="ttSchool">${state.schools
               .map((s) => `<option value="${s.id}" ${s.id === state.school.id ? "selected" : ""}>${s.name}</option>`)
               .join("")}</select></div>`
        : "";

    const modeToggle = `
      <div class="tt-field"><label>View by</label>
        <div class="tt-mode-toggle">
          <button type="button" id="modeSectionBtn" class="${state.mode === "section" ? "active" : ""}">Section</button>
          <button type="button" id="modeTeacherBtn" class="${state.mode === "teacher" ? "active" : ""}">Teacher</button>
        </div>
      </div>`;

    let selector = "";
    if (state.mode === "section") {
      selector = `
        <div class="tt-field"><label>Class</label>
          <select id="ttClass">${state.classes.map((c) => `<option value="${c.id}" ${c.id === state.selectedClassId ? "selected" : ""}>${c.name}</option>`).join("") || `<option>No classes</option>`}</select>
        </div>
        <div class="tt-field"><label>Section</label>
          <select id="ttSection">${state.sections
            .filter((s) => s.class_id === state.selectedClassId)
            .map((s) => `<option value="${s.id}" ${s.id === state.selectedSectionId ? "selected" : ""}>${s.name}</option>`)
            .join("") || `<option>No sections</option>`}</select>
        </div>`;
    } else {
      selector = `
        <div class="tt-field"><label>Teacher</label>
          <select id="ttTeacher">${state.teachers
            .map((t) => `<option value="${t.id}" ${t.id === state.selectedTeacherId ? "selected" : ""}>${t.name}</option>`)
            .join("") || `<option>No teachers</option>`}</select>
        </div>`;
    }

    let versionSelectHtml = "";
    let workflowStatusHtml = "";
    let actionButtons = "";

    if (state.isAdmin) {
      versionSelectHtml = `
        <div class="tt-field"><label>Version</label>
          <select id="ttVersionSelect" style="min-width:140px">
            <option value="">Active (Master)</option>
            ${state.versions.map(v => `<option value="${v.id}" ${state.selectedVersionId == v.id ? "selected" : ""}>${v.name} [${v.status}]</option>`).join("")}
          </select>
        </div>
      `;

      if (state.selectedVersionId) {
        const v = state.versions.find(x => x.id === state.selectedVersionId);
        if (v) {
          workflowStatusHtml = `
            <div class="tt-field">
              <label>Workflow Status</label>
              <span class="badge-pill success" style="padding:4px 8px; font-weight:700; text-transform:uppercase">${v.status.replace('_', ' ')}</span>
            </div>
          `;

          if (v.status === "draft") {
            actionButtons = `
              <button class="btn btn-ghost" id="submitReviewBtn" style="margin-left: 8px">Submit for Review</button>
            `;
          } else if (v.status === "under_review") {
            actionButtons = `
              <button class="btn btn-primary" id="approveVersionBtn" style="margin-left: 8px">Approve Version</button>
            `;
          } else if (v.status === "approved") {
            actionButtons = `
              <button class="btn btn-ghost" id="compareVersionBtn" style="margin-left: 8px">Compare Changes</button>
              <button class="btn btn-primary" id="publishVersionBtn" style="margin-left: 8px">Publish Master</button>
            `;
          } else if (v.status === "published") {
            actionButtons = `
              <button class="btn btn-ghost" id="compareVersionBtn" style="margin-left: 8px">Compare Changes</button>
              <span class="badge-pill success" style="margin-left: 8px; padding:6px 12px; font-weight:700">Published Active</span>
            `;
          } else {
            // Archived status
            actionButtons = `
              <button class="btn btn-ghost" id="compareVersionBtn" style="margin-left: 8px">Compare</button>
              <button class="btn btn-primary" id="rollbackVersionBtn" style="margin-left: 8px">Rollback to Version</button>
            `;
          }
        }
      } else {
        actionButtons = `
          <button class="btn btn-ghost" id="saveDraftBtn" style="margin-left: 8px">Save Draft</button>
          <div class="tt-field" style="margin-left: 8px"><label>Time limit (s)</label><input id="ttTimeLimit" type="number" min="5" max="120" value="30" style="min-width:80px" /></div>
          <div class="tt-field" style="margin-left: 8px"><label>&nbsp;</label><button class="btn btn-primary" id="ttGenerateBtn">${state.generating ? '<span class="spinner"></span> Generating…' : "⚙ Generate Timetable"}</button></div>
        `;
      }
    }

    const exportBtnHtml = `<div class="tt-field"><label>&nbsp;</label><button type="button" class="btn btn-ghost" id="ttExportBtn">⤓ Export PDF</button></div>`;

    bar.innerHTML = `${schoolPicker}${modeToggle}${selector}${versionSelectHtml}${workflowStatusHtml}<div class="tt-spacer"></div>${exportBtnHtml}${actionButtons}`;

    document.getElementById("ttExportBtn")?.addEventListener("click", openExportModal);
    document.getElementById("ttSchool")?.addEventListener("change", (e) => selectSchool(Number(e.target.value)));
    document.getElementById("modeSectionBtn")?.addEventListener("click", () => { state.mode = "section"; renderToolbar(); loadGrid(); });
    document.getElementById("modeTeacherBtn")?.addEventListener("click", () => { state.mode = "teacher"; renderToolbar(); loadGrid(); });
    document.getElementById("ttClass")?.addEventListener("change", (e) => {
      state.selectedClassId = Number(e.target.value);
      state.selectedSectionId = state.sections.find((s) => s.class_id === state.selectedClassId)?.id ?? null;
      renderToolbar();
      loadGrid();
    });
    document.getElementById("ttSection")?.addEventListener("change", (e) => {
      state.selectedSectionId = Number(e.target.value);
      loadGrid();
    });
    document.getElementById("ttTeacher")?.addEventListener("change", (e) => {
      state.selectedTeacherId = Number(e.target.value);
      loadGrid();
    });
    document.getElementById("ttVersionSelect")?.addEventListener("change", (e) => {
      state.selectedVersionId = e.target.value ? Number(e.target.value) : null;
      renderToolbar();
      loadGrid();
    });

    document.getElementById("ttGenerateBtn")?.addEventListener("click", onGenerate);
    document.getElementById("saveDraftBtn")?.addEventListener("click", onSaveDraft);
    document.getElementById("submitReviewBtn")?.addEventListener("click", onSubmitReview);
    document.getElementById("approveVersionBtn")?.addEventListener("click", onApproveVersion);
    document.getElementById("compareVersionBtn")?.addEventListener("click", onCompareVersion);
    document.getElementById("publishVersionBtn")?.addEventListener("click", onPublishVersion);
    document.getElementById("rollbackVersionBtn")?.addEventListener("click", onRollbackVersion);
  }

  function onSaveDraft() {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="max-width: 440px;">
        <h3>Save Timetable Draft</h3>
        <form id="saveDraftForm" style="margin-top: 12px; display:flex; flex-direction:column; gap:10px;">
          <label>Draft Name</label>
          <input name="name" type="text" required placeholder="e.g. Draft 1.0" />
          
          <label>Academic Year</label>
          <input name="academic_year" type="text" value="2026-2027" placeholder="e.g. 2026-2027" />
          
          <label>Term</label>
          <input name="term" type="text" value="Term 1" placeholder="e.g. Term 1" />
          
          <label>Semester</label>
          <input name="semester" type="text" value="Semester 1" placeholder="e.g. Semester 1" />
          
          <label>Generation Policy</label>
          <select name="generation_policy">
            <option value="Balanced">Balanced</option>
            <option value="Dense">Dense</option>
            <option value="Spread">Spread</option>
          </select>
          
          <label>Notes/Reason</label>
          <textarea name="reason" rows="2" placeholder="e.g. Pre-planning draft snapshot"></textarea>
          
          <div class="modal-actions" style="margin-top: 12px;">
            <button type="button" class="btn btn-ghost" id="cancelDraftBtn">Cancel</button>
            <button type="submit" class="btn btn-primary">Save Draft</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(backdrop);
    backdrop.querySelector("#cancelDraftBtn").addEventListener("click", () => backdrop.remove());
    backdrop.querySelector("#saveDraftForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      try {
        await apiRequest("/timetables/versions/save-draft", {
          method: "POST",
          body: {
            school_id: state.school.id,
            name: fd.get("name"),
            academic_year: fd.get("academic_year"),
            term: fd.get("term"),
            semester: fd.get("semester"),
            generation_policy: fd.get("generation_policy"),
            reason: fd.get("reason")
          }
        });
        backdrop.remove();
        showAlert("success", `Draft "${fd.get("name")}" saved successfully.`);
        state.versions = await apiRequest(`/timetables/versions?school_id=${state.school.id}`);
        renderToolbar();
      } catch (err) {
        alert(err.message);
      }
    });
  }

  async function onSubmitReview() {
    if (!state.selectedVersionId) return;
    try {
      await apiRequest(`/timetables/versions/${state.selectedVersionId}/submit-review`, { method: "POST" });
      showAlert("success", "Timetable submitted for review.");
      state.versions = await apiRequest(`/timetables/versions?school_id=${state.school.id}`);
      renderToolbar();
    } catch (err) {
      showAlert("error", err.message);
    }
  }

  async function onApproveVersion() {
    if (!state.selectedVersionId) return;
    try {
      await apiRequest(`/timetables/versions/${state.selectedVersionId}/approve`, { method: "POST" });
      showAlert("success", "Timetable version approved.");
      state.versions = await apiRequest(`/timetables/versions?school_id=${state.school.id}`);
      renderToolbar();
    } catch (err) {
      showAlert("error", err.message);
    }
  }

  async function onPublishVersion() {
    if (!state.selectedVersionId) return;
    const confirmPublish = confirm("Are you sure you want to publish this approved version? This will update the school readiness validation check.");
    if (!confirmPublish) return;
    try {
      const res = await apiRequest(`/timetables/versions/${state.selectedVersionId}/publish`, {
        method: "POST"
      });
      showAlert("success", res.message);
      state.selectedVersionId = null;
      state.versions = await apiRequest(`/timetables/versions?school_id=${state.school.id}`);
      renderToolbar();
      loadGrid();
    } catch (err) {
      showAlert("error", err.message);
    }
  }

  async function onRollbackVersion() {
    if (!state.selectedVersionId) return;
    try {
      // 1. Fetch side-by-side differences first
      const comparison = await apiRequest(`/timetables/versions/${state.selectedVersionId}/compare`, {
        method: "POST"
      });
      
      // 2. Show compare modal with actual rollback confirmation callback
      showCompareModal(comparison, async () => {
        try {
          const res = await apiRequest(`/timetables/versions/${state.selectedVersionId}/rollback`, {
            method: "POST"
          });
          showAlert("success", res.message);
          state.selectedVersionId = null;
          state.versions = await apiRequest(`/timetables/versions?school_id=${state.school.id}`);
          renderToolbar();
          loadGrid();
        } catch (err) {
          showAlert("error", err.message);
        }
      });
    } catch (err) {
      showAlert("error", err.message);
    }
  }

  async function onCompareVersion() {
    if (!state.selectedVersionId) return;
    try {
      const res = await apiRequest(`/timetables/versions/${state.selectedVersionId}/compare`, {
        method: "POST"
      });
      showCompareModal(res);
    } catch (err) {
      showAlert("error", err.message);
    }
  }

  function showCompareModal(comparison, onConfirm = null) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    
    let diffRows = "";
    if (!comparison.differences || !comparison.differences.length) {
      diffRows = `<tr><td colspan="4" style="text-align:center">No differences found. Both versions are identical.</td></tr>`;
    } else {
      const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
      diffRows = comparison.differences.map(d => {
        // Visual version comparison highlighting (Item 6)
        let changeText = d.version_details;
        let colorClass = "var(--blue)"; // Default Subject Blue
        let label = "Subject Changed";
        
        const actLow = d.active_details.toLowerCase();
        const verLow = d.version_details.toLowerCase();
        
        if (actLow.includes("activity:") || verLow.includes("activity:")) {
          colorClass = "var(--green)"; // Activity Green
          label = "Activity Changed";
        } else if (actLow.includes("[") || verLow.includes("[")) {
          colorClass = "var(--red)"; // Resource Red
          label = "Resource Changed";
        } else if (actLow.includes("(") || verLow.includes("(")) {
          colorClass = "#d97706"; // Teacher Orange/Yellow
          label = "Teacher Changed";
        }

        return `
          <tr>
            <td>${d.section_name}</td>
            <td>${days[d.day_of_week]} Period ${d.period}</td>
            <td style="color: var(--muted); text-decoration: line-through;">${d.active_details}</td>
            <td>
              <span style="border-left: 3px solid ${colorClass}; padding-left: 6px; font-weight: 600; color: ${colorClass}">
                ${d.version_details}
              </span>
              <span class="badge-pill" style="background: ${colorClass}15; color: ${colorClass}; font-size:10px; margin-left: 6px">${label}</span>
            </td>
          </tr>
        `;
      }).join("");
    }

    backdrop.innerHTML = `
      <div class="modal" style="max-width: 800px; max-height: 80vh; display: flex; flex-direction: column;">
        <h3>Comparing Active vs ${comparison.version_name}</h3>
        <div style="overflow-y: auto; margin: 16px 0; flex: 1;">
          <table>
            <thead>
              <tr>
                <th>Section</th>
                <th>Time Slot</th>
                <th>Active (Master)</th>
                <th>Selected Version</th>
              </tr>
            </thead>
            <tbody>
              ${diffRows}
            </tbody>
          </table>
        </div>
        <div class="modal-actions" style="margin-top: 0">
          <button class="btn btn-ghost" id="closeCompareBtn">Close</button>
          ${onConfirm ? `<button class="btn btn-primary" id="confirmRollbackModalBtn">Confirm Rollback</button>` : ""}
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    document.getElementById("closeCompareBtn").addEventListener("click", () => backdrop.remove());
    if (onConfirm) {
      document.getElementById("confirmRollbackModalBtn").addEventListener("click", () => {
        onConfirm();
        backdrop.remove();
      });
    }
  }

  async function onGenerate() {
    if (state.generating) return;
    state.generating = true;
    renderToolbar();
    showAlert("info", "Running pre-generation validation checks...");
    try {
      const report = await apiRequest(`/validation/school/${state.school.id}`);
      if (report.errors && report.errors.length > 0) {
        const errorMsgs = report.errors.map(e => e.message);
        showAlert("error", `Cannot generate: School configuration has blocker errors: ${errorMsgs.join("; ")}`);
        
        const explainBtn = document.createElement("button");
        explainBtn.className = "btn btn-ghost";
        explainBtn.style.cssText = "padding:4px 8px; font-size:11px; margin-left: 12px;";
        explainBtn.textContent = "Explain Blockers with AI";
        explainBtn.onclick = () => {
          if (window.explainInfeasibility) {
            window.explainInfeasibility(errorMsgs, report.warnings.map(w => w.message));
          }
        };
        const alertEl = document.querySelector("#ttAlert .tt-alert");
        if (alertEl) {
          const oldBtn = alertEl.querySelector("button");
          if (oldBtn) oldBtn.replaceWith(explainBtn);
          else alertEl.appendChild(explainBtn);
        }
        
        state.generating = false;
        renderToolbar();
        return;
      }

      showAlert("info", "Validation passed. Running the CP-SAT solver… this can take up to the time limit you set.");
      const timeLimit = Number(document.getElementById("ttTimeLimit")?.value || 30);
      const res = await apiRequest("/timetables/generate", {
        method: "POST",
        body: { school_id: state.school.id, time_limit_seconds: timeLimit },
      });
      showAlert("success", `${res.message} (${res.slots_created} slots across ${res.sections_scheduled} section(s).)`);
      loadGrid();
    } catch (err) {
      showAlert("error", err.message);
    } finally {
      state.generating = false;
      renderToolbar();
    }
  }

  async function loadGrid() {
    const wrap = document.getElementById("ttGridWrap");
    const vParam = state.selectedVersionId ? `?version_id=${state.selectedVersionId}` : "";
    if (state.mode === "section") {
      if (!state.selectedSectionId) {
        wrap.innerHTML = `<div class="empty-state">This school has no classes/sections yet.</div>`;
        return;
      }
      wrap.innerHTML = `<div class="loading-state">Loading timetable…</div>`;
      try {
        const data = await apiRequest(`/timetables/section/${state.selectedSectionId}${vParam}`);
        renderGrid(data.slots, "section");
      } catch (err) {
        wrap.innerHTML = `<div class="empty-state">${err.message}</div>`;
      }
    } else {
      if (!state.selectedTeacherId) {
        wrap.innerHTML = `<div class="empty-state">This school has no teachers yet.</div>`;
        return;
      }
      wrap.innerHTML = `<div class="loading-state">Loading timetable…</div>`;
      try {
        const data = await apiRequest(`/timetables/teacher/${state.selectedTeacherId}${vParam}`);
        renderGrid(data.slots, "teacher");
      } catch (err) {
        wrap.innerHTML = `<div class="empty-state">${err.message}</div>`;
      }
    }
  }

  function renderGrid(slots, viewMode) {
    const wrap = document.getElementById("ttGridWrap");
    const periodsPerDay = state.school.periods_per_day || 8;
    const workingDays = state.school.working_days || 5;
    const days = DAY_NAMES.slice(0, workingDays);

    const byDayPeriod = {};
    slots.forEach((s) => {
      byDayPeriod[`${s.day_of_week}_${s.period}`] = s;
    });

    if (!slots.length) {
      showAlert("info", "No timetable generated yet for this school." + (state.isAdmin ? " Click \u201cGenerate Timetable\u201d above." : " Ask an admin to generate it."));
    } else {
      showAlert(null);
    }

    let html = `<div class="tt-grid-wrap"><table class="tt-grid"><thead><tr><th>Period</th>${days.map((d) => `<th>${d}</th>`).join("")}</tr></thead><tbody>`;

    for (let p = 1; p <= periodsPerDay; p++) {
      html += `<tr><td class="tt-period-label">P${p}</td>`;
      for (let d = 0; d < workingDays; d++) {
        const slot = byDayPeriod[`${d}_${p}`];
        html += `<td>${cellHtml(slot, viewMode)}</td>`;
      }
      html += `</tr>`;
    }
    html += `</tbody></table></div>`;
    wrap.innerHTML = html;

    wrap.querySelectorAll("[data-slot-id]").forEach((el) => {
      el.addEventListener("click", () => {
        const slot = slots.find((s) => s.id === Number(el.dataset.slotId));
        if (slot) openEditModal(slot);
      });
    });
  }

  function cellHtml(slot, viewMode) {
    if (!slot) return `<div class="tt-cell free">Free</div>`;
    const kindClass = slot.kind === "activity" ? "activity" : "subject";
    const title = slot.kind === "activity" ? slot.activity_name : slot.subject_name;
    const subParts = [];
    if (viewMode === "section") {
      if (slot.teacher_name) subParts.push(slot.teacher_name);
    } else {
      subParts.push(slot.section_name);
    }
    if (slot.resource_name) subParts.push(slot.resource_name);
    const clickable = state.isAdmin ? `data-slot-id="${slot.id}"` : "";
    return `<div class="tt-cell ${kindClass}" ${clickable} title="${state.isAdmin ? "Click to edit" : ""}">
      ${slot.is_locked ? `<span class="tt-lock">🔒</span>` : ""}
      <span class="tt-title">${title || "—"}</span>
      ${subParts.map((s) => `<span class="tt-sub">${s}</span>`).join("")}
    </div>`;
  }

  function openEditModal(slot) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    const kind = slot.kind === "activity" ? "activity" : "subject";

    const subjectOpts = state.subjects.map((s) => `<option value="${s.id}" ${s.id === slot.subject_id ? "selected" : ""}>${s.name}</option>`).join("");
    const activityOpts = state.activities.map((a) => `<option value="${a.id}" ${a.id === slot.activity_id ? "selected" : ""}>${a.name}</option>`).join("");
    const teacherOpts = `<option value="">— none —</option>` + state.teachers.map((t) => `<option value="${t.id}" ${t.id === slot.teacher_id ? "selected" : ""}>${t.name}</option>`).join("");
    const resourceOpts = `<option value="">— none —</option>` + state.resources.map((r) => `<option value="${r.id}" ${r.id === slot.resource_id ? "selected" : ""}>${r.name}</option>`).join("");
    const dayOpts = DAY_NAMES.slice(0, state.school.working_days).map((d, i) => `<option value="${i}" ${i === slot.day_of_week ? "selected" : ""}>${d}</option>`).join("");
    const periodOpts = Array.from({ length: state.school.periods_per_day }, (_, i) => i + 1)
      .map((p) => `<option value="${p}" ${p === slot.period ? "selected" : ""}>Period ${p}</option>`)
      .join("");

    const resourcesEnabled = state.config?.resources?.enabled !== false;
    const activitiesEnabled = state.config?.activities?.enabled === true;

    backdrop.innerHTML = `
      <div class="modal tt-modal">
        <h3>Edit slot — ${slot.section_name}</h3>
        <form id="ttEditForm">
          <label style="display: ${activitiesEnabled ? "block" : "none"}">Type</label>
          <select name="kind" style="display: ${activitiesEnabled ? "block" : "none"}">
            <option value="subject" ${kind === "subject" ? "selected" : ""}>Subject</option>
            <option value="activity" ${kind === "activity" ? "selected" : ""}>Activity</option>
          </select>

          <div id="ttSubjectField" style="display:${kind === "subject" ? "block" : "none"}">
            <label>Subject</label>
            <select name="subject_id">${subjectOpts}</select>
            <label>Teacher</label>
            <select name="teacher_id">${teacherOpts}</select>
          </div>

          <div id="ttActivityField" style="display:${kind === "activity" && activitiesEnabled ? "block" : "none"}">
            <label>Activity</label>
            <select name="activity_id">${activityOpts}</select>
          </div>

          <label style="display: ${resourcesEnabled ? "block" : "none"}">Resource / Room</label>
          <select name="resource_id" style="display: ${resourcesEnabled ? "block" : "none"}">${resourceOpts}</select>

          <label>Day</label>
          <select name="day_of_week">${dayOpts}</select>

          <label>Period</label>
          <select name="period">${periodOpts}</select>

          <div class="msg" id="ttFormMsg"></div>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" id="ttLockBtn">${slot.is_locked ? "🔓 Unlock" : "🔒 Lock"}</button>
            <div style="flex:1"></div>
            <button type="button" class="btn btn-ghost" id="ttCancelBtn">Cancel</button>
            <button type="submit" class="btn btn-primary">Save</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(backdrop);

    const kindSelect = backdrop.querySelector('select[name="kind"]');
    kindSelect.addEventListener("change", () => {
      const isSubject = kindSelect.value === "subject";
      backdrop.querySelector("#ttSubjectField").style.display = isSubject ? "block" : "none";
      backdrop.querySelector("#ttActivityField").style.display = isSubject ? "none" : "block";
    });

    backdrop.querySelector("#ttCancelBtn").addEventListener("click", () => backdrop.remove());

    backdrop.querySelector("#ttLockBtn").addEventListener("click", async () => {
      try {
        await apiRequest(`/timetables/${slot.id}/lock?locked=${!slot.is_locked}`, { method: "PATCH" });
        backdrop.remove();
        loadGrid();
      } catch (err) {
        const msg = backdrop.querySelector("#ttFormMsg");
        msg.className = "msg error";
        msg.textContent = err.message;
      }
    });

    backdrop.querySelector("#ttEditForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const isSubject = form.get("kind") === "subject";
      const body = {
        subject_id: isSubject && form.get("subject_id") ? Number(form.get("subject_id")) : null,
        teacher_id: isSubject && form.get("teacher_id") ? Number(form.get("teacher_id")) : null,
        activity_id: !isSubject && form.get("activity_id") ? Number(form.get("activity_id")) : null,
        resource_id: form.get("resource_id") ? Number(form.get("resource_id")) : null,
        day_of_week: Number(form.get("day_of_week")),
        period: Number(form.get("period")),
      };
      try {
        await apiRequest(`/timetables/${slot.id}`, { method: "PUT", body });
        backdrop.remove();
        loadGrid();
      } catch (err) {
        const msg = backdrop.querySelector("#ttFormMsg");
        msg.className = "msg error";
        msg.textContent = err.message;
      }
    });
  }

  // -------------------------------------------------------------------------
  // PDF export (browser print-to-PDF). Five scopes: current section, current
  // teacher, whole grade, all sections, all teachers. Each scope collects one
  // or more grids and renders them into a clean printable document with a
  // page break per grid, then triggers the browser's print / Save-as-PDF.
  // -------------------------------------------------------------------------
  const vParamStr = () => (state.selectedVersionId ? `?version_id=${state.selectedVersionId}` : "");

  function currentSection() {
    return state.sections.find((s) => s.id === state.selectedSectionId) || null;
  }
  function currentClass() {
    return state.classes.find((c) => c.id === state.selectedClassId) || null;
  }
  function currentTeacher() {
    return state.teachers.find((t) => t.id === state.selectedTeacherId) || null;
  }
  const sectionLabel = (sec) => `${sec.class_name || ""} ${sec.name}`.trim();

  function openExportModal() {
    const sec = currentSection();
    const cls = currentClass();
    const tch = currentTeacher();
    const versionNote = state.selectedVersionId
      ? (state.versions.find((v) => v.id === state.selectedVersionId)?.name || "selected version")
      : "Active (Master)";

    const opt = (id, title, sub, disabled) => `
      <button type="button" class="btn btn-ghost" id="${id}" ${disabled ? "disabled" : ""}
        style="display:flex; flex-direction:column; align-items:flex-start; gap:2px; text-align:left; width:100%; padding:12px 14px; height:auto; margin-bottom:8px; ${disabled ? "opacity:.5" : ""}">
        <span style="font-weight:700">${title}</span>
        <span style="font-size:12px; color:var(--muted)">${sub}</span>
      </button>`;

    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal" style="max-width:440px">
        <h3>Export timetable as PDF</h3>
        <p style="color:var(--muted); font-size:13px; margin:6px 0 14px">
          Source: <b>${versionNote}</b>. Your browser's print dialog opens — choose
          <b>“Save as PDF”</b> as the destination.
        </p>
        ${opt("expSection", "This section", sec ? `${sectionLabel(sec)} timetable` : "No section selected", !sec)}
        ${opt("expGrade", "This whole grade", cls ? `All sections of Grade ${cls.name}` : "No class selected", !cls)}
        ${opt("expTeacher", "This teacher", tch ? `${tch.name}'s timetable` : "No teacher selected", !tch)}
        ${opt("expAllSections", "All sections", `Every section (${state.sections.length}), one per page`, !state.sections.length)}
        ${opt("expAllTeachers", "All teachers", `Every teacher (${state.teachers.length}), one per page`, !state.teachers.length)}
        <div class="modal-actions" style="margin-top:4px">
          <button type="button" class="btn btn-ghost" id="expCancel">Cancel</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    const close = () => backdrop.remove();
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    backdrop.querySelector("#expCancel").addEventListener("click", close);

    const run = async (fn) => { close(); try { await fn(); } catch (err) { showAlert("error", err.message); } };
    backdrop.querySelector("#expSection")?.addEventListener("click", () => run(exportSection));
    backdrop.querySelector("#expGrade")?.addEventListener("click", () => run(exportGrade));
    backdrop.querySelector("#expTeacher")?.addEventListener("click", () => run(exportTeacher));
    backdrop.querySelector("#expAllSections")?.addEventListener("click", () => run(exportAllSections));
    backdrop.querySelector("#expAllTeachers")?.addEventListener("click", () => run(exportAllTeachers));
  }

  async function fetchSectionSlots(sectionId) {
    return (await apiRequest(`/timetables/section/${sectionId}${vParamStr()}`)).slots || [];
  }
  async function fetchTeacherSlots(teacherId) {
    return (await apiRequest(`/timetables/teacher/${teacherId}${vParamStr()}`)).slots || [];
  }

  async function exportSection() {
    const sec = currentSection();
    if (!sec) return;
    const slots = await fetchSectionSlots(sec.id);
    openPrintable(`Timetable — ${sectionLabel(sec)}`, [{ heading: sectionLabel(sec), slots }], "section");
  }

  async function exportGrade() {
    const cls = currentClass();
    if (!cls) return;
    const secs = state.sections.filter((s) => s.class_id === cls.id);
    const grids = await Promise.all(
      secs.map(async (s) => ({ heading: sectionLabel(s), slots: await fetchSectionSlots(s.id) }))
    );
    openPrintable(`Grade ${cls.name} — Timetables`, grids, "section");
  }

  async function exportTeacher() {
    const tch = currentTeacher();
    if (!tch) return;
    const slots = await fetchTeacherSlots(tch.id);
    openPrintable(`Timetable — ${tch.name}`, [{ heading: tch.name, slots }], "teacher");
  }

  async function exportAllSections() {
    const secs = [...state.sections].sort((a, b) => sectionLabel(a).localeCompare(sectionLabel(b), undefined, { numeric: true }));
    const grids = await Promise.all(
      secs.map(async (s) => ({ heading: sectionLabel(s), slots: await fetchSectionSlots(s.id) }))
    );
    openPrintable("All Section Timetables", grids, "section");
  }

  async function exportAllTeachers() {
    const teachers = [...state.teachers].sort((a, b) => a.name.localeCompare(b.name));
    const grids = await Promise.all(
      teachers.map(async (t) => ({ heading: t.name, slots: await fetchTeacherSlots(t.id) }))
    );
    openPrintable("All Teacher Timetables", grids, "teacher");
  }

  function escHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function printGridTable(slots, viewMode) {
    const periodsPerDay = state.school.periods_per_day || 8;
    const workingDays = state.school.working_days || 5;
    const days = DAY_NAMES.slice(0, workingDays);
    const byDayPeriod = {};
    (slots || []).forEach((s) => { byDayPeriod[`${s.day_of_week}_${s.period}`] = s; });

    const cell = (slot) => {
      if (!slot) return `<td class="free">—</td>`;
      const isAct = slot.kind === "activity";
      const title = isAct ? slot.activity_name : slot.subject_name;
      const sub = [];
      if (viewMode === "section") { if (slot.teacher_name) sub.push(slot.teacher_name); }
      else if (slot.section_name) sub.push(slot.section_name);
      if (slot.resource_name) sub.push(slot.resource_name);
      return `<td class="${isAct ? "act" : "sub"}">
        <div class="t">${slot.is_locked ? "🔒 " : ""}${escHtml(title || "—")}</div>
        ${sub.map((s) => `<div class="s">${escHtml(s)}</div>`).join("")}
      </td>`;
    };

    let html = `<table class="tt"><thead><tr><th class="ph">Period</th>${days.map((d) => `<th>${d}</th>`).join("")}</tr></thead><tbody>`;
    for (let p = 1; p <= periodsPerDay; p++) {
      html += `<tr><td class="ph">P${p}</td>`;
      for (let d = 0; d < workingDays; d++) html += cell(byDayPeriod[`${d}_${p}`]);
      html += `</tr>`;
    }
    return html + `</tbody></table>`;
  }

  function openPrintable(docTitle, grids, viewMode) {
    if (!grids.length) { showAlert("info", "Nothing to export."); return; }
    const w = window.open("", "_blank");
    if (!w) { showAlert("error", "Please allow pop-ups for this site to export the timetable as PDF."); return; }

    const schoolName = escHtml(state.school?.name || "School");
    const printedOn = new Date().toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
    const pages = grids.map((g) => `
      <section class="page">
        <div class="phead">
          <div><h1>${schoolName}</h1><div class="scope">${escHtml(g.heading)}</div></div>
          <div class="meta">${escHtml(docTitle)}<br>Generated ${printedOn}</div>
        </div>
        ${printGridTable(g.slots, viewMode)}
      </section>`).join("");

    const css = `
      @page { size: A4 landscape; margin: 10mm; }
      * { box-sizing: border-box; }
      body { font-family: 'Segoe UI', system-ui, sans-serif; color: #1e293b; margin: 0; }
      .page { page-break-after: always; }
      .page:last-child { page-break-after: auto; }
      .phead { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-bottom: 12px; }
      .phead h1 { font-size: 18px; margin: 0; }
      .scope { font-size: 15px; font-weight: 600; color: #2563eb; margin-top: 2px; }
      .meta { font-size: 11px; color: #64748b; text-align: right; }
      table.tt { width: 100%; border-collapse: collapse; table-layout: fixed; }
      table.tt th, table.tt td { border: 1px solid #cbd5e1; padding: 5px 6px; vertical-align: top; }
      table.tt th { background: #eff6ff; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #475569; text-align: center; }
      table.tt td.ph, table.tt th.ph { width: 54px; background: #f1f5f9; font-weight: 700; font-size: 11px; text-align: center; color: #475569; vertical-align: middle; }
      table.tt td.sub { background: #f8fbff; }
      table.tt td.act { background: #fdf4ff; }
      table.tt td.free { color: #cbd5e1; text-align: center; }
      table.tt td .t { font-size: 12px; font-weight: 700; }
      table.tt td .s { font-size: 10px; color: #64748b; }
      .hint { font-size: 11px; color: #94a3b8; padding: 8px 0; }
      @media print { .hint { display: none; } }
    `;
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${escHtml(docTitle)}</title><style>${css}</style></head>
      <body>
        <div class="hint">Choose “Save as PDF” in the print dialog. This banner won't appear in the PDF.</div>
        ${pages}
        <script>window.onload=function(){setTimeout(function(){window.focus();window.print();},250);};<\/script>
      </body></html>`);
    w.document.close();
  }
}
