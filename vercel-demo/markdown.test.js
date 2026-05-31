/**
 * Unit tests for markdown.js
 *
 * Run with the built-in Node test runner (no dependencies required):
 *   node --test
 *
 * These lock in the current rendering behaviour so future refactors of the
 * markdown parser can be verified against a known baseline.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  escapeHtml,
  parseMarkdown,
  formatInlineMarkdown,
  renderCodeBlock,
  renderMermaidWorkflow,
  getCalloutHeader,
} = require("./markdown.js");

test("escapeHtml escapes the five special characters", () => {
  assert.equal(
    escapeHtml(`<a href="x">Tom & Jerry</a>`),
    "&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry&lt;/a&gt;",
  );
});

test("escapeHtml coerces null/undefined to empty string", () => {
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
});

test("parseMarkdown returns empty string for falsy input", () => {
  assert.equal(parseMarkdown(""), "");
  assert.equal(parseMarkdown(null), "");
});

test("parseMarkdown renders headings", () => {
  assert.equal(parseMarkdown("# Title"), "<h1>Title</h1>");
  assert.equal(parseMarkdown("## Sub"), "<h2>Sub</h2>");
  assert.equal(parseMarkdown("### Deep"), "<h3>Deep</h3>");
});

test("parseMarkdown renders an unordered list and closes it", () => {
  const html = parseMarkdown("- one\n- two");
  assert.equal(
    html,
    '<ul class="markdown-ul">\n<li>one</li>\n<li>two</li>\n</ul>',
  );
});

test("parseMarkdown renders an ordered list", () => {
  const html = parseMarkdown("1. first\n2. second");
  assert.equal(
    html,
    '<ol class="markdown-ol">\n<li>first</li>\n<li>second</li>\n</ol>',
  );
});

test("parseMarkdown renders a GitHub-style callout", () => {
  const html = parseMarkdown("> [!WARNING] Be careful");
  assert.ok(html.includes('<div class="callout callout-warning">'));
  assert.ok(html.includes("Cảnh báo"));
  assert.ok(html.includes('<p class="callout-body">Be careful</p>'));
  assert.ok(html.trim().endsWith("</div>"));
});

test("parseMarkdown renders a plain blockquote", () => {
  const html = parseMarkdown("> just a quote");
  assert.ok(html.includes("<blockquote>"));
  assert.ok(html.includes("<p>just a quote</p>"));
  assert.ok(html.trim().endsWith("</blockquote>"));
});

test("parseMarkdown renders a fenced code block and escapes its content", () => {
  const html = parseMarkdown("```\n<b>x</b>\n```");
  assert.equal(html, '<pre class="markdown-code"><code>&lt;b&gt;x&lt;/b&gt;</code></pre>');
});

test("parseMarkdown closes an unterminated code block", () => {
  const html = parseMarkdown("```\nno closing fence");
  assert.ok(html.startsWith('<pre class="markdown-code"><code>'));
  assert.ok(html.includes("no closing fence"));
});

test("formatInlineMarkdown handles bold, italic, code and links", () => {
  assert.equal(formatInlineMarkdown("**b**"), "<strong>b</strong>");
  assert.equal(formatInlineMarkdown("*i*"), "<em>i</em>");
  assert.equal(formatInlineMarkdown("`c`"), "<code>c</code>");
  assert.equal(
    formatInlineMarkdown("[label](https://example.com)"),
    '<a href="https://example.com" target="_blank" rel="noopener noreferrer">label</a>',
  );
});

test("formatInlineMarkdown only links http(s) or root-relative urls", () => {
  // javascript: scheme is not matched by the link regex, so it stays literal.
  assert.equal(
    formatInlineMarkdown("[x](javascript:alert(1))"),
    "[x](javascript:alert(1))",
  );
});

test("renderCodeBlock delegates chart configs to a chart container", () => {
  const html = renderCodeBlock("chart", '{"type":"bar"}');
  assert.ok(html.includes('class="chat-chart-container"'));
  assert.ok(html.includes("data-chart-config="));
});

test("renderCodeBlock falls back to <pre> for non-json chart bodies", () => {
  const html = renderCodeBlock("chart", "not json");
  assert.equal(html, '<pre class="markdown-code"><code>not json</code></pre>');
});

test("renderMermaidWorkflow extracts node labels into a workflow diagram", () => {
  const html = renderMermaidWorkflow('flowchart TD\n  A[Start] --> B[End]');
  assert.ok(html.includes('class="workflow-diagram"'));
  assert.ok(html.includes("Start"));
  assert.ok(html.includes("End"));
});

test("renderMermaidWorkflow falls back to <pre> when no labels are found", () => {
  const html = renderMermaidWorkflow("flowchart TD");
  assert.equal(html, '<pre class="markdown-code"><code>flowchart TD</code></pre>');
});

test("getCalloutHeader returns localized title and an icon", () => {
  const html = getCalloutHeader("NOTE");
  assert.ok(html.includes("Ghi chú"));
  assert.ok(html.includes("<svg"));
});
