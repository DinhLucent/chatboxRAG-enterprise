# Quickstart: End-to-End RAG Improvements

How to run and verify the improved RAG system end-to-end. Commands assume repo root `d:\MyProject\demo-chatbot-engineerworkflow` and Windows PowerShell; adjust for Linux.

## 0. Environment

```powershell
Copy-Item .env.example .env   # if .env not present
```
Key variables (additions for this feature):
- `QDRANT_URL` (e.g. `http://127.0.0.1:6333`), `QDRANT_API_KEY` (blank for local), `QDRANT_COLLECTION` (default `technical_active`)
- `RAG_RETRIEVER` = `auto` (use Qdrant when reachable, else lexical fallback) | `qdrant` | `lexical`
- `RAG_DENSE_MODEL` (path/name; default multilingual MiniLM, recommended `bge-m3`), `RAG_SPARSE_ENABLED=true`
- `RAG_RERANK_ENABLED=true`, `RAG_RERANK_MODEL`, `RAG_RERANK_TOP_K=50`, `RAG_RRF_K=60`
- `RAG_MFLOW_EXPERIMENTAL=false`
- `KB_LLM_FAILOVER_CHAIN` (e.g. `gemini,deepseek,freemodel,ollama`) + provider creds (`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, …)

## 1. Start Qdrant (production retrieval core)

Docker (recommended):
```powershell
docker run -p 6333:6333 -p 6334:6334 -v ${PWD}\.qdrant_storage:/qdrant/storage qdrant/qdrant
```
Or use Qdrant embedded/in-memory mode for tests (no server needed). Verify:
```powershell
Invoke-RestMethod http://127.0.0.1:6333/healthz
```
If Qdrant is not running and `RAG_RETRIEVER=auto`, the system falls back to the lexical JSONL index (chat still works, lower ranking quality).

## 2. Start the Local Embedding Server (dense + optional rerank)

```powershell
python scripts/local_openai_embedding_server.py --port 5000 --model <path-to-model>
```
Default = multilingual MiniLM; for the recommended `bge-m3`, point `--model` at a locally cached `BAAI/bge-m3` snapshot (falls back to MiniLM if unavailable). The cross-encoder reranker runs locally as well (sibling endpoint/module).

## 3. (Optional) Reprocess / Clean Existing Data

```powershell
python scripts/clean_ocr_vietnamese.py            # OCR/Vietnamese normalization
python -m poc_workflow.pipeline run-all           # rebuild rag_ready + citation maps (image_ref, bbox, pages)
```

## 4. Build / Rebuild the Index (hierarchical chunks → Qdrant)

```powershell
python -m poc_workflow.cli reindex
```
This builds hierarchical chunks (chunk_type, section_path, parent_section_id, image_refs), encodes dense+sparse vectors, upserts to the Qdrant collection, and writes the JSONL fallback. Verify the collection:
```powershell
Invoke-RestMethod http://127.0.0.1:6333/collections/technical_active
```

## 5. Start the Chatbot Web App

```powershell
python -m poc_workflow.webapp
```
Open `http://127.0.0.1:8088/user` (port per `KB_WEB_PORT`).

## 6. Verify Each User Story

- **US1 (data + hierarchical chunking)**: confirm chunks carry `chunk_type`, `section_path`, `image_refs`, `page_start`; citation coverage ≥ 90% (SC-001).
- **US2 (Qdrant hybrid + rerank)**: query a synonym ("bảo trì máy" vs "bảo dưỡng máy") and an exact code ("KT-QT-002"); confirm dense catches the synonym and sparse keeps the exact-code hit; check `backend="qdrant"` and rerank scores in retrieval telemetry.
- **US3 (softened gating + reasoning)**: ask an equipment/error question previously rejected; confirm it reaches the LLM and returns a structured, spelling-correct answer (Tóm tắt / Các bước / Nguồn), and that weak-evidence questions abstain or ask back. Track rejection-rate drop (SC-002).
- **US4 (preview + images)**: under "Nguồn", click **Xem trước**; confirm the split panel shows highlighted markdown next to the MinerU image; preview < 1.5s (SC-003).
- **US5 (LLM failover)**: break the primary provider key; confirm fallback (stderr `[LLM Failover]`) and answers still succeed (SC-004).
- **Fallback drill**: stop Qdrant with `RAG_RETRIEVER=auto`; confirm chat still answers via `backend="lexical_fallback"`.
- **(Experimental) m_flow**: with `RAG_MFLOW_EXPERIMENTAL=true`, run the hard-question benchmark (condition/exception, multi-step, role/department, "if A then which procedure?", cross-procedure dependency) and compare against the Qdrant baseline.

## 7. Run Tests

```powershell
pytest
python -m poc_workflow.user_chat_render_smoke      # render/format smoke
python -m poc_workflow.qa_test_eval                # QA quality eval (gating/answer)
```
