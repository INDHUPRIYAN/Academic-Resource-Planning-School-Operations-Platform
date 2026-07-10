let currentSchoolId = null;
let validationReport = null;
let activeTab = "All";

async function initHealthPage() {
  renderTopbar("health.html");

  const revalidateBtn = document.getElementById("revalidateBtn");
  revalidateBtn.addEventListener("click", async () => {
    if (currentSchoolId) {
      // Invalidate cache first
      try {
        await apiRequest(`/validation/school/${currentSchoolId}/invalidate`, { method: "POST" });
      } catch (e) {}
      await loadHealthReport(currentSchoolId);
    }
  });

  // Setup tab listeners
  document.getElementById("tabAll").addEventListener("click", () => selectTab("All"));
  document.getElementById("tabErrors").addEventListener("click", () => selectTab("Errors"));
  document.getElementById("tabWarnings").addEventListener("click", () => selectTab("Warnings"));
  document.getElementById("tabSuggestions").addEventListener("click", () => selectTab("Suggestions"));
  document.getElementById("tabInfo").addEventListener("click", () => selectTab("Info"));

  try {
    const me = await apiRequest("/auth/me");
    const schools = (await apiRequest("/schools?limit=100")).items;

    if (me.role === "super_admin") {
      if (!schools.length) {
        document.querySelector("main").innerHTML = `<div class="empty-state">No schools exist yet. Create one in the Schools tab.</div>`;
        return;
      }

      // School context selector
      const selectorWrap = document.createElement("div");
      selectorWrap.style.cssText = "margin-bottom: 24px; max-width: 320px;";
      selectorWrap.innerHTML = `
        <label style="margin: 0 0 6px">Select Active School Context</label>
        <select id="healthSchoolSelect" style="width:100%; padding:8px 10px; border:1px solid var(--border); border-radius:8px; font-size:13px; background:#fff;">
          ${schools.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}
        </select>
      `;
      const main = document.querySelector("main");
      main.insertBefore(selectorWrap, main.querySelector(".health-grid-layout"));

      const schoolSelect = document.getElementById("healthSchoolSelect");
      schoolSelect.addEventListener("change", () => {
        currentSchoolId = parseInt(schoolSelect.value);
        loadHealthReport(currentSchoolId);
      });

      currentSchoolId = schools[0].id;
    } else {
      currentSchoolId = me.school_id;
    }

    if (!currentSchoolId) {
      alert("No school context found.");
      return;
    }

    await loadHealthReport(currentSchoolId);

  } catch (err) {
    console.error(err);
  }
}

async function loadHealthReport(schoolId) {
  const gaugeVal = document.getElementById("gaugeValue");
  const gaugeMsg = document.getElementById("gaugeMessage");
  const gaugeCircle = document.getElementById("gaugeCircle");

  gaugeVal.textContent = "...";
  gaugeMsg.textContent = "Analyzing configuration...";
  gaugeCircle.style.background = `conic-gradient(#f1f5f9 0% 100%)`;

  try {
    const data = await apiRequest(`/validation/school/${schoolId}`);
    validationReport = data;
    
    // 1. Overall Readiness Score
    const score = data.readiness_score;
    gaugeVal.textContent = `${score}%`;

    let color = "var(--blue)";
    let msg = "Config Healthy";

    if (score === 100) {
      color = "var(--green)";
      msg = "Ready to Generate";
    } else if (score >= 70) {
      color = "#2563eb";
      msg = "Ready with Warnings";
    } else if (score >= 50) {
      color = "#eab308";
      msg = "Check Warnings";
    } else {
      color = "var(--red)";
      msg = "Critical Blockers";
    }

    gaugeCircle.style.background = `conic-gradient(${color} 0% ${score}%, #f1f5f9 ${score}% 100%)`;
    gaugeMsg.textContent = msg;
    gaugeMsg.style.color = color;

    // 2. Readiness Status Badges
    const badgeGen = document.getElementById("badgeGenerate");
    badgeGen.textContent = data.ready_to_generate ? "YES" : "NO";
    badgeGen.className = `badge-pill ${data.ready_to_generate ? 'success' : 'danger'}`;

    const badgePub = document.getElementById("badgePublish");
    badgePub.textContent = data.ready_to_publish ? "YES" : "NO";
    badgePub.className = `badge-pill ${data.ready_to_publish ? 'success' : 'danger'}`;

    // 3. Category health progression meters
    const catScoresWrap = document.getElementById("categoryScoresList");
    catScoresWrap.innerHTML = Object.entries(data.category_scores).map(([catName, catScore]) => {
      let progressColor = "var(--blue)";
      if (catScore === 100) progressColor = "var(--green)";
      else if (catScore < 50) progressColor = "var(--red)";
      
      return `
        <div class="category-score-row" style="margin-top: 10px">
          <div class="cat-row-header">
            <span>${catName}</span>
            <span style="color: ${progressColor}">${catScore}%</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-bar-fill" style="width: ${catScore}%; background: ${progressColor}"></div>
          </div>
        </div>
      `;
    }).join("");

    // 4. Quality metrics
    const q = data.quality_score;
    document.getElementById("valQuality").textContent = `${q.overall_quality}%`;
    document.getElementById("valTeacherBalance").textContent = `${q.teacher_balance}%`;
    document.getElementById("valResourceUtil").textContent = `${q.resource_utilization}%`;
    document.getElementById("valSubjectDist").textContent = `${q.subject_distribution}%`;

    // 5. Gather and count validation issues
    renderDiagnosticIssues();

  } catch (err) {
    gaugeVal.textContent = "Err";
    gaugeMsg.textContent = err.message;
    gaugeMsg.style.color = "var(--red)";
  }
}

function selectTab(tabName) {
  activeTab = tabName;
  document.querySelectorAll(".diag-tab-btn").forEach(btn => btn.classList.remove("active"));
  
  if (tabName === "All") document.getElementById("tabAll").classList.add("active");
  else if (tabName === "Errors") document.getElementById("tabErrors").classList.add("active");
  else if (tabName === "Warnings") document.getElementById("tabWarnings").classList.add("active");
  else if (tabName === "Suggestions") document.getElementById("tabSuggestions").classList.add("active");
  else if (tabName === "Info") document.getElementById("tabInfo").classList.add("active");

  renderDiagnosticIssues();
}

function renderDiagnosticIssues() {
  if (!validationReport) return;

  const diagList = document.getElementById("diagnosticList");

  // Collect all items from categories
  let allErrors = [];
  let allWarnings = [];
  let allSuggestions = [];
  let allInfo = [];

  Object.entries(validationReport.categories).forEach(([catName, catData]) => {
    catData.items.forEach(item => {
      const itemWithCat = { ...item, category: catName };
      if (item.severity === "Critical Error") allErrors.push(itemWithCat);
      else if (item.severity === "Warning") allWarnings.push(itemWithCat);
      else if (item.severity === "Suggestion") allSuggestions.push(itemWithCat);
      else allInfo.push(itemWithCat);
    });
  });

  // Update tabs counters
  document.getElementById("countAll").textContent = allErrors.length + allWarnings.length + allSuggestions.length + allInfo.length;
  document.getElementById("countErrors").textContent = allErrors.length;
  document.getElementById("countWarnings").textContent = allWarnings.length;
  document.getElementById("countSuggestions").textContent = allSuggestions.length;
  document.getElementById("countInfo").textContent = allInfo.length;

  // Determine filtered list
  let filtered = [];
  if (activeTab === "All") {
    filtered = [...allErrors, ...allWarnings, ...allSuggestions, ...allInfo];
  } else if (activeTab === "Errors") {
    filtered = allErrors;
  } else if (activeTab === "Warnings") {
    filtered = allWarnings;
  } else if (activeTab === "Suggestions") {
    filtered = allSuggestions;
  } else if (activeTab === "Info") {
    filtered = allInfo;
  }

  if (!filtered.length) {
    diagList.innerHTML = `<div style="text-align:center; padding:24px 0; color:var(--muted); font-size:13px;">No check issues found in this tab.</div>`;
    return;
  }

  diagList.innerHTML = filtered.map(item => {
    let severityClass = "information";
    let icon = "ℹ️";
    if (item.severity === "Critical Error") {
      severityClass = "critical-error";
      icon = "🛑";
    } else if (item.severity === "Warning") {
      severityClass = "warning";
      icon = "⚠️";
    } else if (item.severity === "Suggestion") {
      severityClass = "suggestion";
      icon = "💡";
    }

    return `
      <div class="diag-item ${severityClass}">
        <span class="diag-icon">${icon}</span>
        <div class="diag-body">
          <div class="diag-title">
            <span>${item.message}</span>
            <span class="diag-category-tag">${item.category}</span>
          </div>
          ${item.details ? `<div class="diag-desc">${item.details}</div>` : ""}
        </div>
      </div>
    `;
  }).join("");
}
