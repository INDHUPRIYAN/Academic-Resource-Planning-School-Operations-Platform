// Generic CRUD page renderer. config = { endpoint, title, columns:[{key,label}], fields:[{key,label,type}], pageSize }
function initCrudPage(config) {
  const state = { page: 1, search: "", editing: null };

  const root = document.getElementById("crudRoot");
  root.innerHTML = `
    <div class="toolbar">
      <input type="search" id="searchInput" placeholder="Search ${config.title.toLowerCase()}..." />
      <button class="btn btn-primary" id="addBtn">+ Add ${config.title.slice(0, -1)}</button>
    </div>
    <div id="tableWrap"><div class="loading-state">Loading...</div></div>
    <div class="pagination" id="pagination"></div>
  `;

  document.getElementById("searchInput").addEventListener("input", (e) => {
    state.search = e.target.value;
    state.page = 1;
    load();
  });
  document.getElementById("addBtn").addEventListener("click", () => openForm(null));

  async function load() {
    const wrap = document.getElementById("tableWrap");
    try {
      const q = new URLSearchParams({ page: state.page, limit: config.pageSize || 10, search: state.search });
      const data = await apiRequest(`${config.endpoint}?${q}`);
      renderTable(data);
    } catch (err) {
      wrap.innerHTML = `<div class="empty-state">${err.message}</div>`;
    }
  }

  function renderTable(data) {
    const wrap = document.getElementById("tableWrap");
    if (!data.items.length) {
      wrap.innerHTML = `<div class="empty-state">No ${config.title.toLowerCase()} yet.</div>`;
    } else {
      const head = config.columns.map((c) => `<th>${c.label}</th>`).join("") + "<th></th>";
      const rows = data.items
        .map((item) => {
          const cells = config.columns.map((c) => `<td>${item[c.key] ?? ""}</td>`).join("");
          return `<tr>${cells}<td class="actions">
            <button class="btn btn-ghost" data-edit="${item.id}">Edit</button>
            <button class="btn btn-danger" data-delete="${item.id}">Delete</button>
          </td></tr>`;
        })
        .join("");
      wrap.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
      wrap.querySelectorAll("[data-edit]").forEach((b) =>
        b.addEventListener("click", () => openForm(data.items.find((i) => i.id == b.dataset.edit)))
      );
      wrap.querySelectorAll("[data-delete]").forEach((b) =>
        b.addEventListener("click", () => confirmDelete(b.dataset.delete))
      );
    }

    const totalPages = Math.max(1, Math.ceil(data.total / data.limit));
    const pag = document.getElementById("pagination");
    pag.innerHTML = `
      <button class="btn btn-ghost" id="prevPage" ${state.page <= 1 ? "disabled" : ""}>Prev</button>
      <span>Page ${state.page} of ${totalPages}</span>
      <button class="btn btn-ghost" id="nextPage" ${state.page >= totalPages ? "disabled" : ""}>Next</button>
    `;
    document.getElementById("prevPage")?.addEventListener("click", () => { state.page--; load(); });
    document.getElementById("nextPage")?.addEventListener("click", () => { state.page++; load(); });
  }

  function openForm(item) {
    state.editing = item;
    const fieldsHtml = config.fields
      .map((f) => {
        const val = item ? (item[f.key] ?? "") : "";
        const reqMod = f.requiresModule ? ` data-requires-module="${f.requiresModule}"` : "";
        if (f.type === "select") {
          const opts = (f.options || []).map(o => `<option value="${o.value}" ${o.value == val ? "selected" : ""}>${o.label}</option>`).join("");
          return `<label${reqMod}>${f.label}</label><select name="${f.key}"${reqMod}>${opts}</select>`;
        }
        return `<label${reqMod}>${f.label}</label><input name="${f.key}" type="${f.type || "text"}" value="${val}" ${f.required ? "required" : ""}${reqMod} />`;
      })
      .join("");
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal">
        <h3>${item ? "Edit" : "Add"} ${config.title.slice(0, -1)}</h3>
        <form id="crudForm">${fieldsHtml}
          <div class="msg" id="formMsg"></div>
          <div class="modal-actions">
            <button type="button" class="btn btn-ghost" id="cancelBtn">Cancel</button>
            <button type="submit" class="btn btn-primary">Save</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(backdrop);
    if (typeof DynamicUI !== "undefined") {
      DynamicUI.applyAll();
    }
    backdrop.querySelector("#cancelBtn").addEventListener("click", () => backdrop.remove());
    backdrop.querySelector("#crudForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const body = {};
      config.fields.forEach((f) => {
        const v = form.get(f.key);
        if (f.type === "number") {
          body[f.key] = (v === "" || v === null) ? null : Number(v);
        } else if (f.key === "resource_id" || f.key === "school_id") {
          body[f.key] = (v === "" || v === null || isNaN(Number(v))) ? null : Number(v);
        } else {
          body[f.key] = v;
        }
      });
      try {
        if (item) await apiRequest(`${config.endpoint}/${item.id}`, { method: "PUT", body });
        else await apiRequest(config.endpoint, { method: "POST", body });
        backdrop.remove();
        load();
      } catch (err) {
        backdrop.querySelector("#formMsg").className = "msg error";
        backdrop.querySelector("#formMsg").textContent = err.message;
      }
    });
  }

  function confirmDelete(id) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `
      <div class="modal confirm-modal">
        <h3>Delete this ${config.title.slice(0, -1).toLowerCase()}?</h3>
        <p>This action cannot be undone.</p>
        <div class="modal-actions">
          <button class="btn btn-ghost" id="cancelDel">Cancel</button>
          <button class="btn btn-danger" id="confirmDel">Delete</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    backdrop.querySelector("#cancelDel").addEventListener("click", () => backdrop.remove());
    backdrop.querySelector("#confirmDel").addEventListener("click", async () => {
      try {
        await apiRequest(`${config.endpoint}/${id}`, { method: "DELETE" });
        backdrop.remove();
        load();
      } catch (err) {
        backdrop.remove();
        alert(err.message);
      }
    });
  }

  load();
}
