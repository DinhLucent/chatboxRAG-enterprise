const state = {
  bootstrap: null,
  templateId: null,
  templateLabel: null,
  sessionId: getOrCreateStoredId("kbUserChatSessionId", "session"),
  deviceId: getOrCreateStoredId("kbUserChatDeviceId", "device"),
  lastResponse: null,
  drawerHidden: isCompactLayout(),
  heartbeatTimer: null,
  loadingChartJS: null,
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
  
  const html = escapeHtml(text);
  const lines = html.split("\n");
  const result = [];
  let inUl = false;
  let inOl = false;
  let inCode = false;
  let codeLang = "";
  let codeLines = [];
  let inBlockquote = false;
  let currentCalloutType = "";
  
  for (let line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inBlockquote) {
        result.push(currentCalloutType ? "</div>" : "</blockquote>");
        inBlockquote = false;
        currentCalloutType = "";
      }
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

    // Handle blockquotes / callouts (escaped > is &gt;)
    if (trimmed.startsWith("&gt;")) {
      if (inUl) {
        result.push("</ul>");
        inUl = false;
      }
      if (inOl) {
        result.push("</ol>");
        inOl = false;
      }
      
      const quoteContent = line.substring(line.indexOf("&gt;") + 4).trim();
      
      if (!inBlockquote) {
        const calloutMatch = quoteContent.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]/i);
        if (calloutMatch) {
          currentCalloutType = calloutMatch[1].toUpperCase();
          const innerText = quoteContent.substring(calloutMatch[0].length).trim();
          result.push(`<div class="callout callout-${currentCalloutType.toLowerCase()}">`);
          result.push(getCalloutHeader(currentCalloutType));
          if (innerText) {
            result.push(`<p class="callout-body">${formatInlineMarkdown(innerText)}</p>`);
          }
        } else {
          currentCalloutType = "";
          result.push(`<blockquote>`);
          result.push(`<p>${formatInlineMarkdown(quoteContent)}</p>`);
        }
        inBlockquote = true;
      } else {
        if (currentCalloutType) {
          result.push(`<p class="callout-body">${formatInlineMarkdown(quoteContent)}</p>`);
        } else {
          result.push(`<p>${formatInlineMarkdown(quoteContent)}</p>`);
        }
      }
      continue;
    }

    // Close blockquote if we hit a non-blockquote line
    if (inBlockquote) {
      result.push(currentCalloutType ? "</div>" : "</blockquote>");
      inBlockquote = false;
      currentCalloutType = "";
    }
    
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
    
    if (inUl) {
      result.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      result.push("</ol>");
      inOl = false;
    }
    
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
  if (inBlockquote) {
    result.push(currentCalloutType ? "</div>" : "</blockquote>");
  }
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
  if (lang === "chart" || lang === "echarts") {
    const trimmed = code.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      return `<div class="chat-chart-container" data-chart-config="${escapeHtml(trimmed)}"></div>`;
    }
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

function getCalloutHeader(type) {
  const titles = {
    NOTE: "Ghi chú",
    TIP: "Mẹo / Gợi ý",
    IMPORTANT: "Quan trọng",
    WARNING: "Cảnh báo",
    CAUTION: "Lưu ý đặc biệt"
  };
  const title = titles[type] || type;
  
  let iconSvg = "";
  if (type === "NOTE") {
    iconSvg = `<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;
  } else if (type === "TIP") {
    iconSvg = `<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 22h4M12 2v2M4.22 4.22l1.42 1.42M18.36 4.22l-1.42 1.42M1 12h2M21 12h2M12 6a6 6 0 0 0-6 6c0 1.66.83 3.12 2.1 4H15.9a4 4 0 0 0 2.1-4c0-3.31-2.69-6-6-6z"/></svg>`;
  } else if (type === "IMPORTANT") {
    iconSvg = `<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
  } else if (type === "WARNING") {
    iconSvg = `<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
  } else if (type === "CAUTION") {
    iconSvg = `<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  }
  
  return `
    <div class="callout-title">
      ${iconSvg}
      <span>${title}</span>
    </div>
  `;
}

function loadChartJS() {
  if (window.Chart) {
    return Promise.resolve(window.Chart);
  }
  if (state.loadingChartJS) {
    return state.loadingChartJS;
  }
  state.loadingChartJS = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/chart.js";
    script.onload = () => {
      resolve(window.Chart);
    };
    script.onerror = (err) => {
      reject(err);
    };
    document.head.appendChild(script);
  });
  return state.loadingChartJS;
}

async function hydrateCharts(container = document) {
  const chartContainers = container.querySelectorAll(".chat-chart-container:not(.initialized)");
  if (!chartContainers.length) return;
  
  try {
    const Chart = await loadChartJS();
    chartContainers.forEach((el) => {
      el.classList.add("initialized");
      const configStr = el.getAttribute("data-chart-config");
      try {
        const config = JSON.parse(configStr);
        const canvas = document.createElement("canvas");
        el.appendChild(canvas);
        
        canvas.style.maxWidth = "100%";
        canvas.style.height = "250px";
        
        config.options = config.options || {};
        config.options.responsive = true;
        config.options.maintainAspectRatio = false;
        
        new Chart(canvas, config);
      } catch (err) {
        console.error("Failed to render chart:", err);
        el.innerHTML = `<p class="chart-error">Lỗi hiển thị biểu đồ: ${escapeHtml(err.message)}</p>`;
      }
    });
  } catch (err) {
    console.error("Failed to load Chart.js:", err);
  }
}

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

function autoGrowTextarea() {
  const textarea = qs("#queryInput");
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = textarea.scrollHeight + "px";
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = qs("#demoToken")?.value.trim();
  if (token) {
    headers["X-Demo-Token"] = token;
    localStorage.setItem("demoToken", token);
  }
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.error || payload?.message || response.statusText);
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
  qs("#assistantLine").textContent = "Trợ lý đang dùng: Tài liệu quy trình Phương Đông | Quy tắc: Trả lời có nguồn";
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
  container.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", () => {
      const messageBody = button.closest(".message")?.querySelector(".message-body");
      if (messageBody) {
        const textToCopy = messageBody.innerText.trim();
        navigator.clipboard.writeText(textToCopy)
          .then(() => toast("Đã sao chép vào bộ nhớ tạm"))
          .catch((err) => toast("Lỗi khi sao chép: " + err));
      }
    });
  });

  container.querySelectorAll(".feedback-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const logId = Number(button.closest(".message-actions")?.dataset.logId || 0);
      if (!logId) return;
      try {
        await api("/api/feedback", {
          method: "POST",
          body: JSON.stringify({
            query_log_id: logId,
            feedback: button.dataset.feedback,
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

  // Setup loading animation interval for active step representation
  let activeStepIdx = 0;
  const loadingInterval = setInterval(() => {
    if (!pending) return;
    const steps = pending.querySelectorAll(".loading-step");
    if (!steps.length) {
      clearInterval(loadingInterval);
      return;
    }
    steps.forEach((stepEl, idx) => {
      stepEl.classList.remove("active");
      if (idx < activeStepIdx) {
        stepEl.style.color = "var(--muted)";
        stepEl.style.opacity = "0.5";
        const dot = stepEl.querySelector(".loading-step-dot");
        if (dot) {
          dot.style.background = "var(--green)";
          dot.style.boxShadow = "none";
          dot.style.animation = "none";
        }
      } else if (idx === activeStepIdx) {
        stepEl.classList.add("active");
      }
    });
    activeStepIdx = (activeStepIdx + 1) % steps.length;
  }, 1200);

  try {
    const result = await api("/api/chat", {
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
    clearInterval(loadingInterval);
    state.lastResponse = result;
    if (result.session?.session_id || result.session_id) {
      state.sessionId = result.session?.session_id || result.session_id;
      localStorage.setItem("kbUserChatSessionId", state.sessionId);
    }
    pending.querySelector(".message-body").innerHTML = parseMarkdown(result.answer || NO_SOURCE_TEXT);
    pending.insertAdjacentHTML("beforeend", renderFeedbackActions(result.query_log_id || result.log_id));
    wireFeedback(pending);
    hydrateCharts(pending);
    renderSources(result.citations || []);
    renderTrace(result.trace_steps || result.trace?.steps || []);
    switchDrawerTab("sources");
    qs("#drawerMeta").textContent = `${result.citations?.length || 0} nguồn`;
    qs("#queryInput").value = "";
    autoGrowTextarea();
    checkHealth();
  } catch (error) {
    clearInterval(loadingInterval);
    pending.querySelector(".message-body").textContent = error.message || "Hệ thống chưa sẵn sàng.";
    toast(error.message);
  } finally {
    clearInterval(loadingInterval);
    qs("#sendBtn").disabled = false;
  }
}

function renderLoadingMessage() {
  return `
    <div class="loading-indicator-wrapper">
      <div class="modern-loading-spinner"></div>
      <div class="loading-title">OrientSOP đang suy nghĩ...</div>
    </div>
    <div class="loading-list">
      ${LOADING_STEPS.map((step, idx) => `
        <div class="loading-step${idx === 0 ? " active" : ""}">
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
            ${escapeHtml(citation.display_code || citation.doc_id || "-")} | ${escapeHtml(citation.display_version || `v${citation.version || "-"}`)}
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
  
  const panelId = tabName === "status" ? "statusPanel" : `${tabName}Panel`;
  qs(`#${panelId}`)?.classList.add("active");
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
        <div class="welcome-badge">Hệ thống RAG Quy trình Phương Đông</div>
        <p class="welcome-eyebrow">Tôi có thể giúp gì cho bạn hôm nay?</p>
        <p class="welcome-sub">Tìm kiếm nhanh chóng, trích dẫn chính xác từ kho tài liệu và quy trình hiệu lực của Phương Đông.</p>
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
  const token = qs("#demoToken")?.value.trim();
  if (!token) return;
  const result = await api("/api/heartbeat", {
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
    const headers = {};
    const token = qs("#demoToken")?.value.trim();
    if (token) {
      headers["X-Demo-Token"] = token;
    }
    navigator.sendBeacon?.("/api/heartbeat", new Blob([payload], { type: "application/json" }));
  });
}

async function checkHealth() {
  const statusCard = qs("#vercelStatusCard");
  const statusTitle = qs("#statusTitle");
  const statusDesc = qs("#statusDesc");
  const token = qs("#demoToken")?.value.trim();
  
  if (!token) {
    if (statusTitle) statusTitle.textContent = "Chưa kiểm tra";
    if (statusDesc) statusDesc.textContent = "Nhập mã demo để tải trạng thái hệ thống.";
    return;
  }

  if (statusTitle) statusTitle.textContent = "Đang kiểm tra...";
  if (statusDesc) statusDesc.textContent = "Đang kết nối hệ thống xử lý nội bộ...";

  try {
    const health = await api("/api/health");
    if (qs("#metricDocs")) qs("#metricDocs").textContent = health.active_documents ?? "-";
    if (qs("#metricConnection")) qs("#metricConnection").textContent = health.service_status?.state === "ok" ? "OK" : "Lỗi";
    if (qs("#metricLlm")) qs("#metricLlm").textContent = health.llm_configured ? "Sẵn sàng" : "Chưa cấu hình";
    if (qs("#metricLoop")) {
      qs("#metricLoop").textContent = health.latest_evaluation_pass
        ? `${health.passed_cases}/${health.total_cases} OK`
        : "Chưa pass";
    }

    if (statusCard) {
      statusCard.className = `vercel-status-card ${statusClass(health.service_status)}`;
    }
    if (statusTitle) statusTitle.textContent = health.service_status?.title || "Sẵn sàng";
    if (statusDesc) statusDesc.textContent = health.service_status?.message || "Hệ thống đang hoạt động bình thường.";

    applyStatus(health.service_status);
  } catch (error) {
    if (qs("#metricDocs")) qs("#metricDocs").textContent = "-";
    if (qs("#metricConnection")) qs("#metricConnection").textContent = "Mất kết nối";
    if (qs("#metricLlm")) qs("#metricLlm").textContent = "-";
    if (qs("#metricLoop")) qs("#metricLoop").textContent = "-";
    
    if (statusCard) statusCard.className = "vercel-status-card bad";
    if (statusTitle) statusTitle.textContent = "Mất kết nối";
    if (statusDesc) statusDesc.textContent = error.message || "Không thể kết nối máy chủ nội bộ.";
    
    applyStatus({ state: "offline", can_chat: false });
  }
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
  
  const queryInput = qs("#queryInput");
  queryInput.addEventListener("input", autoGrowTextarea);
  queryInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      qs("#chatForm").requestSubmit();
    }
  });

  qs("#demoToken").addEventListener("change", () => {
    const token = qs("#demoToken").value.trim();
    if (token) {
      localStorage.setItem("demoToken", token);
      checkHealth().then(() => {
        api("/api/bootstrap").then((bootstrap) => {
          state.bootstrap = bootstrap;
          renderBootstrap();
          startHeartbeat();
        }).catch((err) => {
          toast(err.message || "Không tải được dữ liệu khởi tạo.");
        });
      });
    }
  });

  const storedToken = localStorage.getItem("demoToken") || "";
  qs("#demoToken").value = storedToken;

  renderSources([]);
  renderTrace([]);
  
  try {
    state.bootstrap = await api("/api/bootstrap");
    renderBootstrap();
    startHeartbeat();
    checkHealth();
  } catch (error) {
    const isAuthError = error.message?.toLowerCase().includes("mã") ||
                        error.message?.toLowerCase().includes("token") ||
                        error.message?.toLowerCase().includes("access") ||
                        error.message?.toLowerCase().includes("unauthorized") ||
                        !storedToken;
    if (isAuthError) {
      qs("#statusText").textContent = "Nhập mã";
      qs("#railStatus").className = "rail-status bad";
      switchDrawerTab("status");
      ensureDrawerVisible();
      if (storedToken) {
        toast("Vui lòng kiểm tra lại mã truy cập demo.");
      }
    } else {
      qs("#statusText").textContent = "Chưa kết nối";
      qs("#railStatus").className = "rail-status bad";
      toast(error.message || "Không kết nối được máy chủ nội bộ.");
    }
  }
  syncDrawer();
}

init();
