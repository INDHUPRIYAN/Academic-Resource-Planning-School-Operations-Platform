// Configuration Editor JS Logic
let currentSchoolId = null;
let currentConfig = null;
let currentSchool = null;

async function initConfigEditor() {
  renderTopbar("config_editor.html");
  setupTabListeners();

  const msg = document.getElementById("messageRoot");
  const form = document.getElementById("configForm");

  try {
    const me = await apiRequest("/auth/me");
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
        <select id="configSchoolSelect" style="width:100%; padding:8px 10px; border:1px solid var(--border); border-radius:8px; font-size:13px; background:#fff;">
          ${schools.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}
        </select>
      `;
      const main = document.querySelector("main");
      main.insertBefore(selectorWrap, main.querySelector(".config-container"));

      const schoolSelect = document.getElementById("configSchoolSelect");
      schoolSelect.addEventListener("change", () => {
        currentSchoolId = parseInt(schoolSelect.value);
        loadSchoolConfig(currentSchoolId);
      });
      
      currentSchoolId = schools[0].id;
    } else {
      currentSchoolId = me.school_id;
    }

    if (!currentSchoolId) {
      showError("No school context found.");
      return;
    }

    // Load initial config
    await loadSchoolConfig(currentSchoolId);

    // Bind form submission
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await saveConfig();
    });

    // Bind template cards
    setupTemplateCards();

  } catch (err) {
    showError(err.message);
  }
}

function setupTabListeners() {
  const tabs = document.querySelectorAll(".config-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");

      const activeTab = tab.dataset.tab;
      const panels = document.querySelectorAll(".config-panel");
      panels.forEach(panel => {
        if (panel.id === `panel-${activeTab}`) {
          panel.classList.add("active");
        } else {
          panel.classList.remove("active");
        }
      });
    });
  });
}

async function loadSchoolConfig(schoolId) {
  clearMessage();
  try {
    currentSchool = await apiRequest(`/schools/${schoolId}`);
    const configWrapper = await apiRequest(`/schools/${schoolId}/config`);
    currentConfig = JSON.parse(configWrapper.config);

    // Populate General Tab
    document.getElementById("schoolName").value = currentSchool.name;
    document.getElementById("academicYear").value = currentConfig.academic_year || "2026-2027";
    document.getElementById("schoolType").value = currentConfig.school_type || "Other";
    document.getElementById("assignmentMethod").value = currentConfig.teacher_assignment_method || "automatic";

    // Populate Timings Tab
    renderPeriodTimings(currentSchool.periods_per_day, currentConfig.period_timings);

    // Populate Enabled Modules Tab
    const enabledModules = currentConfig.enabled_modules || ["timetables", "leaves", "swaps", "exams", "reports"];
    document.getElementById("mod-leaves").checked = enabledModules.includes("leaves");
    document.getElementById("mod-swaps").checked = enabledModules.includes("swaps");
    document.getElementById("mod-exams").checked = enabledModules.includes("exams");
    document.getElementById("mod-reports").checked = enabledModules.includes("reports");

    // Populate Scheduling Policies Tab
    const policies = currentConfig.scheduling_policies || {};
    document.getElementById("maxConsecutive").value = policies.max_consecutive_periods || 3;
    document.getElementById("maxDaily").value = policies.max_daily_periods || currentSchool.periods_per_day;
    document.getElementById("doublePeriods").checked = !!policies.double_periods_allowed;
    document.getElementById("sciencePractical").checked = !!policies.science_practical_consecutive;
    document.getElementById("petLastPeriods").checked = !!policies.pet_last_periods;
    document.getElementById("morningPreference").checked = !!policies.morning_preference;

    // Highlight Preset Templates Tab
    highlightActiveTemplate(currentConfig.school_type);

  } catch (err) {
    showError("Failed to load configuration: " + err.message);
  }
}

function renderPeriodTimings(periodsCount, timingsArray) {
  const container = document.getElementById("timingList");
  container.innerHTML = "";

  for (let i = 1; i <= periodsCount; i++) {
    const defaultStart = `0${8 + i - 1}:00`.slice(-5);
    const defaultEnd = `0${8 + i - 1}:45`.slice(-5);

    let startVal = defaultStart;
    let endVal = defaultEnd;

    if (timingsArray) {
      const match = timingsArray.find(t => t.period === i);
      if (match) {
        startVal = match.start;
        endVal = match.end;
      }
    }

    const item = document.createElement("div");
    item.className = "timing-item";
    item.innerHTML = `
      <span>Period ${i}</span>
      <label style="margin:0; font-size:12px; color:var(--muted)">Start:</label>
      <input type="time" class="time-start" data-period="${i}" value="${startVal}" required />
      <label style="margin:0; font-size:12px; color:var(--muted)">End:</label>
      <input type="time" class="time-end" data-period="${i}" value="${endVal}" required />
    `;
    container.appendChild(item);
  }
}

function highlightActiveTemplate(schoolType) {
  const cards = document.querySelectorAll(".template-card");
  cards.forEach(card => {
    const tName = card.dataset.template;
    if (schoolType && schoolType.toLowerCase().startsWith(tName.toLowerCase())) {
      card.classList.add("active");
    } else {
      card.classList.remove("active");
    }
  });
}

function setupTemplateCards() {
  const cards = document.querySelectorAll(".template-card");
  cards.forEach(card => {
    card.addEventListener("click", async () => {
      const tName = card.dataset.template;
      if (confirm(`Are you sure you want to apply the ${tName} preset? This will overwrite the current configuration settings.`)) {
        try {
          clearMessage();
          const btn = document.getElementById("saveBtn");
          btn.disabled = true;
          btn.textContent = "Applying Preset...";

          const res = await apiRequest(`/schools/${currentSchoolId}/apply-template`, {
            method: "POST",
            body: { template_name: tName }
          });

          showSuccess(`Preset template ${tName} applied successfully!`);
          await loadSchoolConfig(currentSchoolId);

          // Trigger navigation refresh
          if (typeof renderTopbar === "function") {
            const path = window.location.pathname.split("/").pop();
            renderTopbar(path);
          }
        } catch (err) {
          showError("Failed to apply preset template: " + err.message);
        } finally {
          const btn = document.getElementById("saveBtn");
          btn.disabled = false;
          btn.textContent = "Save Configuration";
        }
      }
    });
  });
}

async function saveConfig() {
  const saveBtn = document.getElementById("saveBtn");
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving...";
  clearMessage();

  try {
    // 1. Save School Name via School PUT
    const schoolName = document.getElementById("schoolName").value.trim();
    if (schoolName !== currentSchool.name) {
      await apiRequest(`/schools/${currentSchoolId}`, {
        method: "PUT",
        body: { name: schoolName }
      });
    }

    // 2. Assemble Timings
    const timingItems = document.querySelectorAll(".timing-item");
    const timings = Array.from(timingItems).map(item => {
      const startInput = item.querySelector(".time-start");
      const endInput = item.querySelector(".time-end");
      return {
        period: parseInt(startInput.dataset.period),
        start: startInput.value,
        end: endInput.value
      };
    });

    // 3. Assemble Enabled Modules
    const enabledModules = ["timetables"];
    if (document.getElementById("mod-leaves").checked) enabledModules.push("leaves");
    if (document.getElementById("mod-swaps").checked) enabledModules.push("swaps");
    if (document.getElementById("mod-exams").checked) enabledModules.push("exams");
    if (document.getElementById("mod-reports").checked) enabledModules.push("reports");

    // 4. Assemble Policies
    const policies = {
      max_consecutive_periods: parseInt(document.getElementById("maxConsecutive").value),
      max_daily_periods: parseInt(document.getElementById("maxDaily").value),
      double_periods_allowed: document.getElementById("doublePeriods").checked,
      science_practical_consecutive: document.getElementById("sciencePractical").checked,
      pet_last_periods: document.getElementById("petLastPeriods").checked,
      morning_preference: document.getElementById("morningPreference").checked
    };

    // 5. Assemble Config Payload
    const newConfig = {
      ...currentConfig,
      school_type: document.getElementById("schoolType").value,
      academic_year: document.getElementById("academicYear").value.trim(),
      teacher_assignment_method: document.getElementById("assignmentMethod").value,
      period_timings: timings,
      enabled_modules: enabledModules,
      scheduling_policies: policies
    };

    // Save configuration
    await apiRequest(`/schools/${currentSchoolId}/config`, {
      method: "PUT",
      body: {
        config: JSON.stringify(newConfig)
      }
    });

    showSuccess("Configuration settings saved successfully!");
    
    // Refresh local cache and UI
    await loadSchoolConfig(currentSchoolId);

    // Refresh navbar links if list changed
    if (typeof renderTopbar === "function") {
      const path = window.location.pathname.split("/").pop();
      renderTopbar(path);
    }

  } catch (err) {
    showError("Failed to save settings: " + err.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save Configuration";
  }
}

function clearMessage() {
  const root = document.getElementById("messageRoot");
  root.style.display = "none";
  root.className = "msg";
  root.textContent = "";
}

function showError(text) {
  const root = document.getElementById("messageRoot");
  root.className = "msg error";
  root.textContent = text;
  root.style.display = "block";
}

function showSuccess(text) {
  const root = document.getElementById("messageRoot");
  root.className = "msg success";
  root.textContent = text;
  root.style.display = "block";
}
