# Quy Trinh Nhan Va Nap Tai Lieu

Muc tieu: nguoi dung chi can cung cap tai lieu. Dashboard chi quan ly hang cho va tao prompt co cau truc; AI agent/operator xu ly phan con lai va dua tai lieu vao hang `pending_review`.

## Vai Tro

- Nguoi cung cap tai lieu: tha file vao `inbox/`.
- AI agent / operator: nhan prompt tu dashboard, chay workflow intake, kiem tra loi, tao metadata nhap.
- Nguoi duyet: approve tai lieu tu `pending_review` sang `active`.

## Noi Dat Tai Lieu

Co 2 cach dua tai lieu vao inbox.

### Cach 1: Dashboard

Mo dashboard va vao tab `Upload`.

```text
Upload
-> chon file
-> chon category hoac de Auto classify
-> Upload
-> Scan Source Folder
-> Generate Agent Prompt
-> Copy Prompt
-> Move To Workplace
-> Processing trong .Workplace/processing/
-> Mark Failed de dua file ve inbox/<category>/failed/
```

Dashboard khong tu chay MinerU/RAGFlow va khong tu dua tai lieu vao `pending_review`. Upload page chi tao nhiem vu cho AI Agent va theo doi Queue / Processing / Done / OCR Required / Failed. Trang Upload khong co nut dua tai lieu sang `Active`; tai lieu chi `Done` khi agent pipeline xu ly xong va dua file ve `inbox/<category>/done/`.

### Cach 2: Thu Muc

```text
inbox/
```

Co the tach nhanh theo nhom:

```text
inbox/procedure/
inbox/vendor_document/
inbox/form_checklist/
inbox/faq_troubleshooting/
```

Neu khong tach dung nhom, agent se doan category tu ten file va duong dan.

## File Duoc Ho Tro

```text
.md, .txt, .pdf, .docx, .pptx, .xlsx, .png, .jpg, .jpeg
```

## Workflow Agent

Sau khi nhan prompt, agent/operator co the chay workflow local:

```powershell
.\scripts\agent-ingest-inbox.ps1
```

Lenh nay thuc hien:

```text
init workspace
-> prepare-inbox
-> tao metadata nhap
-> copy file sang source/technical/<category>/
-> process-source
-> PDF/anh scan qua MinerU; DOCX/XLSX convert native sang Markdown
-> QA Markdown output
-> validate metadata + normalized output
-> tao record pending_review
```

Mac dinh khong co tai lieu nao duoc dua vao `active` tu dong. Neu demo/operator yeu cau auto-load, agent co the chay buoc approve rieng sau khi normalized output hop le; Upload page van khong co nut set Active thu cong.

## Chinh Sach Version

Chatbot chi su dung version moi nhat da duoc approve cho cung mot document family. Family duoc xac dinh theo:

```text
canonical_doc_id -> document_family_id -> doc_id
```

Neu approve version moi hon, version active cu cung family se duoc chuyen sang `archived`. Local index va RAGFlow sync cung loc latest active theo family, nen du lieu version cu khong duoc dung de tra loi chatbot.

Trong luc xu ly, tung file duoc copy vao:

```text
.Workplace/processing/<category>/<doc_id>_v<version>/input/
```

Output phu cua MinerU duoc giu tai:

```text
.Workplace/artifacts/<category>/<doc_id>_v<version>/
```

Moi file co status step-by-step luu trong `manifest/agent_prompt_queue.json`, de Upload page refresh van thay dung tien do:

```text
Waiting -> Prepare -> Check service -> Submit -> Queue -> Parse -> Download -> Build outputs -> QA check -> Done
```

Pipeline co buoc QA sau khi build Markdown. Bao cao QA nam tai:

```text
.Workplace/artifacts/<category>/<doc_id>_v<version>/qa_report.json
```

QA se chan Markdown rong, output con ky tu loi encoding/replacement, va tu sua loi mojibake co ban neu co the sua an toan. Neu QA fail, tai lieu khong vao `pending_review`.

Neu PDF da thu MinerU nhung khong sinh duoc Markdown, va fallback doc text PDF cung khong tim thay text nhung, agent phan loai file vao:

```text
inbox/<category>/ocr_required/
```

Nhom nay can OCR/preprocess thu cong hoac cau hinh MinerU/OCR nang hon; khong retry tu dong trong queue thong thuong de tranh treo may.

## Che Do MinerU

Automation khong upload truc tiep qua Gradio WebUI `http://127.0.0.1:7860/`, nhung no dung cung MinerU CLI/FastAPI engine va can chay voi profile tuong duong WebUI local:

```text
mineru --path <file> --output <artifact_dir> --method <MINERU_METHOD> --backend pipeline --formula true --table true --image-analysis true --start 0 --end 299 --lang ch --api-url http://127.0.0.1:8010
```

Mac dinh:

```powershell
$env:MINERU_METHOD = "auto"
$env:MINERU_BACKEND = "pipeline"
$env:MINERU_FORMULA = "true"
$env:MINERU_TABLE = "true"
$env:MINERU_IMAGE_ANALYSIS = "true"
$env:MINERU_MAX_PAGES = "300"
```

Neu can chay OCR nang cho nhom `ocr_required`, chay theo batch nho va ep method:

```powershell
.\scripts\process-ocr-required.ps1 -DryRun -Limit 1
.\scripts\process-ocr-required.ps1 -Limit 1
```

Script nay requeue batch nho tu `inbox/<category>/ocr_required/`, ep `MINERU_METHOD=ocr`, chay `prepare-inbox`, roi chay `process-source --limit <Limit>`. `Limit` bi gioi han 1-5 de tranh treo may. Khong nen retry toan bo `ocr_required` cung luc vi day la nhom PDF scan/image da fail o che do tu dong.

## Kiem Tra Truoc Khi Duyet

Nguoi duyet kiem tra tren dashboard hoac manifest:

- Metadata dung: `doc_id`, `title`, `category`, `version`, `owner`.
- Markdown/JSON khong rong.
- Bang, anh scan, OCR doc duoc.
- Dung taxonomy.
- Version moi hon ban active neu cung `doc_id`.
- Tai lieu duoc phep dua vao chatbot.

Chay audit taxonomy/doc_id truoc khi duyet hang loat:

```powershell
python -m poc_workflow audit-taxonomy
python -m poc_workflow plan-taxonomy-remediation
python -m poc_workflow apply-taxonomy-remediation
```

Lenh nay tao `data/data_audit/taxonomy_latest.json` va `docs/taxonomy-audit-latest.md`.
Neu report bao `title suggests ...` hoac `category/doc_id prefix mismatch`, can sua metadata/source path va rebuild index truoc khi sync RAGFlow.
`apply-taxonomy-remediation --apply` chi tu dong sua record `pending_review` khong conflict; record `active` van phai review vi co the doi citation/doc_id dang phuc vu chatbot.

Approve:

```powershell
python -m poc_workflow approve <DOC_ID> <VERSION> --approved-by "Ten nguoi duyet"
```

Sau approve:

```powershell
python -m poc_workflow evaluate --provider local
.\scripts\sync-active-to-ragflow.ps1
python -m poc_workflow evaluate --provider ragflow
```

## Metadata Tuy Chon

Neu muon chi dinh chinh xac metadata, dat file sidecar trong `inbox/`:

```text
inbox/procedure/KT-QT-003_v1.2.pdf
inbox/procedure/KT-QT-003_v1.2.metadata.json
```

Vi du:

```json
{
  "doc_id": "KT-QT-003",
  "title": "Quy trinh xu ly su co ky thuat",
  "department": "technical",
  "category": "procedure",
  "source_type": "internal_procedure",
  "language": "vi",
  "version": "1.2",
  "effective_from": "2025-01-01",
  "review_at": "2025-12-31",
  "owner": "Phong Ky thuat",
  "access_group": "technical"
}
```

Neu khong co sidecar, agent se tao metadata nhap.

## Nguyen Tac An Toan

- AI agent duoc tao metadata, convert, validate, va dua vao `pending_review`.
- AI agent khong tu approve tai lieu thanh `active`.
- Chatbot chi tra loi tu tai lieu `active`.
- Neu khong co nguon active hop le, bot tra loi: `Không tìm thấy căn cứ trong tài liệu hiện hành.`
