# Requirements Document

## Introduction

This feature defines an internal refactoring effort to decompose the most complex functions and modules in the `poc_workflow/` backend into smaller, well-bounded, independently testable units. It is treated as a feature because it is a planned, sequenced body of work with measurable acceptance criteria, but it delivers no new user-facing functionality.

The overriding principle is **behavior preservation**: every decomposition must leave observable behavior unchanged — identical CLI behavior, identical HTTP API responses, and identical QA/answer results for the same inputs and configuration. Decomposition work is guarded by the existing pytest suite and smoke scripts, supplemented by characterization (golden) tests captured before any structural change.

The work is grounded in an AST-based complexity scan of `poc_workflow/`. The scan ranked hotspots by cyclomatic complexity, function length, and nesting depth. The eight primary hotspots and three secondary candidates below drive the requirements. Decomposition is sequenced highest-risk-reduction first, with each hotspot delivered as an independently shippable, reversible change.

This effort runs alongside the in-flight RAG uplift (`specs/001-improve-rag-end-to-end`). The `chatbot.ask` answer path and its retrieval/scope-gating seams are sequenced so that decomposition reduces friction for the RAG work rather than colliding with it.

## Glossary

- **Decomposition_Effort**: The overall body of refactoring work defined by this specification.
- **Refactoring_Process**: The defined per-hotspot procedure that extracts smaller units from a complex function or module without changing observable behavior.
- **Hotspot**: A function or module identified by the complexity scan as a primary or secondary decomposition target.
- **Primary_Hotspot**: One of the eight ranked functions/modules that are in-scope targets for this effort.
- **Secondary_Candidate**: One of the three additional functions designated as optional / stretch targets.
- **Observable_Behavior**: Externally visible outputs and effects of the system for a given input and configuration, including CLI exit codes and stdout/stderr content, HTTP response status and body, persisted records, and QA/answer text and citations.
- **Characterization_Test**: A test that captures the current Observable_Behavior of a Hotspot before decomposition, used as a golden reference to detect regressions. Also called a golden test.
- **Test_Guard**: The combined set of the existing pytest suite under `tests/`, the smoke scripts (`poc_workflow/user_chat_render_smoke.py`, `poc_workflow/qa_test_eval.py`), and any Characterization_Tests added for a Hotspot.
- **Complexity_Scan**: The AST-based analysis that measures cyclomatic complexity, length, and nesting depth of functions in `poc_workflow/`.
- **Cyclomatic_Complexity**: The count of linearly independent paths through a function, abbreviated CC.
- **Function_Length**: The number of lines of code (LOC) in a single function body.
- **Nesting_Depth**: The maximum number of nested control-flow blocks within a function.
- **Complexity_Threshold**: The target ceiling values a decomposed function must meet — CC less than or equal to 15, Function_Length less than or equal to 80 LOC, and Nesting_Depth less than or equal to 5.
- **Reversible_Change**: A decomposition delivered as an isolated, self-contained unit of work that can be reverted independently without undoing other Hotspot decompositions.
- **Behavior_Regression**: Any difference in Observable_Behavior between the pre-decomposition and post-decomposition code for the same input and configuration.
- **Test_Coverage**: The proportion of executable lines and branches exercised by the Test_Guard for the code under decomposition.
- **RAG_Uplift**: The in-flight feature defined in `specs/001-improve-rag-end-to-end`.

### Hotspot Inventory (scan results)

| Rank | Hotspot | Location | CC | LOC | Depth | Tier |
|------|---------|----------|----|----|-------|------|
| 1 | `qa_agent_workflow._run_qa_agent_workflow_impl` | `poc_workflow/qa_agent_workflow.py` L424 | 99 | 623 | — | Primary |
| 2 | `cli.main` | `poc_workflow/cli.py` L284 | 67 | 244 | 38 | Primary |
| 3 | `chatbot.ask` | `poc_workflow/chatbot.py` L437 | 59 | 558 | 9 | Primary |
| 4 | `quality_gate.data_audit_gate` | `poc_workflow/quality_gate.py` L1360 | 59 | 140 | — | Primary |
| 5 | `user_chat.user_chat_response` | `poc_workflow/user_chat.py` L446 | 37 | 259 | — | Primary |
| 6 | `pipeline.process_sources` | `poc_workflow/pipeline.py` L228 | 30 | 416 | — | Primary |
| 7 | `upload_processing.process_upload_document_group` | `poc_workflow/upload_processing.py` L230 | 26 | 384 | — | Primary |
| 8 | `webapp.create_app` | `poc_workflow/webapp.py` L1215 | — | 865 | — | Primary |
| S1 | `ai_review.quality_refill_decision` | `poc_workflow/ai_review.py` | — | — | — | Secondary |
| S2 | `upload_processing.verify_upload_rag_readiness` | `poc_workflow/upload_processing.py` | — | — | — | Secondary |
| S3 | `user_chat.qa_agent_chat_response` | `poc_workflow/user_chat.py` | — | — | — | Secondary |

## Requirements

### Requirement 1: Behavior Preservation

**User Story:** As a maintainer, I want decomposition to preserve observable behavior, so that refactoring carries no risk of changing what the system does for users.

#### Acceptance Criteria

1. WHEN a Hotspot decomposition is completed, THE Decomposition_Effort SHALL produce, for the same inputs and configuration as the pre-decomposition code and as verified by the pre-existing automated test suite, Observable_Behavior that is identical across all of its facets: CLI exit codes and stdout/stderr content, HTTP response status and body, persisted records, and QA/answer text and citations.
2. WHEN a decomposed CLI command is executed, THE Decomposition_Effort SHALL produce the same integer exit code and byte-for-byte identical stdout and stderr content as the pre-decomposition code for the same arguments and configuration.
3. WHEN a decomposed HTTP endpoint receives a request, THE Decomposition_Effort SHALL return the same response status code and the same response body as the pre-decomposition code for the same request and configuration, excluding inherently non-deterministic fields such as timestamps and auto-generated identifiers.
4. WHEN a decomposed answer path processes a query, THE Decomposition_Effort SHALL produce the same answer text and the same citation set (equal regardless of citation ordering) as the pre-decomposition code for the same query, corpus, and configuration.
5. WHEN a decomposed unit writes or updates persisted records, THE Decomposition_Effort SHALL produce the same persisted record content as the pre-decomposition code for the same input and configuration, excluding inherently non-deterministic fields such as timestamps and auto-generated identifiers.
6. IF a decomposition produces any Behavior_Regression — a difference in CLI exit code or stdout/stderr, HTTP status or body, persisted record content, or answer text or citation set, or a change in the pass/fail outcome of the pre-existing automated test suite — THEN THE Refactoring_Process SHALL treat the decomposition as failed and SHALL require the change to be reverted or corrected and re-verified against acceptance criteria 1 through 5 before completion.
7. THE Decomposition_Effort SHALL change only internal code structure and SHALL leave public function signatures, CLI argument contracts, and HTTP route contracts unchanged unless a contract change is explicitly approved.

### Requirement 2: Complexity Reduction Targets

**User Story:** As a maintainer, I want measurable complexity ceilings, so that "decomposed enough" is objective and verifiable.

#### Acceptance Criteria

1. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL reduce each resulting function to a Cyclomatic_Complexity less than or equal to 15, as measured by the Complexity_Scan.
2. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL reduce each resulting function to a Function_Length less than or equal to 80 LOC, as measured by the Complexity_Scan.
3. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL reduce each resulting function to a Nesting_Depth less than or equal to 5, as measured by the Complexity_Scan.
4. WHEN a Hotspot decomposition is completed, THE Complexity_Scan SHALL report the Cyclomatic_Complexity, Function_Length in LOC, and Nesting_Depth for each resulting function, together with a per-function pass or fail indication against the Complexity_Threshold.
5. IF a resulting function exceeds any of the Cyclomatic_Complexity, Function_Length, or Nesting_Depth limits of the Complexity_Threshold after decomposition, THEN THE Refactoring_Process SHALL record the function's identifier, its measured Cyclomatic_Complexity, Function_Length, and Nesting_Depth, the specific limit(s) exceeded, and a documented reason the threshold was not met.

### Requirement 3: Test Guarding And Characterization

**User Story:** As a maintainer, I want every decomposition guarded by tests, so that regressions are caught automatically rather than discovered in production.

#### Acceptance Criteria

1. WHEN a Hotspot is selected for decomposition and before any structural change to that Hotspot is made, THE Refactoring_Process SHALL run the full Test_Guard and SHALL record, for each test, its baseline pass-or-fail result and the baseline line-coverage percentage of the Hotspot.
2. WHERE a Hotspot has a recorded baseline line-coverage below 80 percent of its executable lines, THE Refactoring_Process SHALL add Characterization_Tests that capture the current Observable_Behavior before any structural change is made, until the Hotspot's recorded line-coverage is at least 80 percent.
3. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL run the full Test_Guard and SHALL require every test recorded as passing at baseline to pass.
4. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL require the line-coverage percentage of the decomposed code to be greater than or equal to the recorded baseline line-coverage percentage.
5. IF the Test_Guard reports a failure after decomposition for a test that was recorded as passing at baseline, THEN THE Refactoring_Process SHALL treat the decomposition as incomplete, SHALL retain the pre-decomposition code unchanged, and SHALL produce an indication identifying the failing test(s) until the failure is resolved.
6. WHEN the Test_Guard is run, THE Refactoring_Process SHALL execute the smoke scripts `poc_workflow/user_chat_render_smoke.py` and `poc_workflow/qa_test_eval.py` and SHALL require each script to complete with a zero (success) exit status.

### Requirement 4: Incremental Sequencing And Reversibility

**User Story:** As a maintainer, I want hotspots tackled one at a time in priority order, so that risk is reduced steadily and any change can be backed out cleanly.

#### Acceptance Criteria

1. THE Decomposition_Effort SHALL sequence Hotspot decompositions in descending order of the Complexity_Scan risk-reduction ranking, processing the highest-ranked Hotspot first; WHERE two or more Hotspots share the same ranking, THE Decomposition_Effort SHALL order them by a deterministic rule that produces the same sequence on every run.
2. THE Decomposition_Effort SHALL deliver each Hotspot decomposition as a Reversible_Change that is independently shippable and independently revertible, with no dependency on any other Hotspot's decomposition being shipped first.
3. WHEN one Hotspot decomposition is reverted, THE Decomposition_Effort SHALL leave the decompositions of all other Hotspots intact and unchanged.
4. THE Decomposition_Effort SHALL define exactly the eight Primary_Hotspots listed in the Hotspot Inventory as in-scope targets.
5. WHERE the three Secondary_Candidates are undertaken, THE Decomposition_Effort SHALL start them only after all eight Primary_Hotspots have been delivered as Reversible_Changes, SHALL apply the same sequencing and reversibility constraints to them, and SHALL treat the effort as complete even if none of the three Secondary_Candidates are decomposed.
6. WHEN a Hotspot decomposition is started, THE Refactoring_Process SHALL scope the change to a single Hotspot so that review and revert remain isolated.
7. WHILE a Hotspot decomposition is in progress, THE Decomposition_Effort SHALL NOT start another Hotspot decomposition until the in-progress decomposition is either delivered as a Reversible_Change or abandoned.
8. IF a Hotspot decomposition cannot be made independently shippable and independently revertible, THEN THE Decomposition_Effort SHALL stop that decomposition, restore the affected code to its pre-decomposition state, and flag the Hotspot for re-scoping with an indication of the reason it could not be isolated.

### Requirement 5: Decompose The QA Agent Workflow

**User Story:** As a maintainer, I want `_run_qa_agent_workflow_impl` split into bounded stages, so that the highest-complexity function in the project becomes understandable and testable.

#### Acceptance Criteria

1. WHEN `_run_qa_agent_workflow_impl` in `poc_workflow/qa_agent_workflow.py` is decomposed, THE Refactoring_Process SHALL extract its distinct workflow stages — scope gating, query analysis, retrieval planning, evidence retrieval, evidence-pack construction, format planning, answer drafting, answer verification, critique, procedure-compliance checking, and final formatting — into separately named functions, and SHALL ensure each extracted function and the remaining orchestrator meet the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5).
2. WHEN the QA agent workflow is decomposed, THE Decomposition_Effort SHALL produce the same returned result — answer text, citation set, trace steps, evidence summary, quality decision, compliance result, answer format, answer source, and fallback reason — and the same persisted answer-run record content as the pre-decomposition code for the same inputs and configuration.
3. IF the pre-decomposition workflow returns a failure, clarification request, or no-answer outcome for a given input, THEN THE Decomposition_Effort SHALL reproduce the same outcome with the same answer source, fallback reason, and clarification result after decomposition.
4. THE Refactoring_Process SHALL preserve the existing `run_qa_agent_workflow` entry point, including its name, parameters, and return contract, so that callers require no change.

### Requirement 6: Decompose The CLI Command Dispatcher

**User Story:** As a maintainer, I want `cli.main` split per command, so that the deeply nested dispatcher becomes a thin router over discrete handlers.

#### Acceptance Criteria

1. WHEN `cli.main` in `poc_workflow/cli.py` is decomposed, THE Refactoring_Process SHALL extract each command branch into a separate handler function, and SHALL ensure both each handler and the resulting `cli.main` router meet the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5).
2. WHEN a CLI command is invoked after decomposition, THE Decomposition_Effort SHALL produce the same integer exit code and byte-for-byte identical stdout and stderr content as the pre-decomposition code for the same arguments and configuration, including environment-variable-backed defaults.
3. THE Refactoring_Process SHALL preserve the existing CLI argument contract, including command and subcommand names, positional arguments, optional flags, enumerated choices, required flags, argument types, and defaults (including environment-variable-backed defaults).
4. IF a CLI invocation raises an unhandled exception after decomposition, THEN THE Decomposition_Effort SHALL reproduce the pre-decomposition error behavior, writing the same error payload and returning the same non-zero exit code.

### Requirement 7: Decompose The Chatbot Answer Path

**User Story:** As a maintainer, I want `chatbot.ask` split into retrieval, scope gating, context composition, and citation building, so that the answer path is modular and ready for the RAG uplift.

#### Acceptance Criteria

1. WHEN `chatbot.ask` in `poc_workflow/chatbot.py` is decomposed, THE Refactoring_Process SHALL separate the retrieval, scope-gating, context-composition, and citation-building responsibilities into distinct units, and SHALL ensure each resulting unit including the residual `ask` coordinator meets the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5).
2. WHEN a query is answered after decomposition, THE Decomposition_Effort SHALL produce character-for-character identical answer text and an identical collection of source references in the same order as the pre-decomposition code for the same query, corpus, and configuration.
3. IF the pre-decomposition code returns an error indication or an empty / no-answer outcome for a given query, THEN THE Decomposition_Effort SHALL reproduce the same error indication or empty / no-answer outcome after decomposition.
4. THE Refactoring_Process SHALL implement the extracted retrieval unit so that it depends only on the RAG_Uplift Retriever abstraction, so that any conforming retriever implementation (including the LocalRagIndex fallback) can be substituted without changing the scope-gating, context-composition, or citation-building units.
5. WHERE the RAG_Uplift retrieval or context-composition abstraction is adopted, THE Refactoring_Process SHALL confine the required changes to the extracted retrieval and context-composition units.

### Requirement 8: Decompose The Data Audit Quality Gate

**User Story:** As a maintainer, I want `data_audit_gate` split into named checks, so that the dense branching logic becomes individually testable rules.

#### Acceptance Criteria

1. WHEN `data_audit_gate` in `poc_workflow/quality_gate.py` is decomposed, THE Refactoring_Process SHALL extract each audit check into a separately named function, and SHALL ensure each extracted check and the remaining `data_audit_gate` orchestrator meet the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5).
2. WHEN the data audit gate evaluates an input after decomposition, THE Decomposition_Effort SHALL produce the same pass/warn/fail status and the same severity classification as the pre-decomposition code for the same manifest contents, workspace files, and production-or-local configuration.
3. WHEN the data audit gate evaluates an input after decomposition, THE Decomposition_Effort SHALL produce the same ordered list of blocker reasons and the same ordered list of warning notes as the pre-decomposition code for the same input and configuration.
4. IF the manifest is corrupt or unreadable, THEN THE Decomposition_Effort SHALL reproduce the pre-decomposition early-return outcome after decomposition.
5. THE Refactoring_Process SHALL preserve the existing `data_audit_gate` entry point and its public parameter contract so that callers require no change.

### Requirement 9: Decompose The Chat Response Assembly

**User Story:** As a maintainer, I want `user_chat_response` split into assembly steps, so that chat response construction is clear and testable.

#### Acceptance Criteria

1. WHEN `user_chat_response` in `poc_workflow/user_chat.py` is decomposed, THE Refactoring_Process SHALL extract its response-assembly steps into separately named functions, and SHALL ensure each extracted function and the remaining orchestrator meet the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5).
2. WHEN a chat response is assembled after decomposition, THE Decomposition_Effort SHALL produce a response payload that has the same set of keys and the same value for each corresponding key as the pre-decomposition code for the same input and configuration.
3. WHEN any of the response paths — annotated-answer match, out-of-scope rejection, clarification request, QA-agent answer, and standard retrieval answer — is exercised after decomposition, THE Decomposition_Effort SHALL produce the same response payload as the pre-decomposition code for the same input and configuration.
4. THE Refactoring_Process SHALL preserve the existing `user_chat_response` entry point and its public parameter contract so that callers require no change.

### Requirement 10: Decompose The Source Processing Pipeline

**User Story:** As a maintainer, I want `process_sources` split into pipeline stages, so that end-to-end source processing is composed of discrete, testable steps.

#### Acceptance Criteria

1. WHEN `process_sources` in `poc_workflow/pipeline.py` is decomposed, THE Refactoring_Process SHALL extract each processing stage into a separately named function, and SHALL ensure each extracted function and the remaining orchestrator meet the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5).
2. WHEN sources are processed after decomposition, THE Decomposition_Effort SHALL produce the same converted and normalized output and RAG-ready package artifacts, and the same persisted manifest-store records, ingestion-log entries, and processing-status records, as the pre-decomposition code for the same sources and configuration, excluding inherently non-deterministic fields such as timestamps.
3. IF a source fails processing, THEN THE Decomposition_Effort SHALL reproduce the pre-decomposition failure handling — the same failure classification, failure ingestion-log entry, failure processing-status record, and inbox lifecycle movement — after decomposition.
4. WHEN a source is unchanged and skipped, THE Decomposition_Effort SHALL produce the same skip outcome and the same persisted records as the pre-decomposition code.

### Requirement 11: Decompose The Upload Processing Orchestrator

**User Story:** As a maintainer, I want `process_upload_document_group` split into orchestration steps, so that the upload monolith becomes a sequence of bounded operations.

#### Acceptance Criteria

1. WHEN `process_upload_document_group` in `poc_workflow/upload_processing.py` is decomposed, THE Refactoring_Process SHALL extract each orchestration step into a separately named function, and SHALL ensure each extracted step and the remaining top-level orchestrator meet the Complexity_Threshold (CC ≤ 15, LOC ≤ 80, nesting ≤ 5).
2. WHEN an upload document group is processed successfully after decomposition, THE Decomposition_Effort SHALL produce the same returned result, terminal workflow status, workflow events, handoffs, reports, normalized output, and persisted manifest record as the pre-decomposition code for the same upload group and configuration, excluding inherently non-deterministic fields such as timestamps.
3. IF an upload document group is rejected or fails — including unsupported department, unsupported category, missing business code, no usable converted source, or a failed QA recheck — THEN THE Decomposition_Effort SHALL reproduce the same terminal outcome and the same persisted records as the pre-decomposition code after decomposition.
4. THE Refactoring_Process SHALL preserve the existing `process_upload_document_group` entry point and its public parameter contract so that callers require no change.

### Requirement 12: Decompose The Web Application Factory

**User Story:** As a maintainer, I want `create_app` split so routes are grouped into routers, so that the 865-line factory becomes a thin composition of route modules.

#### Acceptance Criteria

1. WHEN `create_app` in `poc_workflow/webapp.py` is decomposed, THE Refactoring_Process SHALL move every inline route definition into routers such that each route is registered in exactly one router, AND THE Refactoring_Process SHALL compose the application solely by registering those routers so that `create_app` contains zero inline route definitions after decomposition.
2. WHEN any decomposed endpoint receives a request with identical path, HTTP method, headers, query parameters, and request body under identical application configuration, THE Decomposition_Effort SHALL return the same HTTP status code, response body, and content type as the pre-decomposition code, for both success and error responses.
3. THE Refactoring_Process SHALL preserve every existing route path, HTTP method, and authentication/access-control requirement, AND THE Refactoring_Process SHALL NOT add or remove any route, so that the set of (path, HTTP method) pairs exposed after decomposition is identical to the set exposed before decomposition.
4. IF a route lacks authentication or access control in the pre-decomposition code, THEN THE Refactoring_Process SHALL preserve that route's existing protection state AND THE Refactoring_Process SHALL record an entry in the decomposition record that identifies the route by path and HTTP method and marks it as lacking authentication or access control.
5. THE Refactoring_Process SHALL produce a decomposition record that enumerates every route with its path, HTTP method, target router, and authentication/access-control state.
6. IF decomposition would change any route's path, HTTP method, or authentication/access-control requirement, THEN THE Refactoring_Process SHALL NOT apply that change AND THE Refactoring_Process SHALL flag the affected route in the decomposition record.

### Requirement 13: Decomposition Verification And Reporting

**User Story:** As a maintainer, I want each completed decomposition documented with before/after evidence, so that the team can review risk reduction and confirm behavior preservation.

#### Acceptance Criteria

1. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL record the before metrics of the original Hotspot function and the after metrics — Cyclomatic_Complexity, Function_Length, and Nesting_Depth — of each resulting extracted function.
2. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL record the baseline and post-decomposition Test_Guard pass/fail results for the decomposed code.
3. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL record the baseline and post-decomposition Test_Coverage (line-coverage percentage) for the decomposed code.
4. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL record the evidence used to confirm zero Behavior_Regression, covering the relevant Observable_Behavior categories — CLI exit code and stdout/stderr, HTTP status and body, persisted records, and QA/answer text and citations — together with the Characterization_Test pass results.
5. IF a resulting function does not meet the Complexity_Threshold, THEN THE Refactoring_Process SHALL record the function name, its measured Cyclomatic_Complexity, Function_Length, and Nesting_Depth, and the documented justification.
6. WHEN a Hotspot decomposition is completed, THE Refactoring_Process SHALL produce a single per-Hotspot decomposition record containing the items required by acceptance criteria 1 through 5 before the decomposition is marked complete.
