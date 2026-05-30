# Implementation Plan: Improve RAG System End-to-End

**Branch**: `001-improve-rag-end-to-end` | **Date**: 2026-05-30 | **Spec**: [specs/001-improve-rag-end-to-end/spec.md](file:///d:/MyProject/demo-chatbot-engineerworkflow/specs/001-improve-rag-end-to-end/spec.md)

**Input**: Feature specification from `/specs/001-improve-rag-end-to-end/spec.md`

## Summary

End-to-end uplift of the engineering-department RAG chatbot. The target pipeline (architect-selected) is:

```
MinerU → normalized Markdown/JSON → hierarchical chunking → Qdrant hybrid index
       → reranker → parent-context expansion → context composer
       → LLM answer with citation → QA guardrails
```

The value is concentrated in **index schema + retrieval strategy**, not in replacing the parser or the app. MinerU already handles the front of the pipeline well (PDF/image/DOCX/PPTX/XLSX → Markdown + JSON, preserving heading, paragraph, list, image, table, formula, OCR, and reading order). So this plan keeps MinerU as the parser and invests in:

1. **Hierarchical chunk schema** — every chunk carries procedure/section/role/form metadata and a `chunk_type` (policy | step | condition | exception | table | form | image_caption | …), with `parent_section_id` for parent-context expansion.
2. **Qdrant hybrid retrieval (production core)** — dense (semantic) + sparse/BM25 (codes, form names, step names) vectors in a single Qdrant collection, fused with Reciprocal Rank Fusion, plus heading/section-path boosts.
3. **Multi-tier retrieval** — query classification → metadata filter → hybrid retrieval → cross-encoder rerank (top 30–80) → parent context expansion → answer composer.
4. **Softened QA workflow** — relax the rigid `is_out_of_scope_query` gate, let the LLM judge scope from retrieved evidence, abstain or ask back when evidence is weak, and produce concise, well-formed Vietnamese answers with correct render blocks and citations.
5. **LLM selection** — recommend the best-fit model versus the current DeepSeek chat, kept config-driven with failover (see research.md).
6. **Interface** — enable the disabled "Xem trước" preview, add an authenticated image-serving endpoint, render a split-screen citation preview (highlighted source text + MinerU image/diagram).

### Stack roles (architect decision)

| Component | Role in this project |
|-----------|----------------------|
| **MinerU** | Primary parser. Keep Markdown + JSON + image/table refs. No change to parsing. |
| **Qdrant** | **Production core** for vector + hybrid retrieval. Operable and strong enough for ~150 docs / low-thousands of chunks. |
| **Vespa** | Optional future swap if a much stronger ranking engine / complex rank profiles / larger scale are needed. Not in scope now. |
| **m_flow** | **Experimental** graph/procedural-memory layer for hard multi-hop / condition / exception / dependency questions. Benchmarked separately, behind a flag. |
| **Kotaemon** | **Reference baseline / UI ideas only**, not a core dependency. |
| **LlamaIndex / Haystack** | Possible orchestration helpers, but retrieval logic stays owned by us — frameworks must not dictate ranking. Adopt only if they reduce code without taking control. |

**Final decision**: production core = **Qdrant hybrid retrieval + reranker + hierarchical metadata schema**. m_flow = experimental procedural/graph layer (separate benchmark on the hard-question set). Kotaemon = reference only.

This is a deliberate change from the prior "no external vector DB" stance: it adds a Qdrant service and new Python dependencies. To contain risk, the existing local-JSONL lexical index (`LocalRagIndex`) is retained as an **offline fallback retriever**, and Qdrant becomes the default when configured/reachable.

## Technical Context

**Language/Version**: Python 3.11+ (backend), vanilla ES (no framework) for the SPA frontend

**Primary Dependencies**:
- Existing: FastAPI + Pydantic + uvicorn (web), `urllib` OpenAI-compatible LLM client (`poc_workflow/llm.py`), local embedding server (`scripts/local_openai_embedding_server.py`, HuggingFace `transformers` + `torch`), MinerU CLI/HTTP, pytest.
- **New**: `qdrant-client` (vector/hybrid store), a sparse encoder for BM25/SPLADE-style vectors (e.g. FastEmbed BM25 or an in-house BM25 over the existing tokenizer), a cross-encoder reranker (local sentence-transformers cross-encoder, e.g. multilingual MiniLM cross-encoder) served via the local embedding service or a sibling endpoint. `numpy` for fusion math.

**Storage**:
- **Qdrant collection** `technical_active` (named vectors: `dense` + `sparse`) as the production retrieval store.
- SQLite (`poc_workflow/database.py`) for logging/metadata; filesystem for normalized markdown, MinerU artifacts, extracted images.
- Retained JSONL local index (`ragflow_index/*.jsonl`) as the offline fallback retriever.

**Testing**: pytest (existing suite + smoke scripts e.g. `user_chat_render_smoke.py`, `qa_test_eval.py`); a new hard-question benchmark set for the m_flow experimental layer.

**Target Platform**: Local Windows/Linux server. Qdrant runs as a local service (Docker `qdrant/qdrant`, or the native binary, or Qdrant embedded/in-memory mode for tests). Offline-capable: local embeddings + local reranker + lexical fallback when Qdrant or LLM are unavailable.

**Project Type**: Web service (FastAPI) + static single-page chat UI

**Performance Goals**: Hybrid retrieve + rerank within interactive latency (target < ~400ms server-side retrieval before the LLM call for the active corpus); citation preview load < 1.5s (SC-003); answer latency dominated by the LLM call (concise prompts, capped tokens).

**Constraints**:
- Qdrant is the production retriever but MUST degrade gracefully to the lexical JSONL fallback if unreachable (no hard outage).
- Embeddings come from the local OpenAI-compatible server or precomputed at index build; reranker runs locally by default (no document leaves the box unless a cloud provider is explicitly configured).
- Do not expose raw `converted_raw/` files publicly; respect document access groups.
- Treat retrieved context as untrusted (prompt-injection guard already present in `llm.py`).

**Scale/Scope**: Single-tenant engineering knowledge base; ~150 documents, low-thousands of chunks; concurrency handled by the existing user-chat queue (`webapp.py`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

> Note: `.specify/memory/constitution.md` is still the unfilled template (placeholder principles, not ratified). No ratified gates exist to fail against. The de-facto principles below are advisory; recommend running `/speckit.constitution` to ratify real gates — especially relevant now that an external service (Qdrant) is being introduced.

- [x] **Module isolation**: retrieval is introduced behind a `Retriever` abstraction (`QdrantRetriever` vs existing `LocalRagIndex`) so `chatbot.ask()` is decoupled from the backend.
- [x] **Text/CLI interface preserved**: indexing and chat remain invokable via CLI and HTTP; a new `reindex`/`qdrant-upsert` CLI step is additive.
- [x] **Test-first / verification**: each user story has an independent test; Qdrant work is testable via in-memory/embedded mode; verified with pytest + smoke + QA eval before completion.
- [⚠] **Simplicity / YAGNI**: introducing Qdrant + reranker + (experimental) m_flow adds infra and dependencies. Justified in Complexity Tracking below; mitigated by keeping the lexical fallback and gating m_flow behind a flag.
- [x] **Observability**: retain structured logging (SQLite + stderr failover traces); add per-stage retrieval telemetry (lexical/dense/sparse/rerank scores, chosen backend).

**Result**: PASS (advisory) with one justified complexity item (external retrieval service). See Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-improve-rag-end-to-end/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0 output (decisions: schema, Qdrant hybrid, rerank, m_flow, model)
├── data-model.md        # Phase 1 entities (chunk schema, Qdrant point, retrieval result, citation)
├── quickstart.md        # Phase 1 run & verify guide (incl. Qdrant bring-up)
├── contracts/           # Phase 1 contracts (image serving, citation, chat, retriever interface)
│   └── api-contract.md
├── checklists/          # Quality checklists
└── tasks.md             # Phase 2 tasks list (/speckit.tasks output)
```

### Source Code (repository root)

Grounded in the current repository, with additive retrieval modules:

```text
poc_workflow/
├── config.py                     # datasets, departments, dirs; + Qdrant/rerank config
├── data_workflow.py              # MinerU block parsing, citation map, rag_ready package
│                                 #   (mineru_source_blocks, build_citation_record, bbox/image refs)
├── rag_index.py                  # LocalRagIndex (lexical) — retained as offline fallback
├── retrieval/                    # NEW package: backend-agnostic retrieval
│   ├── schema.py                 #   hierarchical Chunk schema + chunk_type classification
│   ├── chunker.py                #   hierarchical chunking (section_path, parent_section_id)
│   ├── embeddings.py             #   dense + sparse encoders (local server + BM25/SPLADE)
│   ├── qdrant_store.py           #   QdrantRetriever: collection mgmt, hybrid query, RRF
│   ├── reranker.py               #   cross-encoder rerank over top-K candidates
│   ├── query_router.py           #   query classification + metadata filter builder
│   ├── context_composer.py       #   parent-context expansion + evidence assembly
│   └── retriever.py              #   Retriever protocol; select Qdrant vs lexical fallback
├── chatbot.py                    # ask(), softened is_out_of_scope_query(), citation_payload()
├── llm.py                        # OpenAICompatibleClient (answer/failover), LLM_PRESETS, chain
├── webapp.py                     # FastAPI app: + image route, extended citation/preview endpoints
└── static/user/                  # user-chat.js (enable "Xem trước"), user-chat.css (split preview)

scripts/
├── local_openai_embedding_server.py   # dense embeddings (+ optional rerank endpoint)
└── (qdrant bring-up via docker/binary — documented in quickstart)

refs/                              # read-only references to borrow patterns from
├── ragflow/        # chunking + rerank patterns
├── m_flow/         # experimental cone-graph procedural memory (Episode/Facet/FacetPoint/Entity)
├── kotaemon/       # reference UI / RAG app organization
└── MinerU/ Vespa-notes/ turbovec/ ...
```

**Structure Decision**: Keep the single Python package + static SPA. Introduce a `poc_workflow/retrieval/` package so the new Qdrant hybrid pipeline is cleanly separated behind a `Retriever` protocol, with `LocalRagIndex` adapted as the fallback implementation. m_flow lives behind an experimental flag and is benchmarked separately, not wired into the default answer path.

### Where each spec area lands

| Spec area | Primary files |
|-----------|---------------|
| US1 Data + hierarchical chunking + image refs | `data_workflow.py`, `retrieval/schema.py`, `retrieval/chunker.py`, `text_cleaning.py` |
| US2 Qdrant hybrid retrieval + rerank | `retrieval/embeddings.py`, `retrieval/qdrant_store.py`, `retrieval/reranker.py`, `retrieval/query_router.py`, `retrieval/context_composer.py`, `config.py` |
| US3 Softened gating + multi-step reasoning | `chatbot.py` (`is_out_of_scope_query`, `ask`), `retrieval/context_composer.py`, `llm.py` (`answer` prompt) |
| US4 Citation preview + images | `webapp.py` (image route, citation payload), `static/user/user-chat.js`, `user-chat.css` |
| US5 LLM selection + failover | `llm.py` (`LLM_PRESETS`, `llm_failover_chain`), `.env` / `.env.example` |
| (Experimental) procedural/graph layer | `refs/m_flow` patterns → flagged module + hard-question benchmark |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| External vector DB (Qdrant) replacing in-memory lexical core | Production-grade hybrid (dense+sparse) retrieval with metadata filtering, RRF, and room to scale; needed for condition/exception/multi-step question quality | Pure in-memory cosine + lexical (prior plan) caps ranking quality and metadata-filtered hybrid; rejected by architect for the production core (kept as offline fallback) |
| Cross-encoder reranker | Precision on top 30–80 candidates materially improves answer grounding | RRF-only ordering leaves near-duplicates/weak hits high; rerank is the standard precision lever |
| Experimental m_flow graph layer | Hard multi-hop / dependency / "if A then which procedure?" questions are not well served by chunk similarity alone | Skipping it loses the upside; mitigated by keeping it experimental, flagged, and separately benchmarked (not in the default path) |
