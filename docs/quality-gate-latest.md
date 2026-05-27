# Quality Gate Latest

- Status: `escalated`
- Mode: `local`
- Provider: `local`
- Started: `2026-05-27T03:27:54+00:00`
- Finished: `2026-05-27T03:28:25+00:00`
- Latency: `30605 ms`
- Cases: `13`

## Summary

| Metric | Value |
| --- | ---: |
| total | 12 |
| pass | 6 |
| warn | 3 |
| fail | 2 |
| skip | 1 |
| blocker_failures | 2 |

## Checks

| Gate | Severity | Status | Latency | Evidence | Detail |
| --- | --- | --- | ---: | --- | --- |
| preflight | warning | warn | 68 ms | `git ls-files; git status --short` | No tracked raw documents or runtime artifacts were detected. |
| static | blocker | pass | 142 ms | `JSON parse; compileall; FastAPI route inventory` | JSON files parse, package compiles, API route inventory is valid. |
| frontend_static | blocker | pass | 39 ms | `frontend ID/status/forbidden-text checks + UTF-8 mojibake scan` | Frontend static UI, Upload workflow labels, auth unlock path, and text encoding checks passed. |
| agent_skills | blocker | pass | 1 ms | `agent_skills registry + SKILL.md contract scan` | Agent skill registry and handoff contracts are present. |
| unit_integration | blocker | pass | 27811 ms | `C:\Users\ADMIN\miniconda3\envs\prismaflex\python.exe -m pytest -o addopts= --basetemp=D:\MyProject\demo-chatbot-engineerworkflow\.quality-sandbox\2026-05-27T032754Z0000\pytest` | Pytest passed. |
| retrieval_eval | info | skip | 0 ms | `python -m poc_workflow evaluate --provider local --cases eval/regression_cases_69.json` | Regression evaluation was skipped by request. |
| workspace_eval | blocker | fail | 752 ms | `evaluate_case loop over eval/regression_cases.json` | Workspace regression cases failed. |
| user_workflow | blocker | pass | 896 ms | `FastAPI TestClient sandbox workflow` | Upload queue, prompt generation, review detail, and chat workflow passed in sandbox. |
| security_jailbreak | blocker | pass | 550 ms | `ask() safety cases + OpenAICompatibleClient payload inspection` | Security and jailbreak deterministic checks passed. |
| data_audit | warning | warn | 11 ms | `manifest duplicate/version/metadata/Markdown/QA audit` | Manifest/data audit completed. |
| production_readiness | warning | warn | 3 ms | `python -m poc_workflow readiness` | Local readiness has non-blocking production gaps. |
| performance_smoke | blocker | fail | 84 ms | `ask() over eval/quality_gate_cases.json representative queries` | Performance smoke found slow or failing cases. |

## Failed Cases

- `workspace_eval`: engineering-scope-count-direct: expected=['KT-QT-142', 'KT-QT-144', 'KT-QT-146', 'KT-QT-148', 'KT-QT-150', 'KT-QT-152', 'KT-QT-356', 'KT-QT-360', 'KT-QT-376', 'KT-QT-401', 'KT-QT-426', 'KT-QT-431'] retrieved=['KT-QT-075'] latency=28ms
- `workspace_eval`: installation-procedure-steps: expected=['KT-QT-426'] retrieved=['KT-QT-001'] latency=21ms
- `workspace_eval`: maintenance-procedure-steps: expected=['KT-QT-401'] retrieved=['KT-QT-002'] latency=25ms
- `workspace_eval`: repair-procedure-workflow: expected=['KT-QT-431'] retrieved=['KT-QT-003'] latency=0ms
- `performance_smoke`: chat-known-procedure missed expected docs: KT-QT-426
- `performance_smoke`: performance-representative-chat missed expected docs: KT-QT-360

## Open Risks

- preflight: No tracked raw documents or runtime artifacts were detected.
- preflight: Working tree has uncommitted changes; preserving them is allowed for local gate runs.
- workspace_eval: Workspace regression cases failed.
- data_audit: Manifest/data audit completed.
- data_audit: KT-QT-001::rev04 has no QA report reference
- data_audit: KT-QT-002::rev04 has no QA report reference
- data_audit: KT-QT-003::rev04 has no QA report reference
- data_audit: KT-QT-057::rev07 has no QA report reference
- data_audit: KT-QT-075::rev03 has no QA report reference
- production_readiness: Local readiness has non-blocking production gaps.
- production_readiness: ragflow_config: Set RAGFLOW_BASE_URL, RAGFLOW_API_KEY, RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID, and RAGFLOW_CHAT_ID or RAGFLOW_SEARCH_ID.
- production_readiness: latest_evaluation: Run python -m poc_workflow evaluate --provider ragflow or --provider local for smoke verification.
- production_readiness: operator_auth: Set KB_REQUIRE_AUTH=true and KB_AUTH_TOKEN for production.
- production_readiness: local_fallback_disabled: Set KB_ENABLE_LOCAL_FALLBACK=false in production.
- performance_smoke: Performance smoke found slow or failing cases.
- RAGFlow/auth/local fallback gaps are warnings in local mode; production mode makes them blockers.

## Next Action

Fix blocker gates before release: workspace_eval, performance_smoke
