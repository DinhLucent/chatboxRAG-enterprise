from __future__ import annotations

import argparse
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from .chatbot import DEPARTMENT_LABELS
from .manifest import ManifestStore, latest_active_records
from .models import ManifestRecord
from .qa_agent_workflow import BLOCK_TYPES, RESPONSE_CONTRACT_VERSION
from .text_cleaning import clean_excerpt, normalized_text, repair_mojibake
from .utils import utc_now, write_json
from .webapp import create_app


DEFAULT_REPORT = Path(".runtime") / "user-chat-100-context-audit.json"
QUALITY_WEIGHTS = {
    "intent_alignment": 0.30,
    "document_grounding": 0.30,
    "completeness": 0.20,
    "citation_fit": 0.15,
    "render_fit": 0.05,
}
QUALITY_PASS_THRESHOLD = 0.68
CRITICAL_QUALITY_THRESHOLD = 0.45
TERM_STOPWORDS = {
    "anh",
    "ban",
    "bang",
    "biet",
    "bo",
    "buoc",
    "cac",
    "cho",
    "cua",
    "duoc",
    "dung",
    "gom",
    "hay",
    "hoi",
    "khi",
    "la",
    "lam",
    "mau",
    "mot",
    "nao",
    "neu",
    "nguon",
    "noi",
    "phong",
    "quy",
    "quy trinh",
    "tai",
    "tai lieu",
    "the",
    "thi",
    "tom",
    "trinh",
    "trong",
    "va",
    "ve",
}


@dataclass(frozen=True)
class Scenario:
    id: str
    query: str
    expected_action: str = "answer"
    answer_style: str = "brief"
    expected_doc_ids: tuple[str, ...] = ()
    expected_department: str | None = None
    expected_blocks: tuple[str, ...] = ()
    expected_blocks_any: tuple[str, ...] = ()
    prelude: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default_factory=tuple)


def run_user_chat_scenario_audit(root: Path, *, limit: int = 100) -> dict[str, Any]:
    root = root.resolve()
    records = latest_active_records(ManifestStore(root).load())
    scenarios = generate_scenarios(records, limit=limit)
    active_by_key = {(record.doc_id, record.version): record for record in records}
    source_cache: dict[tuple[str, str], str] = {}
    client = TestClient(create_app(root))
    run_id = uuid.uuid4().hex[:8]
    results = [
        run_scenario(client, scenario, active_by_key=active_by_key, source_cache=source_cache, run_id=run_id)
        for scenario in scenarios
    ]
    quality_scores = [float((item.get("answer_evaluation") or {}).get("overall_score") or 0.0) for item in results]
    report = {
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "run_id": run_id,
        "rubric": quality_rubric(),
        "total_contexts": len(scenarios),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "pass": all(item["passed"] for item in results),
        "quality_metrics": {
            "average_score": round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else 0.0,
            "min_score": round(min(quality_scores), 3) if quality_scores else 0.0,
            "quality_passed": sum(
                1
                for item in results
                if bool((item.get("answer_evaluation") or {}).get("quality_pass"))
            ),
            "quality_failed": sum(
                1
                for item in results
                if not bool((item.get("answer_evaluation") or {}).get("quality_pass"))
            ),
        },
        "failure_summary": summarize_failures(results),
        "results": results,
    }
    write_json(root / DEFAULT_REPORT, report)
    return report


def generate_scenarios(records: list[ManifestRecord], *, limit: int = 100) -> list[Scenario]:
    active = sorted(
        records,
        key=lambda record: (
            record.department,
            record.category,
            str(record.extra.get("display_code") or record.doc_id),
            record.doc_id,
        ),
    )
    procedure_records = [record for record in active if record.category == "procedure"]
    form_records = [record for record in active if record.category in {"form_checklist", "faq_troubleshooting"}]

    scenarios: list[Scenario] = []
    by_department: dict[str, list[ManifestRecord]] = {}
    for record in procedure_records:
        by_department.setdefault(record.department, []).append(record)
    for department in sorted(by_department):
        label = DEPARTMENT_LABELS.get(department, department.replace("_", " "))
        scenarios.append(
            Scenario(
                id=f"catalog-{department}",
                query=f"Danh sách quy trình phòng {label}",
                answer_style="steps",
                expected_department=department,
                expected_blocks=("summary", "table", "sources"),
                tags=("catalog", "department"),
            )
        )

    for record in procedure_records[:28]:
        scenarios.append(
            Scenario(
                id=f"steps-{record.doc_id}",
                query=f"{clean_title(record.title)} ({display_code(record)}) gồm những bước nào?",
                answer_style="steps",
                expected_doc_ids=(record.doc_id,),
                expected_department=record.department,
                expected_blocks_any=("steps", "workflow"),
                tags=("procedure_steps", record.department),
            )
        )

    for record in active[:22]:
        scenarios.append(
            Scenario(
                id=f"direct-{record.doc_id}",
                query=f"Tóm tắt tài liệu {display_code(record)}",
                expected_doc_ids=(record.doc_id,),
                expected_department=record.department,
                expected_blocks=("summary", "sources"),
                tags=("direct_doc", record.department),
            )
        )

    for record in form_records[:16]:
        scenarios.append(
            Scenario(
                id=f"form-{record.doc_id}",
                query=f"Biểu mẫu/hồ sơ {display_code(record)} dùng khi nào?",
                expected_doc_ids=(record.doc_id,),
                expected_department=record.department,
                expected_blocks_any=("form", "summary"),
                tags=("form_lookup", record.department),
            )
        )

    for record in procedure_records[28:40]:
        scenarios.append(
            Scenario(
                id=f"workflow-{record.doc_id}",
                query=f"Vẽ workflow cho {display_code(record)}",
                answer_style="workflow",
                expected_doc_ids=(record.doc_id,),
                expected_department=record.department,
                expected_blocks=("workflow", "sources"),
                tags=("workflow", record.department),
            )
        )

    decision_queries = [
        ("decision-risk-form", "Tôi nên dùng biểu mẫu nào khi phát sinh sự cố vận hành?", ("decision_matrix", "form")),
        ("decision-recruitment", "Khi cần tuyển người mới thì nên dùng tài liệu/quy trình nào?", ("decision_matrix", "table", "summary")),
        ("decision-contract", "Khi ký hợp đồng lao động nên xem quy trình hay biểu mẫu nào?", ("decision_matrix", "form", "summary")),
        ("decision-import", "Khi mua hàng nước ngoài nên đi theo quy trình nào?", ("decision_matrix", "summary")),
        ("decision-label", "Khi cần tạo nhãn phụ thì nên dùng quy trình nào?", ("decision_matrix", "summary")),
        ("decision-complaint", "Khách hàng khiếu nại thì nên tra quy trình nào?", ("decision_matrix", "summary")),
    ]
    for scenario_id, query, any_blocks in decision_queries:
        scenarios.append(
            Scenario(
                id=scenario_id,
                query=query,
                expected_blocks_any=any_blocks,
                tags=("decision",),
            )
        )

    follow_up_sources = procedure_records[40:48]
    for record in follow_up_sources:
        code = display_code(record)
        scenarios.append(
            Scenario(
                id=f"follow-up-{record.doc_id}",
                query="Bước 2 ai phụ trách hoặc phê duyệt?",
                expected_doc_ids=(record.doc_id,),
                expected_blocks_any=("steps", "summary", "listing"),
                prelude=(f"Cho tôi biết các bước chính của {code}",),
                tags=("follow_up", record.department),
            )
        )

    edge_cases = [
        Scenario(
            id="clarify-vague-procedure",
            query="Quy trình này làm sao?",
            expected_action="clarify",
            expected_blocks=("clarification", "form"),
            tags=("clarification",),
        ),
        Scenario(
            id="clarify-vague-document",
            query="Tài liệu này nói gì?",
            expected_action="clarify",
            expected_blocks=("clarification", "form"),
            tags=("clarification",),
        ),
        Scenario(
            id="scope-weather",
            query="Thời tiết hôm nay thế nào?",
            expected_action="scope_reject",
            expected_blocks=("scope_reject",),
            tags=("scope",),
        ),
        Scenario(
            id="scope-joke",
            query="Kể một câu chuyện cười không liên quan tài liệu",
            expected_action="scope_reject",
            expected_blocks=("scope_reject",),
            tags=("scope",),
        ),
        Scenario(
            id="unknown-vendor",
            query="Biến tần E-07 encoder parameter P191 sửa như thế nào?",
            expected_action="no_answer",
            expected_blocks=("scope_reject",),
            tags=("no_source",),
        ),
        Scenario(
            id="unknown-policy",
            query="Quy trình teleport hàng hóa qua kho ảo gồm mấy bước?",
            expected_action="no_answer",
            expected_blocks=("scope_reject",),
            tags=("no_source",),
        ),
    ]
    scenarios.extend(edge_cases)

    return scenarios[:limit]


def run_scenario(
    client: TestClient,
    scenario: Scenario,
    *,
    active_by_key: dict[tuple[str, str], ManifestRecord],
    source_cache: dict[tuple[str, str], str],
    run_id: str,
) -> dict[str, Any]:
    session_id = f"audit-{scenario.id}-{run_id}"
    prelude_results = []
    for index, query in enumerate(scenario.prelude, start=1):
        body = post_chat(client, query, session_id=session_id, answer_style="steps")
        prelude_results.append(
            {
                "index": index,
                "query": query,
                "action": infer_action(body),
                "doc_ids": citation_doc_ids(body),
                "block_types": block_types(body),
            }
        )
    body = post_chat(client, scenario.query, session_id=session_id, answer_style=scenario.answer_style)
    answer_evaluation = evaluate_answer_quality(scenario, body, active_by_key, source_cache)
    failures = validate_scenario(scenario, body, active_by_key) + [
        f"quality: {failure}" for failure in answer_evaluation.get("failures", [])
    ]
    return {
        "id": scenario.id,
        "query": scenario.query,
        "tags": list(scenario.tags),
        "question_meaning": answer_evaluation["question_meaning"],
        "expected_action": scenario.expected_action,
        "action": infer_action(body),
        "passed": not failures,
        "failures": failures,
        "answer_evaluation": answer_evaluation,
        "answer_preview": str(body.get("answer") or body.get("answer_text") or "")[:500],
        "block_types": block_types(body),
        "doc_ids": citation_doc_ids(body),
        "prelude": prelude_results,
    }


def post_chat(client: TestClient, query: str, *, session_id: str, answer_style: str) -> dict[str, Any]:
    response = client.post(
        "/api/user/chat",
        json={
            "query": query,
            "session_id": session_id,
            "answer_style": answer_style,
            "use_llm": False,
        },
    )
    if response.status_code != 200:
        return {"_http_status": response.status_code, "answer": response.text}
    return response.json()


def validate_scenario(
    scenario: Scenario,
    body: dict[str, Any],
    active_by_key: dict[tuple[str, str], ManifestRecord],
) -> list[str]:
    failures: list[str] = []
    if body.get("_http_status"):
        return [f"HTTP {body['_http_status']}"]
    action = infer_action(body)
    if action != scenario.expected_action:
        failures.append(f"expected action {scenario.expected_action}, got {action}")
    if body.get("response_contract_version") != RESPONSE_CONTRACT_VERSION:
        failures.append("missing or invalid response contract version")
    blocks = block_types(body)
    if not blocks:
        failures.append("missing blocks")
    unknown_blocks = sorted(set(blocks) - BLOCK_TYPES)
    if unknown_blocks:
        failures.append(f"unknown blocks {unknown_blocks}")
    for block_type in scenario.expected_blocks:
        if block_type not in blocks:
            failures.append(f"missing block {block_type}")
    if scenario.expected_blocks_any and not set(blocks).intersection(scenario.expected_blocks_any):
        failures.append(f"missing any block from {list(scenario.expected_blocks_any)}")

    answer = str(body.get("answer") or body.get("answer_text") or "")
    if contains_mojibake(answer):
        failures.append("answer contains mojibake markers")
    if contains_raw_markup(answer):
        failures.append("answer contains raw markup")

    citations = body.get("citations") if isinstance(body.get("citations"), list) else []
    doc_ids = citation_doc_ids(body)
    if scenario.expected_action == "answer" and not doc_ids:
        failures.append("answer has no citations")
    for doc_id in scenario.expected_doc_ids:
        if doc_id not in doc_ids:
            failures.append(f"missing expected doc_id {doc_id}")
    for citation in citations:
        if not isinstance(citation, dict):
            failures.append("citation is not an object")
            continue
        doc_id = str(citation.get("doc_id") or "")
        version = str(citation.get("version") or "")
        record = active_by_key.get((doc_id, version))
        if doc_id and version and record is None:
            failures.append(f"citation not active/latest: {doc_id} {version}")
        if scenario.expected_department and record and record.department != scenario.expected_department:
            failures.append(f"citation department {record.department} != {scenario.expected_department}")
    return failures


def evaluate_answer_quality(
    scenario: Scenario,
    body: dict[str, Any],
    active_by_key: dict[tuple[str, str], ManifestRecord],
    source_cache: dict[tuple[str, str], str],
) -> dict[str, Any]:
    question_meaning = infer_question_meaning(scenario)
    action = infer_action(body)
    blocks = block_types(body)
    citations = body.get("citations") if isinstance(body.get("citations"), list) else []
    answer = str(body.get("answer") or body.get("answer_text") or "")
    evidence_text = source_text_for_citations(citations, active_by_key, source_cache)
    expected_doc_ids = set(scenario.expected_doc_ids)
    doc_ids = set(citation_doc_ids(body))

    scores = {
        "intent_alignment": score_intent_alignment(scenario, action, blocks),
        "document_grounding": score_document_grounding(scenario, action, answer, evidence_text),
        "completeness": score_completeness(scenario, action, answer, body),
        "citation_fit": score_citation_fit(scenario, citations, active_by_key),
        "render_fit": score_render_fit(scenario, blocks),
    }
    overall = round(sum(scores[key] * QUALITY_WEIGHTS[key] for key in QUALITY_WEIGHTS), 3)
    failures: list[str] = []
    if scenario.expected_action == "answer":
        if expected_doc_ids and not expected_doc_ids.intersection(doc_ids):
            failures.append("answer does not cite the expected document focus")
        if scores["document_grounding"] < CRITICAL_QUALITY_THRESHOLD:
            failures.append("answer has weak lexical support from cited documents")
        if scores["intent_alignment"] < QUALITY_PASS_THRESHOLD:
            failures.append("answer action/blocks do not match question meaning")
        if scores["completeness"] < QUALITY_PASS_THRESHOLD:
            failures.append("answer is incomplete for the question intent")
    elif action != scenario.expected_action:
        failures.append("non-answer action does not match question meaning")

    quality_pass = not failures and overall >= QUALITY_PASS_THRESHOLD
    if not quality_pass and not failures:
        failures.append(f"overall quality score {overall} below threshold {QUALITY_PASS_THRESHOLD}")

    return {
        "question_meaning": question_meaning,
        "scores": scores,
        "overall_score": overall,
        "quality_pass": quality_pass,
        "evidence_term_overlap": evidence_term_overlap(answer, evidence_text),
        "failures": failures,
    }


def infer_question_meaning(scenario: Scenario) -> dict[str, Any]:
    tags = set(scenario.tags)
    intent = "answer"
    expected_answer_type = "grounded_summary"
    if "catalog" in tags:
        intent = "catalog"
        expected_answer_type = "department_listing"
    elif "procedure_steps" in tags:
        intent = "procedure_steps"
        expected_answer_type = "ordered_steps"
    elif "direct_doc" in tags:
        intent = "document_summary"
        expected_answer_type = "summary"
    elif "form_lookup" in tags:
        intent = "form_lookup"
        expected_answer_type = "form_usage"
    elif "workflow" in tags:
        intent = "workflow"
        expected_answer_type = "workflow"
    elif "decision" in tags:
        intent = "decision_support"
        expected_answer_type = "decision_matrix_or_grounded_recommendation"
    elif "follow_up" in tags:
        intent = "follow_up_role_or_step_detail"
        expected_answer_type = "contextual_answer"
    elif "clarification" in tags:
        intent = "clarification"
        expected_answer_type = "ask_for_missing_context"
    elif "scope" in tags:
        intent = "scope_reject"
        expected_answer_type = "safe_scope_message"
    elif "no_source" in tags:
        intent = "no_answer"
        expected_answer_type = "no_source_message"
    return {
        "intent": intent,
        "expected_answer_type": expected_answer_type,
        "expected_action": scenario.expected_action,
        "focus_doc_ids": list(scenario.expected_doc_ids),
        "focus_department": scenario.expected_department,
        "required_blocks": list(scenario.expected_blocks),
        "required_blocks_any": list(scenario.expected_blocks_any),
        "needs_document_grounding": scenario.expected_action == "answer",
    }


def score_intent_alignment(scenario: Scenario, action: str, blocks: list[str]) -> float:
    score = 1.0 if action == scenario.expected_action else 0.0
    if scenario.expected_blocks:
        present = sum(1 for block_type in scenario.expected_blocks if block_type in blocks)
        score = min(score, present / len(scenario.expected_blocks))
    if scenario.expected_blocks_any and not set(blocks).intersection(scenario.expected_blocks_any):
        score = min(score, 0.35)
    return round(score, 3)


def score_document_grounding(scenario: Scenario, action: str, answer: str, evidence_text: str) -> float:
    if scenario.expected_action != "answer":
        return 1.0 if action == scenario.expected_action else 0.0
    overlap = evidence_term_overlap(answer, evidence_text)
    score = overlap["ratio"]
    if scenario.expected_doc_ids and all(doc_id.lower() in normalized_text(answer) for doc_id in scenario.expected_doc_ids):
        score = max(score, 0.55)
    if "catalog" in scenario.tags and "table" in scenario.expected_blocks:
        score = max(score, 0.78)
    return round(min(1.0, score), 3)


def score_completeness(scenario: Scenario, action: str, answer: str, body: dict[str, Any]) -> float:
    if action != scenario.expected_action:
        return 0.0
    if scenario.expected_action != "answer":
        return 1.0
    blocks = block_types(body)
    normalized = normalized_text(answer)
    score = 0.75
    tags = set(scenario.tags)
    if "catalog" in tags:
        score = 1.0 if "table" in blocks and len(answer) > 120 else 0.5
    elif "procedure_steps" in tags:
        step_count = block_item_count(body, "steps") + block_item_count(body, "workflow")
        score = 1.0 if step_count >= 2 and any(term in normalized for term in ["buoc", "thuc hien"]) else 0.45
    elif "direct_doc" in tags:
        score = 1.0 if "summary" in blocks and len(answer) > 80 else 0.45
    elif "form_lookup" in tags:
        score = (
            1.0
            if "form" in blocks
            and any(term in normalized for term in ["bieu mau", "ho so", "dung khi", "su dung", "ap dung"])
            else 0.5
        )
    elif "workflow" in tags:
        workflow_count = block_item_count(body, "workflow")
        has_limitation_caveat = any(
            term in normalized for term in ["khong du noi dung dang quy trinh", "khong du can cu", "chua du can cu"]
        )
        score = 1.0 if "workflow" in blocks and (workflow_count >= 2 or has_limitation_caveat) else 0.35
    elif "decision" in tags:
        score = 1.0 if {"decision_matrix", "form", "table", "summary"}.intersection(blocks) else 0.45
    elif "follow_up" in tags:
        score = 1.0 if any(term in normalized for term in ["phu trach", "phe duyet", "duyet", "chua thay can cu", "bo phan"]) else 0.55
    return round(score, 3)


def block_item_count(body: dict[str, Any], block_type: str) -> int:
    blocks = body.get("blocks") if isinstance(body.get("blocks"), list) else []
    total = 0
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != block_type:
            continue
        items = block.get("items")
        if isinstance(items, list):
            total += len(items)
        elif block.get("mermaid"):
            total += 2
    return total


def score_citation_fit(
    scenario: Scenario,
    citations: list[Any],
    active_by_key: dict[tuple[str, str], ManifestRecord],
) -> float:
    if scenario.expected_action != "answer":
        return 1.0 if not citations else 0.75
    if not citations:
        return 0.0
    valid = 0
    department_fit = 0
    expected_doc_fit = 0
    expected_docs = set(scenario.expected_doc_ids)
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("doc_id") or "")
        version = str(citation.get("version") or "")
        record = active_by_key.get((doc_id, version))
        if record:
            valid += 1
            if not scenario.expected_department or record.department == scenario.expected_department:
                department_fit += 1
            if doc_id in expected_docs:
                expected_doc_fit += 1
    valid_ratio = valid / len(citations)
    department_ratio = department_fit / valid if valid else 0.0
    if expected_docs:
        expected_ratio = min(1.0, expected_doc_fit / len(expected_docs))
        return round((valid_ratio * 0.35) + (department_ratio * 0.25) + (expected_ratio * 0.40), 3)
    return round((valid_ratio * 0.60) + (department_ratio * 0.40), 3)


def score_render_fit(scenario: Scenario, blocks: list[str]) -> float:
    if scenario.expected_blocks:
        return round(sum(1 for block in scenario.expected_blocks if block in blocks) / len(scenario.expected_blocks), 3)
    if scenario.expected_blocks_any:
        return 1.0 if set(blocks).intersection(scenario.expected_blocks_any) else 0.0
    return 1.0 if blocks else 0.0


def source_text_for_citations(
    citations: list[Any],
    active_by_key: dict[tuple[str, str], ManifestRecord],
    source_cache: dict[tuple[str, str], str],
) -> str:
    parts: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("doc_id") or "")
        version = str(citation.get("version") or "")
        key = (doc_id, version)
        record = active_by_key.get(key)
        citation_text = " ".join(
            str(citation.get(field) or "")
            for field in ["display_code", "doc_id", "title", "excerpt", "matched_excerpt"]
        )
        if record:
            citation_text = f"{citation_text} {record.title} {record.extra.get('display_code') or ''}"
            if key not in source_cache:
                source_cache[key] = read_record_text(record)
            citation_text = f"{citation_text} {source_cache[key]}"
        parts.append(citation_text)
    return "\n".join(parts)


def read_record_text(record: ManifestRecord, max_chars: int = 20_000) -> str:
    path = Path(record.normalized_path)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def evidence_term_overlap(answer: str, evidence_text: str) -> dict[str, Any]:
    answer_terms = content_terms(answer)
    if not answer_terms:
        return {"ratio": 1.0, "supported": [], "unsupported": []}
    evidence_terms = content_terms(evidence_text)
    supported = sorted(answer_terms.intersection(evidence_terms))
    unsupported = sorted(answer_terms - evidence_terms)
    return {
        "ratio": round(len(supported) / len(answer_terms), 3),
        "supported": supported[:30],
        "unsupported": unsupported[:30],
    }


def content_terms(value: object) -> set[str]:
    normalized = normalized_text(value)
    normalized = re.sub(r"\b(?:pd|kt|bm|ms|pl|phu-luc)(?:[- ][a-z0-9.]+){1,5}\b", " ", normalized)
    tokens = re.findall(r"[a-z0-9]{2,}", normalized)
    return {
        token
        for token in tokens
        if token not in TERM_STOPWORDS and not token.isdigit() and len(token) > 2
    }


def quality_rubric() -> dict[str, Any]:
    return {
        "scale": "0.0-1.0",
        "pass_threshold": QUALITY_PASS_THRESHOLD,
        "critical_threshold": CRITICAL_QUALITY_THRESHOLD,
        "weights": QUALITY_WEIGHTS,
        "criteria": {
            "intent_alignment": "Câu trả lời chọn đúng hành động và đúng loại block theo ý nghĩa câu hỏi.",
            "document_grounding": "Các thuật ngữ/nội dung chính trong câu trả lời có căn cứ trong citation hoặc tài liệu được dẫn.",
            "completeness": "Câu trả lời đủ dạng nội dung người hỏi cần: danh sách, bước, biểu mẫu, workflow, quyết định hoặc hỏi lại.",
            "citation_fit": "Citation là bản active/latest, đúng tài liệu/phòng ban trọng tâm khi scenario yêu cầu.",
            "render_fit": "Blocks phù hợp để frontend render đúng kiểu thay vì chỉ markdown tự do.",
        },
    }


def infer_action(body: dict[str, Any]) -> str:
    if body.get("needs_clarification"):
        return "clarify"
    if (body.get("quality_decision") or {}).get("decision") == "scope_reject":
        return "scope_reject"
    if body.get("format_type") == "no_answer_card":
        return "no_answer"
    if body.get("citations"):
        return "answer"
    return "unknown"


def block_types(body: dict[str, Any]) -> list[str]:
    blocks = body.get("blocks")
    if not isinstance(blocks, list):
        return []
    return [str(block.get("type")) for block in blocks if isinstance(block, dict) and block.get("type")]


def citation_doc_ids(body: dict[str, Any]) -> list[str]:
    citations = body.get("citations") if isinstance(body.get("citations"), list) else []
    return [str(item.get("doc_id")) for item in citations if isinstance(item, dict) and item.get("doc_id")]


def display_code(record: ManifestRecord) -> str:
    return str(record.extra.get("display_code") or record.doc_id)


def clean_title(value: object) -> str:
    return clean_excerpt(value, max_chars=120).strip(". ")


def contains_mojibake(value: object) -> bool:
    text = str(value or "")
    return repair_mojibake(text) != text


def contains_raw_markup(value: object) -> bool:
    normalized = normalized_text(value)
    return any(marker in normalized for marker in ["<table", "<tr", "<td", "<img", "rowspan", "colspan", "src="])


def summarize_failures(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        for failure in result.get("failures") or []:
            key = re.sub(r"'.*?'", "?", str(failure))
            summary[key] = summary.get(key, 0) + 1
    return dict(sorted(summary.items(), key=lambda item: (-item[1], item[0])))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit 100 user-chat document contexts.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--limit", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_user_chat_scenario_audit(args.root, limit=args.limit)
    print(json.dumps({"pass": report["pass"], "passed": report["passed"], "failed": report["failed"]}, ensure_ascii=False))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
