# Acceptance Loop Check - 2026-05-23

Status: accepted for local POC/demo readiness.

This report records the end-to-end loop-check requested for the current local product state.

## Scope

Checked:

- 69-case local retrieval regression suite.
- Python unit/integration tests.
- Web API health and chat.
- Vercel demo proxy health, chat, and feedback.
- FreeLLMAPI local proxy availability.
- LLM answer smoke through FreeLLMAPI.
- Docker Compose configuration parse.
- Production readiness checklist.

Not claimed:

- Full production readiness.
- Live RAGFlow retrieval.
- Live Vercel deployment.
- Public tunnel verification.

## 69-Case Regression Suite

Case file:

```text
eval/regression_cases_69.json
```

Report file:

```text
data/evaluation/2026-05-23T07-04-53+00-00.json
data/evaluation/latest.json
```

Command:

```powershell
python -m poc_workflow evaluate --provider local --cases eval\regression_cases_69.json
```

Result:

```text
total_cases: 69
passed_cases: 69
top3_doc_hit_rate: 1.0
citation_accuracy: 1.0
no_answer_accuracy: 1.0
latency_pass_rate: 1.0
p95_latency_ms: 0
pass: true
```

Coverage shape:

```text
50 positive cases -> expected active source KT-QT-003
19 negative cases -> expected no-source answer / knowledge gap
```

## Automated Test Checklist

| Check | Command | Result |
| --- | --- | --- |
| JSON validation for 69 cases | `python -m json.tool eval\regression_cases_69.json` | Pass |
| Case count | Python count script | Pass, 69 cases |
| Python tests | `python -m pytest -q` | Pass, 17 passed |
| Docker Compose config | `docker compose -f docker-compose.app.yml config --quiet` | Pass |
| Vercel API syntax | `node --check api/chat.js; node --check api/feedback.js; node --check api/health.js; node --check lib/proxy.js; node --check app.js` | Pass |

## Runtime Smoke Checklist

| Check | Evidence | Result |
| --- | --- | --- |
| Chatbot health | `GET http://127.0.0.1:8088/api/health` | Pass |
| Active documents | Health returned `active_docs=1` | Pass |
| Local chat | `POST /api/chat`, `provider=local`, `use_llm=false` | Pass |
| Citation required | Chat returned `citation_count=1`, `first_doc=KT-QT-003` | Pass |
| Vercel proxy health | Node handler call to `vercel-demo/api/health.js` | Pass, HTTP 200 |
| Vercel proxy chat | Node handler call to `vercel-demo/api/chat.js` | Pass, HTTP 200, citation count 1 |
| Vercel proxy feedback | Node handler call to `vercel-demo/api/feedback.js` | Pass, HTTP 200 |
| FreeLLMAPI ping | `GET http://127.0.0.1:3001/api/ping` | Pass, `ok` |
| FreeLLMAPI models | `GET http://127.0.0.1:3001/v1/models` | Pass, 90 models returned |
| LLM smoke | `POST /api/chat`, `use_llm=true` | Pass, `llm_used=true`, citation count 1, latency 1381 ms |

## Current Runtime Snapshot

```text
Chatbot dashboard: http://127.0.0.1:8088
FreeLLMAPI proxy:  http://127.0.0.1:3001
LLM configured:    true
Active docs:       1
Pending review:    0
Open gaps:         28
Readiness ready:   false
```

## Production Readiness Findings

Command:

```powershell
python -m poc_workflow readiness
```

Result summary:

| Check | Status | Detail |
| --- | --- | --- |
| operator_auth | warn | Set `KB_REQUIRE_AUTH=true` and `KB_AUTH_TOKEN` for production. |
| ragflow_config | fail | RAGFlow base URL/API key/dataset/chat or search ID are not configured. |
| mineru_available | pass | MinerU CLI is available. |
| active_documents | pass | 1 active approved document. |
| latest_evaluation | pass | Latest 69-case evaluation passed. |
| local_fallback_disabled | warn | Set `KB_ENABLE_LOCAL_FALLBACK=false` in production. |

Conclusion:

```text
Local POC/demo path: pass
Production readiness: not yet pass
```

## Remaining Go/No-Go Items

Before production pilot:

- Configure and verify RAGFlow live dataset/chat/search.
- Enable operator auth.
- Disable local fallback for production.
- Configure approved LLM provider policy.
- Run 69-case suite against `provider=ragflow`.
- Deploy or tunnel Vercel demo and verify from an external browser.
- Add real company documents beyond the current single sample procedure.
- Review and close knowledge gaps created by negative tests.

## Acceptance Summary

The current local system passed the requested 69-case loop-check and demo API checklist. It is ready for controlled local demo rehearsal. It is not yet ready to be presented as production-complete because RAGFlow production integration and auth hardening are intentionally still open.

