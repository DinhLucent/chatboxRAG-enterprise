const state = {
  health: null,
  manifest: [],
  uploadQueue: { items: [], summary: {} },
  gaps: [],
  queries: [],
  runs: [],
  incidents: [],
  diagnostics: null,
  lastQueryLogId: null,
  generatedPrompt: null,
  adminUnlocked: false,
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
  return Boolean(localStorage.getItem("kbOperatorToken"));
}

function syncAdminAccess() {
  state.adminUnlocked = isAdminUnlocked();
  document.body.classList.toggle("admin-unlocked", state.adminUnlocked);
  const button = qs("#operatorAccessBtn");
  if (button) {
    button.textContent = state.adminUnlocked ? "Khóa điều phối" : "Điều phối";
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
  const [health, manifest, uploadQueue, gaps, queries, runs, incidents, diagnostics] = await Promise.all([
    api("/api/health"),
    api("/api/manifest"),
    api("/api/upload-queue"),
    api("/api/gaps"),
    api("/api/queries"),
    api("/api/ingestion-runs"),
    api("/api/incidents?limit=25"),
    api("/api/diagnostics?include_logs=false"),
  ]);
  Object.assign(state, { health, manifest, uploadQueue, gaps, queries, runs, incidents, diagnostics });
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
    <strong>${escapeHtml(current.title)}</strong>
      <span>${escapeHtml(current.message)}</span>
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

function renderProviderOptions() {
  const select = qs("#providerSelect");
  if (!select) return;
  const allowed = state.health?.providers?.allowed || ["auto", "ragflow", "local"];
  const labels = {
    auto: "Tự động",
    ragflow: "Chỉ RAGFlow",
    local: "Dự phòng cục bộ",
  };
  const current = allowed.includes(select.value) ? select.value : allowed[0] || "auto";
  select.innerHTML = allowed
    .map((provider) => `<option value="${escapeHtml(provider)}">${escapeHtml(labels[provider] || provider)}</option>`)
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
          <strong>${escapeHtml(warning.code || "cảnh báo")}</strong>
          <span>${escapeHtml(warning.message || "")}</span>
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
      const tab = button.dataset.tab;
      container.querySelectorAll(".inspector-tab").forEach((item) => {
        item.classList.toggle("active", item.dataset.tab === tab);
      });
      container.querySelectorAll(".inspector-section").forEach((section) => {
        section.hidden = section.dataset.section !== tab;
      });
    });
  });
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
      <button class="inspector-tab" type="button" data-tab="qa">QA Report</button>
      <button class="inspector-tab" type="button" data-tab="versions">Phiên bản</button>
    </div>

    <div class="inspector-section" data-section="metadata">
      <pre class="json-box compact">${jsonBlock({ manifest: record, source_metadata: metadataSidecar })}</pre>
    </div>
    <div class="inspector-section" data-section="markdown" hidden>
      ${markdown.truncated ? `<div class="review-alert warning">Bản xem trước Markdown đã được rút gọn để giữ hiệu năng trình duyệt.</div>` : ""}
      <pre class="markdown-preview">${escapeHtml(markdown.content || "File Markdown bị thiếu hoặc rỗng.")}</pre>
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
      <tr class="${documentKey(record) === documentKey(state.selectedDocumentRecord) ? "selected-row" : ""}">
        <td>${escapeHtml(record.doc_id)}</td>
        <td>
          <div class="item-title">${escapeHtml(record.title || "-")}</div>
          <div class="item-meta">${escapeHtml(record.source_path || record.normalized_path || "")}</div>
        </td>
        <td>${escapeHtml(record.version)}</td>
        <td>${statusPill(record.status)}</td>
        <td>${escapeHtml(categoryLabel(record.category))}</td>
        <td>${escapeHtml(record.owner)}</td>
        <td>
          <button
            class="button micro document-inspect-btn"
            type="button"
            data-doc-id="${escapeHtml(record.doc_id)}"
            data-version="${escapeHtml(record.version)}"
          >
            Xem
          </button>
        </td>
      </tr>
    `).join("")
    : `
      <tr>
        <td colspan="7" class="empty table-empty">Không có tài liệu khớp bộ lọc.</td>
      </tr>
    `;
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
          Latency p95: ${escapeHtml(evaluation.metrics?.latency_p95_ms ?? "-")}ms
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
}

function renderOperationStatusCards() {
  const target = qs("#operationStatusCards");
  if (!target) return;
  const health = state.health || {};
  const ragflowReady = Boolean(health.ragflow?.configured && health.ragflow?.available);
  const mineruReady = Boolean(health.mineru?.available);
  const llmReady = Boolean(health.llm?.configured);
  const cards = [
    {
      label: "RAGFlow",
      value: ragflowReady ? "Sẵn sàng" : "Chưa sẵn sàng",
      detail: health.ragflow?.message || (health.ragflow?.configured ? "Đã cấu hình" : "Chưa cấu hình"),
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
      value: llmReady ? "Đã cấu hình" : "Tắt",
      detail: health.llm?.model || "Chỉ trả lời theo tài liệu nguồn",
      status: llmReady ? "active" : "queue",
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
  const providers = health.providers?.allowed?.join(", ") || "-";
  const readinessIssues = (health.readiness?.checks || [])
    .filter((check) => check.status !== "pass")
    .map((check) => `${check.name}: ${check.status}`);
  target.innerHTML = `
    <div class="item">
      <div class="item-title">${escapeHtml(service.title || "Chưa rõ trạng thái hệ thống")}</div>
      <div class="item-meta">${escapeHtml(service.message || "Chưa có thông điệp trạng thái.")}</div>
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
        ? result.citations.map((citation) => `
          <div class="item">
            <div class="item-title">${escapeHtml(citation.title || citation.doc_id || "Nguồn")}</div>
            <div class="item-meta">
              Mã: ${escapeHtml(citation.doc_id || "-")} | Phiên bản: ${escapeHtml(citation.version || "-")}<br>
              ${escapeHtml(citation.source_path || citation.normalized_path || citation.chunk_id || "")}
            </div>
          </div>
        `).join("")
        : `<div class="empty">Không có nguồn trích dẫn trả về.</div>`;
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
