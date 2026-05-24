# Operations, Incidents, And Diagnostics

This layer exists so an engineer or AI agent can quickly see what failed, where to look, and what to do next.

## What Is Logged

Operational data is stored in `data/poc_quality.db`:

- `query_logs`: every chat request, retrieved documents, citation flag, latency, feedback.
- `knowledge_gaps`: missing or wrong knowledge reported by retrieval or users.
- `ingestion_runs`: source processing, approval, RAGFlow sync, and failure events.
- `incidents`: operational failures that require attention.

Runtime process logs are written under `.runtime/` by the startup scripts.

## Incident Model

Incident fields:

```json
{
  "severity": "warning | error | critical | info",
  "component": "ingestion | retrieval | llm | ragflow | api | lifecycle | evaluation",
  "title": "Short incident title",
  "detail": "Root symptom or exception message",
  "context": {
    "query_log_id": 123,
    "doc_id": "KT-QT-003"
  },
  "status": "open | resolved | ignored"
}
```

The backend creates incidents automatically for:

- unhandled API errors;
- inbox upload or preparation failure;
- source processing failure;
- approval/rejection/retirement failure;
- RAGFlow bootstrap or sync failure;
- regression evaluation failure;
- RAGFlow retrieval warning returned during chat;
- LLM fallback after provider failure;
- chat latency over `KB_SLOW_RESPONSE_MS` (default `12000` ms).

Manual incident creation is also available for operators and agents.

## Dashboard

Open:

```text
http://127.0.0.1:8088
```

Use:

```text
System -> Incident Center
System -> Diagnostic Summary
```

Actions:

- Review open incidents.
- Use `Diagnostics` to load runtime log tails.
- Resolve an incident only after the root cause is fixed.

## API

List incidents:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/api/incidents
```

Create an incident:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/api/incidents `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"severity":"warning","component":"llm","title":"LLM fallback","detail":"Provider timed out"}'
```

Resolve an incident:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/api/incidents/resolve `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"incident_id":1,"status":"resolved"}'
```

Export diagnostics:

```powershell
Invoke-RestMethod "http://127.0.0.1:8088/api/diagnostics?include_logs=true" |
  ConvertTo-Json -Depth 20
```

If auth is enabled, pass `X-KB-Token`.

## CLI

List incidents:

```powershell
python -m poc_workflow incidents
```

Create an incident:

```powershell
python -m poc_workflow incident warning llm "LLM fallback" --detail "Provider timed out"
```

Resolve an incident:

```powershell
python -m poc_workflow resolve-incident 1
```

Export a diagnostic snapshot:

```powershell
python -m poc_workflow diagnostics
```

Export to a file:

```powershell
.\scripts\export-diagnostics.ps1
```

## Optional Alerts

Set `KB_ALERT_WEBHOOK_URL` to send each incident as JSON to an external webhook:

```powershell
$env:KB_ALERT_WEBHOOK_URL="https://example.com/webhook"
```

If the webhook fails, the failure is appended to:

```text
.runtime/alert-errors.log
```

## User-Facing Status And Maintenance Mode

The backend exposes `service_status` inside `/api/health`. The Vercel demo and local dashboard use this field to show clear messages to non-technical users.

States:

- `ok`: system is ready and chat is enabled.
- `limited`: source-backed search works but AI interpretation is not configured.
- `degraded`: chat still works but open warnings/incidents exist.
- `not_ready`: no approved active documents are available.
- `maintenance`: operator intentionally disabled chat.
- `incident`: critical incident is open and chat should be stopped.
- `offline` / `unavailable`: frontend cannot reach the backend.

Enable maintenance mode before planned downtime:

```powershell
$env:KB_MAINTENANCE_MODE="true"
$env:KB_MAINTENANCE_MESSAGE="He thong dang bao tri. Vui long quay lai sau 15 phut."
```

Disable it:

```powershell
Remove-Item Env:\KB_MAINTENANCE_MODE
Remove-Item Env:\KB_MAINTENANCE_MESSAGE
```

When maintenance is enabled, `/api/chat` returns HTTP `503` with the configured message. The UI disables chat and shows the maintenance notice instead of a technical error.

## AI Agent Debug Procedure

When an AI agent is asked to fix the system:

1. Run `python -m poc_workflow diagnostics`.
2. Check `status`, `summary`, and `recommendations` first.
3. Review `open_incidents` before editing code or re-running ingestion.
4. Check `failed_ingestion_runs` for document pipeline issues.
5. Check `recent_knowledge_gaps` for missing source material.
6. Check `.runtime/*.log` if API, tunnel, or LLM services are failing.
7. Fix the root cause.
8. Re-run `python -m pytest -q`.
9. Re-run `python -m poc_workflow evaluate --provider local`.
10. Resolve the incident after verification.

## Demo Stability Rule

Before any executive demo:

```powershell
python -m poc_workflow diagnostics --no-logs
python -m pytest -q
python -m poc_workflow evaluate --provider local
.\scripts\smoke-web.ps1
```

The demo is acceptable only when there are no open critical incidents, health responds, chat responds with citations for known questions, and the latest evaluation passes.
