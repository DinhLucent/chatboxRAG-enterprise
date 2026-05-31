# Research & Decisions: End-to-End RAG Improvements

Phase 0 output. Records the technical decisions, rationale, and alternatives for the architect-selected pipeline:
`MinerU → normalized Markdown/JSON → hierarchical chunking → Qdrant hybrid index → reranker → context composer → LLM answer with citation → QA guardrails`.

## Current-State Findings (baseline grounding)

- **Retrieval is purely lexical today.** `LocalRagIndex.search()` (`poc_workflow/rag_index.py`) scores by token overlap, exact-code boosts, phrase scoring, and many hand-tuned `*_adjustment` heuristics. No embeddings, no vector store. → Qdrant hybrid retrieval is genuinely new work; the lexical scorer is kept as an offline fallback.
- **No external retrieval infra is present.** `qdrant-client`, LlamaIndex, Haystack, FastEmbed are NOT in `pyproject.toml` (current deps: fastapi/uvicorn/pydantic only). Adding Qdrant is a new operational + dependency commitment.
- **MinerU extraction already exists** in `data_workflow.py` (`mineru_source_blocks`, `mineru_block_bbox`, `mineru_block_image_path`, `resolve_mineru_image_ref`, `build_citation_record`). Page/bbox/image-ref data is available but NOT yet propagated into the index or citation payloads.
- **Chunking is flat.** `chunk_markdown_with_metadata` produces line-range text chunks with no `chunk_type`, `section_path`, `parent_section_id`, role, or form metadata. → Hierarchical schema is new work.
- **Gating + routing are static and brittle.** `is_out_of_scope_query()`, `infer_department()`, and `infer_category()` use hardcoded keyword lists that miss synonyms, typos, and indirect phrasing — rejecting valid questions or letting generic ones through. → Replaced by an LLM Router (Agentic QA layer); static functions retained as deterministic fallback.
- **LLM prompt** already enforces the 3-section format and prompt-injection guards; it lacks explicit Vietnamese spelling correction and richer render-block guidance. Failover exists (`llm_failover_chain`, `LLM_PRESETS` include deepseek + gemini).
- **UI preview is hard-disabled** in `static/user/user-chat.js`; there is no image-serving route in `webapp.py`. Markdown line-range preview plumbing (`_markdown_preview_lines`) already exists.

## Decision 1: Hierarchical Chunk Schema
- **Chosen**: A structured chunk record carrying at minimum:
  `doc_id, procedure_id, procedure_name, version, effective_date, department, owner, confidential_level, source_file, page_start, page_end, section_path, heading_level, chunk_type (policy|step|condition|exception|table|form|image_caption), step_number, role, system_name, form_code, content, parent_section_id, image_refs, table_refs`.
  Built during ingestion from MinerU Markdown + JSON (reading order, headings, tables, images) and the existing manifest record.
- **Rationale**: Retrieval quality for condition/exception/multi-step questions depends on structure, not just text similarity. `chunk_type` + `section_path` + `parent_section_id` enable metadata filtering, heading/path boosts, and parent-context expansion. `image_refs`/`table_refs` unlock the citation preview.
- **Alternatives considered**: Keep flat line-range chunks (status quo) — rejected; cannot express conditions/exceptions/roles or support parent expansion. Borrowed structural ideas from `./refs/ragflow` chunking; rephrased for compliance.

## Decision 2: Qdrant as Production Retrieval Core
- **Chosen**: A single Qdrant collection (`technical_active`) with **named vectors** — `dense` (semantic) and `sparse` (BM25/SPLADE-style) — plus the full chunk schema as payload for metadata filtering. Run Qdrant locally (Docker `qdrant/qdrant` or native binary; embedded/in-memory mode for tests).
- **Rationale**: Qdrant natively supports hybrid dense+sparse queries with server-side fusion and rich payload filtering, is operationally simple for ~150 docs, and leaves headroom to scale. ([Qdrant hybrid queries](https://qdrant.tech/documentation/concepts/hybrid-queries/), [hybrid + reranking tutorial](https://qdrant.tech/documentation/tutorials-basics/reranking-hybrid-search/); rephrased for compliance.)
- **Fallback**: If Qdrant is unreachable, degrade to the existing lexical `LocalRagIndex` so chat never hard-fails (single-mode degradation is a documented best practice).
- **Alternatives considered**:
  - *Vespa*: stronger/complex ranking engine and larger scale — deferred; overkill for current corpus, higher operational cost. Kept as a documented future swap.
  - *In-memory numpy cosine (prior plan)*: rejected as the production core by the architect; retained only as the offline fallback.
  - *FAISS/chroma*: weaker native hybrid + payload filtering than Qdrant for this use case.

## Decision 3: Hybrid Fusion + Heading/Path Boost
- **Chosen**: Retrieve dense and sparse candidate lists and fuse with **Reciprocal Rank Fusion** (RRF, default k=60), then apply heading/section-path boosts (prefer chunks whose `section_path` matches the query intent) and the existing domain priors as post-fusion adjustments. A weighted-linear blend is available as a config alternative.
- **Rationale**: RRF is scale-robust (no normalization/weight tuning), battle-tested, and requires no training. Sparse keeps exact matches deterministic (document codes like `KT-QT-002`, form codes, step names); dense captures synonyms ("bảo trì" vs "bảo dưỡng"). ([RRF position-based boosting](https://qdrant.tech/documentation/concepts/hybrid-queries/); 2026 hybrid-architecture guidance recommends RRF with configurable k — rephrased for compliance.)
- **Alternatives considered**: Replace lexical entirely with dense — rejected (loses exact-code determinism). Pure weighted blend — kept optional; needs per-query tuning.

## Decision 4: Cross-Encoder Reranking
- **Chosen**: Rerank the top **30–80** fused candidates with a local multilingual **cross-encoder** (sentence-transformers cross-encoder served locally, e.g. via the embedding service or a sibling endpoint). Cache identical query–doc pairs; on reranker failure, serve the RRF-merged list directly (graceful fallback).
- **Rationale**: Reranking a small candidate set is the standard high-leverage precision step and keeps latency bounded (expensive model on a few candidates, not the whole corpus). ([Qdrant reranking rationale](https://qdrant.tech/documentation/tutorials-basics/reranking-hybrid-search/); rephrased for compliance.)
- **Alternatives considered**: ColBERT/late-interaction reranking — stronger but heavier to operate; noted as a future option. No rerank — rejected (near-duplicates/weak hits rank too high).

## Decision 5: Multi-Tier Retrieval Flow
- **Chosen** (ordered):
  1. **Query classification** — simple lookup vs condition/exception vs multi-step procedure vs form/code/department vs cross-procedure comparison.
  2. **Metadata filter** — department, version, procedure, access group, effective date.
  3. **Hybrid retrieval** — dense + sparse + heading/path boost.
  4. **Rerank** — cross-encoder on top 30–80.
  5. **Parent context expansion** — take the best child chunk, expand to its parent section / procedure step group via `parent_section_id`/`section_path`.
  6. **Answer composer** — step-wise answer, cite section/page/source, abstain or ask back when evidence is weak.
- **Rationale**: Matches the architect's design and directly targets the hard-question categories. Each tier is independently testable.
- **Alternatives considered**: Single-shot top-k similarity — rejected; loses metadata filtering, parent context, and abstention control.

## Decision 6: m_flow as Experimental Procedural/Graph Layer
- **Chosen**: Treat `./refs/m_flow` as an **experimental** layer (behind a flag), not part of the default answer path. Benchmark it separately on a hard-question set: conditional/exception questions, multi-step chains, role/department/system questions, "if A then which procedure?", and cause/dependency questions across procedures. m_flow's cone graph (Episode → Facet → FacetPoint → Entity) scores evidence *paths* rather than chunk similarity, which fits multi-hop/dependency queries.
- **Rationale**: Chunk similarity alone underperforms on multi-hop/dependency reasoning. m_flow may add real value there, but it is unproven for this corpus and should not destabilize the production core. Flagging + separate benchmarking de-risks adoption.
- **Alternatives considered**: Wire m_flow into the default path now — rejected (premature, risk to stability). Skip entirely — rejected (loses the multi-hop upside).

## Decision 7: Kotaemon / LlamaIndex / Haystack Scope
- **Chosen**: **Kotaemon = reference baseline / UI ideas only** (not a core dependency) since the project already owns parse + agent workflow + QA layers. **LlamaIndex/Haystack = optional orchestration helpers only**; retrieval/ranking logic stays owned in `poc_workflow/retrieval/`. Adopt a helper only if it removes code without taking control of ranking.
- **Rationale**: The goal is deep control over answer quality. Letting a framework own retrieval undermines that. (LlamaIndex offers metadata filtering; Haystack offers hybrid BM25+embedding+reranker pipelines — useful references, not mandates; rephrased for compliance.)

## Decision 8: Agentic QA Layer (LLM flow control replaces static if-then)

The current `chatbot.py` over-relies on hardcoded coordination (`infer_department`, `infer_category`, `is_out_of_scope_query` keyword lists) that misses synonyms, typos, and indirect phrasing, and pushes mixed multi-document context into the answer LLM (→ diluted/incorrect/over-long answers). We replace this with an **Agentic RAG** flow built from three LLM decision nodes + a clarification loop. Retrieval/ranking logic stays owned by `poc_workflow/retrieval/`; only flow control moves into the LLM.

### Node 1 — Router / Intent Classifier + Slot Filling (LLM, structured output)
- **Chosen**: A super-light LLM call (JSON mode / structured output) classifies each query AND performs dynamic slot filling:
  ```json
  { "intent": "generic | specific | out_of_scope | troubleshooting",
    "department": "technical | accounting | ... | unknown",
    "detected_entities": ["máy phát điện", "bơm RO"],
    "is_ambiguous": true,
    "is_complete": false,
    "extracted_parameters": { "action": "bảo dưỡng" },
    "missing_parameters": ["thiết bị", "mã lỗi"],
    "guidance_prompt": "Bạn cần tìm quy trình bảo dưỡng cho thiết bị cụ thể nào? Cho biết tên thiết bị hoặc mã lỗi nếu có." }
  ```
  Replaces `infer_department` / `infer_category` / `is_out_of_scope_query`.
- **Decisions**: `out_of_scope` → refuse early; `is_complete=false` (missing required slots) → dynamic guidance turn (no retrieval); `is_complete=true` → continue into the Qdrant pipeline with `extracted_parameters` as the metadata filter + query expansion.
- **Rationale**: semantic routing + slot extraction handles misspelling/synonyms/indirect phrasing that keyword lists cannot, and the `guidance_prompt`/`missing_parameters` are produced by the LLM — no per-device `if-then`. The bot behaves as a guided technical consultant, narrowing broad → deep.
- **Cost/latency control**: fastest/cheapest model in the chain; cache by normalized query; **deterministic fallback** to static `infer_*` rules on LLM error/invalid JSON.
- **Alternatives considered**: keep static rules (status quo) — rejected (core pain point); embeddings-only intent classifier — weaker on ambiguity/slot extraction; kept as possible offline fallback.

### Dynamic Multi-turn Guidance (broad → deep, options from index hierarchy)
- **Chosen**: When required slots are missing (`is_complete=false`), **stop before Qdrant/reranker** and return one guiding question (`guidance_prompt`) plus **dynamically generated options** (button-chips). Options are derived from the **hierarchical index itself**: a cheap scan of Qdrant payloads filtered by `department`/`extracted_parameters` aggregates the distinct sub-branches that actually exist (`section_path` roots, `procedure_name`, `procedure_id`) — e.g. máy phát điện / máy nén khí / hệ thống lọc nước. This never reads full documents and never uses a hardcoded device list, so coverage grows automatically as the corpus grows.
- **Rationale**: A query like "Quy trình bảo dưỡng?" otherwise pulls ~20 chunks from ~10 unrelated documents and the answer LLM stitches a noisy mega-answer. Guiding the user with the real options from the index is the smart-assistant norm and cheap.
- **Mechanics**: options are capped (e.g. top 5–7 branches by chunk count) with a free-text "Thiết bị khác…" escape; if the index scan yields a single dominant branch, skip the question and proceed.
- **Alternatives considered**: hardcoded option menus per topic — rejected (brittle, doesn't scale); always retrieve and let the answer LLM cope — rejected (diluted answers).

### Stateful Multi-turn Session Management
- **Chosen**: Accumulate filled slots across turns in a session context store keyed by `user_id`/session. Each turn merges newly extracted slots with prior ones; the router is re-run with the accumulated state so it asks only for what is still missing. Example: `action=bảo dưỡng` (turn 1) → `+equipment=máy phát điện` (turn 2) → `+cycle=6 tháng` (turn 3) → `is_complete` → precise retrieval with all three as filters/expansion.
- **Rationale**: progressive narrowing requires memory; without it each turn re-asks the same thing. State lets the bot converge to the single best-matching document instead of guessing.
- **Mechanics**: bounded by `RAG_MAX_CLARIFICATIONS` total guidance turns before falling through to best-effort retrieval with an explicit "đang hiểu là…" assumption; state stored in the existing SQLite/session layer (`webapp.py` already tracks user sessions); slots expire with the session.
- **Alternatives considered**: stateless single-shot clarification — rejected (cannot go 3 levels deep); full dialog-manager framework — rejected (heavier than needed; LLM + slot store suffices).

### Node 2 — Relevance Judge (LLM-as-judge, context filter)
- **Chosen**: After rerank and **before** answer generation, an LLM quickly screens the candidate chunks and drops those that don't actually contain the answer (reranker still leaks a few distractors).
- **Rationale**: shrinks prompt tokens (cost/latency ↓) and removes distraction (accuracy ↑). Runs on the small reranked set only.
- **Cost/latency control**: batch the judgement in one call (return kept chunk ids + reason); skip when ≤ N candidates or when top rerank scores are decisively high; cache by (query, chunk_id) set.
- **Alternatives considered**: trust rerank scores alone — rejected (distractors survive); threshold-only cutoff — kept as a cheap pre-filter before the judge.

### Node 3 — Answer Formatter + Citation Validator (LLM)
- **Chosen**: Validate/repair the generated answer: enforce structure (Tóm tắt / Các bước / Nguồn, tables, checklist, Mermaid `flowchart TD`), correct Vietnamese spelling/diacritics and OCR sentence breaks, and verify **every citation is grounded** in the retrieved context (drop or flag ungrounded claims). Abstain ("Không tìm thấy căn cứ trong tài liệu hiện hành.") or ask back when evidence is weak.
- **Rationale**: directly targets hallucinated citations and malformed/over-long output; the user's quality complaints (spelling, incomplete sentences, listing/render) are handled here.
- **Cost/latency control**: prefer folding format+validation into the single answer call when possible; only invoke a separate validation pass when the answer contains citations or fails a cheap structural check (e.g. `contains_raw_markup`, missing required sections). Reuse the existing `clean_answer` retry hook in `llm.answer`.
- **Alternatives considered**: regex-only post-processing (status quo `contains_raw_markup` retry) — kept as the cheap pre-check; full second LLM pass every time — rejected for latency.

### Orchestrator
- **Chosen**: `agentic/orchestrator.py` wires the nodes around the `Retriever` + `OpenAICompatibleClient`, with deterministic fallbacks at every node (static rules, raw rerank list, regex cleanup) so the chat never hard-fails if any LLM node errors. `chatbot.ask()` delegates to the orchestrator; the old static functions remain as the fallback path.
- **Config**: `RAG_AGENTIC_ENABLED` (default on), `RAG_ROUTER_MODEL` (cheap/fast), `RAG_RELEVANCE_JUDGE_ENABLED`, `RAG_ANSWER_VALIDATOR_ENABLED`, `RAG_MAX_CLARIFICATIONS=1` (max guidance turns before best-effort), `RAG_GUIDANCE_MAX_OPTIONS=7` (cap on dynamically generated option chips).

## Decision 9: LLM Model Selection (vs current DeepSeek chat)
- **Chosen**: Keep the provider-agnostic OpenAI-compatible setup; recommend a **fast, low-cost, strong-multilingual** primary (Gemini 3.x Flash / Flash-Lite class) with **DeepSeek V3/V4 chat** as a quality fallback and the existing free/local providers (freemodel, freemmlai, ollama) underneath. Fully `.env`-driven via `KB_LLM_FAILOVER_CHAIN`.
- **Rationale**: The workload is concise, grounded Vietnamese generation, not frontier reasoning. 2026 round-ups place Flash-class and DeepSeek V-series in the high-value/low-cost zone, and prices fell broadly in 2026. Config-driven selection lets "best" change without code edits. ([2026 model landscape](https://medium.com/@ankit.kotnala12/best-ai-models-in-2026-which-one-should-you-use-9cd638120966); rephrased for compliance; verify live pricing before committing.)
- **Action**: Validate with the QA eval suites (`qa_test_eval.py`, `qa_agent_eval.py`) before flipping the default.

## Decision 10: Embedding & Reranker Models
- **Chosen**: Dense = upgrade the local embedding server toward **BAAI/bge-m3** (multilingual, hybrid-friendly: dense + sparse + multi-vector), keeping `paraphrase-multilingual-MiniLM-L12-v2` as the low-RAM fallback. Sparse = BM25/SPLADE-style vectors (FastEmbed BM25 or in-house BM25 over the existing tokenizer). Reranker = a local multilingual cross-encoder.
- **Rationale**: BGE-M3 leads 2026 multilingual comparisons and can supply both dense and sparse signals, simplifying the hybrid setup. ([BGE-M3 paper](https://arxiv.org/abs/2402.03216); embedding round-ups rephrased for compliance.)
- **Open item**: Confirm bge-m3 loads on target hardware; otherwise default to MiniLM dense + BM25 sparse and document the trade-off.

## Decision 11: Image Serving Endpoint Security
- **Chosen**: `GET /api/user/documents/{doc_id}/{version}/images/{image_name}` resolves the document's MinerU artifacts dir from the manifest and streams the image, with path-traversal protection and access-group checks consistent with existing public document endpoints.
- **Rationale**: Browsers need an HTTP URL; mounting `converted_raw/` wholesale would expose unapproved files and bypass access groups.
- **Alternatives considered**: Base64-inline images (bloats payloads), static-mount raw tree (insecure) — both rejected.

## Open Items / To Verify During Implementation
- Qdrant bring-up on target hosts (Docker vs native binary vs embedded for tests) and collection bootstrap from the existing manifest.
- bge-m3 + cross-encoder memory footprint on target hardware; fallbacks documented.
- MinerU `images/` on-disk location per document for the serving route.
- Validate SC-001 (≥90% citation coverage), SC-002 (−50% rejections), SC-003 (<1.5s preview) with eval suites and a golden query set before flipping defaults.
- Measure the per-query LLM-node overhead (router + judge + validator) and tune which nodes are skippable; confirm the cheap/fast router model keeps total added latency acceptable.
- Build an ambiguous-query set to validate guidance + slot filling (right trigger rate, useful index-derived options, slots accumulate across turns, converges within `RAG_MAX_CLARIFICATIONS`, no loops).
- Confirm the cheap index-hierarchy scan for option generation is fast enough to run before retrieval (aggregate distinct `section_path` roots / `procedure_name` by `department` from Qdrant payload, capped).
- Define the hard-question benchmark set used to evaluate the experimental m_flow layer.
