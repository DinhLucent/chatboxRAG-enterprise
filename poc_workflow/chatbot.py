from __future__ import annotations

import time
from pathlib import Path

from .database import QualityDatabase
from .llm import LLMError, OpenAICompatibleClient, resolve_llm_config
from .rag_index import LocalRagIndex, SearchHit
from .ragflow_http import RAGFlowConfig, RAGFlowHTTPError, answer_with_ragflow
from .runtime import local_fallback_enabled, provider_allowed
from .text_cleaning import clean_excerpt, clean_retrieval_text, contains_raw_markup, normalized_text

NO_SOURCE_ANSWER = "Không tìm thấy căn cứ trong tài liệu hiện hành."
ANSWER_SOURCE_LLM = "llm"
ANSWER_SOURCE_FALLBACK = "fallback_clean_excerpt"
ANSWER_SOURCE_NO_ANSWER = "no_answer"
ANSWER_STYLE_LABELS = {
    "brief": "Ngắn gọn",
    "steps": "Từng bước",
    "checklist": "Checklist",
}
MIN_LOCAL_CONFIDENCE_SCORE = 3


def infer_category(query: str) -> str | None:
    lowered = query.lower()
    normalized_query = normalized_text(query)
    if any(term in normalized_query for term in ["quy trinh", "policy", "chinh sach"]):
        return "procedure"
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
    log_query: str | None = None,
    answer_style: str = "brief",
) -> dict[str, object]:
    start = time.perf_counter()
    db = QualityDatabase(root)
    stored_query = log_query or query
    ragflow_error = None
    if not provider_allowed(provider):
        latency_ms = int((time.perf_counter() - start) * 1000)
        reason = "local_fallback_disabled" if provider == "local" else "provider_not_allowed"
        log_id = db.log_query(
            stored_query,
            user_id,
            [],
            False,
            latency_ms,
            NO_SOURCE_ANSWER,
            answer_source=ANSWER_SOURCE_NO_ANSWER,
        )
        gap_id = db.create_gap(stored_query, reason, infer_category(query))
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
            "answer_source": ANSWER_SOURCE_NO_ANSWER,
            "fallback_reason": reason,
            "llm_provider": None,
            "llm_model": None,
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
                answer_source = ANSWER_SOURCE_LLM if citations else ANSWER_SOURCE_NO_ANSWER
                log_id = db.log_query(
                    stored_query,
                    user_id,
                    doc_ids,
                    bool(citations),
                    latency_ms,
                    answer,
                    llm_used=bool(citations),
                    answer_source=answer_source,
                    llm_provider="ragflow",
                    llm_model=str(ragflow_answer.get("ragflow_mode") or ""),
                )
                gap_id = None
                if not citations:
                    gap_id = db.create_gap(stored_query, "ragflow_answer_missing_citation", infer_category(query))
                return {
                    "answer": answer,
                    "citations": citations,
                    "query_log_id": log_id,
                    "knowledge_gap_id": gap_id,
                    "latency_ms": latency_ms,
                    "provider": "ragflow",
                    "ragflow_mode": ragflow_answer.get("ragflow_mode"),
                    "ragflow_error": None,
                    "llm_used": bool(citations),
                    "llm_error": None,
                    "answer_source": answer_source,
                    "fallback_reason": None if citations else "ragflow_answer_missing_citation",
                    "llm_provider": "ragflow",
                    "llm_model": str(ragflow_answer.get("ragflow_mode") or ""),
                }
            except RAGFlowHTTPError as exc:
                ragflow_error = str(exc)
                if provider == "ragflow":
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    log_id = db.log_query(
                        stored_query,
                        user_id,
                        [],
                        False,
                        latency_ms,
                        NO_SOURCE_ANSWER,
                        answer_source=ANSWER_SOURCE_NO_ANSWER,
                    )
                    gap_id = db.create_gap(stored_query, "ragflow_error", infer_category(query))
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
                        "answer_source": ANSWER_SOURCE_NO_ANSWER,
                        "fallback_reason": "ragflow_error",
                        "llm_provider": None,
                        "llm_model": None,
                    }
                if not local_fallback_enabled():
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    log_id = db.log_query(
                        stored_query,
                        user_id,
                        [],
                        False,
                        latency_ms,
                        NO_SOURCE_ANSWER,
                        answer_source=ANSWER_SOURCE_NO_ANSWER,
                    )
                    gap_id = db.create_gap(stored_query, "ragflow_error_local_fallback_disabled", infer_category(query))
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
                        "answer_source": ANSWER_SOURCE_NO_ANSWER,
                        "fallback_reason": "ragflow_error_local_fallback_disabled",
                        "llm_provider": None,
                        "llm_model": None,
                    }
        elif provider == "ragflow":
            ragflow_error = "RAGFLOW_BASE_URL, RAGFLOW_API_KEY, and RAGFLOW_CHAT_ID or RAGFLOW_SEARCH_ID are required"
            latency_ms = int((time.perf_counter() - start) * 1000)
            log_id = db.log_query(
                stored_query,
                user_id,
                [],
                False,
                latency_ms,
                NO_SOURCE_ANSWER,
                answer_source=ANSWER_SOURCE_NO_ANSWER,
            )
            gap_id = db.create_gap(stored_query, "ragflow_not_configured", infer_category(query))
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
                "answer_source": ANSWER_SOURCE_NO_ANSWER,
                "fallback_reason": "ragflow_not_configured",
                "llm_provider": None,
                "llm_model": None,
            }
        elif provider == "auto" and not local_fallback_enabled():
            ragflow_error = "RAGFlow is not configured and local fallback is disabled"
            latency_ms = int((time.perf_counter() - start) * 1000)
            log_id = db.log_query(
                stored_query,
                user_id,
                [],
                False,
                latency_ms,
                NO_SOURCE_ANSWER,
                answer_source=ANSWER_SOURCE_NO_ANSWER,
            )
            gap_id = db.create_gap(stored_query, "ragflow_not_configured_local_fallback_disabled", infer_category(query))
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
                "answer_source": ANSWER_SOURCE_NO_ANSWER,
                "fallback_reason": "ragflow_not_configured_local_fallback_disabled",
                "llm_provider": None,
                "llm_model": None,
            }

    index = LocalRagIndex(root)
    category = infer_category(query)
    hits = index.search(query, category=category, limit=3)
    if not hits and category:
        hits = index.search(query, category=None, limit=3)
    hits = confident_hits(hits)

    if not hits:
        latency_ms = int((time.perf_counter() - start) * 1000)
        log_id = db.log_query(
            stored_query,
            user_id,
            [],
            False,
            latency_ms,
            NO_SOURCE_ANSWER,
            answer_source=ANSWER_SOURCE_NO_ANSWER,
        )
        gap_id = db.create_gap(stored_query, "no_active_source", category)
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
            "answer_source": ANSWER_SOURCE_NO_ANSWER,
            "fallback_reason": "no_active_source",
            "llm_provider": None,
            "llm_model": None,
        }

    llm_error = None
    llm_used = False
    answer_source = ANSWER_SOURCE_FALLBACK
    fallback_reason = "use_llm_false"
    llm_provider = None
    llm_model = None
    if use_llm:
        config = resolve_llm_config(root)
        if config:
            llm_provider = config.provider
            llm_model = config.model
            try:
                answer = OpenAICompatibleClient(config).answer(query, hits, answer_style=answer_style)
                if contains_raw_markup(answer):
                    answer = OpenAICompatibleClient(config).answer(
                        query,
                        hits,
                        answer_style=answer_style,
                        extra_instruction="clean_answer",
                    )
                if contains_raw_markup(answer):
                    llm_error = "LLM returned raw markup after retry"
                    answer = build_answer(hits, answer_style=answer_style)
                    fallback_reason = "llm_dirty_answer"
                else:
                    llm_used = True
                    answer_source = ANSWER_SOURCE_LLM
                    fallback_reason = None
            except LLMError as exc:
                llm_error = str(exc)
                answer = build_answer(hits, answer_style=answer_style)
                fallback_reason = "llm_error"
        else:
            llm_error = "POC_LLM_MODEL and POC_LLM_API_KEY/OPENAI_API_KEY are required for --use-llm"
            answer = build_answer(hits, answer_style=answer_style)
            fallback_reason = "llm_not_configured"
    else:
        answer = build_answer(hits, answer_style=answer_style)
    latency_ms = int((time.perf_counter() - start) * 1000)
    doc_ids = sorted({hit.doc_id for hit in hits})
    log_id = db.log_query(
        stored_query,
        user_id,
        doc_ids,
        True,
        latency_ms,
        answer,
        llm_used=llm_used,
        llm_error=llm_error,
        answer_source=answer_source,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
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
        "answer_source": answer_source,
        "fallback_reason": fallback_reason,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
    }


def confident_hits(hits: list[SearchHit]) -> list[SearchHit]:
    if not hits:
        return []
    best_score = max(hit.score for hit in hits)
    if best_score < MIN_LOCAL_CONFIDENCE_SCORE:
        return []
    deduped: dict[tuple[str, str], SearchHit] = {}
    for hit in hits:
        key = (hit.doc_id, hit.version)
        current = deduped.get(key)
        if current is None or hit.score > current.score:
            deduped[key] = hit
    return sorted(deduped.values(), key=lambda hit: hit.score, reverse=True)


def build_answer(hits: list[SearchHit], answer_style: str = "brief") -> str:
    best = hits[0]
    excerpt = " ".join(clean_retrieval_text(best.text).split())
    if len(excerpt) > 700:
        excerpt = excerpt[:700].rstrip() + "..."
    sources = ", ".join(f"{hit.doc_id} v{hit.version}" for hit in hits)
    style = answer_style if answer_style in ANSWER_STYLE_LABELS else "brief"
    if style == "checklist":
        body = "\n".join(f"- [ ] {sentence}" for sentence in _answer_points(excerpt))
    elif style == "steps":
        body = "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(_answer_points(excerpt), start=1))
    else:
        body = excerpt
    return f"Tóm tắt:\n{excerpt}\n\nCác bước / Nội dung chính:\n{body}\n\nNguồn:\n{sources}"


def _answer_points(text: str) -> list[str]:
    parts = [part.strip(" .;:-") for part in re_split_sentences(text) if part.strip(" .;:-")]
    return parts[:6] or [text]


def re_split_sentences(text: str) -> list[str]:
    import re

    return re.split(r"(?<=[.!?])\s+|\n+", text)


def citation_payload(hit: SearchHit) -> dict[str, object]:
    return {
        "doc_id": hit.doc_id,
        "version": hit.version,
        "title": hit.title,
        "category": hit.category,
        "chunk_id": hit.chunk_id,
        "excerpt": clean_excerpt(hit.text),
        "source_path": hit.source_path,
        "normalized_path": hit.normalized_path,
        "score": hit.score,
    }


def apply_feedback(root: Path, log_id: int, feedback: str) -> dict[str, object]:
    db = QualityDatabase(root)
    row = db.set_feedback(log_id, feedback)
    gap_id = None
    if feedback in {"wrong", "missing_source", "missing_answer", "wrong_source", "no_answer", "unclear"}:
        gap_id = db.create_gap(
            row["query"],
            f"user_feedback_{feedback}",
            infer_category(row["query"]),
        )
    return {"query_log_id": log_id, "feedback": feedback, "knowledge_gap_id": gap_id}
