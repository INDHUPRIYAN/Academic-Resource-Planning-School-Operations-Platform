// Bulk Upload Logic
requireAuth();
renderTopbar("bulk.html");

let selectedFile = null;
let currentSchoolId = null;

async function initBulkPage() {
  const me = await apiRequest("/auth/me");
  
  if (me.role === "super_admin") {
    // Show school selector
    const wrap = document.getElementById("schoolSelectWrap");
    wrap.style.display = "block";
    
    const select = document.getElementById("schoolSelect");
    const schools = (await apiRequest("/schools?limit=100")).items;
    
    if (!schools.length) {
      document.getElementById("uploadMsg").className = "msg error";
      document.getElementById("uploadMsg").textContent = "Please create a school first in the Schools tab.";
      document.getElementById("uploadMsg").style.display = "block";
      return;
    }
    
    select.innerHTML = schools.map(s => `<option value="${s.id}">${s.name}</option>`).join("");
    currentSchoolId = parseInt(select.value);
    
    select.addEventListener("change", () => {
      currentSchoolId = parseInt(select.value);
    });
  } else {
    currentSchoolId = me.school_id;
  }

  // Setup template download
  document.getElementById("downloadTemplateBtn").addEventListener("click", downloadTemplate);

  // Setup file drag-and-drop / selector
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const dropText = document.getElementById("dropText");
  const uploadBtn = document.getElementById("uploadBtn");

  dropZone.addEventListener("click", () => fileInput.click());
  
  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) {
      handleFile(e.target.files[0]);
    }
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  function handleFile(file) {
    selectedFile = file;
    dropText.innerHTML = `Selected file: <strong>${file.name}</strong> (${(file.size / 1024).toFixed(1)} KB)`;
    uploadBtn.disabled = false;
  }

  // Setup upload submission
  uploadBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    
    const msg = document.getElementById("uploadMsg");
    const results = document.getElementById("resultsCard");
    msg.style.display = "none";
    results.style.display = "none";
    
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Processing upload...";
    
    const formData = new FormData();
    formData.append("file", selectedFile);
    
    const token = localStorage.getItem("token");
    const headers = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    
    try {
      const url = new URL(`${API_BASE}/bulk/upload`);
      if (currentSchoolId) {
        url.searchParams.append("school_id", currentSchoolId);
      }
      
      const res = await fetch(url.toString(), {
        method: "POST",
        headers,
        body: formData
      });
      
      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.detail || "Upload failed");
      }
      
      // Display success message
      msg.className = "msg success";
      msg.textContent = data.message || "Data imported successfully!";
      msg.style.display = "block";
      
      // Update statistics
      document.getElementById("statClasses").textContent = data.stats.classes_created;
      document.getElementById("statSections").textContent = data.stats.sections_created;
      document.getElementById("statResources").textContent = data.stats.resources_created;
      document.getElementById("statSubjects").textContent = data.stats.subjects_created;
      document.getElementById("statTeachers").textContent = data.stats.teachers_created;
      
      results.style.display = "block";
      
      // Reset input
      selectedFile = null;
      fileInput.value = "";
      dropText.innerHTML = `Drag and drop your Excel file here, or <span style="color:var(--blue); text-decoration: underline;">browse files</span>`;
      
    } catch (err) {
      msg.className = "msg error";
      msg.textContent = err.message;
      msg.style.display = "block";
    } finally {
      uploadBtn.disabled = true; // Disabled until a new file is chosen
      uploadBtn.textContent = "Upload and Seed Data";
    }
  });
}

async function downloadTemplate() {
  const token = localStorage.getItem("token");
  const headers = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  
  try {
    const res = await fetch(`${API_BASE}/bulk/template`, { headers });
    if (!res.ok) throw new Error("Could not download template");
    
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "eduflow_bulk_template.xlsx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    alert("Template download failed: " + err.message);
  }
}

initBulkPage();
