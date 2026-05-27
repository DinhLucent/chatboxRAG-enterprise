from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import qa_agent_workflow as qa
from .llm import OpenAICompatibleConfig
from .utils import utc_now, write_json


QA_AGENT_EVAL_JSON = Path("data") / "qa_agent_eval" / "latest.json"
QA_AGENT_EVAL_MARKDOWN = Path("docs") / "qa-agent-eval-latest.md"


@dataclass
class QAAgentEvalCase:
    id: str
    query: str
    answer_style: str = "brief"
    should_answer: bool = True
    expected_format_type: str | None = None
    expected_quality_decision: str | None = None
    expected_fallback_reason: str | None = None
    min_citations: int = 0
    required_trace_ids: list[str] = field(default_factory=list)
    required_answer_terms: list[str] = field(default_factory=list)
    forbidden_answer_terms: list[str] = field(default_factory=list)
    conversation_context: dict[str, Any] = field(default_factory=dict)


CONTRACT_CASES = [
    QAAgentEvalCase(
        id="catalog_procedures",
        query="cac quy trinh cua phong ky thuat",
        answer_style="steps",
        should_answer=True,
        expected_format_type="table",
        expected_quality_decision="pass",
        min_citations=1,
        required_trace_ids=["scope_guard", "retrieval_plan", "retrieve", "evidence", "critic", "format"],
        required_answer_terms=["Phong Ky thuat", "KT-QT-215"],
    ),
    QAAgentEvalCase(
        id="procedure_detail",
        query="quy trinh bao tri may nen gom nhung buoc nao",
        answer_style="steps",
        should_answer=True,
        expected_format_type="step_by_step",
        expected_quality_decision="pass",
        min_citations=1,
        required_trace_ids=["analysis_result", "retrieval_plan", "evidence", "procedure_compliance", "format"],
        required_answer_terms=["Tiep nhan", "Kiem tra"],
    ),
    QAAgentEvalCase(
        id="follow_up_context",
        query="Trong quy trinh bao tri may nen, buoc 2 ai phu trach?",
        answer_style="brief",
        should_answer=True,
        expected_format_type="bullet_responsibility",
        expected_quality_decision="pass",
        min_citations=1,
        required_trace_ids=["context_check", "analysis_result", "format"],
        required_answer_terms=["Truong phong Ky thuat"],
        conversation_context={
            "context_used": True,
            "active_doc_id": "KT-QT-CTX",
            "active_topic": "Quy trinh bao tri may nen",
            "active_display_code": "PD-TECH-A-02",
        },
    ),
    QAAgentEvalCase(
        id="workflow_visual",
        query="ve workflow bao tri may nen",
        answer_style="workflow",
        should_answer=True,
        expected_format_type="mermaid",
        expected_quality_decision="pass",
        min_citations=1,
        required_trace_ids=["format_plan", "procedure_compliance", "format"],
        required_answer_terms=["Tiep nhan", "Kiem tra"],
    ),
    QAAgentEvalCase(
        id="no_active_source",
        query="quy trinh khong ton tai trong phong ky thuat",
        answer_style="brief",
        should_answer=False,
        expected_format_type="no_answer_card",
        expected_quality_decision="fail",
        expected_fallback_reason="no_active_source",
        min_citations=0,
        required_trace_ids=["retrieval_plan", "retrieve", "final"],
    ),
    QAAgentEvalCase(
        id="out_of_scope",
        query="thoi tiet hom nay the nao",
        answer_style="brief",
        should_answer=False,
        expected_format_type="no_answer_card",
        expected_quality_decision="scope_reject",
        expected_fallback_reason="out_of_scope",
        min_citations=0,
        required_trace_ids=["scope_guard"],
        forbidden_answer_terms=["mua ao", "du bao"],
    ),
]


def run_qa_agent_eval(root: Path, *, mode: str = "contract", write_report: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if mode not in {"contract", "live"}:
        raise ValueError("mode must be contract or live")
    started_at = utc_now()
    if mode == "contract":
        results = run_contract_cases(root)
    else:
        results = [evaluate_case(root, case) for case in CONTRACT_CASES]
    report = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "mode": mode,
        "metrics": summarize_results(results),
        "results": results,
    }
    report["pass"] = bool(report["metrics"]["passed_cases"] == report["metrics"]["total_cases"])
    if write_report:
        write_qa_agent_eval_reports(root, report)
    return report


def run_contract_cases(root: Path) -> list[dict[str, Any]]:
    original_llm = qa.OpenAICompatibleClient
    original_ragflow = qa.RAGFlowHTTPClient
    original_resolve_llm = qa.resolve_llm_config
    original_env = {key: os.environ.get(key) for key in CONTRACT_ENV}
    try:
        os.environ.update(CONTRACT_ENV)
        qa.OpenAICompatibleClient = ContractLLM  # type: ignore[assignment]
        qa.RAGFlowHTTPClient = ContractRAGFlow  # type: ignore[assignment]
        qa.resolve_llm_config = lambda root=None: OpenAICompatibleConfig(
            api_key="contract-key",
            model="contract-model",
            base_url="http://contract-llm.local/v1",
            provider="contract",
        )
        return [evaluate_case(root, case) for case in CONTRACT_CASES]
    finally:
        qa.OpenAICompatibleClient = original_llm
        qa.RAGFlowHTTPClient = original_ragflow
        qa.resolve_llm_config = original_resolve_llm
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


CONTRACT_ENV = {
    "RAGFLOW_BASE_URL": "http://contract-ragflow.local",
    "RAGFLOW_API_KEY": "contract-ragflow-key",
    "RAGFLOW_DATASET_ALLOWLIST": "technical-active-contract",
    "KB_QA_AGENT_LATENCY_BUDGET_MS": "20000",
}


class ContractLLM:
    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config

    def complete_messages(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        system = str(messages[0]["content"]).lower()
        payload = parse_message_payload(messages[-1].get("content", ""))
        query = str(payload.get("question") or payload.get("query") or "").lower()
        if "query analysis" in system or "query analyzer" in system:
            return json.dumps(contract_analysis(query), ensure_ascii=False)
        if "retrieval plan" in system:
            return json.dumps(contract_retrieval_plan(query), ensure_ascii=False)
        if "evidence extraction module" in system:
            return json.dumps(contract_evidence(payload), ensure_ascii=False)
        if "response format planner" in system:
            return json.dumps(contract_format_plan(query, payload), ensure_ascii=False)
        if "internal procedure assistant" in system:
            return json.dumps(contract_answer(query, payload), ensure_ascii=False)
        if "answer verification module" in system:
            return json.dumps({"passed": True, "issues": [], "final_action": "render", "rationale": "contract schema ok"})
        if "citation critic" in system:
            return json.dumps({"decision": "pass", "rationale": "contract evidence supports answer", "issues": []})
        if "procedure compliance checker" in system:
            return json.dumps(
                {
                    "procedure_compliance": "passed",
                    "final_decision": "release",
                    "must_fix": [],
                    "nice_to_have": [],
                    "citation_coverage": 1.0,
                    "rationale": "contract procedure answer has source anchors",
                },
                ensure_ascii=False,
            )
        return "{}"


class ContractRAGFlow:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def retrieve_chunks(self, dataset_ids: list[str], question: str, **kwargs: Any) -> dict[str, Any]:
        normalized = qa.normalized_text(question)
        if "khong ton tai" in normalized or "missing procedure" in normalized:
            return {"code": 0, "data": {"chunks": []}}
        if "bao tri" in normalized or "pd-tech-a-02" in normalized or "buoc 2" in normalized or "workflow" in normalized:
            return {"code": 0, "data": {"chunks": [procedure_chunk(dataset_ids[0])]}}
        return {"code": 0, "data": {"chunks": [catalog_chunk(dataset_ids[0])]}}


def catalog_chunk(dataset_id: str) -> dict[str, Any]:
    return {
        "id": "catalog-chunk-1",
        "document_name": "Danh sach SOP",
        "dataset_id": dataset_id,
        "content": "Phong Ky thuat co 3 quy trinh hien hanh: lap dat, sua chua, bao tri. Ma danh muc KT-QT-215.",
        "similarity": 0.96,
        "document_metadata": {
            "doc_id": "KT-QT-215",
            "version": "1.0",
            "display_code": "PD-IC-A-001",
            "display_version": "Rev 10",
            "category": "procedure",
            "status": "active",
            "source_role": "primary",
            "anchor_id": "catalog-chunk-1",
        },
    }


def procedure_chunk(dataset_id: str) -> dict[str, Any]:
    return {
        "id": "procedure-chunk-1",
        "document_name": "Quy trinh bao tri may nen",
        "dataset_id": dataset_id,
        "content": (
            "KT-QT-CTX quy dinh buoc 1 Tiep nhan yeu cau bao tri. "
            "Buoc 2 Kiem tra ap suat va lap bien ban do Truong phong Ky thuat phu trach phe duyet. "
            "Buoc 3 Luu ho so bao tri vao kho ho so ky thuat."
        ),
        "similarity": 0.95,
        "document_metadata": {
            "doc_id": "KT-QT-CTX",
            "version": "1.0",
            "display_code": "PD-TECH-A-02",
            "display_version": "Rev 04",
            "category": "procedure",
            "status": "active",
            "source_role": "primary",
            "anchor_id": "procedure-chunk-1",
        },
    }


def parse_message_payload(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def contract_analysis(query: str) -> dict[str, Any]:
    if "khong ton tai" in query:
        return {
            "intent": "ask_procedure",
            "entities": {"department": "technical"},
            "missing_context": [],
            "out_of_scope": False,
            "confidence": "medium",
        }
    if "buoc 2" in query:
        return {
            "intent": "ask_responsibility",
            "entities": {"department": "technical", "document": "KT-QT-CTX", "step_no": 2},
            "missing_context": [],
            "out_of_scope": False,
            "confidence": "high",
        }
    if "bao tri" in query or "workflow" in query:
        return {
            "intent": "ask_procedure",
            "entities": {"department": "technical", "document": "KT-QT-CTX"},
            "missing_context": [],
            "out_of_scope": False,
            "confidence": "high",
        }
    return {
        "intent": "catalog/list_procedure",
        "entities": {"department": "technical"},
        "missing_context": [],
        "out_of_scope": False,
        "confidence": "high",
    }


def contract_retrieval_plan(query: str) -> dict[str, Any]:
    if "khong ton tai" in query:
        queries = ["quy trinh khong ton tai phong ky thuat", "missing procedure active source"]
        required = ["procedure_steps", "latest_version"]
    elif "bao tri" in query or "buoc 2" in query or "workflow" in query:
        queries = ["quy trinh bao tri may nen", "PD-TECH-A-02 buoc 2 phu trach", "ho so bao tri may nen"]
        required = ["procedure_steps", "responsibility", "forms_records", "latest_version"]
    else:
        queries = ["danh sach quy trinh phong ky thuat", "catalog SOP phong ky thuat", "procedure catalog technical active"]
        required = ["procedure_catalog", "latest_version", "active_status"]
    return {"queries": queries, "required_evidence": required, "top_k": 40}


def contract_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    chunks = payload.get("retrieved_chunks") if isinstance(payload.get("retrieved_chunks"), list) else []
    if not chunks:
        return {"verified_evidence": [], "missing_evidence": ["no_active_source"], "conflicts": []}
    first = chunks[0]
    doc_id = str(first.get("doc_id") or "")
    citation = "procedure-chunk-1" if doc_id == "KT-QT-CTX" else "catalog-chunk-1"
    if doc_id == "KT-QT-CTX":
        claim = "Buoc 2 do Truong phong Ky thuat phu trach phe duyet trong quy trinh bao tri may nen."
        evidence_type = "procedure_steps"
    else:
        claim = "Phong Ky thuat co 3 quy trinh hien hanh trong danh muc KT-QT-215."
        evidence_type = "procedure_catalog"
    return {
        "verified_evidence": [
            {
                "claim": claim,
                "doc_id": doc_id,
                "version": str(first.get("version") or "1.0"),
                "title": str(first.get("title") or doc_id),
                "evidence_type": evidence_type,
                "citation": citation,
                "confidence": 0.96,
            }
        ],
        "missing_evidence": [],
        "conflicts": [],
    }


def contract_format_plan(query: str, payload: dict[str, Any]) -> dict[str, Any]:
    answer_style = str(payload.get("answer_style") or "")
    if answer_style == "workflow" or "workflow" in query:
        primary = "mermaid"
        hints = {"show_timeline": True, "show_checklist_button": False, "show_mermaid_button": True}
        blocks = ["procedure_steps", "sources"]
    elif "buoc 2" in query:
        primary = "bullet_responsibility"
        hints = {"show_timeline": False, "show_checklist_button": False, "show_mermaid_button": False}
        blocks = ["responsibility", "sources"]
    elif "bao tri" in query:
        primary = "step_by_step"
        hints = {"show_timeline": True, "show_checklist_button": True, "show_mermaid_button": False}
        blocks = ["forms_records", "sources"]
    else:
        primary = "table"
        hints = {"show_timeline": False, "show_checklist_button": False, "show_mermaid_button": False}
        blocks = ["sources"]
    return {"primary_format": primary, "secondary_blocks": blocks, "render_hints": hints}


def contract_answer(query: str, payload: dict[str, Any]) -> dict[str, Any]:
    format_plan = payload.get("format_plan") if isinstance(payload.get("format_plan"), dict) else {}
    primary = str(format_plan.get("primary_format") or "summary")
    if primary == "table":
        return {
            "answer_type": "table",
            "title": "Danh sach quy trinh Phong Ky thuat",
            "summary": "Phong Ky thuat co 3 quy trinh hien hanh.",
            "steps": [],
            "responsibilities": [],
            "forms_records": [],
            "notes": [],
            "sources": [{"doc_id": "KT-QT-215", "version": "1.0", "display_code": "PD-IC-A-001", "title": "Danh sach SOP"}],
            "markdown": (
                "Tom tat:\nPhong Ky thuat co 3 quy trinh hien hanh.\n\n"
                "| Ma | Ten | Trang thai |\n"
                "| --- | --- | --- |\n"
                "| KT-QT-215 | Lap dat / Sua chua / Bao tri | active |\n\n"
                "Nguon:\nKT-QT-215 v1.0"
            ),
        }
    steps = [
        {
            "step_no": 1,
            "title": "Tiep nhan yeu cau",
            "description": "Tiep nhan yeu cau bao tri may nen.",
            "owner": "Nhan vien Ky thuat",
            "source_anchor": "procedure-chunk-1",
        },
        {
            "step_no": 2,
            "title": "Kiem tra va lap bien ban",
            "description": "Kiem tra ap suat, lap bien ban va trinh Truong phong Ky thuat phe duyet.",
            "owner": "Truong phong Ky thuat",
            "source_anchor": "procedure-chunk-1",
        },
        {
            "step_no": 3,
            "title": "Luu ho so",
            "description": "Luu ho so bao tri vao kho ho so ky thuat.",
            "owner": "Phong Ky thuat",
            "source_anchor": "procedure-chunk-1",
        },
    ]
    return {
        "answer_type": primary,
        "title": "Quy trinh bao tri may nen",
        "summary": "Quy trinh bao tri may nen gom 3 buoc chinh.",
        "steps": steps,
        "responsibilities": [
            {"label": "Buoc 2", "detail": "Truong phong Ky thuat phu trach phe duyet.", "source_anchor": "procedure-chunk-1"}
        ],
        "forms_records": [{"label": "Bien ban bao tri", "detail": "Lap va luu sau buoc kiem tra.", "source_anchor": "procedure-chunk-1"}],
        "notes": [],
        "sources": [{"doc_id": "KT-QT-CTX", "version": "1.0", "display_code": "PD-TECH-A-02", "title": "Quy trinh bao tri may nen"}],
        "markdown": "",
    }


def evaluate_case(root: Path, case: QAAgentEvalCase) -> dict[str, Any]:
    result = qa.run_qa_agent_workflow(
        root,
        case.query,
        answer_style=case.answer_style,
        conversation_context=case.conversation_context,
    )
    answer = str(result.get("answer") or "")
    citations = [item for item in result.get("citations") or [] if isinstance(item, dict)]
    trace_ids = [str(step.get("id") or "") for step in result.get("trace_steps") or [] if isinstance(step, dict)]
    structured = result.get("structured_answer") if isinstance(result.get("structured_answer"), dict) else {}
    quality = result.get("quality_decision") if isinstance(result.get("quality_decision"), dict) else {}
    checks = {
        "answer_presence_ok": bool(answer) and (bool(citations) if case.should_answer else not citations),
        "citation_count_ok": len(citations) >= case.min_citations,
        "format_ok": case.expected_format_type is None or result.get("format_type") == case.expected_format_type,
        "quality_decision_ok": case.expected_quality_decision is None or quality.get("decision") == case.expected_quality_decision,
        "fallback_reason_ok": case.expected_fallback_reason is None or result.get("fallback_reason") == case.expected_fallback_reason,
        "trace_ok": all(trace_id in trace_ids for trace_id in case.required_trace_ids),
        "structured_payload_ok": structured_payload_ok(result),
        "answer_terms_ok": terms_present(answer, case.required_answer_terms),
        "forbidden_terms_ok": terms_absent(answer, case.forbidden_answer_terms),
    }
    return {
        "id": case.id,
        "query": case.query,
        "answer_style": case.answer_style,
        "should_answer": case.should_answer,
        "format_type": result.get("format_type"),
        "quality_decision": quality.get("decision"),
        "fallback_reason": result.get("fallback_reason"),
        "citation_count": len(citations),
        "trace_ids": trace_ids,
        "structured_answer_type": structured.get("answer_type"),
        "knowledge_gap_expected": not case.should_answer,
        "checks": checks,
        "pass": all(checks.values()),
    }


def structured_payload_ok(result: dict[str, Any]) -> bool:
    format_type = str(result.get("format_type") or "")
    structured = result.get("structured_answer") if isinstance(result.get("structured_answer"), dict) else {}
    format_plan = result.get("format_plan") if isinstance(result.get("format_plan"), dict) else {}
    if not format_type or not format_plan.get("primary_format") or not structured.get("answer_type"):
        return False
    if format_type == "table":
        return bool(structured.get("markdown") or structured.get("forms_records"))
    if format_type in {"step_by_step", "checklist", "mermaid", "timeline", "bullet_responsibility"}:
        return bool(structured.get("steps") or structured.get("responsibilities"))
    if format_type == "no_answer_card":
        return structured.get("answer_type") == "no_answer" and bool(structured.get("summary"))
    return True


def terms_present(value: str, terms: list[str]) -> bool:
    normalized = qa.normalized_text(value)
    return all(qa.normalized_text(term) in normalized for term in terms)


def terms_absent(value: str, terms: list[str]) -> bool:
    normalized = qa.normalized_text(value)
    return all(qa.normalized_text(term) not in normalized for term in terms)


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.get("pass"))
    failed_checks: dict[str, int] = {}
    for result in results:
        for check, ok in result.get("checks", {}).items():
            if not ok:
                failed_checks[check] = failed_checks.get(check, 0) + 1
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "pass_rate": passed / total if total else None,
        "failed_checks": failed_checks,
    }


def write_qa_agent_eval_reports(root: Path, report: dict[str, Any]) -> None:
    write_json(root / QA_AGENT_EVAL_JSON, report)
    lines = [
        "# QA Agent Eval Latest",
        "",
        f"- Mode: {report.get('mode')}",
        f"- Status: {'pass' if report.get('pass') else 'fail'}",
        f"- Cases: {report['metrics']['passed_cases']}/{report['metrics']['total_cases']}",
        "",
        "| Case | Format | Decision | Citations | Status |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for result in report["results"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(result.get("id")),
                    markdown_cell(result.get("format_type")),
                    markdown_cell(result.get("quality_decision")),
                    str(result.get("citation_count") or 0),
                    "pass" if result.get("pass") else "fail",
                ]
            )
            + " |"
        )
    if report["metrics"].get("failed_checks"):
        lines.extend(["", "## Failed Checks", ""])
        for check, count in sorted(report["metrics"]["failed_checks"].items()):
            lines.append(f"- `{check}`: {count}")
    (root / QA_AGENT_EVAL_MARKDOWN).parent.mkdir(parents=True, exist_ok=True)
    (root / QA_AGENT_EVAL_MARKDOWN).write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()
