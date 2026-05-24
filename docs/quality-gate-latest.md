# Quality Gate Latest

- Status: `accepted`
- Mode: `local`
- Provider: `local`
- Started: `2026-05-24T23:41:57+00:00`
- Finished: `2026-05-24T23:42:34+00:00`
- Latency: `37500 ms`
- Cases: `13`

## Summary

| Metric | Value |
| --- | ---: |
| total | 11 |
| pass | 8 |
| warn | 3 |
| fail | 0 |
| skip | 0 |
| blocker_failures | 0 |

## Checks

| Gate | Severity | Status | Latency | Evidence | Detail |
| --- | --- | --- | ---: | --- | --- |
| preflight | warning | warn | 78 ms | `git ls-files; git status --short` | No tracked raw documents or runtime artifacts were detected. |
| static | blocker | pass | 134 ms | `JSON parse; compileall; FastAPI route inventory` | JSON files parse, package compiles, API route inventory is valid. |
| frontend_static | blocker | pass | 54 ms | `frontend ID/status/forbidden-text checks + UTF-8 mojibake scan` | Frontend static UI, Upload workflow labels, auth unlock path, and text encoding checks passed. |
| unit_integration | blocker | pass | 12596 ms | `C:\Users\ADMIN\miniconda3\envs\prismaflex\python.exe -m pytest -o addopts= --basetemp=D:\MyProject\demo-chatbot-engineerworkflow\.quality-sandbox\2026-05-24T234157Z0000\pytest` | Pytest passed. |
| retrieval_eval | blocker | pass | 749 ms | `evaluate_case loop over eval/regression_cases_69.json` | Regression retrieval, citation, no-answer, and latency targets passed. |
| workspace_eval | blocker | pass | 22196 ms | `evaluate_case loop over eval/regression_cases.json` | Workspace regression cases passed. |
| user_workflow | blocker | pass | 532 ms | `FastAPI TestClient sandbox workflow` | Upload queue, prompt generation, review detail, and chat workflow passed in sandbox. |
| security_jailbreak | blocker | pass | 22 ms | `ask() safety cases + OpenAICompatibleClient payload inspection` | Security and jailbreak deterministic checks passed. |
| data_audit | warning | warn | 505 ms | `manifest duplicate/version/metadata/Markdown/QA audit` | Manifest/data audit completed. |
| production_readiness | warning | warn | 12 ms | `python -m poc_workflow readiness` | Local readiness has non-blocking production gaps. |
| performance_smoke | blocker | pass | 45 ms | `ask() over eval/quality_gate_cases.json representative queries` | Representative query latency smoke passed. |

## Open Risks

- preflight: No tracked raw documents or runtime artifacts were detected.
- preflight: Working tree has uncommitted changes; preserving them is allowed for local gate runs.
- data_audit: Manifest/data audit completed.
- data_audit: technical/BM-001.03 has older active revisions excluded from served latest set: KT-BM-002::1.0
- data_audit: technical/PD-IC-A-001 has older active revisions excluded from served latest set: KT-QT-030::1.0
- data_audit: technical/PD-SALES-A-106 has older active revisions excluded from served latest set: KT-QT-096::1.0
- data_audit: KT-FAQ-008::1.0 title suggests procedure but category is faq_troubleshooting: PD IC A 046. Rev 03. Quy trình kiểm soát rủi ro và sự cố
- data_audit: KT-FAQ-010::1.0 title suggests form_checklist but category is faq_troubleshooting: BM 01.Phiếu tiếp nhận sản phẩm trả về
- production_readiness: Local readiness has non-blocking production gaps.
- production_readiness: ragflow_config: Set RAGFLOW_BASE_URL, RAGFLOW_API_KEY, RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID, and RAGFLOW_CHAT_ID or RAGFLOW_SEARCH_ID.
- production_readiness: operator_auth: Set KB_REQUIRE_AUTH=true and KB_AUTH_TOKEN for production.
- production_readiness: local_fallback_disabled: Set KB_ENABLE_LOCAL_FALLBACK=false in production.
- RAGFlow/auth/local fallback gaps are warnings in local mode; production mode makes them blockers.

## Next Action

Quality gate accepted. Keep the JSON/Markdown report as release evidence.
