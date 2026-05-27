---
name: ragflow-schema-indexer
description: Dong goi output da QA thanh thu muc RAG-ready cho RAGFlow, gom schema manifest, citation manifest, index manifest, chunk metadata va folder layout co the ingest. Dung sau khi audit dat tat ca quality gates bat buoc.
metadata:
  risk: medium
  source: poc_workflow/agent_skills
---

# RAGFlow Schema Indexer

## When to Use

Dung skill nay khi auditor tra `status: passed` va can tao folder/schema/citation/index de parent hoac RAGFlow ingest.

## When NOT to Use

- Khong dung khi `audit_report` chua pass hoac citation gate dang fail.
- Khong dung de sua Markdown; tra ve `rag-markdown-repairer` neu schema/chunk phat hien noi dung thieu.
- Khong upload vao RAGFlow thay parent neu workflow yeu cau human review truoc.

## Workflow

1. Xac minh audit moi nhat dat quality gates bat buoc.
2. Chon output uu tien: `repaired` neu co, neu khong dung `converted`.
3. Tao folder `rag_ready/<source_id>/`.
4. Chuan hoa Markdown chunk theo heading, page/sheet boundary va chunk policy.
5. Tao `schema_manifest.json` mo ta dataset, fields, source type, chunk policy, MinerU artifact index va metadata.
6. Tao `citation_manifest.json` mapping chunk -> page/sheet/table/row range; neu co MinerU sidecar thi giu `mineru_block_ids`, `content_types`, `bbox`, `source_json`, `image_refs`.
7. Tao `index_manifest.json` liet ke file ingest, checksum, chunk ids va dependency.
8. Handoff sang `data-skill-evolution`.

## Inputs

- `repaired_outputs` hoac `converted_outputs` da audit pass.
- `audit_report`: bang chung quality gates.
- `mineru_artifact_index`: optional nhung bat buoc giu neu conversion co ZIP/folder MinerU.
- `run_plan`: dataset target, collection name, schema policy.
- `citation_policy`: bat buoc hay optional, dinh dang anchors.

## Outputs / Handoff JSON

```json
{
  "run_id": "ragflow-run-YYYYMMDD-HHMMSS",
  "step": "index",
  "status": "passed",
  "source_ids": ["src_001"],
  "artifacts": [
    {
      "artifact_id": "rag_ready_folder_src_001",
      "path": "rag_ready/src_001",
      "type": "rag_ready",
      "source_id": "src_001",
      "checksum": null
    },
    {
      "artifact_id": "schema_manifest_src_001",
      "path": "rag_ready/src_001/schema_manifest.json",
      "type": "rag_ready",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    },
    {
      "artifact_id": "citation_manifest_src_001",
      "path": "rag_ready/src_001/citation_manifest.json",
      "type": "rag_ready",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    },
    {
      "artifact_id": "index_manifest_src_001",
      "path": "rag_ready/src_001/index_manifest.json",
      "type": "rag_ready",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    }
  ],
  "quality_gates": {
    "audit_passed": true,
    "schema_created": true,
    "citations_complete": true,
    "mineru_artifact_index_linked": true,
    "chunks_indexed": true
  },
  "next_skill": "data-skill-evolution"
}
```

## Failure Handling

- Neu audit khong pass, tra `blocked` va khong tao index chinh thuc.
- Neu chunk nao thieu citation bat buoc, tra `needs_repair` ve `rag-markdown-repairer`.
- Neu schema field thieu gia tri can cho RAGFlow, ghi `schema_gap` va escalte parent neu khong co default an toan.
- Neu checksum hoac path mismatch, dung index de tranh ingest sai artifact.

## Quality Gates

- Thu muc `rag_ready` co Markdown chunk va 3 manifest bat buoc.
- Moi chunk co `chunk_id`, `source_id`, `content_path`, `citation_refs`, `checksum`.
- Citation refs tro ve page/sheet/table/row range hop le; voi PDF MinerU nen co page/bbox khi `middle.json` hoac `content_list` co du lieu.
- Schema manifest phai link `mineru_artifact_index.json` neu artifact nay ton tai de UI co the show nguon/hinh/table snapshot.
- Schema manifest co dataset name, source type, language, chunking policy va metadata fields.
- Index manifest chi tham chieu artifact ton tai va da audit pass.
