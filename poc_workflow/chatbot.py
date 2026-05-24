from __future__ import annotations

import time
from pathlib import Path

from .database import QualityDatabase
from .llm import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig
from .rag_index import LocalRagIndex, SearchHit
from .ragflow_http import RAGFlowConfig, RAGFlowHTTPError, answer_with_ragflow
from .runtime import local_fallback_enabled, provider_allowed

NO_SOURCE_ANSWER = "Khong tim thay can cu trong tai lieu hien hanh."


def infer_category(query: str) -> str | None:
    lowered = query.lower()
    if any(term in lowered for term in ["bieu mau", "biểu mẫu", "checklist", "mau bao cao", "mẫu báo cáo"]):
        return "form_checklist"
    if any(term in lowered for term in ["manual", "datasheet", "catalogue", "hang", "hãng"]):
        return "vendor_document"
    if any(term in lowered for term in ["faq", "loi", "lỗi", "troubleshoot", "su co", "sự cố"]):
        return "faq_troubleshooting"
    if any(term in lowered for term in ["quy trinh", "quy trình", "policy", "chinh sach", "chính sách"]):
        return "procedure"
    return None


def ask(
    root: Path,
    query: str,
    user_id: str | None = None,
    use_llm: bool = False,
    provider: str = "auto",
) -> dict[str, object]:
    start = time.perf_counter()
    db = QualityDatabase(root)
    ragflow_error = None
    if not provider_allowed(provider):
        latency_ms = int((time.perf_counter() - start) * 1000)
        reason = "local_fallback_disabled" if provider == "local" else "provider_not_allowed"
        log_id = db.log_query(query, user_id, [], False, latency_ms, NO_SOURCE_ANSWER)
        gap_id = db.create_gap(query, reason, infer_category(query))
        return {
            "answer": NO_SOURCE_ANSWER,
            "citations": [],
            "query_log_id": log_id,
            "knowledge_gap_id": gap_id,
            "latency_ms": latency_ms,
            "provider": provider,
            "ragflow_error": reason,
            "llm_used": False,
            "llm_error": None,
        }

    if provider in {"auto", "ragflow"}:
        config = RAGFlowConfig.from_env()
        if config and (config.chat_id or config.search_id):
            try:
                ragflow_answer = answer_with_ragflow(query, config)
                answer = str(ragflow_answer.get("answer") or "").strip()
                citations = ragflow_answer.get("citations") or []
                if not answer:
                    answer = NO_SOURCE_ANSWER
                latency_ms = int((time.perf_counter() - start) * 1000)
                doc_ids = sorted(
                    {
                        str(citation.get("doc_id"))
                        for citation in citations
                        if citation.get("doc_id")
                    }
                )
                log_id = db.log_query(query, user_id, doc_ids, bool(citations), latency_ms, answer)
                gap_id = None
                if not citations:
                    gap_id = db.create_gap(query, "ragflow_answer_missing_citation", infer_category(query))
                return {
                    "answer": answer,
                    "citations": citations,
                    "query_log_id": log_id,
                    "knowledge_gap_id": gap_id,
                    "latency_ms": latency_ms,
                    "provider": "ragflow",
                    "ragflow_mode": ragflow_answer.get("ragflow_mode"),
                    "ragflow_error": None,
                    "llm_used": False,
                    "llm_error": None,
                }
            except RAGFlowHTTPError as exc:
                ragflow_error = str(exc)
                if provider == "ragflow":
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    log_id = db.log_query(query, user_id, [], False, latency_ms, NO_SOURCE_ANSWER)
                    gap_id = db.create_gap(query, "ragflow_error", infer_category(query))
                    return {
                        "answer": NO_SOURCE_ANSWER,
                        "citations": [],
                        "query_log_id": log_id,
                        "knowledge_gap_id": gap_id,
                        "latency_ms": latency_ms,
                        "provider": "ragflow",
                        "ragflow_error": ragflow_error,
                        "llm_used": False,
                        "llm_error": None,
                    }
                if not local_fallback_enabled():
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    log_id = db.log_query(query, user_id, [], False, latency_ms, NO_SOURCE_ANSWER)
                    gap_id = db.create_gap(query, "ragflow_error_local_fallback_disabled", infer_category(query))
                    return {
                        "answer": NO_SOURCE_ANSWER,
                        "citations": [],
                        "query_log_id": log_id,
                        "knowledge_gap_id": gap_id,
                        "latency_ms": latency_ms,
                        "provider": "auto",
                        "ragflow_error": ragflow_error,
                        "llm_used": False,
                        "llm_error": None,
                    }
        elif provider == "ragflow":
            ragflow_error = "RAGFLOW_BASE_URL, RAGFLOW_API_KEY, and RAGFLOW_CHAT_ID or RAGFLOW_SEARCH_ID are required"
            latency_ms = int((time.perf_counter() - start) * 1000)
            log_id = db.log_query(query, user_id, [], False, latency_ms, NO_SOURCE_ANSWER)
            gap_id = db.create_gap(query, "ragflow_not_configured", infer_category(query))
            return {
                "answer": NO_SOURCE_ANSWER,
                "citations": [],
                "query_log_id": log_id,
                "knowledge_gap_id": gap_id,
                "latency_ms": latency_ms,
                "provider": "ragflow",
                "ragflow_error": ragflow_error,
                "llm_used": False,
                "llm_error": None,
            }
        elif provider == "auto" and not local_fallback_enabled():
            ragflow_error = "RAGFlow is not configured and local fallback is disabled"
            latency_ms = int((time.perf_counter() - start) * 1000)
            log_id = db.log_query(query, user_id, [], False, latency_ms, NO_SOURCE_ANSWER)
            gap_id = db.create_gap(query, "ragflow_not_configured_local_fallback_disabled", infer_category(query))
            return {
                "answer": NO_SOURCE_ANSWER,
                "citations": [],
                "query_log_id": log_id,
                "knowledge_gap_id": gap_id,
                "latency_ms": latency_ms,
                "provider": "auto",
                "ragflow_error": ragflow_error,
                "llm_used": False,
                "llm_error": None,
            }

    index = LocalRagIndex(root)
    category = infer_category(query)
    hits = index.search(query, category=category, limit=3)
    if not hits and category:
        hits = index.search(query, category=None, limit=3)

    if not hits:
        latency_ms = int((time.perf_counter() - start) * 1000)
        log_id = db.log_query(query, user_id, [], False, latency_ms, NO_SOURCE_ANSWER)
        gap_id = db.create_gap(query, "no_active_source", category)
        return {
            "answer": NO_SOURCE_ANSWER,
            "citations": [],
            "query_log_id": log_id,
            "knowledge_gap_id": gap_id,
            "latency_ms": latency_ms,
            "provider": "local",
            "ragflow_error": ragflow_error,
            "llm_used": False,
            "llm_error": None,
        }

    llm_error = None
    llm_used = False
    if use_llm:
        config = OpenAICompatibleConfig.from_env()
        if config:
            try:
                answer = OpenAICompatibleClient(config).answer(query, hits)
                llm_used = True
            except LLMError as exc:
                llm_error = str(exc)
                answer = build_answer(hits)
        else:
            llm_error = "POC_LLM_MODEL and POC_LLM_API_KEY/OPENAI_API_KEY are required for --use-llm"
            answer = build_answer(hits)
    else:
        answer = build_answer(hits)
    latency_ms = int((time.perf_counter() - start) * 1000)
    doc_ids = sorted({hit.doc_id for hit in hits})
    log_id = db.log_query(query, user_id, doc_ids, True, latency_ms, answer)
    return {
        "answer": answer,
        "citations": [citation_payload(hit) for hit in hits],
        "query_log_id": log_id,
        "knowledge_gap_id": None,
        "latency_ms": latency_ms,
        "provider": "local",
        "ragflow_error": ragflow_error,
        "llm_used": llm_used,
        "llm_error": llm_error,
    }


def build_answer(hits: list[SearchHit]) -> str:
    best = hits[0]
    excerpt = " ".join(best.text.split())
    if len(excerpt) > 700:
        excerpt = excerpt[:700].rstrip() + "..."
    sources = ", ".join(f"{hit.doc_id} v{hit.version}" for hit in hits)
    return f"{excerpt}\n\nNguon: {sources}"


def citation_payload(hit: SearchHit) -> dict[str, object]:
    return {
        "doc_id": hit.doc_id,
        "version": hit.version,
        "title": hit.title,
        "category": hit.category,
        "chunk_id": hit.chunk_id,
        "source_path": hit.source_path,
        "normalized_path": hit.normalized_path,
        "score": hit.score,
    }


def apply_feedback(root: Path, log_id: int, feedback: str) -> dict[str, object]:
    db = QualityDatabase(root)
    row = db.set_feedback(log_id, feedback)
    gap_id = None
    if feedback in {"wrong", "missing_source", "wrong_source", "no_answer"}:
        gap_id = db.create_gap(
            row["query"],
            f"user_feedback_{feedback}",
            infer_category(row["query"]),
        )
    return {"query_log_id": log_id, "feedback": feedback, "knowledge_gap_id": gap_id}
