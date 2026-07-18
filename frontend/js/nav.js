function renderTopbar(active) {
  // 1. Initial render shell — a fixed left sidebar. Element IDs are unchanged so
  // every page's existing script keeps working.
  document.getElementById("topbar").innerHTML = `
    <button class="sidebar-toggle" id="sidebarToggle" aria-label="Toggle navigation">☰</button>
    <div class="sidebar-scrim" id="sidebarScrim"></div>
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-brand">
        <div class="brand-badge"></div>
        <h1>EduFlow AI</h1>
      </div>
      <nav class="nav-links" id="navLinksRoot"></nav>
      <div class="sidebar-footer">
        <div class="sidebar-user">
          <div class="notif-wrap">
            <button class="notif-bell" id="notifBell" title="Notifications">🔔<span class="notif-dot" id="notifDot" style="display:none"></span></button>
            <div class="notif-panel" id="notifPanel" style="display:none">
              <div class="notif-panel-head">
                <strong>Notifications</strong>
                <button class="btn btn-ghost" id="notifMarkAll" style="padding:3px 8px; font-size:11px">Mark all read</button>
              </div>
              <div id="notifList" class="notif-list"><div class="loading-state" style="padding:16px">Loading...</div></div>
            </div>
          </div>
          <span id="userName"></span>
          <span class="role-badge" id="roleBadge"></span>
        </div>
        <button class="logout-btn" onclick="logout()">Logout</button>
      </div>
    </aside>`;

  document.body.classList.add("has-sidebar");
  initSidebarToggle();

  // 2. Fetch auth + dynamic config modules
  apiRequest("/auth/me")
    .then(async (u) => {
      document.getElementById("userName").textContent = u.name;
      document.getElementById("roleBadge").textContent = u.role.replace("_", " ");

      let schoolId = u.school_id;
      if (u.role === "super_admin") {
        const stored = localStorage.getItem("active_school_id");
        if (stored) {
          schoolId = parseInt(stored);
        } else {
          try {
            const schools = (await apiRequest("/schools?limit=1")).items;
            if (schools.length) schoolId = schools[0].id;
          } catch (e) {}
        }
      }

      let enabledModules = ["timetables", "leaves", "swaps", "exams", "reports"];
      let rawConfig = null;
      if (schoolId) {
        try {
          const cfgWrapper = await apiRequest(`/schools/${schoolId}/config`);
          rawConfig = JSON.parse(cfgWrapper.config);
          if (rawConfig && Array.isArray(rawConfig.enabled_modules)) {
            enabledModules = rawConfig.enabled_modules;
          }
        } catch (e) {
          console.error("Failed to load school config for navbar:", e);
        }
      }

      // Role groups. A principal / vice-principal runs daily operations (approvals,
      // attendance, substitutes, swaps, reports) but not destructive setup.
      const SETUP = ["super_admin", "school_admin"];
      const OPS = ["super_admin", "school_admin", "principal", "vice_principal"];
      const ALL = ["super_admin", "school_admin", "principal", "vice_principal", "teacher"];

      const allLinks = [
        { href: "dashboard.html", label: "Dashboard", roles: ALL },
        { href: "schools.html", label: "Schools", roles: ["super_admin"] },
        { href: "classes.html", label: "Classes", roles: SETUP },
        { href: "subjects.html", label: "Subjects", roles: SETUP },
        { href: "teachers.html", label: "Teachers", roles: SETUP },
        { href: "teacher_availability.html", label: "Availability", roles: SETUP, module: "timetables" },
        { href: "timetable.html", label: "Timetable", roles: ALL, module: "timetables" },
        { href: "attendance.html", label: "Attendance", roles: ALL },
        { href: "leaves.html", label: "Leaves", roles: ALL, module: "leaves" },
        { href: "on_duty.html", label: "On Duty", roles: ALL },
        { href: "substitutes.html", label: "Substitutes", roles: OPS, module: "leaves" },
        { href: "swaps.html", label: "Swaps", roles: ALL, module: "swaps" },
        { href: "exams.html", label: "Exams", roles: ALL, module: "exams" },
        { href: "reports.html", label: "Reports", roles: OPS, module: "reports" },
        { href: "health.html", label: "Health", roles: OPS },
        { href: "config_editor.html", label: "Config Editor", roles: SETUP },
        { href: "calendar.html", label: "Calendar", roles: OPS, module: "leaves" },
        { href: "bulk.html", label: "Bulk Upload", roles: SETUP },
        { href: "assignments.html", label: "Assignments", roles: SETUP, module: "timetables" },
        { href: "setup_wizard.html", label: "Setup Wizard", roles: ["super_admin"] },
      ];

      const visible = allLinks.filter(lnk => {
        if (!lnk.roles.includes(u.role)) return false;
        if (lnk.module) {
          if (lnk.module === "resources") {
            const res = rawConfig?.resources;
            const resEnabled = res && typeof res === "object" ? res.enabled !== false : res !== false;
            if (!resEnabled) return false;
          } else if (lnk.module === "activities") {
            const act = rawConfig?.activities;
            const actEnabled = act && typeof act === "object" ? act.enabled !== false : act !== false;
            if (!actEnabled) return false;
          } else if (lnk.module === "mediums") {
            const med = rawConfig?.mediums;
            const medEnabled = med && typeof med === "object" ? med.enabled === true : false;
            if (!medEnabled) return false;
          } else if (!enabledModules.includes(lnk.module)) {
            return false;
          }
        }
        return true;
      });

      document.getElementById("navLinksRoot").innerHTML = visible
        .map(lnk => `<a href="${lnk.href}" class="nav-link${active === lnk.href ? " active" : ""}">${lnk.label}</a>`)
        .join("");
    })
    .catch((err) => {
      // Only a real authentication failure should sign the user out. A transient
      // network error or a 5xx used to call logout() here, which silently kicked
      // people back to the login screen mid-task and lost their work.
      if (err && (err.status === 401 || err.status === 403)) {
        logout();
        return;
      }
      console.error("Sidebar could not load (staying signed in):", err);
      const root = document.getElementById("navLinksRoot");
      if (root && !root.innerHTML.trim()) {
        root.innerHTML = `<a href="dashboard.html" class="nav-link">Dashboard</a>`;
      }
    });

  initNotifications();
}

function initSidebarToggle() {
  const sidebar = document.getElementById("sidebar");
  const toggle = document.getElementById("sidebarToggle");
  const scrim = document.getElementById("sidebarScrim");
  if (!sidebar || !toggle || !scrim) return;

  const setOpen = (open) => {
    sidebar.classList.toggle("open", open);
    scrim.classList.toggle("show", open);
  };

  toggle.addEventListener("click", () => setOpen(!sidebar.classList.contains("open")));
  scrim.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setOpen(false);
  });
  // Follow a link on mobile -> close the drawer behind it.
  sidebar.addEventListener("click", (e) => {
    if (e.target.closest(".nav-link")) setOpen(false);
  });
}

function initNotifications() {
  const bell = document.getElementById("notifBell");
  const panel = document.getElementById("notifPanel");
  const dot = document.getElementById("notifDot");
  const list = document.getElementById("notifList");

  async function refresh() {
    try {
      const data = await apiRequest("/notifications?limit=15");
      dot.style.display = data.unread_count > 0 ? "block" : "none";
      if (!data.items.length) {
        list.innerHTML = `<div class="empty-state" style="padding:16px">No notifications yet.</div>`;
        return;
      }
      list.innerHTML = data.items
        .map(
          (n) => `<div class="notif-item${n.is_read ? "" : " unread"}" data-id="${n.id}">
            <div class="notif-msg">${n.message}</div>
            <div class="notif-time">${new Date(n.created_at).toLocaleString()}</div>
          </div>`
        )
        .join("");
      list.querySelectorAll("[data-id]").forEach((el) =>
        el.addEventListener("click", async () => {
          await apiRequest(`/notifications/${el.dataset.id}/read`, { method: "PATCH" });
          refresh();
        })
      );
    } catch (e) {
      list.innerHTML = `<div class="empty-state" style="padding:16px">${e.message}</div>`;
    }
  }

  bell.addEventListener("click", () => {
    const showing = panel.style.display !== "none";
    panel.style.display = showing ? "none" : "block";
    if (!showing) refresh();
  });
  document.getElementById("notifMarkAll").addEventListener("click", async (e) => {
    e.stopPropagation();
    await apiRequest("/notifications/read-all", { method: "PATCH" });
    refresh();
  });
  document.addEventListener("click", (e) => {
    if (!panel.contains(e.target) && e.target !== bell) panel.style.display = "none";
  });

  refresh();
  setInterval(refresh, 30000);
}
