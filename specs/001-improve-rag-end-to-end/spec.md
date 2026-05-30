# Feature Specification: Improve RAG System End-to-End

**Feature Branch**: `001-improve-rag-end-to-end`

**Created**: 2026-05-30

**Status**: Draft

**Input**: User description: Improve RAG system end-to-end from raw data (MinerU metadata, images) -> RAG, chunking, embedding -> workflow QA logic (avoid over-rigid gating, multi-step reasoning, clean spelling) -> LLM models -> interface rendering and preview.

## User Scenarios & Testing

### User Story 1 - Document Ingest & Rich Chunking with Images (Priority: P1)
As an administrator, when I ingest a document, the system should parse it using MinerU, keep the structured Markdown, extract images and tables, resolve their references (`image_ref`, page indexes, coordinates), and generate rich chunks that preserve the document structure.
- **Why this priority**: Core foundation of the improved RAG system. Without clean chunks and resolved references, we cannot match queries or show previews.
- **Independent Test**: Run pipeline ingestion on a PDF document (e.g. `PD-TECH-A-02_rev04`), verify that the generated chunks in `rag_ready` contain resolved image locators and citation mappings.
- **Acceptance Scenarios**:
  1. **Given** a raw PDF in the inbox, **When** I run the ingestion pipeline, **Then** a package is built in `rag_ready/` containing the normalized markdown, `citation_map.json` with resolved image references, and `chunk_plan.json` matching the text sections.

### User Story 2 - Hybrid Search (Keyword + Local Embeddings) (Priority: P1)
As a chatbot backend, when a query is submitted, the retriever should perform hybrid search (BM25 keyword search + local vector similarity) to find the most relevant chunks, boosting precise document matches and code matches.
- **Why this priority**: Crucial to get the best context before calling the LLM.
- **Independent Test**: Query the search index with technical terms (e.g., "bảo dưỡng máy"), verify that the returned chunks are semantically relevant even if words don't match exactly.
- **Acceptance Scenarios**:
  1. **Given** a query, **When** `LocalRagIndex.search()` is executed, **Then** it uses hybrid retrieval (re-ranking combined score) and returns the top relevant chunks.

### User Story 3 - Softened QA Gating & Multi-Step LLM Reasoning (Priority: P1)
As a chatbot user, when I ask a question, the chatbot should not reject it too rigidly (soften out-of-scope checks). It should formulate a precise, structured answer based on retrieved documents, correcting grammar and Vietnamese spelling errors, and returning formatted block types.
- **Why this priority**: Directly impacts answer quality and user trust.
- **Independent Test**: Submit ambiguous or slightly off-topic queries, verify that they are answered with the correct source instead of a generic "Không tìm thấy căn cứ".
- **Acceptance Scenarios**:
  1. **Given** an engineering question, **When** the query is processed, **Then** `is_out_of_scope_query` does not block it prematurely, and the LLM receives the chunks to output a structured response with Tóm tắt, Các bước, and Nguồn.

### User Story 4 - Citation Preview with Images in UI (Priority: P2)
As a chatbot user, when I click on a citation card or source link in the chat UI, the system should open a preview panel on the side showing the matching lines from the markdown and the corresponding image or diagram (if referenced in the chunk).
- **Why this priority**: Major UX improvement, making the sources immediately verifiable.
- **Independent Test**: Click on a source card in the UI, verify the preview displays the highlighted document text and its associated image from MinerU.
- **Acceptance Scenarios**:
  1. **Given** a citation with an image reference, **When** I request its preview in the UI, **Then** the image is rendered inside the preview panel.

### User Story 5 - LLM Provider Configuration & Failover (Priority: P2)
As a developer, I want to configure the best LLM provider (e.g., DeepSeek, Gemini, etc.) and have the system fall back automatically if the primary provider fails.
- **Why this priority**: Ensures system robustness.
- **Independent Test**: Configure Gemini and DeepSeek endpoints, disable one and check that calls succeed via the other.
- **Acceptance Scenarios**:
  1. **Given** a failover chain, **When** a model times out, **Then** the client automatically tries the next model in the chain.

## Requirements

### Functional Requirements
- **FR-001**: System MUST parse MinerU metadata (`content_list_v2.json`, `middle.json`) during ingestion to build a structured citation map containing page numbers, bboxes, and image references.
- **FR-002**: System MUST serve MinerU-extracted images via a backend static/media endpoint: `/api/user/documents/{doc_id}/{version}/images/{image_name}`.
- **FR-003**: System MUST implement hybrid search combining word overlap TF-IDF/BM25 scores and vector search using local embeddings.
- **FR-004**: System MUST soften the `is_out_of_scope_query` filter to allow more queries to reach the LLM rather than blocking them immediately.
- **FR-005**: System MUST prompt the LLM to format answers using strict Vietnamese spelling, correct sentence semantics, and appropriate rendering blocks (e.g., tables, checklists, Mermaid flowcharts).
- **FR-006**: The frontend UI MUST render MinerU-extracted images in the citation preview panel when clicking on a citation with an `image_ref`.
- **FR-007**: The frontend UI MUST enable the "Xem trước" button and render a split screen showing highlighted text next to the image.

### Success Criteria
- **SC-001**: Ingestion citation mapping coverage must be 90% or higher for documents with MinerU metadata.
- **SC-002**: Ambiguous query rejection rates must be reduced by 50% through softened gating.
- **SC-003**: Citation preview must load in under 1.5 seconds and display the image (if present) without breaking layout.
- **SC-004**: System must support failover between at least Gemini and DeepSeek models.
