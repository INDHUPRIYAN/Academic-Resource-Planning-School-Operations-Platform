// Teacher Availability and Preferences page logic

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

document.addEventListener("DOMContentLoaded", () => {
  initAvailabilityPage();
});

async function initAvailabilityPage() {
  const state = {
    me: null,
    school: null,
    teachers: [],
    selectedTeacherId: null,
    availGrid: {}, // key: "day-period" -> boolean (true=avail, false=blocked)
    preferences: []
  };

  try {
    state.me = await apiRequest("/auth/me");
    let schoolId = state.me.school_id;

    if (state.me.role === "super_admin") {
      const stored = localStorage.getItem("active_school_id");
      if (stored) {
        schoolId = parseInt(stored);
      } else {
        const schools = (await apiRequest("/schools?limit=1")).items;
        if (schools.length) schoolId = schools[0].id;
      }
    }

    if (!schoolId) {
      showMsg("error", "No school context active. Please create or configure a school first.");
      return;
    }

    // Load school details to know working days and periods
    state.school = await apiRequest(`/schools/${schoolId}`);
    
    // Load teachers
    const teachersRes = await apiRequest(`/teachers?limit=200`);
    state.teachers = teachersRes.items || [];

    // Setup form selectors
    setupPrefFormSelectors(state.school.periods_per_day);

    // Check user role
    if (state.me.role === "teacher") {
      // Find the teacher profile associated with current user
      const currentTeacher = state.teachers.find(t => t.email === state.me.email);
      if (!currentTeacher) {
        showMsg("error", "Your user account is not linked to a teacher profile.");
        return;
      }
      state.selectedTeacherId = currentTeacher.id;
      document.getElementById("teacherSelectorWrap").style.display = "none";
      loadTeacherData(state.selectedTeacherId);
    } else {
      // Admin view: show selector
      if (!state.teachers.length) {
        showMsg("info", "No teachers found. Register teachers before configuring availability.");
        return;
      }
      
      const select = document.getElementById("teacherSelect");
      select.innerHTML = state.teachers.map(t => `<option value="${t.id}">${t.name} (${t.department || "No Dept"})</option>`).join("");
      document.getElementById("teacherSelectorWrap").style.display = "block";
      
      select.addEventListener("change", () => {
        state.selectedTeacherId = parseInt(select.value);
        loadTeacherData(state.selectedTeacherId);
      });
      
      state.selectedTeacherId = parseInt(select.value);
      loadTeacherData(state.selectedTeacherId);
    }

  } catch (err) {
    showMsg("error", "Failed to initialize page: " + err.message);
  }

  // Setup grid bulk options
  document.getElementById("markAllAvailableBtn").addEventListener("click", () => {
    setAllGridValue(true);
  });
  document.getElementById("markAllBlockedBtn").addEventListener("click", () => {
    setAllGridValue(false);
  });
  document.getElementById("saveAvailabilityBtn").addEventListener("click", () => {
    saveGridData(state.selectedTeacherId);
  });

  // Setup add preference form
  const prefTypeSelect = document.getElementById("prefType");
  prefTypeSelect.addEventListener("change", () => {
    const val = prefTypeSelect.value;
    document.getElementById("prefDayField").style.display = (val === "max_daily") ? "none" : "block";
    document.getElementById("prefPeriodField").style.display = (val === "preferred_period" || val === "avoid_period") ? "block" : "none";
    document.getElementById("prefValueField").style.display = (val === "max_daily") ? "block" : "none";
    document.getElementById("prefWeightField").style.display = (val === "max_daily") ? "none" : "block";
  });

  document.getElementById("addPrefForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.selectedTeacherId) return;

    const payload = {
      preference_type: document.getElementById("prefType").value,
      day_of_week: document.getElementById("prefDayField").style.display !== "none" ? parseInt(document.getElementById("prefDay").value) : null,
      period: document.getElementById("prefPeriodField").style.display !== "none" ? parseInt(document.getElementById("prefPeriod").value) : null,
      value: document.getElementById("prefValueField").style.display !== "none" ? parseInt(document.getElementById("prefValue").value) : null,
      weight: document.getElementById("prefWeightField").style.display !== "none" ? parseInt(document.getElementById("prefWeight").value) : 1
    };

    try {
      await apiRequest(`/teachers/${state.selectedTeacherId}/preferences`, {
        method: "POST",
        body: payload
      });
      showMsg("success", "Preference added successfully");
      loadPreferences(state.selectedTeacherId);
      document.getElementById("addPrefForm").reset();
      // Trigger preference type change to reset fields visibility
      prefTypeSelect.dispatchEvent(new Event("change"));
    } catch (err) {
      showMsg("error", "Failed to add preference: " + err.message);
    }
  });

  async function loadTeacherData(teacherId) {
    if (!teacherId) return;
    
    // Clear alert message
    document.getElementById("alertBox").style.display = "none";

    try {
      // 1. Fetch availability
      const availList = await apiRequest(`/teachers/${teacherId}/availability`);
      state.availGrid = {};
      availList.forEach(a => {
        state.availGrid[`${a.day_of_week}-${a.period}`] = a.is_available;
      });

      // 2. Fetch preferences
      loadPreferences(teacherId);

      // 3. Render grid
      renderGrid(state.school.working_days, state.school.periods_per_day);

    } catch (err) {
      showMsg("error", "Failed to load teacher availability settings: " + err.message);
    }
  }

  async function loadPreferences(teacherId) {
    const listDiv = document.getElementById("preferencesList");
    listDiv.innerHTML = `<div style="font-size:12px; color:var(--muted)">Loading preferences...</div>`;
    
    try {
      state.preferences = await apiRequest(`/teachers/${teacherId}/preferences`);
      if (!state.preferences.length) {
        listDiv.innerHTML = `<div style="font-size:12px; color:var(--muted); padding: 8px 0;">No soft constraints or preferences added yet.</div>`;
        return;
      }

      listDiv.innerHTML = state.preferences.map(p => {
        let desc = "";
        if (p.preference_type === "preferred_period") {
          desc = `Prefers <strong>Period ${p.period}</strong> on <strong>${WEEKDAYS[p.day_of_week]}</strong> (Weight: ${p.weight})`;
        } else if (p.preference_type === "avoid_period") {
          desc = `Avoid <strong>Period ${p.period}</strong> on <strong>${WEEKDAYS[p.day_of_week]}</strong> (Weight: ${p.weight})`;
        } else if (p.preference_type === "preferred_day") {
          desc = `Prefers working on <strong>${WEEKDAYS[p.day_of_week]}</strong> (Weight: ${p.weight})`;
        } else if (p.preference_type === "avoid_day") {
          desc = `Avoid scheduling on <strong>${WEEKDAYS[p.day_of_week]}</strong> (Weight: ${p.weight})`;
        } else if (p.preference_type === "max_daily") {
          desc = `Hard constraint: max <strong>${p.value} periods</strong> per day`;
        }

        return `
          <div class="preference-row">
            <span>${desc}</span>
            <button class="btn btn-ghost" style="padding: 2px 6px; font-size: 11px; color: var(--red)" onclick="deletePreference(${teacherId}, ${p.id})">Remove</button>
          </div>
        `;
      }).join("");

    } catch (err) {
      listDiv.innerHTML = `<div style="font-size:12px; color:var(--red)">Failed to load preferences: ${err.message}</div>`;
    }
  }

  // Expose deletePreference globally
  window.deletePreference = async (teacherId, prefId) => {
    if (!confirm("Are you sure you want to remove this preference?")) return;
    try {
      await apiRequest(`/teachers/${teacherId}/preferences/${prefId}`, {
        method: "DELETE"
      });
      showMsg("success", "Preference removed successfully");
      loadPreferences(teacherId);
    } catch (err) {
      showMsg("error", "Failed to delete preference: " + err.message);
    }
  };

  function renderGrid(workingDays, periodsPerDay) {
    // Header
    const headerRow = document.getElementById("gridHeader");
    headerRow.innerHTML = "<th>Day</th>" + Array.from({ length: periodsPerDay }, (_, i) => `<th>Period ${i + 1}</th>`).join("");

    // Body
    const body = document.getElementById("gridBody");
    body.innerHTML = "";

    for (let d = 0; d < workingDays; d++) {
      const row = document.createElement("tr");
      
      const dayCell = document.createElement("td");
      dayCell.innerHTML = `<strong>${WEEKDAYS[d] || ("Day " + (d + 1))}</strong>`;
      row.appendChild(dayCell);

      for (let p = 1; p <= periodsPerDay; p++) {
        const cell = document.createElement("td");
        const isAvail = state.availGrid[`${d}-${p}`] !== false; // Default to true if not set
        
        const toggle = document.createElement("div");
        toggle.className = `cell-toggle ${isAvail ? "available" : "blocked"}`;
        toggle.id = `cell-${d}-${p}`;
        toggle.textContent = isAvail ? "Available" : "Blocked";
        
        toggle.addEventListener("click", () => {
          const current = state.availGrid[`${d}-${p}`] !== false;
          const nextVal = !current;
          state.availGrid[`${d}-${p}`] = nextVal;
          
          toggle.className = `cell-toggle ${nextVal ? "available" : "blocked"}`;
          toggle.textContent = nextVal ? "Available" : "Blocked";
        });

        cell.appendChild(toggle);
        row.appendChild(cell);
      }
      
      body.appendChild(row);
    }
  }

  function setAllGridValue(value) {
    const workingDays = state.school.working_days;
    const periodsPerDay = state.school.periods_per_day;

    for (let d = 0; d < workingDays; d++) {
      for (let p = 1; p <= periodsPerDay; p++) {
        state.availGrid[`${d}-${p}`] = value;
        const el = document.getElementById(`cell-${d}-${p}`);
        if (el) {
          el.className = `cell-toggle ${value ? "available" : "blocked"}`;
          el.textContent = value ? "Available" : "Blocked";
        }
      }
    }
  }

  async function saveGridData(teacherId) {
    if (!teacherId) return;

    const workingDays = state.school.working_days;
    const periodsPerDay = state.school.periods_per_day;

    const payload = [];
    for (let d = 0; d < workingDays; d++) {
      for (let p = 1; p <= periodsPerDay; p++) {
        const isAvail = state.availGrid[`${d}-${p}`] !== false;
        payload.push({
          day_of_week: d,
          period: p,
          is_available: isAvail
        });
      }
    }

    try {
      await apiRequest(`/teachers/${teacherId}/availability`, {
        method: "PUT",
        body: payload
      });
      showMsg("success", "Availability grid saved successfully.");
    } catch (err) {
      showMsg("error", "Failed to save availability: " + err.message);
    }
  }

  function setupPrefFormSelectors(periodsPerDay) {
    const periodSelect = document.getElementById("prefPeriod");
    periodSelect.innerHTML = Array.from({ length: periodsPerDay }, (_, i) => `<option value="${i + 1}">Period ${i + 1}</option>`).join("");
  }
}

function showMsg(type, text) {
  const alertBox = document.getElementById("alertBox");
  alertBox.className = `msg ${type === "error" ? "error" : "success"}`;
  alertBox.textContent = text;
  alertBox.style.display = "block";
  
  // Auto-scroll to alert
  alertBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
