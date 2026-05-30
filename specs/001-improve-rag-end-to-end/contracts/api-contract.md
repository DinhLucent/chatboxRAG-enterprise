# API & Interface Contracts: End-to-End RAG Improvements

Phase 1 output. HTTP contracts exposed by the FastAPI backend (`poc_workflow/webapp.py`) plus the internal `Retriever` interface contract. New/changed only; existing endpoints unchanged unless noted.

## 1. Document Image Serving Endpoint (NEW)

- **Path**: `GET /api/user/documents/{doc_id}/{version}/images/{image_name}`
- **Purpose**: Stream a MinerU-extracted image for the citation preview.
- **Resolution**: Resolve the document's MinerU artifacts directory from the manifest record (e.g. via `citation_map_path` / artifacts root); locate `images/{image_name}` under it.
- **Security**:
  - Reject `image_name` containing path separators, `..`, or absolute paths.
  - Verify the resolved file is inside the document's artifacts `images/` directory (no traversal).
  - Apply the same access-group / public-visibility checks used by other `/api/user/documents/...` endpoints.
- **Response**: `200 OK`, binary body, `Content-Type: image/jpeg` or `image/png` (by extension), with cache headers.
- **Errors**: `400` invalid/unsafe `image_name`; `403` access-group denied; `404` document/version/image missing.

## 2. Public Citation Info Endpoint (EXTENDED)

- **Path**: `GET /api/user/documents/{doc_id}/{version}/citation/{anchor_id}`
- **Change**: adds `citation.image_url`, `citation.display_locator`, `citation.section_path`, and `citation.source_locator`; `preview` is the existing highlighted line-range payload from `_markdown_preview_lines`.
- **Response**:
  ```json
  {
    "record": { "title": "Quy trình bảo dưỡng thiết bị", "doc_id": "KT-QT-002", "version": "4" },
    "citation": {
      "anchor_id": "KT-QT-002-v4-c5",
      "line_start": 45, "line_end": 60,
      "locator_status": "exact",
      "matched_excerpt": "...",
      "section_path": ["5. Quy trình thực hiện", "5.2 Bảo dưỡng định kỳ"],
      "page_start": 3, "page_end": 3,
      "bbox": [72.0, 140.5, 523.2, 311.8],
      "source_locator": { "type": "mineru", "content_type": "image", "mineru_block_id": "image-003", "page_start": 3 },
      "display_locator": "Trang 3, khối ảnh",
      "image_url": "/api/user/documents/KT-QT-002/4/images/07e34598...ab8.jpg"
    },
    "preview": { "line_start": 37, "line_end": 68, "highlight_line_start": 45, "highlight_line_end": 60, "content": "..." }
  }
  ```
- **Errors**: `404` if document/anchor cannot be resolved. `image_url` omitted when the chunk has no associated image.

## 3. User Chat Endpoint (BEHAVIOR CHANGE, contract stable)

- **Path**: `POST /api/user/chat` (request/response shape unchanged)
- **Change**: retrieval now runs the Qdrant hybrid + rerank + parent-expansion pipeline (or lexical fallback); softened gating means fewer requests short-circuit to "Không tìm thấy căn cứ...". When evidence is weak the answer may **abstain** or **ask a clarifying question**. Answers may include richer render blocks (tables, checklists, Mermaid) within the Tóm tắt / Các bước / Nguồn structure. Citation objects gain the fields from Contract 2.
- **No breaking change** to request/response keys; additive only.

## 4. Internal Retriever Interface (NEW — contract for `poc_workflow/retrieval/`)

Not an HTTP endpoint; the contract `chatbot.ask()` depends on so backends are swappable.

```python
class Retriever(Protocol):
    def search(
        self, query: str, *,
        department: str | None = None,
        category: str | None = None,
        filters: dict | None = None,   # metadata filter: version, procedure_id, confidential_level, effective_date, chunk_type
        limit: int = 8,
    ) -> list[RetrievalResult]: ...

    def document_chunks(self, doc_id: str, *, version: str | None = None, limit: int = 40) -> list[RetrievalResult]: ...

    def health(self) -> bool: ...   # used to choose Qdrant vs lexical fallback
```

- **Implementations**: `QdrantRetriever` (default when `health()` is True), `LexicalRetriever` (adapts `LocalRagIndex`, always available offline).
- **Contract guarantees**: results sorted by `final_score` desc; `backend` set on each result; never raises on a missing optional metadata field; on Qdrant error the caller falls back to `LexicalRetriever`.

## 5. Indexing CLI (NEW/EXTENDED)

- `python -m poc_workflow.cli reindex` — builds the hierarchical chunks, encodes dense+sparse vectors, and upserts to Qdrant (and writes the JSONL fallback). Idempotent.
- Behavior: if Qdrant is unconfigured/unreachable, it still writes the lexical JSONL index and logs that Qdrant upsert was skipped.

## 6. LLM Runtime Config (EXISTING, config-driven)

Failover order via `KB_LLM_FAILOVER_CHAIN`; provider creds via `LLM_PROVIDER_ENV`. No endpoint schema change — documented because research.md Decision 9 changes recommended defaults.

## Contract Test Expectations

- Image route: `200` + correct content-type for a known image; `400` on `..` traversal; `404` on missing image; `403` on access-group violation.
- Citation endpoint: includes `image_url` + `section_path` for an image-bearing chunk; omits `image_url` otherwise; `display_locator` reflects page vs section vs line locator.
- Retriever: `QdrantRetriever.search` returns RRF+reranked results with `backend="qdrant"`; when Qdrant is down, `ask()` returns results with `backend="lexical_fallback"` and chat still succeeds.
- Chat response stays schema-compatible with the current frontend parser (`user-chat.js`).
- Reindex: produces a populated Qdrant collection and a non-empty JSONL fallback; rerun is idempotent.
