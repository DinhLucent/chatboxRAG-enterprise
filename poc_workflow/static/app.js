const state = {
  health: null,
  llmStatus: null,
  manifest: [],
  uploadQueue: { items: [], summary: {} },
  gaps: [],
  queries: [],
  runs: [],
  incidents: [],
  diagnostics: null,
  llmPresets: [],
  llmConfig: null,
  llmDraft: null,
  llmTestStatus: null,
  lastQueryLogId: null,
  generatedPrompt: null,
  adminUnlocked: false,
  authStatus: { required: true, configured: false },
  selectedReviewRecord: null,
  selectedDocumentRecord: null,
  selectedDocumentDetail: null,
  selectedReviewDetail: null,
};

const ADMIN_VIEWS = new Set(["upload", "review", "operations"]);

class AuthRequiredError extends Error {
  constructor(message) {
    super(message);
    this.authRequired = true;
  }
}

const api = async (path, options = {}) => {
  const token = localStorage.getItem("kbOperatorToken") || "";
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) {
    headers["X-KB-Token"] = token;
  }
  const response = await fetch(path, {
    headers,
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (response.status === 401) {
    showAuthPanel(data?.detail || "Cần token điều phối.");
    throw new AuthRequiredError("Cần token điều phối.");
  }
  if (!response.ok) {
    throw new Error(data?.detail || data?.error || response.statusText);
  }
  hideAuthPanel();
  return data;
};

const qs = (selector) => document.querySelector(selector);

function isAdminUnlocked() {
  return !state.authStatus?.required || Boolean(localStorage.getItem("kbOperatorToken"));
}

function syncAdminAccess() {
  state.adminUnlocked = isAdminUnlocked();
  document.body.classList.toggle("admin-unlocked", state.adminUnlocked);
  const button = qs("#operatorAccessBtn");
  if (button) {
    button.textContent = state.authStatus?.required && state.adminUnlocked ? "Khóa điều phối" : "Điều phối";
  }
  const activeAdminView = document.querySelector(".view.active.admin-only");
  if (!state.adminUnlocked && activeAdminView) {
    switchView("chat");
  }
}

function toast(message) {
  const el = qs("#toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3200);
}

function showAuthPanel(message) {
  const panel = qs("#authPanel");
  if (!panel) return;
  panel.hidden = false;
  qs("#authMessage").textContent = message || "Nhập token điều phối.";
  qs("#operatorTokenInput").value = localStorage.getItem("kbOperatorToken") || "";
  window.setTimeout(() => qs("#operatorTokenInput")?.focus(), 0);
}

function hideAuthPanel() {
  const panel = qs("#authPanel");
  if (panel) {
    panel.hidden = true;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function refreshAll() {
  const [authStatus, health, manifest, uploadQueue, gaps, queries, runs, incidents, diagnostics, llmPresets, llmConfig] = await Promise.all([
    api("/api/auth-status"),
    api("/api/health"),
    api("/api/manifest"),
    api("/api/upload-queue"),
    api("/api/gaps"),
    api("/api/queries"),
    api("/api/ingestion-runs"),
    api("/api/incidents?limit=25"),
    api("/api/diagnostics?include_logs=false"),
    api("/api/llm/presets"),
    api("/api/llm/config"),
  ]);
  Object.assign(state, { authStatus, health, manifest, uploadQueue, gaps, queries, runs, incidents, diagnostics, llmPresets, llmConfig });
  syncAdminAccess();
  if (!state.llmDraft) {
    state.llmDraft = llmConfigToDraft(llmConfig, llmPresets);
  }
  if (
    !state.llmStatus ||
    state.llmStatus.base_url !== health.llm?.base_url ||
    state.llmStatus.model !== health.llm?.model
  ) {
    state.llmStatus = health.llm;
  }
  renderMetrics();
  renderServiceBanner();
  renderProviderOptions();
  renderInbox();
  renderManifest();
  renderPending();
  renderQuality();
  renderOperations();
}

function serviceClass(state) {
  if (state === "ok") return "ok";
  if (["maintenance", "incident", "offline", "unavailable"].includes(state)) return "bad";
  if (["degraded", "limited", "not_ready", "unknown"].includes(state)) return "warn";
  return "warn";
}

function serviceText(value) {
  const text = String(value || "");
  const known = {
    "Dang dung che do tra cuu co ban": "Đang dùng chế độ tra cứu cơ bản",
    "AI dien giai chua cau hinh, he thong van tra loi dua tren tai lieu nguon.":
      "AI diễn giải chưa cấu hình, hệ thống vẫn trả lời dựa trên tài liệu nguồn.",
    "He thong dang bao tri": "Hệ thống đang bảo trì",
    "He thong dang duoc bao tri. Vui long quay lai sau.": "Hệ thống đang được bảo trì. Vui lòng quay lại sau.",
    "He thong dang gap su co": "Hệ thống đang gặp sự cố",
    "Doi ky thuat da ghi nhan su co va dang xu ly. Vui long thu lai sau.":
      "Đội kỹ thuật đã ghi nhận sự cố và đang xử lý. Vui lòng thử lại sau.",
    "Chua co tai lieu san sang": "Chưa có tài liệu sẵn sàng",
    "Chua co tai lieu active da duyet de chatbot tra loi.": "Chưa có tài liệu hiệu lực đã duyệt để chatbot trả lời.",
    "He thong dang hoat dong han che": "Hệ thống đang hoạt động hạn chế",
    "Mot so canh bao dang duoc theo doi. Ban van co the dat cau hoi.":
      "Một số cảnh báo đang được theo dõi. Bạn vẫn có thể đặt câu hỏi.",
    "He thong san sang": "Hệ thống sẵn sàng",
    "Chatbot dang ket noi voi kho tai lieu noi bo.": "Chatbot đang kết nối với kho tài liệu nội bộ.",
    "Chat service unavailable": "Dịch vụ trò chuyện chưa sẵn sàng",
    "RAGFlow env is not configured": "Chưa cấu hình RAGFlow",
  };
  return known[text] || text;
}

function renderServiceBanner(status = state.health?.service_status) {
  const target = qs("#serviceBanner");
  if (!target) return;
  const current = status || {
    state: "unknown",
    title: "Chưa rõ trạng thái hệ thống",
    message: "Chưa xác minh được trạng thái backend.",
    can_chat: false,
  };
  target.className = `service-banner ${serviceClass(current.state)}`;
  target.innerHTML = `
    <strong>${escapeHtml(serviceText(current.title))}</strong>
      <span>${escapeHtml(serviceText(current.message))}</span>
  `;
}

function renderInbox() {
  renderUploadWorkflow();
}

function renderUploadWorkflow() {
  const cardsTarget = qs("#uploadStatusCards");
  const rowsTarget = qs("#uploadQueueRows");
  if (!cardsTarget || !rowsTarget) return;

  const summary = state.uploadQueue?.summary || {};
  const statusOrder = ["queue", "processing", "done", "ocr_required", "failed"];
  cardsTarget.innerHTML = statusOrder
    .map((status) => `
      <div class="status-card ${escapeHtml(status)}">
        <div class="metric-label">${escapeHtml(statusLabel(status))}</div>
        <div class="metric-value">${escapeHtml(summary[status] ?? 0)}</div>
      </div>
    `)
    .join("");

  const items = state.uploadQueue?.items || [];
  rowsTarget.innerHTML = items.length
    ? items.map(renderQueueRow).join("")
    : `
      <tr>
        <td colspan="8" class="empty table-empty">Chưa có file trong hàng chờ. Hãy nạp tài liệu hoặc quét thư mục nguồn.</td>
      </tr>
    `;

  document.querySelectorAll(".queue-row-action").forEach((button) => {
    button.addEventListener("click", async () => {
      const item = findQueueItem(button.dataset.path, button.dataset.source);
      if (!item) return;
      if (button.dataset.action === "generate") {
        await generateAgentPrompt([item.relative_path]);
      } else if (button.dataset.action === "copy") {
        await copyPrompt(item.prompt || qs("#agentPromptBox").value);
      } else if (button.dataset.action === "done") {
        await updateUploadStatus([item.relative_path], "done");
      }
    });
  });

  const selectAll = qs("#selectAllQueue");
  if (selectAll) {
    selectAll.checked = false;
  }
}

function renderQueueRow(item) {
  const selectable = ["queue", "processing"].includes(item.status);
  const trace = item.prompt_id
    ? `<br>Prompt: ${escapeHtml(item.prompt_id)}${item.prompt_version ? ` | ${escapeHtml(item.prompt_version)}` : ""}`
    : "";
  return `
    <tr>
      <td>
        <input
          class="queue-select"
          type="checkbox"
          data-path="${escapeHtml(item.relative_path)}"
          ${selectable ? "" : "disabled"}
          aria-label="Chọn ${escapeHtml(item.file_name)}"
        />
      </td>
      <td>
        <div class="item-title">${escapeHtml(item.file_name)}</div>
        <div class="item-meta">${escapeHtml(item.relative_path)}${item.doc_id ? `<br>${escapeHtml(item.doc_id)} ${escapeHtml(item.title || "")}` : ""}${trace}</div>
      </td>
      <td>${escapeHtml(typeLabel(item.suggested_type))}</td>
      <td>${statusPill(item.status)}</td>
      <td>${renderProcessingStage(item)}</td>
      <td>${escapeHtml(item.version || "-")}</td>
      <td>${escapeHtml(formatDateTime(item.updated_at))}</td>
      <td>${renderQueueAction(item)}</td>
    </tr>
  `;
}

function renderProcessingStage(item) {
  const step = item.processing_step || defaultStepForStatus(item.status);
  const label = item.processing_step_label || processingStepLabel(step);
  const detail = item.processing_detail ? `<div class="item-meta">${escapeHtml(item.processing_detail)}</div>` : "";
  const qa = item.qa_status
    ? `<div class="item-meta">QA: ${escapeHtml(item.qa_status)}${
        item.qa_issues?.length ? ` | ${escapeHtml(item.qa_issues.join(", "))}` : ""
      }</div>`
    : "";
  return `<div class="stage-cell"><span class="status stage-${escapeHtml(step)}">${escapeHtml(label)}</span>${detail}${qa}</div>`;
}

function renderQueueAction(item) {
  if (item.status === "queue") {
    return `<button class="button secondary compact queue-row-action" data-source="${escapeHtml(item.source)}" data-path="${escapeHtml(item.relative_path)}" data-action="generate" type="button">Tạo prompt</button>`;
  }
  if (item.status === "processing") {
    return `<span class="item-meta">Đang xử lý</span>`;
  }
  if (item.prompt) {
    return `<button class="button secondary compact queue-row-action" data-source="${escapeHtml(item.source)}" data-path="${escapeHtml(item.relative_path)}" data-action="copy" type="button">Sao chép prompt</button>`;
  }
  if (["failed", "ocr_required"].includes(item.status)) {
    return `<span class="item-meta">${escapeHtml(item.error || "Xem lỗi")}</span>`;
  }
  return `<span class="item-meta">-</span>`;
}

function findQueueItem(relativePath, source) {
  return (state.uploadQueue?.items || []).find(
    (item) => item.relative_path === relativePath && (!source || item.source === source),
  );
}

function renderWorkflowItem(item) {
  return `
    <div class="item">
      <div class="item-title">${statusPill(item.status)} ${escapeHtml(item.title)}</div>
      <div class="item-meta">${escapeHtml(item.detail)}</div>
    </div>
  `;
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function statusLabel(status) {
  const labels = {
    queue: "Hàng chờ",
    processing: "Đang xử lý",
    done: "Hoàn tất",
    ocr_required: "Cần OCR",
    failed: "Lỗi",
    active: "Hiệu lực",
    pending_review: "Chờ duyệt",
    failed_review: "Duyệt lỗi",
    retired: "Ngưng dùng",
    open: "Đang mở",
    resolved: "Đã xử lý",
    warning: "Cảnh báo",
    error: "Lỗi",
    critical: "Nghiêm trọng",
    pass: "Đạt",
    fail: "Lỗi",
  };
  return labels[status] || status;
}

function defaultStepForStatus(status) {
  const defaults = {
    queue: "waiting",
    processing: "prepare",
    done: "done",
    ocr_required: "ocr_required",
    failed: "failed",
  };
  return defaults[status] || "waiting";
}

function processingStepLabel(step) {
  const labels = {
    waiting: "Đợi xử lý",
    prepare: "Chuẩn bị",
    check_service: "Kiểm tra dịch vụ",
    submit: "Gửi xử lý",
    queue: "Vào hàng chờ",
    parse: "Phân tích",
    download: "Tải kết quả",
    build_outputs: "Dựng đầu ra",
    qa: "Kiểm tra QA",
    done: "Hoàn tất",
    ocr_required: "Cần OCR",
    failed: "Lỗi",
  };
  return labels[step] || step;
}

function typeLabel(type) {
  const labels = {
    procedure: "Quy trình",
    vendor_document: "Tài liệu hãng",
    form_checklist: "Biểu mẫu / checklist",
    faq_troubleshooting: "FAQ / xử lý lỗi",
    unknown: "Chưa rõ",
  };
  return labels[type] || type || "Chưa rõ";
}

function providerLabel(provider) {
  const labels = {
    auto: "Tự động",
    ragflow: "Chỉ RAGFlow",
    local: "Dự phòng cục bộ",
  };
  return labels[provider] || provider || "-";
}

function llmConfigToDraft(config = {}, presets = []) {
  const provider = config?.provider || presets[0]?.id || "ollama";
  const preset = presets.find((item) => item.id === provider) || presets.find((item) => item.id === "ollama") || {};
  return {
    provider,
    base_url: config?.runtime_profile?.base_url || config?.base_url || preset.base_url || "",
    model: config?.runtime_profile?.model || config?.model || preset.model_hint || "",
    api_key: "",
    timeout_seconds: config?.runtime_profile?.timeout_seconds || 8,
  };
}

function selectedLlmPreset() {
  return state.llmPresets.find((item) => item.id === state.llmDraft?.provider) || state.llmPresets[0] || {};
}

function collectLlmDraftFromForm() {
  const current = state.llmDraft || {};
  return {
    provider: current.provider || "ollama",
    base_url: qs("#llmBaseUrlInput")?.value.trim() || "",
    model: qs("#llmModelInput")?.value.trim() || "",
    api_key: qs("#llmApiKeyInput")?.value.trim() || "",
    timeout_seconds: Number(qs("#llmTimeoutInput")?.value || current.timeout_seconds || 8),
  };
}

function applyLlmPreset(provider) {
  const preset = state.llmPresets.find((item) => item.id === provider);
  if (!preset) return;
  state.llmDraft = {
    provider,
    base_url: preset.base_url || "",
    model: preset.model_hint || "",
    api_key: "",
    timeout_seconds: state.llmDraft?.timeout_seconds || 8,
  };
  state.llmTestStatus = null;
  renderLlmConfigPanel();
}

function renderProviderOptions() {
  const select = qs("#providerSelect");
  if (!select) return;
  const allowed = state.health?.providers?.allowed || ["auto", "ragflow", "local"];
  const current = allowed.includes(select.value) ? select.value : allowed[0] || "auto";
  select.innerHTML = allowed
    .map((provider) => `<option value="${escapeHtml(provider)}">${escapeHtml(providerLabel(provider))}</option>`)
    .join("");
  select.value = current;
}

function renderMetrics() {
  const target = qs("#metrics");
  if (!target) return;
  const health = state.health || {};
  const metrics = [
    ["Tổng hồ sơ", health.manifest?.records ?? 0],
    ["Hiệu lực", health.manifest?.active ?? 0],
    ["Chờ duyệt", health.manifest?.pending_review ?? 0],
    ["Thiếu tri thức", health.quality?.open_gap_count ?? 0],
    ["Sự cố", health.incidents?.open ?? health.quality?.open_incident_count ?? 0],
    ["Đánh giá", health.evaluation ? (health.evaluation.pass ? "Đạt" : "Lỗi") : "Chưa chạy"],
  ];
  target.innerHTML = metrics
    .map(([label, value]) => `
      <div class="metric">
        <div class="metric-label">${escapeHtml(label)}</div>
        <div class="metric-value">${escapeHtml(value)}</div>
      </div>
    `)
    .join("");
}

function statusPill(status) {
  return `<span class="status ${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>`;
}

function documentKey(record) {
  return `${record?.doc_id || ""}::${record?.version || ""}`;
}

function categoryLabel(category) {
  const labels = {
    procedure: "Quy trình",
    vendor_document: "Tài liệu hãng",
    form_checklist: "Biểu mẫu",
    faq_troubleshooting: "FAQ / lỗi",
  };
  return labels[category] || category || "Chưa phân loại";
}

function feedbackLabel(feedback) {
  const labels = {
    correct: "Đúng",
    wrong_source: "Sai nguồn",
    no_answer: "Không trả lời",
  };
  return labels[feedback] || feedback || "chưa phản hồi";
}

function warningCodeLabel(code) {
  const labels = {
    missing_markdown: "Thiếu Markdown",
    short_markdown: "Markdown quá ngắn",
    possible_mojibake: "Lỗi mã hóa",
    replacement_characters: "Ký tự lỗi",
    ocr_uncertain_text: "OCR cần rà soát",
    qa_not_passed: "QA chưa đạt",
    qa_report_unreadable: "Không đọc được QA",
    missing_qa_report: "Thiếu báo cáo QA",
    title_needs_review: "Tiêu đề cần rà soát",
    category_mismatch: "Lệch danh mục",
    related_versions: "Có phiên bản liên quan",
    older_active_version: "Phiên bản hiệu lực cũ",
  };
  return labels[code] || code || "Cảnh báo";
}

function warningMessageLabel(warning = {}) {
  const message = String(warning.message || "");
  switch (warning.code) {
    case "missing_markdown":
      return "Thiếu file Markdown đã chuẩn hóa.";
    case "short_markdown":
      return "Nội dung Markdown quá ngắn, cần kiểm tra lại nguồn chuyển đổi.";
    case "possible_mojibake":
      return "Markdown vẫn có dấu hiệu lỗi mã hóa.";
    case "replacement_characters":
      return "Markdown chứa ký tự thay thế do lỗi đọc mã.";
    case "ocr_uncertain_text":
      return "Markdown có nhiều dấu hỏi; cần rà soát kết quả OCR.";
    case "qa_not_passed": {
      const status = message.match(/^QA status is (.+)\.$/)?.[1];
      return status ? `Trạng thái QA là ${status}.` : "Báo cáo QA chưa đạt.";
    }
    case "qa_report_unreadable":
      return message ? `Không đọc được báo cáo QA: ${message}` : "Không đọc được báo cáo QA.";
    case "missing_qa_report":
      return "Thiếu báo cáo QA.";
    case "title_needs_review":
      return "Tiêu đề có vẻ bị slug hoặc thiếu dấu tiếng Việt.";
    case "category_mismatch":
      return "Tên file hoặc tiêu đề gợi ý danh mục khác với danh mục hiện tại.";
    case "related_versions": {
      const count = message.match(/^(\d+) related record/)?.[1];
      return count ? `${count} hồ sơ liên quan cùng một nhóm tài liệu.` : "Có hồ sơ liên quan cùng nhóm tài liệu.";
    }
    case "older_active_version": {
      const revision = message.match(/Rev ([^.]+)/)?.[1];
      return revision ? `Hồ sơ hiệu lực đang cũ hơn Rev ${revision}.` : "Hồ sơ hiệu lực có vẻ cũ hơn phiên bản mới nhất.";
    }
    default:
      return message;
  }
}

function jsonBlock(value) {
  return escapeHtml(JSON.stringify(value ?? {}, null, 2));
}

function pathLine(label, value) {
  if (!value) return "";
  return `
    <div class="path-line">
      <span>${escapeHtml(label)}</span>
      <code>${escapeHtml(value)}</code>
      <button class="button micro copy-text-btn" type="button" data-copy="${escapeHtml(value)}">Sao chép</button>
    </div>
  `;
}

function warningList(warnings = []) {
  if (!warnings.length) {
    return `<div class="review-alert ok">Kiểm tra tự động chưa phát hiện cảnh báo chặn duyệt.</div>`;
  }
  return `
    <div class="warning-stack">
      ${warnings.map((warning) => `
        <div class="review-alert ${escapeHtml(warning.level || "warning")}">
          <strong>${escapeHtml(warningCodeLabel(warning.code))}</strong>
          <span>${escapeHtml(warningMessageLabel(warning))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function relatedRecordsTable(records = []) {
  if (!records.length) {
    return `<div class="empty compact-empty">Chưa phát hiện phiên bản liên quan hoặc hồ sơ cùng nhóm.</div>`;
  }
  return `
    <div class="table-wrap compact-table">
      <table>
        <thead>
          <tr>
            <th>Mã tài liệu</th>
            <th>Trạng thái</th>
            <th>Danh mục</th>
            <th>Rev</th>
          </tr>
        </thead>
        <tbody>
          ${records.map((record) => `
            <tr>
              <td>
                <div class="item-title">${escapeHtml(record.doc_id)} v${escapeHtml(record.version)}</div>
                <div class="item-meta">${escapeHtml(record.title || "")}</div>
              </td>
              <td>${statusPill(record.status)}</td>
              <td>${escapeHtml(categoryLabel(record.category))}</td>
              <td>${escapeHtml(record.revision ?? "-")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function bindInspectorButtons(container) {
  container.querySelectorAll(".copy-text-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      await copyText(button.dataset.copy || "", "Đã sao chép");
    });
  });
  container.querySelectorAll(".inspector-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activateInspectorTab(container, button.dataset.tab);
    });
  });
}

function activateInspectorTab(container, tab) {
  if (!container || !tab) return;
  container.querySelectorAll(".inspector-tab").forEach((item) => {
    item.classList.toggle("active", item.dataset.tab === tab);
  });
  container.querySelectorAll(".inspector-section").forEach((section) => {
    section.hidden = section.dataset.section !== tab;
  });
}

function scrollCitationIntoView(container) {
  const target = container?.querySelector(".markdown-line.highlight");
  if (!target) return;
  target.scrollIntoView({ block: "center", behavior: "smooth" });
}

function markdownInline(value) {
  let html = escapeHtml(value);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  html = html.replace(
    /\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return html;
}

function markdownLineRange(lines) {
  if (!lines.length) return "";
  const first = lines[0].line;
  const last = lines[lines.length - 1].line;
  return first === last ? String(first) : `${first}-${last}`;
}

function markdownAnchorAttr(line) {
  return line.anchor_id ? `data-anchor-id="${escapeHtml(line.anchor_id)}"` : "";
}

function markdownLineAttrs(line, extraClass = "") {
  return `class="markdown-line ${extraClass} ${line.highlight ? "highlight" : ""}" data-line="${escapeHtml(line.line)}" ${markdownAnchorAttr(line)}`;
}

function isMarkdownTableSeparator(line) {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(String(line || "").trim());
}

function isMarkdownTableRow(line) {
  const trimmed = String(line || "").trim();
  return trimmed.includes("|") && !trimmed.startsWith("```");
}

function isHtmlTableStart(line) {
  return /<\s*table(?:\s|>)/i.test(String(line || ""));
}

function isHtmlTableEnd(line) {
  return /<\s*\/\s*table\s*>/i.test(String(line || ""));
}

function splitMarkdownTableRow(line) {
  return String(line || "")
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderMarkdownTableBlock(rows) {
  const visibleRows = rows.filter((line) => !isMarkdownTableSeparator(line.text));
  if (!visibleRows.length) return "";
  const hasHeader = rows.length > 1 && isMarkdownTableSeparator(rows[1].text);
  const header = hasHeader ? visibleRows[0] : null;
  const bodyRows = hasHeader ? visibleRows.slice(1) : visibleRows;
  const highlighted = rows.some((line) => line.highlight);
  const anchor = rows.find((line) => line.anchor_id)?.anchor_id || "";
  return `
    <div class="markdown-line markdown-table-block ${highlighted ? "highlight" : ""}" data-line="${escapeHtml(markdownLineRange(rows))}" ${anchor ? `data-anchor-id="${escapeHtml(anchor)}"` : ""}>
      <span class="markdown-line-number">${escapeHtml(markdownLineRange(rows))}</span>
      <div class="markdown-line-content">
        <table class="markdown-table">
          ${
            header
              ? `<thead><tr>${splitMarkdownTableRow(header.text).map((cell) => `<th>${markdownInline(cell)}</th>`).join("")}</tr></thead>`
              : ""
          }
          <tbody>
            ${bodyRows
              .map(
                (row) => `
                  <tr class="${row.highlight ? "row-highlight" : ""}">
                    ${splitMarkdownTableRow(row.text).map((cell) => `<td>${markdownInline(cell)}</td>`).join("")}
                  </tr>
                `,
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function sanitizedSpanAttr(value) {
  const parsed = Number.parseInt(String(value || "1"), 10);
  if (!Number.isFinite(parsed) || parsed <= 1) return "";
  return String(Math.min(parsed, 50));
}

function htmlCellText(node) {
  const collect = (current) => {
    if (!current) return "";
    if (current.nodeType === Node.TEXT_NODE) return current.nodeValue || "";
    if (current.nodeType !== Node.ELEMENT_NODE) return "";
    const tagName = current.tagName.toLowerCase();
    if (tagName === "br") return "\n";
    const childText = Array.from(current.childNodes).map(collect).join("");
    if (["p", "div", "li", "h1", "h2", "h3", "h4"].includes(tagName)) {
      return `${childText}\n`;
    }
    return childText;
  };
  return collect(node)
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function htmlCellContent(node) {
  return escapeHtml(htmlCellText(node) || " ").replace(/\n/g, "<br>");
}

function renderSafeHtmlTable(table) {
  const rows = Array.from(table.rows || []);
  if (!rows.length) return "";
  return `
    <table class="markdown-table markdown-html-table">
      <tbody>
        ${rows
          .map((row) => {
            const cells = Array.from(row.cells || []);
            return `
              <tr>
                ${cells
                  .map((cell) => {
                    const tag = cell.tagName?.toLowerCase() === "th" ? "th" : "td";
                    const rowspan = sanitizedSpanAttr(cell.getAttribute("rowspan"));
                    const colspan = sanitizedSpanAttr(cell.getAttribute("colspan"));
                    const attrs = `${rowspan ? ` rowspan="${rowspan}"` : ""}${colspan ? ` colspan="${colspan}"` : ""}`;
                    return `<${tag}${attrs}>${htmlCellContent(cell)}</${tag}>`;
                  })
                  .join("")}
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

function renderHtmlTableBlock(lines) {
  const source = lines.map((line) => line.text || "").join("\n");
  const highlighted = lines.some((line) => line.highlight);
  const anchor = lines.find((line) => line.anchor_id)?.anchor_id || "";
  let tableHtml = "";
  try {
    const doc = new DOMParser().parseFromString(source, "text/html");
    const tables = Array.from(doc.querySelectorAll("table"));
    tableHtml = tables.map(renderSafeHtmlTable).join("");
  } catch {
    tableHtml = "";
  }
  if (!tableHtml.trim()) {
    tableHtml = `<p>${escapeHtml(source.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() || " ")}</p>`;
  }
  return `
    <div class="markdown-line markdown-table-block markdown-html-table-block ${highlighted ? "highlight" : ""}" data-line="${escapeHtml(markdownLineRange(lines))}" ${anchor ? `data-anchor-id="${escapeHtml(anchor)}"` : ""}>
      <span class="markdown-line-number">${escapeHtml(markdownLineRange(lines))}</span>
      <div class="markdown-line-content">${tableHtml}</div>
    </div>
  `;
}

function renderMarkdownCodeBlock(lines) {
  const highlighted = lines.some((line) => line.highlight);
  const anchor = lines.find((line) => line.anchor_id)?.anchor_id || "";
  const code = lines
    .filter((line) => !String(line.text || "").trim().startsWith("```"))
    .map((line) => line.text)
    .join("\n");
  return `
    <div class="markdown-line markdown-code-block ${highlighted ? "highlight" : ""}" data-line="${escapeHtml(markdownLineRange(lines))}" ${anchor ? `data-anchor-id="${escapeHtml(anchor)}"` : ""}>
      <span class="markdown-line-number">${escapeHtml(markdownLineRange(lines))}</span>
      <div class="markdown-line-content"><pre><code>${escapeHtml(code || " ")}</code></pre></div>
    </div>
  `;
}

function renderMarkdownLineContent(rawLine) {
  const trimmed = String(rawLine || "").trim();
  if (!trimmed) return '<span class="markdown-empty-line">&nbsp;</span>';
  const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
  if (heading) {
    const level = Math.min(heading[1].length + 1, 4);
    return `<h${level}>${markdownInline(heading[2])}</h${level}>`;
  }
  const unordered = trimmed.match(/^[-*]\s+(.+)$/);
  if (unordered) return `<p class="markdown-list-line"><span aria-hidden="true">•</span>${markdownInline(unordered[1])}</p>`;
  const ordered = trimmed.match(/^(\d+)\.\s+(.+)$/);
  if (ordered) return `<p class="markdown-list-line"><span>${escapeHtml(ordered[1])}.</span>${markdownInline(ordered[2])}</p>`;
  const quote = trimmed.match(/^>\s?(.+)$/);
  if (quote) return `<blockquote>${markdownInline(quote[1])}</blockquote>`;
  return `<p>${markdownInline(rawLine)}</p>`;
}

function renderReadableMarkdownViewer(lines, className = "markdown-preview markdown-line-preview markdown-viewer") {
  const rows = Array.isArray(lines) ? lines : [];
  const html = [];
  let index = 0;
  while (index < rows.length) {
    const current = rows[index];
    const text = String(current.text || "");
    const trimmed = text.trim();
    if (isHtmlTableStart(text)) {
      const tableRows = [current];
      index += 1;
      while (index < rows.length && !isHtmlTableEnd(tableRows[tableRows.length - 1].text)) {
        tableRows.push(rows[index]);
        index += 1;
      }
      html.push(renderHtmlTableBlock(tableRows));
      continue;
    }
    if (trimmed.startsWith("```")) {
      const codeRows = [current];
      index += 1;
      while (index < rows.length) {
        codeRows.push(rows[index]);
        if (String(rows[index].text || "").trim().startsWith("```")) {
          index += 1;
          break;
        }
        index += 1;
      }
      html.push(renderMarkdownCodeBlock(codeRows));
      continue;
    }
    if (isMarkdownTableRow(text)) {
      const tableRows = [];
      while (index < rows.length && isMarkdownTableRow(rows[index].text)) {
        tableRows.push(rows[index]);
        index += 1;
      }
      if (tableRows.length >= 2) {
        html.push(renderMarkdownTableBlock(tableRows));
        continue;
      }
      html.push(
        `<div ${markdownLineAttrs(current, "markdown-plain-line")}>
          <span class="markdown-line-number">${escapeHtml(current.line)}</span>
          <div class="markdown-line-content">${renderMarkdownLineContent(text)}</div>
        </div>`,
      );
      continue;
    }
    html.push(
      `<div ${markdownLineAttrs(current, "markdown-plain-line")}>
        <span class="markdown-line-number">${escapeHtml(current.line)}</span>
        <div class="markdown-line-content">${renderMarkdownLineContent(text)}</div>
      </div>`,
    );
    index += 1;
  }
  return `<div class="${className}">${html.join("")}</div>`;
}

function renderMarkdownPreview(markdown, citation, citationPreview = null) {
  const previewLines = citation && Array.isArray(citationPreview?.lines) ? citationPreview.lines : null;
  if (previewLines?.length) {
    return renderReadableMarkdownViewer(previewLines);
  }
  const content = String(markdown?.content || "File Markdown bị thiếu hoặc rỗng.");
  const lines = content.split(/\r?\n/);
  const highlightStart = Number(citation?.line_start || 0);
  const highlightEnd = Number(citation?.line_end || highlightStart || 0);
  const anchorId = citation?.anchor_id || "";
  const viewerLines = lines.map((line, index) => {
    const lineNumber = index + 1;
    const highlighted = Boolean(highlightStart && lineNumber >= highlightStart && lineNumber <= highlightEnd);
    return {
      line: lineNumber,
      text: line,
      highlight: highlighted,
      anchor_id: highlighted ? anchorId : "",
    };
  });
  return renderReadableMarkdownViewer(viewerLines);
}

async function copyText(content, message = "Đã sao chép") {
  if (!String(content || "").trim()) {
    toast("Không có nội dung để sao chép");
    return;
  }
  try {
    await navigator.clipboard.writeText(content);
  } catch {
    const box = qs("#agentPromptBox");
    if (box) {
      box.value = content;
      box.focus();
      box.select();
      document.execCommand("copy");
    }
  }
  toast(message);
}

function renderDocumentInspector(targetSelector, detail, options = {}) {
  const target = qs(targetSelector);
  if (!target) return;
  if (!detail) {
    target.classList.add("empty");
    target.innerHTML = options.emptyText || "Chọn một tài liệu để xem hồ sơ.";
    return;
  }

  const record = detail.record || {};
  const qaStatus = detail.qa_report?.data?.status || record.extra?.qa_status || "-";
  const markdown = detail.markdown || {};
  const citation = detail.citation || null;
  const citationPreview = detail.citation_preview || null;
  const metadataSidecar = detail.metadata_sidecar?.data || {};
  target.classList.remove("empty");
  target.innerHTML = `
    <div class="inspector-summary">
      <div>
        <div class="inspector-title">${escapeHtml(record.doc_id)} v${escapeHtml(record.version)}</div>
        <div class="item-meta">${escapeHtml(record.title || "")}</div>
      </div>
      <div class="inspector-statuses">
        ${statusPill(record.status)}
        <span class="status info">QA ${escapeHtml(qaStatus)}</span>
      </div>
    </div>

    <div class="inspector-grid">
      <div class="metric">
        <div class="metric-label">Danh mục</div>
        <div class="metric-value small">${escapeHtml(categoryLabel(record.category))}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Chủ sở hữu</div>
        <div class="metric-value small">${escapeHtml(record.owner || "-")}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Revision</div>
        <div class="metric-value small">${escapeHtml(detail.current_revision ?? "-")}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Liên quan</div>
        <div class="metric-value small">${escapeHtml(detail.related_records?.length || 0)}</div>
      </div>
    </div>

    ${warningList(detail.warnings || [])}

    <div class="path-stack">
      ${pathLine("Nguồn", record.source_path)}
      ${pathLine("Markdown", record.normalized_path)}
      ${pathLine("QA", detail.qa_report?.path)}
      ${pathLine("Metadata", detail.metadata_sidecar?.path)}
    </div>

    <div class="inspector-tabs" role="tablist" aria-label="Các phần hồ sơ tài liệu">
      <button class="inspector-tab active" type="button" data-tab="metadata">Metadata</button>
      <button class="inspector-tab" type="button" data-tab="markdown">Markdown</button>
      <button class="inspector-tab" type="button" data-tab="qa">Báo cáo QA</button>
      <button class="inspector-tab" type="button" data-tab="versions">Phiên bản</button>
    </div>

    <div class="inspector-section" data-section="metadata">
      <pre class="json-box compact">${jsonBlock({ manifest: record, source_metadata: metadataSidecar })}</pre>
    </div>
    <div class="inspector-section" data-section="markdown" hidden>
      ${markdown.truncated ? `<div class="review-alert warning">Bản xem trước Markdown đã được rút gọn để giữ hiệu năng trình duyệt.</div>` : ""}
      ${
        citation
          ? `<div class="review-alert info">Đã mở trích dẫn ${escapeHtml(citation.anchor_id || "")} (${escapeHtml(citation.locator_status || "exact")}).</div>`
          : ""
      }
      ${renderMarkdownPreview(markdown, citation, citationPreview)}
    </div>
    <div class="inspector-section" data-section="qa" hidden>
      <pre class="json-box compact">${jsonBlock(detail.qa_report?.data || detail.qa_report)}</pre>
    </div>
    <div class="inspector-section" data-section="versions" hidden>
      <div class="item-meta">Nhóm tài liệu: ${escapeHtml(detail.canonical_key || "-")}</div>
      ${relatedRecordsTable(detail.related_records || [])}
    </div>
  `;
  bindInspectorButtons(target);
  if (citation) {
    activateInspectorTab(target, "markdown");
    window.setTimeout(() => scrollCitationIntoView(target), 80);
  }
}

async function loadDocumentDetail(record, target = "documents") {
  if (!record) return;
  const selector = target === "review" ? "#reviewInspector" : "#documentInspector";
  const inspector = qs(selector);
  if (inspector) {
    inspector.classList.add("empty");
    inspector.textContent = "Đang tải hồ sơ tài liệu...";
  }
  const detail = await api(`/api/documents/${encodeURIComponent(record.doc_id)}/${encodeURIComponent(record.version)}`);
  if (target === "review") {
    state.selectedReviewDetail = detail;
    renderDocumentInspector("#reviewInspector", detail, {
      emptyText: "Chọn tài liệu chờ duyệt để kiểm tra metadata và QA trước khi duyệt.",
    });
  } else {
    state.selectedDocumentRecord = record;
    state.selectedDocumentDetail = detail;
    renderManifest();
    renderDocumentInspector("#documentInspector", detail);
  }
}

function citationDetailPath(citation) {
  const base = `/api/documents/${encodeURIComponent(citation.doc_id)}/${encodeURIComponent(citation.version)}/citation`;
  if (citation.anchor_id) {
    return `${base}/${encodeURIComponent(citation.anchor_id)}`;
  }
  const params = new URLSearchParams();
  if (citation.excerpt || citation.matched_excerpt) {
    params.set("excerpt", citation.excerpt || citation.matched_excerpt);
  }
  return params.toString() ? `${base}?${params}` : base;
}

async function openCitationInInspector(citation) {
  if (!citation?.doc_id || !citation?.version) return;
  switchView("documents");
  const inspector = qs("#documentInspector");
  if (inspector) {
    inspector.classList.add("empty");
    inspector.textContent = "Đang mở đoạn trích Markdown...";
  }
  const detail = await api(citationDetailPath(citation));
  state.selectedDocumentRecord = detail.record || citation;
  state.selectedDocumentDetail = detail;
  renderManifest();
  renderDocumentInspector("#documentInspector", detail);
}

function renderManifest() {
  const rows = qs("#manifestRows");
  if (!rows) return;
  renderDocumentFilters();

  const search = (qs("#documentSearchInput")?.value || "").trim().toLowerCase();
  const category = qs("#documentCategoryFilter")?.value || "";
  const status = qs("#documentStatusFilter")?.value ?? "active";
  const baseFiltered = state.manifest.filter((record) => {
    const haystack = [
      record.doc_id,
      record.title,
      record.owner,
      record.category,
      record.department,
      record.status,
    ]
      .join(" ")
      .toLowerCase();
    return (!search || haystack.includes(search))
      && (!status || record.status === status);
  });
  const filtered = baseFiltered.filter((record) => !category || record.category === category);
  renderDocumentCategoryRail(baseFiltered, category);
  renderDocumentResultMeta(filtered.length, baseFiltered.length);

  if (state.selectedDocumentRecord) {
    const stillVisible = filtered.some((record) => documentKey(record) === documentKey(state.selectedDocumentRecord));
    if (!stillVisible) {
      state.selectedDocumentRecord = null;
      state.selectedDocumentDetail = null;
      renderDocumentInspector("#documentInspector", null);
    }
  } else {
    renderDocumentInspector("#documentInspector", null);
  }

  rows.innerHTML = filtered.length
    ? filtered.map((record) => `
      <button
        class="document-record-card document-inspect-btn ${documentKey(record) === documentKey(state.selectedDocumentRecord) ? "selected-row" : ""}"
        type="button"
        data-doc-id="${escapeHtml(record.doc_id)}"
        data-version="${escapeHtml(record.version)}"
      >
        <div class="record-main">
          <div class="record-code">${escapeHtml(record.doc_id)} v${escapeHtml(record.version)}</div>
          <div class="item-title">${escapeHtml(record.title || "-")}</div>
          <div class="item-meta">${escapeHtml(record.source_path || record.normalized_path || "")}</div>
        </div>
        <div class="record-side">
          ${statusPill(record.status)}
          <span>${escapeHtml(categoryLabel(record.category))}</span>
          <span>${escapeHtml(record.owner || "-")}</span>
        </div>
      </button>
    `).join("")
    : `<div class="empty table-empty">Không có tài liệu khớp bộ lọc.</div>`;
  document.querySelectorAll(".document-inspect-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const record = state.manifest.find(
        (item) => item.doc_id === button.dataset.docId && item.version === button.dataset.version,
      );
      try {
        await loadDocumentDetail(record, "documents");
      } catch (err) {
        toast(err.message);
      }
    });
  });
}

function renderDocumentCategoryRail(records, currentCategory) {
  const target = qs("#documentCategoryRail");
  if (!target) return;
  const counts = records.reduce((acc, record) => {
    const key = record.category || "";
    acc.set(key, (acc.get(key) || 0) + 1);
    return acc;
  }, new Map());
  const categories = Array.from(counts.entries())
    .filter(([key]) => key)
    .sort((a, b) => categoryLabel(a[0]).localeCompare(categoryLabel(b[0]), "vi"));
  const items = [["", "Tất cả", records.length], ...categories.map(([key, count]) => [key, categoryLabel(key), count])];
  target.innerHTML = items.map(([key, label, count]) => `
    <button class="category-chip ${key === currentCategory ? "active" : ""}" type="button" data-category="${escapeHtml(key)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(count)}</strong>
    </button>
  `).join("");
  target.querySelectorAll(".category-chip").forEach((button) => {
    button.addEventListener("click", () => {
      const filter = qs("#documentCategoryFilter");
      if (filter) {
        filter.value = button.dataset.category || "";
      }
      renderManifest();
    });
  });
}

function renderDocumentResultMeta(filteredCount, baseCount) {
  const target = qs("#documentResultMeta");
  if (!target) return;
  const suffix = filteredCount === baseCount
    ? "Cuộn trong khung danh sách để xem, không kéo dài toàn trang."
    : `Đang lọc từ ${baseCount} hồ sơ phù hợp tìm kiếm/trạng thái.`;
  target.textContent = `${filteredCount} tài liệu. ${suffix}`;
}

function renderDocumentFilters() {
  const categoryFilter = qs("#documentCategoryFilter");
  if (!categoryFilter) return;
  const current = categoryFilter.value;
  const categories = Array.from(new Set(state.manifest.map((record) => record.category).filter(Boolean))).sort();
  categoryFilter.innerHTML = `<option value="">Tất cả danh mục</option>${categories
    .map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(categoryLabel(category))}</option>`)
    .join("")}`;
  if (categories.includes(current)) {
    categoryFilter.value = current;
  }
}

function renderPending() {
  const pending = state.manifest.filter((record) => record.status === "pending_review");
  const target = qs("#pendingList");
  if (!target) return;
  if (state.selectedReviewRecord) {
    const stillPending = pending.some(
      (record) =>
        record.doc_id === state.selectedReviewRecord.doc_id
        && record.version === state.selectedReviewRecord.version,
    );
    if (!stillPending) {
      state.selectedReviewRecord = null;
      state.selectedReviewDetail = null;
    }
  }
  if (!pending.length) {
    target.innerHTML = `<div class="empty">Không có tài liệu chờ duyệt.</div>`;
    renderReviewSelection();
    return;
  }
  target.innerHTML = pending
    .map((record) => `
      <button class="item pending-pick" data-doc-id="${escapeHtml(record.doc_id)}" data-version="${escapeHtml(record.version)}" type="button">
        <div class="item-title">${escapeHtml(record.doc_id)} v${escapeHtml(record.version)}</div>
        <div class="item-meta">${escapeHtml(record.title)}<br>${escapeHtml(categoryLabel(record.category))} | ${escapeHtml(record.owner)}</div>
      </button>
    `)
    .join("");
  document.querySelectorAll(".pending-pick").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedReviewRecord = pending.find(
        (record) => record.doc_id === button.dataset.docId && record.version === button.dataset.version,
      ) || null;
      state.selectedReviewDetail = null;
      renderReviewSelection();
      loadDocumentDetail(state.selectedReviewRecord, "review").catch((err) => toast(err.message));
    });
  });
  renderReviewSelection();
}

function renderReviewSelection() {
  const selection = qs("#reviewSelection");
  if (!selection) return;
  const record = state.selectedReviewRecord;
  qs("#reviewDocId").value = record?.doc_id || "";
  qs("#reviewVersion").value = record?.version || "";
  document.querySelectorAll(".pending-pick").forEach((button) => {
    button.classList.toggle(
      "selected",
      record?.doc_id === button.dataset.docId && record?.version === button.dataset.version,
    );
  });
  if (!record) {
    selection.classList.add("empty");
    selection.innerHTML = "Chưa chọn tài liệu.";
    state.selectedReviewDetail = null;
    renderDocumentInspector("#reviewInspector", null, {
      emptyText: "Chọn tài liệu chờ duyệt để kiểm tra metadata và QA trước khi duyệt.",
    });
  } else {
    selection.classList.remove("empty");
    selection.innerHTML = `
      <div class="item-title">${escapeHtml(record.doc_id)} v${escapeHtml(record.version)}</div>
      <div class="item-meta">
        ${escapeHtml(record.title || "")}<br>
        Danh mục: ${escapeHtml(categoryLabel(record.category))} | Chủ sở hữu: ${escapeHtml(record.owner || "-")}<br>
        ${escapeHtml(record.source_path || record.normalized_path || "")}
      </div>
    `;
    renderDocumentInspector("#reviewInspector", state.selectedReviewDetail, {
      emptyText: "Đang tải hồ sơ tài liệu...",
    });
  }
  const enabled = Boolean(record);
  qs("#reviewApproveBtn").disabled = !enabled;
  qs("#reviewRejectBtn").disabled = !enabled;
}

function renderQuality() {
  const evaluation = state.health?.evaluation;
  const evaluationBox = qs("#evaluationBox");
  if (!evaluationBox) return;
  evaluationBox.classList.toggle("empty", !evaluation);
  evaluationBox.innerHTML = evaluation
    ? `
      <div class="item">
        <div class="item-title">${evaluation.pass ? "Đánh giá đạt" : "Đánh giá cần xử lý"}</div>
        <div class="item-meta">
          Nguồn: ${escapeHtml(evaluation.provider || "-")} | Hoàn tất: ${escapeHtml(evaluation.finished_at || "-")}<br>
          Top-3 hit: ${escapeHtml(evaluation.metrics?.top3_doc_hit_rate ?? "-")} |
          Trích dẫn: ${escapeHtml(evaluation.metrics?.citation_accuracy ?? "-")} |
          Không trả lời: ${escapeHtml(evaluation.metrics?.no_answer_accuracy ?? "-")} |
          Độ trễ p95: ${escapeHtml(evaluation.metrics?.latency_p95_ms ?? "-")}ms
        </div>
      </div>
    `
    : `<div class="empty">Chưa có lượt đánh giá. Hãy chạy bộ regression mặc định trước khi mở cho người dùng thử.</div>`;

  const visibleGaps = state.gaps.slice(0, 10);
  qs("#gapList").innerHTML = visibleGaps.length
    ? `${listLimitNote(visibleGaps.length, state.gaps.length)}${visibleGaps.map((gap) => `
      <div class="item">
        <div class="item-title">${escapeHtml(gap.reason)}</div>
        <div class="item-meta">${escapeHtml(gap.query)}<br>Chủ xử lý: ${escapeHtml(gap.suggested_owner)} | ${escapeHtml(statusLabel(gap.status))}</div>
      </div>
    `).join("")}`
    : `<div class="empty">Không có khoảng trống tri thức.</div>`;

  const visibleQueries = state.queries.slice(0, 10);
  qs("#queryList").innerHTML = visibleQueries.length
    ? `${listLimitNote(visibleQueries.length, state.queries.length)}${visibleQueries.map((query) => `
      <div class="item">
        <div class="item-title">#${escapeHtml(query.id)} ${escapeHtml(feedbackLabel(query.feedback))}</div>
        <div class="item-meta">${escapeHtml(query.query)}<br>Độ trễ: ${escapeHtml(query.latency_ms)}ms | Trích dẫn: ${query.answer_has_citation ? "có" : "không"}</div>
        <div class="button-row">
          <button class="button secondary feedback-btn" data-id="${escapeHtml(query.id)}" data-feedback="correct" type="button">Đúng</button>
          <button class="button warning feedback-btn" data-id="${escapeHtml(query.id)}" data-feedback="wrong_source" type="button">Sai nguồn</button>
          <button class="button danger feedback-btn" data-id="${escapeHtml(query.id)}" data-feedback="no_answer" type="button">Không trả lời</button>
        </div>
      </div>
    `).join("")}`
    : `<div class="empty">Chưa có log truy vấn.</div>`;

  document.querySelectorAll(".feedback-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      await api("/api/feedback", {
        method: "POST",
        body: JSON.stringify({ query_log_id: Number(button.dataset.id), feedback: button.dataset.feedback }),
      });
      toast("Đã lưu phản hồi");
      await refreshAll();
    });
  });
}

function listLimitNote(visibleCount, totalCount) {
  if (totalCount <= visibleCount) return "";
  return `<div class="item-meta list-note">Đang hiển thị ${escapeHtml(visibleCount)} mục mới nhất trong ${escapeHtml(totalCount)} mục.</div>`;
}

function renderOperations() {
  const healthBox = qs("#healthBox");
  if (!healthBox) return;
  renderOperationStatusCards();
  renderSystemSummary();
  renderLlmStatusPanel();
  renderLlmConfigPanel();
  healthBox.textContent = JSON.stringify(state.health, null, 2);
  const visibleIncidents = state.incidents.slice(0, 10);
  qs("#incidentList").innerHTML = visibleIncidents.length
    ? `${listLimitNote(visibleIncidents.length, state.incidents.length)}${visibleIncidents.map((incident) => `
      <div class="item">
        <div class="item-title">
          ${statusPill(incident.severity)} #${escapeHtml(incident.id)} ${escapeHtml(incident.title)}
        </div>
        <div class="item-meta">
          Thành phần: ${escapeHtml(incident.component)} | Trạng thái: ${escapeHtml(statusLabel(incident.status))}<br>
          ${escapeHtml(incident.detail)}<br>
          ${escapeHtml(incident.created_at)}
        </div>
        ${incident.status === "open" ? `
          <div class="button-row">
            <button class="button copy-incident-prompt-btn" data-id="${escapeHtml(incident.id)}" type="button">Sao chép prompt fix</button>
            <button class="button secondary resolve-incident-btn" data-id="${escapeHtml(incident.id)}" type="button">Đánh dấu đã xử lý</button>
          </div>
        ` : ""}
      </div>
    `).join("")}`
    : `<div class="empty">Không có sự cố. Dùng Chẩn đoán nếu hệ thống có biểu hiện bất thường.</div>`;

  const visibleRuns = state.runs.slice(0, 15);
  qs("#ingestionList").innerHTML = visibleRuns.length
    ? `${listLimitNote(visibleRuns.length, state.runs.length)}${visibleRuns.map((run) => `
      <div class="item">
        <div class="item-title">${escapeHtml(run.status)} ${escapeHtml(run.doc_id || "")} ${escapeHtml(run.version || "")}</div>
        <div class="item-meta">${escapeHtml(run.created_at)}<br>${escapeHtml(run.error_message || run.run_id || "")}</div>
      </div>
    `).join("")}`
    : `<div class="empty">Chưa có lượt xử lý dữ liệu.</div>`;
  qs("#diagnosticsBox").textContent = JSON.stringify(state.diagnostics, null, 2);

  document.querySelectorAll(".resolve-incident-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      await api("/api/incidents/resolve", {
        method: "POST",
        body: JSON.stringify({ incident_id: Number(button.dataset.id), status: "resolved" }),
      });
      toast("Đã xử lý sự cố");
      await refreshAll();
    });
  });
  document.querySelectorAll(".copy-incident-prompt-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const result = await api(`/api/incidents/${button.dataset.id}/agent-prompt`);
      await copyText(result.prompt || "", "Đã sao chép prompt sửa lỗi");
    });
  });
}

function llmStateLabel(status = {}) {
  const labels = {
    not_configured: "Chưa cấu hình",
    configured: "Đã cấu hình",
    proxy_online: "Proxy online",
    ready: "Đang hoạt động",
    error: "Có lỗi",
  };
  return labels[status.state] || "Chưa rõ";
}

function llmStatusClass(status = {}) {
  if (status.state === "ready" || status.state === "proxy_online") return "active";
  if (status.state === "configured") return "ocr_required";
  if (status.state === "not_configured") return "queue";
  return "failed";
}

function formatCheckedAt(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("vi-VN");
  } catch {
    return value;
  }
}

function llmStatusDetail(status = {}) {
  if (!status.configured) return "Thiếu model hoặc API key";
  if (status.state === "ready") return `${status.model || "-"} | ${status.latency_ms ?? "-"}ms`;
  if (status.state === "proxy_online") return `${status.model_count ?? 0} model khả dụng`;
  if (status.state === "configured") return "Chưa kiểm tra live";
  return status.last_error || "Không kiểm tra được LLM";
}

function llmErrorStatus(message) {
  return {
    configured: false,
    state: "error",
    live_checked: true,
    models_ok: false,
    smoke_ok: false,
    latency_ms: null,
    last_error: message || "Không kiểm tra được LLM",
    checked_at: new Date().toISOString(),
  };
}

function readinessCheckLabel(name) {
  const labels = {
    operator_auth: "Xác thực điều phối",
    ragflow_config: "Cấu hình RAGFlow",
    ragflow_network: "Kết nối RAGFlow",
    mineru_available: "MinerU",
    active_documents: "Tài liệu hiệu lực",
    latest_evaluation: "Đánh giá hồi quy",
    local_fallback_disabled: "Dự phòng cục bộ",
  };
  return labels[name] || name;
}

function readinessStatusLabel(status) {
  const labels = {
    pass: "đạt",
    warn: "cảnh báo",
    fail: "lỗi",
  };
  return labels[status] || status;
}

function renderLlmStatusPanel() {
  const target = qs("#llmStatusPanel");
  if (!target) return;
  const status = state.llmStatus || state.health?.llm || {};
  const modelSample = (status.model_sample || []).slice(0, 5).join(", ");
  target.innerHTML = `
    <div class="runtime-status-grid">
      <div class="runtime-status-main ${escapeHtml(llmStatusClass(status))}">
        <div>
          <div class="metric-label">LLM runtime</div>
          <div class="metric-value small">${escapeHtml(llmStateLabel(status))}</div>
        </div>
        <span class="status ${escapeHtml(llmStatusClass(status))}">${escapeHtml(status.live_checked ? "Đã kiểm tra live" : "Cấu hình")}</span>
      </div>
      <div class="runtime-status-row">
        <span>Endpoint</span>
        <code>${escapeHtml(status.base_url || "-")}</code>
      </div>
      <div class="runtime-status-row">
        <span>Model</span>
        <strong>${escapeHtml(status.model || "-")}</strong>
      </div>
      <div class="runtime-status-row">
        <span>Proxy / model</span>
        <strong>${escapeHtml(status.models_ok === null || status.models_ok === undefined ? "Chưa kiểm tra" : status.models_ok ? "OK" : "Lỗi")}</strong>
      </div>
      <div class="runtime-status-row">
        <span>Smoke test</span>
        <strong>${escapeHtml(status.smoke_ok === null || status.smoke_ok === undefined ? "Chưa chạy" : status.smoke_ok ? "Trả lời được" : "Lỗi")}</strong>
      </div>
      <div class="runtime-status-row">
        <span>Lần kiểm tra</span>
        <strong>${escapeHtml(formatCheckedAt(status.checked_at))}</strong>
      </div>
      ${modelSample ? `
        <div class="runtime-status-row wide">
          <span>Model mẫu</span>
          <code>${escapeHtml(modelSample)}</code>
        </div>
      ` : ""}
      ${status.last_error ? `
        <div class="review-alert warning runtime-status-error">
          <strong>Thông báo</strong>
          <span>${escapeHtml(status.last_error)}</span>
        </div>
      ` : ""}
    </div>
  `;
}

function renderLlmConfigPanel() {
  const target = qs("#llmConfigPanel");
  if (!target) return;
  const draft = state.llmDraft || llmConfigToDraft(state.llmConfig, state.llmPresets);
  state.llmDraft = draft;
  const preset = selectedLlmPreset();
  const status = state.llmTestStatus;
  const saveReady = status?.state === "ready";
  target.innerHTML = `
    <div class="llm-config-header">
      <div>
        <div class="metric-label">Cấu hình LLM</div>
        <div class="item-meta">Đổi provider/model ngay trên dashboard. Config áp dụng global cho toàn app.</div>
      </div>
      <span class="status ${escapeHtml(state.llmConfig?.source === "runtime" ? "active" : "info")}">
        ${escapeHtml(state.llmConfig?.source === "runtime" ? "Đang dùng dashboard config" : "Đang dùng env / auto")}
      </span>
    </div>
    <form id="llmConfigForm" class="llm-config-form">
      <div class="llm-preset-row" role="group" aria-label="Chọn nhà cung cấp LLM">
        ${state.llmPresets.map((item) => `
          <button
            class="llm-preset-button ${item.id === draft.provider ? "active" : ""}"
            type="button"
            data-provider="${escapeHtml(item.id)}"
          >${escapeHtml(item.label || item.id)}</button>
        `).join("")}
      </div>
      <div class="llm-form-grid">
        <label class="field-stack" for="llmBaseUrlInput">
          <span>Base URL</span>
          <input id="llmBaseUrlInput" value="${escapeHtml(draft.base_url)}" placeholder="https://.../v1" />
        </label>
        <label class="field-stack" for="llmModelInput">
          <span>Model</span>
          <input id="llmModelInput" value="${escapeHtml(draft.model)}" placeholder="${escapeHtml(preset.model_hint || "model-id")}" />
        </label>
        <label class="field-stack" for="llmApiKeyInput">
          <span>API key</span>
          <input id="llmApiKeyInput" type="password" value="" placeholder="${escapeHtml(state.llmConfig?.api_key_configured ? "Để trống để giữ key hiện tại" : preset.requires_api_key ? "Bắt buộc" : "Không bắt buộc")}" autocomplete="off" />
        </label>
        <label class="field-stack" for="llmTimeoutInput">
          <span>Timeout</span>
          <input id="llmTimeoutInput" type="number" min="3" max="60" value="${escapeHtml(draft.timeout_seconds || 8)}" />
        </label>
      </div>
      <div class="item-meta llm-config-note">${escapeHtml(preset.note || "Endpoint cần tương thích OpenAI /v1/chat/completions.")}</div>
      ${draft.provider === "ollama" ? `<div class="item-meta llm-config-note">Nếu model chưa có, chạy: <code>ollama pull ${escapeHtml(draft.model || preset.model_hint || "llama3.2")}</code></div>` : ""}
      <div class="button-row">
        <button id="loadLlmModelsBtn" class="button secondary" type="button">Tải model</button>
        <button id="testLlmConfigBtn" class="button secondary" type="button">Kiểm tra</button>
        <button id="saveLlmConfigBtn" class="button" type="submit" ${saveReady ? "" : "disabled"}>Lưu & kích hoạt</button>
        <button id="resetLlmConfigBtn" class="button secondary" type="button">Khôi phục mặc định</button>
      </div>
      <div class="llm-test-result">
        ${status ? `
          <div class="runtime-status-main ${escapeHtml(llmStatusClass(status))}">
            <div>
              <div class="metric-label">Kết quả kiểm tra</div>
              <div class="metric-value small">${escapeHtml(llmStateLabel(status))}</div>
            </div>
            <span class="status ${escapeHtml(llmStatusClass(status))}">${escapeHtml(status.latency_ms ?? "-")}ms</span>
          </div>
          ${status.last_error ? `<div class="review-alert warning"><strong>Lỗi</strong><span>${escapeHtml(status.last_error)}</span></div>` : ""}
          ${(status.model_sample || []).length ? `<div class="item-meta">Model mẫu: ${escapeHtml(status.model_sample.slice(0, 6).join(", "))}</div>` : ""}
        ` : `<div class="empty compact-empty">Chưa kiểm tra cấu hình mới.</div>`}
      </div>
    </form>
  `;

  target.querySelectorAll(".llm-preset-button").forEach((button) => {
    button.addEventListener("click", () => applyLlmPreset(button.dataset.provider));
  });
  ["#llmBaseUrlInput", "#llmModelInput", "#llmApiKeyInput", "#llmTimeoutInput"].forEach((selector) => {
    target.querySelector(selector)?.addEventListener("input", () => {
      state.llmDraft = collectLlmDraftFromForm();
      state.llmTestStatus = null;
      qs("#saveLlmConfigBtn").disabled = true;
    });
  });
  qs("#loadLlmModelsBtn")?.addEventListener("click", async () => {
    state.llmDraft = collectLlmDraftFromForm();
    try {
      state.llmTestStatus = await api("/api/llm/test?smoke=false", {
        method: "POST",
        body: JSON.stringify(state.llmDraft),
      });
    } catch (err) {
      state.llmTestStatus = llmErrorStatus(err.message);
    }
    renderOperations();
    toast(state.llmTestStatus.models_ok ? "Đã tải danh sách model" : "Không tải được model");
  });
  qs("#testLlmConfigBtn")?.addEventListener("click", async () => {
    state.llmDraft = collectLlmDraftFromForm();
    try {
      state.llmTestStatus = await api("/api/llm/test?smoke=true", {
        method: "POST",
        body: JSON.stringify(state.llmDraft),
      });
    } catch (err) {
      state.llmTestStatus = llmErrorStatus(err.message);
    }
    renderOperations();
    toast(state.llmTestStatus.state === "ready" ? "LLM trả lời được" : "LLM chưa sẵn sàng");
  });
  qs("#llmConfigForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    state.llmDraft = collectLlmDraftFromForm();
    try {
      const result = await api("/api/llm/config", {
        method: "PUT",
        body: JSON.stringify(state.llmDraft),
      });
      state.llmConfig = result.config;
      state.llmStatus = result.status;
      state.llmTestStatus = result.status;
      await refreshAll();
      toast("Đã kích hoạt cấu hình LLM");
    } catch (err) {
      state.llmTestStatus = llmErrorStatus(err.message);
      renderOperations();
      toast("Chưa lưu được cấu hình LLM");
    }
  });
  qs("#resetLlmConfigBtn")?.addEventListener("click", async () => {
    try {
      state.llmConfig = await api("/api/llm/config/reset", { method: "POST", body: "{}" });
      state.llmDraft = llmConfigToDraft(state.llmConfig, state.llmPresets);
      state.llmTestStatus = null;
      state.llmStatus = state.health?.llm;
      await refreshAll();
      toast("Đã khôi phục cấu hình mặc định");
    } catch (err) {
      toast(err.message);
    }
  });
}

function renderOperationStatusCards() {
  const target = qs("#operationStatusCards");
  if (!target) return;
  const health = state.health || {};
  const ragflowReady = Boolean(health.ragflow?.configured && health.ragflow?.available);
  const mineruReady = Boolean(health.mineru?.available);
  const llmStatus = state.llmStatus || health.llm || {};
  const llmReady = llmStatus.state === "ready" || llmStatus.state === "proxy_online";
  const cards = [
    {
      label: "RAGFlow",
      value: ragflowReady ? "Sẵn sàng" : "Chưa sẵn sàng",
      detail: serviceText(health.ragflow?.message || (health.ragflow?.configured ? "Đã cấu hình" : "Chưa cấu hình")),
      status: ragflowReady ? "active" : "ocr_required",
    },
    {
      label: "MinerU",
      value: mineruReady ? "Sẵn sàng" : "Thiếu",
      detail: health.mineru?.command || "mineru",
      status: mineruReady ? "active" : "failed",
    },
    {
      label: "LLM",
      value: llmStateLabel(llmStatus),
      detail: llmStatusDetail(llmStatus),
      status: llmStatusClass(llmStatus),
    },
    {
      label: "Tài liệu hiệu lực",
      value: health.manifest?.active ?? 0,
      detail: `${health.manifest?.records ?? 0} hồ sơ manifest`,
      status: "active",
    },
    {
      label: "Chờ duyệt",
      value: health.manifest?.pending_review ?? 0,
      detail: "Tài liệu cần phê duyệt",
      status: (health.manifest?.pending_review ?? 0) ? "pending_review" : "done",
    },
    {
      label: "Sự cố mở",
      value: health.incidents?.open ?? 0,
      detail: `${health.incidents?.critical ?? 0} nghiêm trọng`,
      status: (health.incidents?.open ?? 0) ? "failed" : "active",
    },
  ];
  target.innerHTML = cards.map((card) => `
    <div class="status-card ${escapeHtml(card.status)}">
      <div class="metric-label">${escapeHtml(card.label)}</div>
      <div class="metric-value">${escapeHtml(card.value)}</div>
      <div class="item-meta">${escapeHtml(card.detail)}</div>
    </div>
  `).join("");
}

function renderSystemSummary() {
  const target = qs("#systemSummary");
  if (!target) return;
  const health = state.health || {};
  const service = health.service_status || {};
  const providers = (health.providers?.allowed || []).map(providerLabel).join(", ") || "-";
  const readinessIssues = (health.readiness?.checks || [])
    .filter((check) => check.status !== "pass")
    .map((check) => `${readinessCheckLabel(check.name)}: ${readinessStatusLabel(check.status)}`);
  target.innerHTML = `
    <div class="item">
      <div class="item-title">${escapeHtml(serviceText(service.title || "Chưa rõ trạng thái hệ thống"))}</div>
      <div class="item-meta">${escapeHtml(serviceText(service.message || "Chưa có thông điệp trạng thái."))}</div>
    </div>
    <div class="item">
      <div class="item-title">Nguồn truy xuất</div>
      <div class="item-meta">Cho phép: ${escapeHtml(providers)} | Dự phòng cục bộ: ${health.providers?.local_fallback_enabled ? "bật" : "tắt"}</div>
    </div>
    <div class="item">
      <div class="item-title">Mức sẵn sàng</div>
      <div class="item-meta">${
        readinessIssues.length ? escapeHtml(readinessIssues.slice(0, 4).join(" | ")) : "Tất cả kiểm tra sẵn sàng đã đạt."
      }</div>
    </div>
  `;
}

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      if (ADMIN_VIEWS.has(button.dataset.view) && !state.adminUnlocked) {
        showAuthPanel("Mở khóa quyền điều phối để dùng công cụ quản trị.");
        return;
      }
      switchView(button.dataset.view);
    });
  });
}

function switchView(viewName) {
  if (ADMIN_VIEWS.has(viewName) && !state.adminUnlocked) {
    showAuthPanel("Mở khóa quyền điều phối để dùng công cụ quản trị.");
    viewName = "chat";
  }
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewName);
  });
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  qs(`#view-${viewName}`)?.classList.add("active");
  const metrics = qs("#metrics");
  if (metrics) {
    metrics.hidden = viewName === "upload";
  }
  if (window.matchMedia("(max-width: 980px)").matches) {
    const activeView = qs(`#view-${viewName}`);
    requestAnimationFrame(() => activeView?.scrollIntoView({ block: "start" }));
  }
}

async function refreshUploadQueue() {
  state.uploadQueue = await api("/api/upload-queue");
  renderUploadWorkflow();
}

function selectedQueuePaths() {
  return Array.from(document.querySelectorAll(".queue-select:checked"))
    .map((input) => input.dataset.path)
    .filter(Boolean);
}

async function generateAgentPrompt(paths = null) {
  const relativePaths = paths || selectedQueuePaths();
  if (!relativePaths.length) {
    toast("Chọn ít nhất một file trong hàng chờ");
    return;
  }
  const result = await api("/api/agent-prompts/generate", {
    method: "POST",
    body: JSON.stringify({ relative_paths: relativePaths }),
  });
  state.generatedPrompt = result;
  await refreshUploadQueue();
  renderAgentPrompt(result.prompt, result);
  toast("Đã tạo prompt tác nhân");
}

function renderAgentPrompt(prompt, trace = null) {
  const box = qs("#agentPromptBox");
  if (box) {
    box.value = prompt || "";
  }
  const traceTarget = qs("#promptTrace");
  if (traceTarget) {
    if (trace?.prompt_id) {
      traceTarget.textContent = `prompt_id: ${trace.prompt_id} | prompt_version: ${trace.prompt_version || "-"} | số file: ${
        trace.files?.length ?? "-"
      }`;
    } else {
      traceTarget.textContent = "Chưa tạo prompt.";
    }
  }
}

async function copyPrompt(prompt = null) {
  const content = prompt || qs("#agentPromptBox")?.value || "";
  if (!content.trim()) {
    toast("Không có prompt để sao chép");
    return;
  }
  try {
    await navigator.clipboard.writeText(content);
  } catch {
    const box = qs("#agentPromptBox");
    box.value = content;
    box.focus();
    box.select();
    document.execCommand("copy");
  }
  toast("Đã sao chép prompt");
}

async function updateSelectedUploadStatus(status) {
  const relativePaths = selectedQueuePaths().length
    ? selectedQueuePaths()
    : (state.generatedPrompt?.files || []).map((file) => file.relative_path);
  if (!relativePaths.length) {
    toast("Chọn ít nhất một file trong hàng chờ");
    return;
  }
  await updateUploadStatus(relativePaths, status);
}

async function updateUploadStatus(relativePaths, status) {
  await api("/api/upload-queue/status", {
    method: "POST",
    body: JSON.stringify({ relative_paths: relativePaths, status }),
  });
  await refreshUploadQueue();
  toast(`Đã cập nhật ${relativePaths.length} file sang trạng thái ${statusLabel(status)}`);
}

function setupActions() {
  qs("#refreshBtn").addEventListener("click", () => refreshAll().catch((err) => toast(err.message)));
  qs("#operatorAccessBtn").addEventListener("click", () => {
    if (!state.authStatus?.required) {
      switchView("operations");
      return;
    }
    if (state.adminUnlocked) {
      localStorage.removeItem("kbOperatorToken");
      syncAdminAccess();
      hideAuthPanel();
      toast("Đã khóa công cụ điều phối");
      return;
    }
    showAuthPanel("Nhập token điều phối để mở khóa công cụ quản trị.");
  });
  ["#documentSearchInput", "#documentCategoryFilter", "#documentStatusFilter"].forEach((selector) => {
    qs(selector)?.addEventListener("input", renderManifest);
    qs(selector)?.addEventListener("change", renderManifest);
  });
  document.querySelectorAll(".answer-feedback-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!state.lastQueryLogId) {
        toast("Hãy đặt câu hỏi trước khi gửi phản hồi");
        return;
      }
      await api("/api/feedback", {
        method: "POST",
        body: JSON.stringify({ query_log_id: Number(state.lastQueryLogId), feedback: button.dataset.feedback }),
      });
      toast("Đã lưu phản hồi");
      await refreshAll();
    });
  });
  qs("#uploadForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const files = Array.from(qs("#uploadFiles").files || []);
    if (!files.length) {
      toast("Chọn ít nhất một file");
      return;
    }
    const category = qs("#uploadCategory").value || null;
    for (const file of files) {
      await api("/api/inbox/upload", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_base64: await readFileAsDataUrl(file),
          category,
        }),
      });
    }
    qs("#uploadFiles").value = "";
    toast(`Đã thêm ${files.length} file vào hàng chờ`);
    await refreshAll();
  });
  const uploadZone = qs(".upload-zone");
  uploadZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    uploadZone.classList.add("dragover");
  });
  uploadZone.addEventListener("dragleave", () => {
    uploadZone.classList.remove("dragover");
  });
  uploadZone.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadZone.classList.remove("dragover");
    if (event.dataTransfer?.files?.length) {
      qs("#uploadFiles").files = event.dataTransfer.files;
      toast(`Đã chọn ${event.dataTransfer.files.length} file`);
    }
  });
  qs("#scanSourceBtn").addEventListener("click", async () => {
    await refreshUploadQueue();
    toast("Đã quét thư mục nguồn");
  });
  qs("#generatePromptBtn").addEventListener("click", () => generateAgentPrompt().catch((err) => toast(err.message)));
  qs("#copyPromptBtn").addEventListener("click", () => copyPrompt().catch((err) => toast(err.message)));
  qs("#copySelectedPromptBtn").addEventListener("click", async () => {
    const selected = selectedQueuePaths()
      .map((path) => findQueueItem(path, "inbox"))
      .filter((item) => item?.prompt);
    if (!selected.length) {
      await copyPrompt();
      return;
    }
    renderAgentPrompt(selected[0].prompt, {
      prompt_id: selected[0].prompt_id,
      prompt_version: selected[0].prompt_version,
      files: selected,
    });
    await copyPrompt(selected[0].prompt);
  });
  qs("#moveWorkplaceBtn").addEventListener("click", () => updateSelectedUploadStatus("processing").catch((err) => toast(err.message)));
  qs("#markFailedBtn").addEventListener("click", () => updateSelectedUploadStatus("failed").catch((err) => toast(err.message)));
  qs("#clearPromptBtn").addEventListener("click", () => {
    state.generatedPrompt = null;
    renderAgentPrompt("");
  });
  qs("#selectAllQueue").addEventListener("change", (event) => {
    document.querySelectorAll(".queue-select:not(:disabled)").forEach((input) => {
      input.checked = event.target.checked;
    });
  });
  qs("#rebuildBtn").addEventListener("click", async () => {
    await api("/api/rebuild-index", { method: "POST", body: "{}" });
    toast("Đã dựng lại index dự phòng cục bộ");
  });
  qs("#syncRagflowBtn").addEventListener("click", async () => {
    await api("/api/sync-ragflow", { method: "POST", body: "{}" });
    toast("Đã yêu cầu đồng bộ RAGFlow");
    await refreshAll();
  });
  qs("#bootstrapRagflowBtn").addEventListener("click", async () => {
    const result = await api("/api/bootstrap-ragflow", { method: "POST", body: "{}" });
    toast(`Dataset RAGFlow ${result.dataset_created ? "đã tạo" : "đã tồn tại"}`);
    await refreshAll();
  });
  qs("#evaluateBtn").addEventListener("click", async () => {
    const result = await api("/api/evaluate", {
      method: "POST",
      body: JSON.stringify({ provider: qs("#providerSelect")?.value || "auto", latency_target_ms: 12000 }),
    });
    toast(result.pass ? "Đánh giá đạt" : "Đánh giá lỗi");
    await refreshAll();
  });
  qs("#refreshDiagnosticsBtn").addEventListener("click", async () => {
    state.diagnostics = await api("/api/diagnostics?include_logs=true");
    renderOperations();
    toast("Đã làm mới chẩn đoán");
  });
  qs("#checkLlmBtn")?.addEventListener("click", async () => {
    const button = qs("#checkLlmBtn");
    button.disabled = true;
    button.textContent = "Đang kiểm tra...";
    try {
      state.llmStatus = await api("/api/llm/status?smoke=true");
      renderOperations();
      toast(state.llmStatus.state === "ready" ? "LLM đang hoạt động" : "LLM cần kiểm tra cấu hình");
    } finally {
      button.disabled = false;
      button.textContent = "Kiểm tra LLM";
    }
  });
  qs("#chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      query: qs("#queryInput").value,
      user_id: qs("#userIdInput")?.value || null,
      provider: qs("#providerSelect")?.value || "auto",
      use_llm: Boolean(qs("#useLlmInput")?.checked),
    };
    try {
      const result = await api("/api/chat", { method: "POST", body: JSON.stringify(payload) });
      state.lastQueryLogId = result.query_log_id;
      qs("#answerBox").classList.remove("empty");
      qs("#answerBox").textContent = result.answer;
      qs("#answerFeedback").hidden = !result.query_log_id;
      qs("#citations").classList.remove("empty");
      qs("#citations").innerHTML = result.citations.length
        ? result.citations.map((citation, index) => `
          <button class="item citation-card" type="button" data-citation-index="${index}">
            <div class="item-title">${escapeHtml(citation.title || citation.doc_id || "Nguồn")}</div>
            <div class="item-meta">
              Mã: ${escapeHtml(citation.doc_id || "-")} | Phiên bản: ${escapeHtml(citation.version || "-")}<br>
              ${escapeHtml(citation.anchor_id || citation.chunk_id || "")}
            </div>
            <div class="item-meta">${escapeHtml(citation.matched_excerpt || citation.excerpt || "")}</div>
          </button>
        `).join("")
        : `<div class="empty">Không có nguồn trích dẫn trả về.</div>`;
      document.querySelectorAll(".citation-card").forEach((button) => {
        button.addEventListener("click", async () => {
          const citation = result.citations[Number(button.dataset.citationIndex)];
          try {
            await openCitationInInspector(citation);
          } catch (error) {
            toast(error.message || "Không mở được đoạn trích Markdown");
          }
        });
      });
      await refreshAll();
    } catch (err) {
      qs("#answerBox").classList.remove("empty");
      qs("#answerBox").textContent = err.message || "Hệ thống đang tạm thời không sẵn sàng.";
      qs("#answerFeedback").hidden = true;
      renderServiceBanner({
        state: "unavailable",
        title: "Hệ thống chưa thể trả lời",
        message: err.message || "Vui lòng thử lại sau hoặc liên hệ kỹ thuật.",
        can_chat: false,
      });
      toast(err.message);
    }
  });
  qs("#reviewForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const action = event.submitter.dataset.action;
    const doc_id = qs("#reviewDocId").value;
    const version = qs("#reviewVersion").value;
    const reason = qs("#rejectReason").value.trim();
    if (!doc_id || !version) {
      toast("Chọn tài liệu chờ duyệt trước");
      return;
    }
    if (action === "approve") {
      await api("/api/approve", {
        method: "POST",
        body: JSON.stringify({ doc_id, version, approved_by: qs("#approvedBy").value || "Người duyệt" }),
      });
      toast("Đã duyệt tài liệu");
    } else {
      if (!reason) {
        toast("Cần nhập lý do từ chối");
        qs("#rejectReason").focus();
        return;
      }
      await api("/api/reject", { method: "POST", body: JSON.stringify({ doc_id, version, reason }) });
      toast("Đã từ chối tài liệu");
    }
    state.selectedReviewRecord = null;
    state.selectedReviewDetail = null;
    qs("#rejectReason").value = "";
    document.querySelectorAll(".review-check").forEach((input) => {
      input.checked = false;
    });
    await refreshAll();
  });
}

function setupAuthPanel() {
  qs("#saveOperatorTokenBtn").addEventListener("click", async () => {
    const token = qs("#operatorTokenInput").value.trim();
    if (!token) {
      showAuthPanel("Token điều phối là bắt buộc.");
      return;
    }
    localStorage.setItem("kbOperatorToken", token);
    try {
      await refreshAll();
      syncAdminAccess();
      hideAuthPanel();
      toast("Đã mở khóa quyền điều phối");
    } catch (err) {
      if (err.authRequired) {
        localStorage.removeItem("kbOperatorToken");
        syncAdminAccess();
        showAuthPanel("Token bị từ chối. Kiểm tra .runtime\\kb-auth-token.txt rồi thử lại.");
        return;
      }
      toast(err.message);
    }
  });
  qs("#clearOperatorTokenBtn").addEventListener("click", () => {
    localStorage.removeItem("kbOperatorToken");
    syncAdminAccess();
    showAuthPanel("Đã xóa token. Nhập token điều phối để tiếp tục.");
  });
  qs("#operatorTokenInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      qs("#saveOperatorTokenBtn").click();
    }
  });
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("Không đọc được file"));
    reader.readAsDataURL(file);
  });
}

setupNavigation();
setupActions();
setupAuthPanel();
syncAdminAccess();
refreshAll().catch((err) => {
  if (err.authRequired) {
    return;
  }
  renderServiceBanner({
    state: "offline",
    title: "Không kết nối được hệ thống",
    message: err.message || "Không thể kết nối backend.",
    can_chat: false,
  });
  toast(err.message);
});
