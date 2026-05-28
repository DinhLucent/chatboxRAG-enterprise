const state = {
  bootstrap: null,
  templateId: null,
  templateLabel: null,
  sessionId: getOrCreateStoredId("kbUserChatSessionId", "session"),
  deviceId: getOrCreateStoredId("kbUserChatDeviceId", "device"),
  sessionHasTurns: false,
  lastResponse: null,
  drawerHidden: isCompactLayout(),
  heartbeatTimer: null,
  selectedCitation: null,
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

function parseMarkdown(text) {
  if (!text) return "";
  
  // First escape HTML to prevent XSS
  const html = displayText(text);
  const lines = html.split("\n");
  const result = [];
  let inUl = false;
  let inOl = false;
  let inCode = false;
  let codeLang = "";
  let codeLines = [];
  let inBlockquote = false;
  let currentCalloutType = "";
  
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
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

    if (isMarkdownTableStart(lines, lineIndex)) {
      if (inUl) {
        result.push("</ul>");
        inUl = false;
      }
      if (inOl) {
        result.push("</ol>");
        inOl = false;
      }
      const table = collectMarkdownTable(lines, lineIndex);
      result.push(renderMarkdownTable(table.rows));
      lineIndex = table.endIndex;
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
  if (inBlockquote) {
    result.push(currentCalloutType ? "</div>" : "</blockquote>");
  }
  if (inCode) result.push(renderCodeBlock(codeLang, codeLines.join("\n")));
  
  return result.join("\n");
}

function renderStructuredAnswer(answer, formatPlan = {}, citations = []) {
  if (!answer || typeof answer !== "object") return parseMarkdown(NO_SOURCE_TEXT);
  const steps = Array.isArray(answer.steps) ? answer.steps : [];
  const responsibilities = Array.isArray(answer.responsibilities) ? answer.responsibilities : [];
  const forms = Array.isArray(answer.forms_records) ? answer.forms_records : [];
  const notes = Array.isArray(answer.notes) ? answer.notes : [];
  const sources = Array.isArray(answer.sources) ? answer.sources : [];
  const primaryFormat = formatPlan?.primary_format || answer.answer_type || "summary";
  const markdown = typeof answer.markdown === "string" ? answer.markdown.trim() : "";
  const hasDetailBlocks = Boolean(steps.length || responsibilities.length || forms.length || notes.length);
  const shouldRenderMarkdown = Boolean(
    markdown && (!hasDetailBlocks || primaryFormat === "table" || primaryFormat === "comparison_table"),
  );
  if (primaryFormat === "no_answer_card" || answer.answer_type === "no_answer") {
    return renderNoAnswerCard(answer, formatPlan);
  }
  return `
    <section class="structured-answer" data-format="${displayText(primaryFormat)}">
      ${answer.title ? `<h3>${displayText(answer.title)}</h3>` : ""}
      ${answer.summary ? `<p class="structured-summary">${displayText(answer.summary)}</p>` : ""}
      ${renderFormatBadges(primaryFormat, formatPlan)}
      ${shouldRenderWorkflowDiagram(primaryFormat, formatPlan, steps) ? renderStructuredWorkflow(steps) : ""}
      ${shouldRenderMarkdown ? renderStructuredMarkdown(markdown) : ""}
      ${steps.length ? renderStructuredSteps(steps, primaryFormat, citations) : ""}
      ${responsibilities.length ? renderStructuredList("Bộ phận phụ trách", responsibilities, citations) : ""}
      ${forms.length ? renderStructuredForms(forms, primaryFormat, citations) : ""}
      ${notes.length ? renderStructuredList("Lưu ý", notes, citations) : ""}
      ${sources.length ? renderStructuredSources(sources, citations) : parseMarkdown(answer.markdown || "")}
    </section>
  `;
}

function renderNoAnswerCard(answer, formatPlan = {}) {
  const message = answer.summary || answer.markdown || NO_SOURCE_TEXT;
  const hints = formatPlan?.render_hints || {};
  return `
    <section class="structured-answer no-answer-card" data-format="no_answer_card">
      <h3>Không có căn cứ đủ để trả lời</h3>
      <p class="structured-summary">${displayText(message)}</p>
      ${hints.show_no_answer_card ? `<p class="structured-note">Hệ thống chỉ trả lời khi có nguồn active/latest/approved.</p>` : ""}
    </section>
  `;
}

function renderStructuredMarkdown(markdown) {
  return `<div class="structured-markdown">${parseMarkdown(markdown)}</div>`;
}

function hasStructuredAnswer(answer) {
  if (!answer || typeof answer !== "object") return false;
  return Boolean(
    answer.title ||
    answer.summary ||
    answer.markdown ||
    (Array.isArray(answer.steps) && answer.steps.length) ||
    (Array.isArray(answer.sources) && answer.sources.length),
  );
}

function structuredAnswerForResult(result = {}) {
  if (hasStructuredAnswer(result.structured_answer)) {
    return result.structured_answer;
  }
  if (result.format_type === "no_answer_card") {
    return {
      answer_type: "no_answer",
      title: result.quality_decision?.decision === "scope_reject" ? "Ngoài phạm vi hỗ trợ" : "Không có căn cứ đủ để trả lời",
      summary: result.answer || NO_SOURCE_TEXT,
      steps: [],
      responsibilities: [],
      forms_records: [],
      notes: [],
      sources: [],
    };
  }
  return null;
}

function shouldRenderWorkflowDiagram(primaryFormat, formatPlan = {}, steps = []) {
  if (!Array.isArray(steps) || steps.length < 2) return false;
  const hints = formatPlan.render_hints || {};
  return Boolean(
    hints.show_mermaid_button ||
      primaryFormat === "mermaid" ||
      primaryFormat === "timeline" ||
      primaryFormat === "workflow",
  );
}

function renderStructuredWorkflow(steps) {
  return `
    <div class="workflow-diagram structured-workflow" aria-label="Sơ đồ quy trình">
      <div class="workflow-nodes">
        ${steps.map((step, index) => `
          ${index > 0 ? `<div class="workflow-arrow">↓</div>` : ""}
          <div class="workflow-node">
            <span>${displayText(step.step_no || index + 1)}</span>
            <p>${displayText(step.title || step.description || `Bước ${index + 1}`)}</p>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderFormatBadges(primaryFormat, formatPlan = {}) {
  const blocks = Array.isArray(formatPlan.secondary_blocks) ? formatPlan.secondary_blocks : [];
  const hints = formatPlan.render_hints || {};
  const badges = [primaryFormat, ...blocks.slice(0, 4)];
  if (hints.show_timeline) badges.push("timeline");
  if (hints.show_checklist_button) badges.push("checklist");
  if (hints.show_mermaid_button) badges.push("diagram-ready");
  const unique = [...new Set(badges.filter(Boolean))];
  if (!unique.length) return "";
  return `
    <div class="structured-format-badges" aria-label="Định dạng câu trả lời">
      ${unique.map((badge) => `<span>${displayText(badge)}</span>`).join("")}
    </div>
  `;
}

function renderStructuredSteps(steps, primaryFormat, citations = []) {
  const className = primaryFormat === "checklist" ? "structured-checklist" : "structured-timeline";
  const isChecklist = primaryFormat === "checklist";
  return `
    <div class="${className}">
      <h4>Các bước thực hiện</h4>
      <ol>
        ${steps.map((step) => `
          <li>
            <span class="step-index">${isChecklist ? "" : displayText(step.step_no || "")}</span>
            <div>
              <strong>${displayText(step.title || "Bước thực hiện")}</strong>
              ${step.description ? `<p>${displayText(step.description)}</p>` : ""}
              <div class="structured-item-meta">
                ${step.owner ? `<small>Phụ trách: ${displayText(step.owner)}</small>` : ""}
                ${renderAnswerSourceLink(step.source_anchor, citations)}
              </div>
            </div>
          </li>
        `).join("")}
      </ol>
    </div>
  `;
}

function renderStructuredList(title, items, citations = []) {
  return `
    <div class="structured-block">
      <h4>${displayText(title)}</h4>
      <ul>
        ${items.map((item) => `
          <li>
            <strong>${displayText(item.label || item.title || item.name || "")}</strong>
            ${item.detail ? `<span>${displayText(item.detail)}</span>` : ""}
            ${renderAnswerSourceLink(item.source_anchor, citations)}
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function renderStructuredForms(items, primaryFormat, citations = []) {
  if (primaryFormat === "table" || primaryFormat === "comparison_table") {
    return `
      <div class="structured-table-wrap">
        <h4>Hồ sơ / biểu mẫu liên quan</h4>
        <table class="structured-table">
          <thead>
            <tr>
              <th>Tên</th>
              <th>Chi tiết</th>
              <th>Nguồn</th>
            </tr>
          </thead>
          <tbody>
            ${items.map((item) => `
              <tr>
                <td>${displayText(item.label || item.title || item.name || "")}</td>
                <td>${displayText(item.detail || "")}</td>
                <td>${renderAnswerSourceLink(item.source_anchor, citations)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }
  return renderStructuredList("Hồ sơ / biểu mẫu liên quan", items, citations);
}

function renderStructuredSources(sources, citations = []) {
  return `
    <div class="structured-sources">
      <h4>Nguồn</h4>
      <ul>
        ${sources.map((source) => {
          const label = source.display_code || source.doc_id || "Nguồn";
          const version = source.display_version || (source.version ? `v${source.version}` : "");
          const sourceButton = renderStructuredSourceButton(source, citations);
          return `<li>${displayText(`${label} ${version}`.trim())}${source.title ? ` — ${displayText(source.title)}` : ""}${sourceButton}</li>`;
        }).join("")}
      </ul>
    </div>
  `;
}

function renderAnswerSourceLink(anchor, citations = []) {
  if (!anchor) return "";
  const index = findCitationIndex(anchor, citations);
  if (index >= 0 && canOpenCitation(citations[index])) {
    return `<button class="answer-source-link" type="button" data-citation-index="${index}">Nguồn ${index + 1}</button>`;
  }
  return `<span class="answer-source-link muted">${displayText(anchor)}</span>`;
}

function renderStructuredSourceButton(source, citations = []) {
  const index = findSourceCitationIndex(source, citations);
  if (index < 0 || !canOpenCitation(citations[index])) return "";
  return `<button class="answer-source-link" type="button" data-citation-index="${index}">Tải nguồn ${index + 1}</button>`;
}

function canOpenCitation(citation) {
  return Boolean(citation?.doc_id && citation?.version);
}

function findCitationIndex(anchor, citations = []) {
  const value = String(anchor || "").trim();
  if (!value) return -1;
  return citations.findIndex((citation) => {
    const candidates = [
      citation.anchor_id,
      citation.citation,
      citation.chunk_id,
      citation.doc_id,
      citation.display_code,
      `${citation.doc_id || ""}:${citation.version || ""}`,
      `${citation.display_code || ""}:${citation.display_version || ""}`,
    ];
    return candidates.some((candidate) => String(candidate || "").trim() === value);
  });
}

function findSourceCitationIndex(source, citations = []) {
  if (!source || typeof source !== "object") return -1;
  return citations.findIndex((citation) => {
    const sameDoc = source.doc_id && citation.doc_id && String(source.doc_id) === String(citation.doc_id);
    const sameVersion = !source.version || !citation.version || String(source.version) === String(citation.version);
    const sameCode = source.display_code && citation.display_code && String(source.display_code) === String(citation.display_code);
    return (sameDoc && sameVersion) || sameCode;
  });
}

function isMarkdownTableStart(lines, index) {
  const current = lines[index]?.trim() || "";
  const next = lines[index + 1]?.trim() || "";
  return isMarkdownTableRow(current) && /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(next);
}

function isMarkdownTableRow(line) {
  return line.includes("|") && line.replace(/\|/g, "").trim().length > 0;
}

function collectMarkdownTable(lines, startIndex) {
  const rows = [];
  let index = startIndex;
  while (index < lines.length && isMarkdownTableRow(lines[index].trim())) {
    rows.push(lines[index].trim());
    index += 1;
  }
  return { rows, endIndex: index - 1 };
}

function renderMarkdownTable(rows) {
  if (rows.length < 2) return rows.map((row) => `<p class="markdown-para">${formatInlineMarkdown(row)}</p>`).join("");
  const header = splitMarkdownTableRow(rows[0]);
  const bodyRows = rows.slice(2).map(splitMarkdownTableRow);
  return `
    <div class="markdown-table-wrap">
      <table class="markdown-table">
        <thead>
          <tr>${header.map((cell) => `<th>${formatInlineMarkdown(cell)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${bodyRows.map((row) => `<tr>${row.map((cell) => `<td>${formatInlineMarkdown(cell || " ")}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function splitMarkdownTableRow(row) {
  return row.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
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
  target.textContent = displayAlias(message);
  target.classList.add("show");
  window.setTimeout(() => target.classList.remove("show"), 2800);
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
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

function chatPayload(query) {
  const categorySelect = document.getElementById("docCategorySelect");
  const categoryValue = categorySelect ? categorySelect.value : "";
  const variables = categoryValue ? { category: categoryValue } : null;

  return {
    query,
    template_id: state.templateId,
    answer_style: qs("#answerStyle").value,
    session_id: state.sessionId,
    device_id: state.deviceId,
    use_llm: true,
    variables: variables,
  };
}

function qaAgentStreamingEnabled() {
  return Boolean(state.bootstrap?.qa_agent?.enabled && state.bootstrap?.qa_agent?.streaming);
}

async function streamChat(payload) {
  const response = await fetch("/api/user/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    const text = await response.text();
    const error = text ? JSON.parse(text) : null;
    throw new Error(error?.detail || error?.error || response.statusText);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      const parsed = parseSseEvent(rawEvent);
      if (!parsed) continue;
      if (parsed.event === "trace") {
        renderTrace(parsed.data.trace_steps || []);
        updateLoadingStepsUI(state.pendingBubble, parsed.data.trace_steps || []);
      } else if (parsed.event === "final") {
        finalResult = parsed.data.result;
      } else if (parsed.event === "error") {
        throw new Error(parsed.data.detail || "Stream error");
      }
    }
  }
  if (!finalResult) {
    throw new Error("Stream ended before final answer.");
  }
  return finalResult;
}

function parseSseEvent(rawEvent) {
  const lines = rawEvent.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLines = lines.filter((line) => line.startsWith("data:"));
  if (!dataLines.length) return null;
  try {
    return {
      event: eventLine ? eventLine.replace("event:", "").trim() : "message",
      data: JSON.parse(dataLines.map((line) => line.replace("data:", "").trimStart()).join("\n")),
    };
  } catch {
    return null;
  }
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
      (card) => {
        const isProcedure = card.template_id === "procedure_steps";
        return `
        <button
          class="welcome-card${isProcedure ? "" : " disabled"}"
          type="button"
          ${isProcedure ? "" : "disabled"}
          data-template-id="${escapeHtml(card.template_id)}"
          data-question="${escapeHtml(card.question)}"
          data-label="${escapeHtml(card.label)}"
          data-answer-style="${escapeHtml(card.answer_style || "brief")}"
        >
          <span>${displayText(card.label)}</span>
          <small>${displayText(card.question)}</small>
        </button>
        `;
      }
    )
    .join("");
  document.querySelectorAll(".welcome-card").forEach((button) => {
    if (!button.disabled) {
      button.addEventListener("click", () => selectPrompt(button));
    }
  });
  wireSpotlight(".welcome-card:not(:disabled)");
}

function renderTemplates() {
  const groups = state.bootstrap?.templates?.groups || [];
  const target = qs("#templateGroups");
  target.innerHTML = groups
    .flatMap((group) =>
      (group.templates || []).map(
        (template) => {
          const isProcedure = template.id === "procedure_steps";
          return `
          <button
            class="template-chip${isProcedure ? "" : " disabled"}"
            type="button"
            ${isProcedure ? "" : "disabled"}
            data-template-id="${escapeHtml(template.id)}"
            data-question="${escapeHtml(template.question)}"
            data-label="${escapeHtml(group.label)}"
          >
            ${displayText(group.label)}
          </button>
          `;
        }
      ),
    )
    .join("");
  document.querySelectorAll(".template-chip").forEach((button) => {
    if (!button.disabled) {
      button.addEventListener("click", () => selectPrompt(button));
    }
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
  qs("#selectedTemplate").textContent = displayAlias(state.templateLabel || "Không dùng mẫu");
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
  state.pendingBubble = pending;

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
    const payload = chatPayload(query);
    const result = qaAgentStreamingEnabled()
      ? await streamChat(payload)
      : await api("/api/user/chat", {
          method: "POST",
          body: JSON.stringify(payload),
        });
    clearInterval(loadingInterval);
    state.lastResponse = result;
    if (result.session?.session_id) {
      state.sessionId = result.session.session_id;
      localStorage.setItem("kbUserChatSessionId", state.sessionId);
    }
    state.sessionHasTurns = true;
    const structuredAnswer = structuredAnswerForResult(result);
    pending.querySelector(".message-body").innerHTML = structuredAnswer
      ? renderStructuredAnswer(structuredAnswer, result.format_plan, result.citations || [])
      : parseMarkdown(result.answer || NO_SOURCE_TEXT);
    pending.insertAdjacentHTML("beforeend", renderFeedbackActions(result.log_id || result.query_log_id));
    wireFeedback(pending);
    wireAnswerSourceLinks(pending, result.citations || []);
    hydrateCharts(pending);
    renderSources(result.citations || [], result);
    renderTrace(result.trace_steps || result.trace?.steps || [], result.trace);
    switchDrawerTab("sources");
    qs("#drawerMeta").textContent = drawerMetaLabel(result);
    qs("#queryInput").value = "";
    autoGrowTextarea();
  } catch (error) {
    clearInterval(loadingInterval);
    pending.querySelector(".message-body").textContent = displayAlias(error.message || "Hệ thống chưa sẵn sàng.");
    toast(error.message);
  } finally {
    clearInterval(loadingInterval);
    qs("#sendBtn").disabled = false;
    state.pendingBubble = null;
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

function updateLoadingStepsUI(pendingElement, traceSteps) {
  if (!pendingElement) return;
  const steps = pendingElement.querySelectorAll(".loading-step");
  if (!steps.length) return;
  
  if (Array.isArray(traceSteps) && traceSteps.length > 0) {
    steps.forEach((stepEl, idx) => {
      const traceStep = traceSteps[idx];
      if (traceStep) {
        stepEl.classList.remove("active");
        if (traceStep.status === "done") {
          stepEl.style.color = "var(--muted)";
          stepEl.style.opacity = "0.5";
          const dot = stepEl.querySelector(".loading-step-dot");
          if (dot) {
            dot.style.background = "var(--green)";
            dot.style.boxShadow = "none";
            dot.style.animation = "none";
          }
        } else if (traceStep.status === "running") {
          stepEl.classList.add("active");
        }
      }
    });
  }
}

function renderSimilarityBadge(score) {
  if (score === null || score === undefined) return "";
  let val = parseFloat(score);
  if (isNaN(val)) return "";
  let percent = val;
  if (val <= 1.0 && val >= 0.0) {
    percent = val * 100;
  }
  percent = Math.round(percent);
  let matchClass = "match-low";
  if (percent >= 80) {
    matchClass = "match-high";
  } else if (percent >= 50) {
    matchClass = "match-medium";
  }
  return `<span class="similarity-badge ${matchClass}">Độ khớp: ${percent}%</span>`;
}

function renderSources(citations, result = null) {
  const target = qs("#sourcesPanel");
  state.selectedCitation = null;
  const summaryHtml = renderEvidenceDrawerSummary(result);
  const evidenceHtml = renderEvidenceClaims(result, citations);
  if (!citations.length) {
    target.innerHTML = `
      ${summaryHtml}
      ${evidenceHtml}
      <div class="empty-state">
        Chưa có nguồn tham chiếu. Khi bạn đặt câu hỏi, tài liệu được dùng để trả lời sẽ hiển thị tại đây.
      </div>
    `;
    return;
  }
  target.innerHTML = summaryHtml + evidenceHtml + citations
    .map(
      (citation, index) => `
        <article class="source-card citation-source-card" data-citation-index="${index}">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
            <div class="source-title">${index + 1}. ${displayText(citation.title || citation.doc_id || "Nguồn")}</div>
            ${renderSimilarityBadge(citation.score)}
          </div>
          <div class="source-meta">
            ${displayText(citation.display_code || citation.doc_id || "-")} | ${displayText(citation.display_version || `v${citation.version || "-"}`)}
            ${citation.display_code && citation.doc_id ? ` | ${displayText(citation.doc_id)}` : ""}
          </div>
          <div class="source-excerpt">${displayText(citation.excerpt || "Không có đoạn trích công khai.")}</div>
          ${canOpenCitation(citation)
            ? `<a class="source-open-btn" href="${escapeHtml(publicSourceFilePath(citation))}" target="_blank" rel="noopener" download>Tải PDF gốc</a>`
            : `<button class="source-open-btn" type="button" disabled>Tải PDF gốc</button>`}
        </article>
      `,
    )
    .join("");
  wireSpotlight(".source-card");
  wireEvidenceClaimLinks(citations);
}

function renderEvidenceDrawerSummary(result) {
  if (!result || typeof result !== "object") return "";
  const evidence = result.evidence_summary || {};
  const quality = result.quality_decision || {};
  const compliance = result.procedure_compliance || {};
  const run = result.answer_run || {};
  const missing = Array.isArray(evidence.missing_evidence) ? evidence.missing_evidence : [];
  const conflicts = Array.isArray(evidence.conflicts) ? evidence.conflicts : [];
  const chips = [];
  if (result.format_type) chips.push(["Format", result.format_type]);
  if (run.intent) chips.push(["Intent", run.intent]);
  if (quality.decision) chips.push(["Critic", quality.decision]);
  if (compliance.final_decision) chips.push(["Compliance", compliance.final_decision]);
  if (evidence.selected_chunks !== undefined) chips.push(["Chunks", evidence.selected_chunks]);
  if (evidence.claim_count !== undefined) chips.push(["Claims", evidence.claim_count]);
  if (run.final_confidence !== undefined) chips.push(["Confidence", formatPercent(run.final_confidence)]);
  if (compliance.citation_coverage !== undefined) chips.push(["Citations", formatPercent(compliance.citation_coverage)]);
  if (!chips.length && !missing.length && !conflicts.length && !result.knowledge_gap_id) return "";
  return `
    <article class="source-summary-card">
      <div class="source-summary-title">Tóm tắt căn cứ</div>
      <div class="source-summary-grid">
        ${chips.map(([label, value]) => `
          <div>
            <span>${displayText(label)}</span>
            <strong>${displayText(value)}</strong>
          </div>
        `).join("")}
      </div>
      ${missing.length ? `<div class="source-summary-warning">Thiếu căn cứ: ${displayText(missing.slice(0, 4).join(", "))}</div>` : ""}
      ${conflicts.length ? `<div class="source-summary-warning">Có mâu thuẫn nguồn: ${displayText(conflicts.length)}</div>` : ""}
      ${result.knowledge_gap_id ? `<div class="source-summary-warning">Đã ghi knowledge gap: ${displayText(result.knowledge_gap_id)}</div>` : ""}
    </article>
  `;
}

function renderEvidenceClaims(result, citations = []) {
  const pack = result?.evidence_pack;
  if (!pack || typeof pack !== "object") return "";
  const claims = Array.isArray(pack.verified_evidence) ? pack.verified_evidence : [];
  const missing = Array.isArray(pack.missing_evidence) ? pack.missing_evidence : [];
  const conflicts = Array.isArray(pack.conflicts) ? pack.conflicts : [];
  if (!claims.length && !missing.length && !conflicts.length) return "";
  return `
    <article class="evidence-pack-card">
      <div class="source-summary-title">Claim đã kiểm chứng</div>
      ${claims.length ? `
        <div class="evidence-claim-list">
          ${claims.slice(0, 8).map((claim, index) => renderEvidenceClaim(claim, index, citations)).join("")}
        </div>
      ` : ""}
      ${missing.length ? renderEvidenceAlert("Thiếu bằng chứng", missing) : ""}
      ${conflicts.length ? renderEvidenceAlert("Mâu thuẫn nguồn", conflicts) : ""}
    </article>
  `;
}

function renderEvidenceClaim(claim, index, citations = []) {
  const citationIndex = findEvidenceClaimCitationIndex(claim, citations);
  const confidence = claim.confidence !== undefined ? formatPercent(claim.confidence) : "";
  const sourceLabel = [claim.doc_id, claim.version ? `v${claim.version}` : ""].filter(Boolean).join(" ");
  return `
    <div class="evidence-claim">
      <div class="evidence-claim-index">${index + 1}</div>
      <div class="evidence-claim-body">
        <p>${displayText(claim.claim || "Claim")}</p>
        <div class="evidence-claim-meta">
          ${claim.evidence_type ? `<span>${displayText(claim.evidence_type)}</span>` : ""}
          ${sourceLabel ? `<span>${displayText(sourceLabel)}</span>` : ""}
          ${confidence ? `<span>${displayText(confidence)}</span>` : ""}
          ${claim.citation ? `<span>${displayText(claim.citation)}</span>` : ""}
          ${citationIndex >= 0 && canOpenCitation(citations[citationIndex])
            ? `<button class="answer-source-link" type="button" data-citation-index="${citationIndex}">Tải nguồn ${citationIndex + 1}</button>`
            : ""}
        </div>
      </div>
    </div>
  `;
}

function renderEvidenceAlert(title, items) {
  return `
    <div class="evidence-alert">
      <strong>${displayText(title)}</strong>
      <ul>
        ${items.slice(0, 6).map((item) => `<li>${displayText(item)}</li>`).join("")}
      </ul>
    </div>
  `;
}

function findEvidenceClaimCitationIndex(claim, citations = []) {
  if (!claim || typeof claim !== "object") return -1;
  const anchorIndex = findCitationIndex(claim.citation, citations);
  if (anchorIndex >= 0) return anchorIndex;
  return citations.findIndex((citation) => {
    const sameDoc = claim.doc_id && citation.doc_id && String(claim.doc_id) === String(citation.doc_id);
    const sameVersion = !claim.version || !citation.version || String(claim.version) === String(citation.version);
    return sameDoc && sameVersion;
  });
}

function wireEvidenceClaimLinks(citations = []) {
  document.querySelectorAll(".evidence-pack-card .answer-source-link[data-citation-index]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const citation = citations[Number(button.dataset.citationIndex)];
      if (canOpenCitation(citation)) {
        await openPublicCitation(citation);
      }
    });
  });
}

function drawerMetaLabel(result = {}) {
  const count = result.citations?.length || 0;
  const decision = result.quality_decision?.decision || result.procedure_compliance?.final_decision || "";
  return decision ? `${count} nguồn · ${displayAlias(decision)}` : `${count} nguồn`;
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "");
  if (number <= 1) return `${Math.round(number * 100)}%`;
  return `${Math.round(number)}%`;
}

function wireAnswerSourceLinks(container, citations = []) {
  container.querySelectorAll(".answer-source-link[data-citation-index]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const index = Number(button.dataset.citationIndex);
      const citation = citations[index];
      if (!canOpenCitation(citation)) return;
      ensureDrawerVisible();
      switchDrawerTab("sources");
      await openPublicCitation(citation);
    });
  });
}

function publicSourceFilePath(citation) {
  return `/api/user/documents/${encodeURIComponent(citation.doc_id)}/${encodeURIComponent(citation.version)}/source-file`;
}

function publicCitationPath(citation) {
  const base = `/api/user/documents/${encodeURIComponent(citation.doc_id)}/${encodeURIComponent(citation.version)}/citation`;
  if (citation.anchor_id) {
    return `${base}/${encodeURIComponent(citation.anchor_id)}`;
  }
  const params = new URLSearchParams();
  if (citation.excerpt) {
    params.set("excerpt", citation.excerpt);
  }
  return params.toString() ? `${base}?${params}` : base;
}

async function openPublicCitation(citation) {
  const target = qs("#sourcesPanel");
  state.selectedCitation = citation;
  qs("#citationPreviewPanel")?.remove();
  target.insertAdjacentHTML("beforeend", `<div id="citationPreviewPanel" class="citation-preview-card">Đang chuẩn bị tài liệu gốc...</div>`);
  try {
    const payload = await api(publicCitationPath(citation));
    renderCitationPreview(payload);
  } catch (error) {
    const panel = qs("#citationPreviewPanel");
    if (panel) {
      panel.textContent = displayAlias(error.message || "Không chuẩn bị được tài liệu gốc.");
    }
  }
}

function citationMarkdownInline(value) {
  return formatInlineMarkdown(displayText(value));
}

function citationLineRange(lines) {
  if (!lines.length) return "";
  const first = lines[0].line;
  const last = lines[lines.length - 1].line;
  return first === last ? String(first) : `${first}-${last}`;
}

function isCitationTableSeparator(line) {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(String(line || "").trim());
}

function isCitationTableRow(line) {
  const trimmed = String(line || "").trim();
  return trimmed.includes("|") && !trimmed.startsWith("```");
}

function isCitationHtmlTableStart(line) {
  return /<\s*table(?:\s|>)/i.test(String(line || ""));
}

function isCitationHtmlTableEnd(line) {
  return /<\s*\/\s*table\s*>/i.test(String(line || ""));
}

function splitCitationTableRow(line) {
  return String(line || "")
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderCitationTableBlock(rows) {
  const visibleRows = rows.filter((line) => !isCitationTableSeparator(line.text));
  if (!visibleRows.length) return "";
  const hasHeader = rows.length > 1 && isCitationTableSeparator(rows[1].text);
  const header = hasHeader ? visibleRows[0] : null;
  const bodyRows = hasHeader ? visibleRows.slice(1) : visibleRows;
  const highlighted = rows.some((line) => line.highlight);
  const anchor = rows.find((line) => line.anchor_id)?.anchor_id || "";
  return `
    <div
      class="citation-markdown-line citation-table-block ${highlighted ? "highlight" : ""}"
      data-line="${escapeHtml(citationLineRange(rows))}"
      ${anchor ? `data-anchor-id="${escapeHtml(anchor)}"` : ""}
    >
      <span>${escapeHtml(citationLineRange(rows))}</span>
      <div class="citation-markdown-content">
        <table class="citation-markdown-table">
          ${header ? `<thead><tr>${splitCitationTableRow(header.text).map((cell) => `<th>${citationMarkdownInline(cell)}</th>`).join("")}</tr></thead>` : ""}
          <tbody>
            ${bodyRows
              .map(
                (row) => `
                  <tr class="${row.highlight ? "row-highlight" : ""}">
                    ${splitCitationTableRow(row.text).map((cell) => `<td>${citationMarkdownInline(cell)}</td>`).join("")}
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

function citationSpanAttr(value) {
  const parsed = Number.parseInt(String(value || "1"), 10);
  if (!Number.isFinite(parsed) || parsed <= 1) return "";
  return String(Math.min(parsed, 50));
}

function citationHtmlCellText(node) {
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

function citationHtmlCellContent(node) {
  return displayText(citationHtmlCellText(node) || " ").replace(/\n/g, "<br>");
}

function renderSafeCitationHtmlTable(table) {
  const rows = Array.from(table.rows || []);
  if (!rows.length) return "";
  return `
    <table class="citation-markdown-table citation-html-table">
      <tbody>
        ${rows
          .map((row) => {
            const cells = Array.from(row.cells || []);
            return `
              <tr>
                ${cells
                  .map((cell) => {
                    const tag = cell.tagName?.toLowerCase() === "th" ? "th" : "td";
                    const rowspan = citationSpanAttr(cell.getAttribute("rowspan"));
                    const colspan = citationSpanAttr(cell.getAttribute("colspan"));
                    const attrs = `${rowspan ? ` rowspan="${rowspan}"` : ""}${colspan ? ` colspan="${colspan}"` : ""}`;
                    return `<${tag}${attrs}>${citationHtmlCellContent(cell)}</${tag}>`;
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

function renderCitationHtmlTableBlock(lines) {
  const source = lines.map((line) => line.text || "").join("\n");
  const highlighted = lines.some((line) => line.highlight);
  const anchor = lines.find((line) => line.anchor_id)?.anchor_id || "";
  let tableHtml = "";
  try {
    const doc = new DOMParser().parseFromString(source, "text/html");
    const tables = Array.from(doc.querySelectorAll("table"));
    tableHtml = tables.map(renderSafeCitationHtmlTable).join("");
  } catch {
    tableHtml = "";
  }
  if (!tableHtml.trim()) {
    tableHtml = `<p>${displayText(source.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() || " ")}</p>`;
  }
  return `
    <div
      class="citation-markdown-line citation-table-block citation-html-table-block ${highlighted ? "highlight" : ""}"
      data-line="${escapeHtml(citationLineRange(lines))}"
      ${anchor ? `data-anchor-id="${escapeHtml(anchor)}"` : ""}
    >
      <span>${escapeHtml(citationLineRange(lines))}</span>
      <div class="citation-markdown-content">${tableHtml}</div>
    </div>
  `;
}

function renderCitationCodeBlock(lines) {
  const highlighted = lines.some((line) => line.highlight);
  const anchor = lines.find((line) => line.anchor_id)?.anchor_id || "";
  const code = lines
    .filter((line) => !String(line.text || "").trim().startsWith("```"))
    .map((line) => line.text)
    .join("\n");
  return `
    <div
      class="citation-markdown-line citation-code-block ${highlighted ? "highlight" : ""}"
      data-line="${escapeHtml(citationLineRange(lines))}"
      ${anchor ? `data-anchor-id="${escapeHtml(anchor)}"` : ""}
    >
      <span>${escapeHtml(citationLineRange(lines))}</span>
      <div class="citation-markdown-content"><pre><code>${displayText(code || " ")}</code></pre></div>
    </div>
  `;
}

function renderCitationMarkdownLineContent(rawLine) {
  const trimmed = String(rawLine || "").trim();
  if (!trimmed) return '<span class="markdown-empty-line">&nbsp;</span>';
  const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
  if (heading) {
    const level = Math.min(heading[1].length + 1, 4);
    return `<h${level}>${citationMarkdownInline(heading[2])}</h${level}>`;
  }
  const unordered = trimmed.match(/^[-*]\s+(.+)$/);
  if (unordered) return `<p class="citation-list-line"><span aria-hidden="true">•</span>${citationMarkdownInline(unordered[1])}</p>`;
  const ordered = trimmed.match(/^(\d+)\.\s+(.+)$/);
  if (ordered) return `<p class="citation-list-line"><span>${escapeHtml(ordered[1])}.</span>${citationMarkdownInline(ordered[2])}</p>`;
  const quote = trimmed.match(/^>\s?(.+)$/);
  if (quote) return `<blockquote>${citationMarkdownInline(quote[1])}</blockquote>`;
  return `<p>${citationMarkdownInline(rawLine)}</p>`;
}

function renderCitationMarkdownViewer(lines) {
  const rows = Array.isArray(lines) ? lines : [];
  const html = [];
  let index = 0;
  while (index < rows.length) {
    const current = rows[index];
    const text = String(current.text || "");
    const trimmed = text.trim();
    if (isCitationHtmlTableStart(text)) {
      const tableRows = [current];
      index += 1;
      while (index < rows.length && !isCitationHtmlTableEnd(tableRows[tableRows.length - 1].text)) {
        tableRows.push(rows[index]);
        index += 1;
      }
      html.push(renderCitationHtmlTableBlock(tableRows));
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
      html.push(renderCitationCodeBlock(codeRows));
      continue;
    }
    if (isCitationTableRow(text)) {
      const tableRows = [];
      while (index < rows.length && isCitationTableRow(rows[index].text)) {
        tableRows.push(rows[index]);
        index += 1;
      }
      if (tableRows.length >= 2) {
        html.push(renderCitationTableBlock(tableRows));
        continue;
      }
      html.push(
        `<div class="citation-markdown-line citation-plain-line ${current.highlight ? "highlight" : ""}" data-line="${escapeHtml(current.line)}" ${current.anchor_id ? `data-anchor-id="${escapeHtml(current.anchor_id)}"` : ""}>
          <span>${escapeHtml(current.line)}</span>
          <div class="citation-markdown-content">${renderCitationMarkdownLineContent(text)}</div>
        </div>`,
      );
      continue;
    }
    html.push(
      `<div class="citation-markdown-line citation-plain-line ${current.highlight ? "highlight" : ""}" data-line="${escapeHtml(current.line)}" ${current.anchor_id ? `data-anchor-id="${escapeHtml(current.anchor_id)}"` : ""}>
        <span>${escapeHtml(current.line)}</span>
        <div class="citation-markdown-content">${renderCitationMarkdownLineContent(text)}</div>
      </div>`,
    );
    index += 1;
  }
  return `<div class="citation-markdown-preview citation-markdown-viewer">${html.join("")}</div>`;
}

function renderCitationPreview(payload) {
  const existing = qs("#citationPreviewPanel");
  const record = payload?.record || {};
  const citation = payload?.citation || {};
  const sourceFile = payload?.source_file || {};
  const selected = state.selectedCitation || {};
  const downloadUrl = sourceFile.download_url || (selected.doc_id && selected.version ? publicSourceFilePath(selected) : "");
  const fileName = sourceFile.file_name || "Tài liệu gốc";
  const fileKind = sourceFile.kind === "pdf" ? "PDF gốc" : "Tài liệu gốc";
  const html = `
    <div class="citation-preview-header">
      <div>
        <div class="source-title">${displayText(record.title || record.doc_id || "Tài liệu nguồn")}</div>
        <div class="source-meta">
          ${displayText(record.doc_id || selected.doc_id || "-")} | v${displayText(record.version || selected.version || "-")}
        </div>
      </div>
    </div>
    <div class="source-download-panel">
      <div>
        <strong>${displayText(fileKind)}</strong>
        <span>${displayText(fileName)}</span>
      </div>
      ${downloadUrl
        ? `<a class="source-download-btn" href="${escapeHtml(downloadUrl)}" target="_blank" rel="noopener" download>Tải xuống</a>`
        : `<button class="source-download-btn" type="button" disabled>Tải xuống</button>`}
    </div>
    ${citation.matched_excerpt
      ? `<div class="source-excerpt source-excerpt-compact">${displayText(citation.matched_excerpt)}</div>`
      : ""}
  `;
  if (existing) {
    existing.innerHTML = html;
  }
  qs("#citationPreviewPanel")?.scrollIntoView({
    block: "center",
    behavior: "smooth",
  });
}

function renderTrace(steps, trace = null) {
  const target = qs("#tracePanel");
  const rows = Array.isArray(steps) ? steps : [];
  if (!rows.length) {
    target.innerHTML = `<div class="empty-state">Chưa có quá trình xử lý.</div>`;
    return;
  }
  
  let summaryHtml = "";
  if (trace && typeof trace === "object") {
    const latency = trace.latency_ms !== undefined ? `${trace.latency_ms}ms` : "-";
    const promptTokens = trace.tokens_prompt !== undefined ? trace.tokens_prompt : "-";
    const completionTokens = trace.tokens_completion !== undefined ? trace.tokens_completion : "-";
    
    summaryHtml = `
      <article class="trace-summary-card" style="margin-bottom: 16px; border: 1px solid var(--line-strong); border-radius: var(--radius); background: var(--surface-solid); padding: 16px; box-shadow: var(--shadow-sm);">
        <div class="source-summary-title" style="font-size: 13px; font-weight: 700; color: var(--ink); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Thống kê hiệu năng</div>
        <div class="source-summary-grid" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; font-size: 11px;">
          <div>
            <span style="display: block; color: var(--muted); font-weight: 600; margin-bottom: 4px;">Độ trễ xử lý</span>
            <strong style="color: var(--ink); font-size: 13px; font-weight: 700;">${latency}</strong>
          </div>
          <div>
            <span style="display: block; color: var(--muted); font-weight: 600; margin-bottom: 4px;">Token Input</span>
            <strong style="color: var(--ink); font-size: 13px; font-weight: 700;">${promptTokens}</strong>
          </div>
          <div>
            <span style="display: block; color: var(--muted); font-weight: 600; margin-bottom: 4px;">Token Output</span>
            <strong style="color: var(--ink); font-size: 13px; font-weight: 700;">${completionTokens}</strong>
          </div>
        </div>
      </article>
    `;
  }
  
  target.innerHTML = summaryHtml + rows
    .map(
      (step) => `
        <article class="trace-step">
          <span class="trace-dot ${escapeHtml(step.status || "")}"></span>
          <div class="trace-card">
            <div class="source-title">${displayText(step.label || "Bước xử lý")}</div>
            ${step.detail ? `<div class="trace-meta">${displayText(step.detail)}</div>` : ""}
            ${renderTraceMetadata(step.metadata)}
          </div>
        </article>
      `,
    )
    .join("");
  wireSpotlight(".trace-card");
}

function renderTraceMetadata(metadata) {
  if (!metadata || typeof metadata !== "object") return "";
  const rows = [];
  if (Array.isArray(metadata.queries) && metadata.queries.length) {
    rows.push(["Queries", metadata.queries.slice(0, 6).join(" | ")]);
  }
  if (Array.isArray(metadata.datasets) && metadata.datasets.length) {
    rows.push(["Datasets", `${metadata.datasets.length} allowlisted`]);
  }
  if (Array.isArray(metadata.filters) && metadata.filters.length) {
    rows.push(["Filters", metadata.filters.join(", ")]);
  }
  if (metadata.selected_chunks !== undefined) {
    rows.push(["Evidence", `${metadata.selected_chunks} chunks`]);
  }
  if (metadata.claim_count !== undefined) {
    rows.push(["Claims", `${metadata.claim_count}`]);
  }
  if (Array.isArray(metadata.required_evidence) && metadata.required_evidence.length) {
    rows.push(["Evidence types", metadata.required_evidence.slice(0, 5).join(", ")]);
  }
  if (Array.isArray(metadata.missing_evidence) && metadata.missing_evidence.length) {
    rows.push(["Missing", metadata.missing_evidence.slice(0, 5).join(", ")]);
  }
  if (Array.isArray(metadata.conflicts) && metadata.conflicts.length) {
    rows.push(["Conflicts", metadata.conflicts.length]);
  }
  if (metadata.quality_decision?.decision) {
    rows.push(["Critic", metadata.quality_decision.decision]);
  }
  if (metadata.answer_run?.stage) {
    rows.push(["Run stage", metadata.answer_run.stage]);
  }
  if (metadata.answer_run?.final_confidence !== undefined) {
    rows.push(["Confidence", formatPercent(metadata.answer_run.final_confidence)]);
  }
  if (metadata.context?.context_used !== undefined) {
    rows.push(["Memory", metadata.context.context_used ? "context used" : "standalone"]);
  }
  if (metadata.citation_count !== undefined) {
    rows.push(["Citations", `${metadata.citation_count}`]);
  }
  if (metadata.procedure_compliance?.final_decision) {
    rows.push(["Compliance", metadata.procedure_compliance.final_decision]);
  }
  if (metadata.procedure_compliance?.citation_coverage !== undefined) {
    rows.push(["Citation coverage", `${metadata.procedure_compliance.citation_coverage}`]);
  }
  if (metadata.format_plan?.primary_format) {
    rows.push(["Planned format", metadata.format_plan.primary_format]);
  }
  if (Array.isArray(metadata.format_plan?.secondary_blocks) && metadata.format_plan.secondary_blocks.length) {
    rows.push(["Blocks", metadata.format_plan.secondary_blocks.join(", ")]);
  }
  if (metadata.answer_verification?.final_action) {
    rows.push(["Verification", metadata.answer_verification.final_action]);
  }
  if (metadata.format_type) {
    rows.push(["Format", metadata.format_type]);
  }
  if (!rows.length) return "";
  return `
    <dl class="trace-details">
      ${rows.map(([label, value]) => `<div><dt>${displayText(label)}</dt><dd>${displayText(value)}</dd></div>`).join("")}
    </dl>
  `;
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

function syncSidebar() {
  const sidebar = qs("#chatSidebar");
  const shell = qs(".user-shell");
  const isHidden = sidebar.classList.contains("hidden");
  shell.classList.toggle("sidebar-open", !isHidden);
}

function ensureDrawerVisible() {
  state.drawerHidden = false;
  syncDrawer();
}

function resetChat() {
  state.sessionId = createId("session");
  localStorage.setItem("kbUserChatSessionId", state.sessionId);
  state.sessionHasTurns = false;
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
        <div class="welcome-badge">Hệ thống tri thức Quy trình Phương Đông</div>
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
  // Lazy: không gửi heartbeat cho session chưa có tin nhắn
}

async function sendHeartbeat() {
  // Chỉ gửi heartbeat cho session đã có ít nhất 1 tin nhắn
  if (!state.sessionHasTurns) return {};
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
    if (!state.sessionHasTurns) return;
    const payload = JSON.stringify({ session_id: state.sessionId, device_id: state.deviceId });
    navigator.sendBeacon?.("/api/user/session/heartbeat", new Blob([payload], { type: "application/json" }));
  });
}

async function loadHistorySessions() {
  const panel = qs("#historyList");
  if (!panel) return;
  panel.innerHTML = `<div class="loading-indicator-wrapper" style="padding: 20px; justify-content: center;"><div class="modern-loading-spinner"></div></div>`;
  try {
    const sessions = await api(`/api/user/sessions?device_id=${encodeURIComponent(state.deviceId)}`);
    if (!sessions || !sessions.length) {
      panel.innerHTML = `
        <div class="history-empty">
          <svg class="history-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          <p>Chưa có lịch sử trò chuyện nào trên thiết bị này.</p>
        </div>
      `;
      return;
    }
    panel.innerHTML = sessions.map(session => {
      const activeClass = session.session_id === state.sessionId ? " active" : "";
      const dateText = formatDateTime(session.last_seen_at);
      const title = session.title || "Cuộc trò chuyện mới";
      return `
        <div class="history-card${activeClass}" data-session-id="${escapeHtml(session.session_id)}">
          <div class="history-card-header">
            <div class="history-card-title">${escapeHtml(title)}</div>
            <button class="history-card-delete" type="button" title="Xóa lịch sử" data-session-id="${escapeHtml(session.session_id)}">
              <svg style="width: 14px; height: 14px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
              </svg>
            </button>
          </div>
          <div class="history-card-meta">
            <span>${escapeHtml(dateText)}</span>
          </div>
        </div>
      `;
    }).join("");

    panel.querySelectorAll(".history-card").forEach(card => {
      card.addEventListener("click", (e) => {
        if (e.target.closest(".history-card-delete")) return;
        const sessionId = card.dataset.sessionId;
        restoreSession(sessionId);
      });
    });

    panel.querySelectorAll(".history-card-delete").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const sessionId = btn.dataset.sessionId;
        if (confirm("Bạn có chắc chắn muốn xóa cuộc trò chuyện này?")) {
          try {
            await api(`/api/user/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
            toast("Đã xóa cuộc trò chuyện");
            if (sessionId === state.sessionId) {
              resetChat();
            } else {
              loadHistorySessions();
            }
          } catch (err) {
            toast(err.message);
          }
        }
      });
    });

  } catch (err) {
    panel.innerHTML = `<div class="history-empty"><p style="color: var(--red-alert);">Lỗi khi tải lịch sử: ${escapeHtml(err.message)}</p></div>`;
  }
}

async function restoreSession(sessionId) {
  try {
    const turns = await api(`/api/user/sessions/${encodeURIComponent(sessionId)}/turns`);
    state.sessionId = sessionId;
    localStorage.setItem("kbUserChatSessionId", sessionId);
    state.sessionHasTurns = turns && turns.length > 0;
    
    document.querySelectorAll(".history-card").forEach(card => {
      card.classList.toggle("active", card.dataset.sessionId === sessionId);
    });

    const messagesContainer = qs("#messages");
    messagesContainer.innerHTML = "";
    
    if (!turns || !turns.length) {
      resetChat();
      return;
    }

    turns.forEach(turn => {
      appendMessage("user", escapeHtml(turn.query));
      const msgEl = appendMessage("assistant", parseMarkdown(turn.answer));
      if (turn.query_log_id) {
        msgEl.insertAdjacentHTML("beforeend", renderFeedbackActions(turn.query_log_id));
        wireFeedback(msgEl);
      }
    });
    
    state.templateId = null;
    state.templateLabel = null;
    qs("#selectedTemplate").textContent = "Không dùng mẫu";
    document.querySelectorAll(".template-chip").forEach((item) => item.classList.remove("active"));
    
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    if (isCompactLayout()) {
      qs("#chatSidebar")?.classList.add("hidden");
      syncSidebar();
    }
  } catch (err) {
    toast("Lỗi khi khôi phục cuộc trò chuyện: " + err.message);
  }
}

async function init() {
  window.addEventListener("mousemove", (e) => {
    document.body.style.setProperty("--global-mouse-x", `${e.clientX}px`);
    document.body.style.setProperty("--global-mouse-y", `${e.clientY}px`);
  });

  qs("#chatForm").addEventListener("submit", submitChat);
  qs("#newChatBtn").addEventListener("click", resetChat);
  qs("#historyBtn")?.addEventListener("click", () => {
    const sidebar = qs("#chatSidebar");
    sidebar.classList.toggle("hidden");
    syncSidebar();
    if (!sidebar.classList.contains("hidden")) {
      loadHistorySessions();
    }
  });
  qs("#closeSidebarBtn")?.addEventListener("click", () => {
    qs("#chatSidebar")?.classList.add("hidden");
    syncSidebar();
  });
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

  renderSources([]);
  renderTrace([]);
  try {
    state.bootstrap = await api("/api/user/bootstrap");
    renderBootstrap();
    // Kiểm tra session hiện tại đã có nội dung chưa để quyết định heartbeat
    try {
      const existingTurns = await api(`/api/user/sessions/${encodeURIComponent(state.sessionId)}/turns`);
      state.sessionHasTurns = existingTurns && existingTurns.length > 0;
    } catch (_) {
      state.sessionHasTurns = false;
    }
    startHeartbeat();
  } catch (error) {
    qs("#statusText").textContent = "Lỗi";
    qs("#railStatus").className = "rail-status bad";
    toast(error.message);
  }
  syncDrawer();
  syncSidebar();
}

init();
