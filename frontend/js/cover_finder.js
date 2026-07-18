// "Who can cover this hour?" — lists EVERY teacher eligible to substitute for one
// slot on one date, ranked with a suitability score.
// GET /substitutions/candidates?timetable_id=&date=   (read-only; creates nothing)

function initCoverFinder() {
  const state = { classes: [], sections: [], periods: 8, slots: [] };

  boot();

  async function boot() {
    try {
      const me = await apiRequest("/auth/me");
      const schools = (await apiRequest("/schools?limit=100")).items;
      const school = schools.find((s) => s.id === me.school_id) || schools[0];
      state.periods = school?.periods_per_day || 8;

      state.classes = (await apiRequest("/classes?limit=100")).items;
      const lists = await Promise.all(
        state.classes.map((c) => apiRequest(`/sections?limit=200&class_id=${c.id}`))
      );
      state.sections = lists.flatMap((res, i) =>
        res.items.map((s) => ({ ...s, class_name: state.classes[i].name })));

      document.getElementById("cfClass").innerHTML = state.classes
        .map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
      document.getElementById("cfPeriod").innerHTML = Array.from(
        { length: state.periods }, (_, i) => `<option value="${i + 1}">Period ${i + 1}</option>`).join("");
      document.getElementById("cfDate").value = new Date().toISOString().slice(0, 10);

      fillSections();
      document.getElementById("cfClass").addEventListener("change", fillSections);
      document.getElementById("cfFind").addEventListener("click", find);
    } catch (err) {
      msg("error", err.message);
    }
  }

  function fillSections() {
    const cid = Number(document.getElementById("cfClass").value);
    document.getElementById("cfSection").innerHTML = state.sections
      .filter((s) => s.class_id === cid)
      .map((s) => `<option value="${s.id}">${s.name}</option>`).join("");
  }

  function msg(kind, text) {
    const el = document.getElementById("cfMsg");
    if (!text) { el.style.display = "none"; return; }
    el.className = `msg ${kind}`;
    el.textContent = text;
    el.style.display = "block";
  }

  async function find() {
    msg(null);
    const result = document.getElementById("cfResult");
    result.innerHTML = `<div class="loading-state">Checking who is free…</div>`;

    const sectionId = Number(document.getElementById("cfSection").value);
    const dateStr = document.getElementById("cfDate").value;
    const period = Number(document.getElementById("cfPeriod").value);
    if (!sectionId || !dateStr) { msg("error", "Choose a section and a date."); result.innerHTML = ""; return; }

    try {
      // Resolve the master slot for that section on that weekday + period.
      const dow = (new Date(dateStr + "T00:00:00").getDay() + 6) % 7; // Mon=0
      const slots = (await apiRequest(`/timetables/section/${sectionId}`)).slots || [];
      const slot = slots.find((s) => s.day_of_week === dow && s.period === period);
      if (!slot) {
        result.innerHTML = "";
        msg("info", `That section has no class scheduled at period ${period} on that weekday — nothing to cover.`);
        return;
      }

      const data = await apiRequest(`/substitutions/candidates?timetable_id=${slot.id}&date=${dateStr}`);
      render(data, slot);
    } catch (err) {
      result.innerHTML = "";
      msg("error", err.message);
    }
  }

  function render(data, slot) {
    const result = document.getElementById("cfResult");
    const cands = data.candidates || [];

    const header = `
      <p style="font-size:13px; margin:14px 0 8px">
        <b>${data.section_name} · Period ${data.period} · ${data.date}</b> —
        normally ${slot.subject_name || slot.activity_name || "a class"}
        with <b>${slot.teacher_name || "—"}</b>.
        ${data.assigned_teacher
          ? `Currently covered by <b>${data.assigned_teacher}</b>.`
          : `No cover raised yet — this is who <i>would</i> be available.`}
      </p>`;

    if (!cands.length) {
      result.innerHTML = header +
        `<div class="empty-state">No teacher is free and available for this hour.
         Covering it would double-book someone or use a teacher outside their availability.</div>`;
      return;
    }

    const badge = (c) => {
      if (c.status === "assigned") return `<span class="status-badge approved">assigned</span>`;
      if (c.status === "declined") return `<span class="status-badge rejected">declined</span>`;
      if (c.status === "backup") return `<span class="status-badge pending">backup</span>`;
      return `<span class="method-badge available">eligible</span>`;
    };

    result.innerHTML = header + `
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Rank</th><th>Teacher</th><th>Score</th><th>Match</th><th>Why</th><th>Status</th>
        </tr></thead>
        <tbody>
          ${cands.map((c) => `
            <tr>
              <td><b>${c.rank}</b></td>
              <td>${c.teacher_name}</td>
              <td><b>${c.score}%</b></td>
              <td><span class="method-badge ${c.method}">${(c.method || "").replace("_", " ")}</span></td>
              <td style="font-size:12px; color:var(--muted)">
                ${c.reason || ""}${c.decline_reason ? `<br><i>Declined: ${c.decline_reason}</i>` : ""}
              </td>
              <td>${badge(c)}</td>
            </tr>`).join("")}
        </tbody>
      </table></div>
      <p style="font-size:12px; color:var(--muted); margin-top:8px">
        ${cands.length} teacher(s) available. Rank 1 is auto-assigned; the rest are the backup
        queue and are promoted automatically if someone declines.
      </p>`;
  }
}
