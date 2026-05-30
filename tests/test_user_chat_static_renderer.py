from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_user_chat_structured_renderer_links_sources_and_quality_summary() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static user chat renderer smoke test")

    script = textwrap.dedent(
        r"""
        const fs = require('fs');
        const vm = require('vm');
        const source = fs
          .readFileSync('poc_workflow/static/user/user-chat.js', 'utf8')
          .replace(/\ninit\(\);\s*$/, '\n');
        const tracePanelEl = { innerHTML: '' };
        const context = {
          console,
          setTimeout: () => 0,
          localStorage: { getItem: () => null, setItem: () => {} },
          window: {
            matchMedia: () => ({ matches: false }),
            crypto: { randomUUID: () => 'uuid' },
            setTimeout: () => 0,
            addEventListener: () => {},
          },
          document: {
            querySelector: (sel) => {
              if (sel === '#tracePanel') return tracePanelEl;
              return null;
            },
            querySelectorAll: () => []
          },
        };
        vm.createContext(context);
        vm.runInContext(source, context);

        const citations = [{
          doc_id: 'KT-QT-215',
          version: '1.0',
          display_code: 'PD-IC-A-001',
          display_version: 'Rev 10',
          title: 'Danh sach SOP',
          excerpt: 'Phong Ky thuat co 3 quy trinh.',
          anchor_id: 'chunk-1',
        }];
        const answerHtml = context.renderStructuredAnswer({
          answer_type: 'checklist',
          title: 'Danh sach SOP',
          summary: 'Phong Ky thuat co 3 quy trinh.',
          blocks: [{
            type: 'checklist',
            items: [{
              text: 'Lap dat',
              detail: 'Thuc hien theo SOP.',
              source_anchor: 'chunk-1',
            }],
          }, {
            type: 'sources',
            items: [{ doc_id: 'KT-QT-215', version: '1.0', title: 'Danh sach SOP' }],
          }],
          steps: [{
            step_no: 1,
            title: 'Lap dat',
            description: 'Thuc hien theo SOP.',
            owner: 'Phong Ky thuat',
            source_anchor: 'chunk-1',
          }],
          forms_records: [{ label: 'Bien ban', detail: 'Luu ho so', source_anchor: 'chunk-1' }],
          sources: [{
            doc_id: 'KT-QT-215',
            version: '1.0',
            display_code: 'PD-IC-A-001',
            display_version: 'Rev 10',
            title: 'Danh sach SOP',
          }],
        }, {
          primary_format: 'checklist',
          secondary_blocks: ['forms_records', 'sources'],
          render_hints: { show_timeline: true, show_checklist_button: true },
        }, citations);
        const decisionHtml = context.renderStructuredAnswer({
          answer_type: 'decision_matrix',
          blocks: [{
            type: 'decision_matrix',
            title: 'Lua chon bieu mau',
            items: [{
              label: 'Bien ban',
              detail: 'Dung khi can luu ho so.',
              source_anchor: 'chunk-1',
            }],
          }, {
            type: 'clarification',
            question: 'Ban dang xu ly truong hop nao?',
            missing_context: ['scenario'],
          }],
        }, {
          primary_format: 'decision_matrix',
          block_plan: {
            decision_matrix: { enabled: true, reason: 'decision support' },
            clarification: { enabled: true, reason: 'ask for context' },
          },
        }, citations);
        const tableHtml = context.renderStructuredAnswer({
          answer_type: 'table',
          title: 'Danh sach SOP',
          summary: 'Phong Ky thuat co 3 quy trinh.',
          markdown: '| Ma | Ten |\n| --- | --- |\n| KT-QT-215 | Danh sach SOP |',
          sources: [{ doc_id: 'KT-QT-215', version: '1.0', title: 'Danh sach SOP' }],
        }, {
          primary_format: 'table',
          secondary_blocks: ['sources'],
          render_hints: {},
        }, citations);
        const workflowHtml = context.renderStructuredAnswer({
          answer_type: 'mermaid',
          title: 'Quy trinh bao tri',
          summary: 'Thuc hien theo 2 buoc.',
          steps: [
            { step_no: 1, title: 'Tiep nhan', source_anchor: 'chunk-1' },
            { step_no: 2, title: 'Kiem tra', source_anchor: 'chunk-1' },
          ],
          sources: [{ doc_id: 'KT-QT-215', version: '1.0', title: 'Danh sach SOP' }],
        }, {
          primary_format: 'mermaid',
          secondary_blocks: ['sources'],
          render_hints: { show_mermaid_button: true },
        }, citations);
        const sourceSummaryHtml = context.renderEvidenceDrawerSummary({
          citations,
          format_type: 'checklist',
          quality_decision: { decision: 'pass' },
          procedure_compliance: { final_decision: 'release', citation_coverage: 1 },
          evidence_summary: { selected_chunks: 3, claim_count: 2, missing_evidence: [] },
          answer_run: { intent: 'catalog/list_procedure', final_confidence: 0.93 },
        });
        const evidenceClaimsHtml = context.renderEvidenceClaims({
          evidence_pack: {
            verified_evidence: [{
              claim: 'Phong Ky thuat co 3 quy trinh.',
              doc_id: 'KT-QT-215',
              version: '1.0',
              evidence_type: 'procedure_catalog',
              citation: 'chunk-1',
              confidence: 0.93,
            }],
            missing_evidence: [],
            conflicts: [],
          },
        }, citations);
        const noAnswerHtml = context.renderStructuredAnswer({
          answer_type: 'no_answer',
          summary: 'Khong tim thay can cu.',
        }, {
          primary_format: 'no_answer_card',
          render_hints: { show_no_answer_card: true },
        }, []);
        const synthesizedNoAnswer = context.structuredAnswerForResult({
          answer: 'Noi dung nay ngoai pham vi.',
          format_type: 'no_answer_card',
          quality_decision: { decision: 'scope_reject' },
        });

        // Render trace with dummy data
        const dummyTraceSteps = [
          { id: 'scope_guard', label: 'Kiem pham vi cau hoi', status: 'done', detail: 'Cau hoi hop le' },
          { id: 'analyze', label: 'Phan tich cau hoi', status: 'running', detail: 'Dang phan tich...' }
        ];
        context.renderTrace(dummyTraceSteps);
        const traceHtml = tracePanelEl.innerHTML;

        if (!answerHtml.includes('data-contract="answer_blocks.v1"')) throw new Error('missing block contract');
        if (!answerHtml.includes('answer-block checklist')) throw new Error('missing checklist block');
        if (answerHtml.includes('answer-source-link')) throw new Error('chat answer must not embed source links');
        if (answerHtml.includes('structured-sources')) throw new Error('chat answer must not embed a sources section');
        if (!decisionHtml.includes('answer-block decision-matrix')) throw new Error('missing decision matrix block');
        if (!decisionHtml.includes('answer-block clarification')) throw new Error('missing clarification block');
        if (!tableHtml.includes('markdown-table')) throw new Error('missing markdown table fallback');
        if (!workflowHtml.includes('structured-workflow')) throw new Error('missing workflow visual block');
        if (!sourceSummaryHtml.includes('source-summary-card')) throw new Error('missing source summary');
        if (!sourceSummaryHtml.includes('93%')) throw new Error('missing confidence percent');
        if (!evidenceClaimsHtml.includes('evidence-pack-card')) throw new Error('missing evidence pack card');
        if (!evidenceClaimsHtml.includes('data-citation-index="0"')) throw new Error('missing evidence claim source link');
        if (!noAnswerHtml.includes('no-answer-card')) throw new Error('missing no-answer card');
        if (!synthesizedNoAnswer || synthesizedNoAnswer.answer_type !== 'no_answer') {
          throw new Error('missing synthesized no-answer card payload');
        }

        // Assertions for premium trace visualization
        if (!traceHtml.includes('trace-timeline-connector')) {
          throw new Error('missing timeline connector structure');
        }
        if (!traceHtml.includes('trace-duration')) {
          throw new Error('missing duration timer element');
        }
        if (!traceHtml.includes('svg') || !traceHtml.includes('shield')) {
          throw new Error('missing SVG icon render or correct step mapping');
        }
        """
    )

    result = subprocess.run(
        [node, "-e", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
