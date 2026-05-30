# Quality Gate Latest

- Status: `accepted`
- Mode: `local`
- Provider: `local`
- Started: `2026-05-29T18:17:21+00:00`
- Finished: `2026-05-29T18:17:42+00:00`
- Latency: `21440 ms`
- Cases: `13`

## Summary

| Metric | Value |
| --- | ---: |
| total | 14 |
| pass | 8 |
| warn | 2 |
| fail | 0 |
| skip | 4 |
| blocker_failures | 0 |

## Checks

| Gate | Severity | Status | Latency | Evidence | Detail |
| --- | --- | --- | ---: | --- | --- |
| preflight | warning | warn | 86 ms | `git ls-files; git status --short` | No tracked raw documents or runtime artifacts were detected. |
| static | blocker | pass | 180 ms | `JSON parse; compileall; FastAPI route inventory` | JSON files parse, package compiles, API route inventory is valid. |
| frontend_static | blocker | pass | 83 ms | `frontend ID/status/forbidden-text checks + UTF-8 mojibake scan` | Frontend static UI, Upload workflow labels, auth unlock path, and text encoding checks passed. |
| agent_skills | blocker | pass | 1 ms | `agent_skills registry + SKILL.md contract scan` | Agent skill registry and handoff contracts are present. |
| unit_integration | info | skip | 0 ms | `python -m pytest -o addopts= --basetemp=D:\MyProject\demo-chatbot-engineerworkflow\.quality-sandbox\2026-05-29T181721Z0000\pytest` | Pytest was skipped by request. |
| qa_agent_eval | info | skip | 0 ms | `python -m poc_workflow qa-agent-eval --mode contract` | QA Agent contract evaluation was skipped by request. |
| user_chat_render_smoke | info | skip | 0 ms | `python -m poc_workflow user-chat-render-smoke` | User chat browser render smoke is opt-in and was skipped. |
| retrieval_eval | info | skip | 0 ms | `python -m poc_workflow evaluate --provider local --cases eval/regression_cases_69.json` | Regression evaluation was skipped by request. |
| workspace_eval | blocker | pass | 8230 ms | `evaluate_case loop over eval/regression_cases.json` | Workspace regression cases passed. |
| user_workflow | blocker | pass | 740 ms | `FastAPI TestClient sandbox workflow` | Upload queue, prompt generation, review detail, and chat workflow passed in sandbox. |
| security_jailbreak | blocker | pass | 7749 ms | `ask() safety cases + OpenAICompatibleClient payload inspection` | Security and jailbreak deterministic checks passed. |
| data_audit | blocker | pass | 390 ms | `manifest duplicate/version/metadata/Markdown/QA audit` | Manifest/data audit completed. |
| production_readiness | warning | warn | 10 ms | `python -m poc_workflow readiness` | Local readiness has non-blocking production gaps. |
| performance_smoke | blocker | pass | 97 ms | `ask() over eval/quality_gate_cases.json representative queries` | Representative query latency smoke passed. |

## Open Risks

- preflight: No tracked raw documents or runtime artifacts were detected.
- preflight: Working tree has uncommitted changes; preserving them is allowed for local gate runs.
- production_readiness: Local readiness has non-blocking production gaps.
- production_readiness: ragflow_config: Set RAGFLOW_BASE_URL, RAGFLOW_API_KEY, RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID, and RAGFLOW_CHAT_ID or RAGFLOW_SEARCH_ID.
- production_readiness: operator_auth: Set KB_REQUIRE_AUTH=true and KB_AUTH_TOKEN for production.
- production_readiness: local_fallback_disabled: Set KB_ENABLE_LOCAL_FALLBACK=false in production.
- RAGFlow/auth/local fallback gaps are warnings in local mode; production mode makes them blockers.

## Next Action

Quality gate accepted. Keep the JSON/Markdown report as release evidence.
