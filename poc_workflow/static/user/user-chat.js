const state = {
  bootstrap: null,
  templateId: null,
  templateLabel: null,
  sessionId: getOrCreateStoredId("kbUserChatSessionId", "session"),
  deviceId: getOrCreateStoredId("kbUserChatDeviceId", "device"),
  lastResponse: null,
  drawerHidden: isCompactLayout(),
  heartbeatTimer: null,
};

const qs = (selector) => document.querySelector(selector);
const NO_SOURCE_TEXT = "Không tìm thấy căn cứ trong tài liệu hiện hành.";
const LOADING_STEPS = [
  "Đang hiểu câu hỏi...",
  "Đang tìm trong tài liệu hiện hành...",
  "Đang chọn nguồn phù hợp...",
  "Đang tạo câu trả lời...",
];

function isCompactLayout() {
  return window.matchMedia?.("(max-width: 1040px)")?.matches ?? false;
}

function createId(prefix) {
  if (window.crypto?.randomUUID) {
    return `${prefix}-${window.crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getOrCreateStoredId(key, prefix) {
  const current = localStorage.getItem(key);
  if (current) return current;
  const value = createId(prefix);
  localStorage.setItem(key, value);
  return value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function parseMarkdown(text) {
  if (!text) return "";
  
  // First escape HTML to prevent XSS
  const html = escapeHtml(text);
  const lines = html.split("\n");
  const result = [];
  let inUl = false;
  let inOl = false;
  let inCode = false;
  let codeLang = "";
  let codeLines = [];
  
  for (let line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inCode) {
        result.push(renderCodeBlock(codeLang, codeLines.join("\n")));
        inCode = false;
        codeLang = "";
        codeLines = [];
      } else {
        if (inUl) {
          result.push("</ul>");
          inUl = false;
        }
        if (inOl) {
          result.push("</ol>");
          inOl = false;
        }
        inCode = true;
        codeLang = trimmed.slice(3).trim().toLowerCase();
        codeLines = [];
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }
    
    // Unordered lists: starts with "- " or "* "
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      if (inOl) {
        result.push("</ol>");
        inOl = false;
      }
      if (!inUl) {
        result.push('<ul class="markdown-ul">');
        inUl = true;
      }
      const content = trimmed.substring(2);
      result.push(`<li>${formatInlineMarkdown(content)}</li>`);
      continue;
    }
    
    // Ordered lists: starts with e.g. "1. " or "2. "
    const olMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
    if (olMatch) {
      if (inUl) {
        result.push("</ul>");
        inUl = false;
      }
      if (!inOl) {
        result.push('<ol class="markdown-ol">');
        inOl = true;
      }
      const content = olMatch[2];
      result.push(`<li>${formatInlineMarkdown(content)}</li>`);
      continue;
    }
    
    // Close lists if we hit a non-list line
    if (inUl) {
      result.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      result.push("</ol>");
      inOl = false;
    }
    
    // Headings
    if (trimmed.startsWith("### ")) {
      result.push(`<h3>${formatInlineMarkdown(trimmed.substring(4))}</h3>`);
    } else if (trimmed.startsWith("## ")) {
      result.push(`<h2>${formatInlineMarkdown(trimmed.substring(3))}</h2>`);
    } else if (trimmed.startsWith("# ")) {
      result.push(`<h1>${formatInlineMarkdown(trimmed.substring(2))}</h1>`);
    } else if (trimmed === "") {
      result.push('<p class="markdown-empty-line"></p>');
    } else {
      result.push(`<p class="markdown-para">${formatInlineMarkdown(line)}</p>`);
    }
  }
  
  if (inUl) result.push("</ul>");
  if (inOl) result.push("</ol>");
  if (inCode) result.push(renderCodeBlock(codeLang, codeLines.join("\n")));
  
  return result.join("\n");
}

function formatInlineMarkdown(value) {
  let html = String(value ?? "");
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
  html = html.replace(/`(.*?)`/g, "<code>$1</code>");
  html = html.replace(
    /\[(.*?)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return html;
}

function renderCodeBlock(lang, code) {
  if (lang === "mermaid") {
    return renderMermaidWorkflow(code);
  }
  return `<pre class="markdown-code"><code>${code}</code></pre>`;
}

function renderMermaidWorkflow(code) {
  const labels = [];
  const seen = new Set();
  const nodePattern = /([A-Za-z][A-Za-z0-9_-]*)\[(?:(?:"|&quot;)(.*?)(?:"|&quot;)|([^\]]+))\]/g;
  for (const line of code.split("\n")) {
    for (const match of line.matchAll(nodePattern)) {
      if (seen.has(match[1])) continue;
      seen.add(match[1]);
      const label = (match[2] || match[3] || "").trim();
      if (label) labels.push(label);
    }
  }
  if (!labels.length) {
    return `<pre class="markdown-code"><code>${code}</code></pre>`;
  }
  return `
    <div class="workflow-diagram">
      <div class="workflow-nodes">
        ${labels
          .map(
            (label, index) => `
              <div class="workflow-node">
                <span>${index + 1}</span>
                <p>${label}</p>
              </div>
              ${index < labels.length - 1 ? '<div class="workflow-arrow" aria-hidden="true">&darr;</div>' : ""}
            `,
          )
          .join("")}
      </div>
      <details class="workflow-source">
        <summary>Mermaid</summary>
        <pre class="markdown-code"><code>${code}</code></pre>
      </details>
    </div>
  `;
}

function toast(message) {
  const target = qs("#toast");
  target.textContent = message;
  target.classList.add("show");
  window.setTimeout(() => target.classList.remove("show"), 2800);
}

// Spotlight cursor tracking function
function handleSpotlightMove(e) {
  const card = e.currentTarget;
  const rect = card.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  card.style.setProperty("--mouse-x", `${x}px`);
  card.style.setProperty("--mouse-y", `${y}px`);
}

function wireSpotlight(selector) {
  document.querySelectorAll(selector).forEach((card) => {
    card.removeEventListener("mousemove", handleSpotlightMove);
    card.addEventListener("mousemove", handleSpotlightMove);
  });
}

// Textarea auto grow
function autoGrowTextarea() {
  const textarea = qs("#queryInput");
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = textarea.scrollHeight + "px";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.error || response.statusText);
  }
  return payload;
}

function statusClass(serviceStatus) {
  if (serviceStatus?.state === "ok") return "ok";
  if (["maintenance", "incident", "offline", "unavailable"].includes(serviceStatus?.state)) return "bad";
  return "";
}

function applyStatus(serviceStatus) {
  const railStatus = qs("#railStatus");
  railStatus.className = `rail-status ${statusClass(serviceStatus)}`.trim();
  qs("#statusText").textContent = serviceStatus?.can_chat === false ? "Tạm dừng" : "Sẵn sàng";
}

function renderBootstrap() {
  qs("#assistantLine").textContent = "Trợ lý đang dùng: Tài liệu đang hiệu lực | Quy tắc: Trả lời có nguồn";
  renderAnswerStyles();
  renderTemplates();
  renderWelcomeCards();
  applyStatus(state.bootstrap?.service_status);
  switchDrawerTab("sources");
}

function renderAnswerStyles() {
  const styles = state.bootstrap?.answer_styles || [
    { id: "brief", label: "Ngắn gọn" },
    { id: "steps", label: "Từng bước" },
    { id: "checklist", label: "Checklist" },
    { id: "workflow", label: "Workflow" },
  ];
  qs("#answerStyle").innerHTML = styles
    .map((style) => `<option value="${escapeHtml(style.id)}">${escapeHtml(style.label)}</option>`)
    .join("");
}

function renderWelcomeCards() {
  const cards = state.bootstrap?.welcome_cards || [];
  qs("#welcomeCards").innerHTML = cards
    .map(
      (card) => `
        <button
          class="welcome-card"
          type="button"
          data-template-id="${escapeHtml(card.template_id)}"
          data-question="${escapeHtml(card.question)}"
          data-label="${escapeHtml(card.label)}"
          data-answer-style="${escapeHtml(card.answer_style || "brief")}"
        >
          <span>${escapeHtml(card.label)}</span>
          <small>${escapeHtml(card.question)}</small>
        </button>
      `,
    )
    .join("");
  document.querySelectorAll(".welcome-card").forEach((button) => {
    button.addEventListener("click", () => selectPrompt(button));
  });
  wireSpotlight(".welcome-card");
}

function renderTemplates() {
  const groups = state.bootstrap?.templates?.groups || [];
  const target = qs("#templateGroups");
  target.innerHTML = groups
    .flatMap((group) =>
      (group.templates || []).map(
        (template) => `
          <button
            class="template-chip"
            type="button"
            data-template-id="${escapeHtml(template.id)}"
            data-question="${escapeHtml(template.question)}"
            data-label="${escapeHtml(group.label)}"
          >
            ${escapeHtml(group.label)}
          </button>
        `,
      ),
    )
    .join("");
  document.querySelectorAll(".template-chip").forEach((button) => {
    button.addEventListener("click", () => selectPrompt(button));
  });
}

function selectPrompt(button) {
  state.templateId = button.dataset.templateId || null;
  state.templateLabel = button.dataset.label || null;
  qs("#queryInput").value = button.dataset.question || "";
  autoGrowTextarea();
  if (button.dataset.answerStyle) {
    qs("#answerStyle").value = button.dataset.answerStyle;
  }
  qs("#selectedTemplate").textContent = state.templateLabel || "Không dùng mẫu";
  document.querySelectorAll(".template-chip").forEach((item) => {
    item.classList.toggle("active", item.dataset.templateId === state.templateId);
  });
  qs("#queryInput").focus();
}

function appendMessage(role, html, actions = "") {
  const target = qs("#messages");
  qs("#welcomeState")?.remove();
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = `<div class="message-body">${html}</div>${actions}`;
  target.appendChild(article);
  target.scrollTop = target.scrollHeight;
  return article;
}

function renderFeedbackActions(logId) {
  if (!logId) return "";
  const options = [
    ["correct", "Đúng"],
    ["wrong", "Sai"],
    ["missing_source", "Thiếu nguồn"],
  ];
  return `
    <div class="message-actions" data-log-id="${escapeHtml(logId)}">
      <button class="copy-button" type="button" title="Sao chép câu trả lời">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>
        <span>Sao chép</span>
      </button>
      ${options
        .map(([value, label]) => `<button class="feedback-button" type="button" data-feedback="${value}">${label}</button>`)
        .join("")}
    </div>
  `;
}

function wireFeedback(container = document) {
  // Wire Copy Button
  container.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", () => {
      const messageBody = button.closest(".message")?.querySelector(".message-body");
      if (messageBody) {
        // Strip copy buttons text and feedback steps if nested
        const textToCopy = messageBody.innerText.trim();
        navigator.clipboard.writeText(textToCopy)
          .then(() => toast("Đã sao chép vào bộ nhớ tạm"))
          .catch((err) => toast("Lỗi khi sao chép: " + err));
      }
    });
  });

  // Wire Feedback Buttons
  container.querySelectorAll(".feedback-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const logId = Number(button.closest(".message-actions")?.dataset.logId || 0);
      if (!logId) return;
      try {
        await api("/api/user/feedback", {
          method: "POST",
          body: JSON.stringify({
            log_id: logId,
            rating: button.dataset.feedback,
            session_id: state.sessionId,
          }),
        });
        toast("Đã ghi nhận phản hồi");
      } catch (error) {
        toast(error.message);
      }
    });
  });
}

async function submitChat(event) {
  event.preventDefault();
  const query = qs("#queryInput").value.trim();
  if (!query) {
    qs("#queryInput").focus();
    return;
  }

  qs("#sendBtn").disabled = true;
  appendMessage("user", escapeHtml(query));
  const pending = appendMessage("assistant", renderLoadingMessage());
  if (!isCompactLayout()) {
    ensureDrawerVisible();
  }
  switchDrawerTab("trace");
  renderTrace(LOADING_STEPS.map((label) => ({ label, status: "empty", detail: "" })));

  try {
    const result = await api("/api/user/chat", {
      method: "POST",
      body: JSON.stringify({
        query,
        template_id: state.templateId,
        answer_style: qs("#answerStyle").value,
        session_id: state.sessionId,
        device_id: state.deviceId,
        use_llm: true,
      }),
    });
    state.lastResponse = result;
    if (result.session?.session_id) {
      state.sessionId = result.session.session_id;
      localStorage.setItem("kbUserChatSessionId", state.sessionId);
    }
    pending.querySelector(".message-body").innerHTML = parseMarkdown(result.answer || NO_SOURCE_TEXT);
    pending.insertAdjacentHTML("beforeend", renderFeedbackActions(result.log_id || result.query_log_id));
    wireFeedback(pending);
    renderSources(result.citations || []);
    renderTrace(result.trace_steps || result.trace?.steps || []);
    switchDrawerTab("sources");
    qs("#drawerMeta").textContent = `${result.citations?.length || 0} nguồn`;
    qs("#queryInput").value = "";
    autoGrowTextarea();
  } catch (error) {
    pending.querySelector(".message-body").textContent = error.message || "Hệ thống chưa sẵn sàng.";
    toast(error.message);
  } finally {
    qs("#sendBtn").disabled = false;
  }
}

function renderLoadingMessage() {
  return `
    <div class="loading-list">
      ${LOADING_STEPS.map((step) => `
        <div class="loading-step">
          <span class="loading-step-dot"></span>
          <span>${escapeHtml(step)}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function renderSources(citations) {
  const target = qs("#sourcesPanel");
  if (!citations.length) {
    target.innerHTML = `
      <div class="empty-state">
        Chưa có nguồn tham chiếu. Khi bạn đặt câu hỏi, tài liệu được dùng để trả lời sẽ hiển thị tại đây.
      </div>
    `;
    return;
  }
  target.innerHTML = citations
    .map(
      (citation, index) => `
        <article class="source-card">
          <div class="source-title">${index + 1}. ${escapeHtml(citation.title || citation.doc_id || "Nguồn")}</div>
          <div class="source-meta">
            ${escapeHtml(citation.display_code || citation.doc_id || "-")} | v${escapeHtml(citation.version || "-")}
            ${citation.display_code && citation.doc_id ? ` | ${escapeHtml(citation.doc_id)}` : ""}
          </div>
          <div class="source-excerpt">${escapeHtml(citation.excerpt || "Không có đoạn trích công khai.")}</div>
        </article>
      `,
    )
    .join("");
  wireSpotlight(".source-card");
}

function renderTrace(steps) {
  const target = qs("#tracePanel");
  const rows = Array.isArray(steps) ? steps : [];
  if (!rows.length) {
    target.innerHTML = `<div class="empty-state">Chưa có quá trình xử lý.</div>`;
    return;
  }
  target.innerHTML = rows
    .map(
      (step) => `
        <article class="trace-step">
          <span class="trace-dot ${escapeHtml(step.status || "")}"></span>
          <div class="trace-card">
            <div class="source-title">${escapeHtml(step.label || "Bước xử lý")}</div>
            ${step.detail ? `<div class="trace-meta">${escapeHtml(step.detail)}</div>` : ""}
          </div>
        </article>
      `,
    )
    .join("");
  wireSpotlight(".trace-card");
}

function switchDrawerTab(tabName) {
  document.querySelectorAll(".drawer-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });
  document.querySelectorAll(".drawer-panel").forEach((panel) => panel.classList.remove("active"));
  qs(`#${tabName}Panel`)?.classList.add("active");
}

function syncDrawer() {
  const drawer = qs("#sourceDrawer");
  qs(".user-shell").classList.toggle("drawer-hidden", state.drawerHidden);
  drawer.classList.toggle("hidden", state.drawerHidden);
}

function ensureDrawerVisible() {
  state.drawerHidden = false;
  syncDrawer();
}

function resetChat() {
  state.sessionId = createId("session");
  localStorage.setItem("kbUserChatSessionId", state.sessionId);
  state.templateId = null;
  state.templateLabel = null;
  state.lastResponse = null;
  qs("#queryInput").value = "";
  autoGrowTextarea();
  qs("#selectedTemplate").textContent = "Không dùng mẫu";
  document.querySelectorAll(".template-chip").forEach((item) => item.classList.remove("active"));
  qs("#messages").innerHTML = `
    <div id="welcomeState" class="welcome-state">
      <div class="welcome-hero">
        <div class="welcome-badge">Hệ thống RAG thông minh</div>
        <p class="welcome-eyebrow">Tôi có thể giúp gì cho bạn hôm nay?</p>
        <p class="welcome-sub">Tìm kiếm nhanh chóng, trích dẫn chính xác từ kho quy trình nội bộ của doanh nghiệp.</p>
      </div>
      <div id="welcomeCards" class="welcome-cards" aria-label="Gợi ý bắt đầu"></div>
    </div>
  `;
  renderWelcomeCards();
  qs("#drawerMeta").textContent = "Chưa có câu trả lời";
  renderSources([]);
  renderTrace([]);
  switchDrawerTab("sources");
  sendHeartbeat().catch(() => {});
}

async function sendHeartbeat() {
  const result = await api("/api/user/session/heartbeat", {
    method: "POST",
    body: JSON.stringify({
      session_id: state.sessionId,
      device_id: state.deviceId,
    }),
  });
  if (result.session_id && result.session_id !== state.sessionId) {
    state.sessionId = result.session_id;
    localStorage.setItem("kbUserChatSessionId", state.sessionId);
  }
  return result;
}

function startHeartbeat() {
  if (state.heartbeatTimer) {
    window.clearInterval(state.heartbeatTimer);
  }
  sendHeartbeat().catch(() => {});
  state.heartbeatTimer = window.setInterval(() => {
    sendHeartbeat().catch(() => {});
  }, 30000);
  window.addEventListener("beforeunload", () => {
    const payload = JSON.stringify({ session_id: state.sessionId, device_id: state.deviceId });
    navigator.sendBeacon?.("/api/user/session/heartbeat", new Blob([payload], { type: "application/json" }));
  });
}

async function init() {
  window.addEventListener("mousemove", (e) => {
    document.body.style.setProperty("--global-mouse-x", `${e.clientX}px`);
    document.body.style.setProperty("--global-mouse-y", `${e.clientY}px`);
  });

  qs("#chatForm").addEventListener("submit", submitChat);
  qs("#newChatBtn").addEventListener("click", resetChat);
  qs("#toggleDrawerBtn").addEventListener("click", () => {
    state.drawerHidden = !state.drawerHidden;
    syncDrawer();
  });
  qs("#closeDrawerBtn").addEventListener("click", () => {
    state.drawerHidden = true;
    syncDrawer();
  });
  document.querySelectorAll(".drawer-tab").forEach((button) => {
    button.addEventListener("click", () => switchDrawerTab(button.dataset.tab));
  });
  
  // Custom textarea resize and shortcuts
  const queryInput = qs("#queryInput");
  queryInput.addEventListener("input", autoGrowTextarea);
  queryInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      qs("#chatForm").requestSubmit();
    }
  });

  renderSources([]);
  renderTrace([]);
  try {
    state.bootstrap = await api("/api/user/bootstrap");
    renderBootstrap();
    startHeartbeat();
  } catch (error) {
    qs("#statusText").textContent = "Lỗi";
    qs("#railStatus").className = "rail-status bad";
    toast(error.message);
  }
  syncDrawer();
}

init();
