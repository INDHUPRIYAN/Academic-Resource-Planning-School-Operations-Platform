/* Classes & Sections manager.
   Add a class -> immediately asked which sections it has, each with a medium and
   an optional class teacher. Everything is thin: the backend validates and owns
   the rules. */

const CX = {
  schoolId: null,
  role: null,
  schools: [],
  classes: [],
  sectionsByClass: {},
  teachers: [],
  mediums: [],
  mediumsEnabled: false,
};

/* The naming convention (A / A1 / A2 => English) is a per-school habit, not a
   platform rule, so it only ever *suggests* a value the admin can override. */
function suggestMedium(sectionName) {
  if (!CX.mediums.length) return "";
  const first = (sectionName || "").trim().charAt(0).toUpperCase();
  const english = CX.mediums.find((m) => /english/i.test(m));
  const other = CX.mediums.find((m) => !/english/i.test(m));
  if (first === "A") return english || CX.mediums[0];
  if (first) return other || CX.mediums[CX.mediums.length - 1];
  return "";
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function initClassesPage() {
  const me = await apiRequest("/auth/me");
  CX.role = me.role;
  CX.schoolId = me.school_id;

  if (me.role === "super_admin") {
    const stored = localStorage.getItem("active_school_id");
    CX.schools = (await apiRequest("/schools?limit=100")).items;
    CX.schoolId = stored ? parseInt(stored) : CX.schools[0]?.id ?? null;
  }
  if (!CX.schoolId) {
    document.getElementById("classesRoot").innerHTML =
      `<div class="empty-state">No school found. Create a school first.</div>`;
    return;
  }

  await loadConfig();
  await loadTeachers();
  render();
  await loadClasses();
}

async function loadConfig() {
  try {
    const wrapper = await apiRequest(`/schools/${CX.schoolId}/config`);
    const cfg = JSON.parse(wrapper.config);
    const m = cfg.mediums || {};
    CX.mediumsEnabled = m.enabled === true;
    CX.mediums = Array.isArray(m.list) ? m.list : [];
  } catch (e) {
    CX.mediumsEnabled = false;
    CX.mediums = [];
  }
}

async function loadTeachers() {
  try {
    const res = await apiRequest("/teachers?limit=200");
    CX.teachers = res.items.filter((t) => t.school_id === CX.schoolId);
  } catch (e) {
    CX.teachers = [];
  }
}

function teacherOptions(selectedId) {
  const opts = CX.teachers
    .map((t) => `<option value="${t.id}" ${t.id === selectedId ? "selected" : ""}>${esc(t.name)}</option>`)
    .join("");
  return `<option value="">— none —</option>${opts}`;
}

function mediumOptions(selected) {
  if (!CX.mediums.length) return "";
  return (
    `<option value="">— not set —</option>` +
    CX.mediums
      .map((m) => `<option value="${esc(m)}" ${m === selected ? "selected" : ""}>${esc(m)}</option>`)
      .join("")
  );
}

function render() {
  const schoolPicker =
    CX.role === "super_admin"
      ? `<select id="schoolPicker" class="cx-select">
           ${CX.schools.map((s) => `<option value="${s.id}" ${s.id === CX.schoolId ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
         </select>`
      : "";

  document.getElementById("classesRoot").innerHTML = `
    <div class="toolbar">
      ${schoolPicker}
      <button class="btn btn-primary" id="addClassBtn">+ Add Class</button>
    </div>
    ${CX.mediumsEnabled ? "" : `<div class="cx-hint">Mediums are turned off for this school. Enable them in <a href="config_editor.html">Config Editor</a> to tag sections as English / Tamil.</div>`}
    <div id="classList"><div class="loading-state">Loading classes…</div></div>`;

  document.getElementById("addClassBtn").addEventListener("click", openClassModal);
  const picker = document.getElementById("schoolPicker");
  if (picker) {
    picker.addEventListener("change", async () => {
      CX.schoolId = parseInt(picker.value);
      localStorage.setItem("active_school_id", String(CX.schoolId));
      await loadConfig();
      await loadTeachers();
      await loadClasses();
    });
  }
}

async function loadClasses() {
  const list = document.getElementById("classList");
  list.innerHTML = `<div class="loading-state">Loading classes…</div>`;
  try {
    const res = await apiRequest(`/classes?limit=100&school_id=${CX.schoolId}`);
    CX.classes = res.items.filter((c) => c.school_id === CX.schoolId);

    const secRes = await apiRequest(`/sections?limit=200&school_id=${CX.schoolId}`);
    CX.sectionsByClass = {};
    secRes.items.forEach((s) => {
      (CX.sectionsByClass[s.class_id] = CX.sectionsByClass[s.class_id] || []).push(s);
    });

    renderClassList();
  } catch (e) {
    list.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
  }
}

function renderClassList() {
  const list = document.getElementById("classList");
  if (!CX.classes.length) {
    list.innerHTML = `<div class="empty-state">No classes yet. Click “+ Add Class” to begin — you’ll be asked which sections it has.</div>`;
    return;
  }

  list.innerHTML = CX.classes
    .map((c) => {
      const secs = CX.sectionsByClass[c.id] || [];
      const rows = secs.length
        ? secs
            .map(
              (s) => `<tr>
                <td><strong>${esc(c.name)} ${esc(s.name)}</strong></td>
                <td>${s.medium ? `<span class="medium-badge ${/english/i.test(s.medium) ? "eng" : "reg"}">${esc(s.medium)}</span>` : `<span class="cx-muted">—</span>`}</td>
                <td>${s.class_teacher_name ? esc(s.class_teacher_name) : `<span class="cx-muted">not assigned</span>`}</td>
                <td class="cx-right">
                  <button class="btn btn-ghost cx-sm" data-edit-section="${s.id}">Edit</button>
                  <button class="btn btn-danger cx-sm" data-del-section="${s.id}">Delete</button>
                </td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="4" class="cx-muted">No sections yet.</td></tr>`;

      return `<div class="card cx-class-card">
        <div class="cx-class-head">
          <h3>${esc(c.name)} <span class="cx-count">${secs.length} section${secs.length === 1 ? "" : "s"}</span></h3>
          <div>
            <button class="btn btn-ghost cx-sm" data-add-sections="${c.id}">+ Add Sections</button>
            <button class="btn btn-danger cx-sm" data-del-class="${c.id}">Delete Class</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="cx-table">
            <thead><tr><th>Section</th><th>Medium</th><th>Class Teacher</th><th></th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
    })
    .join("");

  list.querySelectorAll("[data-add-sections]").forEach((b) =>
    b.addEventListener("click", () => openSectionsModal(parseInt(b.dataset.addSections)))
  );
  list.querySelectorAll("[data-del-class]").forEach((b) =>
    b.addEventListener("click", () => deleteClass(parseInt(b.dataset.delClass)))
  );
  list.querySelectorAll("[data-edit-section]").forEach((b) =>
    b.addEventListener("click", () => openEditSection(parseInt(b.dataset.editSection)))
  );
  list.querySelectorAll("[data-del-section]").forEach((b) =>
    b.addEventListener("click", () => deleteSection(parseInt(b.dataset.delSection)))
  );
}

/* ---------- modals ---------- */

function modal(html) {
  const back = document.createElement("div");
  back.className = "modal-backdrop";
  back.innerHTML = `<div class="modal cx-modal">${html}</div>`;
  document.body.appendChild(back);
  back.addEventListener("click", (e) => {
    if (e.target === back) back.remove();
  });
  return back;
}

/* Step 1: name the class. Step 2: it immediately asks for sections. */
function openClassModal() {
  const back = modal(`
    <h3>Add Class</h3>
    <label>Class name</label>
    <input id="newClassName" placeholder="e.g. Class 6" autofocus />
    <div class="cx-err" id="classErr"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="cxCancel">Cancel</button>
      <button class="btn btn-primary" id="cxNext">Next: Sections →</button>
    </div>`);

  back.querySelector("#cxCancel").addEventListener("click", () => back.remove());
  back.querySelector("#cxNext").addEventListener("click", async () => {
    const name = back.querySelector("#newClassName").value.trim();
    const err = back.querySelector("#classErr");
    if (!name) {
      err.textContent = "Class name is required.";
      return;
    }
    try {
      const cls = await apiRequest("/classes", {
        method: "POST",
        body: { name, school_id: CX.schoolId },
      });
      back.remove();
      await loadClasses();
      openSectionsModal(cls.id, name);
    } catch (e) {
      err.textContent = e.message;
    }
  });
}

function sectionRowHtml(idx, name = "", medium = "", teacherId = null) {
  return `<tr data-row="${idx}">
    <td><input class="cx-sec-name" value="${esc(name)}" placeholder="A" /></td>
    ${CX.mediums.length ? `<td><select class="cx-sec-medium">${mediumOptions(medium)}</select></td>` : ""}
    <td><select class="cx-sec-teacher">${teacherOptions(teacherId)}</select></td>
    <td class="cx-right"><button type="button" class="btn btn-ghost cx-sm cx-remove-row">✕</button></td>
  </tr>`;
}

function openSectionsModal(classId, className) {
  const cls = CX.classes.find((c) => c.id === classId);
  const title = className || cls?.name || "Class";

  const back = modal(`
    <h3>Sections for ${esc(title)}</h3>
    <p class="cx-sub">Add each section. ${CX.mediums.length ? "Medium is suggested from the section name — change it if needed." : ""}</p>
    <div class="table-wrap">
      <table class="cx-table">
        <thead><tr><th>Name</th>${CX.mediums.length ? "<th>Medium</th>" : ""}<th>Class Teacher</th><th></th></tr></thead>
        <tbody id="secRows"></tbody>
      </table>
    </div>
    <button type="button" class="btn btn-ghost cx-sm" id="cxAddRow">+ Add another section</button>
    <div class="cx-err" id="secErr"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="cxCancel">Cancel</button>
      <button class="btn btn-primary" id="cxSave">Save Sections</button>
    </div>`);

  const rows = back.querySelector("#secRows");
  let idx = 0;
  const addRow = () => {
    rows.insertAdjacentHTML("beforeend", sectionRowHtml(idx++));
    wireRows();
  };

  function wireRows() {
    rows.querySelectorAll(".cx-remove-row").forEach((b) => {
      b.onclick = () => {
        if (rows.children.length > 1) b.closest("tr").remove();
      };
    });
    // Suggest the medium as soon as a name is typed, but never overwrite a manual pick.
    rows.querySelectorAll(".cx-sec-name").forEach((inp) => {
      inp.oninput = () => {
        const tr = inp.closest("tr");
        const sel = tr.querySelector(".cx-sec-medium");
        if (sel && !sel.dataset.touched) sel.value = suggestMedium(inp.value);
      };
    });
    rows.querySelectorAll(".cx-sec-medium").forEach((sel) => {
      sel.onchange = () => (sel.dataset.touched = "1");
    });
  }

  addRow();
  back.querySelector("#cxAddRow").addEventListener("click", addRow);
  back.querySelector("#cxCancel").addEventListener("click", () => back.remove());

  back.querySelector("#cxSave").addEventListener("click", async () => {
    const err = back.querySelector("#secErr");
    err.textContent = "";
    const sections = [...rows.querySelectorAll("tr")]
      .map((tr) => ({
        name: tr.querySelector(".cx-sec-name").value.trim(),
        medium: tr.querySelector(".cx-sec-medium")?.value || null,
        class_teacher_id: tr.querySelector(".cx-sec-teacher").value
          ? parseInt(tr.querySelector(".cx-sec-teacher").value)
          : null,
      }))
      .filter((s) => s.name);

    if (!sections.length) {
      err.textContent = "Add at least one section.";
      return;
    }
    try {
      // One atomic call: all sections land, or none do.
      await apiRequest("/sections/bulk", { method: "POST", body: { class_id: classId, sections } });
      back.remove();
      await loadClasses();
    } catch (e) {
      err.textContent = e.message;
    }
  });
}

function openEditSection(sectionId) {
  const sec = Object.values(CX.sectionsByClass).flat().find((s) => s.id === sectionId);
  if (!sec) return;

  const back = modal(`
    <h3>Edit ${esc(sec.display_name || sec.name)}</h3>
    <label>Section name</label>
    <input id="edName" value="${esc(sec.name)}" />
    ${CX.mediums.length ? `<label>Medium</label><select id="edMedium">${mediumOptions(sec.medium)}</select>` : ""}
    <label>Class teacher</label>
    <select id="edTeacher">${teacherOptions(sec.class_teacher_id)}</select>
    <div class="cx-err" id="edErr"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="cxCancel">Cancel</button>
      <button class="btn btn-primary" id="cxSave">Save</button>
    </div>`);

  back.querySelector("#cxCancel").addEventListener("click", () => back.remove());
  back.querySelector("#cxSave").addEventListener("click", async () => {
    const err = back.querySelector("#edErr");
    const t = back.querySelector("#edTeacher").value;
    const body = {
      name: back.querySelector("#edName").value.trim(),
      medium: back.querySelector("#edMedium")?.value || null,
      class_teacher_id: t ? parseInt(t) : null,
    };
    if (!body.name) {
      err.textContent = "Section name is required.";
      return;
    }
    try {
      await apiRequest(`/sections/${sectionId}`, { method: "PUT", body });
      back.remove();
      await loadClasses();
    } catch (e) {
      err.textContent = e.message;
    }
  });
}

async function deleteSection(sectionId) {
  const sec = Object.values(CX.sectionsByClass).flat().find((s) => s.id === sectionId);
  if (!confirm(`Delete section ${sec?.display_name || ""}? This cannot be undone.`)) return;
  try {
    await apiRequest(`/sections/${sectionId}`, { method: "DELETE" });
    await loadClasses();
  } catch (e) {
    alert(e.message);
  }
}

async function deleteClass(classId) {
  const cls = CX.classes.find((c) => c.id === classId);
  const secs = CX.sectionsByClass[classId] || [];
  if (secs.length) {
    alert(`“${cls.name}” still has ${secs.length} section(s). Delete those first.`);
    return;
  }
  if (!confirm(`Delete ${cls.name}?`)) return;
  try {
    await apiRequest(`/classes/${classId}`, { method: "DELETE" });
    await loadClasses();
  } catch (e) {
    alert(e.message);
  }
}
