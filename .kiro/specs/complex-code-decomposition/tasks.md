# Implementation Plan: Complex Code Decomposition

## Overview

This plan turns the behavior-preserving decomposition design into incremental coding steps in **Python**. It first builds the two shared tools the whole effort depends on — the `Complexity_Scan` (`scripts/complexity_scan.py`) and the characterization-test harness (`tests/characterization/`) — then decomposes the eight primary hotspots one at a time, highest-rank first, each as an isolated, independently revertible change set (Requirement 4).

Every hotspot follows the same six-phase playbook expressed as sub-tasks: capture baseline + characterization golden tests (Phase A/B) → extract bounded units (Phase C) → guard with property-based tests (validates the design's Correctness Properties) → generate the per-hotspot decomposition record after re-running the full `Test_Guard` and smoke scripts (Phase D/E/F). Characterization golden tests are core (they are the golden reference required before any structural edit, Req 3.2); property-based and supplementary tests are marked optional with `*`.

Hotspots are sequenced across successive dependency waves so that no hotspot decomposition starts before the previous one is delivered as a `Reversible_Change` (Req 4.7).

## Tasks

- [x] 1. Build the Complexity_Scan tool (`scripts/complexity_scan.py`)
  - [x] 1.1 Implement metric data models and AST metric computation
    - Add `FunctionMetric` (qualname, file, lineno, cc, loc, nesting, `passes`, `exceeds`) and `ScanDiff`/`ThresholdException` dataclasses in `scripts/complexity_scan.py`
    - Implement CC (1 + decision points), LOC (`end_lineno - lineno + 1`), and Nesting_Depth computation using the standard library `ast` module only
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 1.2 Implement scan traversal, diff, CLI, and JSON reporting
    - Implement `scan_path(path, *, only)` and `diff_reports(before, after)`; add per-function pass/fail against the Complexity_Threshold
    - Add the `python -m scripts.complexity_scan <path> [--json OUT] [--baseline FILE] [--only ...] [--fail-over-threshold]` CLI and the JSON output shape (functions + summary)
    - _Requirements: 2.4, 13.1_
  - [x]* 1.3 Write property test for threshold classification
    - **Property 4: Complexity_Scan threshold classification is correct**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    - Use Hypothesis (≥100 iterations) over generated function sources; assert `passes == true` iff cc≤15 ∧ loc≤80 ∧ nesting≤5 and `exceeds` lists exactly the violated limits
  - [x]* 1.4 Write property test for metric monotonicity under wrapping
    - **Property 5: Complexity_Scan nesting and CC are monotonic under wrapping**
    - **Validates: Requirements 2.1, 2.3, 2.4**
    - Hypothesis metamorphic test: wrapping a body in an extra control-flow block never decreases nesting and strictly increases cc; extracting an inner block does not increase either metric
  - [x]* 1.5 Write unit tests for scan edge cases
    - Cover comprehensions, boolean operators, ternaries, `match`/`case`, nested functions, and unparseable input
    - _Requirements: 2.1, 2.4_

- [x] 2. Build the characterization (golden) test harness (`tests/characterization/`)
  - [x] 2.1 Implement capture/compare helpers and volatile-field normalization
    - Implement `golden_cli`, `golden_http`, `golden_answer`, and `assert_equivalent` plus the `VOLATILE` field set (timestamps, auto-ids, `latency_ms`, `generated_at`, run ids)
    - Support byte-exact CLI compare, HTTP status/body/content-type compare minus volatile fields, and order-sensitive vs order-insensitive citation compare
    - _Requirements: 1.3, 1.4, 1.5_
  - [x]* 2.2 Write unit tests for harness normalization and compare logic
    - Verify volatile-field stripping, set-equal vs order-sensitive citation comparison, and difference reporting
    - _Requirements: 1.3, 1.4, 1.5_

- [x] 3. Checkpoint - shared tooling ready
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Decompose Hotspot 1 - QA agent workflow (`qa_agent_workflow._run_qa_agent_workflow_impl`)
  - [ ] 4.1 Capture baseline and write QA-workflow characterization golden tests
    - Record baseline `Test_Guard` pass/fail and hotspot line-coverage via the scan tool; add golden tests in `tests/characterization/test_qa_agent_golden.py` mocking LLM boundaries until coverage ≥ 80%
    - Capture golden answer text, citation set (order-insensitive), trace steps, quality/compliance decisions, and the persisted answer-run record
    - _Requirements: 3.1, 3.2_
  - [ ] 4.2 Extract workflow stages into named functions and result builders
    - Extract scope gating, query analysis, retrieval planning, evidence retrieval, evidence-pack construction, format planning, answer drafting, verification, critique, procedure-compliance, and final formatting into `_stage_*` functions over a `QaRunContext`
    - Add `_build_result`/`_failed_result`/`_clarification_result`/`_no_answer_result` so every return dict keeps an identical key set; keep the orchestrator and `run_qa_agent_workflow` entry point unchanged; ensure each function meets CC≤15/LOC≤80/nesting≤5
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ]* 4.3 Write property test for observable-behavior equivalence
    - **Property 1: Decomposition preserves observable behavior (equivalence)**
    - **Validates: Requirements 1.1, 5.2**
    - Hypothesis (≥100 iterations) over query/corpus/config; assert returned result fields and persisted answer-run record equal the captured baseline (minus volatile fields)
  - [ ]* 4.4 Write property test for answer-path citation-set equivalence
    - **Property 2: Answer-path equivalence with citation-set semantics**
    - **Validates: Requirements 1.4, 5.2**
    - Assert same answer text and order-insensitive citation set vs baseline
  - [ ]* 4.5 Write property test for failure/clarification/no-answer preservation
    - **Property 3: Failure and non-answer outcomes are preserved**
    - **Validates: Requirements 5.3**
    - Assert same answer source, fallback reason, and clarification result for baseline failure/no-answer inputs
  - [ ] 4.6 Generate QA-workflow decomposition record
    - Run the scan before/after diff and full `Test_Guard` + smoke scripts; write `decomposition-records/01-qa-agent-workflow.md` with before/after metrics, baseline/post test results, baseline/post coverage, behavior evidence, and any threshold exception
    - _Requirements: 2.4, 2.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 5. Decompose Hotspot 2 - CLI command dispatcher (`cli.main`)
  - [ ] 5.1 Capture baseline and write CLI characterization golden tests
    - Add `tests/characterization/test_cli_golden.py` capturing exit code + byte-exact stdout/stderr (incl. env-backed defaults and the sync-ragflow `--dry-run` and quality-gate early-return branches) until coverage ≥ 80%
    - _Requirements: 3.1, 3.2, 6.2_
  - [ ] 5.2 Extract command handlers into a dispatch registry
    - Extract each command branch into a `_cmd_*` handler with signature `(Namespace, Path) -> HandlerResult`; build a `HANDLERS` registry; reduce `cli.main` to a thin router preserving the single top-level `try/except`, `parser.error(...)` unknown-command path, and the two explicit exit-code branches
    - Keep `build_parser()` and the full argparse contract unchanged; ensure handlers and the router meet CC≤15/LOC≤80/nesting≤5
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ]* 5.3 Write property test for CLI observable-behavior equivalence
    - **Property 1: Decomposition preserves observable behavior (equivalence)**
    - **Validates: Requirements 6.2**
    - Hypothesis over valid arg combinations; assert byte-exact exit code/stdout/stderr vs baseline
  - [ ]* 5.4 Write property test for CLI error-path preservation
    - **Property 3: Failure and non-answer outcomes are preserved**
    - **Validates: Requirements 6.4**
    - Assert unhandled-exception invocations reproduce the same error payload and non-zero exit code
  - [ ] 5.5 Generate CLI decomposition record
    - Write `decomposition-records/02-cli-main.md` with before/after metrics, test/coverage results, and behavior evidence
    - _Requirements: 2.4, 2.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 6. Decompose Hotspot 3 - chatbot answer path (`chatbot.ask`)
  - [ ] 6.1 Capture baseline and write answer-path characterization golden tests
    - Add `tests/characterization/test_chatbot_ask_golden.py` capturing character-for-character answer text and ordered source references (order-sensitive) across provider paths until coverage ≥ 80%
    - _Requirements: 3.1, 3.2, 7.2_
  - [ ] 6.2 Extract retrieval, scope-gating, context-composition, and citation units
    - Extract `_retrieve_hits` into `chatbot_retrieval.py` depending only on the RAG_Uplift `Retriever` protocol; extract `_scope_decision`, `_compose_context`, `_build_citations` (order-preserving), `_answer_with_llm_or_fallback`, provider `_ask_via_*` functions, and a single `_ask_result` builder; reduce `ask` to a coordinator meeting CC≤15/LOC≤80/nesting≤5
    - _Requirements: 7.1, 7.4, 7.5_
  - [ ]* 6.3 Write property test for order-sensitive answer-path equivalence
    - **Property 2: Answer-path equivalence with citation-set semantics**
    - **Validates: Requirements 7.2**
    - Assert character-for-character answer text and identical citation order vs baseline
  - [ ]* 6.4 Write property test for error/no-answer preservation
    - **Property 3: Failure and non-answer outcomes are preserved**
    - **Validates: Requirements 7.3**
    - Assert error/empty/no-answer outcomes are reproduced
  - [ ] 6.5 Generate chatbot.ask decomposition record
    - Write `decomposition-records/03-chatbot-ask.md` with before/after metrics, test/coverage results, and behavior evidence
    - _Requirements: 2.4, 2.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 7. Checkpoint - top three hotspots decomposed
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Decompose Hotspot 4 - data audit quality gate (`quality_gate.data_audit_gate`)
  - [ ] 8.1 Capture baseline and write data-audit-gate characterization golden tests
    - Add `tests/characterization/test_quality_gate_golden.py` capturing pass/warn/fail status, severity, ordered blocker/warning lists, and corrupt-manifest early return until coverage ≥ 80%
    - _Requirements: 3.1, 3.2, 8.2, 8.3_
  - [ ] 8.2 Extract audit checks over a shared accumulator
    - Extract `_audit_load_manifest`, `_audit_records`, `_audit_active_families`, `_audit_active_index`, `_audit_taxonomy`, and `_finalize_audit` appending to an ordered `AuditAccumulator`; keep `data_audit_gate` name/signature and preserve append order; ensure each meets CC≤15/LOC≤80/nesting≤5
    - _Requirements: 8.1, 8.5_
  - [ ]* 8.3 Write property test for audit-gate observable-behavior equivalence
    - **Property 1: Decomposition preserves observable behavior (equivalence)**
    - **Validates: Requirements 8.2, 8.3**
    - Hypothesis over manifest/workspace/config; assert same status, severity, and ordered blocker/warning lists vs baseline
  - [ ]* 8.4 Write property test for corrupt-manifest early-return preservation
    - **Property 3: Failure and non-answer outcomes are preserved**
    - **Validates: Requirements 8.4**
    - Assert corrupt/unreadable manifest reproduces the baseline early-return fail result
  - [ ] 8.5 Generate data-audit-gate decomposition record
    - Write `decomposition-records/04-data-audit-gate.md` with before/after metrics, test/coverage results, and behavior evidence
    - _Requirements: 2.4, 2.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 9. Decompose Hotspot 5 - chat response assembly (`user_chat.user_chat_response`)
  - [ ] 9.1 Capture baseline and write chat-response characterization golden tests
    - Add `tests/characterization/test_user_chat_golden.py` capturing the response payload key set/values for all five paths (annotated, scope-reject, clarification, qa-agent, standard) until coverage ≥ 80%
    - _Requirements: 3.1, 3.2, 9.2, 9.3_
  - [ ] 9.2 Extract response-assembly functions and shared envelope
    - Extract `_annotated_answer_response`, `_standard_answer_response`, `_session_envelope`, and `_decorate_trace`; reduce `user_chat_response` to a dispatcher reusing one envelope builder; keep entry point/parameters unchanged; ensure each meets CC≤15/LOC≤80/nesting≤5
    - _Requirements: 9.1, 9.4_
  - [ ]* 9.3 Write property test for response-payload equivalence
    - **Property 1: Decomposition preserves observable behavior (equivalence)**
    - **Validates: Requirements 9.2, 9.3**
    - Hypothesis over inputs exercising each path; assert identical payload key set and per-key values vs baseline
  - [ ]* 9.4 Write property test for per-path outcome preservation
    - **Property 3: Failure and non-answer outcomes are preserved**
    - **Validates: Requirements 9.3**
    - Assert scope-reject/clarification/qa-agent/standard outcomes reproduce baseline payloads
  - [ ] 9.5 Generate user_chat_response decomposition record
    - Write `decomposition-records/05-user-chat-response.md` with before/after metrics, test/coverage results, and behavior evidence
    - _Requirements: 2.4, 2.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 10. Decompose Hotspot 6 - source processing pipeline (`pipeline.process_sources`)
  - [ ] 10.1 Capture baseline and write pipeline characterization golden tests
    - Add `tests/characterization/test_pipeline_golden.py` capturing converted/normalized output, RAG-ready artifacts, and persisted manifest/ingestion-log/status records (minus volatile fields) until coverage ≥ 80%
    - _Requirements: 3.1, 3.2, 10.2_
  - [ ] 10.2 Extract pipeline stages over a SourceJob context
    - Extract `_prepare_source`, `_skip_if_unchanged`, `_convert_source`, `_audit_source`, `_build_rag_ready`, `_record_evolution`, `_finalize_source`, and `_handle_source_failure`; keep `process_sources` signature and loop; preserve skip/failure classification and lifecycle moves; ensure each meets CC≤15/LOC≤80/nesting≤5
    - _Requirements: 10.1_
  - [ ]* 10.3 Write property test for pipeline observable-behavior/persisted-record equivalence
    - **Property 1: Decomposition preserves observable behavior (equivalence)**
    - **Validates: Requirements 10.2**
    - Hypothesis over sources/config (MinerU mocked); assert artifacts and persisted records equal baseline minus volatile fields
  - [ ]* 10.4 Write property test for failure/skip outcome preservation
    - **Property 3: Failure and non-answer outcomes are preserved**
    - **Validates: Requirements 10.3, 10.4**
    - Assert failure classification/log/status/lifecycle and skip outcomes reproduce baseline
  - [ ] 10.5 Generate pipeline decomposition record
    - Write `decomposition-records/06-process-sources.md` with before/after metrics, test/coverage results, and behavior evidence
    - _Requirements: 2.4, 2.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 11. Checkpoint - six hotspots decomposed
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Decompose Hotspot 7 - upload processing orchestrator (`upload_processing.process_upload_document_group`)
  - [ ] 12.1 Capture baseline and write upload-processing characterization golden tests
    - Add `tests/characterization/test_upload_processing_golden.py` capturing returned result, terminal status, workflow events, handoffs, reports, normalized output, and persisted manifest record (minus volatile fields), plus rejection/failure terminals, until coverage ≥ 80%
    - _Requirements: 3.1, 3.2, 11.2_
  - [ ] 12.2 Extract orchestration steps over an UploadRun context
    - Extract `_validate_group`, `_stage_and_plan`, `_probe_and_select`, `_record_conversion`, `_initial_audit_and_repair`, `_normalize_and_log`, `_qa_recheck`, `_record_index`, and `_finalize_upload`; thread `UploadRun`/`TerminalResult`; keep entry point/parameters unchanged; route every terminal through existing `terminal_*`/`finalize_upload_queue_state` helpers; ensure each meets CC≤15/LOC≤80/nesting≤5
    - _Requirements: 11.1, 11.4_
  - [ ]* 12.3 Write property test for upload observable-behavior/persisted-record equivalence
    - **Property 1: Decomposition preserves observable behavior (equivalence)**
    - **Validates: Requirements 11.2**
    - Hypothesis over upload groups/config; assert result, status, events, reports, and manifest record equal baseline minus volatile fields
  - [ ]* 12.4 Write property test for rejection/failure terminal preservation
    - **Property 3: Failure and non-answer outcomes are preserved**
    - **Validates: Requirements 11.3**
    - Assert unsupported department/category, missing business code, no usable converted source, and failed QA recheck reproduce baseline terminal outcomes and records
  - [ ] 12.5 Generate upload-processing decomposition record
    - Write `decomposition-records/07-upload-processing.md` with before/after metrics, test/coverage results, and behavior evidence
    - _Requirements: 2.4, 2.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 13. Decompose Hotspot 8 - web application factory (`webapp.create_app`)
  - [ ] 13.1 Capture baseline, snapshot route inventory, and write HTTP characterization golden tests
    - Add `tests/characterization/test_webapp_routes_golden.py` snapshotting the `(path, method)` set and per-route auth classification, and capturing status/body/content-type (success + error) via FastAPI `TestClient` until coverage ≥ 80%
    - _Requirements: 3.1, 3.2, 12.2, 12.3_
  - [ ] 13.2 Extract grouped APIRouter modules and compose create_app
    - Move every inline route into domain routers under `poc_workflow/webapp_routers/` (each route in exactly one router); reduce `create_app` to install middleware/lifespan/static mount and `include_router(...)` only, with zero inline routes; preserve every path/method and the path-prefix auth middleware; do not add/remove routes
    - _Requirements: 12.1, 12.3, 12.6_
  - [ ]* 13.3 Write property test for HTTP observable-behavior equivalence
    - **Property 1: Decomposition preserves observable behavior (equivalence)**
    - **Validates: Requirements 12.2**
    - Hypothesis over request path/method/headers/query/body; assert same status, body, content-type (minus volatile fields) vs baseline
  - [ ]* 13.4 Write property test for route-inventory set equality and auth classification
    - **Property 6: Route-inventory set equality**
    - **Validates: Requirements 12.1, 12.3, 12.4**
    - Assert the composed app's `(path, method)` set and per-route auth classification equal the pre-decomposition snapshot
  - [ ] 13.5 Generate route-inventory.json and webapp decomposition record
    - Emit `decomposition-records/route-inventory.json` enumerating every route (path, method, router, authenticated) and listing unauthenticated routes; write `decomposition-records/08-create-app.md` with before/after metrics, test/coverage results, and behavior evidence; flag any route that lacks authentication
    - _Requirements: 12.4, 12.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 14. Checkpoint - all eight primary hotspots delivered
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Decompose secondary candidates (optional stretch, only after all primaries ship)
  - [ ]* 15.1 Decompose `ai_review.quality_refill_decision` via the playbook
    - Capture baseline + characterization, extract bounded units, guard with equivalence property tests, and emit `decomposition-records/S1-quality-refill-decision.md`
    - _Requirements: 4.5_
  - [ ]* 15.2 Decompose `upload_processing.verify_upload_rag_readiness` via the playbook
    - Capture baseline + characterization, extract bounded units, guard with equivalence property tests, and emit `decomposition-records/S2-verify-upload-rag-readiness.md`
    - _Requirements: 4.5_
  - [ ]* 15.3 Decompose `user_chat.qa_agent_chat_response` via the playbook
    - Capture baseline + characterization, extract bounded units, guard with equivalence property tests, and emit `decomposition-records/S3-qa-agent-chat-response.md`
    - _Requirements: 4.5_

- [ ] 16. Final checkpoint - effort complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster path; characterization golden tests are intentionally **not** optional because they are the required golden reference captured before any structural edit (Req 3.2) and the gate for behavior preservation.
- Each hotspot is a single, independently revertible change set; hotspots are sequenced highest-rank-first and never decomposed concurrently (Requirement 4), which is why each hotspot occupies its own dependency waves rather than running in parallel.
- Every decomposed unit and the residual orchestrator must meet the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5); a justified exception is recorded in the decomposition record when a split would harm clarity (Reqs 2.5, 13.5).
- The full `Test_Guard` (pytest suite + the `user_chat_render_smoke.py` and `qa_test_eval.py` smoke scripts, each exiting 0) is re-run before any decomposition record is marked complete (Reqs 3.3, 3.6, 13.6).
- Property-based tests use Hypothesis at ≥100 iterations and carry the comment `# Feature: complex-code-decomposition, Property {n}: {property text}`; external LLM/MinerU/RAGFlow boundaries are mocked deterministically so equivalence is tested against the captured golden baseline.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "1.5", "4.1"] },
    { "id": 3, "tasks": ["4.2"] },
    { "id": 4, "tasks": ["4.3", "4.4", "4.5"] },
    { "id": 5, "tasks": ["4.6"] },
    { "id": 6, "tasks": ["5.1"] },
    { "id": 7, "tasks": ["5.2"] },
    { "id": 8, "tasks": ["5.3", "5.4"] },
    { "id": 9, "tasks": ["5.5"] },
    { "id": 10, "tasks": ["6.1"] },
    { "id": 11, "tasks": ["6.2"] },
    { "id": 12, "tasks": ["6.3", "6.4"] },
    { "id": 13, "tasks": ["6.5"] },
    { "id": 14, "tasks": ["8.1"] },
    { "id": 15, "tasks": ["8.2"] },
    { "id": 16, "tasks": ["8.3", "8.4"] },
    { "id": 17, "tasks": ["8.5"] },
    { "id": 18, "tasks": ["9.1"] },
    { "id": 19, "tasks": ["9.2"] },
    { "id": 20, "tasks": ["9.3", "9.4"] },
    { "id": 21, "tasks": ["9.5"] },
    { "id": 22, "tasks": ["10.1"] },
    { "id": 23, "tasks": ["10.2"] },
    { "id": 24, "tasks": ["10.3", "10.4"] },
    { "id": 25, "tasks": ["10.5"] },
    { "id": 26, "tasks": ["12.1"] },
    { "id": 27, "tasks": ["12.2"] },
    { "id": 28, "tasks": ["12.3", "12.4"] },
    { "id": 29, "tasks": ["12.5"] },
    { "id": 30, "tasks": ["13.1"] },
    { "id": 31, "tasks": ["13.2"] },
    { "id": 32, "tasks": ["13.3", "13.4"] },
    { "id": 33, "tasks": ["13.5"] },
    { "id": 34, "tasks": ["15.1"] },
    { "id": 35, "tasks": ["15.2"] },
    { "id": 36, "tasks": ["15.3"] }
  ]
}
```
