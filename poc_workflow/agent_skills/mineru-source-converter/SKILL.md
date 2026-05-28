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
3. Chay MinerU cho PDF/XLSX theo tung file; khong dung native parser thay the trong workflow chinh neu MinerU fail.
4. Giu nguyen ZIP/folder output MinerU lam bang chung convert; khong chi copy `.md`.
5. Bao toan toan bo file MinerU xuat ra vao `mineru_artifacts/`; cac artifact giau ngu canh duoc gan nhan rieng gom `content_list.json`, `content_list_v2.json`, `middle.json`, `model.json`, `images/`, va `_origin.pdf` neu co.
6. Tao `mineru_artifact_index.json` lien ket selected Markdown, tat ca sidecar JSON/Markdown/log/other files, image refs, checksum, count block/page/image va duong dan ZIP goc.
7. Ghi output vao `converted/<source_id>/` hoac `.Workplace/artifacts/.../mineru_raw/`.
8. Tao `conversion_manifest.json` voi mapping source -> output Markdown, MinerU artifact index, images, tables, logs.
9. Handoff sang `source-output-quality-auditor`.

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
    },
    {
      "artifact_id": "mineru_artifact_index_src_001",
      "path": "converted/src_001/mineru_artifact_index.json",
      "type": "converted",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    }
  ],
  "quality_gates": {
    "processed_sequentially": true,
    "markdown_created": true,
    "mineru_artifact_index_created": true,
    "content_list_or_middle_json_available": true,
    "page_or_sheet_anchors_created": true,
    "conversion_log_created": true
  },
  "next_skill": "source-output-quality-auditor"
}
```

## Failure Handling

- Neu MinerU fail tren mot file, ghi `status: failed`, giu log day du va khong tiep tuc file ke tiep neu parent yeu cau stop-on-error.
- Neu output Markdown rong, danh dau `failed` ke ca MinerU exit code thanh cong.
- Neu ZIP co `.md` nhung thieu ca `content_list/content_list_v2` va `middle.json`, danh dau `needs_review`; Markdown don le khong du citation giau cho RAG.
- Neu XLSX co sheet bi bo qua, danh dau `needs_repair` hoac `failed` tuy muc do va neu ro sheet name.
- Neu file co password, corrupt, scan chat luong kem hoac OCR bat dinh, tra `blocked` voi de xuat can source tot hon.

## Quality Gates

- Moi source chi duoc convert mot lan trong mot slot tuan tu.
- `content.md` ton tai va khong rong.
- `mineru_artifact_index.json` ton tai va tro toi ZIP/folder MinerU goc; index phai co ca artifact quen thuoc va sidecar la/khac neu MinerU sinh ra.
- `content_list_v2.json` duoc uu tien; neu khong co thi dung `content_list.json`; `middle.json` duoc dung cho bbox/page locator khi co.
- Images/flowchart/table snapshots trong `images/` phai duoc giu ref, khong xoa im lang.
- PDF output co page anchors dang `page:<number>` hoac tuong duong.
- XLSX output co sheet anchors va table ranges.
- `conversion_manifest.json` lien ket tat ca artifact ve cung `source_id`.
- Conversion log ghi command/options, thoi gian, exit status va warning.
