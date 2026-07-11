// On Duty — request, approve/reject (principal / vice-principal), cancel.
// GET/POST /on-duty, /on-duty/{id}/approve|reject|cancel, GET /on-duty/duty-types
// Approving auto-allocates substitutes for exactly the affected periods.

function initOnDutyPage() {
  const state = {
    me: null,
    canApprove: false,
    isAdmin: false,
    teachers: [],
    periods: 8,
    filter: "",
  };

  boot();

  async function boot() {
    try {
      state.me = await apiRequest("/auth/me");
      state.canApprove = ["super_admin", "school_admin", "principal", "vice_principal"].includes(state.me.role);
      state.isAdmin = state.canApprove;

      // duty types come from the API — no hardcoded list in the UI
      const { duty_types } = await apiRequest("/on-duty/duty-types");
      document.getElementById("odType").innerHTML =
        duty_types.map((t) => `<option value="${t}">${t}</option>`).join("");

      // periods per day from the school
      try {
        const schools = (await apiRequest("/schools?limit=100")).items;
        const school = schools.find((s) => s.id === state.me.school_id) || schools[0];
        if (school) state.periods = school.periods_per_day || 8;
      } catch (e) {}

      const opts = ['<option value="">— whole day —</option>'];
      for (let p = 1; p <= state.periods; p++) opts.push(`<option value="${p}">Period ${p}</option>`);
      document.getElementById("odStartP").innerHTML = opts.join("");
      document.getElementById("odEndP").innerHTML = opts.join("");

      if (state.isAdmin) {
        state.teachers = (await apiRequest("/teachers?limit=500")).items;
        document.getElementById("odTeacherWrap").style.display = "";
        document.getElementById("odTeacher").innerHTML =
          state.teachers.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
      }

      document.getElementById("odForm").addEventListener("submit", onSubmit);
      document.querySelectorAll("#odTabs button").forEach((b) =>
        b.addEventListener("click", () => {
          document.querySelectorAll("#odTabs button").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          state.filter = b.dataset.status;
          load();
        }));

      load();
    } catch (err) {
      showMsg("error", err.message);
    }
  }

  function showMsg(kind, text) {
    const el = document.getElementById("odMsg");
    if (!text) { el.style.display = "none"; return; }
    el.className = `msg ${kind}`;
    el.textContent = text;
    el.style.display = "block";
  }

  async function onSubmit(e) {
    e.preventDefault();
    showMsg(null);
    const sp = document.getElementById("odStartP").value;
    const ep = document.getElementById("odEndP").value;
    if ((sp && !ep) || (!sp && ep)) {
      showMsg("error", "Choose both a start and end period, or leave both blank for a whole day.");
      return;
    }
    const body = {
      date: document.getElementById("odDate").value,
      end_date: document.getElementById("odEndDate").value || null,
      start_period: sp ? Number(sp) : null,
      end_period: ep ? Number(ep) : null,
      duty_type: document.getElementById("odType").value,
      description: document.getElementById("odDesc").value.trim() || null,
      location: document.getElementById("odLocation").value.trim() || null,
    };
    if (state.isAdmin) body.teacher_id = Number(document.getElementById("odTeacher").value);

    try {
      await apiRequest("/on-duty", { method: "POST", body });
      showMsg("success", "On-duty request submitted. It now needs principal approval.");
      document.getElementById("odForm").reset();
      load();
    } catch (err) {
      showMsg("error", err.message);
    }
  }

  async function load() {
    const root = document.getElementById("odRoot");
    root.innerHTML = `<div class="loading-state">Loading…</div>`;
    try {
      const q = state.filter ? `?status=${state.filter}&limit=200` : "?limit=200";
      const data = await apiRequest(`/on-duty${q}`);
      render(data.items || []);
    } catch (err) {
      root.innerHTML = `<div class="empty-state">${err.message}</div>`;
    }
  }

  function periodLabel(r) {
    if (r.start_period == null && r.end_period == null) return "Whole day";
    if (r.start_period === r.end_period) return `P${r.start_period}`;
    return `P${r.start_period}–P${r.end_period}`;
  }

  function render(items) {
    const root = document.getElementById("odRoot");
    if (!items.length) {
      root.innerHTML = `<div class="empty-state">No on-duty records${state.filter ? " with this status" : ""}.</div>`;
      return;
    }
    root.innerHTML = `
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Teacher</th><th>Dates</th><th>Periods</th><th>Duty Type</th>
          <th>Location</th><th>Status</th><th>Actions</th>
        </tr></thead>
        <tbody>
          ${items.map((r) => `
            <tr>
              <td>${r.teacher_name}</td>
              <td>${r.date}${r.end_date ? ` → ${r.end_date}` : ""}</td>
              <td>${periodLabel(r)}</td>
              <td>${r.duty_type}</td>
              <td>${r.location || "—"}</td>
              <td><span class="status-badge ${r.status}">${r.status}</span></td>
              <td class="actions">
                ${r.status === "pending" && state.canApprove
                  ? `<button class="btn btn-primary cx-sm" data-approve="${r.id}">Approve</button>
                     <button class="btn btn-danger cx-sm" data-reject="${r.id}">Reject</button>`
                  : ""}
                ${r.status === "approved" && state.canApprove
                  ? `<button class="btn btn-ghost cx-sm" data-cancel="${r.id}">Cancel</button>` : ""}
              </td>
            </tr>`).join("")}
        </tbody>
      </table></div>`;

    root.querySelectorAll("[data-approve]").forEach((b) =>
      b.addEventListener("click", () => decide(b.dataset.approve, "approve")));
    root.querySelectorAll("[data-reject]").forEach((b) =>
      b.addEventListener("click", () => decide(b.dataset.reject, "reject")));
    root.querySelectorAll("[data-cancel]").forEach((b) =>
      b.addEventListener("click", () => cancel(b.dataset.cancel)));
  }

  async function decide(id, action) {
    const note = prompt(action === "approve" ? "Approval note (optional):" : "Reason for rejection:");
    if (action === "reject" && note === null) return;
    showMsg("info", action === "approve" ? "Approving and allocating substitutes…" : "Rejecting…");
    try {
      const res = await apiRequest(`/on-duty/${id}/${action}`, { method: "POST", body: { note: note || null } });
      if (action === "approve") {
        showMsg("success", res.message || "Approved.");
        if (res.uncovered_slots && res.uncovered_slots.length) {
          showMsg("error", `${res.message} Uncovered: ` +
            res.uncovered_slots.map((u) => `${u.date} P${u.period} (${u.section_name})`).join("; "));
        }
      } else {
        showMsg("success", "On-duty request rejected.");
      }
      load();
    } catch (err) {
      showMsg("error", err.message);
    }
  }

  async function cancel(id) {
    if (!confirm("Cancel this on-duty? Any substitutes it created will be released.")) return;
    try {
      await apiRequest(`/on-duty/${id}/cancel`, { method: "POST" });
      showMsg("success", "On-duty cancelled; substitutes released.");
      load();
    } catch (err) {
      showMsg("error", err.message);
    }
  }
}
