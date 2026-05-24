# Local Runtime Status

Last verified: May 23, 2026.

## Running Services

```text
Chatbot dashboard:  http://127.0.0.1:8088
FreeLLMAPI proxy:   http://127.0.0.1:3001
```

## Chatbot Configuration

The chatbot process was restarted with:

```powershell
$env:POC_LLM_BASE_URL = "http://127.0.0.1:3001/v1"
$env:POC_LLM_MODEL = "auto"
```

The FreeLLMAPI unified API key is not documented here because it is a local secret. Retrieve it with:

```powershell
$freeKey = (Invoke-RestMethod -Uri http://127.0.0.1:3001/api/settings/api-key).apiKey
```

## Health Check

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8088/api/health | ConvertTo-Json -Depth 5
```

Expected relevant fields:

```json
{
  "llm": {
    "configured": true,
    "base_url": "http://127.0.0.1:3001/v1",
    "model": "auto"
  },
  "manifest": {
    "records": 1,
    "active": 1,
    "pending_review": 0
  }
}
```

## Smoke Test Result

Command:

```powershell
python -m poc_workflow ask "Quy trinh xu ly su co ky thuat gom nhung buoc nao?" --provider local --use-llm
```

Observed important result:

```json
{
  "provider": "local",
  "llm_used": true,
  "llm_error": null,
  "citations": [
    {
      "doc_id": "KT-QT-003",
      "version": "1.0"
    }
  ]
}
```

The local FreeLLMAPI request routed successfully through `llm7/codestral-latest` during testing.

## Known Gaps

- RAGFlow is still not configured in this local runtime.
- Production readiness is not complete until RAGFlow API keys, dataset, chat/search ID, operator auth, and production provider policy are configured.
- FreeLLMAPI anonymous providers are suitable only for demos and smoke tests.

## Open Dashboards

```powershell
Start-Process "http://127.0.0.1:8088"
Start-Process "http://127.0.0.1:3001"
```

