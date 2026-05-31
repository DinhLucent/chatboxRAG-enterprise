# Tasks: Improve RAG System End-to-End

**Input**: Design documents from `/specs/001-improve-rag-end-to-end/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api-contract.md, quickstart.md

**Tests**: Included because the feature specification defines Independent Tests and the API contract defines Contract Test Expectations. Write these tests before implementation and verify they fail for the missing behavior.

**Organization**: Tasks are grouped by user story so each story can be implemented and verified independently where possible.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files or has no dependency on incomplete tasks
- **[Story]**: Which user story the task belongs to, used only inside user story phases
- Every task includes a concrete file path

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add shared dependencies, feature flags, local service defaults, and package skeletons needed by later phases.

- [ ] T001 Update Python dependencies for qdrant-client, numpy, and optional local reranker support in pyproject.toml
- [ ] T002 [P] Create retrieval package marker in poc_workflow/retrieval/__init__.py
- [ ] T003 [P] Create agentic QA package marker in poc_workflow/agentic/__init__.py
- [ ] T004 Update Qdrant, reranker, and agentic QA environment examples in .env.example
- [ ] T005 Add local Qdrant service wiring and storage notes in docker-compose.app.yml
- [ ] T006 Add Qdrant, rerank, guidance, and agentic QA feature flags/defaults in poc_workflow/config.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core contracts and compatibility types that must exist before any story implementation can be completed.

**Critical**: No user story work should be merged until this phase is complete.

- [ ] T007 [P] Implement Chunk schema, chunk_type enum, and validation helpers in poc_workflow/retrieval/schema.py
- [ ] T008 [P] Implement RetrievalResult, Retriever protocol, and retriever factory shell in poc_workflow/retrieval/retriever.py
- [ ] T009 Extend SearchHit and IndexEntry with image_refs, page_start/page_end, bbox, section_path, source_locator, and debug score fields in poc_workflow/rag_index.py
- [ ] T010 Add retrieval backend, routing decision, relevance judge, and citation-validation telemetry fields in poc_workflow/database.py
- [ ] T011 Add reindex command routing skeleton for `python -m poc_workflow.cli reindex` in poc_workflow/cli.py
- [ ] T012 [P] Add shared MinerU block, image reference, and retrieval-hit fixtures in tests/conftest.py
- [ ] T013 [P] Add generated retrieval artifact cleanup for Qdrant/JSONL test outputs in tests/conftest.py

**Checkpoint**: Foundation ready; user story implementation can now proceed.

---

## Phase 3: User Story 1 - Document Ingest & Rich Chunking with Images (Priority: P1) - MVP

**Goal**: Ingest MinerU artifacts into normalized markdown, citation maps, and hierarchical chunks with resolved image/table/page/bbox metadata.

**Independent Test**: Run ingestion for a MinerU-backed sample such as `PD-TECH-A-02_rev04` and verify `rag_ready/` contains normalized markdown, `citation_map.json`, and `chunk_plan.json` with resolved image locators and section-aware chunks.

### Tests for User Story 1

- [ ] T014 [P] [US1] Add MinerU citation-map coverage test for page, bbox, image_refs, and source_locator extraction in tests/test_data_workflow.py
- [ ] T015 [P] [US1] Add hierarchical chunk classification test for section_path, chunk_type, parent_section_id, and image_refs in tests/test_retrieval_chunker.py
- [ ] T016 [P] [US1] Add ingestion smoke coverage for PD-TECH-A-02 image-bearing citations in tests/test_pilot_pdtech_a02.py

### Implementation for User Story 1

- [ ] T017 [US1] Extend MinerU block extraction to normalize page indexes, bboxes, image_refs, and table_refs in poc_workflow/data_workflow.py
- [ ] T018 [US1] Implement source-block to citation-record mapping with source_locator and display_locator in poc_workflow/data_workflow.py
- [ ] T019 [P] [US1] Implement hierarchical markdown chunk parsing by heading and section path in poc_workflow/retrieval/chunker.py
- [ ] T020 [P] [US1] Implement chunk_type, step_number, role, system_name, and form_code classification in poc_workflow/retrieval/chunker.py
- [ ] T021 [US1] Wire hierarchical chunking into rag_ready package generation and write chunk_plan.json in poc_workflow/data_workflow.py
- [ ] T022 [US1] Persist image_refs, page_start/page_end, bbox, section_path, parent_section_id, and chunk_type in LocalRagIndex dataset writes in poc_workflow/rag_index.py
- [ ] T023 [US1] Update retrieval text cleaning to preserve valuable tables, forms, steps, and image captions in poc_workflow/text_cleaning.py
- [ ] T024 [US1] Add ingestion telemetry for citation mapping coverage and dropped chunk counts in poc_workflow/data_workflow.py

**Checkpoint**: US1 produces independently inspectable chunk and citation artifacts.

---

## Phase 4: User Story 2 - Hybrid Search with Qdrant, Sparse Signals, and Rerank (Priority: P1)

**Goal**: Retrieve relevant context using dense embeddings, sparse/BM25 exact-match signals, Qdrant metadata filters, RRF fusion, reranking, parent-context expansion, and lexical fallback.

**Independent Test**: Query technical terms and exact codes, including synonym cases such as "bảo trì máy" vs "bảo dưỡng máy", and verify semantic hits, exact-code hits, rerank scores, and fallback behavior.

### Tests for User Story 2

- [ ] T025 [P] [US2] Add sparse/dense fusion tests for RRF ordering, exact-code retention, and heading/path boosts in tests/test_retrieval_qdrant.py
- [ ] T026 [P] [US2] Add retriever contract test for Qdrant down -> backend="lexical_fallback" in tests/test_retrieval_contract.py
- [ ] T027 [P] [US2] Add reindex idempotency test for Qdrant upsert plus non-empty JSONL fallback in tests/test_pipeline.py

### Implementation for User Story 2

- [ ] T028 [P] [US2] Implement dense embedding client and local embedding server adapter in poc_workflow/retrieval/embeddings.py
- [ ] T029 [P] [US2] Implement sparse BM25 encoder over the existing tokenizer in poc_workflow/retrieval/embeddings.py
- [ ] T030 [US2] Implement Qdrant collection creation, named vectors, payload indexes, and idempotent upsert in poc_workflow/retrieval/qdrant_store.py
- [ ] T031 [US2] Implement hybrid query, RRF fusion, heading/path boosts, and metadata filters in poc_workflow/retrieval/qdrant_store.py
- [ ] T032 [P] [US2] Implement cross-encoder reranker interface with cached no-op fallback in poc_workflow/retrieval/reranker.py
- [ ] T033 [US2] Implement parent-context expansion and evidence assembly in poc_workflow/retrieval/context_composer.py
- [ ] T034 [US2] Implement query classification and metadata filter builder in poc_workflow/retrieval/query_router.py
- [ ] T035 [US2] Implement LexicalRetriever adapter over LocalRagIndex in poc_workflow/retrieval/retriever.py
- [ ] T036 [US2] Wire retriever factory into the chatbot query path while preserving the public chat schema in poc_workflow/chatbot.py
- [ ] T037 [US2] Implement `python -m poc_workflow.cli reindex` to build chunks, vectors, Qdrant points, and JSONL fallback in poc_workflow/cli.py
- [ ] T038 [US2] Add retrieval debug scores, backend name, and filter summary to citations and logs in poc_workflow/chatbot.py

**Checkpoint**: US2 can answer retrieval-only checks through Qdrant and degrade to lexical fallback when Qdrant is unavailable.

---

## Phase 5: User Story 3 - Agentic QA, Soft Gating, and Multi-Step Reasoning (Priority: P1)

**Goal**: Replace brittle static routing with LLM-driven intent/slot filling, dynamic guidance, session state, relevance judging, answer validation, and better Vietnamese formatting while keeping deterministic fallbacks.

**Independent Test**: Submit ambiguous, misspelled, synonym, and slightly off-topic engineering queries; verify valid questions are not blocked prematurely, broad questions return `status="clarify"` with options, and complete questions return structured cited answers.

### Tests for User Story 3

- [ ] T039 [P] [US3] Add router JSON and deterministic fallback tests for misspelled, synonym, specific, and out_of_scope queries in tests/test_agentic_router.py
- [ ] T040 [P] [US3] Add dynamic guidance option generation tests using index hierarchy payloads in tests/test_agentic_guidance.py
- [ ] T041 [P] [US3] Add session_state accumulated_context merge and clarification limit tests in tests/test_agentic_session_state.py
- [ ] T042 [P] [US3] Add chat response contract tests for status="clarify" and status="success" in tests/test_qa_agent_workflow.py
- [ ] T043 [P] [US3] Add answer grounding validation tests for ungrounded citation detection and repair in tests/test_answer_quality.py

### Implementation for User Story 3

- [ ] T044 [US3] Add JSON/structured-output helper and router model selection support to OpenAICompatibleClient in poc_workflow/llm.py
- [ ] T045 [P] [US3] Implement RouterDecision model, LLM router prompt, and deterministic fallback mapping in poc_workflow/agentic/router.py
- [ ] T046 [P] [US3] Implement SessionState storage, merge, expiration, and serialization helpers in poc_workflow/agentic/session_state.py
- [ ] T047 [US3] Implement dynamic guidance option aggregation from retriever payload hierarchy in poc_workflow/agentic/guidance.py
- [ ] T048 [P] [US3] Implement batched relevance judge with keep-all fallback in poc_workflow/agentic/relevance_judge.py
- [ ] T049 [P] [US3] Implement answer formatter and citation validator with fallback to clean_answer in poc_workflow/agentic/answer_validator.py
- [ ] T050 [US3] Implement orchestrator flow router -> guidance or retrieval -> judge -> answer -> validator in poc_workflow/agentic/orchestrator.py
- [ ] T051 [US3] Replace primary chatbot.ask flow with the agentic orchestrator behind RAG_AGENTIC_ENABLED in poc_workflow/chatbot.py
- [ ] T052 [US3] Soften static is_out_of_scope_query, infer_department, and infer_category behavior for deterministic fallback in poc_workflow/chatbot.py
- [ ] T053 [US3] Update answer prompts for Vietnamese spelling correction, block structure, abstention, and citation rules in poc_workflow/llm.py
- [ ] T054 [US3] Echo canonical status fields and session_state.accumulated_context from /api/user/chat in poc_workflow/webapp.py

**Checkpoint**: US3 returns either guided clarification or grounded answers without relying on hardcoded device menus.

---

## Phase 6: User Story 4 - Citation Preview with Images in UI (Priority: P2)

**Goal**: Serve MinerU images securely and render a split citation preview with highlighted markdown plus matching image/diagram in the chat UI.

**Independent Test**: Click a source/citation preview action in the user chat and verify highlighted document text and the associated MinerU image load within the target preview latency.

### Tests for User Story 4

- [ ] T055 [P] [US4] Add image-serving endpoint tests for 200, 400 traversal, 403 access denied, and 404 missing image in tests/test_webapp.py
- [ ] T056 [P] [US4] Add citation endpoint contract test for image_url, section_path, display_locator, source_locator, page_start, and bbox in tests/test_webapp.py
- [ ] T057 [P] [US4] Add static renderer test for clarify chips and split citation preview states in tests/test_user_chat_static_renderer.py
- [ ] T058 [P] [US4] Add user chat render smoke coverage for image-bearing citation preview in tests/test_user_chat_render_smoke.py

### Implementation for User Story 4

- [ ] T059 [US4] Implement safe MinerU image route with path traversal and access-group checks in poc_workflow/webapp.py
- [ ] T060 [US4] Extend _public_document_citation_payload with image_url, source_locator, section_path, bbox, and display_locator in poc_workflow/webapp.py
- [ ] T061 [US4] Extend citation_payload to emit compact card aliases image_ref, page, and text_snippet in poc_workflow/chatbot.py
- [ ] T062 [US4] Enable "Xem trước" preview actions and citation detail fetching in poc_workflow/static/user/user-chat.js
- [ ] T063 [US4] Render split preview with highlighted markdown, image panel, loading, empty, and error states in poc_workflow/static/user/user-chat.js
- [ ] T064 [P] [US4] Add responsive split-preview styles and image constraints in poc_workflow/static/user/user-chat.css

**Checkpoint**: US4 makes cited evidence visually inspectable without exposing raw converted files.

---

## Phase 7: User Story 5 - LLM Provider Configuration and Failover (Priority: P2)

**Goal**: Configure provider order and fail over between Gemini, DeepSeek, and local/free providers without changing chatbot code.

**Independent Test**: Configure multiple providers, force the primary model to timeout or fail, and verify the next provider in KB_LLM_FAILOVER_CHAIN completes the call.

### Tests for User Story 5

- [ ] T065 [P] [US5] Add failover-chain parsing, disabled-provider, timeout, and secondary-success tests in tests/test_llm.py
- [ ] T066 [P] [US5] Add QA eval coverage for primary provider failure followed by fallback answer success in tests/test_qa_agent_eval.py

### Implementation for User Story 5

- [ ] T067 [US5] Extend LLM_PRESETS and provider environment mapping for Gemini, DeepSeek, free/local, and router-model usage in poc_workflow/llm.py
- [ ] T068 [US5] Harden OpenAICompatibleClient failover timeout handling, error capture, and stderr telemetry in poc_workflow/llm.py
- [ ] T069 [US5] Add KB_LLM_FAILOVER_CHAIN, RAG_ROUTER_MODEL, and agentic model defaults to .env.example
- [ ] T070 [US5] Document failover validation commands and recommended provider order in specs/001-improve-rag-end-to-end/quickstart.md

**Checkpoint**: US5 can survive primary LLM provider failure and preserve answer behavior through the configured chain.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Validate success criteria, document operational guidance, and keep experimental m_flow work isolated from the production path.

- [ ] T071 [P] Add hard-question benchmark cases for experimental m_flow comparison in eval/mflow_hard_questions.json
- [ ] T072 Add m_flow experimental feature flag documentation and non-default wiring notes in docs/architecture.md
- [ ] T073 [P] Update full quickstart validation checklist for Qdrant, fallback, guidance, preview, and failover in specs/001-improve-rag-end-to-end/quickstart.md
- [ ] T074 Run pytest, user chat render smoke, and QA eval commands documented in specs/001-improve-rag-end-to-end/quickstart.md
- [ ] T075 Update acceptance evidence for SC-001, SC-002, SC-003, and SC-004 in docs/quality-gate-latest.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can start immediately.
- **Foundational (Phase 2)**: Depends on Setup and blocks all user story completion.
- **US1 (Phase 3)**: Depends on Foundational; provides production chunk/citation artifacts.
- **US2 (Phase 4)**: Depends on Foundational; can be tested with fixtures, but production indexing benefits from US1 artifacts.
- **US3 (Phase 5)**: Depends on Foundational; can be tested with mock retriever results, but production answer quality depends on US2.
- **US4 (Phase 6)**: Depends on Foundational and can use mocked citations; production preview depends on US1 citation metadata.
- **US5 (Phase 7)**: Depends on Setup/Foundational and can proceed in parallel with US1-US4.
- **Polish (Phase 8)**: Depends on the selected completed stories.

### User Story Dependencies

- **US1 (P1)**: Independent ingest MVP after Phase 2.
- **US2 (P1)**: Independently testable with chunk fixtures after Phase 2; recommended after US1 for real corpus validation.
- **US3 (P1)**: Independently testable with mock retriever and LLM fixtures after Phase 2; recommended after US2 for end-to-end QA.
- **US4 (P2)**: Independently testable with fixture citations after Phase 2; real image preview requires US1 metadata.
- **US5 (P2)**: Independent after Phase 2.

### Completion Order

1. Complete Phase 1 and Phase 2.
2. Deliver US1 as the ingest MVP.
3. Deliver US2 and US3 to complete the P1 chatbot-quality vertical slice.
4. Deliver US4 for source verification UX.
5. Deliver US5 for operational robustness.
6. Run Phase 8 acceptance evidence and quickstart validation.

---

## Parallel Execution Examples

### User Story 1

```text
Task: "T014 Add MinerU citation-map coverage test for page, bbox, image_refs, and source_locator extraction in tests/test_data_workflow.py"
Task: "T015 Add hierarchical chunk classification test for section_path, chunk_type, parent_section_id, and image_refs in tests/test_retrieval_chunker.py"
Task: "T019 Implement hierarchical markdown chunk parsing by heading and section path in poc_workflow/retrieval/chunker.py"
Task: "T020 Implement chunk_type, step_number, role, system_name, and form_code classification in poc_workflow/retrieval/chunker.py"
```

### User Story 2

```text
Task: "T025 Add sparse/dense fusion tests for RRF ordering, exact-code retention, and heading/path boosts in tests/test_retrieval_qdrant.py"
Task: "T026 Add retriever contract test for Qdrant down -> backend=\"lexical_fallback\" in tests/test_retrieval_contract.py"
Task: "T028 Implement dense embedding client and local embedding server adapter in poc_workflow/retrieval/embeddings.py"
Task: "T029 Implement sparse BM25 encoder over the existing tokenizer in poc_workflow/retrieval/embeddings.py"
Task: "T032 Implement cross-encoder reranker interface with cached no-op fallback in poc_workflow/retrieval/reranker.py"
```

### User Story 3

```text
Task: "T039 Add router JSON and deterministic fallback tests for misspelled, synonym, specific, and out_of_scope queries in tests/test_agentic_router.py"
Task: "T040 Add dynamic guidance option generation tests using index hierarchy payloads in tests/test_agentic_guidance.py"
Task: "T041 Add session_state accumulated_context merge and clarification limit tests in tests/test_agentic_session_state.py"
Task: "T045 Implement RouterDecision model, LLM router prompt, and deterministic fallback mapping in poc_workflow/agentic/router.py"
Task: "T046 Implement SessionState storage, merge, expiration, and serialization helpers in poc_workflow/agentic/session_state.py"
Task: "T048 Implement batched relevance judge with keep-all fallback in poc_workflow/agentic/relevance_judge.py"
Task: "T049 Implement answer formatter and citation validator with fallback to clean_answer in poc_workflow/agentic/answer_validator.py"
```

### User Story 4

```text
Task: "T055 Add image-serving endpoint tests for 200, 400 traversal, 403 access denied, and 404 missing image in tests/test_webapp.py"
Task: "T056 Add citation endpoint contract test for image_url, section_path, display_locator, source_locator, page_start, and bbox in tests/test_webapp.py"
Task: "T057 Add static renderer test for clarify chips and split citation preview states in tests/test_user_chat_static_renderer.py"
Task: "T064 Add responsive split-preview styles and image constraints in poc_workflow/static/user/user-chat.css"
```

### User Story 5

```text
Task: "T065 Add failover-chain parsing, disabled-provider, timeout, and secondary-success tests in tests/test_llm.py"
Task: "T066 Add QA eval coverage for primary provider failure followed by fallback answer success in tests/test_qa_agent_eval.py"
Task: "T069 Add KB_LLM_FAILOVER_CHAIN, RAG_ROUTER_MODEL, and agentic model defaults to .env.example"
Task: "T070 Document failover validation commands and recommended provider order in specs/001-improve-rag-end-to-end/quickstart.md"
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 (US1) and validate ingestion/citation artifacts.
3. Stop and verify US1 independently before changing query behavior.

### P1 End-to-End Slice

1. Add US2 to make retrieval hybrid, ranked, and fallback-safe.
2. Add US3 to make chat routing, guidance, answer formatting, and citation validation agentic.
3. Validate the P1 vertical using pytest, QA eval, and representative Vietnamese engineering queries.

### Incremental Delivery

1. US1 delivers inspectable source artifacts.
2. US2 improves retrieval quality without requiring UI changes.
3. US3 improves answer quality and clarification behavior while keeping deterministic fallbacks.
4. US4 adds source preview and image verification.
5. US5 hardens provider operations.

### Parallel Team Strategy

1. One developer handles Phase 1 and Phase 2 contracts.
2. After Phase 2, separate developers can work on US1 chunking, US2 retrieval, US3 agentic tests with fixtures, US4 UI contract tests, and US5 LLM failover.
3. Integrate in P1 order before final acceptance evidence.

---

## Notes

- Tasks marked [P] should touch separate files or only tests/fixtures.
- Tests in each user story should be written first and observed failing before implementation.
- Keep Qdrant optional at runtime: `RAG_RETRIEVER=auto` must fall back to lexical JSONL.
- Do not expose raw `converted_raw/` files; serve only resolved MinerU images through the authenticated route.
- m_flow remains experimental and disabled by default.
