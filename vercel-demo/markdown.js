/**
 * markdown.js
 *
 * Markdown -> HTML rendering for the chat answer area, extracted from app.js.
 * Pure functions (string in -> string out), no DOM access, so they can be
 * unit-tested in isolation.
 *
 * Loading model: this file is a CLASSIC script loaded BEFORE app.js in
 * index.html. Top-level function declarations become globals, so app.js keeps
 * calling escapeHtml / parseMarkdown / formatInlineMarkdown directly with no
 * call-site changes. A guarded module.exports at the bottom enables Node tests.
 */

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

// Node/CommonJS export for unit tests. Guarded so the browser classic-script
// load path is unaffected (module is undefined there).
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    escapeHtml,
    parseMarkdown,
    formatInlineMarkdown,
    renderCodeBlock,
    renderMermaidWorkflow,
    getCalloutHeader,
  };
}
