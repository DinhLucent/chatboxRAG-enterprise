---
name: mineru-source-converter
description: Convert file nguon PDF/XLSX sang Markdown va artifact trung gian bang MinerU cho pipeline RAGFlow. Dung khi can xu ly PDF/XLSX tuan tu, luu conversion manifest, anh, bang, page/sheet anchors va log loi.
metadata:
  risk: medium
  source: poc_workflow/agent_skills
---

# MinerU Source Converter

## When to Use

Dung skill nay khi co `batch_manifest` tu orchestrator va can convert PDF/XLSX goc sang output de QA va ingest RAGFlow.

## When NOT to Use

- Khong dung de sua Markdown sau convert; handoff sang `rag-markdown-repairer`.
- Khong dung de quyet dinh output da dat chat luong; handoff sang `source-output-quality-auditor`.
- Khong dung de chay batch song song neu run_config chua cho phep.

## Workflow

1. Doc `batch_manifest`; chi lay mot source active tai mot thoi diem.
2. Xac minh file goc, checksum neu co, va quyen doc.
3. Chay MinerU cho PDF theo tung file, giu page number, images, table extraction va reading order.
4. Chay MinerU cho XLSX sau PDF hoac theo thu tu batch; moi sheet phai co sheet name, row/column range va table id.
5. Ghi output vao `converted/<source_id>/`.
6. Tao `conversion_manifest.json` voi mapping source -> output Markdown, images, tables, logs.
7. Handoff sang `source-output-quality-auditor`.

## Inputs

- `batch_manifest`: queue tuan tu, `source_id`, `source_path`, `source_type`.
- `run_config`: MinerU options, language, OCR mode, table mode.
- `workspace_paths.converted`: thu muc output.

## Outputs / Handoff JSON

```json
{
  "run_id": "ragflow-run-YYYYMMDD-HHMMSS",
  "step": "convert",
  "status": "passed",
  "source_ids": ["src_001"],
  "artifacts": [
    {
      "artifact_id": "converted_markdown_src_001",
      "path": "converted/src_001/content.md",
      "type": "converted",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    },
    {
      "artifact_id": "conversion_manifest_src_001",
      "path": "converted/src_001/conversion_manifest.json",
      "type": "converted",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    }
  ],
  "quality_gates": {
    "processed_sequentially": true,
    "markdown_created": true,
    "page_or_sheet_anchors_created": true,
    "conversion_log_created": true
  },
  "next_skill": "source-output-quality-auditor"
}
```

## Failure Handling

- Neu MinerU fail tren mot file, ghi `status: failed`, giu log day du va khong tiep tuc file ke tiep neu parent yeu cau stop-on-error.
- Neu output Markdown rong, danh dau `failed` ke ca MinerU exit code thanh cong.
- Neu XLSX co sheet bi bo qua, danh dau `needs_repair` hoac `failed` tuy muc do va neu ro sheet name.
- Neu file co password, corrupt, scan chat luong kem hoac OCR bat dinh, tra `blocked` voi de xuat can source tot hon.

## Quality Gates

- Moi source chi duoc convert mot lan trong mot slot tuan tu.
- `content.md` ton tai va khong rong.
- PDF output co page anchors dang `page:<number>` hoac tuong duong.
- XLSX output co sheet anchors va table ranges.
- `conversion_manifest.json` lien ket tat ca artifact ve cung `source_id`.
- Conversion log ghi command/options, thoi gian, exit status va warning.
