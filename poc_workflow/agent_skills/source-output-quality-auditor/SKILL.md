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
2. Doi chieu tung candidate raw output MinerU: selected Markdown, `mineru_artifact_index.json`, `content_list_v2/content_list`, `middle.json`, `model.json`, image/table artifacts.
3. Lay mau theo trang/sheet, bang, heading, hinh, footnote, bbox va cac doan co so lieu.
4. Doi chieu noi dung goc voi Markdown/output da convert, bao gom coverage term, row/table signal, step signal, reading order, citation locator, MinerU block id va bbox/image ref.
5. Phan loai issue: `missing_content`, `wrong_order`, `table_error`, `ocr_error`, `citation_gap`, `format_noise`, `schema_gap`, `low_rag_usefulness`.
6. Gan severity: `blocker`, `major`, `minor`.
7. Tao `audit_report.json`, `repair_request.json` va `learning_notes.md` neu co loi can sua.
8. Neu dat nguong, handoff sang `ragflow-schema-indexer`; neu chua dat, handoff sang `rag-markdown-repairer`.

## MinerU Rich Sidecar Contract

- Khong duoc audit chi dua tren file `.md`. Markdown la view de doc, con sidecar MinerU la bang chung de lap locator.
- Thu tu khai thac: `content_list_v2`, `content_list`, `middle.json`, `model.json`, `images/`, `_origin.pdf`, cac JSON/log phu.
- `content_list_v2/content_list` dung de lay semantic block, table/body text, block id va page.
- `middle.json` dung de lay page/layout hierarchy, bbox, reading order va lien ket image/figure khi co.
- `model.json` dung de bo sung model-detected table/text/image blocks neu content_list thieu.
- `images/` dung lam visual evidence cho flowchart, form screenshot, figure/table snapshot; khong xoa image neu chua doc chac.
- Audit pass phai ghi `rich_sidecar_evidence_map` hoac ly do vi sao sidecar khong co evidence dung duoc.

## Inputs

- `raw_sources`: path PDF/XLSX goc.
- `conversion_manifest`: mapping output tu MinerU.
- `mineru_artifact_index`: index sidecar MinerU, selected Markdown, content_list, middle/model JSON va images.
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
    "mineru_artifact_index_checked": true,
    "content_list_or_middle_json_checked": true,
    "middle_or_model_json_checked": true,
    "rich_sidecar_evidence_map_created": true,
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
- Neu Markdown co ve sach nhung `mineru_artifact_index` thieu `content_list/content_list_v2` va `middle.json`, khong ket luan citation giau da dat; tra `needs_repair` hoac `needs_review` tuy muc do.
- Khong chay retrieval/chatbot smoke test trong phase nay. Retrieval quality la phase sau khi RAG-ready package da duoc human review.

## Quality Gates

- Audit doc truc tiep PDF/XLSX goc va ghi `source_compared: true`.
- Moi issue co `issue_id`, `source_id`, `location`, `evidence`, `expected`, `actual`, `severity`.
- Bang quan trong trong XLSX/PDF co header, row count va numeric values duoc doi chieu.
- Heading va reading order phai du dung de chunk RAG.
- Tat ca noi dung RAG-ready phai co page/sheet citation hoac ly do mien tru; neu MinerU co bbox/block id thi citation_map phai giu `mineru_block_ids`, `content_types`, `bbox`, `source_json`, va `image_refs` khi co.
- Output co `retrieval_or_smoke_chat_executed: false` de admin biet phase nay chi kiem hau-convert.

## Learned Rules

- MinerU ZIP/raw Markdown la bang chung goc cua buoc convert; khong ghi de.
- Markdown MinerU chi la mot view; `content_list_v2/content_list + middle.json + images` moi la bang chung chinh de tao locator RAG/UI.
- XLSX MinerU output thuong giu bang tot hon nhung co HTML/table noise; can parse table HTML truoc khi danh gia chat luong.
- PDF MinerU output co the sach ve encoding nhung kem ve ngu nghia/step neu OCR mat dau hoac vo bang; khong pass chi vi `mojibake_score=0`.
- Neu mot candidate giau step/table signal hon nhung co loi nho co the repair, uu tien repair candidate do thay vi chon candidate sach gia.
