# Tasks: Improve RAG System End-to-End

**Input**: Design documents from `/specs/001-improve-rag-end-to-end/`

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Verify local environment variables (`.env`) for embedding and LLM servers
- [ ] T002 Verify current tests pass by running pytest in root folder

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data structures and layout extensions

- [ ] T003 [P] Add fields `image_ref`, `bbox`, `page_start`, `page_end`, and `sheet_name` to `SearchHit` and `IndexEntry` in `poc_workflow/rag_index.py`

---

## Phase 3: User Story 1 - Document Ingest & Rich Chunking with Images (Priority: P1) 🎯 MVP

**Goal**: Parse and resolve MinerU metadata (coordinate bounding boxes, page indices, image references) during ingestion.

**Independent Test**: Verify that ingestion of a sample PDF produces a citation map with resolved image links.

### Implementation for User Story 1

- [ ] T004 [US1] Update `mineru_source_blocks` in `poc_workflow/data_workflow.py` to extract page numbers, bounding boxes, and image references from middle.json and content_list_v2.json
- [ ] T005 [US1] Update `build_rag_ready_package` in `poc_workflow/data_workflow.py` to save `image_ref` and coordinate properties into the citation map
- [ ] T006 [US1] Update `LocalRagIndex._write_dataset` in `poc_workflow/rag_index.py` to persist `image_ref`, `bbox`, page start/end, and sheet name to `dataset.jsonl`

---

## Phase 4: User Story 2 - Hybrid Search (Keyword + Local Embeddings) (Priority: P1)

**Goal**: Support combining word overlap scores with semantic vector embeddings in the local index query flow.

**Independent Test**: Retrieve chunks for query "bảo dưỡng máy" and verify semantic matches are returned.

### Implementation for User Story 2

- [ ] T007 [US2] Implement vector retrieval logic and similarity ranking inside `poc_workflow/rag_index.py`
- [ ] T008 [US2] Update search matching in `LocalRagIndex.search` inside `poc_workflow/rag_index.py` to execute hybrid re-ranking (keyword score + embedding similarity)

---

## Phase 5: User Story 3 - Softened QA Gating & Multi-Step LLM Reasoning (Priority: P1)

**Goal**: Prevent rigid query rejections and prompt the LLM to format structured, cleaned Vietnamese answers.

**Independent Test**: Submit natural language queries and verify spelling-corrected answers with sources.

### Implementation for User Story 3

- [ ] T009 [US3] Soften keyword check lists in `is_out_of_scope_query` inside `poc_workflow/chatbot.py`
- [ ] T010 [US3] Update `citation_payload` in `poc_workflow/chatbot.py` to forward `image_ref`, `source_locator`, and page number fields
- [ ] T011 [US3] Upgrade system instruction prompt templates in `OpenAICompatibleClient.answer` in `poc_workflow/llm.py` to correct Vietnamese spelling and structure blocks

---

## Phase 6: User Story 4 - Citation Preview with Images in UI (Priority: P2)

**Goal**: Expose an image serving endpoint and render a side-by-side preview panel showing markdown content and diagrams.

**Independent Test**: Click "Xem trước" in the chat client and see the highlighted source text with its corresponding image.

### Implementation for User Story 4

- [ ] T012 [US4] Add static/media router endpoint in `poc_workflow/webapp.py` to serve extracted images from `mineru_artifacts/images`
- [ ] T013 [US4] Refactor `_public_document_citation_payload` in `poc_workflow/webapp.py` to retrieve detailed citation maps including image urls
- [ ] T014 [US4] Enable "Xem trước" in `poc_workflow/static/user/user-chat.js` and render split screen showing highlighted text alongside images
- [ ] T015 [P] [US4] Add preview layout styles in `poc_workflow/static/user/user-chat.css`

---

## Phase 7: User Story 5 - LLM Provider Configuration & Failover (Priority: P2)

**Goal**: Allow robust failover between Gemini and DeepSeek models.

**Independent Test**: De-activate the primary endpoint and verify that queries succeed by falling back to the next model in the chain.

### Implementation for User Story 5

- [ ] T016 [US5] Verify and refine failover chains in `llm_failover_chain` and `OpenAICompatibleClient._build_failover_configs` inside `poc_workflow/llm.py`

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Verification and optimization

- [ ] T017 Run all unit and integration test suites with `pytest`
- [ ] T018 Document changes in walkthrough and finalize configuration

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - Phase 3 (US1) -> Phase 4 (US2) -> Phase 5 (US3) -> Phase 6 (US4) -> Phase 7 (US5)
- **Polish (Phase 8)**: Depends on all user stories being complete
