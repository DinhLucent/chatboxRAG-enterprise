# Security And Production Checklist

## Required Before Pilot

- Set `KB_REQUIRE_AUTH=true`.
- Set a long random `KB_AUTH_TOKEN` through a secret store or environment variable.
- Set `KB_ENABLE_LOCAL_FALLBACK=false`.
- Set `KB_ALLOWED_PROVIDERS=auto,ragflow`.
- Keep `KB_WORKSPACE_ROOT` on an internal disk with restricted filesystem permissions.
- Use HTTPS or put the app behind an internal reverse proxy with TLS.
- Restrict inbound network access to internal users or VPN.
- Configure RAGFlow API keys as secrets, not committed files.
- Use only approved LLM providers and approved data regions.
- Do not use anonymous/free community LLM routes for confidential production documents.
- Keep FreeLLMAPI `.env`, provider keys, and SQLite database out of git.
- Confirm prompts send only retrieved chunks, not the full document repository.
- Back up `manifest/`, `normalized/`, `source/`, `eval/`, and `data/poc_quality.db`.

## Data Governance

- Only `active` and approved documents can enter the active dataset.
- Archive or retire old versions instead of deleting them immediately.
- Keep `access_group` metadata on all records for future RBAC.
- Do not upload sensitive documents to external LLM providers unless approved.
- Review knowledge gaps and negative feedback on a scheduled cadence.

## Operational Checks

- Run `python -m pytest -q` before deployment.
- Run `python -m poc_workflow evaluate --provider local` before and after document updates.
- Run `python -m poc_workflow readiness --check-network` before enabling pilot users.
- Run `docker compose -f docker-compose.app.yml config --quiet` before container deployment.
- Rebuild RAGFlow active index from manifest after large document changes.
- Verify RAGFlow answers include citations before enabling `provider=auto` for users.

## Incident Response

- If a wrong source is cited, mark feedback as `wrong_source` and review the related knowledge gap.
- If stale policy appears in answers, retire/archive the stale document and rebuild/sync the active dataset.
- If auth is misconfigured, `KB_REQUIRE_AUTH=true` with empty `KB_AUTH_TOKEN` fails closed with HTTP 503 for protected APIs.
- If RAGFlow is down, `provider=ragflow` returns the no-source answer and logs a knowledge gap.
