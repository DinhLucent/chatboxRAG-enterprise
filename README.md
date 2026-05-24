# Chatbot Quy Trinh POC Workflow

This repository implements the POC blueprint for a governed internal chatbot knowledge workflow.

Important: **RAGFlow is the RAG engine.** The Python code in this repo is only the governance layer around source folders, manifest lifecycle, MinerU conversion, approval, sync, logging, and quality loop. The local JSONL index is a smoke-test fallback so the workflow can be tested before RAGFlow is running.

```text
Nguon tai lieu noi bo
-> Taxonomy / knowledge map
-> Manifest metadata
-> MinerU/native convert Markdown
-> Validate content + metadata + version
-> Human review / approve
-> RAGFlow-compatible active index
-> Chatbot answer with sources
-> Query log + feedback + knowledge gap
```

The implementation is intentionally runnable without a live RAGFlow server. It uses a local JSONL index as the default adapter so the lifecycle, rebuild, query logging, and quality loop can be tested immediately. `manifest + normalized Markdown/JSON` remain the source of truth.

## Quick Start

```powershell
python -m poc_workflow init --with-sample
python -m poc_workflow process-source
python -m poc_workflow manifest
python -m poc_workflow approve KT-QT-003 1.0 --approved-by "Truong phong Ky thuat"
python -m poc_workflow ask "Quy trinh xu ly su co ky thuat gom nhung buoc nao?"
python -m poc_workflow gaps
```

## User-Only Document Drop Workflow

If you only want to provide files and let an agent handle processing, use the dashboard `Upload` tab or drop documents into:

```text
inbox/
```

Optional subfolders:

```text
inbox/procedure/
inbox/vendor_document/
inbox/form_checklist/
inbox/faq_troubleshooting/
```

The dashboard does not run document processing directly. It shows the source queue and generates a structured prompt that an AI Agent/operator can use for the processing task.

Dashboard path:

```text
Upload tab -> choose files -> Upload -> Scan Source Folder
-> Queue
-> Generate Agent Prompt / Copy Prompt
-> Move To Workplace
-> Processing in .Workplace/processing/
-> Mark Done -> inbox/<category>/done/
-> Mark Failed -> inbox/<category>/failed/
```

For the local agent/operator workflow, the agent can still run:

```powershell
.\scripts\agent-ingest-inbox.ps1
```

This starts the MinerU background API if needed, creates draft metadata, copies files into `source/technical/<category>/`, converts/validates them, runs Markdown QA, and creates `pending_review` records. PDF/image files use MinerU; DOCX/XLSX files are converted natively to Markdown. It does not auto-approve documents into `active` unless an operator/agent explicitly runs an approval step.

MinerU agent tool:

```powershell
.\scripts\start-mineru-tool.ps1 -WithWebUI
.\scripts\status-mineru-tool.ps1
```

Default URLs:

- MinerU API: `http://127.0.0.1:8010`
- MinerU WebUI: `http://127.0.0.1:7860`

The automation uses the MinerU CLI/FastAPI path, aligned with the local Gradio/WebUI processing profile:

```text
mineru --path <file> --output <artifact_dir> --method auto --backend pipeline --formula true --table true --image-analysis true --start 0 --end 299 --lang ch --api-url http://127.0.0.1:8010
```

Per-file status is recorded server-side with these stages: `Waiting`, `Prepare`, `Check service`, `Submit`, `Queue`, `Parse`, `Download`, `Build outputs`, `QA check`, `Done`. QA writes `.Workplace/artifacts/<category>/<doc_id>_v<version>/qa_report.json` and can repair basic mojibake before the file reaches review.

Version policy: chatbot retrieval uses only the latest approved active version for the same document family. The family key is `canonical_doc_id` or `document_family_id` when metadata provides it, otherwise `doc_id`. Older versions are archived on approval and are excluded from the active local index and RAGFlow sync.

Use `MINERU_METHOD=ocr` only for controlled small batches of `ocr_required` PDFs; those files already failed automatic parsing and may be expensive to OCR.

OCR-required recovery workflow:

```powershell
.\scripts\process-ocr-required.ps1 -DryRun -Limit 1
.\scripts\process-ocr-required.ps1 -Limit 1
```

The script requeues a small batch from `inbox/<category>/ocr_required/`, forces the OCR-heavy MinerU profile, runs `prepare-inbox`, then runs `process-source --limit <Limit>`. `Limit` is intentionally capped at 5.

Detailed procedure: `docs/document-intake-procedure.md`.

Run tests:

```powershell
python -m pytest
```

Run the self-hosted product UI:

```powershell
.\scripts\start-app.ps1
```

Open `http://127.0.0.1:8088`.

Smoke check the web API after it starts:

```powershell
.\scripts\smoke-web.ps1
```

Run regression evaluation:

```powershell
python -m poc_workflow evaluate --provider local
```

Run the full deterministic quality gate before accepting a build:

```powershell
python -m poc_workflow quality-gate
.\scripts\quality-gate.ps1 -Mode local
```

The gate follows `intake -> gated -> verify -> accepted/escalated`, writes evidence to
`data/quality_gate/latest.json` and `docs/quality-gate-latest.md`, checks frontend
encoding/layout regressions, and does not call an LLM judge, run heavy OCR, or sync RAGFlow by default.

Audit suspicious taxonomy/doc_id metadata before approving or syncing documents:

```powershell
python -m poc_workflow audit-taxonomy
python -m poc_workflow plan-taxonomy-remediation
python -m poc_workflow apply-taxonomy-remediation
```

This writes `data/data_audit/taxonomy_latest.json` and `docs/taxonomy-audit-latest.md`.
It reports category/doc_id prefix mismatches and titles that suggest a different taxonomy.
`apply-taxonomy-remediation` defaults to dry-run and only changes safe `pending_review`
records when called with `--apply`; active records are left for reviewer approval.
Local quality-gate runs keep taxonomy findings as warnings, while production mode blocks on
unresolved active or pending taxonomy issues.

Check production readiness:

```powershell
python -m poc_workflow readiness
```

Export diagnostics for engineers or AI agents:

```powershell
python -m poc_workflow diagnostics
.\scripts\export-diagnostics.ps1
```

## Directory Layout

The `init` command creates:

- `.Workplace/processing/`: temporary per-file working area while an agent or MinerU is processing a document.
- `.Workplace/artifacts/`: per-document MinerU raw outputs, QA reports, and supporting artifacts.
- `inbox/`: user/agent intake drop folder, with `done/`, `ocr_required/`, and `failed/` subfolders under each category for Upload queue tracking.
- `source/`: original documents and sidecar metadata.
- `staging/`: documents copied for processing.
- `normalized/`: Markdown produced by MinerU, native DOCX/XLSX extraction, or text fallback.
- `manifest/records.json`: source of truth for metadata and lifecycle.
- `archive/`: old or retired source artifacts.
- `failed/`: files that failed validation/conversion.
- `ragflow_index/`: local RAGFlow-compatible JSONL index used for POC.
- `data/poc_quality.db`: SQLite logs for ingestion, query feedback, and knowledge gaps.

## Source Metadata

Every source document must have a sidecar metadata file named:

```text
<source-file-stem>.metadata.json
```

Example:

```json
{
  "doc_id": "KT-QT-003",
  "title": "Quy trinh xu ly su co ky thuat",
  "department": "technical",
  "category": "procedure",
  "source_type": "internal_procedure",
  "language": "vi",
  "version": "1.0",
  "effective_from": "2025-01-01",
  "review_at": "2025-12-31",
  "owner": "Phong Ky thuat",
  "access_group": "technical"
}
```

## Lifecycle

```text
new -> staging -> normalized -> pending_review -> active -> archived / retired
failed_review -> staging
```

Rules:

- Nothing enters `technical_active` unless it is `active` and approved.
- A newer active version archives the previous active version with the same `doc_id`.
- Archived/retired documents are not retrieved by default.
- Rebuild uses manifest records and normalized files, never the index as source of truth.

## Run The Downloaded RAGFlow Repo

The RAGFlow repo is expected at `refs/ragflow`. Start it with Docker:

```powershell
.\scripts\start-ragflow.ps1
.\scripts\status-ragflow.ps1
```

Default URLs:

- Web UI: `http://localhost:80`
- HTTP API: `http://localhost:9380`
- Admin API: `http://localhost:9381`

Stop it:

```powershell
.\scripts\stop-ragflow.ps1
```

## Sync Active Documents To RAGFlow

Create or find a `technical_active` dataset and chat assistant in RAGFlow:

```powershell
$env:RAGFLOW_BASE_URL="http://127.0.0.1:9380"
$env:RAGFLOW_API_KEY="<your-ragflow-api-key>"
$bootstrap = python -m poc_workflow bootstrap-ragflow | ConvertFrom-Json
$env:RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID=$bootstrap.env.RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID
$env:RAGFLOW_CHAT_ID=$bootstrap.env.RAGFLOW_CHAT_ID
```

Then sync active normalized Markdown files:

```powershell
.\scripts\sync-active-to-ragflow.ps1
```

Use `--delete-all` only when intentionally rebuilding the RAGFlow dataset from manifest source of truth.

## Web App Surfaces

The self-hosted dashboard exposes:

- Chat over active knowledge with citations and feedback.
- Manifest records and lifecycle status.
- Pending review approval/rejection.
- Knowledge gaps and recent query logs.
- Incident center, diagnostic summary, and runtime troubleshooting report.
- User-facing service status for maintenance, offline backend, and degraded operation.
- Ingestion run history.
- System health for RAGFlow, MinerU, LLM config, manifest, and quality logs.
- Regression evaluation report for retrieval, citation, no-answer, and latency KPIs.

Important production behavior:

- `provider=auto` tries RAGFlow first when `RAGFLOW_CHAT_ID` or `RAGFLOW_SEARCH_ID` is configured.
- `provider=ragflow` fails closed to a no-source answer if RAGFlow is unavailable or not configured.
- `provider=local` is only an offline fallback for development and smoke tests.

Protected APIs are fail-closed when auth is required:

```powershell
$env:KB_REQUIRE_AUTH="true"
$env:KB_AUTH_TOKEN="<long-random-token>"
.\scripts\start-app.ps1
```

The dashboard stores this token in browser local storage after the first prompt.

For production, disable local retrieval fallback so `provider=auto` fails closed if RAGFlow is not configured or unavailable:

```powershell
$env:KB_ENABLE_LOCAL_FALLBACK="false"
$env:KB_ALLOWED_PROVIDERS="auto,ragflow"
```

## Regression Evaluation

Default cases live in `eval/regression_cases.json`:

```json
[
  {
    "id": "procedure-incident-flow",
    "query": "Quy trinh xu ly su co ky thuat gom nhung buoc nao?",
    "should_answer": true,
    "expected_doc_ids": ["KT-QT-003"],
    "expected_category": "procedure"
  }
]
```

Run:

```powershell
python -m poc_workflow evaluate --provider local
```

Reports are saved to `data/evaluation/latest.json` and timestamped JSON files.

Measured POC KPIs:

- Top-3 expected document hit rate.
- Citation accuracy.
- No-answer accuracy for missing knowledge.
- Latency p95 against the configured target.

## Production-Style Container Run

Set a token first:

```powershell
$env:KB_AUTH_TOKEN="change-me-long-random-token"
.\scripts\start-production.ps1
```

The Compose file mounts `source/`, `manifest/`, `normalized/`, `data/`, `eval/`, and related workflow directories into `/workspace`.

The Docker image does not install MinerU by default because the core model package is large. To include MinerU in the app image:

```powershell
$env:INSTALL_MINERU="true"
.\scripts\start-production.ps1
```

Alternatively, run ingestion on the host where `mineru` is already installed, then run the app container against the mounted `normalized/` and `manifest/` source of truth.

Back up source-of-truth files before large document updates:

```powershell
.\scripts\backup-workspace.ps1
```

See:

- `docs/README.md`
- `docs/architecture.md`
- `docs/demo-end-to-end-architecture.md`
- `docs/acceptance-loop-check-2026-05-23.md`
- `docs/freellmapi-integration.md`
- `docs/local-runtime-status.md`
- `docs/vercel-demo.md`
- `docs/production-runbook.md`
- `docs/security-production-checklist.md`
- `docs/oss-compliance.md`

## Human Review Checklist

Before approval, verify:

- Required metadata is present.
- Markdown/JSON output is not empty.
- Important tables/images/OCR text are readable.
- Taxonomy is correct.
- Version is newer than the active version for the same `doc_id`.
- Source path opens.
- The document is allowed to be used by the chatbot.

## Prompt Policy

The chatbot layer should use these rules:

- Answer only from retrieved context.
- Do not guess when the context is insufficient.
- Always cite document sources.
- If sources conflict, prefer active documents with newer versions.
- If no valid source exists, answer: `Không tìm thấy căn cứ trong tài liệu hiện hành.`

## Optional LLM Answering

By default, `ask` returns an extractive answer from retrieved active chunks. To call an OpenAI-compatible chat completions API after retrieval:

```powershell
$env:POC_LLM_BASE_URL="https://api.openai.com/v1"
$env:POC_LLM_API_KEY="<api-key>"
$env:POC_LLM_MODEL="<chat-model>"
python -m poc_workflow ask "Quy trinh xu ly su co gom nhung buoc nao?" --use-llm
```

If the LLM call fails, the CLI falls back to the source-backed extractive answer and reports `llm_error`.

## Optional FreeLLMAPI Proxy

FreeLLMAPI can run as a local OpenAI-compatible proxy for free-tier testing:

```text
Chatbot -> http://127.0.0.1:3001/v1 -> FreeLLMAPI -> configured provider
```

The repo is cloned under:

```text
refs/freellmapi/
```

Start FreeLLMAPI, retrieve its unified key, then configure the chatbot:

```powershell
$freeKey = (Invoke-RestMethod -Uri http://127.0.0.1:3001/api/settings/api-key).apiKey
$env:POC_LLM_BASE_URL="http://127.0.0.1:3001/v1"
$env:POC_LLM_API_KEY=$freeKey
$env:POC_LLM_MODEL="auto"
```

Run a source-backed LLM smoke test:

```powershell
python -m poc_workflow ask "Quy trinh xu ly su co ky thuat gom nhung buoc nao?" --provider local --use-llm
```

Details: `docs/freellmapi-integration.md`.
