# FreeLLMAPI Integration

FreeLLMAPI is used as an optional local OpenAI-compatible LLM proxy. It lets the chatbot call one local endpoint while FreeLLMAPI routes to configured providers.

Important: FreeLLMAPI is not a guaranteed no-key LLM. It works best when you add provider free-tier API keys in its dashboard. Anonymous providers can work for demos, but they may return 429/500 or disappear without notice.

## Local Location

The upstream repo is cloned as a reference dependency:

```text
refs/freellmapi/
```

It is intentionally kept outside the owned app code. `refs/` is ignored by git.

## Verified Local Setup

Verified on May 23, 2026:

- Node.js: available.
- `npm install`: successful.
- `npm run build`: successful.
- `npm run test -w server`: `104 passed`.
- Server port: `3001`.
- Dashboard/API: `http://127.0.0.1:3001`.
- OpenAI-compatible base URL: `http://127.0.0.1:3001/v1`.

Observed provider behavior during the local smoke test:

- `pollinations` with placeholder key `anonymous`: upstream returned `500`.
- `llm7` with placeholder key `unused`: worked for a short test and routed through `llm7/codestral-latest`.

Treat anonymous providers as demo-only.

## First-Time Setup

```powershell
cd D:\MyProject\demo-chatbot-engineerworkflow\refs\freellmapi
npm install

$key = node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
@"
ENCRYPTION_KEY=$key
PORT=3001
"@ | Set-Content .env -Encoding UTF8

npm run build
npm run test -w server
```

## Start FreeLLMAPI

```powershell
cd D:\MyProject\demo-chatbot-engineerworkflow\refs\freellmapi
node server/dist/index.js
```

The app serves both the dashboard and API on:

```text
http://127.0.0.1:3001
```

The OpenAI-compatible endpoint is:

```text
http://127.0.0.1:3001/v1/chat/completions
```

## Get The Unified API Key

```powershell
$freeKey = (Invoke-RestMethod -Uri http://127.0.0.1:3001/api/settings/api-key).apiKey
$freeKey
```

Do not commit this key. It is generated locally and stored in FreeLLMAPI's SQLite database.

## Add Provider Keys

Open:

```text
http://127.0.0.1:3001
```

Go to the `Keys` page and add providers such as:

- Google AI Studio
- Groq
- OpenRouter
- Mistral
- Cerebras
- SambaNova
- GitHub Models
- Cloudflare

For quick anonymous experiments, the local test used:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:3001/api/keys `
  -Method Post `
  -ContentType 'application/json' `
  -Body (@{
    platform = 'llm7'
    key = 'unused'
    label = 'anonymous-local-test'
  } | ConvertTo-Json)
```

This is not a production-grade provider setup.

## Configure The Chatbot To Use FreeLLMAPI

```powershell
$freeKey = (Invoke-RestMethod -Uri http://127.0.0.1:3001/api/settings/api-key).apiKey

$env:POC_LLM_BASE_URL = "http://127.0.0.1:3001/v1"
$env:POC_LLM_API_KEY = $freeKey
$env:POC_LLM_MODEL = "auto"
$env:PYTHONIOENCODING = "utf-8"
```

Then start or restart the chatbot:

```powershell
cd D:\MyProject\demo-chatbot-engineerworkflow
.\scripts\start-app.ps1
```

## Test Through CLI

```powershell
python -m poc_workflow ask "Quy trinh xu ly su co ky thuat gom nhung buoc nao?" --provider local --use-llm
```

Expected important fields:

```json
{
  "provider": "local",
  "llm_used": true,
  "llm_error": null
}
```

The answer must still include source citation from the active document, for example:

```text
Nguon: KT-QT-003 v1.0
```

## Test Through Web API

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8088/api/chat `
  -Method Post `
  -ContentType 'application/json' `
  -Body (@{
    query = 'Quy trinh xu ly su co ky thuat gom nhung buoc nao?'
    provider = 'local'
    use_llm = $true
    user_id = 'smoke-test'
  } | ConvertTo-Json -Depth 5)
```

Expected important fields:

```json
{
  "llm_used": true,
  "citations": [
    {
      "doc_id": "KT-QT-003",
      "version": "1.0"
    }
  ]
}
```

## Current Local Runtime

If started by the assistant, runtime files are stored in ignored folders:

```text
refs/freellmapi/.runtime/freellmapi.pid
.pytest-tmp/kb-web-8088.pid
.runtime/kb-web-8088.err.log
.runtime/kb-web-8088.out.log
```

Check running ports:

```powershell
Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue
```

Stop the current local FreeLLMAPI process:

```powershell
$pidValue = Get-Content D:\MyProject\demo-chatbot-engineerworkflow\refs\freellmapi\.runtime\freellmapi.pid
Stop-Process -Id ([int]$pidValue) -Force
```

Stop the current local chatbot process:

```powershell
$pidValue = Get-Content D:\MyProject\demo-chatbot-engineerworkflow\.pytest-tmp\kb-web-8088.pid
Stop-Process -Id ([int]$pidValue) -Force
```

## Security Notes

- Do not use anonymous free providers for confidential company documents.
- Free-tier providers can change limits or terms without notice.
- Provider keys must stay in FreeLLMAPI storage or a secret store, never in git.
- For production, prefer a paid or enterprise-approved LLM provider.
- The chatbot sends only the question plus retrieved chunks, not the full repository.

## Recommended Provider Strategy

For demo:

```text
FreeLLMAPI + free-tier keys + model=auto
```

For internal pilot:

```text
RAGFlow retrieval + approved low-cost paid LLM API
```

For production:

```text
RAGFlow retrieval + enterprise-approved LLM provider + auth + audit + monitoring
```

