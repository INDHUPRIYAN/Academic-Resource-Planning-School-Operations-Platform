// Setup Wizard JS Logic
requireAuth();
renderTopbar("setup_wizard.html");

let currentStep = 1;
const totalSteps = 5;

// Selected options state
const state = {
  mediumsEnabled: false,
  assignmentMethod: "automatic", // automatic, manual, hybrid
  resourcesEnabled: true,
  activitiesEnabled: false,
  petLastPeriods: false,
};

// Preset settings definition for dynamic template loading
const presets = {
  Government: {
    type: "Government School",
    periods: 8,
    days: 5,
    grades: "Grade 6, Grade 7, Grade 8, Grade 9, Grade 10",
    sections: "A, B",
    mediums: true,
    assignment: "manual",
    resources: false,
    activities: false,
    maxConsecutive: 4,
    petLast: true,
    modules: ["timetables", "leaves", "swaps", "reports"],
    timings: [
      { period: 1, start: "09:30", end: "10:15" },
      { period: 2, start: "10:15", end: "11:00" },
      { period: 3, start: "11:15", end: "12:00" },
      { period: 4, start: "12:00", end: "12:45" },
      { period: 5, start: "13:30", end: "14:15" },
      { period: 6, start: "14:15", end: "15:00" },
      { period: 7, start: "15:15", end: "16:00" },
      { period: 8, start: "16:00", end: "16:45" }
    ]
  },
  Private: {
    type: "Private School",
    periods: 8,
    days: 5,
    grades: "Grade 1, Grade 2, Grade 3, Grade 4, Grade 5, Grade 6, Grade 7, Grade 8",
    sections: "A, B",
    mediums: false,
    assignment: "automatic",
    resources: true,
    activities: true,
    maxConsecutive: 3,
    petLast: false,
    modules: ["timetables", "leaves", "swaps", "exams", "reports"],
    timings: [
      { period: 1, start: "08:30", end: "09:15" },
      { period: 2, start: "09:15", end: "10:00" },
      { period: 3, start: "10:00", end: "10:45" },
      { period: 4, start: "11:00", end: "11:45" },
      { period: 5, start: "11:45", end: "12:30" },
      { period: 6, start: "13:30", end: "14:15" },
      { period: 7, start: "14:15", end: "15:00" },
      { period: 8, start: "15:00", end: "15:45" }
    ]
  },
  CBSE: {
    type: "CBSE School",
    periods: 8,
    days: 5,
    grades: "Grade 6, Grade 7, Grade 8, Grade 9, Grade 10",
    sections: "A, B",
    mediums: false,
    assignment: "hybrid",
    resources: true,
    activities: true,
    maxConsecutive: 3,
    petLast: false,
    modules: ["timetables", "leaves", "swaps", "exams", "reports"],
    timings: [
      { period: 1, start: "08:30", end: "09:15" },
      { period: 2, start: "09:15", end: "10:00" },
      { period: 3, start: "10:00", end: "10:45" },
      { period: 4, start: "11:00", end: "11:45" },
      { period: 5, start: "11:45", end: "12:30" },
      { period: 6, start: "13:30", end: "14:15" },
      { period: 7, start: "14:15", end: "15:00" },
      { period: 8, start: "15:00", end: "15:45" }
    ]
  },
  ICSE: {
    type: "ICSE School",
    periods: 8,
    days: 5,
    grades: "Grade 6, Grade 7, Grade 8, Grade 9, Grade 10",
    sections: "A, B",
    mediums: false,
    assignment: "automatic",
    resources: true,
    activities: true,
    maxConsecutive: 3,
    petLast: false,
    modules: ["timetables", "leaves", "swaps", "exams", "reports"],
    timings: [
      { period: 1, start: "08:30", end: "09:15" },
      { period: 2, start: "09:15", end: "10:00" },
      { period: 3, start: "10:00", end: "10:45" },
      { period: 4, start: "11:00", end: "11:45" },
      { period: 5, start: "11:45", end: "12:30" },
      { period: 6, start: "13:30", end: "14:15" },
      { period: 7, start: "14:15", end: "15:00" },
      { period: 8, start: "15:00", end: "15:45" }
    ]
  },
  Matriculation: {
    type: "Matriculation School",
    periods: 8,
    days: 5,
    grades: "Grade 6, Grade 7, Grade 8, Grade 9, Grade 10",
    sections: "A, B",
    mediums: true,
    assignment: "hybrid",
    resources: true,
    activities: true,
    maxConsecutive: 3,
    petLast: true,
    modules: ["timetables", "leaves", "swaps", "exams", "reports"],
    timings: [
      { period: 1, start: "08:30", end: "09:15" },
      { period: 2, start: "09:15", end: "10:00" },
      { period: 3, start: "10:00", end: "10:45" },
      { period: 4, start: "11:00", end: "11:45" },
      { period: 5, start: "11:45", end: "12:30" },
      { period: 6, start: "13:30", end: "14:15" },
      { period: 7, start: "14:15", end: "15:00" },
      { period: 8, start: "15:00", end: "15:45" }
    ]
  },
  "Higher Secondary": {
    type: "Higher Secondary School",
    periods: 8,
    days: 5,
    grades: "Grade 11, Grade 12",
    sections: "A, B",
    mediums: true,
    assignment: "manual",
    resources: true,
    activities: false,
    maxConsecutive: 4,
    petLast: true,
    modules: ["timetables", "leaves", "swaps", "exams", "reports"],
    timings: [
      { period: 1, start: "08:30", end: "09:15" },
      { period: 2, start: "09:15", end: "10:00" },
      { period: 3, start: "10:00", end: "10:45" },
      { period: 4, start: "11:00", end: "11:45" },
      { period: 5, start: "11:45", end: "12:30" },
      { period: 6, start: "13:30", end: "14:15" },
      { period: 7, start: "14:15", end: "15:00" },
      { period: 8, start: "15:00", end: "15:45" }
    ]
  }
};

function initWizard() {
  const progressBar = document.getElementById("progressBar");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const msg = document.getElementById("wizardMsg");
  const templateSelect = document.getElementById("wTemplate");

  // Step 2 option cards
  bindOptionCard("optMedNo", "optMedYes", (val) => { state.mediumsEnabled = val; });
  // Step 3 option cards
  bindGroupOptionCards([
    { id: "optAssignAuto", val: "automatic" },
    { id: "optAssignManual", val: "manual" },
    { id: "optAssignHybrid", val: "hybrid" }
  ], (val) => { state.assignmentMethod = val; });
  // Step 4 option cards
  bindOptionCard("optResNo", "optResYes", (val) => { state.resourcesEnabled = val; });
  bindOptionCard("optActNo", "optActYes", (val) => { state.activitiesEnabled = val; });
  // Step 5 option cards
  bindOptionCard("optPetAny", "optPetLast", (val) => { state.petLastPeriods = val; });

  // Initial highlight for Step 3
  document.getElementById("optAssignAuto").classList.add("selected");

  // Template select change listener
  templateSelect.addEventListener("change", () => {
    const tName = templateSelect.value;
    if (!tName) return;

    const p = presets[tName];
    if (p) {
      document.getElementById("wType").value = p.type;
      document.getElementById("wPeriods").value = p.periods;
      document.getElementById("wDays").value = p.days;
      document.getElementById("wGrades").value = p.grades;
      document.getElementById("wSections").value = p.sections;
      document.getElementById("wMaxConsecutive").value = p.maxConsecutive;

      setOptionCard("optMedNo", "optMedYes", p.mediums, (val) => { state.mediumsEnabled = val; });
      setGroupOptionCard([
        { id: "optAssignAuto", val: "automatic" },
        { id: "optAssignManual", val: "manual" },
        { id: "optAssignHybrid", val: "hybrid" }
      ], p.assignment, (val) => { state.assignmentMethod = val; });
      setOptionCard("optResNo", "optResYes", p.resources, (val) => { state.resourcesEnabled = val; });
      setOptionCard("optActNo", "optActYes", p.activities, (val) => { state.activitiesEnabled = val; });
      setOptionCard("optPetAny", "optPetLast", p.petLast, (val) => { state.petLastPeriods = val; });
    }
  });

  prevBtn.addEventListener("click", () => navigate(-1));
  nextBtn.addEventListener("click", () => {
    if (validateStep(currentStep)) {
      if (currentStep < totalSteps) {
        navigate(1);
      } else {
        submitWizard();
      }
    }
  });

  function navigate(direction) {
    msg.style.display = "none";
    
    // Hide current step
    document.getElementById(`step${currentStep}`).classList.remove("active");
    document.getElementById(`pstep${currentStep}`).classList.remove("active");
    
    currentStep += direction;
    
    // Show new step
    document.getElementById(`step${currentStep}`).classList.add("active");
    document.getElementById(`pstep${currentStep}`).classList.add("active");
    
    // Update progress bar width
    progressBar.style.width = `${(currentStep / totalSteps) * 100}%`;
    
    // Button states
    prevBtn.disabled = currentStep === 1;
    nextBtn.textContent = currentStep === totalSteps ? "Finish Setup" : "Next";
  }

  function validateStep(step) {
    if (step === 1) {
      const name = document.getElementById("wName").value.trim();
      if (!name) {
        showError("School Name is required.");
        return false;
      }
    }
    if (step === 2) {
      const grades = document.getElementById("wGrades").value.trim();
      const sections = document.getElementById("wSections").value.trim();
      if (!grades || !sections) {
        showError("Grades and Sections lists are required.");
        return false;
      }
    }
    return true;
  }

  async function submitWizard() {
    nextBtn.disabled = true;
    nextBtn.textContent = "Seeding School Structure...";
    msg.style.display = "none";
    
    try {
      const schoolName = document.getElementById("wName").value.trim();
      const schoolType = document.getElementById("wType").value;
      const periods = parseInt(document.getElementById("wPeriods").value);
      const days = parseInt(document.getElementById("wDays").value);
      
      const gradesRaw = document.getElementById("wGrades").value.split(",").map(g => g.trim()).filter(Boolean);
      const sectionsRaw = document.getElementById("wSections").value.split(",").map(s => s.trim()).filter(Boolean);
      
      // 1. Create School
      const school = await apiRequest("/schools", {
        method: "POST",
        body: {
          name: schoolName,
          periods_per_day: periods,
          working_days: days
        }
      });
      
      // 2. Create Classes and Sections
      for (const gradeName of gradesRaw) {
        const cls = await apiRequest("/classes", {
          method: "POST",
          body: {
            name: gradeName,
            school_id: school.id
          }
        });
        
        for (const secName of sectionsRaw) {
          await apiRequest("/sections", {
            method: "POST",
            body: {
              name: secName,
              class_id: cls.id
            }
          });
        }
      }

      // 3. Generate Timings array
      let timings = [];
      const tName = templateSelect.value;
      if (tName && presets[tName]) {
        timings = presets[tName].timings;
      } else {
        for (let i = 1; i <= periods; i++) {
          const startHour = 8 + i - 1;
          const start = `${String(startHour).padStart(2, '0')}:30`;
          const end = `${String(startHour + 1).padStart(2, '0')}:15`;
          timings.push({ period: i, start, end });
        }
      }

      // 4. Assemble modules list
      let enabledModules = ["timetables", "leaves", "swaps", "exams", "reports"];
      if (tName && presets[tName] && presets[tName].modules) {
        enabledModules = presets[tName].modules;
      }

      // 5. Assemble and Update Config JSON
      const maxConsecutive = parseInt(document.getElementById("wMaxConsecutive").value) || 3;
      
      const configObj = {
        school_type: schoolType,
        academic_year: "2026-2027",
        period_timings: timings,
        enabled_modules: enabledModules,
        academic_structure: {
          grades: gradesRaw
        },
        sections_per_grade: {}, 
        mediums: {
          enabled: state.mediumsEnabled,
          list: state.mediumsEnabled ? ["English", "Tamil"] : []
        },
        teacher_assignment_method: state.assignmentMethod,
        teacher_eligibility: {
          enabled: false,
          groups: []
        },
        subject_configuration: {
          hours_defined_at: "per_class"
        },
        activities: {
          enabled: state.activitiesEnabled,
          list: state.activitiesEnabled ? ["PET", "Library", "Computer Lab"] : []
        },
        resources: {
          enabled: state.resourcesEnabled
        },
        substitution_policy: "automatic",
        scheduling_policies: {
          max_consecutive_periods: maxConsecutive,
          max_daily_periods: periods,
          double_periods_allowed: false,
          science_practical_consecutive: false,
          pet_last_periods: state.petLastPeriods
        }
      };

      // Save Config
      await apiRequest(`/schools/${school.id}/config`, {
        method: "PUT",
        body: {
          config: JSON.stringify(configObj)
        }
      });

      // Update current user info context in localStorage/session if they set up a new school
      const me = await apiRequest("/auth/me");
      if (me.role !== "super_admin") {
        // Log out or force refresh token so user has school_id bound in backend session
        // Actually, just let dashboard reload.
      }

      msg.className = "msg success";
      msg.textContent = "School onboarding setup completed successfully! Redirecting...";
      msg.style.display = "block";
      
      setTimeout(() => {
        window.location.href = "dashboard.html";
      }, 2000);
      
    } catch (err) {
      nextBtn.disabled = false;
      nextBtn.textContent = "Finish Setup";
      showError(err.message);
    }
  }

  function showError(text) {
    msg.className = "msg error";
    msg.textContent = text;
    msg.style.display = "block";
  }
}

// Option selection card helpers
function bindOptionCard(noId, yesId, callback) {
  const cardNo = document.getElementById(noId);
  const cardYes = document.getElementById(yesId);

  cardNo.addEventListener("click", () => {
    cardNo.classList.add("selected");
    cardYes.classList.remove("selected");
    callback(false);
  });
  cardYes.addEventListener("click", () => {
    cardYes.classList.add("selected");
    cardNo.classList.remove("selected");
    callback(true);
  });
}

function setOptionCard(noId, yesId, val, callback) {
  const cardNo = document.getElementById(noId);
  const cardYes = document.getElementById(yesId);
  if (val) {
    cardYes.classList.add("selected");
    cardNo.classList.remove("selected");
  } else {
    cardNo.classList.add("selected");
    cardYes.classList.remove("selected");
  }
  callback(val);
}

function bindGroupOptionCards(optionsList, callback) {
  optionsList.forEach(opt => {
    const el = document.getElementById(opt.id);
    el.addEventListener("click", () => {
      optionsList.forEach(o => document.getElementById(o.id).classList.remove("selected"));
      el.classList.add("selected");
      callback(opt.val);
    });
  });
}

function setGroupOptionCard(optionsList, selectedVal, callback) {
  optionsList.forEach(opt => {
    const el = document.getElementById(opt.id);
    if (opt.val === selectedVal) {
      el.classList.add("selected");
    } else {
      el.classList.remove("selected");
    }
  });
  callback(selectedVal);
}

initWizard();
