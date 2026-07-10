// Dashboard and Settings Page logic (Phase 8)

let currentSchoolId = null;

async function initDashboard() {
  try {
    if (typeof DynamicUI !== "undefined") {
      await DynamicUI.init();
    }
    const me = await apiRequest("/auth/me");
    const welcome = document.getElementById("welcome");
    welcome.textContent = `Welcome, ${me.name}`;

    const schools = (await apiRequest("/schools?limit=100")).items;
    
    if (me.role === "super_admin") {
      if (!schools.length) {
        document.querySelector("main").innerHTML = `<div class="empty-state">No schools exist yet. Create one in the Schools tab.</div>`;
        return;
      }
      
      // Inject School Selector at the top
      const selectorWrap = document.createElement("div");
      selectorWrap.style.cssText = "margin-bottom: 24px; max-width: 320px;";
      selectorWrap.innerHTML = `
        <label style="margin: 0 0 6px">Select Active School Context</label>
        <select id="dashboardSchoolSelect" style="width:100%; padding:8px 10px; border:1px solid var(--border); border-radius:8px; font-size:13px; background:#fff;">
          ${schools.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}
        </select>
      `;
      const main = document.querySelector("main");
      main.insertBefore(selectorWrap, main.querySelector(".kpi-grid"));

      const schoolSelect = document.getElementById("dashboardSchoolSelect");
      schoolSelect.addEventListener("change", () => {
        currentSchoolId = parseInt(schoolSelect.value);
        loadDashboardData(currentSchoolId);
      });
      
      currentSchoolId = schools[0].id;
    } else {
      currentSchoolId = me.school_id;
    }

    loadDashboardData(currentSchoolId);

    // Bind settings form submission
    document.getElementById("settingsForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = document.getElementById("settingsMsg");
      msg.className = "msg";
      
      const payload = {
        name: document.getElementById("schoolName").value,
        address: document.getElementById("schoolAddress").value || null,
        phone: document.getElementById("schoolPhone").value || null,
        periods_per_day: parseInt(document.getElementById("schoolPeriods").value),
        working_days: parseInt(document.getElementById("schoolWorkingDays").value)
      };

      try {
        await apiRequest(`/schools/${currentSchoolId}`, {
          method: "PUT",
          body: payload
        });
        msg.textContent = "School settings updated successfully!";
        msg.className = "msg success";
        loadDashboardData(currentSchoolId);
      } catch (err) {
        msg.textContent = err.message;
        msg.className = "msg error";
      }
    });

    // Bind refresh suggestions button
    document.getElementById("refreshSuggestionsBtn").addEventListener("click", () => {
      loadSuggestions(currentSchoolId);
    });

  } catch (e) {
    console.error(e);
  }
}

async function loadDashboardData(schoolId) {
  if (!schoolId) return;

  // Load School Settings details into form
  try {
    const school = await apiRequest(`/schools/${schoolId}`);
    document.getElementById("schoolName").value = school.name;
    document.getElementById("schoolAddress").value = school.address || "";
    document.getElementById("schoolPhone").value = school.phone || "";
    document.getElementById("schoolPeriods").value = school.periods_per_day;
    document.getElementById("schoolWorkingDays").value = school.working_days;
  } catch (err) {
    console.error("Failed to load school settings details:", err);
  }

  // Load KPIs
  try {
    // 1. Teacher workload kpi
    const wl = await apiRequest(`/reports/teacher-workload?school_id=${schoolId}`);
    document.getElementById("statTeachers").textContent = wl.summary.teacher_count;
    document.getElementById("statOverloaded").textContent = wl.summary.overloaded_count;

    // 2. Subject coverage kpi
    const cov = await apiRequest(`/reports/subject-coverage?school_id=${schoolId}`);
    
    // Count unique sections from rows
    const sectionNames = new Set(cov.rows.map(r => r.section_name));
    document.getElementById("statSections").textContent = sectionNames.size;
    document.getElementById("statSectionsDesc").textContent = `${cov.summary.pair_count} subject assignments`;
    document.getElementById("statUnderCovered").textContent = cov.summary.under_covered_count;

    // 3. Leaves KPI if enabled
    if (typeof DynamicUI !== "undefined" && DynamicUI.isModuleEnabled("leaves")) {
      try {
        const leaves = await apiRequest(`/leaves?status=pending&limit=100`);
        document.getElementById("statLeaves").textContent = leaves.total ?? (leaves.items ? leaves.items.length : 0);
      } catch (e) {
        document.getElementById("statLeaves").textContent = "0";
      }
    }

    // 4. Exams KPI if enabled
    if (typeof DynamicUI !== "undefined" && DynamicUI.isModuleEnabled("exams")) {
      try {
        const exams = await apiRequest(`/exams?limit=100`);
        document.getElementById("statExams").textContent = exams.total ?? (exams.items ? exams.items.length : 0);
      } catch (e) {
        document.getElementById("statExams").textContent = "0";
      }
    }

    // 5. Resources KPI if enabled
    if (typeof DynamicUI !== "undefined" && DynamicUI.isResourcesEnabled()) {
      try {
        const resources = await apiRequest(`/resources?limit=100`);
        document.getElementById("statResources").textContent = resources.total ?? (resources.items ? resources.items.length : 0);
      } catch (e) {
        document.getElementById("statResources").textContent = "0";
      }
    }

  } catch (err) {
    console.error("Failed to load dashboard KPIs:", err);
  }

  // Load Suggestions
  loadSuggestions(schoolId);
}

async function loadSuggestions(schoolId) {
  const box = document.getElementById("suggestionsBox");
  box.textContent = "Analyzing workload and scheduling data...";
  
  try {
    const data = await apiRequest(`/assistant/workload-suggestions?school_id=${schoolId}`);
    // Replace newlines with breaks or render markdown-like formatting in a simple way
    box.innerHTML = data.suggestions.replace(/\n/g, "<br>");
  } catch (err) {
    box.textContent = `Could not load suggestions: ${err.message}`;
  }
}

requireAuth();
renderTopbar("dashboard.html");
initDashboard();
