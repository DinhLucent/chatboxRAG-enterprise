from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .utils import utc_now, write_json


SMOKE_DIR = Path("data") / "qa_agent_eval"
SMOKE_HTML = Path(".runtime") / "user-chat-render-smoke.html"
SMOKE_SCREENSHOT = SMOKE_DIR / "user-chat-render-smoke.png"
SMOKE_REPORT = SMOKE_DIR / "user-chat-render-smoke.json"


def run_user_chat_render_smoke(root: Path, *, browser_path: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    browser = Path(browser_path) if browser_path else find_browser()
    report: dict[str, Any] = {
        "started_at": utc_now(),
        "browser": str(browser) if browser else None,
        "screenshot": str((root / SMOKE_SCREENSHOT).resolve()),
        "pass": False,
        "skipped": False,
        "checks": {},
    }
    if not browser:
        report.update({"skipped": True, "reason": "No Chrome/Edge executable found."})
        write_json(root / SMOKE_REPORT, report)
        return report

    html_path = root / SMOKE_HTML
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_harness_html(root), encoding="utf-8")
    screenshot_path = root / SMOKE_SCREENSHOT
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    profile_dir = root / ".runtime" / "browser-smoke-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--disable-crash-reporter",
        "--disable-breakpad",
        "--disable-features=Crashpad",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--allow-file-access-from-files",
        f"--user-data-dir={profile_dir}",
        "--window-size=1440,1000",
        "--virtual-time-budget=3000",
        f"--screenshot={screenshot_path}",
        "--dump-dom",
        html_path.as_uri(),
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    dom = completed.stdout or ""
    checks = {
        "browser_exit_ok": completed.returncode == 0,
        "ready_marker_ok": 'data-smoke-ready="true"' in dom,
        "structured_answer_ok": "structured-answer" in dom and 'data-contract="answer_blocks.v1"' in dom,
        "table_ok": "markdown-table" in dom,
        "workflow_ok": "answer-block workflow" in dom and "structured-workflow" in dom,
        "decision_matrix_ok": "answer-block decision-matrix" in dom,
        "source_summary_ok": "source-summary-card" in dom,
        "trace_ok": "trace-details" in dom,
        "evidence_claim_ok": "evidence-pack-card" in dom and "evidence-claim" in dom,
        "citation_download_ok": (
            "citation-preview-card" in dom
            and "source-download-panel" in dom
            and "source-download-btn" in dom
            and "/api/user/documents/KT-QT-CTX/1.0/source-file" in dom
        ),
        "screenshot_ok": screenshot_path.exists() and screenshot_path.stat().st_size > 10_000,
    }
    report.update(
        {
            "finished_at": utc_now(),
            "returncode": completed.returncode,
            "stderr_tail": (completed.stderr or "")[-1200:],
            "checks": checks,
            "pass": all(checks.values()),
        }
    )
    write_json(root / SMOKE_REPORT, report)
    return report


def find_browser() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    return next((path for path in candidates if path.exists()), None)


def render_harness_html(root: Path) -> str:
    css_uri = (root / "poc_workflow" / "static" / "user" / "user-chat.css").resolve().as_uri()
    js_uri = (root / "poc_workflow" / "static" / "user" / "user-chat.js").resolve().as_uri()
    bootstrap = {
        "service_status": {"state": "ok", "can_chat": True},
        "templates": {"groups": []},
        "welcome_cards": [],
        "answer_styles": [
            {"id": "brief", "label": "Ngan gon"},
            {"id": "steps", "label": "Tung buoc"},
            {"id": "checklist", "label": "Checklist"},
            {"id": "workflow", "label": "Workflow"},
        ],
        "policy": {"debug_visible": False, "summary": []},
        "qa_agent": {"enabled": True, "streaming": True, "trace_visibility": "detailed_safe_rationale"},
        "ui": {"default_drawer_tab": "sources", "show_policy_debug": False},
    }
    result = sample_result_payload()
    table_result = sample_table_result_payload()
    citation_preview = sample_public_citation_payload()
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>User Chat Render Smoke</title>
  <link rel="stylesheet" href="{css_uri}" />
</head>
<body>
  <div class="user-shell">
    <aside class="rail" aria-label="Dieu huong">
      <div class="rail-brand"><span class="brand-text">DL Knowledge</span></div>
      <div class="rail-nav">
        <button id="newChatBtn" class="rail-button active" type="button">Moi</button>
        <button id="toggleDrawerBtn" class="rail-button" type="button">Nguon</button>
      </div>
      <div class="rail-status" id="railStatus"><span id="statusText">Dang ket noi</span></div>
    </aside>
    <main class="chat-main">
      <header class="chat-header"><div class="header-content"><h1>Tro ly Tri thuc phong Ky thuat</h1><div id="assistantLine" class="assistant-line"></div></div></header>
      <section id="templateGroups" class="template-groups"></section>
      <section id="messages" class="messages" aria-live="polite"><div id="welcomeState" class="welcome-state"></div></section>
      <form id="chatForm" class="composer">
        <div class="composer-container">
          <select id="answerStyle" class="answer-style-select"><option value="brief">Brief</option><option value="workflow">Workflow</option></select>
          <textarea id="queryInput" rows="1"></textarea>
          <div class="composer-actions"><div id="selectedTemplate" class="selected-template"></div><button id="sendBtn" class="send-button" type="submit">Gui</button></div>
        </div>
      </form>
    </main>
    <aside id="sourceDrawer" class="source-drawer" aria-label="Nguon va qua trinh">
      <div class="drawer-header"><div class="drawer-header-content"><h2>Can cu tham chieu</h2><span id="drawerMeta"></span></div><button id="closeDrawerBtn" type="button">An</button></div>
      <div class="drawer-tabs"><button class="drawer-tab active" data-tab="sources" type="button">Tai lieu nguon</button><button class="drawer-tab" data-tab="trace" type="button">Qua trinh truy xuat</button></div>
      <section id="sourcesPanel" class="drawer-panel active"></section>
      <section id="tracePanel" class="drawer-panel"></section>
    </aside>
  </div>
  <div id="toast" class="toast"></div>
  <script>
    const bootstrapPayload = {json.dumps(bootstrap, ensure_ascii=False)};
    const sampleResult = {json.dumps(result, ensure_ascii=False)};
    const sampleTableResult = {json.dumps(table_result, ensure_ascii=False)};
    const sampleCitationPreview = {json.dumps(citation_preview, ensure_ascii=False)};
    window.fetch = async function(url, options) {{
      const text = String(url);
      if (text.includes("/api/user/bootstrap")) {{
        return new Response(JSON.stringify(bootstrapPayload), {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
      }}
      if (text.includes("/api/user/session/heartbeat")) {{
        return new Response(JSON.stringify({{ session_id: "smoke-session" }}), {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
      }}
      if (text.includes("/api/user/documents/")) {{
        return new Response(JSON.stringify(sampleCitationPreview), {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
      }}
      return new Response(JSON.stringify({{ detail: "not mocked" }}), {{ status: 404, headers: {{ "Content-Type": "application/json" }} }});
    }};
  </script>
  <script src="{js_uri}"></script>
  <script>
    window.addEventListener("load", () => {{
      window.setTimeout(() => {{
        const structured = structuredAnswerForResult(sampleResult);
        const message = appendMessage("assistant", renderStructuredAnswer(structured, sampleResult.format_plan, sampleResult.citations));
        wireAnswerSourceLinks(message, sampleResult.citations);
        const tableStructured = structuredAnswerForResult(sampleTableResult);
        const tableMessage = appendMessage("assistant", renderStructuredAnswer(tableStructured, sampleTableResult.format_plan, sampleTableResult.citations));
        wireAnswerSourceLinks(tableMessage, sampleTableResult.citations);
        renderSources(sampleResult.citations, sampleResult);
        renderTrace(sampleResult.trace_steps);
        document.querySelector("#drawerMeta").textContent = drawerMetaLabel(sampleResult);
        document.querySelector(".answer-source-link[data-citation-index]")?.click();
        window.setTimeout(() => {{
          document.body.dataset.smokeReady = "true";
        }}, 300);
      }}, 200);
    }});
  </script>
</body>
</html>
"""


def sample_result_payload() -> dict[str, Any]:
    citations = [
        {
            "doc_id": "KT-QT-CTX",
            "version": "1.0",
            "display_code": "PD-TECH-A-02",
            "display_version": "Rev 04",
            "title": "Quy trinh bao tri may nen",
            "excerpt": "Buoc 2 Kiem tra ap suat va lap bien ban.",
            "anchor_id": "procedure-chunk-1",
        }
    ]
    return {
        "answer": "Quy trinh bao tri may nen gom 3 buoc.",
        "citations": citations,
        "response_contract_version": "answer_blocks.v1",
        "format_type": "mermaid",
        "format_plan": {
            "primary_format": "mermaid",
            "secondary_blocks": ["forms_records", "sources"],
            "render_hints": {"show_timeline": True, "show_checklist_button": True, "show_mermaid_button": True},
            "block_plan": {
                "summary": {"enabled": True, "reason": "show overview"},
                "workflow": {"enabled": True, "reason": "primary format"},
                "steps": {"enabled": True, "reason": "workflow steps"},
                "form": {"enabled": True, "reason": "records are relevant"},
                "sources": {"enabled": True, "reason": "grounded answer"},
            },
        },
        "structured_answer": {
            "answer_type": "mermaid",
            "title": "Quy trinh bao tri may nen",
            "summary": "Quy trinh bao tri may nen gom 3 buoc chinh.",
            "steps": [
                {"step_no": 1, "title": "Tiep nhan", "description": "Tiep nhan yeu cau.", "owner": "Nhan vien Ky thuat", "source_anchor": "procedure-chunk-1"},
                {"step_no": 2, "title": "Kiem tra", "description": "Kiem tra ap suat va lap bien ban.", "owner": "Truong phong Ky thuat", "source_anchor": "procedure-chunk-1"},
                {"step_no": 3, "title": "Luu ho so", "description": "Luu ho so bao tri.", "owner": "Phong Ky thuat", "source_anchor": "procedure-chunk-1"},
            ],
            "responsibilities": [{"label": "Buoc 2", "detail": "Truong phong Ky thuat phu trach.", "source_anchor": "procedure-chunk-1"}],
            "forms_records": [{"label": "Bien ban bao tri", "detail": "Lap sau buoc kiem tra.", "source_anchor": "procedure-chunk-1"}],
            "notes": [],
            "sources": [{"doc_id": "KT-QT-CTX", "version": "1.0", "display_code": "PD-TECH-A-02", "display_version": "Rev 04", "title": "Quy trinh bao tri may nen"}],
            "markdown": "| Ho so | Trang thai |\\n| --- | --- |\\n| Bien ban bao tri | Bat buoc |",
            "blocks": [
                {"type": "summary", "content": "Quy trinh bao tri may nen gom 3 buoc chinh."},
                {
                    "type": "workflow",
                    "items": [
                        {"text": "Tiep nhan", "detail": "Tiep nhan yeu cau.", "source_anchor": "procedure-chunk-1"},
                        {"text": "Kiem tra", "detail": "Kiem tra ap suat va lap bien ban.", "source_anchor": "procedure-chunk-1"},
                        {"text": "Luu ho so", "detail": "Luu ho so bao tri.", "source_anchor": "procedure-chunk-1"},
                    ],
                },
                {
                    "type": "form",
                    "items": [{"label": "Bien ban bao tri", "detail": "Lap sau buoc kiem tra.", "source_anchor": "procedure-chunk-1"}],
                },
                {
                    "type": "sources",
                    "items": [{"doc_id": "KT-QT-CTX", "version": "1.0", "display_code": "PD-TECH-A-02", "display_version": "Rev 04", "title": "Quy trinh bao tri may nen"}],
                },
            ],
        },
        "blocks": [
            {"type": "summary", "content": "Quy trinh bao tri may nen gom 3 buoc chinh."},
            {
                "type": "workflow",
                "items": [
                    {"text": "Tiep nhan", "detail": "Tiep nhan yeu cau.", "source_anchor": "procedure-chunk-1"},
                    {"text": "Kiem tra", "detail": "Kiem tra ap suat va lap bien ban.", "source_anchor": "procedure-chunk-1"},
                    {"text": "Luu ho so", "detail": "Luu ho so bao tri.", "source_anchor": "procedure-chunk-1"},
                ],
            },
        ],
        "block_plan": {
            "summary": {"enabled": True, "reason": "show overview"},
            "workflow": {"enabled": True, "reason": "primary format"},
            "steps": {"enabled": True, "reason": "workflow steps"},
            "form": {"enabled": True, "reason": "records are relevant"},
            "sources": {"enabled": True, "reason": "grounded answer"},
        },
        "evidence_summary": {"selected_chunks": 3, "claim_count": 3, "missing_evidence": [], "conflicts": []},
        "evidence_pack": {
            "verified_evidence": [
                {
                    "claim": "Buoc 2 yeu cau kiem tra ap suat va lap bien ban.",
                    "doc_id": "KT-QT-CTX",
                    "version": "1.0",
                    "evidence_type": "procedure_steps",
                    "citation": "procedure-chunk-1",
                    "confidence": 0.94,
                }
            ],
            "missing_evidence": [],
            "conflicts": [],
        },
        "quality_decision": {"decision": "pass"},
        "procedure_compliance": {"final_decision": "release", "citation_coverage": 1.0},
        "answer_run": {"intent": "ask_procedure", "final_confidence": 0.94},
        "trace_steps": [
            {"id": "retrieval_plan", "label": "Ke hoach truy xuat", "status": "done", "metadata": {"queries": ["quy trinh bao tri may nen"], "datasets": ["technical"], "filters": ["status=active"]}},
            {"id": "evidence", "label": "Xay bang chung", "status": "done", "metadata": {"selected_chunks": 3, "claim_count": 3}},
            {"id": "critic", "label": "Kiem dinh cau tra loi", "status": "done", "metadata": {"quality_decision": {"decision": "pass"}}},
        ],
}


def sample_public_citation_payload() -> dict[str, Any]:
    return {
        "record": {
            "doc_id": "KT-QT-CTX",
            "version": "1.0",
            "title": "Quy trinh bao tri may nen",
            "display_code": "PD-TECH-A-02",
            "display_version": "Rev 04",
        },
        "citation": {
            "anchor_id": "procedure-chunk-1",
            "line_start": 11,
            "line_end": 13,
            "locator_status": "exact",
            "matched_excerpt": "Buoc 2 Kiem tra ap suat va lap bien ban.",
        },
        "source_file": {
            "exists": True,
            "kind": "pdf",
            "file_name": "PD-TECH-A-02 Rev 04.pdf",
            "suffix": ".pdf",
            "size_bytes": 2048,
            "download_url": "/api/user/documents/KT-QT-CTX/1.0/source-file",
            "preferred_pdf": True,
        },
        "preview": {
            "highlight_line_start": 11,
            "highlight_line_end": 13,
            "anchor_id": "procedure-chunk-1",
            "locator_status": "exact",
            "matched_excerpt": "Buoc 2 Kiem tra ap suat va lap bien ban.",
            "lines": [
                {"line": 9, "text": "## Quy trinh thuc hien", "highlight": False},
                {"line": 10, "text": "| Buoc | Noi dung | Ho so |", "highlight": False},
                {"line": 11, "text": "| --- | --- | --- |", "highlight": True, "anchor_id": "procedure-chunk-1"},
                {
                    "line": 12,
                    "text": "| 2 | Buoc 2 Kiem tra ap suat va lap bien ban. | Bien ban bao tri |",
                    "highlight": True,
                    "anchor_id": "procedure-chunk-1",
                },
                {"line": 13, "text": "| 3 | Luu ho so bao tri. | Kho ho so ky thuat |", "highlight": True, "anchor_id": "procedure-chunk-1"},
            ],
        },
    }


def sample_table_result_payload() -> dict[str, Any]:
    citations = [
        {
            "doc_id": "KT-QT-215",
            "version": "1.0",
            "display_code": "PD-IC-A-001",
            "display_version": "Rev 10",
            "title": "Danh sach SOP",
            "excerpt": "Phong Ky thuat co 3 quy trinh hien hanh.",
            "anchor_id": "catalog-chunk-1",
        }
    ]
    return {
        "answer": "Phong Ky thuat co 3 quy trinh hien hanh.",
        "citations": citations,
        "response_contract_version": "answer_blocks.v1",
        "format_type": "table",
        "format_plan": {
            "primary_format": "table",
            "secondary_blocks": ["sources", "decision_matrix"],
            "render_hints": {"show_timeline": False, "show_checklist_button": False, "show_mermaid_button": False},
            "block_plan": {
                "summary": {"enabled": True, "reason": "show overview"},
                "table": {"enabled": True, "reason": "primary format"},
                "decision_matrix": {"enabled": True, "reason": "decision support rendering"},
                "sources": {"enabled": True, "reason": "grounded answer"},
            },
        },
        "structured_answer": {
            "answer_type": "table",
            "title": "Danh sach quy trinh Phong Ky thuat",
            "summary": "Phong Ky thuat co 3 quy trinh hien hanh.",
            "steps": [],
            "responsibilities": [],
            "forms_records": [],
            "notes": [],
            "sources": [{"doc_id": "KT-QT-215", "version": "1.0", "display_code": "PD-IC-A-001", "display_version": "Rev 10", "title": "Danh sach SOP"}],
            "markdown": "| Ma | Ten | Trang thai |\n| --- | --- | --- |\n| KT-QT-215 | Lap dat / Sua chua / Bao tri | active |",
            "blocks": [
                {"type": "summary", "content": "Phong Ky thuat co 3 quy trinh hien hanh."},
                {
                    "type": "table",
                    "markdown": "| Ma | Ten | Trang thai |\n| --- | --- | --- |\n| KT-QT-215 | Lap dat / Sua chua / Bao tri | active |",
                },
                {
                    "type": "decision_matrix",
                    "title": "Chon quy trinh phu hop",
                    "items": [{"label": "Lap dat / Sua chua / Bao tri", "detail": "Chon theo tinh huong van hanh.", "source_anchor": "catalog-chunk-1"}],
                },
                {"type": "sources", "items": [{"doc_id": "KT-QT-215", "version": "1.0", "display_code": "PD-IC-A-001", "display_version": "Rev 10", "title": "Danh sach SOP"}]},
            ],
        },
        "blocks": [
            {"type": "summary", "content": "Phong Ky thuat co 3 quy trinh hien hanh."},
            {
                "type": "table",
                "markdown": "| Ma | Ten | Trang thai |\n| --- | --- | --- |\n| KT-QT-215 | Lap dat / Sua chua / Bao tri | active |",
            },
            {
                "type": "decision_matrix",
                "title": "Chon quy trinh phu hop",
                "items": [{"label": "Lap dat / Sua chua / Bao tri", "detail": "Chon theo tinh huong van hanh.", "source_anchor": "catalog-chunk-1"}],
            },
        ],
        "block_plan": {
            "summary": {"enabled": True, "reason": "show overview"},
            "table": {"enabled": True, "reason": "primary format"},
            "decision_matrix": {"enabled": True, "reason": "decision support rendering"},
            "sources": {"enabled": True, "reason": "grounded answer"},
        },
        "evidence_summary": {"selected_chunks": 1, "claim_count": 1, "missing_evidence": [], "conflicts": []},
        "evidence_pack": {
            "verified_evidence": [
                {
                    "claim": "Phong Ky thuat co 3 quy trinh hien hanh.",
                    "doc_id": "KT-QT-215",
                    "version": "1.0",
                    "evidence_type": "procedure_catalog",
                    "citation": "catalog-chunk-1",
                    "confidence": 0.95,
                }
            ],
            "missing_evidence": [],
            "conflicts": [],
        },
        "quality_decision": {"decision": "pass"},
        "procedure_compliance": {"final_decision": "release", "citation_coverage": 1.0},
        "answer_run": {"intent": "catalog/list_procedure", "final_confidence": 0.95},
        "trace_steps": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the user chat UI smoke harness in a headless browser.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--browser-path", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_user_chat_render_smoke(args.root, browser_path=args.browser_path)
    print(json.dumps({"pass": report["pass"], "skipped": report["skipped"], "checks": report["checks"]}, ensure_ascii=False))
    return 0 if report["pass"] or report["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
