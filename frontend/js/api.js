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
  if (!res.ok) {
    const err = new Error(formatApiError(data, res.status));
    // Callers need to tell "you are not signed in" (401/403) apart from "the network
    // hiccuped" (500 / offline). Without this, a transient blip looks like a logout.
    err.status = res.status;
    throw err;
  }
  return data;
}

// FastAPI error bodies vary: detail can be a string, a validation-error array
// ([{loc, msg, type}, ...]) or an object. Flatten any of them to a readable
// string so the UI never shows a bare "[object Object]".
function formatApiError(data, status) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
        return field ? `${field}: ${e.msg}` : e.msg || JSON.stringify(e);
      })
      .join("; ") || `Request failed (${status})`;
  }
  if (d && typeof d === "object") return d.message || JSON.stringify(d);
  return d || `Request failed (${status})`;
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
