function initLeavesPage() {
  const root = document.getElementById("leaveRoot");
  root.innerHTML = `<div class="loading-state">Loading...</div>`;

  apiRequest("/auth/me").then((me) => {
    if (me.role === "teacher") renderTeacherView(me);
    else renderAdminView(me);
  }).catch((e) => {
    root.innerHTML = `<div class="empty-state">${e.message}</div>`;
  });
}

function statusBadge(status) {
  return `<span class="status-badge ${status}">${status}</span>`;
}

function methodBadge(method) {
  if (!method) return "";
  return `<span class="method-badge ${method}">${method.replace("_", " ")}</span>`;
}

// ---------------- Teacher view ----------------
function renderTeacherView(me) {
  const root = document.getElementById("leaveRoot");
  root.innerHTML = `
    <div class="leave-form-card">
      <h3>Apply for Leave</h3>
      <div class="msg" id="applyMsg"></div>
      <div class="leave-form-row">
        <div class="tt-field"><label>Start date</label><input type="date" id="leaveDate" /></div>
        <div class="tt-field"><label>End date (optional)</label><input type="date" id="leaveEndDate" /></div>
        <button class="btn btn-primary" id="applyBtn">Submit Request</button>
      </div>
      <label style="margin-top:12px">Reason (optional)</label>
      <textarea id="leaveReason" placeholder="e.g. Medical appointment"></textarea>
    </div>
    <h3 style="margin:18px 0 10px">My Leave Requests</h3>
    <div id="myLeavesWrap"><div class="loading-state">Loading...</div></div>
  `;

  document.getElementById("applyBtn").addEventListener("click", async () => {
    const date = document.getElementById("leaveDate").value;
    const end_date = document.getElementById("leaveEndDate").value || null;
    const reason = document.getElementById("leaveReason").value || null;
    const msg = document.getElementById("applyMsg");
    if (!date) { msg.className = "msg error"; msg.textContent = "Please pick a start date."; return; }
    try {
      await apiRequest("/leaves", { method: "POST", body: { date, end_date, reason } });
      msg.className = "msg success"; msg.textContent = "Leave request submitted.";
      document.getElementById("leaveDate").value = "";
      document.getElementById("leaveEndDate").value = "";
      document.getElementById("leaveReason").value = "";
      loadMyLeaves();
    } catch (e) {
      msg.className = "msg error"; msg.textContent = e.message;
    }
  });

  async function loadMyLeaves() {
    const wrap = document.getElementById("myLeavesWrap");
    try {
      const data = await apiRequest("/leaves?limit=50");
      if (!data.items.length) { wrap.innerHTML = `<div class="empty-state">No leave requests yet.</div>`; return; }
      wrap.innerHTML = `<table><thead><tr><th>Date</th><th>Reason</th><th>Status</th><th>Note</th><th></th></tr></thead><tbody>
        ${data.items.map((l) => `<tr>
          <td>${l.date}${l.end_date && l.end_date !== l.date ? " → " + l.end_date : ""}</td>
          <td>${l.reason || "—"}</td>
          <td>${statusBadge(l.status)}</td>
          <td>${l.decision_note || "—"}</td>
          <td class="actions">${l.status === "pending" ? `<button class="btn btn-danger" data-cancel="${l.id}">Cancel</button>` : ""}</td>
        </tr>`).join("")}
      </tbody></table>`;
      wrap.querySelectorAll("[data-cancel]").forEach((b) =>
        b.addEventListener("click", async () => {
          if (!confirm("Cancel this leave request?")) return;
          await apiRequest(`/leaves/${b.dataset.cancel}`, { method: "DELETE" });
          loadMyLeaves();
        })
      );
    } catch (e) {
      wrap.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }

  loadMyLeaves();
}

// ---------------- Admin view ----------------
function renderAdminView(me) {
  const root = document.getElementById("leaveRoot");
  const state = { status: "pending" };
  root.innerHTML = `
    <div class="filter-tabs" id="filterTabs">
      <button data-status="pending" class="active">Pending</button>
      <button data-status="approved">Approved</button>
      <button data-status="rejected">Rejected</button>
      <button data-status="">All</button>
    </div>
    <div id="resultZone"></div>
    <div id="leavesWrap"><div class="loading-state">Loading...</div></div>
  `;

  document.getElementById("filterTabs").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#filterTabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.status = b.dataset.status;
      load();
    })
  );

  async function load() {
    const wrap = document.getElementById("leavesWrap");
    wrap.innerHTML = `<div class="loading-state">Loading...</div>`;
    try {
      const q = new URLSearchParams({ limit: 50 });
      if (state.status) q.set("status", state.status);
      const data = await apiRequest(`/leaves?${q}`);
      if (!data.items.length) { wrap.innerHTML = `<div class="empty-state">No leave requests here.</div>`; return; }
      wrap.innerHTML = `<table><thead><tr><th>Teacher</th><th>Date</th><th>Reason</th><th>Status</th><th></th></tr></thead><tbody>
        ${data.items.map((l) => `<tr>
          <td>${l.teacher_name}</td>
          <td>${l.date}${l.end_date && l.end_date !== l.date ? " → " + l.end_date : ""}</td>
          <td>${l.reason || "—"}</td>
          <td>${statusBadge(l.status)}</td>
          <td class="actions">
            ${l.status === "pending" ? `
              <button class="btn btn-primary" data-approve="${l.id}">Approve</button>
              <button class="btn btn-danger" data-reject="${l.id}">Reject</button>
            ` : l.status === "approved" ? `<button class="btn btn-ghost" data-gaps="${l.id}">View gaps</button>` : ""}
          </td>
        </tr>`).join("")}
      </tbody></table>`;

      wrap.querySelectorAll("[data-approve]").forEach((b) =>
        b.addEventListener("click", () => approveLeave(b.dataset.approve))
      );
      wrap.querySelectorAll("[data-reject]").forEach((b) =>
        b.addEventListener("click", async () => {
          const note = prompt("Reason for rejection (optional):") || null;
          await apiRequest(`/leaves/${b.dataset.reject}/reject`, { method: "POST", body: { note } });
          load();
        })
      );
      wrap.querySelectorAll("[data-gaps]").forEach((b) =>
        b.addEventListener("click", () => showGaps(b.dataset.gaps))
      );
    } catch (e) {
      wrap.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
  }

  async function approveLeave(leaveId) {
    const resultZone = document.getElementById("resultZone");
    resultZone.innerHTML = `<div class="loading-state">Running auto-substitute engine...</div>`;
    try {
      const result = await apiRequest(`/leaves/${leaveId}/approve`, { method: "POST", body: {} });
      await renderApprovalResult(result.leave.school_id, result, leaveId);
      load();
    } catch (e) {
      resultZone.innerHTML = `<div class="tt-alert error">${e.message}</div>`;
    }
  }

  async function showGaps(leaveId) {
    const resultZone = document.getElementById("resultZone");
    resultZone.innerHTML = `<div class="loading-state">Checking coverage...</div>`;
    try {
      const gaps = await apiRequest(`/leaves/${leaveId}/gaps`);
      await renderApprovalResult(me.school_id, { leave: { id: leaveId }, substitutions_created: 0, uncovered_slots: gaps, message: gaps.length ? `${gaps.length} slot(s) still need a substitute.` : "All slots are covered." }, leaveId);
    } catch (e) {
      resultZone.innerHTML = `<div class="tt-alert error">${e.message}</div>`;
    }
  }

  async function renderApprovalResult(schoolId, result, leaveId) {
    const resultZone = document.getElementById("resultZone");
    const gaps = result.uncovered_slots || [];
    let teachers = [];
    try {
      const t = await apiRequest(`/teachers?limit=100`);
      teachers = t.items;
    } catch (e) { /* ignore */ }

    resultZone.innerHTML = `
      <div class="approval-result ${gaps.length ? "has-gaps" : ""}">
        <strong>${result.message}</strong>
        ${gaps.length ? `<div style="margin-top:10px">
          ${gaps.map((g, i) => `<div class="gap-row" data-gap="${i}">
            <span>${g.date} · period ${g.period} · ${g.section_name} · ${g.subject_name || g.activity_name || ""}</span>
            <span>
              <select data-teacher-select="${i}">
                <option value="">Assign teacher...</option>
                ${teachers.map((t) => `<option value="${t.id}">${t.name}${t.department ? " (" + t.department + ")" : ""}</option>`).join("")}
              </select>
              <button class="btn btn-primary" data-assign="${i}" style="padding:5px 10px; font-size:12px">Assign</button>
            </span>
          </div>`).join("")}
        </div>` : ""}
      </div>
    `;
    gaps.forEach((g, i) => {
      const btn = resultZone.querySelector(`[data-assign="${i}"]`);
      if (!btn) return;
      btn.addEventListener("click", async () => {
        const sel = resultZone.querySelector(`[data-teacher-select="${i}"]`);
        if (!sel.value) return;
        try {
          await apiRequest("/substitutions", {
            method: "POST",
            body: { leave_id: parseInt(leaveId), timetable_id: g.timetable_id, substitute_teacher_id: parseInt(sel.value), date: g.date },
          });
          btn.closest(".gap-row").innerHTML = "✅ Assigned.";
        } catch (e) {
          alert(e.message);
        }
      });
    });
  }

  load();
}
