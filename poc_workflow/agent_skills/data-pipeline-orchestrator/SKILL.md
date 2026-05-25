---
name: data-pipeline-orchestrator
description: Dieu phoi workflow xu ly data RAGFlow tu dau den cuoi. Dung khi can nhan manifest PDF/XLSX goc, lap run plan, chia batch tuan tu, goi MinerU conversion, QA, repair loop, index RAGFlow va self-evolution.
metadata:
  risk: medium
  source: poc_workflow/agent_skills
---

# Data Pipeline Orchestrator

## When to Use

Dung skill nay khi parent yeu cau chay hoac thiet ke pipeline RAGFlow end-to-end cho PDF/XLSX, dac biet khi can tao thu tu goi skill, run manifest, retry policy hoac handoff JSON giua cac worker.

## When NOT to Use

- Khong dung de sua noi dung Markdown chi tiet; handoff viec do cho `rag-markdown-repairer`.
- Khong dung de ingest truc tiep vao RAGFlow khi chua co audit pass va human review.

## Workflow

1. Nhan `raw_manifest` va `run_config`.
2. Gan `run_id`, `source_id` on dinh cho tung PDF/XLSX.
3. Sap xep hang doi convert tuan tu: PDF truoc XLSX neu parent khong chi dinh, giu nguyen thu tu trong manifest khi co uu tien.
4. Tao `batch_manifest` gom moi batch nho, moi batch co toi da mot file dang convert active.
5. Handoff sang `mineru-source-converter`.
6. Sau convert, handoff sang `source-output-quality-auditor`.
7. Neu audit tra `needs_repair`, goi `rag-markdown-repairer`, sau do audit lai. Lap toi da 3 vong tru khi parent phe duyet tiep.
8. Khi audit dat, goi `ragflow-schema-indexer`.
9. Sau index, goi `data-skill-evolution` de ghi bai hoc va de xuat rule moi.

## Inputs

- `raw_manifest`: danh sach file goc, path, type, checksum neu co.
- `run_config`: ngon ngu, nguong QA, RAGFlow collection/dataset target, chunk policy, citation policy.
- `workspace_paths`: cac thu muc raw, converted, audit, repaired, rag_ready, evolution.

## Outputs / Handoff JSON

```json
{
  "run_id": "ragflow-run-YYYYMMDD-HHMMSS",
  "step": "plan",
  "status": "ready",
  "source_ids": ["src_001"],
  "artifacts": [
    {
      "artifact_id": "batch_manifest_001",
      "path": "poc_workflow/runs/<run_id>/batch_manifest.json",
      "type": "plan",
      "source_id": "src_001",
      "checksum": null
    }
  ],
  "quality_gates": {
    "source_ids_unique": true,
    "paths_exist": true,
    "sequential_queue_declared": true
  },
  "next_skill": "mineru-source-converter"
}
```

## Failure Handling

- Neu file khong ton tai hoac type khong phai PDF/XLSX, danh dau `blocked` va tra ve danh sach file loi.
- Neu thieu `run_config`, dung default an toan: convert tuan tu, QA bat buoc, max repair 3, citation bat buoc.
- Neu repair loop lap lai cung mot loi, dung pipeline va escalte parent voi issue id, source path va bang chung.
- Khong bo qua QA de di thang den index.

## Quality Gates

- Moi source co `source_id` duy nhat, path hop le va file type ro rang.
- Run plan co thu tu skill trung voi `registry.json`.
- Convert PDF/XLSX duoc khai bao tuan tu.
- Audit va repair loop co gioi han lap.
- Handoff JSON co du cac key ASCII: `run_id`, `step`, `status`, `source_ids`, `artifacts`, `quality_gates`, `next_skill`.
