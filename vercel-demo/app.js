const demoTokenInput = document.querySelector("#demoToken");
const questionInput = document.querySelector("#question");
const useLlmInput = document.querySelector("#useLlm");
const askBtn = document.querySelector("#askBtn");
const healthBtn = document.querySelector("#healthBtn");
const answerBox = document.querySelector("#answerBox");
const statusCard = document.querySelector("#statusCard");
const statusTitle = document.querySelector("#statusTitle");
const statusText = document.querySelector("#statusText");
const metrics = document.querySelector("#metrics");
const feedbackBox = document.querySelector("#feedbackBox");

let currentLogId = null;
let currentServiceStatus = null;

demoTokenInput.value = localStorage.getItem("demoToken") || "";

function tokenHeaders() {
  const token = demoTokenInput.value.trim();
  if (token) {
    localStorage.setItem("demoToken", token);
  }
  return token ? { "X-Demo-Token": token } : {};
}

function statusClass(state) {
  if (state === "ok") return "ok";
  if (["maintenance", "incident", "offline", "unavailable"].includes(state)) return "bad";
  if (["degraded", "limited", "not_ready", "unknown"].includes(state)) return "warn";
  return "";
}

function setStatus(type, title, text) {
  statusCard.className = `status ${type || ""}`.trim();
  statusTitle.textContent = title;
  statusText.textContent = text;
}

function setServiceStatus(serviceStatus) {
  currentServiceStatus = serviceStatus;
  setStatus(
    statusClass(serviceStatus?.state),
    serviceStatus?.title || "Chua xac dinh trang thai",
    serviceStatus?.message || "Chua nhan duoc trang thai he thong.",
  );
  askBtn.disabled = serviceStatus?.can_chat === false;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...tokenHeaders(),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload.message || payload.detail || payload.error || `HTTP ${response.status}`;
    const error = new Error(message);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function renderSources(citations) {
  if (!citations || citations.length === 0) {
    return "";
  }
  const items = citations
    .map((source) => {
      const title = source.title || source.doc_id || "Tai lieu";
      const version = source.version ? `v${source.version}` : "";
      const category = source.category || "";
      return `
        <div class="source">
          <strong>${escapeHtml(title)} ${escapeHtml(version)}</strong>
          <span>${escapeHtml(source.doc_id || "")} ${category ? "- " + escapeHtml(category) : ""}</span>
        </div>
      `;
    })
    .join("");
  return `<div class="source-list">${items}</div>`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMetrics(health) {
  const aiLabel = health.llm_configured ? "AI san sang" : "Tra cuu co ban";
  const evalLabel = health.latest_evaluation_pass
    ? `${health.passed_cases || "-"} / ${health.total_cases || "-"} pass`
    : "Chua pass";
  metrics.innerHTML = `
    <div><strong>${escapeHtml(health.active_documents ?? "-")}</strong><span>Tai lieu active</span></div>
    <div><strong>${escapeHtml(health.open_incidents ?? 0)}</strong><span>Su co dang mo</span></div>
    <div><strong>${escapeHtml(aiLabel)}</strong><span>Trang thai AI</span></div>
    <div><strong>${escapeHtml(evalLabel)}</strong><span>Loop-check</span></div>
  `;
}

function renderUnavailable(serviceStatus, message) {
  const title = serviceStatus?.title || "He thong tam thoi khong san sang";
  const text = serviceStatus?.message || message || "Vui long thu lai sau hoac bao ky thuat.";
  answerBox.innerHTML = `
    <div class="notice">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(text)}</span>
    </div>
  `;
  setServiceStatus({
    state: serviceStatus?.state || "unavailable",
    can_chat: false,
    title,
    message: text,
  });
}

async function checkHealth() {
  healthBtn.disabled = true;
  setStatus("", "Dang kiem tra", "Dang ket noi he thong xu ly noi bo...");
  try {
    const health = await api("/api/health");
    renderMetrics(health);
    setServiceStatus(health.service_status);
  } catch (error) {
    metrics.innerHTML = `
      <div><strong>-</strong><span>Tai lieu active</span></div>
      <div><strong>Mat ket noi</strong><span>May xu ly noi bo</span></div>
    `;
    renderUnavailable(error.payload?.service_status, error.message);
  } finally {
    healthBtn.disabled = false;
  }
}

async function askQuestion() {
  const query = questionInput.value.trim();
  if (!query) {
    questionInput.focus();
    return;
  }
  if (currentServiceStatus?.can_chat === false) {
    renderUnavailable(currentServiceStatus);
    return;
  }
  askBtn.disabled = true;
  feedbackBox.hidden = true;
  currentLogId = null;
  answerBox.innerHTML = `<span class="muted">Dang tra cuu tai lieu va tao cau tra loi...</span>`;
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        query,
        use_llm: useLlmInput.checked,
      }),
    });
    currentLogId = result.query_log_id;
    answerBox.innerHTML = `
      <div>${escapeHtml(result.answer || "Khong co cau tra loi.")}</div>
      ${renderSources(result.citations)}
    `;
    feedbackBox.hidden = !currentLogId;
    setStatus("ok", "Da tra loi", `Thoi gian xu ly: ${result.latency_ms ?? "-"} ms`);
  } catch (error) {
    renderUnavailable(error.payload?.service_status, error.message);
  } finally {
    if (currentServiceStatus?.can_chat !== false) {
      askBtn.disabled = false;
    }
  }
}

async function sendFeedback(feedback) {
  if (!currentLogId) {
    return;
  }
  try {
    await api("/api/feedback", {
      method: "POST",
      body: JSON.stringify({
        query_log_id: currentLogId,
        feedback,
      }),
    });
    setStatus("ok", "Da ghi nhan phan hoi", "Phan hoi se duoc dung de cai thien kho tri thuc.");
  } catch (error) {
    setStatus("bad", "Khong ghi duoc phan hoi", error.message);
  }
}

askBtn.addEventListener("click", askQuestion);
healthBtn.addEventListener("click", checkHealth);
feedbackBox.addEventListener("click", (event) => {
  const feedback = event.target?.dataset?.feedback;
  if (feedback) {
    sendFeedback(feedback);
  }
});
questionInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    askQuestion();
  }
});

if (demoTokenInput.value) {
  checkHealth();
}
