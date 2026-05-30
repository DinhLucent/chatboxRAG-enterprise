# Data Model: End-to-End RAG Improvements

Phase 1 output. Entities, fields, validation, and data flow for the architect-selected pipeline.

## Flow Overview

```
MinerU artifacts (content_list_v2.json, middle.json, images/)
   → data_workflow (extract blocks, bbox, page, image_ref, tables)
   → retrieval/chunker (hierarchical chunking + chunk_type classification)   →  Chunk
   → retrieval/embeddings (dense + sparse encode)                            →  vectors
   → retrieval/qdrant_store.upsert                                           →  Qdrant point
   → query: classify → metadata filter → hybrid query → RRF → rerank
                                       → parent-context expand               →  RetrievalResult[]
   → context_composer → chatbot.citation_payload                            →  Citation payload
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

## 7. Public Citation Endpoint (`webapp._public_document_citation_payload`) — extended

Adds `citation.image_url`, `citation.display_locator`, `citation.section_path`, `citation.source_locator` on top of the existing `record` / `citation` / `preview` structure from `_markdown_preview_lines`. See contracts/api-contract.md.

## 8. LLM Failover Chain (config entity)

Ordered list from `KB_LLM_FAILOVER_CHAIN` (csv) filtered against `LLM_PRESETS`; per-provider creds via `LLM_PROVIDER_ENV`. Recommended default leads with the chosen fast multilingual provider, then DeepSeek, then free/local fallbacks (research.md Decision 9).

## 9. Config additions (`config.py` / `.env`)

`QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` (default `technical_active`), `RAG_RETRIEVER` (`qdrant|lexical|auto`), `RAG_DENSE_MODEL`, `RAG_SPARSE_ENABLED`, `RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `RAG_RERANK_TOP_K` (default 50), `RAG_RRF_K` (default 60), `RAG_MFLOW_EXPERIMENTAL` (default off).

## State Transitions

- **Chunk**: `mineru blocks → classified+structured Chunk → dense+sparse encoded → upserted (Qdrant) [+ JSONL fallback]`. Reprocess/clean pass is idempotent and may re-run before encoding.
- **Retrieval**: `query → classify → metadata filter → dense+sparse → RRF → rerank(top-K) → parent expand → RetrievalResult[]` (or `lexical_fallback` when Qdrant down).
- **Citation**: `RetrievalResult → SearchHit adapter → citation_payload → API → UI preview (text + image)`.
