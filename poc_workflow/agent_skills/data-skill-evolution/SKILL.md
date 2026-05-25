---
name: data-skill-evolution
description: Ghi nhan bai hoc sau moi loop xu ly data RAGFlow va de xuat cap nhat rule, quality gate, registry hoac skill. Dung sau convert/audit/repair/index de cai thien workflow ma khong tu y sua ngoai pham vi.
metadata:
  risk: low
  source: poc_workflow/agent_skills
---

# Data Skill Evolution

## When to Use

Dung skill nay sau moi vong pipeline hoac khi co loi lap lai trong MinerU conversion, QA, repair hoac RAGFlow indexing.

## When NOT to Use

- Khong dung de sua skill/registry truc tiep neu parent chua phe duyet.
- Khong dung de thay the audit hay repair; chi ghi bai hoc va de xuat rule.
- Khong tao rule moi neu khong co bang chung tu run artifact.

## Workflow

1. Thu thap `run_plan`, `conversion_log`, `audit_report`, `repair_log`, `index_manifest`.
2. Rut ra pattern: file type gay loi, rule QA thieu, repair lap lai, citation gap, schema gap.
3. Phan loai de xuat: `rule_update`, `quality_gate_update`, `registry_update`, `skill_update`, `source_requirement`.
4. Ghi `evolution_report.json` vao thu muc evolution cua run.
5. Neu can sua skill/registry, tao `registry_patch_request` hoac `skill_patch_request`; khong tu y sua neu parent chua giao.
6. Handoff ve orchestrator/parent voi ket luan no-op neu khong co thay doi can thiet.

## Inputs

- `run_plan`: ke hoach ban dau va config.
- `conversion_log`: MinerU command/options/warning.
- `audit_report`: issue va quality gate.
- `repair_log`: patch da ap dung va loi lap lai.
- `index_manifest`: artifact RAG-ready.

## Outputs / Handoff JSON

```json
{
  "run_id": "ragflow-run-YYYYMMDD-HHMMSS",
  "step": "evolve",
  "status": "passed",
  "source_ids": ["src_001"],
  "artifacts": [
    {
      "artifact_id": "evolution_report_src_001",
      "path": "evolution/src_001/evolution_report.json",
      "type": "evolution",
      "source_id": "src_001",
      "checksum": "sha256-or-null"
    }
  ],
  "quality_gates": {
    "logs_reviewed": true,
    "repeat_issues_checked": true,
    "actionable_rules_recorded": true,
    "no_unapproved_file_changes": true
  },
  "next_skill": "done"
}
```

## Failure Handling

- Neu log thieu, ghi `insufficient_evidence` thay vi tao rule moi yeu.
- Neu de xuat doi workflow co nguy co anh huong API/UI hoac thu muc ngoai pham vi, danh dau `requires_parent_approval`.
- Neu cung mot issue lap lai nhieu run, nang severity cua de xuat len `major`.
- Neu khong co bai hoc moi, ghi no-op ro rang voi ly do.

## Quality Gates

- Moi de xuat co bang chung tu run artifact, khong dua tren cam tinh.
- Key JSON dung ASCII va co `proposal_id`, `proposal_type`, `evidence`, `target_file`, `risk`, `approval_required`.
- Khong tu dong sua skill/registry khi nhiem vu hien tai chi yeu cau bao cao.
- Bao cao phan biet loi source, loi MinerU, loi repair, loi schema va loi orchestration.
