// AI Assistant Floating Widget (Phase 8)
// Self-contained injection of chatbot UI and styles.

(function() {
  const role = localStorage.getItem("role");
  const token = localStorage.getItem("token");
  if (!token || (role !== "school_admin" && role !== "super_admin")) {
    return; // Admin-only chat
  }

  // Inject Styles
  const style = document.createElement("style");
  style.textContent = `
    .ai-chat-btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: linear-gradient(135deg, #2563eb, #16a34a);
      color: white;
      border: none;
      box-shadow: 0 4px 20px rgba(37, 99, 235, 0.3);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      z-index: 1000;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    .ai-chat-btn:hover {
      transform: scale(1.05);
      box-shadow: 0 6px 24px rgba(37, 99, 235, 0.4);
    }
    .ai-chat-window {
      position: fixed;
      bottom: 96px;
      right: 24px;
      width: 360px;
      height: 500px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.85);
      backdrop-filter: blur(20px) saturate(180%);
      -webkit-backdrop-filter: blur(20px) saturate(180%);
      border: 1px solid rgba(255, 255, 255, 0.5);
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
      display: flex;
      flex-direction: column;
      z-index: 1000;
      overflow: hidden;
      transform: translateY(20px);
      opacity: 0;
      pointer-events: none;
      transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s;
    }
    .ai-chat-window.open {
      transform: translateY(0);
      opacity: 1;
      pointer-events: auto;
    }
    .ai-chat-header {
      background: linear-gradient(135deg, rgba(37, 99, 235, 0.9), rgba(22, 103, 74, 0.9));
      color: white;
      padding: 16px;
      font-weight: 600;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .ai-chat-close {
      background: none;
      border: none;
      color: white;
      font-size: 18px;
      cursor: pointer;
      opacity: 0.8;
    }
    .ai-chat-close:hover {
      opacity: 1;
    }
    .ai-chat-messages {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .ai-msg {
      max-width: 80%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13px;
      line-height: 1.4;
    }
    .ai-msg.user {
      background: #2563eb;
      color: white;
      align-self: flex-end;
      border-bottom-right-radius: 2px;
    }
    .ai-msg.bot {
      background: #e2e8f0;
      color: #1e293b;
      align-self: flex-start;
      border-bottom-left-radius: 2px;
    }
    .ai-chat-input-area {
      padding: 12px;
      border-top: 1px solid rgba(0, 0, 0, 0.08);
      display: flex;
      gap: 8px;
      background: rgba(255, 255, 255, 0.5);
    }
    .ai-chat-input-area input {
      flex: 1;
      border: 1px solid #cbd5e1;
      background: rgba(255, 255, 255, 0.8);
    }
    .ai-chat-send {
      padding: 0 16px;
      background: #2563eb;
      color: white;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
      font-size: 13px;
    }
    .ai-chat-send:hover {
      background: #1d4ed8;
    }
  `;
  document.head.appendChild(style);

  // Inject UI Elements
  const container = document.createElement("div");
  container.innerHTML = `
    <button class="ai-chat-btn" id="aiChatBtn" title="Ask Assistant">🤖</button>
    <div class="ai-chat-window" id="aiChatWindow">
      <div class="ai-chat-header">
        <span>EduFlow AI Assistant</span>
        <button class="ai-chat-close" id="aiChatClose">×</button>
      </div>
      <div class="ai-chat-messages" id="aiChatMessages">
        <div class="ai-msg bot">Hello! I am your EduFlow AI assistant. How can I help you manage your school scheduling today?</div>
      </div>
      <form class="ai-chat-input-area" id="aiChatForm">
        <input type="text" id="aiChatInput" placeholder="Type a message..." required autocomplete="off" />
        <button type="submit" class="ai-chat-send">Send</button>
      </form>
    </div>
  `;
  document.body.appendChild(container);

  const chatBtn = document.getElementById("aiChatBtn");
  const chatWindow = document.getElementById("aiChatWindow");
  const chatClose = document.getElementById("aiChatClose");
  const chatMessages = document.getElementById("aiChatMessages");
  const chatForm = document.getElementById("aiChatForm");
  const chatInput = document.getElementById("aiChatInput");

  // Toggle Window
  chatBtn.addEventListener("click", () => {
    chatWindow.classList.toggle("open");
    if (chatWindow.classList.contains("open")) {
      chatInput.focus();
    }
  });

  chatClose.addEventListener("click", () => {
    chatWindow.classList.remove("open");
  });

  // Append Message Helper
  function appendMsg(text, isUser = false) {
    const msg = document.createElement("div");
    msg.className = `ai-msg ${isUser ? 'user' : 'bot'}`;
    msg.innerHTML = text.replace(/\n/g, "<br>");
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // Handle Form Submit
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;

    chatInput.value = "";
    appendMsg(text, true);

    // Show loading
    const loadingMsg = document.createElement("div");
    loadingMsg.className = "ai-msg bot";
    loadingMsg.textContent = "Thinking...";
    chatMessages.appendChild(loadingMsg);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
      // Determine active school ID if on dashboard, or fall back to me.school_id
      let schoolId = typeof currentSchoolId !== 'undefined' ? currentSchoolId : null;
      if (!schoolId) {
        const me = await apiRequest("/auth/me");
        schoolId = me.school_id;
      }

      const res = await apiRequest("/assistant/chat", {
        method: "POST",
        body: {
          message: text,
          school_id: schoolId
        }
      });
      loadingMsg.remove();
      appendMsg(res.reply);
    } catch (err) {
      loadingMsg.remove();
      appendMsg(`Error: ${err.message}`);
    }
  });

  // Globally expose conflict explanation helper
  window.explainConflict = async function(detail, context = {}) {
    chatWindow.classList.add("open");
    appendMsg(`Can you explain this conflict: "${detail}"?`, true);
    
    const loadingMsg = document.createElement("div");
    loadingMsg.className = "ai-msg bot";
    loadingMsg.textContent = "Analyzing conflict details...";
    chatMessages.appendChild(loadingMsg);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
      const res = await apiRequest("/assistant/explain-conflict", {
        method: "POST",
        body: { detail, context }
      });
      loadingMsg.remove();
      appendMsg(res.explanation);
    } catch (err) {
      loadingMsg.remove();
      appendMsg(`Error explaining conflict: ${err.message}`);
    }
  };
  
  window.explainInfeasibility = async function(errors, warnings = []) {
    chatWindow.classList.add("open");
    appendMsg(`Can you explain why the timetable could not be generated with these validation errors: ${JSON.stringify(errors)}?`, true);
    
    const loadingMsg = document.createElement("div");
    loadingMsg.className = "ai-msg bot";
    loadingMsg.textContent = "Analyzing solver infeasibility...";
    chatMessages.appendChild(loadingMsg);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    try {
      const res = await apiRequest("/assistant/explain-infeasibility", {
        method: "POST",
        body: { errors, warnings }
      });
      loadingMsg.remove();
      appendMsg(res.explanation);
    } catch (err) {
      loadingMsg.remove();
      appendMsg(`Error explaining infeasibility: ${err.message}`);
    }
  };

})();
