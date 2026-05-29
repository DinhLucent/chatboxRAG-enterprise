from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from .chatbot import (
    ANSWER_STYLE_LABELS,
    NO_SOURCE_ANSWER,
    ask,
    infer_category,
    infer_query_answer_style,
    mermaid_flowchart,
    workflow_label,
)
from .database import QualityDatabase
from .manifest import ManifestStore, latest_active_records
from .qa_agent_workflow import (
    RESPONSE_CONTRACT_VERSION,
    attach_answer_contract,
    clarification_format_plan,
    clarification_structured_answer,
    no_answer_format_plan,
    no_answer_structured_answer,
    normalize_block_plan,
    normalize_blocks,
    public_format_plan,
    public_structured_answer,
    qa_agent_workflow_enabled,
    run_qa_agent_workflow,
    scope_guard,
)
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
        "label": "Quy trình Phương Đông",
        "template_id": "procedure_steps",
        "question": "Quy trình Phương Đông gồm những bước nào?",
        "answer_style": "steps",
    },
    {
        "id": "welcome_form",
        "label": "Biểu mẫu quy trình",
        "template_id": "form_usage",
        "question": "Trường hợp này cần dùng biểu mẫu quy trình nào?",
        "answer_style": "brief",
    },
    {
        "id": "welcome_incident",
        "label": "Xử lý sự cố",
        "template_id": "incident_first_response",
        "question": "Khi phát sinh sự cố vận hành, cần xử lý ban đầu thế nào?",
        "answer_style": "checklist",
    },
    {
        "id": "welcome_vendor",
        "label": "Tài liệu quy trình",
        "template_id": "vendor_requirement",
        "question": "Tài liệu quy trình nêu yêu cầu thế nào?",
        "answer_style": "brief",
    },
]


FOLLOW_UP_PATTERNS = [
    r"\b(buoc|bước)\s*\d+\b",
    r"\b(no|nó|do|đó|tren|trên|duoi|dưới)\b",
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


def confidence_label(value: object = None, *, has_citations: bool = False, needs_clarification: bool = False) -> str:
    if needs_clarification:
        return "low"
    try:
        score = float(value) if value is not None else (0.82 if has_citations else 0.2)
    except (TypeError, ValueError):
        score = 0.82 if has_citations else 0.2
    if score > 1:
        score = score / 100
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def answer_contract_fields(
    answer: str,
    citations: list[dict[str, Any]],
    *,
    answer_style: str,
    fallback_reason: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    if fallback_reason or (not citations and normalized_text(answer) == normalized_text(NO_SOURCE_ANSWER)):
        reason = fallback_reason or "no_active_source"
        format_plan = no_answer_format_plan()
        structured_answer = no_answer_structured_answer(answer or NO_SOURCE_ANSWER, reason)
        return {
            "answer_text": answer or NO_SOURCE_ANSWER,
            "confidence": "low",
            "response_contract_version": RESPONSE_CONTRACT_VERSION,
            "format_type": "no_answer_card",
            "format_plan": public_format_plan(format_plan),
            "structured_answer": public_structured_answer(structured_answer),
            "blocks": normalize_blocks(structured_answer.get("blocks")),
            "block_plan": normalize_block_plan(format_plan.get("block_plan")),
        }

    format_type = {
        "workflow": "workflow",
        "checklist": "checklist",
        "steps": "step_by_step",
    }.get(answer_style, "summary")
    blocks = legacy_answer_blocks(answer, citations, answer_style, query=query)
    block_plan = normalize_block_plan(
        {
            str(block.get("type")): {
                "enabled": True,
                "reason": "Derived from legacy grounded answer.",
            }
            for block in blocks
            if isinstance(block, dict) and block.get("type")
        }
    )
    format_plan = {
        "primary_format": format_type,
        "secondary_blocks": ["sources"],
        "render_hints": {
            "show_timeline": format_type in {"workflow", "step_by_step"},
            "show_checklist_button": format_type in {"workflow", "step_by_step", "checklist"},
            "show_mermaid_button": format_type == "workflow",
            "show_no_answer_card": False,
        },
        "block_plan": block_plan,
    }
    structured_answer = {
        "answer_type": format_type,
        "title": "",
        "summary": answer_summary_text(answer),
        "steps": [],
        "responsibilities": [],
        "forms_records": [],
        "notes": [],
        "sources": sources_from_public_citations(citations),
        "markdown": answer,
        "blocks": blocks,
    }
    return {
        "answer_text": answer,
        "confidence": confidence_label(has_citations=bool(citations)),
        "response_contract_version": RESPONSE_CONTRACT_VERSION,
        "format_type": format_type,
        "format_plan": public_format_plan(format_plan),
        "structured_answer": public_structured_answer(structured_answer),
        "blocks": blocks,
        "block_plan": normalize_block_plan(format_plan.get("block_plan")),
    }


def answer_summary_text(answer: str) -> str:
    sections = answer_sections(answer)
    summary = "\n".join(sections.get("summary") or []).strip()
    if summary:
        return clean_excerpt(summary, max_chars=720)
    for line in answer.splitlines():
        cleaned = line.strip()
        normalized = normalized_text(cleaned).rstrip(":")
        if cleaned and normalized not in {"tom tat", "workflow", "nguon"}:
            return clean_excerpt(cleaned, max_chars=720)
    return ""


def answer_sections(answer: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "summary"
    for raw_line in str(answer or "").splitlines():
        raw_normalized = normalized_text(raw_line).strip().strip("#").strip()
        normalized = raw_normalized.rstrip(":")
        if normalized == "tom tat" or raw_normalized.startswith("tom tat:"):
            current = "summary"
            sections.setdefault(current, [])
            inline = raw_line.split(":", 1)[1].strip() if ":" in raw_line else ""
            if inline:
                sections[current].append(inline)
            continue
        if normalized.startswith("workflow"):
            current = "workflow"
            sections.setdefault(current, [])
            continue
        if normalized.startswith("bang"):
            current = "table"
            sections.setdefault(current, [])
            continue
        if normalized.startswith("cac buoc") or normalized.startswith("noi dung chinh"):
            current = "main"
            sections.setdefault(current, [])
            continue
        if normalized.startswith("nguon"):
            current = "sources"
            sections.setdefault(current, [])
            inline = raw_line.split(":", 1)[1].strip() if ":" in raw_line else ""
            if inline:
                sections[current].append(inline)
            continue
        sections.setdefault(current, []).append(raw_line)
    return {key: [line for line in value if line.strip()] for key, value in sections.items()}


def legacy_answer_blocks(
    answer: str,
    citations: list[dict[str, Any]],
    answer_style: str,
    *,
    query: str | None = None,
) -> list[dict[str, object]]:
    sections = answer_sections(answer)
    blocks: list[dict[str, object]] = []
    summary = "\n".join(sections.get("summary") or []).strip()
    if summary:
        blocks.append({"type": "summary", "content": clean_excerpt(summary, max_chars=720)})

    table = extract_markdown_table(answer)
    if table:
        blocks.append({"type": "table", "markdown": table})

    main_items = legacy_block_items(sections.get("main") or [], citations)
    mermaid = extract_mermaid(answer)
    if answer_style == "workflow" or mermaid:
        workflow_items = main_items or workflow_items_from_mermaid(mermaid)
        if workflow_items or mermaid:
            block: dict[str, object] = {"type": "workflow", "items": workflow_items}
            if mermaid:
                block["mermaid"] = mermaid
            blocks.append(block)
    if main_items:
        blocks.append({"type": "checklist" if answer_style == "checklist" else "steps", "items": main_items})

    normalized_query = normalized_text(query or "")
    if asks_decision_matrix(normalized_query) and citations:
        blocks.append({"type": "decision_matrix", "items": option_items_from_citations(citations)})
    if asks_form_listing(normalized_query) and citations:
        form_items = option_items_from_citations(
            [
                citation
                for citation in citations
                if str(citation.get("category") or "") == "form_checklist"
                or normalized_text(citation.get("title") or citation.get("display_code") or "").startswith("bm")
            ]
            or citations
        )
        blocks.append({"type": "form", "items": form_items})

    sources = sources_from_public_citations(citations)
    if sources:
        blocks.append({"type": "sources", "items": sources})
    return normalize_blocks(blocks)


def extract_markdown_table(answer: str) -> str:
    lines = str(answer or "").splitlines()
    tables: list[str] = []
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if "|" in next_line and re.search(r"\|\s*:?-{3,}:?\s*\|", next_line):
            table_lines = [line, next_line]
            for tail in lines[index + 2 :]:
                if "|" not in tail.strip():
                    break
                table_lines.append(tail)
            tables.append("\n".join(table_lines))
            break
    return tables[0] if tables else ""


def asks_decision_matrix(normalized_query: str) -> bool:
    return any(
        term in normalized_query
        for term in ["nen dung", "nen chon", "chon bieu mau", "so sanh", "khac nhau", "phan van"]
    )


def asks_form_listing(normalized_query: str) -> bool:
    return any(term in normalized_query for term in ["bieu mau", "form", "ho so", "phieu", "mau nao"])


def option_items_from_citations(citations: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for citation in citations:
        display = str(citation.get("display_code") or citation.get("doc_id") or "").strip()
        title = clean_excerpt(citation.get("title") or display, max_chars=160)
        key = display or title
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "option": display or title,
                "text": title,
                "detail": clean_excerpt(citation.get("excerpt") or citation.get("matched_excerpt") or "", max_chars=260),
                "source_anchor": str(citation.get("anchor_id") or ""),
            }
        )
    return items[:8]


def legacy_block_items(lines: list[str], citations: list[dict[str, Any]]) -> list[dict[str, str]]:
    source_anchor = str((citations[0] if citations else {}).get("anchor_id") or "")
    items: list[dict[str, str]] = []
    for line in lines:
        text = re.sub(r"^\s*(?:[-*]\s*(?:\[[ xX]\]\s*)?|\d+[\).\s-]+)", "", line).strip()
        if not text:
            continue
        items.append({"text": clean_excerpt(text, max_chars=260), "detail": "", "source_anchor": source_anchor})
    return items[:12]


def extract_mermaid(answer: str) -> str:
    match = re.search(r"```mermaid\s*(.*?)```", str(answer or ""), flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def workflow_items_from_mermaid(mermaid: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for label in re.findall(r"\[\"?([^\"\]\n]+)\"?\]", mermaid or ""):
        cleaned = clean_excerpt(label, max_chars=160)
        if cleaned:
            items.append({"text": cleaned, "detail": "", "source_anchor": ""})
    return items[:12]


def sources_from_public_citations(citations: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for citation in citations:
        doc_id = str(citation.get("doc_id") or "")
        version = str(citation.get("version") or "")
        if not doc_id or (doc_id, version) in seen:
            continue
        sources.append(
            {
                "doc_id": doc_id,
                "version": version,
                "display_code": str(citation.get("display_code") or ""),
                "display_version": str(citation.get("display_version") or ""),
                "title": clean_excerpt(citation.get("title") or doc_id, max_chars=180),
                "locator": str(citation.get("anchor_id") or ""),
            }
        )
        seen.add((doc_id, version))
    return sources[:10]


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
    stream_callback: Callable[[dict[str, Any]], None] | None = None,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = QualityDatabase(root)
    # Check for annotated standard QA
    annotation = db.get_annotation(query)
    if annotation:
        active_session_id = normalize_session_id(session_id)
        session = db.touch_user_chat_session(
            active_session_id,
            device_id=device_id,
            ttl_seconds=user_session_ttl_seconds(),
        )
        
        # Build mock citations if doc_id is available
        annotated_answer = str(annotation.get("annotated_answer") or "")
        citations = []
        doc_id = annotation.get("doc_id")
        version = annotation.get("version")
        if doc_id:
            citations.append({
                "title": f"Tài liệu ghim: {doc_id}",
                "doc_id": doc_id,
                "version": version or "1.0",
                "display_code": doc_id,
                "display_version": f"v{version}" if version else "",
                "excerpt": annotated_answer,
                "anchor_id": ""
            })
            
        # Log to query_logs (0 latency, 0 tokens, answer_source="annotations")
        log_id = db.log_query(
            query,
            user_id,
            [doc_id] if doc_id else [],
            bool(citations),
            0,
            annotated_answer,
            llm_used=False,
            answer_source="annotations",
            tokens_prompt=0,
            tokens_completion=0,
        )
        
        # Log session turn
        db.log_user_chat_turn(
            active_session_id,
            query=query,
            effective_query=query,
            answer=annotated_answer,
            citation_doc_ids=[doc_id] if doc_id else [],
            query_log_id=log_id,
            template_id=template_id
        )
        
        # Build trace steps
        trace_steps = [
            {
                "id": "annotations",
                "label": "Kho câu hỏi chuẩn",
                "status": "done",
                "detail": "Khớp câu trả lời chuẩn đã được phê duyệt bởi Quản trị viên."
            }
        ]
        
        trace = {
            "source_count": len(citations),
            "generated_at": utc_now(),
            "steps": trace_steps,
            "tokens_prompt": 0,
            "tokens_completion": 0,
            "latency_ms": 0,
            "context": {
                "session_id": active_session_id,
                "turns_available": 0,
                "turns_used": 0,
                "context_used": False,
                "expires_at": session["expires_at"],
            }
        }
        contract = answer_contract_fields(annotated_answer, citations, answer_style=answer_style or "brief", query=query)
        
        return {
            "answer": annotated_answer,
            **contract,
            "citations": citations,
            "trace": trace,
            "trace_steps": trace_steps,
            "query_log_id": log_id,
            "log_id": log_id,
            "policy": public_policy_summary(load_policy_pack(root)),
            "template_id": template_id,
            "answer_style": answer_style or "brief",
            "needs_clarification": False,
            "session_id": active_session_id,
            "session": {
                "session_id": active_session_id,
                "device_id": session.get("device_id"),
                "last_seen_at": session.get("last_seen_at"),
                "expires_at": session.get("expires_at"),
                "ttl_seconds": user_session_ttl_seconds(),
            }
        }

    policy = load_policy_pack(root)
    active_answer_style = infer_answer_style(query, normalize_answer_style(answer_style))
    active_session_id = normalize_session_id(session_id)
    session = db.touch_user_chat_session(
        active_session_id,
        device_id=device_id,
        ttl_seconds=user_session_ttl_seconds(),
    )
    session_context = db.user_chat_context(active_session_id)
    history = db.recent_user_chat_turns(active_session_id, limit=user_context_turn_limit())
    scope = scope_guard(query)
    contextual_follow_up = should_use_context(query) and (history or session_context.get("active_doc_id"))
    if not scope["in_scope"] and not contextual_follow_up:
        return scope_reject_response(
            db,
            policy,
            query=query,
            answer=str(scope.get("safe_reply") or policy.get("no_answer") or NO_SOURCE_ANSWER),
            active_session_id=active_session_id,
            session=session,
            template_id=template_id,
            answer_style=active_answer_style,
            user_id=user_id,
        )
    if needs_clarification(query, history, session_context):
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
    if qa_agent_workflow_enabled():
        return qa_agent_chat_response(
            root,
            db,
            policy,
            query=query,
            active_session_id=active_session_id,
            session=session,
            session_context=session_context,
            history=history,
            template_id=template_id,
            answer_style=active_answer_style,
            use_llm=use_llm,
            user_id=user_id,
            stream_callback=stream_callback,
            variables=variables,
        )
    effective_query = contextual_query(query, history, session_context)
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
    result["answer"] = format_user_answer(str(result.get("answer") or ""), citations, active_answer_style, query=query)
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
    db.update_user_chat_context(
        active_session_id,
        build_session_context(
            query=query,
            answer=str(result.get("answer") or ""),
            answer_style=active_answer_style,
            citations=citations,
            previous=session_context,
            structured_answer={},
        ),
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
    contract = answer_contract_fields(
        str(result.get("answer") or policy.get("no_answer") or NO_SOURCE_ANSWER),
        citations,
        answer_style=active_answer_style,
        fallback_reason=str(result.get("fallback_reason") or "") if not citations else None,
        query=query,
    )
    return {
        "answer": result.get("answer") or policy.get("no_answer") or NO_SOURCE_ANSWER,
        **contract,
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


def qa_agent_chat_response(
    root: Path,
    db: QualityDatabase,
    policy: dict[str, Any],
    *,
    query: str,
    active_session_id: str,
    session: dict[str, Any],
    session_context: dict[str, Any],
    history: list[dict[str, Any]],
    template_id: str | None,
    answer_style: str,
    use_llm: bool,
    user_id: str | None,
    stream_callback: Callable[[dict[str, Any]], None] | None = None,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_query = contextual_query(query, history, session_context)
    context_info = conversation_context_payload(query, effective_query, history, session_context)
    result = run_qa_agent_workflow(
        root,
        effective_query,
        history=history,
        conversation_context=context_info,
        answer_style=answer_style,
        use_llm=use_llm,
        emit=stream_callback,
        variables=variables,
    )
    result = attach_answer_contract(result)
    citations = sanitize_public_citations(
        root,
        result.get("citations") or [],
        require_manifest=False,
    )
    if result.get("answer_source") in {"clarification", "scope_guard"}:
        answer = str(result.get("answer") or "")
    else:
        answer = format_user_answer(str(result.get("answer") or ""), citations, answer_style, query=query)
    citation_doc_ids = sorted({str(citation.get("doc_id")) for citation in citations if citation.get("doc_id")})
    
    tokens_prompt = result.get("tokens_prompt") or 0
    tokens_completion = result.get("tokens_completion") or 0
    latency_ms = int(result.get("latency_ms") or 0)
    
    log_id = db.log_query(
        query,
        user_id,
        citation_doc_ids,
        bool(citations),
        latency_ms,
        answer,
        llm_used=bool(result.get("llm_used")),
        llm_error=result.get("llm_error"),
        answer_source=str(result.get("answer_source") or ""),
        llm_provider=result.get("llm_provider"),
        llm_model=result.get("llm_model"),
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
    )
    gap_id = None
    fallback_reason = str(result.get("fallback_reason") or "")
    if fallback_reason and result.get("answer_source") not in {"clarification", "qa_agent_llm"}:
        gap_id = db.create_gap(query, fallback_reason, infer_category(query))
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
        effective_query=effective_query,
        answer=answer,
        citation_doc_ids=citation_doc_ids,
        query_log_id=log_id,
        template_id=template_id,
    )
    answer_run = result.get("answer_run") if isinstance(result.get("answer_run"), dict) else {}
    if answer_run:
        db.log_answer_run(
            answer_run,
            query_log_id=log_id,
            session_id=active_session_id,
            user_question=query,
        )
    db.update_user_chat_context(
        active_session_id,
        build_session_context(
            query=query,
            answer=answer,
            answer_style=answer_style,
            citations=citations,
            previous=session_context,
            structured_answer=result.get("structured_answer") if isinstance(result.get("structured_answer"), dict) else {},
        ),
    )
    trace_steps = list(result.get("trace_steps") or [])
    context_used = effective_query != query
    if context_used:
        trace_steps.insert(
            0,
            {
                "id": "context",
                "label": "Dùng bối cảnh hội thoại",
                "status": "done",
                "detail": f"Dùng {len(history)} lượt gần nhất để hiểu câu hỏi nối tiếp.",
            },
        )
    trace = {
        "source_count": len(citations),
        "generated_at": utc_now(),
        "steps": trace_steps,
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "latency_ms": latency_ms,
        "context": {
            "session_id": active_session_id,
            "turns_available": len(history),
            "turns_used": len(history) if context_used else 0,
            "context_used": context_used,
            "active_doc_id": context_info.get("active_doc_id"),
            "active_display_code": context_info.get("active_display_code"),
            "active_topic": context_info.get("active_topic"),
            "expires_at": session["expires_at"],
        },
    }
    return {
        "answer": answer or policy.get("no_answer") or NO_SOURCE_ANSWER,
        "answer_text": answer or policy.get("no_answer") or NO_SOURCE_ANSWER,
        "confidence": confidence_label(
            answer_run.get("final_confidence") if isinstance(answer_run, dict) else None,
            has_citations=bool(citations),
            needs_clarification=bool(result.get("needs_clarification")),
        ),
        "citations": citations,
        "trace": trace,
        "trace_steps": trace_steps,
        "evidence_summary": result.get("evidence_summary") or {},
        "quality_decision": result.get("quality_decision") or {},
        "procedure_compliance": result.get("procedure_compliance") or {},
        "format_type": result.get("format_type") or "markdown",
        "evidence_pack": result.get("evidence_pack") or {},
        "answer_run": answer_run,
        "structured_answer": result.get("structured_answer") or {},
        "format_plan": result.get("format_plan") or {},
        "response_contract_version": result.get("response_contract_version") or RESPONSE_CONTRACT_VERSION,
        "blocks": result.get("blocks") or [],
        "block_plan": result.get("block_plan") or {},
        "handoff": result.get("handoff"),
        "query_log_id": log_id,
        "log_id": log_id,
        "knowledge_gap_id": gap_id,
        "policy": public_policy_summary(policy),
        "template_id": template_id,
        "answer_style": answer_style,
        "needs_clarification": bool(result.get("needs_clarification")),
        "session_id": active_session_id,
        "session": {
            "session_id": active_session_id,
            "device_id": session.get("device_id"),
            "last_seen_at": session.get("last_seen_at"),
            "expires_at": session.get("expires_at"),
            "ttl_seconds": user_session_ttl_seconds(),
            "context": context_info,
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
    format_plan = clarification_format_plan()
    structured_answer = clarification_structured_answer(answer, ["document_or_procedure_name"])
    trace["context"] = {
        "session_id": active_session_id,
        "turns_available": 0,
        "turns_used": 0,
        "context_used": False,
        "expires_at": session["expires_at"],
    }
    return {
        "answer": answer,
        "answer_text": answer,
        "confidence": "low",
        "citations": [],
        "trace": trace,
        "trace_steps": trace["steps"],
        "query_log_id": log_id,
        "log_id": log_id,
        "knowledge_gap_id": None,
        "policy": public_policy_summary(policy),
        "template_id": template_id,
        "answer_style": answer_style,
        "response_contract_version": RESPONSE_CONTRACT_VERSION,
        "format_type": "clarification",
        "format_plan": public_format_plan(format_plan),
        "structured_answer": public_structured_answer(structured_answer),
        "blocks": normalize_blocks(structured_answer.get("blocks")),
        "block_plan": normalize_block_plan(format_plan.get("block_plan")),
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


def scope_reject_response(
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
        answer_source="scope_guard",
    )
    gap_id = db.create_gap(query, "out_of_scope", infer_category(query))
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
    trace = build_public_trace({"answer": answer, "answer_source": "scope_guard"}, 0, policy)
    trace["context"] = {
        "session_id": active_session_id,
        "turns_available": 0,
        "turns_used": 0,
        "context_used": False,
        "expires_at": session["expires_at"],
    }
    contract = answer_contract_fields(answer, [], answer_style=answer_style, fallback_reason="out_of_scope", query=query)
    return {
        "answer": answer,
        **contract,
        "citations": [],
        "trace": trace,
        "trace_steps": trace["steps"],
        "query_log_id": log_id,
        "log_id": log_id,
        "knowledge_gap_id": gap_id,
        "quality_decision": {
            "decision": "scope_reject",
            "reason": "out_of_scope",
            "issues": ["Question is outside the supported document scope."],
        },
        "policy": public_policy_summary(policy),
        "template_id": template_id,
        "answer_style": answer_style,
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


def contextual_query(
    query: str,
    history: list[dict[str, Any]],
    session_context: dict[str, Any] | None = None,
) -> str:
    clean_query = query.strip()
    session_context = session_context or {}
    if not should_use_context(clean_query):
        return clean_query
    if not history and not session_context.get("active_doc_id"):
        return clean_query
    anchor_turn = next((turn for turn in reversed(history) if turn.get("citation_doc_ids")), history[-1] if history else {})
    context_lines: list[str] = []
    if session_context.get("active_topic"):
        context_lines.append(f"Chủ đề đang theo: {public_excerpt(session_context.get('active_topic') or '')}")
    if session_context.get("active_doc_id"):
        display = session_context.get("active_display_code") or session_context.get("active_doc_id")
        version = session_context.get("active_display_version") or ""
        context_lines.append(f"Tài liệu đang theo: {display} {version}".strip())
    if anchor_turn:
        context_lines.append(f"Chủ đề trước: {public_excerpt(anchor_turn.get('query') or '')}")
    citation_doc_ids = [str(doc_id) for doc_id in anchor_turn.get("citation_doc_ids") or [] if doc_id]
    if citation_doc_ids:
        context_lines.append(f"Tài liệu đã dùng trước: {', '.join(citation_doc_ids[:5])}")
    if not context_lines:
        return clean_query
    return "\n".join(
        [
            "Cau hoi hien tai:",
            clean_query,
            "",
            "Boi canh hoi thoai gan day de lam ro dai tu/cau hoi noi tiep:",
            *context_lines,
        ]
    )


def conversation_context_payload(
    query: str,
    effective_query: str,
    history: list[dict[str, Any]],
    session_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_context = session_context or {}
    return {
        "needs_clarification": False,
        "is_follow_up": should_use_context(query),
        "effective_query": effective_query,
        "context_used": effective_query != query,
        "turns_used": len(history) if effective_query != query else 0,
        "active_doc_id": session_context.get("active_doc_id"),
        "active_display_code": session_context.get("active_display_code"),
        "active_display_version": session_context.get("active_display_version"),
        "active_topic": session_context.get("active_topic"),
        "last_answer_style": session_context.get("last_answer_style"),
        "last_steps": session_context.get("last_steps") or [],
        "last_citations": session_context.get("last_citations") or [],
    }


def build_session_context(
    *,
    query: str,
    answer: str,
    answer_style: str,
    citations: list[dict[str, Any]],
    previous: dict[str, Any] | None = None,
    structured_answer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous or {}
    structured_answer = structured_answer or {}
    primary = citations[0] if citations else {}
    active_doc_id = primary.get("doc_id") or previous.get("active_doc_id")
    active_topic = primary.get("title") or structured_answer.get("title") or previous.get("active_topic") or query
    return {
        "active_doc_id": active_doc_id,
        "active_topic": public_excerpt(active_topic or query, 160),
        "active_display_code": primary.get("display_code") or previous.get("active_display_code"),
        "active_display_version": primary.get("display_version") or previous.get("active_display_version"),
        "last_answer_style": answer_style,
        "last_steps": extract_context_steps(structured_answer, answer),
        "last_citations": [
            {
                "doc_id": citation.get("doc_id"),
                "version": citation.get("version"),
                "display_code": citation.get("display_code"),
                "display_version": citation.get("display_version"),
                "title": citation.get("title"),
            }
            for citation in citations[:5]
        ],
        "session_summary": public_excerpt(answer, 360),
        "updated_at": utc_now(),
    }


def extract_context_steps(structured_answer: dict[str, Any], answer: str) -> list[dict[str, Any]]:
    steps = structured_answer.get("steps") if isinstance(structured_answer.get("steps"), list) else []
    if steps:
        return [
            {
                "step_no": item.get("step_no"),
                "title": public_excerpt(item.get("title") or item.get("description") or "", 120),
                "source_anchor": item.get("source_anchor"),
            }
            for item in steps[:8]
            if isinstance(item, dict)
        ]
    extracted = []
    for line in answer.splitlines():
        match = re.match(r"\s*(\d+)[.)]\s+(.+)", line)
        if not match:
            continue
        extracted.append({"step_no": int(match.group(1)), "title": public_excerpt(match.group(2), 120)})
        if len(extracted) >= 8:
            break
    return extracted


def infer_answer_style(query: str, selected_style: str) -> str:
    return infer_query_answer_style(query, selected_style)


def needs_clarification(
    query: str,
    history: list[dict[str, Any]],
    session_context: dict[str, Any] | None = None,
) -> bool:
    clean_query = query.strip()
    session_context = session_context or {}
    if history and should_use_context(clean_query):
        last_turn = history[-1]
        if last_turn.get("citation_doc_ids"):
            return False
    if should_use_context(clean_query) and session_context.get("active_doc_id"):
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
            "cai nay",
            "van de nay",
            "muc nay",
            "phan nay",
            "noi dung tren",
        ]
    )


def public_policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": "Trợ lý Tri thức Quy trình Phương Đông",
        "summary": [
            "Trợ lý chỉ trả lời dựa trên tài liệu quy trình đang hiệu lực của Phương Đông.",
            "Nếu không tìm thấy căn cứ, trợ lý sẽ nói rõ là chưa tìm thấy trong tài liệu hiện hành.",
        ],
        "debug_visible": False,
    }


def sanitize_public_citations(
    root: Path,
    citations: list[dict[str, Any]],
    *,
    require_manifest: bool = True,
) -> list[dict[str, Any]]:
    active_records = latest_active_records(ManifestStore(root).load())
    active_latest = {(record.doc_id, record.version): record for record in active_records}
    safe: list[dict[str, Any]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("doc_id") or "")
        version = str(citation.get("version") or "")
        record = active_latest.get((doc_id, version))
        if not doc_id or not version:
            continue
        if record is None and require_manifest:
            continue
        if record is None and str(citation.get("status") or "").lower() not in {"active", "approved", "latest"}:
            continue
        record_extra = record.extra if record else {}
        display_code = str(citation.get("display_code") or record_extra.get("display_code") or "")
        display_version = str(
            citation.get("display_version")
            or citation.get("source_revision")
            or record_extra.get("display_version")
            or record_extra.get("source_revision")
            or ""
        )
        title = citation.get("title") or (record.title if record else doc_id)
        score = citation.get("score") or citation.get("similarity") or citation.get("rank_score")
        try:
            score_float = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_float = None

        safe_dict = {
            "title": public_excerpt(clean_retrieval_text(title or doc_id or "Nguồn"), 160),
            "doc_id": doc_id,
            "version": version,
            "display_code": display_code,
            "display_version": display_version,
            "excerpt": public_excerpt(clean_excerpt(citation.get("excerpt") or citation.get("text") or "")),
            "anchor_id": str(citation.get("anchor_id") or ""),
        }
        if score_float is not None:
            safe_dict["score"] = score_float
        safe.append(safe_dict)
    return safe


def format_user_answer(
    answer: str,
    citations: list[dict[str, Any]],
    answer_style: str,
    *,
    query: str | None = None,
) -> str:
    text = answer.strip() or NO_SOURCE_ANSWER
    if contains_raw_markup(text):
        text = clean_retrieval_text(text)
    if text == NO_SOURCE_ANSWER or not citations:
        return NO_SOURCE_ANSWER if not citations else text
    text = add_grounding_caveat_for_requested_role(text, query)
    text = add_form_usage_context(text, query, citations)
    text = add_workflow_evidence_caveat(text, query, answer_style)
    if has_answer_headings(text):
        return normalize_answer_headings(text)
    if "Tóm tắt:" in text and "Nguồn:" in text:
        return text
    source_text = ", ".join(
        f"{citation.get('display_code') or citation.get('doc_id')} {citation.get('display_version') or 'v' + str(citation.get('version'))}"
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


def add_grounding_caveat_for_requested_role(answer: str, query: str | None) -> str:
    normalized_query = normalized_text(query or "")
    if not any(term in normalized_query for term in ["ai duyet", "ai phe duyet", "ai phu trach", "nguoi duyet"]):
        return answer
    normalized_answer = normalized_text(answer)
    if any(term in normalized_answer for term in ["duyet", "phe duyet", "phu trach", "responsible", "accountable"]):
        return answer
    return (
        "Chưa thấy căn cứ nêu rõ người phê duyệt/phụ trách trực tiếp cho ý hỏi này. "
        f"Phần liên quan trong tài liệu cho biết: {answer}"
    )


def add_form_usage_context(answer: str, query: str | None, citations: list[dict[str, Any]]) -> str:
    normalized_query = normalized_text(query or "")
    if not asks_form_listing(normalized_query):
        return answer
    if not any(term in normalized_query for term in ["dung khi", "khi nao", "luc nao", "truong hop nao"]):
        return answer
    normalized_answer = normalized_text(answer)
    if any(
        term in normalized_answer
        for term in ["dung khi", "su dung khi", "ap dung khi", "dung de", "su dung de", "tai lieu nay la bieu mau"]
    ):
        return answer
    citation = next(
        (
            item
            for item in citations
            if str(item.get("category") or "") == "form_checklist"
            or normalized_text(item.get("title") or item.get("display_code") or "").startswith("bm")
        ),
        citations[0] if citations else {},
    )
    label = citation_usage_label(citation)
    excerpt = clean_excerpt(citation.get("excerpt") or citation.get("matched_excerpt") or citation.get("text") or "", max_chars=260)
    prefix = f"Biểu mẫu/hồ sơ này dùng khi cần lập hoặc ghi nhận thông tin theo {label}."
    if excerpt:
        prefix += f" Tài liệu không nêu rõ điều kiện sử dụng riêng trong phần trích dẫn; căn cứ hiện có cho biết: {excerpt}"
    return f"{prefix}\n\n{answer}"


def citation_usage_label(citation: dict[str, Any]) -> str:
    title = clean_retrieval_text(citation.get("title") or citation.get("display_code") or citation.get("doc_id") or "biểu mẫu/hồ sơ")
    display_code = str(citation.get("display_code") or citation.get("doc_id") or "").strip()
    if display_code and normalized_text(display_code) not in normalized_text(title):
        title = f"{display_code} - {title}"
    return clean_excerpt(title, max_chars=180)


def add_workflow_evidence_caveat(answer: str, query: str | None, answer_style: str) -> str:
    normalized_query = normalized_text(query or "")
    if answer_style != "workflow" and not any(term in normalized_query for term in ["workflow", "luu do", "ve quy trinh"]):
        return answer
    normalized_answer = normalized_text(answer)
    if any(term in normalized_answer for term in ["khong du noi dung dang quy trinh", "khong du can cu", "chua du can cu"]):
        return answer
    if workflow_point_count(answer) >= 2:
        return answer
    evidence = compact_answer_evidence(answer)
    return (
        "Tài liệu được dẫn chưa đủ nội dung dạng quy trình để vẽ workflow nhiều bước. "
        f"Phần có căn cứ hiện tại là: {evidence}"
    )


def compact_answer_evidence(answer: str) -> str:
    sections = answer_sections(answer)
    candidates = sections.get("summary") or sections.get("main") or []
    if not candidates:
        candidates = _answer_points(answer)
    text = " ".join(str(item).strip(" -*") for item in candidates if str(item).strip(" -*"))
    return clean_excerpt(text or answer, max_chars=260)


def workflow_point_count(answer: str) -> int:
    sections = answer_sections(answer)
    main_items = legacy_block_items(sections.get("main") or [], [])
    if main_items:
        return len(main_items)
    mermaid_items = workflow_items_from_mermaid(extract_mermaid(answer))
    if mermaid_items:
        return len(mermaid_items)
    heading_terms = {"tom tat", "workflow", "cac buoc / noi dung chinh", "noi dung chinh", "nguon"}
    points = [workflow_label(item) for item in _answer_points(answer)]
    return len([point for point in points if point and normalized_text(point).strip(" :-") not in heading_terms])


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
        heading_key = re.sub(r"\s+", " ", normalized_heading).strip(" #*-")
        heading_candidate = len(heading_key) <= 32 and len(heading_key.split()) <= 6
        if heading_candidate and heading_key.startswith("tom tat"):
            lines.append("Tóm tắt:" + (f" {rest}" if rest else ""))
        elif heading_candidate and (heading_key.startswith("cac buoc") or heading_key.startswith("noi dung chinh")):
            lines.append("Các bước / Nội dung chính:" + (f" {rest}" if rest else ""))
        elif heading_candidate and heading_key.startswith("nguon"):
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
    elif answer_source == "scope_guard":
        answer_detail = "Câu hỏi nằm ngoài phạm vi tài liệu quy trình đang hỗ trợ."
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
