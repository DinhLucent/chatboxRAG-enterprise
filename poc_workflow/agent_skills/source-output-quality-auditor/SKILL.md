---
name: source-output-quality-auditor
description: Audit chat luong output MinerU bang cach doi chieu PDF/Excel goc voi Markdown/artifact da convert. Dung khi can phat hien mat noi dung, sai bang, sai thu tu doc, thieu citation, OCR loi va quyet dinh co can repair loop hay khong.
metadata:
  risk: high
  source: poc_workflow/agent_skills
---

# Source Output Quality Auditor

## When to Use

Dung skill nay sau conversion va sau moi repair loop de xac nhan output gan voi file goc, khong chi lint artifact da convert.

## When NOT to Use

- Khong dung de sua artifact; neu co issue, tao `repair_request` cho `rag-markdown-repairer`.
- Khong dung de index RAGFlow; chi handoff sang `ragflow-schema-indexer` khi audit pass.

## Workflow

1. Mo file PDF/XLSX goc va `conversion_manifest`.
2. Lay mau theo trang/sheet, bang, heading, hinh, footnote va cac doan co so lieu.
3. Doi chieu noi dung goc voi Markdown/output da convert.
4. Phan loai issue: `missing_content`, `wrong_order`, `table_error`, `ocr_error`, `citation_gap`, `format_noise`, `schema_gap`.
5. Gan severity: `blocker`, `major`, `minor`.
6. Tao `audit_report.json` va `repair_request.json` neu co loi can sua.
7. Neu dat nguong, handoff sang `ragflow-schema-indexer`; neu chua dat, handoff sang `rag-markdown-repairer`.

## Inputs

- `raw_sources`: path PDF/XLSX goc.
- `conversion_manifest`: mapping output tu MinerU.
- `converted_outputs` hoac `repaired_outputs`.
- `quality_thresholds`: nguong coverage, table fidelity, citation coverage.

## Outputs / Handoff JSON

```json
{
  "run_id": "ragflow-run-YYYYMMDD-HHMMSS",
  "step": "audit",
  "status": "needs_repair",
  "source_ids": ["src_001"],
  "artifacts": [
    {
      "artifact_id": "audit_report_src_001",
      "path": "audit/src_001/audit_report.json",
      "type": "audit",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    },
    {
      "artifact_id": "repair_request_src_001",
      "path": "audit/src_001/repair_request.json",
      "type": "audit",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    }
  ],
  "quality_gates": {
    "source_compared": true,
    "required_coverage_passed": false,
    "tables_passed": false,
    "citations_passed": true
  },
  "next_skill": "rag-markdown-repairer"
}
```

## Failure Handling

- Neu khong doc duoc file goc, tra `blocked`; khong ket luan output dat.
- Neu audit thieu bang chung cho issue blocker/major, tu ha issue thanh `needs_review` hoac lap lai sampling.
- Neu repair da lap 3 lan ma van loi cu, tra `blocked` cho orchestrator.
- Neu Markdown dat nhung citation thieu, khong cho qua index vi RAGFlow can truy vet nguon.

## Quality Gates

- Audit doc truc tiep PDF/XLSX goc va ghi `source_compared: true`.
- Moi issue co `issue_id`, `source_id`, `location`, `evidence`, `expected`, `actual`, `severity`.
- Bang quan trong trong XLSX/PDF co header, row count va numeric values duoc doi chieu.
- Heading va reading order phai du dung de chunk RAG.
- Tat ca noi dung RAG-ready phai co page/sheet citation hoac ly do mien tru.
