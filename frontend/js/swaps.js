// Swap Management page (Phase 5).
// Talks to: GET /timetables?day_of_week=&limit=  (slot pickers, school-scoped)
//           POST /swaps   GET /swaps   POST /swaps/{id}/approve
//           POST /swaps/{id}/reject   DELETE /swaps/{id}

function pyWeekday(dateStr) {
  // JS Date.getDay(): Sunday=0..Saturday=6. Backend convention: Monday=0..Sunday=6.
  const d = new Date(dateStr + "T00:00:00");
  return (d.getDay() + 6) % 7;
}

const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function slotOptionLabel(s) {
  const what = s.subject_name || s.activity_name || "Free";
  return `${s.section_name} · P${s.period} · ${what}${s.teacher_name ? " (" + s.teacher_name + ")" : ""}`;
}

function initSwapsPage() {
  const root = document.getElementById("swapRoot");
  root.innerHTML = `<div class="loading-state">Loading...</div>`;

  apiRequest("/auth/me").then(async (me) => {
    const isAdmin = me.role === "super_admin" || me.role === "school_admin";
    let myTeacherId = null;
    if (me.role === "teacher") {
      try {
        const t = await apiRequest("/teachers?limit=200");
        const mine = t.items.find((x) => x.email === me.email);
        myTeacherId = mine ? mine.id : null;
      } catch (e) { /* ignore */ }
    }
    renderPage(me, isAdmin, myTeacherId);
  }).catch((e) => {
    root.innerHTML = `<div class="empty-state">${e.message}</div>`;
  });
}

function renderPage(me, isAdmin, myTeacherId) {
  const root = document.getElementById("swapRoot");
  const state = { date: new Date().toISOString().slice(0, 10), slots: [], status: "pending" };

  root.innerHTML = `
    <div class="leave-form-card">
      <h3>Request a Swap</h3>
      <div class="msg" id="swapMsg"></div>
      <div class="leave-form-row">
        <div class="tt-field"><label>Date</label><input type="date" id="swapDate" value="${state.date}" /></div>
        <span id="weekdayLabel" style="font-size:12px; color:var(--muted); align-self:center"></span>
      </div>
      <div class="swap-pair">
        <div class="swap-slot-card">
          <div class="swap-slot-title">${isAdmin ? "Slot A" : "Your class"}</div>
          <select id="slotASelect"><option value="">Pick a date first...</option></select>
        </div>
        <div class="swap-pair-arrow">⇄</div>
        <div class="swap-slot-card">
          <div class="swap-slot-title">${isAdmin ? "Slot B" : "Swap with"}</div>
          <select id="slotBSelect"><option value="">Pick a date first...</option></select>
        </div>
      </div>
      <label>Reason (optional)</label>
      <textarea id="swapReason" placeholder="e.g. Doctor's appointment that afternoon"></textarea>
      <div style="margin-top:10px"><button class="btn btn-primary" id="submitSwapBtn">Request Swap</button></div>
    </div>

    <div class="filter-tabs" id="filterTabs">
      <button data-status="pending" class="active">Pending</button>
      <button data-status="approved">Approved</button>
      <button data-status="rejected">Rejected</button>
      <button data-status="">All</button>
    </div>
    <div id="swapsWrap"><div class="loading-state">Loading...</div></div>
  `;

  const dateInput = document.getElementById("swapDate");
  async function refreshSlotPickers() {
    const weekdayLabel = document.getElementById("weekdayLabel");
    const aSel = document.getElementById("slotASelect");
    const bSel = document.getElementById("slotBSelect");
    const date = dateInput.value;
    if (!date) return;
    const dow = pyWeekday(date);
    weekdayLabel.textContent = `(${DAY_NAMES[dow]})`;
    aSel.innerHTML = `<option value="">Loading...</option>`;
    bSel.innerHTML = `<option value="">Loading...</option>`;
    try {
      const data = await apiRequest(`/timetables?day_of_week=${dow}&limit=200`);
      state.slots = data.items;
      const aOptions = isAdmin ? state.slots : state.slots.filter((s) => s.teacher_id === myTeacherId);
      aSel.innerHTML = aOptions.length
        ? `<option value="">Select...</option>` + aOptions.map((s) => `<option value="${s.id}">${slotOptionLabel(s)}</option>`).join("")
        : `<option value="">No slots on this day</option>`;
      const bOptions = state.slots;
      bSel.innerHTML = bOptions.length
        ? `<option value="">Select...</option>` + bOptions.map((s) => `<option value="${s.id}">${slotOptionLabel(s)}</option>`).join("")
        : `<option value="">No slots on this day</option>`;
    } catch (e) {
      aSel.innerHTML = `<option value="">${e.message}</option>`;
      bSel.innerHTML = `<option value="">${e.message}</option>`;
    }
  }
  dateInput.addEventListener("change", refreshSlotPickers);
  refreshSlotPickers();

  document.getElementById("submitSwapBtn").addEventListener("click", async () => {
    const msg = document.getElementById("swapMsg");
    const timetable_id_a = parseInt(document.getElementById("slotASelect").value);
    const timetable_id_b = parseInt(document.getElementById("slotBSelect").value);
    const date = dateInput.value;
    const reason = document.getElementById("swapReason").value || null;
    if (!timetable_id_a || !timetable_id_b) { msg.className = "msg error"; msg.textContent = "Pick both slots."; return; }
    if (timetable_id_a === timetable_id_b) { msg.className = "msg error"; msg.textContent = "Pick two different slots."; return; }
    try {
      await apiRequest("/swaps", { method: "POST", body: { timetable_id_a, timetable_id_b, date, reason } });
      msg.className = "msg success"; msg.textContent = "Swap request submitted.";
      document.getElementById("swapReason").value = "";
      load();
    } catch (e) {
      msg.className = "msg error"; msg.textContent = e.message;
    }
  });

  document.getElementById("filterTabs").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#filterTabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.status = b.dataset.status;
      load();
    })
  );

  async function load() {
    const wrap = document.getElementById("swapsWrap");
    wrap.innerHTML = `<div class="loading-state">Loading...</div>`;
    try {
      const q = new URLSearchParams({ limit: 50 });
      if (state.status) q.set("status", state.status);
      const data = await apiRequest(`/swaps?${q}`);
      if (!data.items.length) { wrap.innerHTML = `<div class="empty-state">No swap requests here.</div>`; return; }
      wrap.innerHTML = `<table><thead><tr><th>Date</th><th>Slot A</th><th>Slot B</th><th>Requested by</th><th>Status</th><th></th></tr></thead><tbody>
        ${data.items.map((s) => `<tr>
          <td>${s.date}</td>
          <td>${s.slot_a_label}</td>
          <td>${s.slot_b_label}</td>
          <td>${s.requested_by_name || "—"}</td>
          <td>${statusBadgeLocal(s.status)}</td>
          <td class="actions">
            ${s.status === "pending" && isAdmin ? `
              <button class="btn btn-primary" data-approve="${s.id}">Approve</button>
              <button class="btn btn-danger" data-reject="${s.id}">Reject</button>
            ` : ""}
            ${s.status === "pending" && (isAdmin || s.requested_by === me.id) ? `<button class="btn btn-ghost" data-cancel="${s.id}">Cancel</button>` : ""}
          </td>
        </tr>${s.decision_note ? `<tr><td></td><td colspan="5" style="color:var(--muted); font-size:12px; padding-top:0">Note: ${s.decision_note}</td></tr>` : ""}`).join("")}
      </tbody></table>`;

      wrap.querySelectorAll("[data-approve]").forEach((b) =>
        b.addEventListener("click", async () => {
          try {
            await apiRequest(`/swaps/${b.dataset.approve}/approve`, { method: "POST", body: {} });
            load();
          } catch (e) { alert(e.message); }
        })
      );
      wrap.querySelectorAll("[data-reject]").forEach((b) =>
        b.addEventListener("click", async () => {
          const note = prompt("Reason for rejection (optional):") || null;
          try {
            await apiRequest(`/swaps/${b.dataset.reject}/reject`, { method: "POST", body: { note } });
            load();
          } catch (e) { alert(e.message); }
        })
      );
      wrap.querySelectorAll("[data-cancel]").forEach((b) =>
        b.addEventListener("click", async () => {
          if (!confirm("Cancel this swap request?")) return;
          try {
            await apiRequest(`/swaps/${b.dataset.cancel}`, { method: "DELETE" });
            load();
          } catch (e) { alert(e.message); }
        })
      );
    } catch (e) {
      wrap.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }

  function statusBadgeLocal(status) {
    return `<span class="status-badge ${status}">${status}</span>`;
  }

  load();
}
