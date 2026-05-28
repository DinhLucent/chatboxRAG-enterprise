---
name: rag-markdown-repairer
description: Sua Markdown va artifact convert de san sang cho RAGFlow dua tren repair_request tu QA. Dung khi can lap repair loop, khoi phuc heading, bang, citation anchors, schema metadata va loai bo noise ma van bao toan noi dung goc.
metadata:
  risk: medium
  source: poc_workflow/agent_skills
---

# RAG Markdown Repairer

## When to Use

Dung skill nay khi `source-output-quality-auditor` tra `status: needs_repair` hoac parent yeu cau sua output MinerU de dat chuan RAGFlow.

## When NOT to Use

- Khong dung de bo qua audit; moi output sua xong phai quay lai `source-output-quality-auditor`.
- Khong dung de them noi dung suy dien khong co trong source.
- Khong dung de ingest RAGFlow truc tiep.

## Workflow

1. Doc `repair_request.json`, `audit_report.json`, Markdown hien tai va `mineru_artifact_index.json`.
2. Nhom issue theo source, page/sheet, MinerU block id, bbox, table/image va severity.
3. Sua blocker/major truoc: noi dung mat, bang sai, reading order sai, citation thieu.
4. Chuan hoa Markdown: heading cap bac, table pipe format, list, code block, image alt text, frontmatter metadata neu pipeline yeu cau.
5. Them hoac sua anchors citation dang on dinh: page, sheet, row range, table id, `mineru_block_ids`, `content_types`, `bbox`, `source_json`, `image_refs`.
6. Ghi output vao `repaired/<source_id>/content.md` va tao `repair_manifest.json`.
7. Handoff lai `source-output-quality-auditor` de audit lai tren file goc.

## MinerU Sidecar Repair Rules

- Khi Markdown thieu cau truc, dung `content_list_v2/content_list` de khoi phuc heading, paragraph, table text va step order.
- Khi can locator UI, dung `middle.json` de lay page, bbox, layout block va image/figure relationship; khong chi copy text tu Markdown.
- Khi `content_list` va `middle.json` khong du thong tin, dung `model.json` lam evidence bo sung cho table/image/text block.
- Flowchart/hinh/so do khong bi xoa. Neu doc duoc thi chuyen thanh Mermaid hoac danh sach buoc co citation; neu chua doc chac thi giu placeholder kem `image_ref`, `source_json`, page/bbox va `needs_review`.
- `repair_manifest.json` phai ghi ro moi action dung evidence nao: `source_json`, `mineru_block_id`, `bbox`, `image_ref`, hoac source sheet/row/page.

## Inputs

- `repair_request`: danh sach issue can sua.
- `converted_outputs`: Markdown va artifact tu MinerU.
- `mineru_artifact_index`: sidecar MinerU de lay content_list/middle/images khi Markdown thieu locator.
- `rich_sidecar_evidence_map`: map evidence tu content_list/middle/model/images do auditor tao.
- `audit_report`: bang chung tu QA.
- `source_snippets`: trich xuat goc neu auditor cung cap.

## Outputs / Handoff JSON

```json
{
  "run_id": "ragflow-run-YYYYMMDD-HHMMSS",
  "step": "repair",
  "status": "passed",
  "source_ids": ["src_001"],
  "artifacts": [
    {
      "artifact_id": "repaired_markdown_src_001",
      "path": "repaired/src_001/content.md",
      "type": "repair",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    },
    {
      "artifact_id": "repair_manifest_src_001",
      "path": "repaired/src_001/repair_manifest.json",
      "type": "repair",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    }
  ],
  "quality_gates": {
    "all_blockers_addressed": true,
    "citations_preserved": true,
    "markdown_valid": true,
    "ready_for_reaudit": true
  },
  "next_skill": "source-output-quality-auditor"
}
```

## Failure Handling

- Khong doan noi dung mat neu khong co bang chung tu file goc; danh dau `blocked` va yeu cau auditor/parent cung cap snippet.
- Neu sua table lam mat numeric value, revert phan sua table do trong ban repair va giu issue mo.
- Neu citation khong the xac dinh, them `citation_status: unresolved` trong manifest va khong danh dau pass.
- Khong xoa image/flowchart/table snapshot; neu chua doc chac, giu placeholder kem `image_ref` va `needs_review`.
- Neu cung mot issue quay lai sau audit, ghi `repeat_issue: true` de orchestrator dung sau gioi han loop.

## Quality Gates

- Tat ca issue blocker co action: fixed, deferred_with_reason, hoac blocked.
- Markdown parse duoc, khong co heading nhay cap bat thuong neu khong co ly do.
- Bang co header, cot on dinh, khong mat dong tong/subtotal.
- Citation anchors khong bi xoa khi sua noi dung.
- Neu source la MinerU ZIP co rich metadata, output repaired phai giu duong dan den `mineru_artifact_index.json`.
- `repair_manifest.json` mapping tung `issue_id` sang patch/action va output path.
