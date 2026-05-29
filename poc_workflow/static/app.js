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

  promptTemplates: { default_mode: "process_raw", modes: [] },

  activePromptTab: "task",

  adminUnlocked: false,

  authStatus: { required: true, configured: false },

  selectedReviewRecord: null,

  selectedDocumentRecord: null,

  selectedDocumentDetail: null,

  selectedReviewDetail: null,

  chatMessagesList: [],

  annotations: [],

  selectedGaps: new Set(),

  selectedQueries: new Set(),

  selectedRuns: new Set(),

  selectedIncidents: new Set(),

  selectedLogs: new Set(),

};



const ADMIN_VIEWS = new Set(["chat", "upload", "review", "operations"]);



const UPLOAD_WORKFLOW_STEPS = [

  { id: "waiting", label: "Chờ file", hint: "File nằm trong inbox và chưa được agent nhận xử lý." },

  { id: "prepare", label: "Nhận file", hint: "Tạo workplace xử lý tuần tự cho một file." },

  { id: "classify", label: "Phân loại", hint: "Nhận diện nhóm tài liệu và hướng xử lý." },

  { id: "mineru_convert", label: "HyperScribeModel", hint: "Convert/extract bằng HyperScribeModel, gồm OCR khi cần." },

  { id: "extract_artifacts", label: "Artifact map", hint: "Trích content_list, middle/model JSON và images từ HyperScribeModel package." },

  { id: "compare_sources", label: "So sánh nguồn", hint: "So sánh PDF/XLSX và chọn bản sạch hơn." },

  { id: "preclean", label: "Pre-clean", hint: "Loại nhiễu rõ ràng, giữ tối đa nội dung nguồn." },

  { id: "domain_agent", label: "Domain agent", hint: "Chuẩn hóa nội dung theo domain quy trình." },

  { id: "handoff_check", label: "Handoff", hint: "Kiểm tra bàn giao giữa các sub-agent." },

  { id: "qa", label: "QA", hint: "Đối chiếu ý nghĩa, cấu trúc, citation và lỗi synthetic." },

  { id: "repair_loop", label: "Repair", hint: "Trả về đúng agent để sửa nếu QA fail." },

  { id: "rag_ready", label: "Knowledge-ready", hint: "Đóng schema, metadata và chunk/citation map." },

  { id: "review", label: "Human review", hint: "Admin duyệt trước khi đồng bộ tri thức." },

  { id: "done", label: "Review queue", hint: "Xử lý xong và chờ human approval; chưa đồng bộ knowledge base." },

  { id: "ocr_required", label: "Cần OCR", hint: "Cần OCR hoặc kiểm tra thủ công trước khi tiếp tục." },

  { id: "failed", label: "Lỗi", hint: "Workflow dừng vì lỗi cần xử lý." },

];



const AGENT_WORKFLOW_BLUEPRINT = [

  {

    id: "intake",

    title: "Intake",

    stage: "prepare",

    skill: "data-pipeline-orchestrator",

    input: "inbox/root_source raw file",

    output: "run_plan + source_id",

    gate: "single file/group only",

  },

  {

    id: "convert",

    title: "HyperScribeModel Convert",

    stage: "mineru_convert",

    skill: "hyperscribe-normalizer",

    input: "PDF/XLSX primary candidates",

    output: "raw .md + ZIP sidecars",

    gate: "HyperScribeModel only, no parser fallback",

  },

  {

    id: "artifact",

    title: "Artifact Map",

    stage: "extract_artifacts",

    skill: "hyperscribe-normalizer",

    input: "conversion_result.zip",

    output: "document_artifact_index.json",

    gate: "content_list/middle/images kept",

  },

  {

    id: "audit",

    title: "Source QA",

    stage: "qa",

    skill: "source-output-quality-auditor",

    input: "source + Markdown + sidecars",

    output: "audit_report + repair_request",

    gate: "source-faithfulness + citation",

  },

  {

    id: "repair",

    title: "Repair Loop",

    stage: "repair_loop",

    skill: "rag-markdown-repairer",

    input: "QA handoff + HyperScribeModel refs",

    output: "clean Markdown + fixed anchors",

    gate: "max loop then human review",

  },

  {

    id: "package",

    title: "Knowledge-ready",

    stage: "rag_ready",

    skill: "knowledge-schema-indexer",

    input: "approved QA output",

    output: "metadata, chunks, citation_map",

    gate: "no KnowledgeCore sync yet",

  },

  {

    id: "evolve",

    title: "Learning",

    stage: "review",

    skill: "data-skill-evolution",

    input: "run logs + audit issues",

    output: "rule candidates",

    gate: "human approves changes",

  },

];



const PROMPT_PACKET_BLUEPRINT = [

  {

    title: "Source Packet",

    items: ["selected files", "absolute paths", "business role", "primary/supporting candidates"],

  },

  {

    title: "Policy Packet",

    items: ["immutable raw source", "HyperScribeModel-only conversion", "no duplicate PDF/XLSX ingest"],

  },

  {

    title: "Workflow Packet",

    items: ["skill order", "one file at a time", "repair loop limit", "dashboard stage updates"],

  },

  {

    title: "Skill Contract Packet",

    items: ["skill_read_receipts", "subagent prompt contract", "handoff checker", "Knowledge readiness contract"],

  },

  {

    title: "Evidence Packet",

    items: ["document_artifact_index", "content_list_v2", "middle.json", "images", "citation anchors"],

  },

  {

    title: "Handoff Packet",

    items: ["run_id", "step", "status", "source_ids", "artifacts", "quality_gates", "next_skill"],

  },

  {

    title: "Output Packet",

    items: ["normalized Markdown", "metadata", "section index", "chunk plan", "citation map", "quality report"],

  },

];



const WORKFLOW_STEP_ALIASES = {

  waiting: "waiting",

  prepare: "prepare",

  classify: "classify",

  route: "classify",

  check_service: "mineru_convert",

  submit: "mineru_convert",

  queue: "mineru_convert",

  parse: "mineru_convert",

  download: "mineru_convert",

  extract_artifacts: "extract_artifacts",

  build_outputs: "mineru_convert",

  mineru: "mineru_convert",

  mineru_convert: "mineru_convert",

  source_probe: "compare_sources",

  compare_sources: "compare_sources",

  preclean: "preclean",

  clean: "preclean",

  normalize: "domain_agent",

  domain_agent: "domain_agent",

  handoff: "handoff_check",

  handoff_check: "handoff_check",

  qa: "qa",

  verify: "qa",

  repair: "repair_loop",

  repair_loop: "repair_loop",

  rag_ready: "rag_ready",

  formatter: "rag_ready",

  review: "review",

  done: "done",

  ocr_required: "ocr_required",

  failed: "failed",

};



const WORKFLOW_EXCEPTION_STEPS = new Set(["ocr_required", "failed"]);



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

    switchView("documents");

  }

}



function toast(message) {

  const el = qs("#toast");

  el.textContent = displayAlias(message);

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



const TECH_DISPLAY_ALIASES = [

  [/\bMinerU\b/g, "HyperScribeModel"],

  [/\bmineru-source-converter\b/gi, "hyperscribe-normalizer"],

  [/\bmineru_artifact_index\b/gi, "document_artifact_index"],

  [/\bmineru_result\.zip\b/gi, "conversion_result.zip"],

  [/\bmineru_raw\b/gi, "converted_raw"],

  [/\bmineru\b/gi, "hyperscribe"],

  [/\bRAGFlow\b/g, "KnowledgeCore"],

  [/\bragflow-schema-indexer\b/gi, "knowledge-schema-indexer"],

  [/\bragflow_index\b/gi, "knowledge_index"],

  [/\bragflow_ingestion\b/gi, "knowledge_sync"],

  [/\bragflow\b/gi, "knowledgecore"],

  [/\bRAG-ready\b/g, "Knowledge-ready"],

  [/\bRAG\b/g, "Knowledge Retrieval"],

  [/\bFreeLLMAPI\b/g, "LLM Gateway"],

  [/\bFastAPI\b/g, "Application API"],

  [/\bpoc_workflow\b/g, "workflow runtime"],

];



function displayAlias(value) {

  return TECH_DISPLAY_ALIASES.reduce(

    (text, [pattern, replacement]) => text.replace(pattern, replacement),

    String(value ?? ""),

  );

}



function displayText(value) {

  return escapeHtml(displayAlias(value));

}



async function refreshAll() {

  const [

    authStatus,

    health,

    manifest,

    uploadQueue,

    promptTemplates,

    gaps,

    queries,

    runs,

    incidents,

    diagnostics,

    llmPresets,

    llmConfig,

    annotations,

  ] = await Promise.all([

    api("/api/auth-status"),

    api("/api/health"),

    api("/api/manifest"),

    api("/api/upload-queue"),

    api("/api/agent-prompts/templates"),

    api("/api/gaps"),

    api("/api/queries"),

    api("/api/ingestion-runs"),

    api("/api/incidents?limit=25"),

    api("/api/diagnostics?include_logs=false"),

    api("/api/llm/presets"),

    api("/api/llm/config"),

    api("/api/annotations"),

  ]);

  Object.assign(state, { authStatus, health, manifest, uploadQueue, promptTemplates, gaps, queries, runs, incidents, diagnostics, llmPresets, llmConfig, annotations });

  

  // Prune selected sets to remove IDs that no longer exist

  const currentGapIds = new Set(state.gaps.map(g => g.id));

  state.selectedGaps.forEach(id => { if (!currentGapIds.has(id)) state.selectedGaps.delete(id); });



  const currentQueryIds = new Set(state.queries.map(q => q.id));

  state.selectedQueries.forEach(id => { if (!currentQueryIds.has(id)) state.selectedQueries.delete(id); });



  const currentRunIds = new Set(state.runs.map(r => r.id));

  state.selectedRuns.forEach(id => { if (!currentRunIds.has(id)) state.selectedRuns.delete(id); });



  const currentIncidentIds = new Set(state.incidents.map(i => i.id));

  state.selectedIncidents.forEach(id => { if (!currentIncidentIds.has(id)) state.selectedIncidents.delete(id); });



  const currentLogFiles = new Set((state.diagnostics?.runtime_logs || []).map(l => l.file));

  state.selectedLogs.forEach(file => { if (!currentLogFiles.has(file)) state.selectedLogs.delete(file); });



  await refreshSelectedDetails();

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

  renderPromptTemplates();

  renderManifest();

  if (state.selectedDocumentRecord) {

    renderDocumentInspector("#documentInspector", state.selectedDocumentDetail);

  }

  renderPending();

  if (state.selectedReviewRecord) {

    renderDocumentInspector("#reviewInspector", state.selectedReviewDetail, {

      emptyText: "Chọn tài liệu chờ duyệt để kiểm tra metadata và QA trước khi duyệt.",

    });

    syncReviewFormFromDetail(state.selectedReviewDetail);

  }

  renderQuality();

  renderOperations();

  updateArchitectureStatus(health);

}



async function refreshSelectedDetails() {

  if (state.selectedDocumentRecord) {

    const current = state.manifest.find((record) => documentKey(record) === documentKey(state.selectedDocumentRecord));

    if (current) {

      state.selectedDocumentRecord = current;

      state.selectedDocumentDetail = await api(`/api/documents/${encodeURIComponent(current.doc_id)}/${encodeURIComponent(current.version)}`);

    } else {

      state.selectedDocumentRecord = null;

      state.selectedDocumentDetail = null;

    }

  }

  if (state.selectedReviewRecord) {

    const current = state.manifest.find((record) => documentKey(record) === documentKey(state.selectedReviewRecord));

    if (current) {

      state.selectedReviewRecord = current;

      state.selectedReviewDetail = await api(`/api/documents/${encodeURIComponent(current.doc_id)}/${encodeURIComponent(current.version)}`);

    } else {

      state.selectedReviewRecord = null;

      state.selectedReviewDetail = null;

    }

  }

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

    "RAGFlow env is not configured": "Chưa cấu hình KnowledgeCore",

  };

  return displayAlias(known[text] || text);

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

  const items = state.uploadQueue?.items || [];

  const overviewTarget = qs("#uploadWorkflowOverview");

  const mapTarget = qs("#agentWorkflowMap");

  const statusOrder = ["queue", "processing", "done", "pending_review", "approved", "ocr_required", "failed", "failed_review"];

  cardsTarget.innerHTML = statusOrder

    .map((status) => `

      <div class="status-card ${escapeHtml(status)}">

        <div class="metric-label">${escapeHtml(statusLabel(status))}</div>

        <div class="metric-value">${escapeHtml(summary[status] ?? 0)}</div>

      </div>

    `)

    .join("");

  if (overviewTarget) {

    overviewTarget.innerHTML = renderWorkflowOverview(items);

  }

  if (mapTarget) {

    mapTarget.innerHTML = renderAgentWorkflowMap(items);

  }



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



function renderPromptTemplates() {

  const select = qs("#promptModeSelect");

  const help = qs("#promptModeHelp");

  const branchInput = qs("#goalBranchInput");

  if (branchInput && !branchInput.dataset.touched) {

    branchInput.value = state.promptTemplates?.default_goal_branch || branchInput.value || "codex/upload-data-long-run";

  }

  if (!select) {

    renderPromptTabs();

    return;

  }

  const templates = state.promptTemplates?.modes || [];

  const current = select.value || state.promptTemplates?.default_mode || "process_raw";

  select.innerHTML = templates.length

    ? templates

        .map(

          (mode) => `

            <option value="${escapeHtml(mode.id)}">${displayText(mode.label || mode.id)}</option>

          `

        )

        .join("")

    : `<option value="process_raw">Xử lý dữ liệu thô (Raw data)</option>`;

  const nextValue = templates.some((mode) => mode.id === current)

    ? current

    : state.promptTemplates?.default_mode || templates[0]?.id || "process_raw";

  select.value = nextValue;

  renderPromptModeHelp();

  renderPromptArchitecture();

  renderPromptTabs();

}



function renderPromptModeHelp() {

  const select = qs("#promptModeSelect");

  const help = qs("#promptModeHelp");

  if (!select || !help) return;

  const mode = (state.promptTemplates?.modes || []).find((item) => item.id === select.value);

  help.textContent = displayAlias(mode?.description || "Chọn chế độ prompt để điều phối AI agent xử lý dữ liệu đúng quy trình (workflow).");

  renderPromptArchitecture();

}



function renderPromptTabs() {

  document.querySelectorAll(".prompt-tab-button").forEach((button) => {

    button.classList.toggle("active", button.dataset.promptTab === state.activePromptTab);

  });

  document.querySelectorAll(".prompt-tab-pane").forEach((pane) => {

    pane.classList.toggle("active", pane.id === `${state.activePromptTab}PromptPane`);

  });

}



function selectPromptTab(tab) {

  state.activePromptTab = tab === "goal" ? "goal" : "task";

  renderPromptTabs();

}



function renderQueueRow(item) {

  const selectable = ["queue", "processing"].includes(item.status);

  const trace = item.prompt_id

    ? `<br>Prompt: ${escapeHtml(item.prompt_id)}${item.prompt_version ? ` | ${escapeHtml(item.prompt_version)}` : ""}${

        item.prompt_mode ? ` | ${escapeHtml(item.prompt_mode)}` : ""

      }`

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

      <td>${statusPill(item.display_status || item.status)}</td>

      <td>${renderProcessingStage(item)}</td>

      <td>${escapeHtml(item.version || "-")}</td>

      <td>${escapeHtml(formatDateTime(item.updated_at))}</td>

      <td>${renderQueueAction(item)}</td>

    </tr>

  `;

}



function renderProcessingStage(item) {

  const step = item.processing_step || defaultStepForStatus(item.status);

  const visualStep = workflowVisualStep(item);

  const label = item.processing_step_label || processingStepLabel(step);

  const visualLabel = processingStepLabel(visualStep);

  const rawLabel = label && label !== visualLabel ? `<span class="stage-raw">${displayText(label)}</span>` : "";

  const detail = item.processing_detail ? `<div class="item-meta">${displayText(item.processing_detail)}</div>` : "";

  const qa = item.qa_status

    ? `<div class="item-meta">QA: ${displayText(item.qa_status)}${

        item.qa_issues?.length ? ` | ${displayText(item.qa_issues.join(", "))}` : ""

      }</div>`

    : "";

  const checkpoint = item.checkpoint ? `<div class="item-meta">Checkpoint: ${displayText(item.checkpoint)}</div>` : "";

  const handoff = item.handoff_path ? `<div class="item-meta">Handoff: ${displayText(item.handoff_path)}</div>` : "";

  const nextSkill = item.next_skill ? `<div class="item-meta">Next skill: ${displayText(item.next_skill)}</div>` : "";

  const qualityGateKeys = item.quality_gates && typeof item.quality_gates === "object" ? Object.keys(item.quality_gates) : [];

  const gates = qualityGateKeys.length ? `<div class="item-meta">Quality gates: ${displayText(qualityGateKeys.join(", "))}</div>` : "";

  const artifacts = Array.isArray(item.artifacts) && item.artifacts.length

    ? `<div class="item-meta">Artifacts: ${escapeHtml(String(item.artifacts.length))}</div>`

    : "";

  const manifest = item.manifest_status

    ? `<div class="item-meta">Manifest: ${escapeHtml(item.manifest_status)}${item.approved_by ? ` | approved_by: ${escapeHtml(item.approved_by)}` : ""}</div>`

    : "";

  const review = item.review_status

    ? `<div class="item-meta">Review: ${escapeHtml(item.review_status)}${item.simulated_approval ? " | simulated" : ""}</div>`

    : "";

  const ragflow = item.ragflow_ingestion

    ? `<div class="item-meta">KnowledgeCore: ${displayText(typeof item.ragflow_ingestion === "string" ? item.ragflow_ingestion : JSON.stringify(item.ragflow_ingestion))}</div>`

    : "";

  return `

    <div class="stage-cell">

      <div class="stage-current">

        <span class="status stage-${escapeHtml(workflowStepClass(visualStep))}">${escapeHtml(visualLabel)}</span>

        ${rawLabel}

      </div>

      ${renderWorkflowTimeline(item)}

      ${detail}${qa}${manifest}${review}${ragflow}${checkpoint}${handoff}${nextSkill}${gates}${artifacts}

    </div>

  `;

}



function renderWorkflowOverview(items) {

  const activeCounts = items.reduce((counts, item) => {

    const step = workflowVisualStep(item);

    counts[step] = (counts[step] || 0) + 1;

    return counts;

  }, {});

  return `

    <div class="workflow-overview-rail" role="list">

      ${UPLOAD_WORKFLOW_STEPS.map((step, index) => {

        const count = activeCounts[step.id] || 0;

        const stateClass = count ? "active" : "waiting";

        return `

          <div class="workflow-overview-step ${stateClass}" role="listitem" title="${escapeHtml(step.hint)}">

            <span class="workflow-step-index">${index + 1}</span>

            <span class="workflow-step-label">${escapeHtml(step.label)}</span>

            <span class="workflow-step-count">${escapeHtml(count)}</span>

          </div>

        `;

      }).join("")}

    </div>

  `;

}



function renderAgentWorkflowMap(items) {

  const activeStep = mostCommonActiveWorkflowStep(items);

  return `

    <div class="workflow-map-header">

      <div>

        <h3>Workflow xử lý data khép kín</h3>

        <p>Agent đọc từ trái sang phải, mỗi bước tạo handoff rõ ràng cho bước kế tiếp.</p>

      </div>

      <span class="workflow-map-badge">${escapeHtml(items.length)} file trong hàng chờ</span>

    </div>

    <div class="workflow-map-lanes" role="list">

      ${AGENT_WORKFLOW_BLUEPRINT.map((node, index) => {

        const stateClass = activeStep === node.stage ? "active" : workflowStepIndex(node.stage) < workflowStepIndex(activeStep) ? "done" : "waiting";

        return `

          <article class="workflow-map-node ${stateClass}" role="listitem">

            <div class="workflow-map-node-top">

              <span class="workflow-map-order">${index + 1}</span>

              <strong>${escapeHtml(node.title)}</strong>

            </div>

            <div class="workflow-map-skill">${displayText(node.skill)}</div>

            <dl class="workflow-map-meta">

              <div><dt>Input</dt><dd>${displayText(node.input)}</dd></div>

              <div><dt>Output</dt><dd>${displayText(node.output)}</dd></div>

              <div><dt>Gate</dt><dd>${displayText(node.gate)}</dd></div>

            </dl>

          </article>

        `;

      }).join("")}

    </div>

  `;

}



function mostCommonActiveWorkflowStep(items) {

  if (!items.length) return "waiting";

  const counts = items.reduce((memo, item) => {

    const step = workflowVisualStep(item);

    memo[step] = (memo[step] || 0) + 1;

    return memo;

  }, {});

  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "waiting";

}



function renderPromptArchitecture() {

  const target = qs("#promptArchitecture");

  if (!target) return;

  const selectedMode = qs("#promptModeSelect")?.value || state.promptTemplates?.default_mode || "process_raw";

  const mode = (state.promptTemplates?.modes || []).find((item) => item.id === selectedMode);

  const packets = promptArchitecturePackets();

  target.innerHTML = `

    <div class="prompt-architecture-header">

      <div>

        <h3>Kiến trúc prompt bàn giao cho AI Agent</h3>

        <p>${displayText(mode?.label || "Task prompt")} · ${displayText(mode?.request_type || "workflow")}</p>

      </div>

      <span class="workflow-map-badge">${escapeHtml(state.promptTemplates?.prompt_version || "agent-task-v3")}</span>

    </div>

    <div class="prompt-packet-grid">

      ${packets.map((packet) => `

        <section class="prompt-packet">

          <strong>${displayText(packet.title)}</strong>

          ${packet.purpose ? `<p>${displayText(packet.purpose)}</p>` : ""}

          <ul>

            ${packet.items.map((item) => `<li>${displayText(item)}</li>`).join("")}

          </ul>

        </section>

      `).join("")}

    </div>

  `;

}



function promptArchitecturePackets() {

  const backendPackets = state.promptTemplates?.prompt_architecture;

  if (!Array.isArray(backendPackets) || !backendPackets.length) return PROMPT_PACKET_BLUEPRINT;

  return backendPackets.map((packet) => ({

    title: packetTitle(packet.packet),

    purpose: packet.purpose || "",

    items: Array.isArray(packet.fields) ? packet.fields : [],

  }));

}



function packetTitle(packetId) {

  const value = String(packetId || "packet").replace(/_/g, " ");

  return value.charAt(0).toUpperCase() + value.slice(1);

}



function renderWorkflowTimeline(item) {

  const activeStep = workflowVisualStep(item);

  const history = workflowHistorySteps(item);

  const activeIndex = workflowStepIndex(activeStep);

  const terminalException = WORKFLOW_EXCEPTION_STEPS.has(activeStep);

  return `

    <div class="workflow-rail" role="list" aria-label="Workflow xử lý data">

      ${UPLOAD_WORKFLOW_STEPS.map((step, index) => {

        const stateClass = workflowTimelineState(step.id, index, activeStep, activeIndex, history, terminalException);

        return `

          <span class="workflow-step ${stateClass}" role="listitem" title="${escapeHtml(step.label)} - ${escapeHtml(step.hint)}">

            <span class="workflow-step-dot" aria-hidden="true"></span>

            <span class="workflow-step-label">${escapeHtml(step.label)}</span>

          </span>

        `;

      }).join("")}

    </div>

  `;

}



function workflowTimelineState(stepId, index, activeStep, activeIndex, history, terminalException) {

  if (stepId === activeStep) {

    return activeStep === "failed" ? "failed active" : "active";

  }

  if (history.has(stepId) || (!terminalException && activeIndex > index)) {

    return "done";

  }

  return "waiting";

}



function workflowVisualStep(item) {

  const rawStep = item.processing_step || defaultStepForStatus(item.status);

  if (item.status === "done") return "done";

  if (item.status === "ocr_required") return "ocr_required";

  if (item.status === "failed") return "failed";

  return normalizeWorkflowStep(rawStep);

}



function workflowStepClass(step) {

  const aliases = {

    mineru_convert: "hyperscribe",

    rag_ready: "knowledge_ready",

  };

  return aliases[step] || step;

}



function workflowHistorySteps(item) {

  const steps = new Set();

  (item.processing_history || []).forEach((event) => {

    const step = normalizeWorkflowStep(event.step);

    if (step) {

      steps.add(step);

    }

  });

  return steps;

}



function normalizeWorkflowStep(step) {

  const key = String(step || "").trim();

  return WORKFLOW_STEP_ALIASES[key] || key || "waiting";

}



function workflowStepIndex(step) {

  return UPLOAD_WORKFLOW_STEPS.findIndex((candidate) => candidate.id === step);

}



function renderQueueAction(item) {

  if (item.display_status === "approved") {

    return `<span class="item-meta">Sẵn sàng đồng bộ KnowledgeCore</span>`;

  }

  if (item.display_status === "pending_review") {

    return `<span class="item-meta">Waiting for human review</span>`;

  }

  if (item.display_status === "failed_review") {

    return `<span class="item-meta">${displayText(item.processing_detail || "Cần AI agent sửa lại")}</span>`;

  }

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

    return `<span class="item-meta">${displayText(item.error || "Xem lỗi")}</span>`;

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

    approved: "\u0110\u00e3 duy\u1ec7t",

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

    classify: "Phân loại",

    check_service: "Kiểm tra dịch vụ",

    submit: "Gửi xử lý",

    queue: "Vào hàng chờ",

    parse: "Phân tích",

    download: "Tải kết quả",

    extract_artifacts: "Trích artifact",

    build_outputs: "Dựng đầu ra",

    mineru_convert: "HyperScribeModel convert",

    compare_sources: "So sánh nguồn",

    preclean: "Pre-clean",

    domain_agent: "Domain agent",

    handoff_check: "Handoff check",

    qa: "Kiểm tra QA",

    repair_loop: "Repair loop",

    rag_ready: "Knowledge-ready",

    review: "Human review",

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

    ragflow: "Chỉ KnowledgeCore",

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



function percentFormat(val) {

  if (val === null || val === undefined) return "-";

  const num = Number(val);

  if (Number.isNaN(num)) return val;

  return `${Math.round(num * 100)}%`;

}



function gapReasonLabel(reason) {

  const labels = {

    no_active_source: "Không tìm thấy nguồn tài liệu",

    out_of_active_engineering_scope: "Ngoài phạm vi tài liệu kỹ thuật",

    user_feedback_correct: "Đánh giá Đúng (Cần xác nhận lại)",

    user_feedback_wrong_source: "Phản hồi: Sai nguồn thông tin",

    user_feedback_no_answer: "Phản hồi: Chatbot không trả lời được",

    ragflow_answer_missing_citation: "Thiếu trích dẫn (KnowledgeCore)",

    ragflow_error: "Lỗi kết nối KnowledgeCore",

    ragflow_not_configured: "KnowledgeCore chưa được cấu hình",

    ragflow_not_configured_local_fallback_disabled: "KnowledgeCore lỗi/chưa cấu hình (Local Fallback tắt)",

    ragflow_error_local_fallback_disabled: "Lỗi KnowledgeCore (Local Fallback tắt)",

  };

  if (!reason) return "Khoảng trống chưa xác định";

  if (reason.startsWith("user_feedback_")) {

    const feedbackType = reason.replace("user_feedback_", "");

    return labels[reason] || `Phản hồi tiêu cực: ${feedbackType}`;

  }

  return labels[reason] || reason;

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



function bindInspectorButtons(container, detail) {

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

  const openReaderBtn = container.querySelector("#openReaderBtn");

  if (openReaderBtn && detail) {

    openReaderBtn.addEventListener("click", () => {

      openMarkdownReader(detail);

    });

  }

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



function renderSourcePreview(source) {

  if (!source?.exists) {

    return `<div class="empty compact-empty">Không tìm thấy file gốc để đối chiếu.</div>`;

  }

  const kind = source.kind || "binary";

  if (kind === "pdf") {

    return `

      <iframe

        class="source-preview-iframe"

        title="File PDF gốc"

        src="${escapeHtml(source.file_url || "")}"

      ></iframe>

    `;

  }

  if (kind === "image") {

    return `<img class="source-preview-image" src="${escapeHtml(source.file_url || "")}" alt="File gốc" />`;

  }

  if (kind === "excel") {

    return renderExcelPreview(source.excel || {});

  }

  if (kind === "text") {

    const content = source.text?.content || "";

    const lines = content.split(/\r?\n/).slice(0, 500).map((line, index) => ({

      line: index + 1,

      text: line,

      highlight: false,

    }));

    return renderReadableMarkdownViewer(lines);

  }

  return `

    <div class="review-alert info">

      <strong>File gốc không render trực tiếp</strong>

      <span>${escapeHtml(source.file_name || source.path || "Nguồn")} có thể mở bằng ứng dụng phù hợp trên máy.</span>

    </div>

  `;

}



function renderExcelPreview(excel) {

  if (excel.error) {

    return `<div class="review-alert warning"><strong>Không đọc được XLSX</strong><span>${escapeHtml(excel.error)}</span></div>`;

  }

  const sheets = excel.sheets || [];

  if (!sheets.length) {

    return `<div class="empty compact-empty">Không có bảng preview trong file Excel.</div>`;

  }



  // Render tabs

  const tabsHtml = sheets.map((sheet, index) => {

    const activeClass = index === 0 ? "active" : "";

    return `<button type="button" class="excel-tab-btn ${activeClass}" data-sheet-index="${index}">${escapeHtml(sheet.name)}</button>`;

  }).join("");



  // Render sheet tables

  const tablesHtml = sheets.map((sheet, index) => {

    const hiddenAttr = index === 0 ? "" : "hidden";

    if (!sheet.rows?.length) {

      return `

        <div class="excel-sheet-pane" data-sheet-index="${index}" ${hiddenAttr}>

          <div class="empty compact-empty">Không có dữ liệu trong sheet ${escapeHtml(sheet.name)}.</div>

        </div>

      `;

    }

    return `

      <div class="excel-sheet-pane" data-sheet-index="${index}" ${hiddenAttr}>

        <div class="excel-preview-scroll">

          <table class="excel-preview-table">

            <tbody>

              ${sheet.rows.map((row) => `

                <tr>

                  ${row.map((cell) => `<td>${escapeHtml(cell || "")}</td>`).join("")}

                </tr>

              `).join("")}

            </tbody>

          </table>

        </div>

        ${sheet.truncated ? `<div class="item-meta warning" style="margin-top: 4px;">* Dữ liệu chỉ hiển thị 40 dòng đầu tiên của sheet.</div>` : ""}

      </div>

    `;

  }).join("");



  return `

    <div class="excel-preview">

      <div class="excel-tabs">

        ${tabsHtml}

      </div>

      <div class="excel-panes">

        ${tablesHtml}

      </div>

    </div>

  `;

}



function renderSourceCompare(detail) {

  const source = detail.source_preview || {};

  const markdown = detail.markdown || {};

  const downloadUrl = `/api/documents/${encodeURIComponent(detail.doc_id)}/${encodeURIComponent(detail.version)}/source-file`;

  return `

    <div class="source-compare-grid">

      <section class="source-compare-pane">

        <div class="source-compare-heading">

          <strong>File gốc</strong>

          <span>${escapeHtml(source.file_name || source.path || "-")}</span>

          ${source.exists ? `

            <a href="${downloadUrl}" class="button secondary compact" download style="text-decoration: none; margin-left: auto; display: inline-flex; align-items: center; gap: 4px;">

              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">

                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>

                <polyline points="7 10 12 15 17 10"></polyline>

                <line x1="12" y1="15" x2="12" y2="3"></line>

              </svg>

              Tải file gốc

            </a>

          ` : ""}

        </div>

        <div class="source-preview-frame">${renderSourcePreview(source)}</div>

      </section>

      <section class="source-compare-pane">

        <div class="source-compare-heading">

          <strong>Bản render / Markdown</strong>

          <span>${escapeHtml(markdown.path || "-")}</span>

        </div>

        <div class="source-preview-frame">${renderMarkdownPreview(markdown, null, null)}</div>

      </section>

    </div>

  `;

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



function qaDisplayStatus(detail, record) {

  const data = detail?.qa_report?.data || {};

  return data.quality_status || data.status || record?.extra?.quality_status || record?.extra?.qa_status || "-";

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

  const qaStatus = qaDisplayStatus(detail, record);

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

        <button id="openReaderBtn" class="button compact primary" type="button" style="display: inline-flex; align-items: center; gap: var(--space-1); font-weight: 600; padding: 5px 10px; height: auto; font-size: 11px; margin-right: 4px;">

          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 13px; height: 13px;"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>

          <span>Đọc tài liệu</span>

        </button>

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

      <button class="inspector-tab" type="button" data-tab="compare">Đối chiếu</button>

      <button class="inspector-tab" type="button" data-tab="markdown">Markdown</button>

      <button class="inspector-tab" type="button" data-tab="qa">Báo cáo QA</button>

      <button class="inspector-tab" type="button" data-tab="versions">Phiên bản</button>

    </div>



    <div class="inspector-section" data-section="metadata">

      <pre class="json-box compact">${jsonBlock({ manifest: record, source_metadata: metadataSidecar })}</pre>

    </div>

    <div class="inspector-section" data-section="compare" hidden>

      ${renderSourceCompare(detail)}

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

  bindInspectorButtons(target, detail);

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

    syncReviewFormFromDetail(detail);

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

  const failed = state.manifest.filter((record) => record.status === "failed_review");

  const target = qs("#pendingList");

  const failedTarget = qs("#failedReviewList");

  if (!target) return;

  if (state.selectedReviewRecord) {

    const stillInReview = [...pending, ...failed].some(

      (record) =>

        record.doc_id === state.selectedReviewRecord.doc_id

        && record.version === state.selectedReviewRecord.version,

    );

    if (!stillInReview) {

      state.selectedReviewRecord = null;

      state.selectedReviewDetail = null;

    }

  }

  if (!pending.length) {

    target.innerHTML = `<div class="empty">Không có tài liệu chờ duyệt.</div>`;

  } else {

    target.innerHTML = pending

      .map((record) => reviewQueueButton(record, "pending-pick"))

      .join("");

  }

  if (failedTarget) {

    failedTarget.innerHTML = failed.length

      ? failed.map((record) => reviewQueueButton(record, "failed-review-pick")).join("")

      : `<div class="empty compact-empty">Không có tài liệu không duyệt.</div>`;

  }

  bindReviewQueuePickers(".pending-pick", pending);

  bindReviewQueuePickers(".failed-review-pick", failed);

  renderReviewSelection();

}



function reviewQueueButton(record, className) {

  const reason = record.status_reason ? `<br>Lý do: ${escapeHtml(record.status_reason)}` : "";

  return `

    <button class="item ${className}" data-doc-id="${escapeHtml(record.doc_id)}" data-version="${escapeHtml(record.version)}" type="button">

      <div class="item-title">${escapeHtml(record.doc_id)} v${escapeHtml(record.version)}</div>

      <div class="item-meta">${escapeHtml(record.title)}<br>${escapeHtml(categoryLabel(record.category))} | ${escapeHtml(record.owner)}${reason}</div>

    </button>

  `;

}



function bindReviewQueuePickers(selector, records) {

  document.querySelectorAll(selector).forEach((button) => {

    button.addEventListener("click", () => {

      state.selectedReviewRecord = records.find(

        (record) => record.doc_id === button.dataset.docId && record.version === button.dataset.version,

      ) || null;

      state.selectedReviewDetail = null;

      renderReviewSelection();

      loadDocumentDetail(state.selectedReviewRecord, "review").catch((err) => toast(err.message));

    });

  });

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

  document.querySelectorAll(".failed-review-pick").forEach((button) => {

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

  const enabled = Boolean(record && record.status === "pending_review");

  qs("#reviewApproveBtn").disabled = !enabled;

  qs("#reviewRejectBtn").disabled = !enabled;

}



function collectReviewChecklist() {

  const checklist = {};

  document.querySelectorAll(".review-check[data-review-key]").forEach((input) => {

    checklist[input.dataset.reviewKey] = Boolean(input.checked);

  });

  return checklist;

}



function allReviewChecksPassed(checklist) {

  const values = Object.values(checklist || {});

  return values.length > 0 && values.every(Boolean);

}



function resetReviewFormInputs() {

  qs("#rejectReason").value = "";

  document.querySelectorAll(".review-check").forEach((input) => {

    input.checked = false;

  });

}



function syncReviewFormFromDetail(detail) {

  const checklist = detail?.human_review?.data?.checklist || {};

  document.querySelectorAll(".review-check[data-review-key]").forEach((input) => {

    input.checked = checklist[input.dataset.reviewKey] === true;

  });

  const reviewer = detail?.human_review?.data?.reviewer || "";

  if (reviewer && qs("#approvedBy") && !qs("#approvedBy").value) {

    qs("#approvedBy").value = reviewer;

  }

  const notes = detail?.human_review?.data?.notes || "";

  if (notes && qs("#rejectReason") && !qs("#rejectReason").value) {

    qs("#rejectReason").value = notes;

  }

}



function listLimitNote(visibleCount, totalCount) {

  if (totalCount <= visibleCount) return "";

  return `<div class="item-meta list-note">Đang hiển thị ${escapeHtml(visibleCount)} mục mới nhất trong ${escapeHtml(totalCount)} mục.</div>`;

}



function renderQuality() {

  const evaluation = state.health?.evaluation;

  const evaluationBox = qs("#evaluationBox");

  if (!evaluationBox) return;

  evaluationBox.classList.toggle("empty", !evaluation);

  evaluationBox.innerHTML = evaluation

    ? `

      <div style="display: flex; flex-direction: column; gap: var(--space-4); width: 100%;">

        <div class="item" style="border-left: 4px solid ${evaluation.pass ? 'var(--success)' : 'var(--danger)'}; background: ${evaluation.pass ? 'var(--success-soft)' : 'var(--danger-soft)'}; margin: 0; padding: var(--space-3); border-radius: var(--radius-md);">

          <div class="item-title" style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-2);">

            <strong style="color: ${evaluation.pass ? 'var(--success)' : 'var(--danger)'}; font-size: 14px;">

              ${evaluation.pass ? "✓ ĐÁNH GIÁ ĐẠT TIÊU CHUẨN" : "✗ ĐÁNH GIÁ CẦN XỬ LÝ"}

            </strong>

            <span class="status ${evaluation.pass ? 'done' : 'failed'}">

              ${evaluation.pass ? 'Đạt' : 'Lỗi'}

            </span>

          </div>

          <div class="item-meta" style="margin-top: var(--space-1); font-size: 11px; color: var(--muted-strong);">

            Bộ kiểm thử: <strong>${escapeHtml(evaluation.provider || "-")}</strong> | Hoàn tất: ${formatDateTime(evaluation.finished_at)}

          </div>

        </div>



        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-3); width: 100%;">

          <div class="bento-card bento-cyan" style="padding: var(--space-3); margin: 0; min-height: auto; align-items: center; justify-content: center; text-align: center;">

            <div style="font-size: 10px; font-weight: bold; color: var(--muted); text-transform: uppercase; margin-bottom: var(--space-1);">Top-3 Doc Hit</div>

            <div style="font-size: 18px; font-weight: 800; color: var(--primary-strong);">${percentFormat(evaluation.metrics?.top3_doc_hit_rate)}</div>

          </div>

          <div class="bento-card bento-teal" style="padding: var(--space-3); margin: 0; min-height: auto; align-items: center; justify-content: center; text-align: center;">

            <div style="font-size: 10px; font-weight: bold; color: var(--muted); text-transform: uppercase; margin-bottom: var(--space-1);">Trích dẫn</div>

            <div style="font-size: 18px; font-weight: 800; color: var(--success);">${percentFormat(evaluation.metrics?.citation_accuracy)}</div>

          </div>

          <div class="bento-card bento-orange" style="padding: var(--space-3); margin: 0; min-height: auto; align-items: center; justify-content: center; text-align: center;">

            <div style="font-size: 10px; font-weight: bold; color: var(--muted); text-transform: uppercase; margin-bottom: var(--space-1);">Không trả lời</div>

            <div style="font-size: 18px; font-weight: 800; color: var(--warning);">${percentFormat(evaluation.metrics?.no_answer_accuracy)}</div>

          </div>

          <div class="bento-card bento-blue" style="padding: var(--space-3); margin: 0; min-height: auto; align-items: center; justify-content: center; text-align: center;">

            <div style="font-size: 10px; font-weight: bold; color: var(--muted); text-transform: uppercase; margin-bottom: var(--space-1);">Trễ p95</div>

            <div style="font-size: 18px; font-weight: 800; color: #0369a1;">${evaluation.metrics?.p95_latency_ms ?? "-"} ms</div>

          </div>

        </div>

      </div>

    `

    : `<div class="empty">Chưa có lượt đánh giá. Hãy chạy bộ regression mặc định trước khi mở cho người dùng thử.</div>`;



  const visibleGaps = state.gaps.slice(0, 10);

  qs("#gapList").innerHTML = visibleGaps.length

    ? `${listLimitNote(visibleGaps.length, state.gaps.length)}

       <div class="list-select-header">

         <label>

           <input type="checkbox" id="selectAllGaps" ${visibleGaps.length > 0 && visibleGaps.every(gap => state.selectedGaps.has(gap.id)) ? 'checked' : ''} />

           Chọn tất cả (${visibleGaps.length})

         </label>

       </div>

       ${visibleGaps.map((gap) => {

         const isSelected = state.selectedGaps.has(gap.id);

         return `

           <div class="item operation-selectable ${isSelected ? 'selected' : ''}">

             <div class="checkbox-container">

               <input type="checkbox" class="operation-checkbox gap-checkbox" data-id="${gap.id}" ${isSelected ? 'checked' : ''} />

             </div>

             <div class="item-content" style="flex: 1; min-width: 0;">

               <div class="item-title" style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); width: 100%;">

                 <span style="font-weight: 700; color: var(--primary);">${escapeHtml(gapReasonLabel(gap.reason))}</span>

                 ${statusPill(gap.status)}

               </div>

               <div class="item-meta" style="margin-top: var(--space-2); width: 100%;">

                 <div style="font-size: 13px; color: var(--text); font-style: italic; border-left: 3px solid var(--primary-tint); padding-left: var(--space-2); margin-bottom: var(--space-2); word-break: break-all; white-space: pre-wrap; font-weight: 600; line-height: 1.45;">&ldquo;${escapeHtml(gap.query)}&rdquo;</div>

                 <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--muted);">

                   <span>Chủ xử lý: <strong style="color: var(--muted-strong);">${escapeHtml(gap.suggested_owner || "Phòng Kỹ thuật")}</strong></span>

                   <span>Lập lúc: ${formatDateTime(gap.created_at)}</span>

                 </div>

               </div>

             </div>

           </div>

         `;

       }).join("")}`

    : `<div class="empty">Không có khoảng trống tri thức.</div>`;



  const visibleQueries = state.queries.slice(0, 10);

  qs("#queryList").innerHTML = visibleQueries.length

    ? `${listLimitNote(visibleQueries.length, state.queries.length)}

       <div class="list-select-header">

         <label>

           <input type="checkbox" id="selectAllQueries" ${visibleQueries.length > 0 && visibleQueries.every(q => state.selectedQueries.has(q.id)) ? 'checked' : ''} />

           Chọn tất cả (${visibleQueries.length})

         </label>

       </div>

       ${visibleQueries.map((query) => {

         const isSelected = state.selectedQueries.has(query.id);

         return `

           <div class="item operation-selectable ${isSelected ? 'selected' : ''}">

             <div class="checkbox-container">

               <input type="checkbox" class="operation-checkbox query-checkbox" data-id="${query.id}" ${isSelected ? 'checked' : ''} />

             </div>

             <div class="item-content" style="flex: 1; min-width: 0;">

               <div class="item-title" style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); width: 100%;">

                 <span style="font-weight: 700;">Truy vấn #${escapeHtml(query.id)}</span>

                 <span class="status ${query.feedback ? (query.feedback === 'correct' ? 'done' : (query.feedback === 'wrong_source' ? 'warning' : 'failed')) : 'queue'}">

                   ${escapeHtml(feedbackLabel(query.feedback))}

                 </span>

               </div>

               <div class="item-meta" style="margin-top: var(--space-2); width: 100%;">

                 <div style="font-size: 13px; color: var(--text); font-style: italic; border-left: 3px solid var(--primary-tint); padding-left: var(--space-2); margin-bottom: var(--space-2); word-break: break-all; white-space: pre-wrap; font-weight: 600; line-height: 1.45;">&ldquo;${escapeHtml(query.query)}&rdquo;</div>

                 <div style="font-size: 11px; color: var(--text); background: var(--surface-soft); padding: var(--space-2); border-radius: var(--radius-sm); border: 1px solid var(--line); margin-bottom: var(--space-2); word-break: break-all; white-space: pre-wrap;"><strong>Trả lời:</strong> ${escapeHtml(query.answer)}</div>

                 <div style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: var(--space-2); font-size: 11px; color: var(--muted); margin-bottom: var(--space-3);">

                   <span>Độ trễ: <strong style="color: var(--muted-strong);">${escapeHtml(query.latency_ms)} ms</strong></span>

                   <span>Trích dẫn: <strong style="color: ${query.answer_has_citation ? 'var(--success)' : 'var(--danger)'};">${query.answer_has_citation ? "Có dẫn nguồn" : "Không dẫn nguồn"}</strong></span>

                   <span>Thời gian: ${formatDateTime(query.created_at)}</span>

                 </div>

                 <div class="button-row" style="margin-top: var(--space-2); display: flex; justify-content: space-between; align-items: center; width: 100%;">

                   <div>

                     <button class="button secondary feedback-btn${query.feedback === 'correct' ? ' active-correct' : ''}" data-id="${escapeHtml(query.id)}" data-feedback="correct" type="button" style="min-height: 28px; padding: 4px 10px; font-size: 12px;">Đúng</button>

                     <button class="button secondary feedback-btn${query.feedback === 'wrong_source' ? ' active-wrong' : ''}" data-id="${escapeHtml(query.id)}" data-feedback="wrong_source" type="button" style="min-height: 28px; padding: 4px 10px; font-size: 12px;">Sai nguồn</button>

                     <button class="button secondary feedback-btn${query.feedback === 'no_answer' ? ' active-no' : ''}" data-id="${escapeHtml(query.id)}" data-feedback="no_answer" type="button" style="min-height: 28px; padding: 4px 10px; font-size: 12px;">Không trả lời</button>

                   </div>

                   <button class="button pin-annotation-btn" data-query="${escapeHtml(query.query)}" data-answer="${escapeHtml(query.answer)}" type="button" style="min-height: 28px; padding: 4px 10px; font-size: 12px; border: 1px solid var(--success); color: var(--success); background: transparent;">Ghim câu chuẩn</button>

                 </div>

               </div>

             </div>

           </div>

         `;

       }).join("")}`

    : `<div class="empty">Chưa có log truy vấn.</div>`;



  const visibleAnnotations = state.annotations || [];

  qs("#annotationList").innerHTML = visibleAnnotations.length

    ? `${visibleAnnotations.map((ann) => `

      <div class="item">

        <div class="item-title" style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); width: 100%;">

          <span style="font-weight: 700; color: var(--success);">${escapeHtml(ann.query)}</span>

          <button class="button secondary danger delete-annotation-btn" data-id="${escapeHtml(ann.id)}" type="button" style="min-height: 24px; padding: 2px 8px; font-size: 11px; border: 1px solid var(--danger); color: var(--danger); background: transparent;">Xóa</button>

        </div>

        <div class="item-meta" style="margin-top: var(--space-2); width: 100%;">

          <div style="font-size: 12px; color: var(--text); background: var(--surface-muted); padding: var(--space-2); border-radius: var(--radius-sm); border: 1px solid var(--line); margin-bottom: var(--space-2); word-break: break-all; white-space: pre-wrap;"><strong>Trả lời ghim:</strong> ${escapeHtml(ann.annotated_answer)}</div>

          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--muted);">

            <span>Tài liệu: <strong style="color: var(--muted-strong);">${escapeHtml(ann.doc_id || "Không có")} ${ann.version ? `(v${escapeHtml(ann.version)})` : ""}</strong></span>

            <span>Ghim lúc: ${formatDateTime(ann.created_at)}</span>

          </div>

        </div>

      </div>

    `).join("")}`

    : `<div class="empty">Chưa có câu hỏi ghim chuẩn nào. Thêm câu hỏi chuẩn bằng cách bấm nút "Ghim câu chuẩn" cạnh truy vấn lỗi bên dưới.</div>`;



  document.querySelectorAll(".delete-annotation-btn").forEach((button) => {

    button.addEventListener("click", async () => {

      if (confirm("Bạn có chắc chắn muốn xóa câu hỏi ghim chuẩn này?")) {

        await api(`/api/annotations/${button.dataset.id}`, { method: "DELETE" });

        toast("Đã xóa câu hỏi chuẩn");

        await refreshAll();

      }

    });

  });



  document.querySelectorAll(".pin-annotation-btn").forEach((button) => {

    button.addEventListener("click", () => {

      openAnnotationModal(button.dataset.query, button.dataset.answer);

    });

  });



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



  // Bind Select All Gaps Checkbox

  const selectAllGapsInput = qs("#selectAllGaps");

  if (selectAllGapsInput) {

    selectAllGapsInput.addEventListener("change", (e) => {

      const checked = e.target.checked;

      visibleGaps.forEach(gap => {

        if (checked) {

          state.selectedGaps.add(gap.id);

        } else {

          state.selectedGaps.delete(gap.id);

        }

      });

      renderQuality();

      updateOperationsActionBar();

    });

  }



  // Bind Individual Gap Checkboxes

  document.querySelectorAll(".gap-checkbox").forEach(chk => {

    chk.addEventListener("change", (e) => {

      const id = Number(e.target.dataset.id);

      if (e.target.checked) {

        state.selectedGaps.add(id);

      } else {

        state.selectedGaps.delete(id);

      }

      renderQuality();

      updateOperationsActionBar();

    });

  });



  // Bind Select All Queries Checkbox

  const selectAllQueriesInput = qs("#selectAllQueries");

  if (selectAllQueriesInput) {

    selectAllQueriesInput.addEventListener("change", (e) => {

      const checked = e.target.checked;

      visibleQueries.forEach(q => {

        if (checked) {

          state.selectedQueries.add(q.id);

        } else {

          state.selectedQueries.delete(q.id);

        }

      });

      renderQuality();

      updateOperationsActionBar();

    });

  }



  // Bind Individual Query Checkboxes

  document.querySelectorAll(".query-checkbox").forEach(chk => {

    chk.addEventListener("change", (e) => {

      const id = Number(e.target.dataset.id);

      if (e.target.checked) {

        state.selectedQueries.add(id);

      } else {

        state.selectedQueries.delete(id);

      }

      renderQuality();

      updateOperationsActionBar();

    });

  });



  updateOperationsActionBar();

}



function updateOperationsActionBar() {

  const bar = qs("#operationsActionBar");

  const countEl = qs("#operationsSelectedCount");

  const buttonsGroup = qs("#operationsActionBarButtons");

  if (!bar || !countEl || !buttonsGroup) return;



  const gapCount = state.selectedGaps.size;

  const queryCount = state.selectedQueries.size;

  const runCount = state.selectedRuns.size;

  const incidentCount = state.selectedIncidents.size;

  const logCount = state.selectedLogs.size;



  const total = gapCount + queryCount + runCount + incidentCount + logCount;



  if (total === 0) {

    bar.hidden = true;

    return;

  }



  bar.hidden = false;

  countEl.textContent = total;



  let buttonsHtml = "";



  if (gapCount > 0) {

    buttonsHtml += `

      <span style="font-size: 11px; font-weight: bold; color: var(--muted); margin-right: 4px;">Khoảng trống (${gapCount}):</span>

      <button class="button compact bulk-gap-status-btn" data-status="resolved" style="background: var(--success); color: white; min-height: 28px; padding: 4px 10px; font-size: 12px; margin-right: var(--space-1);">Đã sửa</button>

      <button class="button secondary compact bulk-gap-status-btn" data-status="ignored" style="min-height: 28px; padding: 4px 10px; font-size: 12px; margin-right: var(--space-1);">Bỏ qua</button>

      <button class="button secondary danger compact bulk-gap-delete-btn" style="border-color: var(--danger); color: var(--danger); background: transparent; min-height: 28px; padding: 4px 10px; font-size: 12px;">Xóa bỏ</button>

    `;

  }



  if (queryCount > 0) {

    if (buttonsHtml) buttonsHtml += `<div style="width: 1px; height: 24px; background: var(--line); margin: 0 var(--space-2); display: inline-block; vertical-align: middle;"></div>`;

    buttonsHtml += `

      <span style="font-size: 11px; font-weight: bold; color: var(--muted); margin-right: 4px;">Truy vấn (${queryCount}):</span>

      <button class="button compact bulk-query-feedback-btn" data-feedback="correct" style="background: var(--success); color: white; min-height: 28px; padding: 4px 10px; font-size: 12px; margin-right: var(--space-1);">Đúng</button>

      <button class="button secondary compact bulk-query-feedback-btn" data-feedback="wrong_source" style="min-height: 28px; padding: 4px 10px; font-size: 12px; margin-right: var(--space-1);">Sai nguồn</button>

      <button class="button secondary compact bulk-query-feedback-btn" data-feedback="no_answer" style="min-height: 28px; padding: 4px 10px; font-size: 12px; margin-right: var(--space-1);">Không TL</button>

      <button class="button secondary danger compact bulk-query-delete-btn" style="border-color: var(--danger); color: var(--danger); background: transparent; min-height: 28px; padding: 4px 10px; font-size: 12px;">Xóa bỏ</button>

    `;

  }



  if (runCount > 0) {

    if (buttonsHtml) buttonsHtml += `<div style="width: 1px; height: 24px; background: var(--line); margin: 0 var(--space-2); display: inline-block; vertical-align: middle;"></div>`;

    buttonsHtml += `

      <span style="font-size: 11px; font-weight: bold; color: var(--muted); margin-right: 4px;">Lượt xử lý (${runCount}):</span>

      <button class="button secondary danger compact bulk-run-delete-btn" style="border-color: var(--danger); color: var(--danger); background: transparent; min-height: 28px; padding: 4px 10px; font-size: 12px;">Xóa bỏ</button>

    `;

  }



  if (incidentCount > 0) {

    if (buttonsHtml) buttonsHtml += `<div style="width: 1px; height: 24px; background: var(--line); margin: 0 var(--space-2); display: inline-block; vertical-align: middle;"></div>`;

    buttonsHtml += `

      <span style="font-size: 11px; font-weight: bold; color: var(--muted); margin-right: 4px;">Sự cố (${incidentCount}):</span>

      <button class="button compact bulk-incident-resolve-btn" data-status="resolved" style="background: var(--success); color: white; min-height: 28px; padding: 4px 10px; font-size: 12px; margin-right: var(--space-1);">Đã xử lý</button>

      <button class="button secondary compact bulk-incident-resolve-btn" data-status="ignored" style="min-height: 28px; padding: 4px 10px; font-size: 12px; margin-right: var(--space-1);">Bỏ qua</button>

      <button class="button secondary danger compact bulk-incident-delete-btn" style="border-color: var(--danger); color: var(--danger); background: transparent; min-height: 28px; padding: 4px 10px; font-size: 12px;">Xóa bỏ</button>

    `;

  }



  if (logCount > 0) {

    if (buttonsHtml) buttonsHtml += `<div style="width: 1px; height: 24px; background: var(--line); margin: 0 var(--space-2); display: inline-block; vertical-align: middle;"></div>`;

    buttonsHtml += `

      <span style="font-size: 11px; font-weight: bold; color: var(--muted); margin-right: 4px;">Nhật ký (${logCount}):</span>

      <button class="button secondary danger compact bulk-log-clear-btn" style="border-color: var(--danger); color: var(--danger); background: transparent; min-height: 28px; padding: 4px 10px; font-size: 12px;">Xóa nhật ký chẩn đoán</button>

    `;

  }



  buttonsGroup.innerHTML = buttonsHtml;



  // Bind floating action buttons

  // Gaps

  buttonsGroup.querySelectorAll(".bulk-gap-status-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      const status = btn.dataset.status;

      const ids = Array.from(state.selectedGaps);

      await api("/api/gaps/bulk-status", {

        method: "POST",

        body: JSON.stringify({ ids, status }),

      });

      toast(`Đã cập nhật trạng thái ${ids.length} khoảng trống`);

      state.selectedGaps.clear();

      await refreshAll();

    });

  });



  buttonsGroup.querySelectorAll(".bulk-gap-delete-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      if (confirm(`Bạn có chắc chắn muốn xóa ${state.selectedGaps.size} khoảng trống tri thức?`)) {

        const ids = Array.from(state.selectedGaps);

        await api("/api/gaps/bulk-delete", {

          method: "POST",

          body: JSON.stringify({ ids }),

        });

        toast(`Đã xóa ${ids.length} khoảng trống`);

        state.selectedGaps.clear();

        await refreshAll();

      }

    });

  });



  // Queries

  buttonsGroup.querySelectorAll(".bulk-query-feedback-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      const feedback = btn.dataset.feedback;

      const ids = Array.from(state.selectedQueries);

      await api("/api/queries/bulk-feedback", {

        method: "POST",

        body: JSON.stringify({ ids, feedback }),

      });

      toast(`Đã đánh giá ${ids.length} truy vấn`);

      state.selectedQueries.clear();

      await refreshAll();

    });

  });



  buttonsGroup.querySelectorAll(".bulk-query-delete-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      if (confirm(`Bạn có chắc chắn muốn xóa ${state.selectedQueries.size} log truy vấn?`)) {

        const ids = Array.from(state.selectedQueries);

        await api("/api/queries/bulk-delete", {

          method: "POST",

          body: JSON.stringify({ ids }),

        });

        toast(`Đã xóa ${ids.length} truy vấn`);

        state.selectedQueries.clear();

        await refreshAll();

      }

    });

  });



  // Ingestion runs

  buttonsGroup.querySelectorAll(".bulk-run-delete-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      if (confirm(`Bạn có chắc chắn muốn xóa ${state.selectedRuns.size} lượt xử lý dữ liệu?`)) {

        const ids = Array.from(state.selectedRuns);

        await api("/api/ingestion-runs/bulk-delete", {

          method: "POST",

          body: JSON.stringify({ ids }),

        });

        toast(`Đã xóa ${ids.length} lượt xử lý`);

        state.selectedRuns.clear();

        await refreshAll();

      }

    });

  });



  // Incidents

  buttonsGroup.querySelectorAll(".bulk-incident-resolve-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      const status = btn.dataset.status;

      const ids = Array.from(state.selectedIncidents);

      await api("/api/incidents/bulk-resolve", {

        method: "POST",

        body: JSON.stringify({ ids, status }),

      });

      toast(`Đã cập nhật ${ids.length} sự cố`);

      state.selectedIncidents.clear();

      await refreshAll();

    });

  });



  buttonsGroup.querySelectorAll(".bulk-incident-delete-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      if (confirm(`Bạn có chắc chắn muốn xóa ${state.selectedIncidents.size} sự cố?`)) {

        const ids = Array.from(state.selectedIncidents);

        await api("/api/incidents/bulk-delete", {

          method: "POST",

          body: JSON.stringify({ ids }),

        });

        toast(`Đã xóa ${ids.length} sự cố`);

        state.selectedIncidents.clear();

        await refreshAll();

      }

    });

  });



  // Diagnostics logs

  buttonsGroup.querySelectorAll(".bulk-log-clear-btn").forEach(btn => {

    btn.addEventListener("click", async () => {

      if (confirm(`Bạn có chắc chắn muốn xóa/dọn sạch các tệp nhật ký chẩn đoán đã chọn?`)) {

        const files = Array.from(state.selectedLogs);

        await api("/api/diagnostics/clear-logs", {

          method: "POST",

          body: JSON.stringify({ files }),

        });

        toast(`Đã dọn sạch các tệp nhật ký chẩn đoán`);

        state.selectedLogs.clear();

        await refreshAll();

      }

    });

  });

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

    ? `${listLimitNote(visibleIncidents.length, state.incidents.length)}

       <div class="list-select-header">

         <label>

           <input type="checkbox" id="selectAllIncidents" ${visibleIncidents.length > 0 && visibleIncidents.every(inc => state.selectedIncidents.has(inc.id)) ? 'checked' : ''} />

           Chọn tất cả (${visibleIncidents.length})

         </label>

       </div>

       ${visibleIncidents.map((incident) => {

         const isSelected = state.selectedIncidents.has(incident.id);

         return `

           <div class="item operation-selectable ${isSelected ? 'selected' : ''}" style="border-left: 4px solid ${incident.severity === 'critical' ? 'var(--danger)' : (incident.severity === 'error' ? 'var(--warning)' : 'var(--primary)')}; padding-left: var(--space-3);">

             <div class="checkbox-container">

               <input type="checkbox" class="operation-checkbox incident-checkbox" data-id="${incident.id}" ${isSelected ? 'checked' : ''} />

             </div>

             <div class="item-content" style="flex: 1; min-width: 0;">

               <div class="item-title" style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); width: 100%;">

                 <span style="font-weight: 700;">#${escapeHtml(incident.id)} - ${escapeHtml(incident.title)}</span>

                 <div style="display: flex; align-items: center; gap: var(--space-2);">

                   ${statusPill(incident.severity)}

                   ${statusPill(incident.status)}

                 </div>

               </div>

               <div class="item-meta" style="margin-top: var(--space-2); width: 100%;">

                 <div style="color: var(--muted); font-size: 11px; margin-bottom: var(--space-2);">

                   Thành phần: <strong style="color: var(--muted-strong);">${escapeHtml(incident.component)}</strong> | Lập lúc: ${formatDateTime(incident.created_at)}

                 </div>

                 <div style="font-family: var(--font-mono); font-size: 11px; background: rgba(15, 118, 110, 0.04); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: var(--space-2); margin-bottom: var(--space-2); white-space: pre-wrap; word-break: break-all;">

                   ${escapeHtml(incident.detail)}

                 </div>

                 ${incident.status === "open" ? `

                   <div class="button-row" style="margin-top: var(--space-2);">

                     <button class="button copy-incident-prompt-btn compact" data-id="${escapeHtml(incident.id)}" type="button" style="min-height: 28px; padding: 4px 10px; font-size: 12px;">Sao chép prompt sửa lỗi</button>

                     <button class="button secondary resolve-incident-btn compact" data-id="${escapeHtml(incident.id)}" type="button" style="min-height: 28px; padding: 4px 10px; font-size: 12px;">Đánh dấu đã xử lý</button>

                   </div>

                 ` : ""}

               </div>

             </div>

           </div>

         `;

       }).join("")}`

    : `<div class="empty">Không có sự cố. Dùng Chẩn đoán nếu hệ thống có biểu hiện bất thường.</div>`;



  const visibleRuns = state.runs.slice(0, 15);

  qs("#ingestionList").innerHTML = visibleRuns.length

    ? `${listLimitNote(visibleRuns.length, state.runs.length)}

       <div class="list-select-header">

         <label>

           <input type="checkbox" id="selectAllRuns" ${visibleRuns.length > 0 && visibleRuns.every(run => state.selectedRuns.has(run.id)) ? 'checked' : ''} />

           Chọn tất cả (${visibleRuns.length})

         </label>

       </div>

       ${visibleRuns.map((run) => {

         const isSelected = state.selectedRuns.has(run.id);

         return `

           <div class="item operation-selectable ${isSelected ? 'selected' : ''}">

             <div class="checkbox-container">

               <input type="checkbox" class="operation-checkbox run-checkbox" data-id="${run.id}" ${isSelected ? 'checked' : ''} />

             </div>

             <div class="item-content" style="flex: 1; min-width: 0;">

               <div class="item-title" style="display: flex; align-items: center; gap: var(--space-2);">

                 ${statusPill(run.status)}

                 <span style="font-weight: 700;">${escapeHtml(run.doc_id || "N/A")}</span>

                 <span class="count-pill" style="font-size: 10px; font-weight: normal; min-width: auto; padding: 2px 6px;">v${escapeHtml(run.version || "1.0")}</span>

               </div>

               <div class="item-meta" style="margin-top: var(--space-1); font-family: var(--font-mono); font-size: 11px;">

                 <div>Mã lượt chạy: <code>${escapeHtml(run.run_id)}</code></div>

                 <div style="color: var(--muted);">${formatDateTime(run.created_at)}</div>

                 ${run.error_message ? `<div style="color: var(--danger); margin-top: var(--space-1); padding: var(--space-1) var(--space-2); border-left: 3px solid var(--danger); background: var(--danger-soft); border-radius: 2px;">Lỗi: ${escapeHtml(run.error_message)}</div>` : ""}

               </div>

             </div>

           </div>

         `;

       }).join("")}`

    : `<div class="empty">Chưa có lượt xử lý dữ liệu.</div>`;



  const runtimeLogs = state.diagnostics?.runtime_logs || [];

  qs("#diagnosticsLogList").innerHTML = runtimeLogs.length

    ? `

       <div class="list-select-header">

         <label>

           <input type="checkbox" id="selectAllLogs" ${runtimeLogs.length > 0 && runtimeLogs.every(log => state.selectedLogs.has(log.file)) ? 'checked' : ''} />

           Chọn tất cả (${runtimeLogs.length})

         </label>

       </div>

       ${runtimeLogs.map((log) => {

         const isSelected = state.selectedLogs.has(log.file);

         const filename = log.file.split(/[\\/]/).pop();

         return `

           <div class="diagnostics-log-item ${isSelected ? 'selected' : ''}">

             <details ${isSelected ? 'open' : ''}>

               <summary class="diagnostics-log-header">

                 <div class="checkbox-container" style="padding-top: 0;" onclick="event.stopPropagation();">

                   <input type="checkbox" class="operation-checkbox log-checkbox" data-file="${escapeHtml(log.file)}" ${isSelected ? 'checked' : ''} />

                 </div>

                 <span class="diagnostics-log-title">${escapeHtml(filename)} (${log.lines ? log.lines.length : 0} dòng)</span>

                 <svg class="chevron-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; transition: transform 0.25s ease; color: var(--muted);"><polyline points="6 9 12 15 18 9"></polyline></svg>

               </summary>

               <pre class="diagnostics-log-pre">${escapeHtml(log.lines && log.lines.length ? log.lines.join("\\n") : "Không có dữ liệu log.")}</pre>

             </details>

           </div>

         `;

       }).join("")}

      `

    : `<div class="empty">Không có tệp log chẩn đoán nào trong hệ thống. Hãy nhấn nút Chẩn đoán để tải danh sách logs.</div>`;

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



  // Bind Select All Incidents Checkbox

  const selectAllIncidentsInput = qs("#selectAllIncidents");

  if (selectAllIncidentsInput) {

    selectAllIncidentsInput.addEventListener("change", (e) => {

      const checked = e.target.checked;

      visibleIncidents.forEach(inc => {

        if (checked) {

          state.selectedIncidents.add(inc.id);

        } else {

          state.selectedIncidents.delete(inc.id);

        }

      });

      renderOperations();

      updateOperationsActionBar();

    });

  }



  // Bind Individual Incident Checkboxes

  document.querySelectorAll(".incident-checkbox").forEach(chk => {

    chk.addEventListener("change", (e) => {

      const id = Number(e.target.dataset.id);

      if (e.target.checked) {

        state.selectedIncidents.add(id);

      } else {

        state.selectedIncidents.delete(id);

      }

      renderOperations();

      updateOperationsActionBar();

    });

  });



  // Bind Select All Runs Checkbox

  const selectAllRunsInput = qs("#selectAllRuns");

  if (selectAllRunsInput) {

    selectAllRunsInput.addEventListener("change", (e) => {

      const checked = e.target.checked;

      visibleRuns.forEach(run => {

        if (checked) {

          state.selectedRuns.add(run.id);

        } else {

          state.selectedRuns.delete(run.id);

        }

      });

      renderOperations();

      updateOperationsActionBar();

    });

  }



  // Bind Individual Run Checkboxes

  document.querySelectorAll(".run-checkbox").forEach(chk => {

    chk.addEventListener("change", (e) => {

      const id = Number(e.target.dataset.id);

      if (e.target.checked) {

        state.selectedRuns.add(id);

      } else {

        state.selectedRuns.delete(id);

      }

      renderOperations();

      updateOperationsActionBar();

    });

  });



  // Bind Select All Logs Checkbox

  const selectAllLogsInput = qs("#selectAllLogs");

  if (selectAllLogsInput) {

    selectAllLogsInput.addEventListener("change", (e) => {

      const checked = e.target.checked;

      runtimeLogs.forEach(log => {

        if (checked) {

          state.selectedLogs.add(log.file);

        } else {

          state.selectedLogs.delete(log.file);

        }

      });

      renderOperations();

      updateOperationsActionBar();

    });

  }



  // Bind Individual Log Checkboxes

  document.querySelectorAll(".log-checkbox").forEach(chk => {

    chk.addEventListener("change", (e) => {

      const file = e.target.dataset.file;

      if (e.target.checked) {

        state.selectedLogs.add(file);

      } else {

        state.selectedLogs.delete(file);

      }

      renderOperations();

      updateOperationsActionBar();

    });

  });



  updateOperationsActionBar();

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

  return displayAlias(status.last_error || "Không kiểm tra được LLM");

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

    ragflow_config: "Cấu hình KnowledgeCore",

    ragflow_network: "Kết nối KnowledgeCore",

    mineru_available: "HyperScribeModel",

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

          <span>${displayText(status.last_error)}</span>

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

          ${status.last_error ? `<div class="review-alert warning"><strong>Lỗi</strong><span>${displayText(status.last_error)}</span></div>` : ""}

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

      label: "KnowledgeCore",

      value: ragflowReady ? "Sẵn sàng" : "Chưa sẵn sàng",

      detail: serviceText(health.ragflow?.message || (health.ragflow?.configured ? "Đã cấu hình" : "Chưa cấu hình")),

      status: ragflowReady ? "active" : "ocr_required",

    },

    {

      label: "HyperScribeModel",

      value: mineruReady ? "Sẵn sàng" : "Thiếu",

      detail: mineruReady ? "Document runtime detected" : "Document runtime missing",

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

      <div class="metric-label">${displayText(card.label)}</div>

      <div class="metric-value">${displayText(card.value)}</div>

      <div class="item-meta">${displayText(card.detail)}</div>

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

    viewName = "documents";

  }

  document.querySelectorAll(".nav-item").forEach((item) => {

    item.classList.toggle("active", item.dataset.view === viewName);

  });

  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));

  qs(`#view-${viewName}`)?.classList.add("active");

  const metrics = qs("#metrics");

  if (metrics) {

    metrics.hidden = (viewName === "chat" || viewName === "upload" || viewName === "architecture");

  }

  if (viewName === "architecture") {

    const activeTabButton = document.querySelector("[data-arch-tab].active");

    const activeTab = activeTabButton ? activeTabButton.dataset.archTab : "runtime";

    requestAnimationFrame(() => {

      renderSelectedDiagram(activeTab);

      document.querySelectorAll(".arch-desc-pane").forEach((desc) => {

        desc.classList.remove("active-desc");

      });

      const targetDesc = document.getElementById(`arch-${activeTab}-desc`);

      if (targetDesc) {

        targetDesc.classList.add("active-desc");

      }

    });

  }

  if (viewName === "operations") {

    api("/api/diagnostics?include_logs=true").then(diag => {

      state.diagnostics = diag;

      renderOperations();

    }).catch(err => console.error("Error loading diagnostics:", err));

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

  const promptMode = qs("#promptModeSelect")?.value || state.promptTemplates?.default_mode || "process_raw";

  const adminRequest = qs("#promptRequestInput")?.value?.trim() || "";

  const result = await api("/api/agent-prompts/generate", {

    method: "POST",

    body: JSON.stringify({

      relative_paths: relativePaths,

      prompt_mode: promptMode,

      admin_request: adminRequest,

    }),

  });

  state.generatedPrompt = result;

  await refreshUploadQueue();

  renderAgentPrompt(result.prompt, result);

  toast("Đã tạo prompt tác nhân");

}



async function generateAgentGoalPrompt(paths = null) {

  const relativePaths = paths || selectedQueuePaths();

  if (!relativePaths.length) {

    toast("Chọn ít nhất một file trong hàng chờ");

    return;

  }

  const result = await api("/api/agent-prompts/generate-goal", {

    method: "POST",

    body: JSON.stringify({

      relative_paths: relativePaths,

      goal_target: qs("#goalTargetInput")?.value?.trim() || null,

      branch: qs("#goalBranchInput")?.value?.trim() || state.promptTemplates?.default_goal_branch || null,

      verification: qs("#goalVerificationInput")?.value?.trim() || null,

      admin_request: qs("#goalRequestInput")?.value?.trim() || "",

    }),

  });

  state.generatedPrompt = result;

  await refreshUploadQueue();

  renderAgentPrompt(result.prompt, result);

  toast("Đã tạo GOAL prompt long-run");

}



function renderAgentPrompt(prompt, trace = null) {

  const box = qs("#agentPromptBox");

  if (box) {

    box.value = displayAlias(prompt || "");

  }

  const traceTarget = qs("#promptTrace");

  if (traceTarget) {

    if (trace?.prompt_id) {

      traceTarget.textContent = displayAlias(`prompt_id: ${trace.prompt_id} | prompt_version: ${trace.prompt_version || "-"} | prompt_mode: ${

        trace.prompt_mode || "-"

      } | so file: ${

        trace.files?.length ?? "-"

      }`);

    } else {

      traceTarget.textContent = "Chưa tạo prompt.";

    }

  }

}



async function copyPrompt(prompt = null) {

  const content = displayAlias(prompt || qs("#agentPromptBox")?.value || "");

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

  qs("#operationsClearSelectionBtn")?.addEventListener("click", () => {

    state.selectedGaps.clear();

    state.selectedQueries.clear();

    state.selectedRuns.clear();

    state.selectedIncidents.clear();

    state.selectedLogs.clear();

    renderQuality();

    renderOperations();

    updateOperationsActionBar();

    toast("Đã bỏ chọn tất cả");

  });

  ["#documentSearchInput", "#documentCategoryFilter", "#documentStatusFilter"].forEach((selector) => {

    qs(selector)?.addEventListener("input", renderManifest);

    qs(selector)?.addEventListener("change", renderManifest);

  });

  // Setup event delegation for chatHistory (delegating suggested questions, inline feedback, citation badges)

  qs("#chatHistory")?.addEventListener("click", async (event) => {

    // 1. Handle suggested question clicks

    const card = event.target.closest(".suggested-question-card");

    if (card) {

      const query = card.dataset.query;

      const input = qs("#queryInput");

      if (input) {

        input.value = query;

        qs("#chatForm").dispatchEvent(new Event("submit"));

      }

      return;

    }



    // 2. Handle inline feedback buttons

    const feedbackBtn = event.target.closest(".chat-feedback-btn");

    if (feedbackBtn) {

      const logId = feedbackBtn.dataset.logId;

      const feedback = feedbackBtn.dataset.feedback;

      if (!logId) return;

      try {

        await api("/api/feedback", {

          method: "POST",

          body: JSON.stringify({ query_log_id: Number(logId), feedback }),

        });

        toast("Đã lưu phản hồi");



        // Toggle active visual state

        const container = feedbackBtn.closest(".chat-feedback-inline");

        if (container) {

          container.querySelectorAll(".chat-feedback-btn").forEach((btn) => {

            btn.classList.remove("active");

          });

          feedbackBtn.classList.add("active");

        }

        await refreshAll();

      } catch (err) {

        toast(err.message || "Lỗi lưu phản hồi");

      }

      return;

    }



    // 3. Handle citation badge click in chat thread

    const badge = event.target.closest(".chat-citations-badge");

    if (badge) {

      const msgIndex = Number(badge.dataset.messageIndex);

      const msgData = state.chatMessagesList[msgIndex];

      if (msgData) {

        // Highlight this message bubble as active

        qs("#chatHistory").querySelectorAll(".chat-message.assistant").forEach((bubble, idx) => {

          bubble.classList.toggle("selected", idx === msgIndex);

        });

        renderCitationsList(msgData.citations);

      }

      return;

    }

  });



  // Handle Enter key inside queryInput textarea

  qs("#queryInput")?.addEventListener("keydown", (event) => {

    if (event.key === "Enter" && !event.shiftKey) {

      event.preventDefault();

      qs("#chatForm").dispatchEvent(new Event("submit"));

    }

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

  qs("#promptArchitecture")?.addEventListener("click", (event) => {

    const header = event.target.closest(".prompt-architecture-header");

    if (header) {

      qs("#promptArchitecture")?.classList.toggle("collapsed");

    }

  });

  qs("#generatePromptBtn").addEventListener("click", () => generateAgentPrompt().catch((err) => toast(err.message)));

  qs("#generateGoalPromptBtn")?.addEventListener("click", () => generateAgentGoalPrompt().catch((err) => toast(err.message)));

  qs("#goalBranchInput")?.addEventListener("input", (event) => {

    event.target.dataset.touched = "true";

  });

  document.querySelectorAll(".prompt-tab-button").forEach((button) => {

    button.addEventListener("click", () => selectPromptTab(button.dataset.promptTab));

  });

  qs("#promptModeSelect")?.addEventListener("change", renderPromptModeHelp);

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

      prompt_mode: selected[0].prompt_mode,

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



  qs("#closeAnnotationModalBtn").addEventListener("click", closeAnnotationModal);

  qs("#cancelAnnotationBtn").addEventListener("click", closeAnnotationModal);

  qs("#annotationModalOverlay").addEventListener("click", closeAnnotationModal);

  

  qs("#annotationForm").addEventListener("submit", async (event) => {

    event.preventDefault();

    const query = qs("#annotationQueryInput").value.trim();

    const annotated_answer = qs("#annotationAnswerInput").value.trim();

    const doc_id = qs("#annotationDocIdInput").value.trim() || null;

    const version = qs("#annotationVersionInput").value.trim() || null;

    

    try {

      await api("/api/annotations", {

        method: "POST",

        body: JSON.stringify({ query, annotated_answer, doc_id, version }),

      });

      toast("Đã lưu câu hỏi chuẩn thành công");

      closeAnnotationModal();

      await refreshAll();

    } catch (err) {

      toast("Lỗi: " + err.message);

    }

  });



  function openAnnotationModal(queryText = "", answerText = "") {

    qs("#annotationQueryInput").value = queryText;

    qs("#annotationAnswerInput").value = answerText;

    qs("#annotationDocIdInput").value = "";

    qs("#annotationVersionInput").value = "";

    

    qs("#annotationModalOverlay").hidden = false;

    qs("#annotationModal").hidden = false;

  }



  function closeAnnotationModal() {

    qs("#annotationModalOverlay").hidden = true;

    qs("#annotationModal").hidden = true;

  }

  qs("#syncKnowledgeBtn").addEventListener("click", async () => {

    await api("/api/sync-ragflow", { method: "POST", body: "{}" });

    toast("Đã yêu cầu đồng bộ KnowledgeCore");

    await refreshAll();

  });

  qs("#bootstrapKnowledgeBtn").addEventListener("click", async () => {

    const result = await api("/api/bootstrap-ragflow", { method: "POST", body: "{}" });

    toast(`Dataset KnowledgeCore ${result.dataset_created ? "đã tạo" : "đã tồn tại"}`);

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

function renderMarkdownText(text) {

  if (!text) return "";

  return text.split("\n").map((line) => {

    const trimmed = line.trim();

    if (!trimmed) return "<br>";

    if (trimmed.startsWith("- ")) {

      return `<li class="chat-li">${markdownInline(trimmed.substring(2))}</li>`;

    }

    if (trimmed.startsWith("* ")) {

      return `<li class="chat-li">${markdownInline(trimmed.substring(2))}</li>`;

    }

    return `<p class="chat-p">${markdownInline(line)}</p>`;

  }).join("");

}



function renderCitationsList(citations) {

  const citationsContainer = qs("#citations");

  if (!citationsContainer) return;

  citationsContainer.classList.remove("empty");

  citationsContainer.innerHTML = citations.length

    ? citations.map((citation, index) => `

      <button class="item citation-card" type="button" data-citation-index="${index}">

        <div class="item-title">${displayText(citation.title || citation.doc_id || "Nguồn")}</div>

        <div class="item-meta">

          Mã: ${displayText(citation.doc_id || "-")} | Phiên bản: ${displayText(citation.version || "-")}<br>

          ${displayText(citation.anchor_id || citation.chunk_id || "")}

        </div>

        <div class="item-meta">${displayText(citation.matched_excerpt || citation.excerpt || "")}</div>

      </button>

    `).join("")

    : `<div class="empty">Không có nguồn trích dẫn trả về.</div>`;



  citationsContainer.querySelectorAll(".citation-card").forEach((button) => {

    button.addEventListener("click", async () => {

      const citation = citations[Number(button.dataset.citationIndex)];

      try {

        await openCitationInInspector(citation);

      } catch (error) {

        toast(error.message || "Không mở được đoạn trích Markdown");

      }

    });

  });

}



  qs("#chatForm").addEventListener("submit", async (event) => {

    event.preventDefault();

    const queryInput = qs("#queryInput");

    const query = queryInput.value.trim();

    if (!query) return;



    const payload = {

      query: query,

      user_id: qs("#userIdInput")?.value || null,

      provider: qs("#providerSelect")?.value || "auto",

      use_llm: Boolean(qs("#useLlmInput")?.checked),

    };



    const chatHistory = qs("#chatHistory");

    if (!chatHistory) return;



    // Remove welcome screen if it exists

    const welcome = chatHistory.querySelector(".chat-welcome");

    if (welcome) {

      welcome.remove();

    }



    // Append User message

    const userMsg = document.createElement("div");

    userMsg.className = "chat-message user";

    userMsg.innerHTML = `

      <div class="chat-bubble">

        <p class="chat-p">${escapeHtml(query)}</p>

      </div>

      <div class="chat-message-meta">${new Date().toLocaleTimeString()}</div>

    `;

    chatHistory.appendChild(userMsg);



    // Append loading Assistant bubble

    const assistantMsg = document.createElement("div");

    assistantMsg.className = "chat-message assistant";

    assistantMsg.innerHTML = `

      <div class="chat-bubble">

        <div class="typing-indicator">

          <span></span><span></span><span></span>

        </div>

      </div>

    `;

    chatHistory.appendChild(assistantMsg);

    chatHistory.scrollTop = chatHistory.scrollHeight;



    // Clear query input

    queryInput.value = "";



    try {

      const result = await api("/api/chat", { method: "POST", body: JSON.stringify(payload) });

      state.lastQueryLogId = result.query_log_id;



      // Save result in messages history list

      if (!state.chatMessagesList) state.chatMessagesList = [];

      const msgIndex = state.chatMessagesList.length;

      state.chatMessagesList.push(result);



      // Render actual answer in assistant message

      assistantMsg.dataset.logId = result.query_log_id;

      assistantMsg.innerHTML = `

        <div class="chat-bubble">

          ${renderMarkdownText(displayAlias(result.answer))}

        </div>

        <div class="chat-message-meta">

          <span class="chat-citations-badge" data-message-index="${msgIndex}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px;margin-right:4px;vertical-align:middle;"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>${result.citations.length} nguồn trích dẫn</span>

          <div class="chat-feedback-inline">

            <button class="chat-feedback-btn" data-feedback="correct" data-log-id="${result.query_log_id}">👍</button>

            <button class="chat-feedback-btn" data-feedback="wrong_source" data-log-id="${result.query_log_id}">👎</button>

            <button class="chat-feedback-btn" data-feedback="no_answer" data-log-id="${result.query_log_id}">❓</button>

          </div>

        </div>

      `;



      // Highlight this message bubble as active

      chatHistory.querySelectorAll(".chat-message.assistant").forEach((bubble, idx) => {

        bubble.classList.toggle("selected", idx === msgIndex);

      });



      // Update citations panel

      renderCitationsList(result.citations);



      chatHistory.scrollTop = chatHistory.scrollHeight;

      await refreshAll();

    } catch (err) {

      assistantMsg.innerHTML = `

        <div class="chat-bubble" style="border-color: var(--danger); color: var(--danger); background: var(--danger-soft);">

          <p class="chat-p">${displayText(err.message || "Hệ thống đang tạm thời không sẵn sàng.")}</p>

        </div>

      `;

      renderServiceBanner({

        state: "unavailable",

        title: "Hệ thống chưa thể trả lời",

        message: displayAlias(err.message || "Vui lòng thử lại sau hoặc liên hệ kỹ thuật."),

        can_chat: false,

      });

      toast(err.message);

      chatHistory.scrollTop = chatHistory.scrollHeight;

    }

  });

  qs("#reviewForm").addEventListener("submit", async (event) => {

    event.preventDefault();

    const action = event.submitter.dataset.action;

    const doc_id = qs("#reviewDocId").value;

    const version = qs("#reviewVersion").value;

    const reason = qs("#rejectReason").value.trim();

    const reviewer = qs("#approvedBy").value.trim();

    const checklist = collectReviewChecklist();

    if (!doc_id || !version) {

      toast("Chọn tài liệu chờ duyệt trước");

      return;

    }

    if (action === "approve") {

      if (!reviewer) {

        toast("Can nhap nguoi duyet");

        qs("#approvedBy").focus();

        return;

      }

      if (!allReviewChecksPassed(checklist)) {

        toast("Can check day du checklist truoc khi duyet");

        return;

      }

      await api("/api/human-review", {

        method: "POST",

        body: JSON.stringify({ doc_id, version, review_status: "approved", reviewer, checklist, notes: reason }),

      });

      await api("/api/approve", {

        method: "POST",

        body: JSON.stringify({ doc_id, version, approved_by: reviewer }),

      });

      toast("Đã duyệt tài liệu");

    } else {

      if (!reason) {

        toast("Cần nhập lý do từ chối");

        qs("#rejectReason").focus();

        return;

      }

      await api("/api/human-review", {

        method: "POST",

        body: JSON.stringify({

          doc_id,

          version,

          review_status: "rejected",

          reviewer: reviewer || "human-reviewer",

          checklist,

          notes: reason,

        }),

      });

      await api("/api/reject", { method: "POST", body: JSON.stringify({ doc_id, version, reason }) });

      toast("Đã từ chối tài liệu");

    }

    state.selectedReviewRecord = null;

    state.selectedReviewDetail = null;

    resetReviewFormInputs();

    await refreshAll();

  });



  // Event delegation for Excel tab switching

  document.addEventListener("click", (event) => {

    const button = event.target.closest(".excel-tab-btn");

    if (!button) return;

    event.preventDefault();

    const index = button.dataset.sheetIndex;

    const container = button.closest(".excel-preview");

    if (!container) return;

    container.querySelectorAll(".excel-tab-btn").forEach((btn) => {

      btn.classList.toggle("active", btn.dataset.sheetIndex === index);

    });

    container.querySelectorAll(".excel-sheet-pane").forEach((pane) => {

      if (pane.dataset.sheetIndex === index) {

        pane.removeAttribute("hidden");

      } else {

        pane.setAttribute("hidden", "");

      }

    });

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



function initMermaid() {

  if (typeof mermaid !== 'undefined') {

    mermaid.initialize({

      startOnLoad: false,

      theme: 'neutral',

      securityLevel: 'loose',

      flowchart: {

        useWidth: true,

        htmlLabels: true

      }

    });

  }

}



let currentArchZoom = 100;



const MERMAID_DIAGRAMS = {

  runtime: `flowchart LR

    U["Người dùng nội bộ"] -->|Hỏi đáp quy trình| WEB["Dashboard UI<br/>(Application API + static UI)"]

    WEB -->|Gọi API| APP["Workflow API<br/>(Port :8088)"]

    APP -->|Truy xuất hiệu lực| RET["Tầng truy xuất (Retrieval)"]

    RET -->|Dự phòng cục bộ| LOCAL["Index JSONL cục bộ<br/>(ragflow_index/)"]

    RET -->|Truy xuất chính| RAG["KnowledgeCore technical_active<br/>(Port :9380)"]

    APP -->|Gửi Context + Câu hỏi| LLM["OpenAI-compatible LLM"]

    LLM -->|Cổng điều hướng| FREE["LLM Gateway<br/>(Port :3001)"]

    FREE -->|Miễn phí / Demo| P1["Pollinations / LLM7"]

    FREE -->|API Keys cá nhân| P2["Google / Groq / OpenRouter"]

    APP -->|Lưu nhật ký và gap| QDB["SQLite quality.db<br/>(data/poc_quality.db)"]

    APP -->|Trả về đáp án + nguồn| UI["Đáp án có trích dẫn nguồn"]

    UI --> U



    style U fill:#f9fafb,stroke:#d1d5db,stroke-width:2px,color:#111827

    style WEB fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1

    style APP fill:#e6fffa,stroke:#0f766e,stroke-width:2px,color:#0b5f59

    style RET fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#854d0e

    style LOCAL fill:#f3f4f6,stroke:#9ca3af,stroke-width:2px,color:#4b5563

    style RAG fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#166534

    style LLM fill:#f3e8ff,stroke:#7e22ce,stroke-width:2px,color:#6b21a8

    style FREE fill:#fae8ff,stroke:#c026d3,stroke-width:2px,color:#86198f

    style QDB fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b

    style UI fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1`,



  ingestion: `flowchart TD

    A["Tài liệu tải lên / Drop vào inbox/"] -->|Quét thư mục| B["AI Agent chuẩn hóa (Ingest)"]

    B -->|Tạo metadata thô| C["Lưu source/ & metadata.json"]

    C -->|Số hóa tài liệu| D["HyperScribeModel OCR (Port :8010)<br/>hoặc Native Parser"]

    D -->|Lưu trữ văn bản| E["Thư mục normalized/ (Markdown/JSON)"]

    E -->|Kiểm định 3 lớp| F["Validation Quality Gate (taxonomy, version, schema)"]

    F -->|Đưa vào hàng chờ| G["Trạng thái pending_review"]

    G -->|Đánh giá thủ công| H{"Hội đồng duyệt duyệt?"}

    H -->|Phê duyệt| I["Trạng thái active (Hiệu lực)"]

    H -->|Từ chối| J["Trạng thái failed_review"]

    I -->|Cập nhật cache| K["Index JSONL cục bộ<br/>(ragflow_index/)"]

    I -->|Đồng bộ dataset| L["KnowledgeCore dataset sync<br/>(Port :9380)"]

    I -->|Lưu trữ lịch sử| M["Lưu trữ phiên bản cũ (archived/retired)"]

    J --> B



    style A fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1

    style B fill:#e6fffa,stroke:#0f766e,stroke-width:2px,color:#0b5f59

    style D fill:#f3e8ff,stroke:#7e22ce,stroke-width:2px,color:#6b21a8

    style F fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#854d0e

    style H fill:#fef08a,stroke:#eab308,stroke-width:2px,color:#854d0e

    style I fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#166534

    style J fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b`,



  query: `sequenceDiagram
    autonumber
    actor User as Người dùng
    participant UI as Giao diện Dashboard
    participant Agent as Trợ lý AI Agent
    participant Retrieval as Bộ phận Tìm kiếm
    participant LLM as Trí tuệ Nhân tạo (LLM)
    participant DB as Nhật ký Hệ thống

    User->>UI: Đặt câu hỏi quy trình kỹ thuật
    UI->>Agent: Yêu cầu xử lý câu hỏi
    
    Note over Agent: Bước 1: Bộ lọc Phạm vi (Scope Guard)<br/>Chặn các câu hỏi không liên quan
    
    Agent->>LLM: Bước 2: Phân tích Ý định & Thực thể<br/>(Nếu thiếu thông tin, yêu cầu bổ sung)
    LLM-->>Agent: Trả về kết quả phân tích
    
    Agent->>Retrieval: Bước 3: Lập kế hoạch Tìm kiếm & Truy xuất<br/>(Chỉ tìm tài liệu đang có hiệu lực)
    Retrieval-->>Agent: Trả về các đoạn tài liệu nguồn liên quan
    
    Agent->>LLM: Bước 4: Trích xuất Bằng chứng & Soạn thảo<br/>(Tạo bản nháp theo định dạng phù hợp)
    LLM-->>Agent: Trả về bản nháp có cấu trúc
    
    Agent->>LLM: Bước 5: Kiểm duyệt & Thẩm định chéo<br/>(Verifier & Critic & Compliance Check)
    Note over Agent, LLM: Đảm bảo mọi ý kiến đều có dẫn nguồn,<br/>đúng số bước quy trình và không bịa đặt.
    LLM-->>Agent: Phê duyệt / Sửa đổi câu trả lời
    
    Agent->>DB: Ghi nhận nhật ký & Đánh giá chất lượng
    Agent-->>UI: Trả về câu trả lời có cấu trúc và dẫn nguồn
    UI-->>User: Hiển thị câu trả lời trực quan (Các bước, cảnh báo, nguồn)`,



  security: `flowchart LR

    subgraph PUBLIC["Lớp Công Cộng (Public Demo)"]

        A["Trình duyệt người dùng"] -->|HTTPS / API Token| B["Vercel API Proxy"]

    end

    subgraph TUNNEL["Đường Truyền Bảo Mật"]

        B -->|Secure HTTPS Tunnel| C["Localtunnel / Cloudflare Tunnel"]

    end

    subgraph LOCAL["Lớp Nội Bộ (Local Server Machine)"]

        C -->|X-KB-Token Auth| D["Application Backend (Port :8088)"]

        D -->|Đọc file| E["Thư mục normalized/ & manifest/"]

        D -->|Lưu logs| F["SQLite data/poc_quality.db"]

    end



    style A fill:#f9fafb,stroke:#d1d5db,stroke-width:2px,color:#111827

    style B fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1

    style C fill:#fae8ff,stroke:#c026d3,stroke-width:2px,color:#86198f

    style D fill:#e6fffa,stroke:#0f766e,stroke-width:2px,color:#0b5f59

    style E fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#166534

    style F fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b`

};



function renderSelectedDiagram(tabId) {

  const container = document.getElementById("mermaid-render-area");

  if (!container) return;



  container.innerHTML = "";

  const diagramCode = MERMAID_DIAGRAMS[tabId];

  if (!diagramCode) return;



  const pre = document.createElement("pre");

  pre.className = "mermaid";

  pre.id = "current-mermaid-pre";

  pre.textContent = diagramCode;

  container.appendChild(pre);



  if (typeof mermaid !== 'undefined') {

    mermaid.run({

      querySelector: '#current-mermaid-pre',

    }).then(() => {

      applyArchZoom();

    }).catch((err) => {

      console.error("Mermaid run error:", err);

    });

  }

}



function applyArchZoom() {

  const svg = document.querySelector("#mermaid-render-area svg");

  const display = document.getElementById("zoomLevelDisplay");

  if (display) {

    display.textContent = `${currentArchZoom}%`;

  }

  if (svg) {

    svg.style.setProperty("width", `${currentArchZoom}%`, "important");

    svg.style.setProperty("max-width", "none", "important");

    svg.style.setProperty("height", "auto", "important");

  }

}



function setupArchitectureTabs() {

  document.querySelectorAll("[data-arch-tab]").forEach((button) => {

    button.addEventListener("click", () => {

      const activeTab = button.dataset.archTab;



      // Update buttons

      document.querySelectorAll("[data-arch-tab]").forEach((btn) => {

        btn.classList.toggle("active", btn.dataset.archTab === activeTab);

      });



      // Update descriptions

      document.querySelectorAll(".arch-desc-pane").forEach((desc) => {

        desc.classList.remove("active-desc");

      });

      const targetDesc = document.getElementById(`arch-${activeTab}-desc`);

      if (targetDesc) {

        targetDesc.classList.add("active-desc");

      }



      currentArchZoom = 100;

      renderSelectedDiagram(activeTab);

    });

  });



  qs("#zoomInBtn")?.addEventListener("click", () => {

    if (currentArchZoom < 300) {

      currentArchZoom += 20;

      applyArchZoom();

    }

  });



  qs("#zoomOutBtn")?.addEventListener("click", () => {

    if (currentArchZoom > 40) {

      currentArchZoom -= 20;

      applyArchZoom();

    }

  });



  qs("#zoomResetBtn")?.addEventListener("click", () => {

    currentArchZoom = 100;

    applyArchZoom();

  });



  qs("#copyCheckpointBtn")?.addEventListener("click", () => {

    const promptText = qs("#checkpointPromptText")?.textContent || "";

    navigator.clipboard.writeText(promptText)

      .then(() => {

        toast("Đã sao chép prompt vào bộ nhớ tạm!");

      })

      .catch((err) => {

        toast("Không thể sao chép: " + err.message);

      });

  });

}



function updateArchitectureStatus(health) {

  if (!health) return;



  // 1. Inbox

  const inboxBadge = qs("#bento-inbox .bento-status-badge");

  if (inboxBadge) {

    inboxBadge.className = "bento-status-badge badge-online";

    inboxBadge.textContent = "Hoạt động";

  }



  // 2. HyperScribeModel

  const mineruBadge = qs("#bento-hyperscribe .bento-status-badge");

  if (mineruBadge) {

    const isOnline = Boolean(health.mineru?.available);

    mineruBadge.className = `bento-status-badge ${isOnline ? "badge-online" : "badge-warning"}`;

    mineruBadge.textContent = isOnline ? "Hoạt động" : "Ngoại tuyến";

  }



  // 3. Governance

  const govBadge = qs("#bento-governance .bento-status-badge");

  if (govBadge) {

    const critical = health.incidents?.critical || 0;

    const openIncidents = health.incidents?.open || 0;

    if (critical > 0) {

      govBadge.className = "bento-status-badge badge-offline";

      govBadge.textContent = `Sự cố: ${critical} CRIT`;

    } else if (openIncidents > 0) {

      govBadge.className = "bento-status-badge badge-warning";

      govBadge.textContent = `Cảnh báo: ${openIncidents} sự cố`;

    } else {

      govBadge.className = "bento-status-badge badge-online";

      govBadge.textContent = "Hoạt động";

    }

  }



  // 4. Knowledge engine

  const ragBadge = qs("#bento-knowledge .bento-status-badge");

  if (ragBadge) {

    const isOnline = Boolean(health.ragflow?.available);

    const localFallback = Boolean(health.providers?.local_fallback_enabled);

    if (isOnline) {

      ragBadge.className = "bento-status-badge badge-online";

      ragBadge.textContent = "Đồng bộ KnowledgeCore";

    } else if (localFallback) {

      ragBadge.className = "bento-status-badge badge-warning";

      ragBadge.textContent = "Dự phòng cục bộ";

    } else {

      ragBadge.className = "bento-status-badge badge-offline";

      ragBadge.textContent = "Ngoại tuyến";

    }

  }



  // 5. LLM

  const llmBadge = qs("#bento-llm .bento-status-badge");

  if (llmBadge) {

    const isConfigured = Boolean(health.llm?.configured);

    llmBadge.className = `bento-status-badge ${isConfigured ? "badge-online" : "badge-offline"}`;

    llmBadge.textContent = isConfigured ? "Sẵn sàng" : "Chưa cấu hình";

  }



  // 6. Observability

  const obsBadge = qs("#bento-observability .bento-status-badge");

  if (obsBadge) {

    obsBadge.className = "bento-status-badge badge-online";

    obsBadge.textContent = "Hoạt động";

  }

}



initMermaid();

setupMarkdownReader();

setupNavigation();

setupActions();

setupArchitectureTabs();

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



/* ==========================================================================

   Obsidian Markdown Reader Drawer Logic

   ========================================================================== */



function setupMarkdownReader() {

  const tabSingle = qs("#drawerTabSingle");

  const tabSplit = qs("#drawerTabSplit");

  const toggleWidth = qs("#drawerToggleWidthBtn");

  const closeBtn = qs("#closeDrawerBtn");

  const overlay = qs("#markdownReaderDrawerOverlay");



  if (tabSingle) {

    tabSingle.addEventListener("click", () => toggleReaderViewMode("single"));

  }

  if (tabSplit) {

    tabSplit.addEventListener("click", () => toggleReaderViewMode("split"));

  }

  if (toggleWidth) {

    toggleWidth.addEventListener("click", () => toggleReaderWidth());

  }

  if (closeBtn) {

    closeBtn.addEventListener("click", () => closeMarkdownReader());

  }

  if (overlay) {

    overlay.addEventListener("click", () => closeMarkdownReader());

  }

}



function openMarkdownReader(detail) {

  if (!detail) return;

  state.currentReaderDetail = detail;



  const overlay = qs("#markdownReaderDrawerOverlay");

  const drawer = qs("#markdownReaderDrawer");

  if (!overlay || !drawer) return;



  // Set titles

  const record = detail.record || {};

  qs("#drawerTitle").textContent = record.title || "Tài liệu không có tên";

  qs("#drawerSubtitle").textContent = record.doc_id || "-";

  qs("#drawerDocVersion").textContent = `v${record.version || "1.0"}`;



  // Update source link download button

  const sourceFileUrl = detail.source_preview?.file_url || "#";

  const sourceBtn = qs("#drawerOpenSourceBtn");

  if (sourceBtn) {

    sourceBtn.href = sourceFileUrl;

    if (!detail.source_preview?.exists) {

      sourceBtn.style.display = "none";

    } else {

      sourceBtn.style.display = "inline-flex";

    }

  }



  // Preprocess & Compile markdown to HTML

  const rawMarkdown = detail.markdown?.content || "*Tài liệu không chứa nội dung Markdown.*";

  const processed = preprocessMarkdown(rawMarkdown);

  let html = "";

  try {

    html = marked.parse(processed);

  } catch (err) {

    console.error("marked.parse error:", err);

    html = `<div class="review-alert danger"><strong>Lỗi render Markdown:</strong><span>${escapeHtml(err.message)}</span></div><pre>${escapeHtml(rawMarkdown)}</pre>`;

  }



  // Render Single View Pane

  const singleContent = qs("#drawerMarkdownContent");

  if (singleContent) {

    singleContent.innerHTML = html;

    postprocessMarkdownDOM(singleContent);

  }



  // Render Split View Panes

  const leftPaneContainer = qs("#drawerSourcePreviewContainer");

  if (leftPaneContainer) {

    leftPaneContainer.innerHTML = renderSourcePreview(detail.source_preview);

  }



  const rightPaneContent = qs("#drawerSplitMarkdownContent");

  if (rightPaneContent) {

    rightPaneContent.innerHTML = html;

    postprocessMarkdownDOM(rightPaneContent);

  }



  // Reset display styles

  toggleReaderViewMode("single");

  drawer.classList.remove("expanded");

  updateWidthIcon(false);



  // Animate slide-in

  overlay.hidden = false;

  drawer.hidden = false;

  // trigger reflow

  overlay.offsetHeight;

  drawer.offsetHeight;

  overlay.classList.add("active");

  drawer.classList.add("active");

}



function closeMarkdownReader() {

  const overlay = qs("#markdownReaderDrawerOverlay");

  const drawer = qs("#markdownReaderDrawer");

  if (!overlay || !drawer) return;



  overlay.classList.remove("active");

  drawer.classList.remove("active");



  window.setTimeout(() => {

    if (!drawer.classList.contains("active")) {

      overlay.hidden = true;

      drawer.hidden = true;

    }

  }, 400);

}



function toggleReaderViewMode(mode) {

  const tabSingle = qs("#drawerTabSingle");

  const tabSplit = qs("#drawerTabSplit");

  const paneSingle = qs("#drawerSinglePane");

  const paneSplit = qs("#drawerSplitPane");

  const drawer = qs("#markdownReaderDrawer");



  if (!tabSingle || !tabSplit || !paneSingle || !paneSplit || !drawer) return;



  if (mode === "single") {

    tabSingle.classList.add("active");

    tabSplit.classList.remove("active");

    paneSingle.classList.add("active");

    paneSplit.classList.remove("active");



    // Restore normal width if it was expanded due to split view

    if (state.wasExpandedBeforeSplit === false) {

      drawer.classList.remove("expanded");

      updateWidthIcon(false);

    }

  } else if (mode === "split") {

    tabSingle.classList.remove("active");

    tabSplit.classList.add("active");

    paneSingle.classList.remove("active");

    paneSplit.classList.add("active");



    // Remember previous state of width before auto-expanding

    state.wasExpandedBeforeSplit = drawer.classList.contains("expanded");



    // Auto-expand drawer to 85vw to ensure readable split view layout

    drawer.classList.add("expanded");

    updateWidthIcon(true);

  }

}



function toggleReaderWidth() {

  const drawer = qs("#markdownReaderDrawer");

  if (!drawer) return;



  const isCurrentlyExpanded = drawer.classList.contains("expanded");

  if (isCurrentlyExpanded) {

    drawer.classList.remove("expanded");

    updateWidthIcon(false);

  } else {

    drawer.classList.add("expanded");

    updateWidthIcon(true);

  }

}



function updateWidthIcon(isExpanded) {

  const btn = qs("#drawerToggleWidthBtn");

  if (!btn) return;



  if (isExpanded) {

    btn.innerHTML = `<svg id="drawerWidthIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="nav-icon" style="width: 14px; height: 14px;"><polyline points="4 14 10 14 10 20"></polyline><polyline points="20 10 14 10 14 4"></polyline><line x1="14" y1="10" x2="21" y2="3"></line><line x1="10" y1="14" x2="3" y2="21"></line></svg>`;

    btn.title = "Thu hẹp panel (50vw)";

  } else {

    btn.innerHTML = `<svg id="drawerWidthIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="nav-icon" style="width: 14px; height: 14px;"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>`;

    btn.title = "Mở rộng panel (85vw)";

  }

}



function preprocessMarkdown(text) {

  if (!text) return "";



  // 1. Convert ==highlight== to <mark>highlight</mark>

  text = text.replace(/==([^=]+)==/g, "<mark>$1</mark>");



  // 2. Convert [[WikiLink]] or [[WikiLink|Custom Text]]

  text = text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (match, p1, p2) => {

    const linkText = p2 ? p2 : p1;

    return `<span class="obsidian-wikilink" title="Liên kết nội bộ: ${p1.trim()}">${linkText}</span>`;

  });



  return text;

}



function postprocessMarkdownDOM(container) {

  if (!container) return;



  // 1. Process blockquotes to Obsidian Callouts

  const blockquotes = container.querySelectorAll("blockquote");

  blockquotes.forEach((bq) => {

    const firstP = bq.querySelector("p");

    if (!firstP) return;



    const htmlContent = firstP.innerHTML.trim();

    // Regex matching [!type] or [!type]- or [!type]+ followed by title text

    const match = htmlContent.match(/^\[!([a-zA-Z0-9_-]+)\]([-+])?(.*)$/i);

    if (!match) return;



    const type = match[1].toLowerCase();

    const foldSymbol = match[2]; // "-" or "+" or undefined

    const customTitle = match[3].trim();



    // Clean up first paragraph text

    firstP.innerHTML = customTitle;

    if (!firstP.innerHTML.trim()) {

      firstP.remove();

    }



    const titleText = customTitle || type.charAt(0).toUpperCase() + type.slice(1);

    const isCollapsible = foldSymbol === "-" || foldSymbol === "+";



    // Create callout shell

    const calloutEl = document.createElement(isCollapsible ? "details" : "div");

    calloutEl.className = `obsidian-callout callout-${type}`;

    if (isCollapsible && foldSymbol === "+") {

      calloutEl.setAttribute("open", "");

    }



    // Callout Header/Title

    const titleHeader = document.createElement(isCollapsible ? "summary" : "div");

    titleHeader.className = "callout-title";



    // Icon

    const iconSpan = document.createElement("span");

    iconSpan.className = "callout-icon";

    iconSpan.innerHTML = getCalloutIconSvg(type);

    titleHeader.appendChild(iconSpan);



    // Title Text

    const textSpan = document.createElement("span");

    textSpan.className = "callout-title-text";

    textSpan.textContent = titleText;

    titleHeader.appendChild(textSpan);



    // Fold Indicator

    if (isCollapsible) {

      const foldSpan = document.createElement("span");

      foldSpan.className = "callout-fold-indicator";

      foldSpan.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width: 12px; height: 12px;"><polyline points="9 18 15 12 9 6"></polyline></svg>`;

      titleHeader.appendChild(foldSpan);

    }



    calloutEl.appendChild(titleHeader);



    // Content Pane

    const contentDiv = document.createElement("div");

    contentDiv.className = "callout-content";

    while (bq.firstChild) {

      contentDiv.appendChild(bq.firstChild);

    }

    calloutEl.appendChild(contentDiv);



    // Swap blockquote with Callout element

    bq.parentNode.replaceChild(calloutEl, bq);

  });

}



function getCalloutIconSvg(type) {

  const icons = {

    note: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`,

    info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`,

    todo: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><polyline points="9 11 12 14 22 4"></polyline></svg>`,

    tip: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A5 5 0 0 0 8 8c0 1 .3 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"></path><line x1="9" y1="18" x2="15" y2="18"></line><line x1="10" y1="22" x2="14" y2="22"></line></svg>`,

    success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`,

    check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`,

    warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,

    caution: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,

    danger: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><octagon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></octagon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`,

    bug: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="2" width="8" height="14" rx="4"></rect><path d="M12 2v14M8 5h8M6 9h12M7 14h10M6 18h12"></path></svg>`,

    quote: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21c3 0 7-9 7-14a5 5 0 0 0-5-5 5 5 0 0 0-5 5c0 5 4 14 3 14zm11 0c3 0 7-9 7-14a5 5 0 0 0-5-5 5 5 0 0 0-5 5c0 5 4 14 3 14z"></path></svg>`,

    example: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>`,

  };

  return icons[type] || icons.note;

}

