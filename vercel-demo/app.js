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
  _cooldownInterval: null,
  _beforeUnloadBound: false,
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

// ---------------------------------------------------------------------------
// Markdown rendering moved to markdown.js (loaded before this file in
// index.html). escapeHtml, parseMarkdown, formatInlineMarkdown, renderCodeBlock,
// renderMermaidWorkflow and getCalloutHeader are globals from that classic
// script, so all call sites below remain unchanged.
// ---------------------------------------------------------------------------

function toast(message) {
  const target = qs("#toast");
  target.textContent = message;
  target.classList.add("show");
  window.setTimeout(() => target.classList.remove("show"), 2800);
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
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch (e) {
    payload = { message: text };
  }
  if (!response.ok) {
    const errorMsg = payload?.detail || payload?.error || payload?.message || response.statusText;
    const error = new Error(errorMsg);
    error.status = response.status;
    const retryAfter = response.headers.get("Retry-After");
    if (retryAfter) {
      error.retryAfter = parseInt(retryAfter, 10);
    } else {
      // Fallback: prefer "N giay" pattern over first number to avoid parsing wrong value
      const match = errorMsg.match(/(\d+)\s*gi[aâ]y/) || errorMsg.match(/\d+/);
      if (match) {
        error.retryAfter = parseInt(match[1] || match[0], 10);
      }
    }
    throw error;
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
  initMagneticHover();
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
  initMagneticHover();
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
  const welcomeState = qs("#welcomeState");
  if (welcomeState) {
    // Pin welcome state in place so it doesn't push the new message down
    const rect = welcomeState.getBoundingClientRect();
    welcomeState.style.position = "absolute";
    welcomeState.style.top = `${welcomeState.offsetTop}px`;
    welcomeState.style.left = `${welcomeState.offsetLeft}px`;
    welcomeState.style.width = `${rect.width}px`;
    welcomeState.style.margin = "0";
    welcomeState.style.pointerEvents = "none";

    // Fade out text elements and cards
    const heroText = welcomeState.querySelectorAll(".welcome-eyebrow, .welcome-sub, #welcomeCards");
    const avatar = welcomeState.querySelector(".welcome-avatar");

    anime({
      targets: heroText,
      opacity: 0,
      translateY: -20,
      duration: 350,
      easing: "easeInQuad",
    });

    // Animate avatar: scale down and translate to fly top-left
    anime({
      targets: avatar,
      scale: 0.36,
      translateY: -100,
      translateX: -120,
      opacity: 0,
      duration: 500,
      easing: "cubicBezier(0.16, 1, 0.3, 1)",
      complete: () => {
        welcomeState.remove();
      }
    });
  }
  const article = document.createElement("article");
  article.className = `message ${role}`;
  
  if (role === "assistant") {
    article.innerHTML = `
      <div class="message-wrapper">
        <div class="message-avatar-container">
          <svg class="bot-message-avatar" width="32" height="32" viewBox="0 0 88 88" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="botAvatarGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#fb7185"/>
                <stop offset="100%" stop-color="#e11d48"/>
              </linearGradient>
            </defs>
            <circle cx="44" cy="44" r="38" fill="url(#botAvatarGrad)"/>
            <rect x="32" y="33" width="24" height="20" rx="6" fill="#ffffff"/>
            <rect x="29" y="38" width="3" height="10" rx="1.5" fill="#ffffff"/>
            <rect x="56" y="38" width="3" height="10" rx="1.5" fill="#ffffff"/>
            <rect x="41" y="52" width="6" height="4" fill="#ffffff"/>
            <circle cx="39" cy="42" r="2" fill="#e11d48"/>
            <circle cx="49" cy="42" r="2" fill="#e11d48"/>
            <path d="M41 47.5C42 48.5 43 49 44 49C45 49 46 48.5 47 47.5" stroke="#e11d48" stroke-width="1.5" stroke-linecap="round"/>
            <rect x="43" y="26" width="2" height="7" fill="#ffffff"/>
            <circle cx="44" cy="25" r="2" fill="#ffffff"/>
          </svg>
        </div>
        <div class="message-content">
          <div class="message-body">${html}</div>
          ${actions}
        </div>
      </div>
    `;
  } else {
    article.innerHTML = `<div class="message-body">${html}</div>${actions}`;
  }
  
  target.appendChild(article);

  // Custom spring entrance animation using Anime.js
  anime.set(article, {
    opacity: 0,
    translateY: 20,
    scale: 0.96
  });
  anime({
    targets: article,
    opacity: [0, 1],
    translateY: [20, 0],
    scale: [0.96, 1],
    duration: 500,
    easing: "spring(1, 80, 15, 0)"
  });

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

  triggerComposerGlow(true);
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
  let elapsedMs = 0;
  let queueStateDetected = false;
  const loadingInterval = setInterval(() => {
    if (!pending) return;
    
    elapsedMs += 1200;
    if (elapsedMs >= 4800 && !queueStateDetected) {
      queueStateDetected = true;
      const titleEl = pending.querySelector(".loading-title");
      if (titleEl) {
        titleEl.innerHTML = `<span class="queue-hourglass">⏳</span> Hàng đợi bận. Bạn đang xếp hàng chờ xử lý...`;
      }
      pending.querySelector(".loading-indicator-wrapper")?.classList.add("queued-state");
    }

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
    localStorage.removeItem("kbUserChatDraft"); // Clear draft on success
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
    qs("#drawerMeta").textContent = `${result.citations?.length || 0} nguồn`;
    qs("#queryInput").value = "";
    autoGrowTextarea();
    checkHealth();
  } catch (error) {
    clearInterval(loadingInterval);
    const is429 = error.status === 429 || 
                  error.message?.includes("429") || 
                  error.message?.toLowerCase().includes("vui long cho") || 
                  error.message?.toLowerCase().includes("vui lòng chờ") ||
                  error.message?.toLowerCase().includes("dang duoc xu ly");
                  
    if (is429) {
      const waitSeconds = error.retryAfter || 15;
      
      // Save question as draft
      localStorage.setItem("kbUserChatDraft", query);
      
      // Disable composer inputs and add styling class
      const queryInput = qs("#queryInput");
      if (queryInput) {
        queryInput.disabled = true;
        queryInput.placeholder = "Hệ thống đang hạ nhiệt. Vui lòng chờ...";
      }
      qs(".composer-container")?.classList.add("cooldown-active");
      
      renderCooldownUI(pending, query, waitSeconds);
    } else {
      pending.querySelector(".message-body").textContent = error.message || "Hệ thống chưa sẵn sàng.";
    }
    toast(error.message);
  } finally {
    clearInterval(loadingInterval);
    qs("#sendBtn").disabled = false;
    triggerComposerGlow(false);
  }
}

function renderCooldownUI(pendingCard, query, seconds) {
  // Clear the active trace
  renderTrace([]);
  
  const messageBody = pendingCard.querySelector(".message-body");
  messageBody.classList.add("cooldown-container-wrapper");
  
  const strokeMax = 213.6; // 2 * PI * r (r=34)
  
  messageBody.innerHTML = `
    <div class="cooldown-card">
      <div class="cooldown-visual">
        <svg class="cooldown-ring" viewBox="0 0 80 80">
          <circle class="cooldown-ring-bg" cx="40" cy="40" r="34" />
          <circle class="cooldown-ring-progress" cx="40" cy="40" r="34" style="stroke-dashoffset: 0;" />
        </svg>
        <div class="cooldown-timer">${seconds}</div>
      </div>
      <div class="cooldown-content">
        <div class="cooldown-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          Hạ nhiệt hệ thống
        </div>
        <div class="cooldown-desc">Bạn đang gửi câu hỏi quá nhanh. Vui lòng chờ để hệ thống xử lý tuần tự.</div>
        <div class="cooldown-query-preview" title="${escapeHtml(query)}"><strong>Câu hỏi bị chặn:</strong> "${escapeHtml(query)}"</div>
      </div>
      <button class="cooldown-btn" type="button" disabled>
        <svg class="send-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; stroke: currentColor;">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
        <span>Gửi lại sau (${seconds}s)</span>
      </button>
    </div>
  `;

  let remaining = seconds;
  const progressCircle = messageBody.querySelector(".cooldown-ring-progress");
  const timerText = messageBody.querySelector(".cooldown-timer");
  const actionButton = messageBody.querySelector(".cooldown-btn");
  
  // Clear any previous cooldown interval to prevent leaks
  if (state._cooldownInterval) clearInterval(state._cooldownInterval);
  state._cooldownInterval = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(state._cooldownInterval);
      state._cooldownInterval = null;
      timerText.textContent = "✓";
      timerText.style.color = "var(--green)";
      progressCircle.style.stroke = "var(--green)";
      progressCircle.style.strokeDashoffset = 0;
      
      const titleEl = messageBody.querySelector(".cooldown-title");
      titleEl.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="animation: none;">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        Hệ thống đã sẵn sàng
      `;
      titleEl.style.color = "var(--green)";
      
      messageBody.querySelector(".cooldown-desc").textContent = "Thời gian chờ đã kết thúc. Bạn có thể gửi lại câu hỏi này ngay lập tức.";
      
      // Re-enable composer inputs
      const queryInput = qs("#queryInput");
      if (queryInput) {
        queryInput.disabled = false;
        queryInput.placeholder = "Nhập câu hỏi tại đây...";
      }
      qs(".composer-container")?.classList.remove("cooldown-active");
      
      actionButton.disabled = false;
      actionButton.classList.add("ready");
      actionButton.querySelector("span").textContent = "Gửi lại ngay";
      
      // Focus button for accessibility
      actionButton.focus();
      
      actionButton.onclick = () => {
        localStorage.removeItem("kbUserChatDraft"); // Clear draft on resubmit
        pendingCard.remove();
        qs("#queryInput").value = query;
        qs("#chatForm").requestSubmit();
      };
    } else {
      timerText.textContent = remaining;
      const percent = remaining / seconds;
      const offset = strokeMax * (1 - percent);
      progressCircle.style.strokeDashoffset = offset;
      actionButton.querySelector("span").textContent = `Gửi lại sau (${remaining}s)`;
    }
  }, 1000);
}

function renderLoadingMessage() {
  return `
    <div class="loading-indicator-wrapper">
      <div class="modern-loading-spinner"></div>
      <div class="loading-title">OrientSOP đang suy nghĩ<span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span></div>
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
          <div class="source-actions" style="display: flex; gap: 8px; margin-top: 12px;">
            <button class="source-open-btn" type="button" disabled style="margin-top: 0;">Tải PDF gốc</button>
            <button class="source-open-btn" type="button" disabled style="margin-top: 0; opacity: 0.5; cursor: not-allowed;" title="Tính năng xem trước (Preview) sẽ được cập nhật trong tương lai">Xem trước</button>
          </div>
        </article>
      `,
    )
    .join("");
  wireSpotlight(".source-card");
}

function getStepIcon(stepId, status) {
  const cleanId = String(stepId || "").toLowerCase();
  if (cleanId.includes("scope")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg shield"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;
  }
  if (cleanId.includes("context")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg context"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
  }
  if (cleanId.includes("analyze") || cleanId.includes("analysis")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg brain"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-3.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2zM14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-3.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2z"/></svg>`;
  }
  if (cleanId.includes("plan_retrieval") || cleanId.includes("retrieval_plan")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg compass"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>`;
  }
  if (cleanId.includes("retrieve") || cleanId.includes("search")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg database"><path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>`;
  }
  if (cleanId.includes("evidence")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg evidence"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`;
  }
  if (cleanId.includes("format")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg format"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>`;
  }
  if (cleanId.includes("draft")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg draft"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`;
  }
  if (cleanId.includes("verify") || cleanId.includes("verification") || cleanId.includes("repair")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg verify"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 11 11 13 15 9"/></svg>`;
  }
  if (cleanId.includes("critic")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg critic"><line x1="12" y1="2" x2="12" y2="22"/><line x1="5" y1="7" x2="19" y2="7"/><path d="M19 7l-3 6H20l-3-6M5 7L2 13H6L3 13"/></svg>`;
  }
  if (cleanId.includes("final")) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg final"><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>`;
  }

  const isDone = status === 'done';
  const isWarning = status === 'warning';
  const isEmpty = status === 'empty';
  
  if (isDone) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" class="trace-svg done"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
  }
  if (isWarning) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" class="trace-svg warning"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
  }
  if (isEmpty) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" class="trace-svg empty"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`;
  }

  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="trace-svg"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`;
}

function getStepDuration(step) {
  state.traceTimes = state.traceTimes || {};
  const key = step.id || step.label;
  const now = Date.now();
  if (step.status === 'running') {
    if (!state.traceTimes[key]) {
      state.traceTimes[key] = { start: now };
    }
    return 'đang chạy...';
  }
  if (step.status === 'done' || step.status === 'warning' || step.status === 'empty') {
    if (state.traceTimes[key]) {
      if (!state.traceTimes[key].end) {
        state.traceTimes[key].end = now;
        state.traceTimes[key].duration = ((state.traceTimes[key].end - state.traceTimes[key].start) / 1000).toFixed(1) + 's';
      }
      return state.traceTimes[key].duration;
    }
    return '';
  }
  return '';
}

function renderTrace(steps) {
  const target = qs("#tracePanel");
  const rows = Array.isArray(steps) ? steps : [];
  if (!rows.length) {
    target.innerHTML = `<div class="empty-state">Chưa có quá trình xử lý.</div>`;
    return;
  }
  
  const stepHtmls = rows.map((step) => {
    const duration = getStepDuration(step);
    // Vercel demo steps can also show detail or some simple content
    const detailHtml = step.detail ? `<div class="trace-meta">${escapeHtml(step.detail)}</div>` : "";
    
    return `
      <article class="trace-step">
        <div class="trace-icon-wrapper ${escapeHtml(step.status || "")}">
          ${getStepIcon(step.id || step.label, step.status)}
        </div>
        <div class="trace-card ${escapeHtml(step.status || "")}" data-step-id="${escapeHtml(step.id || step.label)}">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
            <div class="source-title">${escapeHtml(step.label || "Bước xử lý")}</div>
            ${duration ? `<span class="trace-duration" style="font-size: 11px; color: var(--muted); font-weight: 600;">${duration}</span>` : ""}
          </div>
          ${detailHtml}
        </div>
      </article>
    `;
  }).join("");

  target.innerHTML = `
    <div class="trace-timeline-container">
      <div class="trace-timeline-connector"></div>
      ${stepHtmls}
    </div>
  `;

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
  qs("#toggleDrawerBtn")?.classList.toggle("active", !state.drawerHidden);
}

function ensureDrawerVisible() {
  state.drawerHidden = false;
  syncDrawer();
}

function resetChat() {
  // Clear any running cooldown interval to prevent timer leak
  if (state._cooldownInterval) {
    clearInterval(state._cooldownInterval);
    state._cooldownInterval = null;
  }
  // Restore composer state in case cooldown was active
  qs(".composer-container")?.classList.remove("cooldown-active");
  const qi = qs("#queryInput");
  if (qi) {
    qi.disabled = false;
    qi.placeholder = "Nhập câu hỏi tại đây...";
  }
  localStorage.removeItem("kbUserChatDraft");

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
        <div class="welcome-avatar" aria-hidden="true">
          <div class="welcome-avatar-inner">
            <svg width="88" height="88" viewBox="0 0 88 88" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <radialGradient id="avatarGlow" cx="50%" cy="50%" r="50%" fx="50%" fy="50%">
                  <stop offset="0%" stop-color="#e11d48" stop-opacity="0.3"/>
                  <stop offset="100%" stop-color="#e11d48" stop-opacity="0"/>
                </radialGradient>
                <linearGradient id="avatarGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#fb7185"/>
                  <stop offset="100%" stop-color="#e11d48"/>
                </linearGradient>
              </defs>
              <circle class="avatar-glow-circle" cx="44" cy="44" r="40" fill="url(#avatarGlow)"/>
              <circle class="avatar-dash-ring" cx="44" cy="44" r="34" fill="#ffffff" stroke="url(#avatarGradient)" stroke-width="1.5" stroke-dasharray="4 3"/>
              <circle cx="44" cy="44" r="28" fill="url(#avatarGradient)" filter="drop-shadow(0 4px 12px rgba(225, 29, 72, 0.25))"/>
              <rect x="32" y="33" width="24" height="20" rx="6" fill="#ffffff"/>
              <rect x="29" y="38" width="3" height="10" rx="1.5" fill="#ffffff"/>
              <rect x="56" y="38" width="3" height="10" rx="1.5" fill="#ffffff"/>
              <rect x="41" y="52" width="6" height="4" fill="#ffffff"/>
              <circle class="avatar-eye avatar-eye-left" cx="39" cy="42" r="2" fill="#e11d48"/>
              <circle class="avatar-eye avatar-eye-right" cx="49" cy="42" r="2" fill="#e11d48"/>
              <path class="avatar-mouth" d="M41 47.5C42 48.5 43 49 44 49C45 49 46 48.5 47 47.5" stroke="#e11d48" stroke-width="1.5" stroke-linecap="round"/>
              <g class="avatar-antenna">
                <rect x="43" y="26" width="2" height="7" fill="#ffffff"/>
                <circle cx="44" cy="25" r="2" fill="#ffffff"/>
              </g>
            </svg>
          </div>
        </div>
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
  if (!state._beforeUnloadBound) {
    state._beforeUnloadBound = true;
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

/* ==========================================================================
   UI Animations & Design Spells (Anime.js / Custom Easing)
   ========================================================================== */

function runEntranceAnimations() {
  const loader = qs("#pageLoader");
  if (!loader) return;

  // Pre-hide elements to prevent layout flash when the page loader fades out
  anime.set(".rail, .chat-header, .welcome-hero, .welcome-cards, .composer", {
    opacity: 0,
    translateY: 20
  });
  anime.set(".welcome-card", {
    opacity: 0,
    scale: 0.95,
    translateY: 15
  });

  const tl = anime.timeline({
    easing: "easeInOutQuad",
  });

  tl.add({
    targets: "#pageLoader .loader-bar",
    left: ["-100%", "0%"],
    duration: 800,
  }).add({
    targets: "#pageLoader",
    opacity: 0,
    duration: 400,
    complete: () => {
      loader.classList.add("is-hidden");
      runAppEntranceReveal();
    }
  });
}

function runAppEntranceReveal() {
  anime.set(".rail, .chat-header, .welcome-hero, .welcome-cards, .composer", {
    opacity: 0,
    translateY: 20
  });

  anime({
    targets: ".rail, .chat-header, .welcome-hero, .welcome-cards, .composer",
    opacity: [0, 1],
    translateY: [20, 0],
    delay: anime.stagger(80),
    duration: 800,
    easing: "cubicBezier(0.16, 1, 0.3, 1)",
    complete: () => {
      initMagneticHover();
    }
  });

  anime.set(".welcome-card", {
    opacity: 0,
    scale: 0.95,
    translateY: 15
  });

  anime({
    targets: ".welcome-card",
    opacity: [0, 1],
    scale: [0.95, 1],
    translateY: [15, 0],
    delay: anime.stagger(60, { start: 300 }),
    duration: 600,
    easing: "spring(1, 80, 12, 0)"
  });
}

function initMagneticHover() {
  const magneticElements = document.querySelectorAll(".welcome-card, .welcome-avatar-inner, .template-chip");
  
  magneticElements.forEach((el) => {
    if (el.dataset.magneticBound) return;
    el.dataset.magneticBound = "true";

    el.addEventListener("mousemove", (e) => {
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      
      anime({
        targets: el,
        translateX: x * 0.22,
        translateY: y * 0.22,
        duration: 100,
        easing: "easeOutQuad"
      });
    });
    
    el.addEventListener("mouseleave", () => {
      anime({
        targets: el,
        translateX: 0,
        translateY: 0,
        duration: 600,
        easing: "spring(1, 75, 12, 0)"
      });
    });
  });
}

let composerGlowAnimation = null;

function triggerComposerGlow(active) {
  const composer = qs(".composer");
  if (!composer) return;
  
  if (active) {
    composer.classList.add("is-loading");
    if (!composerGlowAnimation) {
      composerGlowAnimation = anime({
        targets: ".composer-border-rect",
        strokeDashoffset: [0, -400],
        duration: 3000,
        loop: true,
        easing: "linear"
      });
    } else {
      composerGlowAnimation.play();
    }
  } else {
    composer.classList.remove("is-loading");
    if (composerGlowAnimation) {
      composerGlowAnimation.pause();
    }
  }
}

async function init() {
  // Throttle mousemove with requestAnimationFrame to avoid excessive CPU usage
  let _rafPending = false;
  window.addEventListener("mousemove", (e) => {
    if (_rafPending) return;
    _rafPending = true;
    requestAnimationFrame(() => {
      document.body.style.setProperty("--global-mouse-x", `${e.clientX}px`);
      document.body.style.setProperty("--global-mouse-y", `${e.clientY}px`);
      _rafPending = false;
    });
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
  
  // Draft recovery check on load
  const savedDraft = localStorage.getItem("kbUserChatDraft");
  if (savedDraft) {
    const queryInput = qs("#queryInput");
    if (queryInput) {
      queryInput.value = savedDraft;
      autoGrowTextarea();
      queryInput.focus();
      toast("Đã khôi phục câu hỏi nháp chưa gửi.");
    }
  }
  runEntranceAnimations();
}

init();
