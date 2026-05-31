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

- **Path**: `POST /api/user/chat` (request/response shape unchanged, additive fields only)
- **Change**: an **Agentic QA layer** now coordinates the flow. The LLM Router classifies the query and fills slots; when required slots are missing the bot guides the user with options drawn from the index hierarchy (no retrieval); retrieval runs the Qdrant hybrid + rerank + parent-expansion pipeline only once enough slots are collected; an LLM Relevance Judge filters chunks before generation; an LLM Answer Validator enforces structure and grounds citations. Multi-turn slots accumulate per session (broad → deep).
- **Request (additive)**: may include a `session_id` (or reuse the existing user/session identity) so accumulated slots carry across turns; selecting an option chip sends its `value` as the next user turn.
- **New response kind — Clarification / Guidance** (no retrieval performed):
  ```json
  {
    "kind": "clarification",
    "answer": "Tôi tìm thấy quy trình bảo dưỡng ở các nhóm sau. Bạn quan tâm nhóm nào?",
    "clarification": {
      "missing_parameter": "thiết bị",
      "options": [
        { "label": "Máy phát điện", "value": "máy phát điện", "section_path": "technical/generators" },
        { "label": "Máy nén khí", "value": "máy nén khí", "section_path": "technical/compressors" },
        { "label": "Hệ thống lọc nước RO", "value": "hệ thống lọc nước", "section_path": "technical/water-systems" },
        { "label": "Thiết bị khác…", "value": "__freetext__" }
      ]
    },
    "session_state": { "slots": { "action": "bảo dưỡng" }, "guidance_turns": 1 },
    "citations": []
  }
  ```
  Options are **generated dynamically from the index hierarchy**, not hardcoded. Normal answers keep the existing shape with `kind` defaulting to `answer` (or omitted). When evidence is weak the validator may return `abstain` or trigger another guidance turn (bounded by `RAG_MAX_CLARIFICATIONS`).
- Answers may include richer render blocks (tables, checklists, Mermaid) within the Tóm tắt / Các bước / Nguồn structure. Citation objects gain the fields from Contract 2.
- **No breaking change** to existing request/response keys; `kind`, `clarification`, and `session_state` are additive. The current frontend ignores unknown fields; rendering option chips is a frontend task.

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

## 5. Internal Agentic QA Interface (NEW — contract for `poc_workflow/agentic/`)

Internal contracts the orchestrator depends on; each node MUST degrade deterministically.

```python
def route(query: str, *, session: SessionState | None = None) -> RouterDecision: ...
    # JSON-mode LLM call; classifies intent + fills slots (extracted/missing parameters, guidance_prompt)
    # on error/invalid JSON → deterministic fallback (infer_department/infer_category/is_out_of_scope_query)

def build_guidance(decision: RouterDecision, session: SessionState, root: Path) -> GuidanceTurn: ...
    # cheap index-hierarchy scan (distinct section_path roots / procedure_name aggregated from Qdrant
    # payloads by department/filled slots), capped by RAG_GUIDANCE_MAX_OPTIONS; NO hybrid retrieval

def merge_slots(session: SessionState, decision: RouterDecision) -> SessionState: ...
    # accumulate extracted_parameters across turns; bump guidance_turns

def judge_relevance(query: str, results: list[RetrievalResult]) -> RelevanceVerdict: ...
    # one batched LLM call over the reranked set; on error/skip → keep all (no-op)

def validate_answer(query: str, answer: str, results: list[RetrievalResult]) -> AnswerValidation: ...
    # structure + citation grounding; on error → existing contains_raw_markup→clean_answer retry
```

- **Orchestration guarantees**: any node failure falls back without hard-failing the chat; nodes are individually toggle-able via config (`RAG_AGENTIC_ENABLED`, `RAG_RELEVANCE_JUDGE_ENABLED`, `RAG_ANSWER_VALIDATOR_ENABLED`); the router model is configurable (`RAG_ROUTER_MODEL`) and uses the failover chain.

## 6. Indexing CLI (NEW/EXTENDED)

- `python -m poc_workflow.cli reindex` — builds the hierarchical chunks, encodes dense+sparse vectors, and upserts to Qdrant (and writes the JSONL fallback). Idempotent.
- Behavior: if Qdrant is unconfigured/unreachable, it still writes the lexical JSONL index and logs that Qdrant upsert was skipped.

## 7. LLM Runtime Config (EXISTING, config-driven)

Failover order via `KB_LLM_FAILOVER_CHAIN`; provider creds via `LLM_PROVIDER_ENV`. No endpoint schema change — documented because research.md Decision 9 changes recommended defaults. The agentic Router uses `RAG_ROUTER_MODEL` (a cheap/fast model) over the same client/failover chain, with JSON/structured-output mode.

## Contract Test Expectations

- Image route: `200` + correct content-type for a known image; `400` on `..` traversal; `404` on missing image; `403` on access-group violation.
- Citation endpoint: includes `image_url` + `section_path` for an image-bearing chunk; omits `image_url` otherwise; `display_locator` reflects page vs section vs line locator.
- Retriever: `QdrantRetriever.search` returns RRF+reranked results with `backend="qdrant"`; when Qdrant is down, `ask()` returns results with `backend="lexical_fallback"` and chat still succeeds.
- Router: a misspelled/synonym/indirect engineering query is classified `specific` (not blocked); a clearly off-domain query is `out_of_scope`; an underspecified query ("Quy trình bảo dưỡng?") returns `is_complete=false` with `missing_parameters` and a `guidance_prompt`. Invalid-JSON LLM output falls back to the static `infer_*` rules.
- Guidance + slot filling: an underspecified query returns `kind="clarification"` with dynamically generated `options` sourced from the index hierarchy (≥2 chips + free-text escape) and performs **no** hybrid retrieval; selecting/typing a value merges into `session_state.slots`; once required slots are filled the next turn runs retrieval. The flow converges within `RAG_MAX_CLARIFICATIONS` turns (no loops).
- Session state: across turns slots accumulate (`action` → `+equipment` → `+cycle`) and the router only asks for still-missing slots.
- Dynamic options: when the corpus gains a new sub-branch, it appears as an option without code changes (options come from Qdrant payload aggregation, not a hardcoded list).
- Relevance judge: injected distractor chunks are dropped from `kept_chunk_ids`; on judge error all chunks are kept (no-op).
- Answer validator: an answer citing a non-retrieved doc is flagged in `ungrounded_claims`; malformed markup is repaired (reusing `clean_answer`).
- Chat response stays schema-compatible with the current frontend parser (`user-chat.js`); unknown `kind`/`clarification` fields are ignored by the old client.
- Reindex: produces a populated Qdrant collection and a non-empty JSONL fallback; rerun is idempotent.
