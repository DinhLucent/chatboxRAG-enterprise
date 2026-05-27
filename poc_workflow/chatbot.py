from __future__ import annotations

import re
import time
from pathlib import Path

from .database import QualityDatabase
from .llm import LLMError, OpenAICompatibleClient, resolve_llm_config
from .manifest import ManifestStore, latest_active_records
from .models import ManifestRecord
from .rag_index import LocalRagIndex, SearchHit
from .ragflow_http import RAGFlowConfig, RAGFlowHTTPError, answer_with_ragflow
from .runtime import local_fallback_enabled, provider_allowed
from .text_cleaning import clean_excerpt, clean_retrieval_text, contains_raw_markup, normalized_text
from .utils import tokenize

NO_SOURCE_ANSWER = "Không tìm thấy căn cứ trong tài liệu hiện hành."
ANSWER_SOURCE_LLM = "llm"
ANSWER_SOURCE_FALLBACK = "fallback_clean_excerpt"
ANSWER_SOURCE_NO_ANSWER = "no_answer"
ENGINEERING_SCOPE_ID = "engineering_procedures_v1"
ANSWER_STYLE_LABELS = {
    "brief": "Ngắn gọn",
    "steps": "Từng bước",
    "checklist": "Checklist",
    "workflow": "Workflow",
}
MIN_LOCAL_CONFIDENCE_SCORE = 8


def infer_query_answer_style(query: str, selected_style: str = "brief") -> str:
    style = selected_style if selected_style in ANSWER_STYLE_LABELS else "brief"
    if style != "brief":
        return style
    normalized = normalized_text(query)
    if any(
        term in normalized
        for term in [
            "workflow",
            "flow",
            "luong xu ly",
            "so do",
            "ve workflow",
            "ve so do",
        ]
    ):
        return "workflow"
    if any(
        term in normalized
        for term in [
            "gom nhung buoc",
            "cac buoc",
            "tung buoc",
            "nhu the nao",
            "lam sao",
        ]
    ):
        return "steps"
    return style


def infer_category(query: str) -> str | None:
    lowered = query.lower()
    normalized_query = normalized_text(query)
    procedure_context_terms = [
        "quy trinh",
        "quy dinh",
        "huong dan",
        "lap dat",
        "bao duong",
        "sua chua",
        "phu kien",
        "hieu chuan",
        "ccdc",
        "chung chi",
        "dao tao",
    ]
    if any(term in normalized_query for term in procedure_context_terms):
        return "procedure"
    if any(term in normalized_query for term in ["bien tan", "encoder", "parameter", "ma loi", "error code", "alarm"]):
        return "vendor_document"
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


def is_out_of_scope_query(query: str) -> bool:
    normalized = normalized_text(query)
    out_of_scope_terms = [
        "nghi phep",
        "nghi phep nam",
        "luong thuong",
        "cong tac",
        "ma so thue",
        "so dien thoai hotline",
        "hotline hien tai",
        "mua laptop",
        "truong phong ky thuat hien tai",
        "dang giu chuc truong phong",
    ]
    if any(term in normalized for term in out_of_scope_terms):
        return True
    if "hop dong" in normalized and any(term in normalized for term in ["gia tri", "bao nhieu tien", "khach hang a"]):
        return True
    if re.search(r"\b[a-z]-?\d{2,}\b", normalized) and any(term in normalized for term in ["model", "ma loi", "sua loi"]):
        return True
    return False


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
    answer_style = infer_query_answer_style(query, answer_style)
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
    if is_out_of_scope_query(query):
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
        gap_id = db.create_gap(stored_query, "out_of_active_engineering_scope", category)
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
            "fallback_reason": "out_of_active_engineering_scope",
            "llm_provider": None,
            "llm_model": None,
        }
    catalog = build_catalog_answer(root, query, answer_style=answer_style)
    if catalog:
        answer, hits = catalog
        latency_ms = int((time.perf_counter() - start) * 1000)
        doc_ids = sorted({hit.doc_id for hit in hits})
        log_id = db.log_query(
            stored_query,
            user_id,
            doc_ids,
            True,
            latency_ms,
            answer,
            answer_source=ANSWER_SOURCE_FALLBACK,
        )
        return {
            "answer": answer,
            "citations": [citation_payload(hit) for hit in hits],
            "query_log_id": log_id,
            "knowledge_gap_id": None,
            "latency_ms": latency_ms,
            "provider": "local",
            "ragflow_error": ragflow_error,
            "llm_used": False,
            "llm_error": None,
            "answer_source": ANSWER_SOURCE_FALLBACK,
            "fallback_reason": "catalog_answer",
            "llm_provider": None,
            "llm_model": None,
        }
    hits = index.search(query, category=category, limit=20)
    if not hits and category == "procedure":
        hits = index.search(query, category=None, limit=20)
    hits = confident_hits(hits)
    hits = focus_hits_for_query(hits, query)

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
                    answer = build_answer(hits, answer_style=answer_style, query=query)
                    fallback_reason = "llm_dirty_answer"
                else:
                    llm_used = True
                    answer_source = ANSWER_SOURCE_LLM
                    fallback_reason = None
            except LLMError as exc:
                llm_error = str(exc)
                answer = build_answer(hits, answer_style=answer_style, query=query)
                fallback_reason = "llm_error"
        else:
            llm_error = "POC_LLM_MODEL and POC_LLM_API_KEY/OPENAI_API_KEY are required for --use-llm"
            answer = build_answer(hits, answer_style=answer_style, query=query)
            fallback_reason = "llm_not_configured"
    else:
        answer = build_answer(hits, answer_style=answer_style, query=query)
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
        if current is None:
            deduped[key] = hit
            continue
        if hit.score > current.score:
            hit.text = combined_hit_text(hit.text, current.text)
            deduped[key] = hit
        else:
            current.text = combined_hit_text(current.text, hit.text)
    return sorted(deduped.values(), key=lambda hit: hit.score, reverse=True)


def focus_hits_for_query(hits: list[SearchHit], query: str) -> list[SearchHit]:
    if len(hits) <= 1 or asks_across_documents(query):
        return hits
    best = hits[0]
    if not best.display_code:
        return hits
    same_document_code = [hit for hit in hits if hit.display_code == best.display_code]
    return same_document_code or hits


def asks_across_documents(query: str) -> bool:
    normalized = normalized_text(query)
    return any(
        term in normalized
        for term in [
            "cac quy trinh",
            "nhung quy trinh",
            "quy trinh nao",
            "tai lieu nao",
            "bo tai lieu",
            "trong bo",
            "hien tai",
            "dung trong nhung",
            "lien quan quy trinh nao",
        ]
    )


def combined_hit_text(primary: str, secondary: str, max_chars: int = 3600) -> str:
    if not secondary or secondary in primary:
        return primary
    combined = f"{primary}\n{secondary}".strip()
    return combined[:max_chars].rstrip()


def build_catalog_answer(root: Path, query: str, answer_style: str = "brief") -> tuple[str, list[SearchHit]] | None:
    if not is_technical_procedure_catalog_query(query):
        return None
    scoped_records = active_scope_records(root)
    if scoped_records:
        return build_active_scope_catalog_answer(scoped_records, answer_style)
    record = active_catalog_record(root)
    if not record:
        active_records = active_technical_procedure_records(root)
        if active_records:
            return build_active_scope_catalog_answer(active_records, answer_style)
        return None
    path = Path(record.normalized_path)
    if not path.exists():
        return None
    rows = extract_department_procedure_rows(path.read_text(encoding="utf-8", errors="ignore"), "ky thuat")
    if not rows:
        return None
    body_lines = [f"{title} ({status})" if status else title for title, status in rows]
    if answer_style == "checklist":
        body = "\n".join(f"- [ ] {line}" for line in body_lines)
    else:
        body = "\n".join(f"{index}. {line}" for index, line in enumerate(body_lines, start=1))
    summary = f"Phòng Kỹ thuật có {len(rows)} tài liệu quy trình trong danh mục hiện hành."
    answer = (
        f"Tóm tắt:\n{summary}\n\n"
        f"Các bước / Nội dung chính:\n{body}\n\n"
        f"Nguồn:\n{record.doc_id} v{record.version}"
    )
    excerpt = "Danh sách SOP - Kỹ thuật: " + "; ".join(body_lines)
    hit = SearchHit(
        doc_id=record.doc_id,
        version=record.version,
        title=record.title,
        category=record.category,
        chunk_id=f"{record.doc_id}_catalog_technical",
        text=excerpt,
        score=100,
        source_path=record.source_path,
        normalized_path=record.normalized_path,
        display_code=record.extra.get("display_code"),
        source_role=record.extra.get("source_role"),
    )
    return answer, [hit]


def active_scope_records(root: Path, scope_id: str = ENGINEERING_SCOPE_ID) -> list[ManifestRecord]:
    records = [
        record
        for record in latest_active_records(ManifestStore(root).load())
        if record.extra.get("active_scope_id") == scope_id and record.category == "procedure"
    ]
    role_order = {"primary_pdf": 0, "supporting_workbook": 1}
    return sorted(
        records,
        key=lambda record: (
            str(record.extra.get("display_code") or record.title),
            role_order.get(str(record.extra.get("source_role") or ""), 9),
            record.doc_id,
        ),
    )


def active_technical_procedure_records(root: Path) -> list[ManifestRecord]:
    records = [
        record
        for record in latest_active_records(ManifestStore(root).load())
        if record.department == "technical" and record.category == "procedure"
    ]
    return sorted(
        records,
        key=lambda record: (
            str(record.extra.get("display_code") or record.title),
            record.doc_id,
            record.version,
        ),
    )


def build_active_scope_catalog_answer(
    records: list[ManifestRecord],
    answer_style: str = "brief",
) -> tuple[str, list[SearchHit]]:
    groups: dict[str, list[ManifestRecord]] = {}
    for record in records:
        key = str(record.extra.get("display_code") or record.title or record.doc_id)
        groups.setdefault(key, []).append(record)

    lines = []
    for index, (display_code, items) in enumerate(sorted(groups.items()), start=1):
        primary = next((item for item in items if item.extra.get("source_role") == "primary_pdf"), items[0])
        role_names = ", ".join(sorted({source_role_label(str(item.extra.get("source_role") or "")) for item in items}))
        lines.append(f"{index}. {display_code}: {primary.title} - {len(items)} file ({role_names})")

    summary = (
        f"Phòng Kỹ thuật hiện có {len(records)} file active thuộc "
        f"{len(groups)} nhóm quy trình chính trong phạm vi Quy trình Kỹ Thuật."
    )
    if answer_style == "checklist":
        body = "\n".join(line.replace(f"{index}. ", "- [ ] ", 1) for index, line in enumerate(lines, start=1))
    else:
        body = "\n".join(lines)
    answer = (
        f"Tóm tắt:\n{summary}\n\n"
        f"Các bước / Nội dung chính:\n{body}\n\n"
        f"Nguồn:\n{', '.join(source_label_for_record(record) for record in records)}"
    )
    hits = [
        SearchHit(
            doc_id=record.doc_id,
            version=record.version,
            title=record.title,
            category=record.category,
            chunk_id=f"{record.doc_id}_scope_catalog",
            text=(
                f"{record.extra.get('display_code') or record.doc_id} "
                f"{record.title} {source_role_label(str(record.extra.get('source_role') or ''))}"
            ),
            score=100,
            source_path=record.source_path,
            normalized_path=record.normalized_path,
            display_code=record.extra.get("display_code"),
            source_role=record.extra.get("source_role"),
        )
        for record in records
    ]
    return answer, hits


def source_role_label(source_role: str) -> str:
    if source_role == "primary_pdf":
        return "PDF"
    if source_role == "supporting_workbook":
        return "XLSX"
    return source_role or "file"


def source_label_for_record(record: ManifestRecord) -> str:
    display_code = record.extra.get("display_code")
    label = f"{display_code} / {record.doc_id}" if display_code else record.doc_id
    version = record.extra.get("display_version") or record.extra.get("source_revision") or f"v{record.version}"
    return f"{label} {version}"


def source_label_for_hit(hit: SearchHit) -> str:
    label = f"{hit.display_code} / {hit.doc_id}" if hit.display_code else hit.doc_id
    version = hit.display_version or hit.source_revision or f"v{hit.version}"
    return f"{label} {version}"


def is_technical_procedure_catalog_query(query: str) -> bool:
    normalized = normalized_text(query)
    asks_catalog = any(
        term in normalized
        for term in [
            "bao nhieu",
            "so luong",
            "cac quy trinh",
            "danh sach quy trinh",
            "quy trinh cua phong",
            "co nhung quy trinh",
        ]
    )
    asks_procedure_docs = "quy trinh" in normalized and (
        "tai lieu" in normalized or "danh sach" in normalized or "phong" in normalized or "bo phan" in normalized or "bao nhieu" in normalized or "so luong" in normalized
    )
    return asks_catalog and asks_procedure_docs


def active_catalog_record(root: Path) -> ManifestRecord | None:
    active_records = latest_active_records(ManifestStore(root).load())
    for record in active_records:
        if record.doc_id == "KT-QT-215":
            return record
    for record in active_records:
        title = normalized_text(record.title)
        if "kiem soat tai lieu" in title and record.category == "procedure":
            return record
    return None


def extract_department_procedure_rows(markdown: str, department: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    in_department = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        first_cell = normalized_text(cells[0])
        department_cell = normalized_text(cells[1])
        if first_cell in {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"} and department_cell:
            if in_department and department not in department_cell:
                break
            in_department = department in department_cell
            continue
        if not in_department:
            continue
        doc_type = normalized_text(cells[1])
        title = cells[3].strip()
        status = cells[4].strip()
        if doc_type == "quy trinh" and title:
            rows.append((title, status))
    return rows


def build_answer(hits: list[SearchHit], answer_style: str = "brief", query: str = "") -> str:
    best = hits[0]
    cleaned_text = answer_ready_text(best.text)
    table_points = procedure_table_points(cleaned_text)
    ranked_points = relevant_answer_points(hits, query)
    use_table_points = bool(table_points and is_broad_procedure_steps_query(query))
    points = table_points if use_table_points else (ranked_points or table_points or _answer_points(cleaned_text))
    sources = ", ".join(source_label_for_hit(hit) for hit in hits)
    style = answer_style if answer_style in ANSWER_STYLE_LABELS else "brief"
    summary_points = points[:1] if style in {"workflow", "steps", "checklist"} else points[:2]
    excerpt = " ".join(summary_points).strip() or " ".join(cleaned_text.split())
    if use_table_points:
        excerpt = f"{source_label_for_hit(best)}: phần nội dung công việc của {best.title}."
    if len(excerpt) > 320:
        excerpt = excerpt[:320].rstrip() + "..."
    body_points = answer_body_points(points)
    if style == "workflow":
        return build_workflow_answer(body_points, excerpt, sources)
    if style == "checklist":
        body = "\n".join(f"- [ ] {sentence}" for sentence in body_points[:6])
    elif style == "steps":
        body = "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(body_points[:6], start=1))
    else:
        body = "\n".join(f"- {sentence}" for sentence in body_points[:6])
    return f"Tóm tắt:\n{excerpt}\n\nCác bước / Nội dung chính:\n{body}\n\nNguồn:\n{sources}"


ANSWER_STOPWORDS = {
    "ai",
    "ban",
    "bo",
    "buoc",
    "cac",
    "can",
    "cho",
    "co",
    "cua",
    "duoc",
    "gi",
    "gom",
    "hoi",
    "khi",
    "la",
    "lam",
    "nao",
    "neu",
    "nhu",
    "nhung",
    "phai",
    "quy",
    "sau",
    "the",
    "thi",
    "trinh",
    "trong",
    "truoc",
}


def relevant_answer_points(hits: list[SearchHit], query: str, limit: int = 8) -> list[str]:
    if not query.strip():
        return []
    normalized_query = normalized_text(query)
    query_terms = {
        term
        for term in tokenize(normalized_query)
        if len(term) > 1 and term not in ANSWER_STOPWORDS
    }
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    order = 0
    for hit in hits:
        for candidate in answer_candidate_units(answer_ready_text(hit.text)):
            normalized = normalized_text(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            score = answer_candidate_score(candidate, query_terms, normalized_query)
            if score <= 0:
                continue
            scored.append((score, order, candidate))
            order += 1
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, _, candidate in scored[:limit]]


def answer_candidate_units(text: str) -> list[str]:
    units: list[str] = []
    for raw_line in clean_retrieval_text(text).splitlines():
        line = re.sub(r"^#{1,6}\s*", "", raw_line.strip()).strip(" .;:-")
        if not line:
            continue
        if not is_answer_candidate_noise(line):
            units.append(line)
        if len(line) < 120:
            continue
        parts = [
            part.strip(" .;:-")
            for part in re.split(r"\s+-\s+|<br\s*/?>", line)
            if part.strip(" .;:-")
        ]
        for part in parts:
            if not is_answer_candidate_noise(part):
                units.append(part)
    return units


def answer_candidate_score(candidate: str, query_terms: set[str], normalized_query: str) -> int:
    normalized = normalized_text(candidate)
    candidate_terms = set(tokenize(normalized))
    score = len(candidate_terms & query_terms) * 5
    intent_rules = [
        (["muc dich"], ["muc dich", "dam bao", "rui ro", "phoi hop"], 35),
        (["pham vi", "ap dung", "khi nao"], ["pham vi ap dung", "ap dung khi", "phat sinh"], 35),
        (["trach nhiem", "chiu trach nhiem"], ["trach nhiem", "phong ky thuat", "chiu trach nhiem"], 45),
        (["kinh doanh", "buoc dau"], ["kinh doanh", "yeu cau lap dat", "pd-cs"], 40),
        (["khao sat", "dieu kien"], ["ban dat may", "nhiet do", "do am", "he thong dien", "nuoc"], 40),
        (["cap nhat thong tin", "phan mem"], ["sn may", "serial", "phu kien", "thoi gian di chuyen", "loi"], 40),
        (["bbdvkt"], ["bbdvkt", "bien ban dich vu ky thuat", "ky gop"], 40),
        (["bieu mau", "dinh kem", "ho so"], ["bm-", "ho so", "tai lieu dinh kem", "danh sach"], 40),
        (["du tru phu kien", "ycmh"], ["du tru phu kien", "ycmh", "mua hang", "xnk"], 35),
        (["ccdc", "hieu chuan"], ["ccdc", "hieu chuan", "chung chi", "serial"], 35),
        (["chung chi", "dao tao", "ccdt"], ["chung chi", "dao tao", "bm-075", "tps"], 35),
    ]
    for query_markers, candidate_markers, weight in intent_rules:
        if any(marker in normalized_query for marker in query_markers) and any(marker in normalized for marker in candidate_markers):
            score += weight
    header_terms = ["stt", "raci", "responsible", "accountable", "consulted", "informed", "bieu mau/van ban"]
    if sum(1 for term in header_terms if term in normalized) >= 3:
        score -= 35
    return score


def is_answer_candidate_noise(candidate: str) -> bool:
    normalized = normalized_text(candidate)
    if len(normalized) < 4 or normalized.isdigit():
        return True
    if re_fullmatch_noise(normalized):
        return True
    exact_noise = {
        "stt",
        "so do quy trinh",
        "raci",
        "ket qua",
        "tan suat",
        "noi dung chi tiet",
        "bieu mau",
        "buoc thuc hien/noi dung chinh",
        "bo phan/nguoi",
        "thoi gian",
    }
    return normalized in exact_noise


def is_broad_procedure_steps_query(query: str) -> bool:
    normalized = normalized_text(query)
    return any(
        term in normalized
        for term in [
            "cac buoc",
            "gom cac buoc",
            "gom nhung buoc",
            "buoc nao",
            "tung buoc",
            "nhu the nao",
            "lam sao",
            "workflow",
            "so do",
        ]
    )


def answer_body_points(points: list[str]) -> list[str]:
    if len(points) > 1 and normalized_text(points[0]).startswith("tai lieu nay huong dan"):
        return points[1:]
    return points


def procedure_table_points(text: str) -> list[str]:
    normalized = normalized_text(text)
    if not any(term in normalized for term in ["noi dung cong viec", "noi dung chi tiet", "so do quy trinh"]):
        return []
    cells = [cell.strip() for cell in re.split(r"\s*\|\s*", clean_retrieval_text(text)) if cell.strip()]
    labels: list[str] = []
    noise_terms = {
        "stt",
        "so do quy trinh",
        "raci",
        "ket qua",
        "tan suat",
        "noi dung chi tiet",
        "bieu mau",
        "responsible",
        "accountable",
        "consulted",
        "informed",
    }
    for index, cell in enumerate(cells):
        if add_procedure_label(labels, cell, noise_terms):
            continue
        normalized_cell = normalized_text(cell)
        if re.search(r"(^|\n|\s)\d{1,2}\s*$", normalized_cell):
            for candidate in cells[index + 1 : index + 5]:
                if add_procedure_label(labels, candidate, noise_terms, raw_label=True):
                    break
        if len(labels) >= 6:
            break
    return labels


def add_procedure_label(labels: list[str], value: str, noise_terms: set[str], raw_label: bool = False) -> bool:
    candidates = [value] if raw_label else []
    candidates.extend(match.group(1) for match in re.finditer(r"(?:^|\n)\s*\d{1,2}\s+([^\n|]{4,90})", value))
    end_match = re.search(r"^\(?\d{1,2}\)?\s*\n?\s*([^|]{4,90}?)(?:\d{1,2})$", value.strip())
    if end_match:
        candidates.append(end_match.group(1))
    for candidate in candidates:
        label = workflow_label(candidate)
        label = re.sub(r"^[↓\d\s.:-]+", "", label).strip()
        label = re.sub(r"\d{1,2}$", "", label).strip()
        normalized_label = normalized_text(label)
        if len(normalized_label) < 4:
            continue
        if normalized_label in noise_terms:
            continue
        if any(term in normalized_label for term in ["pd-tech", "responsible", "accountable", "consulted", "informed"]):
            continue
        if re.fullmatch(r"[irac,\s]+", normalized_label):
            continue
        if label not in labels:
            labels.append(label)
        return True
    return False


def build_workflow_answer(points: list[str], excerpt: str, sources: str) -> str:
    workflow_points = [workflow_label(point) for point in points[:6]]
    workflow_points = [point for point in workflow_points if point]
    if len(workflow_points) < 2:
        body = "\n".join(f"- {sentence}" for sentence in points[:4])
        return f"Tóm tắt:\n{excerpt}\n\nCác bước / Nội dung chính:\n{body}\n\nNguồn:\n{sources}"
    mermaid = mermaid_flowchart(workflow_points)
    body = "\n".join(f"{index}. {point}" for index, point in enumerate(workflow_points, start=1))
    return (
        f"Tóm tắt:\n{excerpt}\n\n"
        f"Workflow:\n```mermaid\n{mermaid}\n```\n\n"
        f"Các bước / Nội dung chính:\n{body}\n\n"
        f"Nguồn:\n{sources}"
    )


def workflow_label(value: str, max_chars: int = 88) -> str:
    import re

    label = re.sub(r"^\s*(?:bước|buoc)?\s*\d+[.)\s:-]*", "", value, flags=re.IGNORECASE).strip()
    label = re.sub(r"\s+", " ", label)
    if len(label) <= max_chars:
        return label
    truncated = label[:max_chars].rsplit(" ", 1)[0].strip()
    return f"{truncated}..." if truncated else label[:max_chars].strip()


def mermaid_flowchart(points: list[str]) -> str:
    nodes = [f'    S{index}["{mermaid_label(point)}"]' for index, point in enumerate(points, start=1)]
    links = [f"    S{index} --> S{index + 1}" for index in range(1, len(points))]
    return "\n".join(["flowchart TD", *nodes, *links])


def mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace("[", "(").replace("]", ")")


def answer_ready_text(value: object) -> str:
    noise = {
        "stt",
        "so do quy trinh",
        "raci",
        "ket qua",
        "tan suat",
        "noi dung chi tiet",
        "noi dung cong viec",
        "muc dich",
        "cac buoc thuc hien",
        "pham vi ap dung",
        "tai lieu vien dan tham khao",
        "nguon",
        "bieu mau",
        "trach nhiem thuc hien - responsible (r)",
        "trach nhiem phe duyet - accountable (a)",
        "tham van - consulted (c)",
        "duoc thong bao - informed (i)",
        "lich su chinh sua",
        "so chinh sua",
        "ngay thang",
        "nguoi lap",
        "app",
        "ky thuat",
        "dvkh",
        "cskh",
        "ps/bdm",
    }
    lines: list[str] = []
    for raw_line in clean_retrieval_text(value).splitlines():
        line = re.sub(r"^#{1,6}\s*", "", raw_line.strip()).strip()
        normalized = normalized_text(line).strip()
        if not line:
            continue
        if normalized in noise:
            continue
        if re_fullmatch_noise(normalized):
            continue
        lines.append(line)
    for index, line in enumerate(lines):
        normalized = normalized_text(line)
        if normalized.startswith("tai lieu nay huong dan") or normalized.startswith("thong tin duoc tiep nhan"):
            return "\n".join(lines[index:]).strip()
    return "\n".join(lines).strip()


def re_fullmatch_noise(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"[-\d]+|[raci,\s]+|rev\s*\d+|\d{4}-\d{2}-\d{2}\s+00:00:00", value))


def _answer_points(text: str) -> list[str]:
    skipped = {
        "khi co phat sinh",
        "muc dich",
        "cac buoc thuc hien",
        "noi dung cong viec",
        "nguon",
    }
    parts = []
    for part in re_split_sentences(text):
        cleaned = re.sub(r"^#{1,6}\s*", "", part.strip(" .;:-")).strip()
        if not cleaned:
            continue
        normalized = normalized_text(cleaned)
        if normalized in skipped or normalized.isdigit():
            continue
        parts.append(cleaned)
    return parts[:6] or [text]


def re_split_sentences(text: str) -> list[str]:
    import re

    return re.split(r"(?<!\d)(?<=[.!?])\s+|\n+", text)


def citation_payload(hit: SearchHit) -> dict[str, object]:
    excerpt = clean_excerpt(answer_ready_text(hit.text))
    payload = {
        "doc_id": hit.doc_id,
        "version": hit.version,
        "title": hit.title,
        "category": hit.category,
        "excerpt": excerpt,
        "matched_excerpt": excerpt,
    }
    if getattr(hit, "chunk_id", None):
        payload["chunk_id"] = hit.chunk_id
    if getattr(hit, "anchor_id", None):
        payload["anchor_id"] = hit.anchor_id
    if getattr(hit, "line_start", None) is not None:
        payload["line_start"] = hit.line_start
    if getattr(hit, "line_end", None) is not None:
        payload["line_end"] = hit.line_end
    if hit.display_code:
        payload["display_code"] = hit.display_code
    if getattr(hit, "display_version", None):
        payload["display_version"] = hit.display_version
    if getattr(hit, "source_revision", None):
        payload["source_revision"] = hit.source_revision
    if hit.source_role:
        payload["source_role"] = hit.source_role
    return payload


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
