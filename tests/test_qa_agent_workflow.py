from __future__ import annotations

import json

from poc_workflow.chatbot import NO_SOURCE_ANSWER
from poc_workflow import qa_agent_workflow as qa


class FakeLLM:
    def __init__(self, config) -> None:
        self.config = config

    def complete_messages(self, messages, **kwargs) -> str:
        system = str(messages[0]["content"]).lower()
        if "query analyzer" in system:
            return json.dumps(
                {
                    "intent": "catalog/list_procedure",
                    "entities": {"department": "technical"},
                    "missing_context": [],
                    "out_of_scope": False,
                    "confidence": "high",
                    "rationale": "catalog request",
                }
            )
        if "retrieval plan" in system:
            return json.dumps(
                {
                    "queries": [
                        "danh sach quy trinh phong ky thuat",
                        "catalog procedure technical active",
                        "SOP phong ky thuat quy trinh hien hanh",
                    ],
                    "required_evidence": "active procedure catalog",
                    "top_k": 40,
                }
            )
        if "evidence extraction module" in system:
            return json.dumps(
                {
                    "verified_evidence": [
                        {
                            "claim": "Phong Ky thuat co 3 quy trinh hien hanh.",
                            "doc_id": "KT-QT-215",
                            "version": "1.0",
                            "evidence_type": "procedure_catalog",
                            "citation": "chunk-1",
                            "confidence": 0.96,
                        }
                    ],
                    "missing_evidence": [],
                    "conflicts": [],
                }
            )
        if "response format planner" in system:
            return json.dumps(
                {
                    "primary_format": "table",
                    "secondary_blocks": ["sources"],
                    "render_hints": {
                        "show_timeline": False,
                        "show_checklist_button": False,
                        "show_mermaid_button": False,
                    },
                }
            )
        if "internal procedure assistant" in system:
            return json.dumps(
                {
                    "answer_type": "table",
                    "title": "Danh sach quy trinh Phong Ky thuat",
                    "summary": "Phong Ky thuat co 3 quy trinh hien hanh.",
                    "steps": [],
                    "responsibilities": [],
                    "forms_records": [],
                    "notes": [],
                    "sources": [{"doc_id": "KT-QT-215", "version": "1.0", "title": "Danh sach SOP"}],
                    "markdown": (
                        "Tom tat:\n"
                        "Phong Ky thuat co 3 quy trinh hien hanh.\n\n"
                        "| Ma | Ten | Phien ban | Trang thai |\n"
                        "| --- | --- | --- | --- |\n"
                        "| KT-QT-215 | Danh sach SOP | 1.0 | active |\n\n"
                        "Nguon:\nKT-QT-215 v1.0"
                    ),
                }
            )
        if "answer verification module" in system:
            return json.dumps({"passed": True, "issues": [], "final_action": "render", "rationale": "schema ok"})
        if "citation critic" in system:
            return json.dumps({"decision": "pass", "rationale": "citations visible", "issues": []})
        if "procedure compliance checker" in system:
            return json.dumps(
                {
                    "procedure_compliance": "passed",
                    "final_decision": "release",
                    "must_fix": [],
                    "nice_to_have": [],
                    "citation_coverage": 1.0,
                    "rationale": "procedure answer has citation and active source",
                }
            )
        return "{}"


def test_qa_agent_workflow_runs_multi_step_pipeline(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeRAGFlow:
        def __init__(self, base_url: str, api_key: str) -> None:
            calls.append({"init": (base_url, api_key)})

        def retrieve_chunks(self, dataset_ids, question, **kwargs):
            calls.append({"dataset_ids": dataset_ids, "question": question, "kwargs": kwargs})
            return {
                "code": 0,
                "data": {
                    "chunks": [
                        {
                            "id": "chunk-1",
                            "document_name": "Danh sach SOP",
                            "dataset_id": dataset_ids[0],
                            "content": "Phong Ky thuat co 3 quy trinh hien hanh trong KT-QT-215.",
                            "similarity": 0.94,
                            "document_metadata": {
                                "doc_id": "KT-QT-215",
                                "version": "1.0",
                                "display_code": "PD-IC-A-001",
                                "display_version": "Rev 10",
                                "category": "procedure",
                                "status": "active",
                                "source_role": "primary",
                            },
                        }
                    ]
                },
            }

    monkeypatch.setenv("POC_LLM_API_KEY", "test-key")
    monkeypatch.setenv("POC_LLM_MODEL", "test-model")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://ragflow.local")
    monkeypatch.setenv("RAGFLOW_API_KEY", "ragflow-key")
    monkeypatch.setenv("RAGFLOW_DATASET_ALLOWLIST", "dataset-a,dataset-b")
    monkeypatch.setattr(qa, "OpenAICompatibleClient", FakeLLM)
    monkeypatch.setattr(qa, "RAGFlowHTTPClient", FakeRAGFlow)

    events: list[dict[str, object]] = []
    result = qa.run_qa_agent_workflow(
        tmp_path,
        "cac quy trinh cua phong ky thuat",
        answer_style="steps",
        emit=events.append,
    )

    assert result["answer_source"] == "qa_agent_llm"
    assert result["format_type"] == "table"
    assert result["format_plan"]["primary_format"] == "table"
    assert result["structured_answer"]["answer_type"] == "table"
    assert "Ma | Ten | Phien ban | Trang thai" in result["structured_answer"]["markdown"]
    assert result["quality_decision"]["decision"] == "pass"
    assert result["procedure_compliance"]["final_decision"] == "release"
    assert result["answer_run"]["stage"] == "finalized"
    assert result["answer_run"]["answer_quality_status"] == "passed"
    assert result["evidence_summary"]["claim_count"] == 1
    assert result["evidence_pack"]["verified_evidence"][0]["claim"] == "Phong Ky thuat co 3 quy trinh hien hanh."
    assert result["citations"][0]["doc_id"] == "KT-QT-215"
    assert {step["id"] for step in result["trace_steps"]} >= {
        "analysis_result",
        "scope_guard",
        "context_check",
        "retrieval_plan",
        "retrieve",
        "evidence",
        "format_plan",
        "answer_verification",
        "critic",
        "procedure_compliance",
        "format",
    }
    retrieval_calls = [call for call in calls if "question" in call]
    assert len(retrieval_calls) >= 3
    assert retrieval_calls[0]["dataset_ids"] == ["dataset-a", "dataset-b"]
    assert retrieval_calls[0]["kwargs"]["top_k"] == 40
    assert retrieval_calls[0]["kwargs"]["metadata_condition"]["conditions"][0]["value"] == "active"
    assert any(event.get("event") == "trace" for event in events)


def test_qa_agent_workflow_fails_closed_without_llm_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(qa, "resolve_llm_config", lambda root: None)

    result = qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")

    assert result["answer"] == NO_SOURCE_ANSWER
    assert result["fallback_reason"] == "llm_not_configured"
    assert result["quality_decision"]["decision"] == "fail"
    assert result["format_type"] == "no_answer_card"
    assert result["format_plan"]["primary_format"] == "no_answer_card"
    assert result["structured_answer"]["answer_type"] == "no_answer"
    assert result["citations"] == []


def test_scope_guard_rejects_out_of_scope_without_llm(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(qa, "resolve_llm_config", lambda root: None)

    result = qa.run_qa_agent_workflow(tmp_path, "luong thuong phong ky thuat nam nay bao nhieu")

    assert result["answer_source"] == "scope_guard"
    assert result["fallback_reason"] == "out_of_scope"
    assert result["format_type"] == "no_answer_card"
    assert result["structured_answer"]["answer_type"] == "no_answer"
    assert result["llm_used"] is False

    unrelated = qa.run_qa_agent_workflow(tmp_path, "thoi tiet hom nay the nao")
    assert unrelated["answer_source"] == "scope_guard"
    assert unrelated["fallback_reason"] == "out_of_scope"
    assert unrelated["quality_decision"]["decision"] == "scope_reject"
    assert unrelated["structured_answer"]["answer_type"] == "no_answer"


def test_analyzer_planner_and_critic_guardrails() -> None:
    analysis = qa.deterministic_analysis("cac quy trinh cua phong ky thuat", [], "brief")
    assert analysis["intent"] == "catalog/list_procedure"
    assert analysis["entities"]["department"] == "technical"

    missing = qa.deterministic_analysis("quy trinh nay", [], "brief")
    assert missing["missing_context"] == ["document_or_procedure_name"]

    out_of_scope = qa.deterministic_analysis("luong thuong phong ky thuat", [], "brief")
    assert out_of_scope["out_of_scope"] is True

    variants = qa.query_variants("cac quy trinh cua phong ky thuat", analysis)
    assert "danh sach quy trinh phong ky thuat" in variants
    assert qa.normalize_bool("false") is False
    assert qa.normalize_string_list("department") == ["department"]
    assert qa.normalize_top_k("bad") == 40
    assert qa.normalize_top_k(500) == 80
    assert qa.normalize_final_decision("revise_with_more_retrieval") == "retrieve_more"

    conflict_chunks = [
        qa.EvidenceChunk("c1", "KT-QT-001", "1.0", "A", "noi dung", 0.9),
        qa.EvidenceChunk("c2", "KT-QT-001", "2.0", "A", "noi dung moi", 0.8),
    ]
    assert qa.detect_conflicts(conflict_chunks)
    assert qa.deterministic_critic("Tra loi khong co nguon", conflict_chunks)["decision"] == "retrieve_more"
    assert qa.deterministic_critic("Nguon KT-QT-001", conflict_chunks)["decision"] == "pass"
    evidence_pack = qa.deterministic_evidence_pack(conflict_chunks, {"required_evidence": ["steps"]})
    assert evidence_pack["verified_evidence"][0]["doc_id"] == "KT-QT-001"
    compliance = qa.deterministic_procedure_compliance("Nguon KT-QT-001", evidence_pack)
    assert compliance["final_decision"] == "retrieve_more"
