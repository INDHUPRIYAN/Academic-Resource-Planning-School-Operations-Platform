document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("msg");
  const btn = document.getElementById("submitBtn");
  msg.className = "msg";
  btn.disabled = true;
  btn.textContent = "Signing in...";

  try {
    const data = await apiRequest("/auth/login", {
      method: "POST",
      auth: false,
      body: {
        email: document.getElementById("email").value.trim(),
        password: document.getElementById("password").value,
      },
    });
    localStorage.setItem("token", data.access_token);
    localStorage.setItem("role", data.role);
    localStorage.setItem("name", data.name);
    window.location.href = "dashboard.html";
  } catch (err) {
    msg.textContent = err.message;
    msg.className = "msg error";
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign In";
  }
});
