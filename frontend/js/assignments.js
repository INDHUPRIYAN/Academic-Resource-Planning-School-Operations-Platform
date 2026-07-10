// Assignments Management Logic
requireAuth();
renderTopbar("assignments.html");

const state = {
  me: null,
  schools: [],
  currentSchoolId: null,
  sections: [],
  subjects: [],
  teachers: [],
  assignments: [],
  editingId: null,
};

async function initAssignmentsPage() {
  state.me = await apiRequest("/auth/me");
  state.schools = (await apiRequest("/schools?limit=100")).items;

  if (state.me.role === "super_admin") {
    // Render school selector in toolbar
    const select = document.createElement("select");
    select.id = "schoolSelect";
    select.className = "toolbar-select";
    select.innerHTML = state.schools.map(s => `<option value="${s.id}">${s.name}</option>`).join("");
    
    const toolbar = document.getElementById("toolbarRoot");
    toolbar.insertBefore(select, document.getElementById("filterSection"));
    
    state.currentSchoolId = parseInt(select.value);
    select.addEventListener("change", async () => {
      state.currentSchoolId = parseInt(select.value);
      await loadMetadata();
      await loadAssignments();
    });
  } else {
    state.currentSchoolId = state.me.school_id;
  }

  await loadMetadata();
  await loadAssignments();

  // Setup event listeners
  document.getElementById("filterSection").addEventListener("change", loadAssignments);
  document.getElementById("addAssignmentBtn").addEventListener("click", () => openModal());
  document.getElementById("cancelModalBtn").addEventListener("click", closeModal);
  
  document.getElementById("assignmentForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveAssignment();
  });
}

async function loadMetadata() {
  const [classesRes, subjectsRes, teachersRes] = await Promise.all([
    apiRequest("/classes?limit=100"),
    apiRequest("/subjects?limit=100"),
    apiRequest("/teachers?limit=100"),
  ]);

  const schoolClasses = classesRes.items.filter(c => c.school_id === state.currentSchoolId);
  const classIds = schoolClasses.map(c => c.id);

  // Fetch sections for these classes
  const sectionsRes = await apiRequest("/sections?limit=100");
  state.sections = sectionsRes.items.filter(s => classIds.includes(s.class_id));
  
  state.subjects = subjectsRes.items.filter(s => s.school_id === state.currentSchoolId);
  state.teachers = teachersRes.items.filter(t => t.school_id === state.currentSchoolId);

  // Populate filters
  const filter = document.getElementById("filterSection");
  filter.innerHTML = `<option value="">All Sections</option>` + 
    state.sections.map(s => `<option value="${s.id}">${s.class_name || ""} ${s.name}</option>`).join("");

  // Populate modal dropdowns
  document.getElementById("modalSection").innerHTML = state.sections.map(s => `<option value="${s.id}">${s.class_name || ""} ${s.name}</option>`).join("");
  document.getElementById("modalSubject").innerHTML = state.subjects.map(s => `<option value="${s.id}">${s.name}</option>`).join("");
  document.getElementById("modalTeacher").innerHTML = `<option value="">-- Let Scheduler Assign Automatically --</option>` + 
    state.teachers.map(t => `<option value="${t.id}">${t.name} (${t.department || "No Dept"})</option>`).join("");
}

async function loadAssignments() {
  const tableWrap = document.getElementById("tableWrap");
  tableWrap.innerHTML = `<div class="loading-state">Loading assignments...</div>`;

  try {
    const secId = document.getElementById("filterSection").value;
    let url = `/assignments?limit=100`;
    if (secId) url += `&section_id=${secId}`;

    const res = await apiRequest(url);
    // Filter by school scope locally if needed
    state.assignments = res.items.filter(a => a.school_id === state.currentSchoolId);

    renderTable();
  } catch (err) {
    tableWrap.innerHTML = `<div class="empty-state">${err.message}</div>`;
  }
}

function renderTable() {
  const tableWrap = document.getElementById("tableWrap");
  if (!state.assignments.length) {
    tableWrap.innerHTML = `<div class="empty-state">No teacher assignments defined. Click "+ Add Assignment" to create one.</div>`;
    return;
  }

  const rows = state.assignments.map(a => {
    const teacherDisplay = a.teacher_name ? a.teacher_name : `<span style="color:var(--muted); font-style: italic;">Auto-Schedule (Hybrid)</span>`;
    return `
      <tr>
        <td><strong>${a.section_name || "Class Section"}</strong></td>
        <td>${a.subject_name || "Subject"}</td>
        <td>${teacherDisplay}</td>
        <td class="actions">
          <button class="btn btn-ghost" onclick="openModal(${a.id})">Edit</button>
          <button class="btn btn-danger" onclick="deleteAssignment(${a.id})">Delete</button>
        </td>
      </tr>
    `;
  }).join("");

  tableWrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Class & Section</th>
          <th>Subject</th>
          <th>Assigned Teacher</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}

function openModal(id = null) {
  state.editingId = id;
  const modal = document.getElementById("assignmentModal");
  const title = document.getElementById("modalTitle");
  const sectionField = document.getElementById("modalSectionField");
  const subjectField = document.getElementById("modalSubjectField");
  
  document.getElementById("modalMsg").style.display = "none";
  document.getElementById("assignmentForm").reset();

  if (id) {
    title.textContent = "Edit Subject Assignment";
    const assign = state.assignments.find(a => a.id === id);
    
    // In edit mode, hide class/subject dropdown selections to prevent key conflict errors, only allow changing teacher
    sectionField.style.display = "none";
    subjectField.style.display = "none";
    
    document.getElementById("modalTeacher").value = assign.teacher_id || "";
  } else {
    title.textContent = "Add Subject Assignment";
    sectionField.style.display = "block";
    subjectField.style.display = "block";
  }

  modal.style.display = "flex";
}

function closeModal() {
  document.getElementById("assignmentModal").style.display = "none";
}

async function saveAssignment() {
  const saveBtn = document.getElementById("saveAssignmentBtn");
  const msg = document.getElementById("modalMsg");
  msg.style.display = "none";
  saveBtn.disabled = true;

  try {
    const teacherId = document.getElementById("modalTeacher").value;
    const body = {
      teacher_id: teacherId ? parseInt(teacherId) : null
    };

    if (state.editingId) {
      await apiRequest(`/assignments/${state.editingId}`, {
        method: "PUT",
        body
      });
    } else {
      body.section_id = parseInt(document.getElementById("modalSection").value);
      body.subject_id = parseInt(document.getElementById("modalSubject").value);
      body.school_id = state.currentSchoolId;
      
      await apiRequest("/assignments", {
        method: "POST",
        body
      });
    }

    closeModal();
    await loadAssignments();
  } catch (err) {
    msg.className = "msg error";
    msg.textContent = err.message;
    msg.style.display = "block";
  } finally {
    saveBtn.disabled = false;
  }
}

async function deleteAssignment(id) {
  if (!confirm("Are you sure you want to delete this assignment?")) return;

  try {
    await apiRequest(`/assignments/${id}`, {
      method: "DELETE"
    });
    await loadAssignments();
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

window.openModal = openModal;
window.deleteAssignment = deleteAssignment;

initAssignmentsPage();
