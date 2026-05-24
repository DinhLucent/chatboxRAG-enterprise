# Production Runbook

## Local Product App

```powershell
python -m poc_workflow init --with-sample
python -m poc_workflow process-source
python -m poc_workflow approve KT-QT-003 1.0 --approved-by "Truong phong Ky thuat"
python -m poc_workflow evaluate --provider local
python -m poc_workflow readiness
.\scripts\start-app.ps1
```

Open `http://127.0.0.1:8088`.

## Optional FreeLLMAPI LLM Proxy

FreeLLMAPI can be used as a local OpenAI-compatible LLM proxy for demo and cost testing.

```powershell
cd D:\MyProject\demo-chatbot-engineerworkflow\refs\freellmapi
npm install
npm run build
node server/dist/index.js
```

Open `http://127.0.0.1:3001`, add provider keys, then configure the chatbot:

```powershell
$freeKey = (Invoke-RestMethod -Uri http://127.0.0.1:3001/api/settings/api-key).apiKey
$env:POC_LLM_BASE_URL="http://127.0.0.1:3001/v1"
$env:POC_LLM_API_KEY=$freeKey
$env:POC_LLM_MODEL="auto"
.\scripts\start-app.ps1
```

Smoke test:

```powershell
python -m poc_workflow ask "Quy trinh xu ly su co ky thuat gom nhung buoc nao?" --provider local --use-llm
```

For details and caveats, see `docs/freellmapi-integration.md`.

## Container App

```powershell
$env:KB_AUTH_TOKEN="change-me-long-random-token"
$env:KB_ENABLE_LOCAL_FALLBACK="false"
$env:KB_ALLOWED_PROVIDERS="auto,ragflow"
.\scripts\start-production.ps1
.\scripts\status-production.ps1
```

Set `$env:INSTALL_MINERU="true"` before `start-production.ps1` if the app container itself must run MinerU conversion. Leave it false if ingestion runs on a host or worker where MinerU is already installed.

Stop:

```powershell
.\scripts\stop-production.ps1
```

## RAGFlow Integration

1. Start RAGFlow from `refs/ragflow`.
2. Generate an API key.
3. Bootstrap `technical_active` dataset and chat assistant:

```powershell
$env:RAGFLOW_BASE_URL="http://127.0.0.1:9380"
$env:RAGFLOW_API_KEY="<ragflow-api-key>"
$bootstrap = python -m poc_workflow bootstrap-ragflow | ConvertFrom-Json
$env:RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID=$bootstrap.env.RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID
$env:RAGFLOW_CHAT_ID=$bootstrap.env.RAGFLOW_CHAT_ID
```

4. Sync approved active documents:

```powershell
.\scripts\sync-active-to-ragflow.ps1
```

5. Configure `RAGFLOW_CHAT_ID` or `RAGFLOW_SEARCH_ID` before using `provider=auto` or `provider=ragflow`.
6. Run readiness before pilot:

```powershell
python -m poc_workflow evaluate --provider ragflow
python -m poc_workflow readiness --check-network
```

Production readiness should have no `fail` checks before enabling users.

## Incident And Diagnostics Workflow

Before a demo or pilot, export diagnostics:

```powershell
python -m poc_workflow diagnostics --no-logs
.\scripts\export-diagnostics.ps1 -NoLogs
```

If the system behaves incorrectly:

1. Open the local dashboard `System -> Incident Center`.
2. Review open incidents and diagnostic recommendations.
3. Check failed ingestion runs for document pipeline issues.
4. Check knowledge gaps for missing source documents.
5. Re-run `python -m pytest -q`.
6. Re-run `python -m poc_workflow evaluate --provider local`.
7. Resolve incidents only after verification passes.

Optional alert webhook:

```powershell
$env:KB_ALERT_WEBHOOK_URL="https://example.com/webhook"
```

Details: `docs/operations-observability.md`.

## LLM Runtime Policy

For demo, the chatbot may use:

```text
provider=local + use_llm=true + FreeLLMAPI
```

For pilot/production, prefer:

```text
provider=auto/ragflow + enterprise-approved LLM provider
```

Free anonymous providers should not be used with confidential company documents.

## Document Update Workflow

```text
source file + metadata sidecar
-> process-source
-> pending_review
-> human checklist
-> approve
-> local index rebuild
-> RAGFlow sync
-> evaluate regression cases
```

## Recovery

RAGFlow index is rebuildable. The source of truth is:

- `manifest/records.json`
- `normalized/`
- `source/`
- `eval/regression_cases.json`
- `data/poc_quality.db`

To recover the local fallback index:

```powershell
python -m poc_workflow rebuild-index
python -m poc_workflow evaluate --provider local
```

Create a backup before large document updates:

```powershell
.\scripts\backup-workspace.ps1
```

To recover RAGFlow active dataset, sync from active manifest records:

```powershell
.\scripts\sync-active-to-ragflow.ps1 -DeleteAll
```
