# RAGFlow Data Workflow Agent Skills

Thu muc nay chua bo skill noi bo cho workflow xu ly du lieu RAGFlow tu file goc den thu muc san sang ingest.

## Thu tu goi skill

1. `data-pipeline-orchestrator`: nhan yeu cau, tao run plan, chia batch va dieu phoi handoff.
2. `mineru-source-converter`: convert PDF/XLSX bang MinerU theo thu tu, khong chay song song khi chua duoc phe duyet.
3. `source-output-quality-auditor`: doi chieu PDF/Excel goc voi output da convert, tao danh sach loi co bang chung.
4. `rag-markdown-repairer`: sua Markdown/schema/citation theo ket qua audit va lap lai den khi dat nguong.
5. `ragflow-schema-indexer`: dong goi thu muc RAG-ready, tao schema/index/citation manifest cho RAGFlow.
6. `data-skill-evolution`: sau moi loop, cap nhat bai hoc, rule va de xuat sua skill/registry neu can.

## Nguyen tac van hanh

- Chi xu ly trong workspace duoc parent giao; khong sua API/UI hoac file ngoai pham vi.
- Moi file goc phai co `source_id` on dinh de lien ket PDF/XLSX, converted output, audit issue, repair patch va citation.
- PDF va XLSX qua MinerU theo hang doi tuan tu de tranh tranh chap GPU/IO va log kho truy vet.
- QA luon doc file goc truoc khi ket luan output dung; khong chi lint Markdown.
- Repair loop ket thuc khi tat ca quality gate bat buoc dat hoac khi can parent quyet dinh.
- Handoff giua cac skill dung JSON co key ASCII de parent co the parse bang tool don gian.

## Artifact mac dinh

- `raw/`: PDF, XLSX va metadata goc.
- `converted/`: MinerU ZIP/folder day du, selected Markdown, `mineru_artifact_index.json`, `content_list_v2/content_list`, `middle.json`, `model.json`, images, origin PDF, extra JSON/log/sidecar khac va table/flowchart snapshots.
- `audit/`: bao cao doi chieu, issue list, bang chung.
- `repaired/`: Markdown da sua, citation anchors, table fixes.
- `rag_ready/`: schema, index, manifest va chunks san sang ingest vao RAGFlow.
- `evolution/`: lessons learned, rule candidates, change log cho skill.

## File trong bo skill

- `registry.json`: khai bao thu tu workflow, step mapping va handoff contract.
- Moi thu muc con la mot Agent Skill doc lap co `SKILL.md`.
