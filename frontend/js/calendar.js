// Calendar Management JS Logic
let currentSchoolId = null;
let calendarEvents = [];

async function initCalendarPage() {
  renderTopbar("calendar.html");

  const addEventForm = document.getElementById("addEventForm");
  const filterType = document.getElementById("filterType");
  const eventTypeSelect = document.getElementById("eventType");
  const eventIsHoliday = document.getElementById("eventIsHoliday");

  // Adjust checkbox default based on event type selection
  eventTypeSelect.addEventListener("change", () => {
    const val = eventTypeSelect.value;
    if (val === "holiday" || val === "exam_week") {
      eventIsHoliday.checked = true;
    } else if (val === "working_day") {
      eventIsHoliday.checked = false;
    }
  });

  try {
    const me = await apiRequest("/auth/me");
    const schools = (await apiRequest("/schools?limit=100")).items;

    if (me.role === "super_admin") {
      if (!schools.length) {
        document.querySelector("main").innerHTML = `<div class="empty-state">No schools exist yet. Create one in the Schools tab.</div>`;
        return;
      }

      // Inject School Selector
      const selectorWrap = document.createElement("div");
      selectorWrap.style.cssText = "margin-bottom: 24px; max-width: 320px;";
      selectorWrap.innerHTML = `
        <label style="margin: 0 0 6px">Select Active School Context</label>
        <select id="calendarSchoolSelect" style="width:100%; padding:8px 10px; border:1px solid var(--border); border-radius:8px; font-size:13px; background:#fff;">
          ${schools.map(s => `<option value="${s.id}">${s.name}</option>`).join("")}
        </select>
      `;
      const main = document.querySelector("main");
      main.insertBefore(selectorWrap, main.querySelector(".calendar-grid-layout"));

      const schoolSelect = document.getElementById("calendarSchoolSelect");
      schoolSelect.addEventListener("change", () => {
        currentSchoolId = parseInt(schoolSelect.value);
        loadCalendarEvents(currentSchoolId);
      });

      currentSchoolId = schools[0].id;
    } else {
      currentSchoolId = me.school_id;
    }

    if (!currentSchoolId) {
      showError("No school context found.");
      return;
    }

    // Load initial events
    await loadCalendarEvents(currentSchoolId);

    // Bind form submission
    addEventForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      await createCalendarEvent();
    });

    // Bind filter change
    filterType.addEventListener("change", () => {
      renderEventsList();
    });

  } catch (err) {
    showError(err.message);
  }
}

async function loadCalendarEvents(schoolId) {
  clearMessage();
  const root = document.getElementById("calendarListRoot");
  root.innerHTML = `<div class="loading-state">Loading calendar events...</div>`;

  try {
    const data = await apiRequest(`/calendar?limit=200`);
    // Note: make_crud_router returns list wrapped as {items, total, page, limit}
    // Filter locally to the current school, as super_admin lists everything by default
    calendarEvents = data.items.filter(item => item.school_id === schoolId);
    renderEventsList();
  } catch (err) {
    showError("Failed to load calendar events: " + err.message);
  }
}

function renderEventsList() {
  const root = document.getElementById("calendarListRoot");
  const filterVal = document.getElementById("filterType").value;

  let filtered = calendarEvents;
  if (filterVal !== "all") {
    filtered = calendarEvents.filter(e => e.type === filterVal);
  }

  // Sort events chronologically
  filtered.sort((a, b) => new Date(a.date) - new Date(b.date));

  if (!filtered.length) {
    root.innerHTML = `<div class="empty-state">No scheduled events found${filterVal !== "all" ? " for this type" : ""}.</div>`;
    return;
  }

  root.innerHTML = `
    <div class="event-list">
      ${filtered.map(e => {
        const dateStr = formatDateDisplay(e.date, e.end_date);
        const typeLabel = e.type.replace("_", " ");
        const holLabel = e.is_holiday ? " (Holiday)" : "";
        return `
          <div class="event-item">
            <div class="event-info">
              <div class="event-title">${e.title}</div>
              <div class="event-meta">
                <span class="event-type-badge ${e.type}">${typeLabel}${holLabel}</span>
                <span>📅 ${dateStr}</span>
              </div>
            </div>
            <button class="btn btn-danger delete-event-btn" data-id="${e.id}">Delete</button>
          </div>
        `;
      }).join("")}
    </div>
  `;

  // Bind delete buttons
  root.querySelectorAll(".delete-event-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const eventId = parseInt(btn.dataset.id);
      if (confirm("Are you sure you want to delete this calendar event?")) {
        try {
          clearMessage();
          await apiRequest(`/calendar/${eventId}`, { method: "DELETE" });
          showSuccess("Calendar event deleted successfully.");
          await loadCalendarEvents(currentSchoolId);
        } catch (err) {
          showError("Failed to delete event: " + err.message);
        }
      }
    });
  });
}

async function createCalendarEvent() {
  clearMessage();
  const form = document.getElementById("addEventForm");
  const title = document.getElementById("eventTitle").value.trim();
  const type = document.getElementById("eventType").value;
  const dateVal = document.getElementById("eventDate").value;
  const endDateVal = document.getElementById("eventEndDate").value || null;
  const isHoliday = document.getElementById("eventIsHoliday").checked;

  if (endDateVal && new Date(endDateVal) < new Date(dateVal)) {
    showError("End Date cannot be earlier than Start Date.");
    return;
  }

  try {
    const payload = {
      title,
      type,
      date: dateVal,
      end_date: endDateVal,
      is_holiday: isHoliday,
      school_id: currentSchoolId
    };

    await apiRequest("/calendar", {
      method: "POST",
      body: payload
    });

    showSuccess("Calendar event scheduled successfully!");
    form.reset();
    
    // Reset checkbox state
    document.getElementById("eventIsHoliday").checked = true;

    await loadCalendarEvents(currentSchoolId);

  } catch (err) {
    showError("Failed to schedule event: " + err.message);
  }
}

function formatDateDisplay(startDate, endDate) {
  const options = { year: "numeric", month: "short", day: "numeric" };
  const s = new Date(startDate).toLocaleDateString("en-US", options);
  if (!endDate || startDate === endDate) {
    return s;
  }
  const e = new Date(endDate).toLocaleDateString("en-US", options);
  return `${s} – ${e}`;
}

function clearMessage() {
  const root = document.getElementById("calendarMsg");
  root.style.display = "none";
  root.className = "msg";
  root.textContent = "";
}

function showError(text) {
  const root = document.getElementById("calendarMsg");
  root.className = "msg error";
  root.textContent = text;
  root.style.display = "block";
}

function showSuccess(text) {
  const root = document.getElementById("calendarMsg");
  root.className = "msg success";
  root.textContent = text;
  root.style.display = "block";
}
