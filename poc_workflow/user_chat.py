from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .chatbot import ANSWER_STYLE_LABELS, NO_SOURCE_ANSWER, ask
from .database import QualityDatabase
from .text_cleaning import clean_excerpt, clean_retrieval_text, contains_raw_markup, normalized_text
from .utils import utc_now


PACKAGE_DIR = Path(__file__).resolve().parent
POLICY_DIR = PACKAGE_DIR / "policies"
MAX_PUBLIC_EXCERPT_CHARS = 720
DEFAULT_SESSION_TTL_SECONDS = 30 * 60
DEFAULT_CONTEXT_TURN_LIMIT = 6
DEFAULT_ANSWER_STYLE = "brief"


def sanitize_debug_string(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    # Remove Windows file paths
    text = re.sub(r'[A-Za-z]:\\[^ \n\r\t\"\'\<\>]+', '[PATH]', text)
    # Remove Unix file paths
    text = re.sub(r'/[^ \n\r\t\"\'\<\>]+/[^ \n\r\t\"\'\<\>]+', '[PATH]', text)
    # Remove token/api key looking patterns
    text = re.sub(r'sk-[a-zA-Z0-9]{20,}', '[KEY]', text)
    text = re.sub(r'Bearer\s+[a-zA-Z0-9\.\-_]{10,}', 'Bearer [TOKEN]', text, flags=re.IGNORECASE)
    return text

ANSWER_STYLES = [
    {"id": "brief", "label": "Ngắn gọn"},
    {"id": "steps", "label": "Từng bước"},
    {"id": "checklist", "label": "Checklist"},
]

WELCOME_CARDS = [
    {
        "id": "welcome_procedure",
        "label": "Tra cứu quy trình",
        "template_id": "procedure_steps",
        "question": "Quy trình này gồm những bước nào?",
        "answer_style": "steps",
    },
    {
        "id": "welcome_form",
        "label": "Tìm biểu mẫu",
        "template_id": "form_usage",
        "question": "Trường hợp này cần dùng biểu mẫu nào?",
        "answer_style": "brief",
    },
    {
        "id": "welcome_incident",
        "label": "Hỏi lỗi kỹ thuật",
        "template_id": "incident_first_response",
        "question": "Khi phát sinh lỗi kỹ thuật, cần xử lý ban đầu thế nào?",
        "answer_style": "checklist",
    },
    {
        "id": "welcome_vendor",
        "label": "Tìm tài liệu hãng",
        "template_id": "vendor_requirement",
        "question": "Tài liệu hãng nêu yêu cầu kỹ thuật nào?",
        "answer_style": "brief",
    },
]

FOLLOW_UP_PATTERNS = [
    r"\b(buoc|bước)\s*\d+\b",
    r"\b(no|nó|nay|này|do|đó|tren|trên|duoi|dưới)\b",
    r"\b(ai|khi nao|khi nào|o dau|ở đâu|can gi|cần gì|nhu the nao|như thế nào)\b",
    r"\b(tiep|tiếp|tie?p theo|sau do|sau đó)\b",
]


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
    active_answer_style = normalize_answer_style(answer_style)
    db = QualityDatabase(root)
    active_session_id = normalize_session_id(session_id)
    session = db.touch_user_chat_session(
        active_session_id,
        device_id=device_id,
        ttl_seconds=user_session_ttl_seconds(),
    )
    history = db.recent_user_chat_turns(active_session_id, limit=user_context_turn_limit())
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

    citations = sanitize_public_citations(result.get("citations") or [])
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
    trace = build_public_trace(result, len(citations), policy)
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
        "answer_source": sanitize_debug_string(result.get("answer_source") or "no_answer"),
        "llm_used": bool(result.get("llm_used")),
        "llm_error": sanitize_debug_string(result.get("llm_error")),
        "fallback_reason": sanitize_debug_string(result.get("fallback_reason")),
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
    context_lines = []
    for turn in history[-user_context_turn_limit() :]:
        context_lines.append(f"User: {public_excerpt(turn.get('query') or '')}")
        context_lines.append(f"Assistant: {public_excerpt(turn.get('answer') or '')}")
    return "\n".join(
        [
            "Cau hoi hien tai:",
            clean_query,
            "",
            "Boi canh hoi thoai gan day de lam ro dai tu/cau hoi noi tiep:",
            *context_lines,
        ]
    )


def should_use_context(query: str) -> bool:
    compact = query.strip().lower()
    if len(compact.split()) <= 7:
        return True
    return any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in FOLLOW_UP_PATTERNS)


def public_policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": "Trả lời có nguồn",
        "summary": [
            "Trợ lý chỉ trả lời dựa trên tài liệu đang hiệu lực.",
            "Nếu không tìm thấy căn cứ, trợ lý sẽ nói rõ là chưa tìm thấy trong tài liệu hiện hành.",
        ],
        "debug_visible": False,
    }


def sanitize_public_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        safe.append(
            {
                "title": citation.get("title") or citation.get("doc_id") or "Nguồn",
                "doc_id": citation.get("doc_id"),
                "version": citation.get("version"),
                "excerpt": public_excerpt(clean_excerpt(citation.get("excerpt") or citation.get("text") or "")),
            }
        )
    return safe


def format_user_answer(answer: str, citations: list[dict[str, Any]], answer_style: str) -> str:
    text = answer.strip() or NO_SOURCE_ANSWER
    if contains_raw_markup(text):
        text = clean_retrieval_text(text)
    
    normalized_ans = normalized_text(text)
    if "khong tim thay can cu" in normalized_ans or text == NO_SOURCE_ANSWER or not citations:
        return NO_SOURCE_ANSWER
        
    if has_answer_headings(text):
        return normalize_answer_headings(text)
    if "### Tóm tắt:" in text and "### Nguồn:" in text:
        return text
    source_text = ", ".join(
        f"{citation.get('doc_id')} v{citation.get('version')}"
        for citation in citations
        if citation.get("doc_id") and citation.get("version")
    )
    body = text
    if answer_style == "checklist":
        body = "\n".join(f"- [ ] {item}" for item in _answer_points(text))
    elif answer_style == "steps":
        body = "\n".join(f"{index}. {item}" for index, item in enumerate(_answer_points(text), start=1))
    return f"### Tóm tắt:\n{text}\n\n### Các bước / Nội dung chính:\n{body}\n\n### Nguồn:\n{source_text}"


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
            lines.append("### Tóm tắt:" + (f" {rest}" if rest else ""))
        elif "cac buoc" in normalized_heading or "noi dung chinh" in normalized_heading:
            lines.append("### Các bước / Nội dung chính:" + (f" {rest}" if rest else ""))
        elif "nguon" in normalized_heading:
            lines.append("### Nguồn:" + (f" {rest}" if rest else ""))
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def _answer_points(text: str) -> list[str]:
    parts = [part.strip(" .;:-") for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip(" .;:-")]
    return parts[:6] or [text]


def build_public_trace(result: dict[str, Any], citation_count: int, policy: dict[str, Any]) -> dict[str, Any]:
    no_answer_reason = None
    if citation_count == 0:
        no_answer_reason = "no_public_citations"
    if result.get("knowledge_gap_id") and not no_answer_reason:
        no_answer_reason = "knowledge_gap_created"
    answer_source = str(result.get("answer_source") or "")
    if answer_source == "llm":
        answer_detail = "Da tao cau tra loi bang LLM."
    elif answer_source == "fallback_clean_excerpt":
        answer_detail = "Tam tra loi bang trich doan da lam sach vi LLM chua san sang."
    elif answer_source == "no_answer":
        answer_detail = "Khong tim thay can cu trong tai lieu hien hanh."
    else:
        answer_detail = "Cau tra loi duoc tao kem nguon neu co can cu."

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
            "detail": f"Tìm thấy {citation_count} nguồn tham chiếu.",
        },
        {
            "id": "select_sources",
            "label": "Đang chọn nguồn phù hợp...",
            "status": "done" if citation_count else "empty",
            "detail": "Nguồn được chọn từ tài liệu đang hiệu lực." if citation_count else "Chưa có nguồn phù hợp.",
        },
        {
            "id": "answer",
            "label": "Đang tạo câu trả lời...",
            "status": "done" if result.get("answer") else "empty",
            "detail": "Câu trả lời được tạo kèm nguồn nếu có căn cứ.",
        },
    ]
    steps[-1]["detail"] = answer_detail

    return {
        "source_count": citation_count,
        "no_answer_reason": no_answer_reason,
        "generated_at": utc_now(),
        "steps": steps,
    }


def public_excerpt(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= MAX_PUBLIC_EXCERPT_CHARS:
        return text
    return text[:MAX_PUBLIC_EXCERPT_CHARS].rstrip() + "..."


def _load_json_with_workspace_override(root: Path, workspace_path: Path, package_path: Path) -> dict[str, Any]:
    path = workspace_path if workspace_path.exists() else package_path
    return json.loads(path.read_text(encoding="utf-8"))


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default
