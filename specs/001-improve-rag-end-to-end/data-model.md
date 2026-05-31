# Data Model: End-to-End RAG Improvements

Phase 1 output. Entities, fields, validation, and data flow for the architect-selected pipeline.

## Flow Overview

```
MinerU artifacts (content_list_v2.json, middle.json, images/)
   → data_workflow (extract blocks, bbox, page, image_ref, tables)
   → retrieval/chunker (hierarchical chunking + chunk_type classification)   →  Chunk
   → retrieval/embeddings (dense + sparse encode)                            →  vectors
   → retrieval/qdrant_store.upsert                                           →  Qdrant point

   query (+ session slots) → agentic/router + slot-fill (LLM)
                                 ─► out_of_scope: refuse
                                 ├► missing slots: GuidanceTurn (options from index hierarchy; stop; merge slot; loop)
                                 └► is_complete:
                                      metadata filter (slots) → hybrid query → RRF → rerank
                                        → parent-context expand → agentic/relevance_judge (LLM)  →  kept RetrievalResult[]
   → LLM answer (cited) → agentic/answer_validator (LLM) → context_composer → chatbot.citation_payload
   → webapp citation endpoint + image route → static/user/user-chat.js       →  split preview + image
```

## 1. Chunk (hierarchical schema) — NEW (`retrieval/schema.py`)

The core ingestion/retrieval unit. Produced by `retrieval/chunker.py` from MinerU output + manifest record.

| Field | Type | Notes |
|-------|------|-------|
| `chunk_id` | `str` | Stable id `{doc_id}_v{version}_c{n}` (matches existing convention) |
| `doc_id` | `str` | Document identifier |
| `procedure_id` | `str \| None` | Procedure/business code (e.g. `KT-QT-002`) |
| `procedure_name` | `str \| None` | Human procedure title |
| `version` | `str` | Document version |
| `effective_date` | `str \| None` | ISO date; used for time-based filtering |
| `department` | `str` | From manifest; one of `config.ALLOWED_DEPARTMENTS` |
| `owner` | `str \| None` | Document owner |
| `confidential_level` | `str \| None` | Access/visibility level (maps to access_group) |
| `source_file` | `str` | Normalized markdown / source path |
| `page_start` | `int \| None` | 1-based page (from `mineru_page_index`) |
| `page_end` | `int \| None` | 1-based page |
| `section_path` | `list[str]` | Heading breadcrumb, e.g. `["5. Quy trình", "5.2 Bảo dưỡng"]` |
| `heading_level` | `int \| None` | Depth of the owning heading |
| `chunk_type` | `enum` | `policy \| step \| condition \| exception \| table \| form \| image_caption \| prose` |
| `step_number` | `int \| None` | For `step` chunks |
| `role` | `str \| None` | Responsible role/position if expressed |
| `system_name` | `str \| None` | Referenced system/tool |
| `form_code` | `str \| None` | Referenced form code (e.g. `BM-125`) |
| `content` | `str` | Cleaned chunk text (via `text_cleaning.clean_retrieval_text`) |
| `parent_section_id` | `str \| None` | Id of the parent section chunk (parent-context expansion) |
| `image_refs` | `list[str]` | Resolved MinerU image filenames (via `resolve_mineru_image_ref`) |
| `table_refs` | `list[str]` | Table block ids/refs |
| `bbox` | `list[float] \| None` | `[x0,y0,x1,y1]` for source highlight |

**Validation**: `chunk_type` ∈ enum; `department` ∈ allowed set; `bbox` length 4 when present; `page_*` ≥ 1 when present; `content` non-empty after cleaning (else dropped, as today via `is_low_value_retrieval_text`). All structural fields optional and tolerant of missing MinerU metadata.

**chunk_type classification** (heuristic, in `chunker.py`): heading/keywords → `policy`; numbered/"Bước N" → `step` (+`step_number`); "nếu/khi/trường hợp" → `condition`; "ngoại lệ/không áp dụng" → `exception`; markdown/HTML table → `table`; "BM-…/biểu mẫu" → `form` (+`form_code`); image block → `image_caption`; else `prose`.

## 2. Qdrant Point — NEW (`retrieval/qdrant_store.py`)

One point per Chunk in collection `technical_active`.

```jsonc
{
  "id": "<uuid or chunk_id hash>",
  "vector": {
    "dense":  [/* float[dense_dim] */],
    "sparse": { "indices": [/* int */], "values": [/* float */] }
  },
  "payload": { /* full Chunk schema fields above, used for metadata filtering */ }
}
```

- **Collection config**: named vectors `dense` (size = embedding dim, cosine) and `sparse` (sparse vector). Payload indexes on `department`, `procedure_id`, `version`, `confidential_level`, `effective_date`, `chunk_type` for fast filtering.
- **Lifecycle**: created/upserted by `qdrant_store.rebuild()` during indexing (mirrors `LocalRagIndex.rebuild`); idempotent upsert keyed by `chunk_id`.
- **Validation**: dense dim and sparse encoder must match collection config; on mismatch, reindex required (logged).

## 3. RetrievalResult — NEW (`retrieval/retriever.py`)

Returned by the retriever to the chatbot; superset of the existing `SearchHit` for compatibility.

| Field | Type | Notes |
|-------|------|-------|
| `chunk` | `Chunk` | The matched chunk (full schema) |
| `dense_score` | `float \| None` | Pre-fusion semantic score |
| `sparse_score` | `float \| None` | Pre-fusion BM25/sparse score |
| `fused_score` | `float` | Post-RRF score |
| `rerank_score` | `float \| None` | Cross-encoder score (None if reranker unavailable) |
| `final_score` | `float` | Score used for ordering (rerank if present else fused) |
| `expanded_context` | `str \| None` | Parent-section/step-group text from context expansion |
| `backend` | `enum` | `qdrant \| lexical_fallback` |

**Compatibility**: an adapter maps `RetrievalResult` → existing `SearchHit` (with new `image_refs`/`page`/`bbox`) so `chatbot.citation_payload`, `build_answer`, and `llm.answer` keep working.

## 4. Retriever protocol — NEW (`retrieval/retriever.py`)

```
class Retriever(Protocol):
    def search(query, *, department=None, category=None, filters=None, limit=...) -> list[RetrievalResult]
    def document_chunks(doc_id, *, version=None, ...) -> list[RetrievalResult]
```

Implementations: `QdrantRetriever` (default when configured/reachable) and `LexicalRetriever` (adapts existing `LocalRagIndex` as the offline fallback). Selection in `chatbot.ask()` via config + health check.

## 5. SearchHit (`rag_index.py`) — extended for compatibility

Add optional `image_refs: list[str] | None`, `page_start/page_end: int | None`, `bbox: list[float] | None`, plus debug scores (`dense_score`, `sparse_score`, `rerank_score`) so the citation layer and observability work regardless of backend. Existing fields unchanged; ranking still keyed on `score`.

## 6. Citation Payload (`chatbot.citation_payload`) — extended

Forwarded to the frontend when present: `image_ref`/`image_refs`, `image_url` (`/api/user/documents/{doc_id}/{version}/images/{name}`), `page_start`/`page_end`, `bbox`, `section_path`, `display_locator` ("Trang 3, khối ảnh" / "Mục 5.2" / "Dòng 45–60"), `source_locator` `{type, content_type, mineru_block_id?, page_start?}`. Existing fields unchanged.

**Wire aliases (Contract 3, Mode B)**: the citation card in the chat `success` response uses the compact form `{ doc_id, title, page, text_snippet, image_ref }`, where `page` = `page_start`, `text_snippet` = `matched_excerpt`/`excerpt`. The richer detail endpoint (Contract 2) supplies `page_start`/`page_end`, `bbox`, `section_path`, and `image_url` for the split-screen preview. Both views are produced from the same `SearchHit`.

## 7. Public Citation Endpoint (`webapp._public_document_citation_payload`) — extended

Adds `citation.image_url`, `citation.display_locator`, `citation.section_path`, `citation.source_locator` on top of the existing `record` / `citation` / `preview` structure from `_markdown_preview_lines`. See contracts/api-contract.md.

## 8. LLM Failover Chain (config entity)

Ordered list from `KB_LLM_FAILOVER_CHAIN` (csv) filtered against `LLM_PRESETS`; per-provider creds via `LLM_PROVIDER_ENV`. Recommended default leads with the chosen fast multilingual provider, then DeepSeek, then free/local fallbacks (research.md Decision 9).

## 9. Agentic QA entities — NEW (`agentic/`)

### RouterDecision (Node 1 output, structured JSON)

| Field | Type | Notes |
|-------|------|-------|
| `intent` | `enum` | `generic \| specific \| out_of_scope \| troubleshooting` |
| `department` | `str` | one of `config.ALLOWED_DEPARTMENTS` or `unknown` |
| `detected_entities` | `list[str]` | e.g. `["máy phát điện", "bơm RO"]` → query expansion / metadata filter |
| `is_ambiguous` | `bool` | high-level ambiguity flag |
| `is_complete` | `bool` | false when required slots are missing → triggers guidance |
| `extracted_parameters` | `dict[str,str]` | filled slots this turn, e.g. `{"action":"bảo dưỡng"}` |
| `missing_parameters` | `list[str]` | required-but-missing slots, e.g. `["thiết bị","mã lỗi"]` |
| `guidance_prompt` | `str \| None` | LLM-authored ask-back question (Vietnamese) |
| `confidence` | `float \| None` | optional; low confidence can also trigger guidance |

**Validation**: `intent`/`department` constrained to enums; on invalid JSON or LLM error → fall back to deterministic `infer_department`/`infer_category`/`is_out_of_scope_query` (which imply `is_complete=true`, no guidance).

### GuidanceTurn (Dynamic Multi-turn Guidance output → wire `status="clarify"`)

| Field | Type | Notes |
|-------|------|-------|
| `message` | `str` | the guiding question (from `guidance_prompt`); serialized as `message` |
| `options` | `list[{label, next_query, section_path?, doc_id?, procedure_id?}]` | button-chips **generated dynamically from the index hierarchy** (distinct `section_path` roots / `procedure_name` aggregated from Qdrant payloads by `department`/filled slots); capped by `RAG_GUIDANCE_MAX_OPTIONS`; may include a free-text "Thiết bị khác…" chip. `next_query` is the full follow-up query the client resends |
| `missing_parameter` | `str` | which slot this turn is collecting (telemetry) |
| `session_state` | `SessionState` | carried forward to the next turn (serialized as `{accumulated_context, ...}`) |

Serialized to the wire as `{ "status": "clarify", "message", "options", "session_state": { "accumulated_context": {...} } }` (Contract 3, Mode A). No retrieval performed. If the index scan yields a single dominant branch, skip the question and proceed. Bounded by `RAG_MAX_CLARIFICATIONS`.

### SessionState (Stateful multi-turn memory)

| Field | Type | Notes |
|-------|------|-------|
| `session_id` | `str` | keyed by `user_id`/session (reuses `webapp.py` session tracking) |
| `accumulated_context` | `dict[str,str]` | accumulated parameters across turns, e.g. `{"action":"bảo dưỡng","equipment":"máy phát điện","department":"technical"}`. **This is the wire field** echoed to/from the client (internally also referred to as `slots`) |
| `intent` | `str` | sticky intent from the first classified turn |
| `guidance_turns` | `int` | count of guidance turns so far (bounded by `RAG_MAX_CLARIFICATIONS`) |
| `updated_at` | `str` | ISO timestamp; state expires with the session |

**Lifecycle**: each turn merges new `extracted_parameters` into `accumulated_context`, re-runs the router with the accumulated state, and either asks for the next missing slot (`status="clarify"`) or (when `is_complete`) runs precise retrieval using `accumulated_context` as the metadata filter + query expansion and returns `status="success"`.

### RelevanceVerdict (Node 2 output)

| Field | Type | Notes |
|-------|------|-------|
| `kept_chunk_ids` | `list[str]` | chunks that actually contain answer evidence |
| `dropped_chunk_ids` | `list[str]` | distractors removed before answer generation |
| `reason` | `str \| None` | brief justification (telemetry) |

**Fallback**: on error/skip, keep all reranked chunks (no-op filter).

### AnswerValidation (Node 3 output)

| Field | Type | Notes |
|-------|------|-------|
| `answer` | `str` | formatted/repaired answer (Tóm tắt / Các bước / Nguồn) |
| `citations_grounded` | `bool` | every citation traced to a retrieved chunk |
| `ungrounded_claims` | `list[str]` | flagged/removed claims (telemetry) |
| `action` | `enum` | `ok \| abstain \| clarify` |

**Fallback**: on error, use the existing `contains_raw_markup`→`clean_answer` retry and return the answer as-is.

## 10. Config additions (`config.py` / `.env`)

Retrieval: `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` (default `technical_active`), `RAG_RETRIEVER` (`qdrant|lexical|auto`), `RAG_DENSE_MODEL`, `RAG_SPARSE_ENABLED`, `RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `RAG_RERANK_TOP_K` (default 50), `RAG_RRF_K` (default 60), `RAG_MFLOW_EXPERIMENTAL` (default off).

Agentic QA: `RAG_AGENTIC_ENABLED` (default on), `RAG_ROUTER_MODEL` (cheap/fast model id), `RAG_RELEVANCE_JUDGE_ENABLED` (default on), `RAG_ANSWER_VALIDATOR_ENABLED` (default on), `RAG_MAX_CLARIFICATIONS` (default 1; max guidance turns), `RAG_GUIDANCE_MAX_OPTIONS` (default 7).

## State Transitions

- **Chunk**: `mineru blocks → classified+structured Chunk → dense+sparse encoded → upserted (Qdrant) [+ JSONL fallback]`. Reprocess/clean pass is idempotent and may re-run before encoding.
- **Agentic flow**: `query (+ SessionState slots) → Router+SlotFill(LLM) → {out_of_scope: refuse | missing slots: GuidanceTurn with index-derived options (stop, merge slot, loop) | is_complete: continue}`.
- **Retrieval (specific only)**: `metadata filter → dense+sparse → RRF → rerank(top-K) → parent expand → RelevanceJudge(LLM) → kept chunks` (or `lexical_fallback` when Qdrant down).
- **Answer**: `kept chunks → LLM answer → AnswerValidation(LLM) → {ok | abstain | clarify}`.
- **Citation**: `RetrievalResult → SearchHit adapter → citation_payload → API → UI preview (text + image)`.
