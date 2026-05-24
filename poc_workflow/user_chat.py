from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .chatbot import (
    ANSWER_STYLE_LABELS,
    NO_SOURCE_ANSWER,
    ask,
    infer_query_answer_style,
    mermaid_flowchart,
    workflow_label,
)
from .database import QualityDatabase
from .manifest import ManifestStore, latest_active_records
from .text_cleaning import clean_excerpt, clean_retrieval_text, contains_raw_markup, normalized_text
from .utils import utc_now


PACKAGE_DIR = Path(__file__).resolve().parent
POLICY_DIR = PACKAGE_DIR / "policies"
MAX_PUBLIC_EXCERPT_CHARS = 720
DEFAULT_SESSION_TTL_SECONDS = 30 * 60
DEFAULT_CONTEXT_TURN_LIMIT = 6
DEFAULT_ANSWER_STYLE = "brief"
CLARIFICATION_ANSWER = (
    "Bạn cho mình thêm mã hoặc tên tài liệu/quy trình cần tra cứu nhé. "
    "Ví dụ: `KT-QT-003` hoặc `quy trình xử lý sự cố kỹ thuật`."
)

CLARIFICATION_ANSWER = (
    "Bạn cho mình thêm mã hoặc tên tài liệu/quy trình cần tra cứu nhé. "
    "Ví dụ: `PD-TECH-A-01` hoặc `quy trình lắp đặt`."
)

ANSWER_STYLES = [
    {"id": "brief", "label": "Ngắn gọn"},
    {"id": "steps", "label": "Từng bước"},
    {"id": "checklist", "label": "Checklist"},
    {"id": "workflow", "label": "Workflow"},
]

WELCOME_CARDS = [
    {
        "id": "welcome_procedure",
        "label": "Quy trình kỹ thuật",
        "template_id": "procedure_steps",
        "question": "Quy trình kỹ thuật gồm những bước nào?",
        "answer_style": "steps",
    },
    {
        "id": "welcome_form",
        "label": "Biểu mẫu kỹ thuật",
        "template_id": "form_usage",
        "question": "Trường hợp này cần dùng biểu mẫu kỹ thuật nào?",
        "answer_style": "brief",
    },
    {
        "id": "welcome_incident",
        "label": "Xử lý sự cố",
        "template_id": "incident_first_response",
        "question": "Khi phát sinh sự cố kỹ thuật, cần xử lý ban đầu thế nào?",
        "answer_style": "checklist",
    },
    {
        "id": "welcome_vendor",
        "label": "Tài liệu hãng",
        "template_id": "vendor_requirement",
        "question": "Tài liệu hãng nêu yêu cầu kỹ thuật nào?",
        "answer_style": "brief",
    },
]

FOLLOW_UP_PATTERNS = [
    r"\b(buoc|bước)\s*\d+\b",
    r"\b(no|nó|nay|này|do|đó|tren|trên|duoi|dưới)\b",
    r"\b(ai duyet|ai duyệt|o dau|ở đâu|can gi tiep|cần gì tiếp)\b",
    r"\b(tiep|tiếp|tie?p theo|sau do|sau đó)\b",
]

STANDALONE_QUERY_TERMS = (
    "quy trinh",
    "quy trình",
    "tai lieu",
    "tài liệu",
    "bieu mau",
    "biểu mẫu",
    "ticket",
    "bien tan",
    "biến tần",
    "encoder",
    "parameter",
    "alarm",
    "ma loi",
    "mã lỗi",
)


def load_policy_pack(root: Path) -> dict[str, Any]:
    return _load_json_with_workspace_override(
        root,
        workspace_path=root / "manifest" / "user_policy_pack.json",
        package_path=POLICY_DIR / "user_policy_pack.json",
    )


def load_curated_templates(root: Path) -> dict[str, Any]:
    return _load_json_with_workspace_override(
        root,
        workspace_path=root / "manifest" / "curated_templates.json",
        package_path=POLICY_DIR / "curated_templates.json",
    )


def template_exists(templates: dict[str, Any], template_id: str | None) -> bool:
    if not template_id:
        return True
    return any(
        item.get("id") == template_id
        for group in templates.get("groups", [])
        for item in group.get("templates", [])
        if isinstance(item, dict)
    )


def normalize_answer_style(answer_style: str | None) -> str:
    value = str(answer_style or DEFAULT_ANSWER_STYLE).strip()
    return value if value in ANSWER_STYLE_LABELS else DEFAULT_ANSWER_STYLE


def answer_styles_payload() -> list[dict[str, str]]:
    return ANSWER_STYLES


def welcome_cards_payload() -> list[dict[str, str]]:
    return WELCOME_CARDS


def user_chat_response(
    root: Path,
    query: str,
    *,
    template_id: str | None = None,
    answer_style: str | None = DEFAULT_ANSWER_STYLE,
    session_id: str | None = None,
    device_id: str | None = None,
    use_llm: bool = True,
    user_id: str | None = "anonymous-user-chat",
) -> dict[str, Any]:
    policy = load_policy_pack(root)
    active_answer_style = infer_answer_style(query, normalize_answer_style(answer_style))
    db = QualityDatabase(root)
    active_session_id = normalize_session_id(session_id)
    session = db.touch_user_chat_session(
        active_session_id,
        device_id=device_id,
        ttl_seconds=user_session_ttl_seconds(),
    )
    history = db.recent_user_chat_turns(active_session_id, limit=user_context_turn_limit())
    if needs_clarification(query, history):
        return clarification_response(
            db,
            policy,
            query=query,
            answer=CLARIFICATION_ANSWER,
            active_session_id=active_session_id,
            session=session,
            template_id=template_id,
            answer_style=active_answer_style,
            user_id=user_id,
        )
    effective_query = contextual_query(query, history)
    result = ask(
        root,
        effective_query,
        user_id=user_id,
        provider="auto",
        use_llm=use_llm,
        log_query=query,
        answer_style=active_answer_style,
    )
    log_id = result.get("query_log_id")
    if isinstance(log_id, int):
        db.annotate_query(
            log_id,
            session_id=active_session_id,
            template_id=template_id,
            policy_id=str(policy.get("policy_id") or ""),
            policy_version=str(policy.get("version") or ""),
        )

    citations = sanitize_public_citations(root, result.get("citations") or [])
    result["answer"] = format_user_answer(str(result.get("answer") or ""), citations, active_answer_style)
    citation_doc_ids = sorted({str(citation.get("doc_id")) for citation in citations if citation.get("doc_id")})
    db.log_user_chat_turn(
        active_session_id,
        query=query,
        effective_query=effective_query,
        answer=str(result.get("answer") or ""),
        citation_doc_ids=citation_doc_ids,
        query_log_id=log_id if isinstance(log_id, int) else None,
        template_id=template_id,
    )
    answer_check = public_answer_check(str(result.get("answer") or ""), citations)
    trace = build_public_trace(result, len(citations), policy, answer_check=answer_check)
    context_used = effective_query != query
    trace["context"] = {
        "session_id": active_session_id,
        "turns_available": len(history),
        "turns_used": len(history) if context_used else 0,
        "context_used": context_used,
        "expires_at": session["expires_at"],
    }
    if context_used:
        trace["steps"].insert(
            0,
            {
                "id": "context",
                "label": "Dùng bối cảnh hội thoại",
                "status": "done",
                "detail": f"Dùng {len(history)} lượt gần nhất để hiểu câu hỏi nối tiếp.",
            },
        )
    return {
        "answer": result.get("answer") or policy.get("no_answer") or NO_SOURCE_ANSWER,
        "citations": citations,
        "trace": trace,
        "trace_steps": trace["steps"],
        "query_log_id": log_id,
        "log_id": log_id,
        "knowledge_gap_id": result.get("knowledge_gap_id"),
        "policy": public_policy_summary(policy),
        "template_id": template_id,
        "answer_style": active_answer_style,
        "needs_clarification": False,
        "session_id": active_session_id,
        "session": {
            "session_id": active_session_id,
            "device_id": session.get("device_id"),
            "last_seen_at": session.get("last_seen_at"),
            "expires_at": session.get("expires_at"),
            "ttl_seconds": user_session_ttl_seconds(),
        },
    }


def clarification_response(
    db: QualityDatabase,
    policy: dict[str, Any],
    *,
    query: str,
    answer: str,
    active_session_id: str,
    session: dict[str, Any],
    template_id: str | None,
    answer_style: str,
    user_id: str | None,
) -> dict[str, Any]:
    log_id = db.log_query(
        query,
        user_id,
        [],
        False,
        0,
        answer,
        answer_source="clarification",
    )
    db.annotate_query(
        log_id,
        session_id=active_session_id,
        template_id=template_id,
        policy_id=str(policy.get("policy_id") or ""),
        policy_version=str(policy.get("version") or ""),
    )
    db.log_user_chat_turn(
        active_session_id,
        query=query,
        effective_query=query,
        answer=answer,
        citation_doc_ids=[],
        query_log_id=log_id,
        template_id=template_id,
    )
    trace = build_public_trace({"answer": answer, "answer_source": "clarification"}, 0, policy)
    trace["context"] = {
        "session_id": active_session_id,
        "turns_available": 0,
        "turns_used": 0,
        "context_used": False,
        "expires_at": session["expires_at"],
    }
    return {
        "answer": answer,
        "citations": [],
        "trace": trace,
        "trace_steps": trace["steps"],
        "query_log_id": log_id,
        "log_id": log_id,
        "knowledge_gap_id": None,
        "policy": public_policy_summary(policy),
        "template_id": template_id,
        "answer_style": answer_style,
        "needs_clarification": True,
        "session_id": active_session_id,
        "session": {
            "session_id": active_session_id,
            "device_id": session.get("device_id"),
            "last_seen_at": session.get("last_seen_at"),
            "expires_at": session.get("expires_at"),
            "ttl_seconds": user_session_ttl_seconds(),
        },
    }


def heartbeat_session(root: Path, session_id: str | None, device_id: str | None = None) -> dict[str, Any]:
    active_session_id = normalize_session_id(session_id)
    session = QualityDatabase(root).touch_user_chat_session(
        active_session_id,
        device_id=device_id,
        ttl_seconds=user_session_ttl_seconds(),
    )
    return {
        "session_id": active_session_id,
        "device_id": session.get("device_id"),
        "last_seen_at": session.get("last_seen_at"),
        "expires_at": session.get("expires_at"),
        "ttl_seconds": user_session_ttl_seconds(),
    }


def cleanup_stale_sessions(root: Path) -> dict[str, Any]:
    return QualityDatabase(root).cleanup_stale_user_chat_sessions()


def normalize_session_id(session_id: str | None) -> str:
    value = str(session_id or "").strip()
    if not value:
        return f"user-session-{uuid.uuid4().hex}"
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value)[:96].strip("-")
    return cleaned or f"user-session-{uuid.uuid4().hex}"


def user_session_ttl_seconds() -> int:
    return _positive_int_env("KB_USER_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS)


def user_session_cleanup_interval_seconds() -> int:
    return _positive_int_env("KB_USER_SESSION_CLEANUP_INTERVAL_SECONDS", 60)


def user_context_turn_limit() -> int:
    return min(_positive_int_env("KB_USER_CONTEXT_TURN_LIMIT", DEFAULT_CONTEXT_TURN_LIMIT), 12)


def contextual_query(query: str, history: list[dict[str, Any]]) -> str:
    clean_query = query.strip()
    if not history or not should_use_context(clean_query):
        return clean_query
    anchor_turn = next((turn for turn in reversed(history) if turn.get("citation_doc_ids")), history[-1])
    context_lines = [f"Chủ đề trước: {public_excerpt(anchor_turn.get('query') or '')}"]
    citation_doc_ids = [str(doc_id) for doc_id in anchor_turn.get("citation_doc_ids") or [] if doc_id]
    if citation_doc_ids:
        context_lines.append(f"Tài liệu đã dùng trước: {', '.join(citation_doc_ids[:5])}")
    return "\n".join(
        [
            "Cau hoi hien tai:",
            clean_query,
            "",
            "Boi canh hoi thoai gan day de lam ro dai tu/cau hoi noi tiep:",
            *context_lines,
        ]
    )


def infer_answer_style(query: str, selected_style: str) -> str:
    return infer_query_answer_style(query, selected_style)


def needs_clarification(query: str, history: list[dict[str, Any]]) -> bool:
    clean_query = query.strip()
    if history and should_use_context(clean_query):
        last_turn = history[-1]
        if last_turn.get("citation_doc_ids"):
            return False
    normalized = normalized_text(clean_query)
    if has_specific_document_hint(normalized):
        return False
    if is_technical_catalog_count_query(normalized):
        return False
    ambiguous_patterns = [
        "quy trinh nay",
        "tai lieu nay",
        "trong quy trinh nay",
        "cai nay",
        "muc nay",
    ]
    generic_questions = {
        "quy trinh nay gom nhung buoc nao",
        "quy trinh nay nhu the nao",
        "quy trinh nay lam sao",
        "tai lieu nay noi ve gi",
    }
    compact = re.sub(r"\s+", " ", normalized).strip(" ?.!:")
    return compact in generic_questions or any(pattern in normalized for pattern in ambiguous_patterns)


def has_specific_document_hint(normalized_query: str) -> bool:
    if re.search(r"\bkt\s*[- ]\s*(qt|faq|bm|hang)\s*[- ]\s*\d{1,4}\b", normalized_query):
        return True
    specific_terms = [
        "xu ly su co",
        "kiem soat tai lieu",
        "bao tri",
        "nghiem thu",
        "lap dat",
        "sua chua",
        "bao duong",
    ]
    return any(term in normalized_query for term in specific_terms)


def is_technical_catalog_count_query(normalized_query: str) -> bool:
    asks_count_or_list = any(term in normalized_query for term in ["bao nhieu", "danh sach", "cac quy trinh"])
    mentions_technical = any(term in normalized_query for term in ["phong ky thuat", "bo phan ky thuat", "ky thuat"])
    mentions_procedure_docs = "quy trinh" in normalized_query and (
        "tai lieu" in normalized_query or "phong" in normalized_query or "danh sach" in normalized_query
    )
    return asks_count_or_list and mentions_technical and mentions_procedure_docs


def should_use_context(query: str) -> bool:
    compact = query.strip().lower()
    normalized = normalized_text(compact)
    if has_context_reference(normalized):
        return True
    if any(term in normalized for term in STANDALONE_QUERY_TERMS):
        return False
    return any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in FOLLOW_UP_PATTERNS)


def has_context_reference(normalized_query: str) -> bool:
    if re.search(r"\bbuoc\s*\d+\b", normalized_query):
        return True
    return any(
        term in normalized_query
        for term in [
            "quy trinh nay",
            "tai lieu nay",
            "trong quy trinh nay",
            "noi dung nay",
            "muc nay",
            "phan nay",
            "noi dung tren",
        ]
    )


def public_policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": "Trợ lý phòng Kỹ thuật",
        "summary": [
            "Trợ lý chỉ trả lời dựa trên tài liệu đang hiệu lực của phòng Kỹ thuật.",
            "Nếu không tìm thấy căn cứ, trợ lý sẽ nói rõ là chưa tìm thấy trong tài liệu hiện hành.",
        ],
        "debug_visible": False,
    }


def sanitize_public_citations(root: Path, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_latest = {
        (record.doc_id, record.version)
        for record in latest_active_records(ManifestStore(root).load())
    }
    safe: list[dict[str, Any]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("doc_id") or "")
        version = str(citation.get("version") or "")
        if not doc_id or not version or (doc_id, version) not in active_latest:
            continue
        safe.append(
            {
                "title": public_excerpt(clean_retrieval_text(citation.get("title") or doc_id or "Nguồn"), 160),
                "doc_id": doc_id,
                "version": version,
                "excerpt": public_excerpt(clean_excerpt(citation.get("excerpt") or citation.get("text") or "")),
            }
        )
        if safe:
            if citation.get("display_code"):
                safe[-1]["display_code"] = str(citation["display_code"])
            if citation.get("source_role"):
                safe[-1]["source_role"] = str(citation["source_role"])
    return safe


def format_user_answer(answer: str, citations: list[dict[str, Any]], answer_style: str) -> str:
    text = answer.strip() or NO_SOURCE_ANSWER
    if contains_raw_markup(text):
        text = clean_retrieval_text(text)
    if text == NO_SOURCE_ANSWER or not citations:
        return NO_SOURCE_ANSWER if not citations else text
    if has_answer_headings(text):
        return normalize_answer_headings(text)
    if "Tóm tắt:" in text and "Nguồn:" in text:
        return text
    source_text = ", ".join(
        f"{citation.get('display_code') or citation.get('doc_id')} v{citation.get('version')}"
        for citation in citations
        if citation.get("doc_id") and citation.get("version")
    )
    body = text
    if answer_style == "checklist":
        body = "\n".join(f"- [ ] {item}" for item in _answer_points(text))
    elif answer_style == "steps":
        body = "\n".join(f"{index}. {item}" for index, item in enumerate(_answer_points(text), start=1))
    elif answer_style == "workflow":
        points = [workflow_label(item) for item in _answer_points(text)]
        points = [point for point in points if point]
        if len(points) >= 2:
            numbered = "\n".join(f"{index}. {item}" for index, item in enumerate(points, start=1))
            return (
                f"Tóm tắt:\n{text}\n\n"
                f"Workflow:\n```mermaid\n{mermaid_flowchart(points)}\n```\n\n"
                f"Các bước / Nội dung chính:\n{numbered}\n\n"
                f"Nguồn:\n{source_text}"
            )
    return f"Tóm tắt:\n{text}\n\nCác bước / Nội dung chính:\n{body}\n\nNguồn:\n{source_text}"


def has_answer_headings(text: str) -> bool:
    normalized = normalized_text(text)
    return "tom tat" in normalized and "nguon" in normalized


def normalize_answer_headings(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip().strip("*").strip()
        if ":" not in stripped:
            lines.append(line)
            continue
        heading, rest = stripped.split(":", 1)
        normalized_heading = normalized_text(heading)
        rest = rest.strip().strip("*").strip()
        if "tom tat" in normalized_heading:
            lines.append("Tóm tắt:" + (f" {rest}" if rest else ""))
        elif "cac buoc" in normalized_heading or "noi dung chinh" in normalized_heading:
            lines.append("Các bước / Nội dung chính:" + (f" {rest}" if rest else ""))
        elif "nguon" in normalized_heading:
            lines.append("Nguồn:" + (f" {rest}" if rest else ""))
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def _answer_points(text: str) -> list[str]:
    parts = [part.strip(" .;:-") for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip(" .;:-")]
    return parts[:6] or [text]


def public_answer_check(answer: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    if not citations:
        return {
            "checked": False,
            "passed": True,
            "detail": "Chưa có nguồn phù hợp để đối chiếu, nên hệ thống không tạo câu trả lời có căn cứ.",
        }
    issues = []
    if contains_raw_markup(answer):
        issues.append("còn dữ liệu thô")
    if not has_answer_headings(answer):
        issues.append("thiếu cấu trúc Tóm tắt/Nguồn")
    if not any(str(citation.get("doc_id") or "") in answer for citation in citations):
        issues.append("chưa hiển thị mã nguồn")
    if issues:
        return {
            "checked": True,
            "passed": False,
            "detail": "Cần kiểm tra lại: " + ", ".join(issues) + ".",
        }
    return {
        "checked": True,
        "passed": True,
        "detail": "Đã kiểm tra câu trả lời sạch, có cấu trúc và khớp nguồn trích dẫn trước khi hiển thị.",
    }


def build_public_trace(
    result: dict[str, Any],
    citation_count: int,
    policy: dict[str, Any],
    answer_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer_source = str(result.get("answer_source") or "")
    if answer_source == "llm":
        answer_detail = "Câu trả lời được tạo từ các nguồn đã chọn."
    elif answer_source == "fallback_clean_excerpt":
        answer_detail = "Câu trả lời được tạo từ trích đoạn tài liệu đã làm sạch."
    elif answer_source == "clarification":
        answer_detail = "Cần thêm mã hoặc tên tài liệu/quy trình để trả lời đúng nguồn."
    elif answer_source == "no_answer":
        answer_detail = "Không tìm thấy căn cứ trong tài liệu hiện hành."
    else:
        answer_detail = "Câu trả lời được tạo kèm nguồn khi có căn cứ."

    steps = [
        {
            "id": "understand",
            "label": "Đang hiểu câu hỏi...",
            "status": "done",
            "detail": "Đã nhận câu hỏi của bạn.",
        },
        {
            "id": "search",
            "label": "Đang tìm trong tài liệu hiện hành...",
            "status": "done" if citation_count else "empty",
            "detail": f"Tìm thấy {citation_count} nguồn tham chiếu." if answer_source != "clarification" else "Tạm dừng tìm kiếm cho đến khi có đủ ngữ cảnh.",
        },
        {
            "id": "select_sources",
            "label": "Đang chọn nguồn phù hợp...",
            "status": "done" if citation_count else "empty",
            "detail": "Nguồn được chọn từ tài liệu đang hiệu lực." if citation_count else "Chưa có nguồn phù hợp.",
        },
        {
            "id": "verify_answer",
            "label": "Đang kiểm tra câu trả lời với nguồn...",
            "status": "done"
            if (answer_check or {}).get("checked") and (answer_check or {}).get("passed")
            else ("warning" if (answer_check or {}).get("checked") else "empty"),
            "detail": str((answer_check or {}).get("detail") or "Kiểm tra nguồn sẽ chạy khi có trích dẫn phù hợp."),
        },
        {
            "id": "answer",
            "label": "Đang tạo câu trả lời..." if answer_source != "clarification" else "Đang hỏi thêm thông tin...",
            "status": "done" if result.get("answer") else "empty",
            "detail": "Câu trả lời được tạo kèm nguồn nếu có căn cứ.",
        },
    ]
    steps[-1]["detail"] = answer_detail

    return {
        "source_count": citation_count,
        "generated_at": utc_now(),
        "steps": steps,
    }


def public_excerpt(value: object, max_chars: int = MAX_PUBLIC_EXCERPT_CHARS) -> str:
    text = re.sub(r"\s+", " ", clean_retrieval_text(value)).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _load_json_with_workspace_override(root: Path, workspace_path: Path, package_path: Path) -> dict[str, Any]:
    path = workspace_path if workspace_path.exists() else package_path
    return json.loads(path.read_text(encoding="utf-8"))


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default
