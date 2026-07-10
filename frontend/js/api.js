// Override per deployment without a build step: set `window.EDUFLOW_API_BASE`
// before this script loads, or `localStorage.eduflow_api_base` at runtime.
// When the backend serves these pages under /app, it is also the API origin.
const API_BASE =
  window.EDUFLOW_API_BASE ||
  localStorage.getItem("eduflow_api_base") ||
  (location.pathname.startsWith("/app/") ? location.origin : "http://localhost:8000");

async function apiRequest(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = localStorage.getItem("token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function requireAuth() {
  if (!localStorage.getItem("token")) window.location.href = "index.html";
}

function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("role");
  localStorage.removeItem("name");
  window.location.href = "index.html";
}
