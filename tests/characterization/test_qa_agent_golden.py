"""Characterization (golden) tests for qa_agent_workflow.

Spec: ``.kiro/specs/complex-code-decomposition`` — Task 4.1.
Requirements: 1.4 (order-insensitive citation set), 3.1, 3.2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from poc_workflow.chatbot import NO_SOURCE_ANSWER
from poc_workflow import qa_agent_workflow as qa
from tests.characterization import golden_answer, assert_equivalent

class ConfigurableFakeLLM:
    def __init__(self, config: Any) -> None:
        self.config = config
        self.analyzer_response: dict[str, Any] = {
            "intent": "catalog/list_procedure",
            "entities": {"department": "technical"},
            "missing_context": [],
            "out_of_scope": False,
            "confidence": "high",
            "rationale": "catalog request",
        }
        self.planner_response: dict[str, Any] = {
            "queries": ["danh sach quy trinh phong ky thuat"],
            "required_evidence": "active procedure catalog",
            "top_k": 40,
        }
        self.extractor_response: dict[str, Any] = {
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
        self.format_planner_response: dict[str, Any] = {
            "primary_format": "table",
            "secondary_blocks": ["sources"],
            "render_hints": {
                "show_timeline": False,
                "show_checklist_button": False,
                "show_mermaid_button": False,
            },
        }
        self.assistant_response: dict[str, Any] = {
            "answer_type": "table",
            "title": "Danh sach quy trinh Phong Ky thuat",
            "summary": "Phong Ky thuat co 3 quy trinh hien hanh.",
            "steps": [],
            "responsibilities": [],
            "forms_records": [],
            "notes": [],
            "sources": [{"doc_id": "KT-QT-215", "version": "1.0", "title": "Danh sach SOP"}],
            "markdown": "Tom tat:\nPhong Ky thuat co 3 quy trinh hien hanh.\n\nNguon:\nKT-QT-215 v1.0",
        }
        self.verification_response: dict[str, Any] = {"passed": True, "issues": [], "final_action": "render", "rationale": "schema ok"}
        self.critic_response: dict[str, Any] = {"decision": "pass", "rationale": "citations visible", "issues": []}
        self.compliance_response: dict[str, Any] = {
            "procedure_compliance": "passed",
            "final_decision": "release",
            "must_fix": [],
            "nice_to_have": [],
            "citation_coverage": 1.0,
            "rationale": "procedure answer has citation and active source",
        }

    def complete_messages(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        system = str(messages[0]["content"]).lower()
        if "query analyzer" in system:
            return json.dumps(self.analyzer_response)
        if "retrieval plan" in system:
            return json.dumps(self.planner_response)
        if "evidence extraction module" in system:
            return json.dumps(self.extractor_response)
        if "response format planner" in system:
            return json.dumps(self.format_planner_response)
        if "internal procedure assistant" in system:
            return json.dumps(self.assistant_response)
        if "answer verification module" in system:
            return json.dumps(self.verification_response)
        if "citation critic" in system:
            return json.dumps(self.critic_response)
        if "procedure compliance checker" in system:
            return json.dumps(self.compliance_response)
        return "{}"

class FakeRAGFlow:
    def __init__(self, base_url: str, api_key: str) -> None:
        pass

    def retrieve_chunks(self, dataset_ids: list[str], question: str, **kwargs: Any) -> dict[str, Any]:
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

@pytest.fixture
def qa_agent_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigurableFakeLLM:
    monkeypatch.setenv("POC_LLM_API_KEY", "test-key")
    monkeypatch.setenv("POC_LLM_MODEL", "test-model")
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://ragflow.local")
    monkeypatch.setenv("RAGFLOW_API_KEY", "ragflow-key")
    monkeypatch.setenv("RAGFLOW_DATASET_ALLOWLIST", "dataset-a,dataset-b")
    
    fake_llm = ConfigurableFakeLLM(None)
    monkeypatch.setattr(qa, "OpenAICompatibleClient", lambda config: fake_llm)
    monkeypatch.setattr(qa, "RAGFlowHTTPClient", FakeRAGFlow)
    return fake_llm

def test_qa_agent_success_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # Golden run for successful QA Agent Workflow
    def run() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat", answer_style="steps")

    before = golden_answer(run, order_sensitive=False)
    # Re-run to verify equivalence (which checks answer text and citation set)
    after = golden_answer(run, order_sensitive=False)
    assert_equivalent(before, after)

def test_qa_agent_out_of_scope_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # 1. Scope rejection from scope_guard (no LLM run)
    def run_unrelated() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "thoi tiet hom nay the nao")
        
    before = golden_answer(run_unrelated, order_sensitive=False)
    assert before.raw["answer_source"] == "scope_guard"
    assert before.raw["fallback_reason"] == "out_of_scope"
    assert before.raw["answer"] == "Nội dung này nằm ngoài phạm vi chatbot quy trình Phương Đông. Tôi chỉ có thể hỗ trợ các câu hỏi dựa trên tài liệu quy trình đang hiệu lực."
    
    # 2. Scope rejection from LLM analyzer
    qa_agent_env.analyzer_response = {
        "intent": "unrelated",
        "entities": {},
        "missing_context": [],
        "out_of_scope": True,
        "confidence": "high",
    }
    
    def run_llm_out_of_scope() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "quy trinh tinh luong")
        
    before_llm = golden_answer(run_llm_out_of_scope, order_sensitive=False)
    assert before_llm.raw["answer_source"] == "no_answer"
    assert before_llm.raw["fallback_reason"] == "out_of_scope"
    assert before_llm.answer == NO_SOURCE_ANSWER

def test_qa_agent_missing_context_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # Missing context / clarification required path
    qa_agent_env.analyzer_response = {
        "intent": "procedure/detail",
        "entities": {},
        "missing_context": ["document_or_procedure_name"],
        "out_of_scope": False,
        "confidence": "high",
    }
    
    def run_missing() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "quy trinh nay can gi")
        
    before = golden_answer(run_missing, order_sensitive=False)
    assert before.raw["answer_source"] == "clarification"
    assert before.raw["fallback_reason"] == "missing_context"
    assert before.raw["needs_clarification"] is True
    assert "Ban bo sung them thong tin giup minh nhe" in before.answer

def test_qa_agent_llm_disabled_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # LLM disabled golden run
    def run_disabled() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat", use_llm=False)
        
    before = golden_answer(run_disabled, order_sensitive=False)
    assert before.answer == NO_SOURCE_ANSWER
    assert before.raw["fallback_reason"] == "llm_disabled"

def test_qa_agent_llm_not_configured_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # LLM not configured golden run
    monkeypatch.setattr(qa, "resolve_llm_config", lambda root: None)
    
    def run_unconfigured() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_unconfigured, order_sensitive=False)
    assert before.answer == NO_SOURCE_ANSWER
    assert before.raw["fallback_reason"] == "llm_not_configured"

def test_qa_agent_ragflow_not_configured_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # RAGFlow not configured path, fall back to local_index (or failed if qa_agent_require_ragflow is true)
    monkeypatch.setenv("POC_LLM_API_KEY", "test-key")
    monkeypatch.setenv("POC_LLM_MODEL", "test-model")
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    
    fake_llm = ConfigurableFakeLLM(None)
    monkeypatch.setattr(qa, "OpenAICompatibleClient", lambda config: fake_llm)
    
    # Enable qa_agent_require_ragflow mock to return True to trigger the ragflow_not_configured failure
    monkeypatch.setattr(qa, "qa_agent_require_ragflow", lambda: True)
    
    def run_ragflow_unconfigured() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_ragflow_unconfigured, order_sensitive=False)
    assert before.answer == NO_SOURCE_ANSWER
    assert before.raw["fallback_reason"] == "ragflow_not_configured"

def test_qa_agent_latency_budget_exceeded_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    # Latency budget exceeded path
    monkeypatch.setattr(qa, "qa_agent_latency_budget_ms", lambda: -1) # Set budget to negative to guarantee timeout
    
    def run_timeout() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_timeout, order_sensitive=False)
    assert before.answer == NO_SOURCE_ANSWER
    assert before.raw["fallback_reason"] == "latency_budget_exceeded"

def test_qa_agent_verify_failed_clarify_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # Verification fails and triggers needs_clarification
    qa_agent_env.verification_response = {
        "passed": False,
        "final_action": "needs_clarification",
        "clarifying_question": "Hãy làm rõ thêm",
        "issues": ["ambiguity"],
    }
    
    def run_verify_clarify() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_verify_clarify, order_sensitive=False)
    assert before.raw["answer_source"] == "clarification"
    assert before.raw["fallback_reason"] == "answer_verification_needs_clarification"

def test_qa_agent_verify_failed_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # Verification fails completely
    qa_agent_env.verification_response = {
        "passed": False,
        "final_action": "fail",
        "rationale": "verification failed",
        "issues": ["bad schema"],
    }
    
    def run_verify_fail() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_verify_fail, order_sensitive=False)
    assert before.answer == NO_SOURCE_ANSWER
    assert before.raw["fallback_reason"] == "answer_verification_failed"

def test_qa_agent_critic_failed_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # Critic fails/rejects
    qa_agent_env.critic_response = {
        "decision": "fail",
        "reason": "insufficient_evidence",
        "issues": ["no citations"],
    }
    
    def run_critic_fail() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_critic_fail, order_sensitive=False)
    assert before.answer == NO_SOURCE_ANSWER
    assert before.raw["fallback_reason"] == "insufficient_evidence"

def test_qa_agent_compliance_failed_clarify_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # Compliance checker returns needs_clarification
    qa_agent_env.compliance_response = {
        "procedure_compliance": "failed",
        "final_decision": "needs_clarification",
        "clarifying_question": "Cần làm rõ quy trình",
    }
    
    def run_compliance_clarify() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_compliance_clarify, order_sensitive=False)
    assert before.raw["answer_source"] == "clarification"
    assert before.raw["fallback_reason"] == "procedure_clarification_required"

def test_qa_agent_compliance_failed_golden(tmp_path: Path, qa_agent_env: ConfigurableFakeLLM) -> None:
    # Compliance checker fails/rejects
    qa_agent_env.compliance_response = {
        "procedure_compliance": "failed",
        "final_decision": "fail",
        "rationale": "non-compliant",
    }
    
    def run_compliance_fail() -> dict[str, Any]:
        return qa.run_qa_agent_workflow(tmp_path, "cac quy trinh cua phong ky thuat")
        
    before = golden_answer(run_compliance_fail, order_sensitive=False)
    assert before.answer == NO_SOURCE_ANSWER
    assert before.raw["fallback_reason"] == "procedure_compliance_failed"
