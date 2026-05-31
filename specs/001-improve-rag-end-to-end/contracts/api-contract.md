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

- **Path**: `POST /api/user/chat` (request/response additive only)
- **Canonical response contract — two `status` modes** (data-driven, decoupled UI: the frontend reads JSON and draws; the backend owns all guidance logic):

**Mode A — `clarify`** (guidance / ask-back; **no retrieval performed**):
```json
{
  "status": "clarify",
  "message": "Tôi tìm thấy quy trình bảo dưỡng ở 2 phòng ban khác nhau. Bạn cần tìm của phòng ban nào?",
  "options": [
    { "label": "Phòng Kỹ thuật (Thiết bị, máy móc)", "next_query": "Quy trình bảo dưỡng thiết bị phòng kỹ thuật" },
    { "label": "Phòng IT (Thiết bị CNTT & Máy chủ)", "next_query": "Quy trình bảo dưỡng thiết bị phòng IT" }
  ],
  "session_state": { "accumulated_context": { "action": "bảo dưỡng" } }
}
```
Frontend: on `status="clarify"`, render `message` and auto-generate buttons from `options`; clicking a button sends its `next_query` back **with the current `session_state`** for the next turn. `options` are generated dynamically from the index hierarchy (research.md), never hardcoded. Each option may optionally carry `section_path`/`doc_id`/`procedure_id` for telemetry.

**Mode B — `success`** (enough context; RAG executed):
```json
{
  "status": "success",
  "answer": "Theo **Quy trình bảo dưỡng máy phát điện (PD-TECH-A-02)**, các bước gồm:\n1. Kiểm tra mức dầu máy...\n2. Đo điện áp ắc quy...",
  "citations": [
    {
      "doc_id": "PD-TECH-A-02",
      "title": "Quy trình vận hành bảo dưỡng máy phát điện",
      "page": 12,
      "text_snippet": "Kiểm tra mức dầu định kỳ mỗi 6 tháng...",
      "image_ref": "image_page12_1.png"
    }
  ],
  "session_state": { "accumulated_context": { "action": "bảo dưỡng", "equipment": "máy phát điện", "department": "technical" } }
}
```
Frontend: on `status="success"`, render `answer` as Markdown, draw citation cards, and allow click-to-open the split-screen preview (Contract 2 supplies `image_url`/locator detail; `image_ref` resolves via the Contract 1 image route).

- **Request (additive)**: clients echo back the last `session_state` (and/or a `session_id`) so `accumulated_context` carries across turns; a clicked option sends its `next_query` as the user turn.
- **Abstain / out-of-scope** reuses `status="success"` with the fixed answer "Không tìm thấy căn cứ trong tài liệu hiện hành." and empty `citations` (no separate mode needed).
- **Backward compatibility**: `status`, `message`, `options`, and `session_state.accumulated_context` are additive; legacy clients that read `answer`/`citations` keep working for `success`. Internal field aliases (`kind`, `slots`) map onto this canonical shape — `kind="answer"`→`status="success"`, `kind="clarification"`→`status="clarify"`, `slots`↔`accumulated_context`.

### Why this contract is stable
- **Decoupled, data-driven UI**: the frontend never hardcodes which buttons appear; it renders whatever `options` the backend returns.
- **Unlimited extensibility**: adding departments/devices only changes backend `options` data — zero frontend edits.
- **Tight conversation control**: `session_state.accumulated_context` preserves multi-turn context so the bot never loses the thread.

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
- Guidance + slot filling: an underspecified query returns `status="clarify"` with a `message` and dynamically generated `options` sourced from the index hierarchy (≥2 chips, each with `next_query`); performs **no** hybrid retrieval; clicking an option sends its `next_query` + `session_state` and merges into `accumulated_context`; once required slots are filled the next turn returns `status="success"`. The flow converges within `RAG_MAX_CLARIFICATIONS` turns (no loops).
- Session state: across turns `session_state.accumulated_context` accumulates (`action` → `+equipment` → `+cycle`) and the router only asks for still-missing slots.
- Dynamic options: when the corpus gains a new sub-branch, it appears as an option without code changes (options come from Qdrant payload aggregation, not a hardcoded list).
- Response contract: every chat response carries a `status` of exactly `clarify` or `success`; `clarify` includes `message`+`options`, `success` includes `answer`+`citations`; both echo `session_state.accumulated_context`.
- Relevance judge: injected distractor chunks are dropped from `kept_chunk_ids`; on judge error all chunks are kept (no-op).
- Answer validator: an answer citing a non-retrieved doc is flagged in `ungrounded_claims`; malformed markup is repaired (reusing `clean_answer`).
- Chat response stays schema-compatible with the current frontend parser (`user-chat.js`); unknown `kind`/`clarification` fields are ignored by the old client.
- Reindex: produces a populated Qdrant collection and a non-empty JSONL fallback; rerun is idempotent.
