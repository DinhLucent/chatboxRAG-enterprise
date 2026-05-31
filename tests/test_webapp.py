from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import poc_workflow.webapp as webapp_module
from poc_workflow.chatbot import NO_SOURCE_ANSWER
from poc_workflow.database import QualityDatabase
from poc_workflow.pipeline import approve_record, process_sources
from poc_workflow.text_cleaning import normalized_text
from poc_workflow.webapp import create_app


def write_source(root: Path) -> None:
    path = root / "source" / "technical" / "procedure" / "KT-QT-010_v1.0.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Quy trinh nghiem thu\n\nCan kiem tra checklist, ky bien ban va luu ho so.",
        encoding="utf-8",
    )
    path.with_name(path.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-QT-010",
                "title": "Quy trinh nghiem thu",
                "department": "technical",
                "category": "procedure",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2025-01-01",
                "review_at": "2025-12-31",
                "owner": "Phong Ky thuat",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_context_source(root: Path) -> None:
    path = root / "source" / "technical" / "procedure" / "KT-QT-CTX_v1.0.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "# Quy trinh bao tri may nen\n\n"
            "Buoc 1: Tiep nhan yeu cau bao tri may nen.\n\n"
            "Buoc 2: Kiem tra ap suat, lap bien ban va trinh Truong phong Ky thuat duyet.\n\n"
            "Buoc 3: Luu ho so bao tri vao kho ho so ky thuat."
        ),
        encoding="utf-8",
    )
    path.with_name(path.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-QT-CTX",
                "title": "Quy trinh bao tri may nen",
                "department": "technical",
                "category": "procedure",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2025-01-01",
                "review_at": "2025-12-31",
                "owner": "Phong Ky thuat",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_catalog_source(root: Path) -> None:
    path = root / "source" / "technical" / "procedure" / "KT-QT-215_v1.0.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "# Danh sach SOP\n\n"
            "| TT | Loại tài liệu | Mã số | Tên tài liệu | Tình trạng | Ghi chú |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| VII | Kỹ thuật |  |  |  |  |\n"
            "| 36 | Quy trình |  | Quy trình lắp đặt máy móc, thiết bị | Đã có bản draff |  |\n"
            "| 37 | Quy trình |  | Quy trình Sửa chữa máy móc, thiết bị | Đã có bản draff |  |\n"
            "| 38 | Quy trình |  | Quy trình bảo dưỡng thiết bị | Đã có bản draff |  |\n"
            "| VIII | APP |  |  |  |  |\n"
        ),
        encoding="utf-8",
    )
    path.with_name(path.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-QT-215",
                "title": "PD IC A 001 Rev 10. Quy trình kiểm soát tài liệu, hồ sơ",
                "department": "technical",
                "category": "procedure",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2026-03-16",
                "review_at": "2027-03-16",
                "owner": "Phong Ky thuat",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def clear_user_chat_queue_state() -> None:
    with webapp_module.USER_CHAT_RATE_LOCK:
        webapp_module.USER_CHAT_ACTIVE_KEYS.clear()
        webapp_module.USER_CHAT_LAST_FINISHED_AT.clear()


def test_web_health_manifest_and_chat(tmp_path: Path) -> None:
    write_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-010", "1.0", "Lead")
    client = TestClient(create_app(tmp_path))

    index = client.get("/")
    assert index.status_code == 200
    assert 'id="view-chat"' in index.text

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["manifest"]["active"] == 1

    manifest = client.get("/api/manifest")
    assert manifest.status_code == 200
    assert manifest.json()[0]["doc_id"] == "KT-QT-010"

    detail = client.get("/api/documents/KT-QT-010/1.0")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["record"]["doc_id"] == "KT-QT-010"
    assert detail_body["record"]["status"] == "active"
    assert detail_body["metadata_sidecar"]["exists"] is True
    assert detail_body["metadata_sidecar"]["data"]["category"] == "procedure"
    assert detail_body["markdown"]["exists"] is True
    assert "Quy trinh nghiem thu" in detail_body["markdown"]["content"]
    assert detail_body["markdown"]["quality"]["characters"] > 20
    assert detail_body["source_preview"]["exists"] is True
    assert detail_body["source_preview"]["kind"] == "text"
    assert detail_body["source_preview"]["file_url"] == "/api/documents/KT-QT-010/1.0/source-file"
    assert "Quy trinh nghiem thu" in detail_body["source_preview"]["text"]["content"]
    assert detail_body["qa_report"]["exists"] is True
    assert detail_body["qa_report"]["data"]["status"] == "pass"
    assert detail_body["canonical_key"]
    assert isinstance(detail_body["related_records"], list)
    assert any(warning["code"] == "short_markdown" for warning in detail_body["warnings"])

    missing_detail = client.get("/api/documents/NOPE/1.0")
    assert missing_detail.status_code == 404

    source_file = client.get("/api/documents/KT-QT-010/1.0/source-file")
    assert source_file.status_code == 200
    assert b"Quy trinh nghiem thu" in source_file.content

    chat = client.post(
        "/api/chat",
        json={"query": "quy trinh nghiem thu can gi", "provider": "local"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["provider"] == "local"
    assert body["citations"]
    citation = body["citations"][0]
    assert citation["chunk_id"]
    assert citation["anchor_id"]
    assert citation["line_start"] >= 1
    assert citation["line_end"] >= citation["line_start"]

    citation_detail = client.get(
        f"/api/documents/{citation['doc_id']}/{citation['version']}/citation/{citation['anchor_id']}"
    )
    assert citation_detail.status_code == 200
    citation_body = citation_detail.json()
    assert citation_body["citation"]["anchor_id"] == citation["anchor_id"]
    assert citation_body["citation_preview"]["highlight_line_start"] == citation["line_start"]
    assert any(line["highlight"] for line in citation_body["citation_preview"]["lines"])

    legacy_detail = client.get(
        f"/api/documents/{citation['doc_id']}/{citation['version']}/citation",
        params={"excerpt": "Can kiem tra checklist"},
    )
    assert legacy_detail.status_code == 200
    legacy_body = legacy_detail.json()
    assert legacy_body["citation"]["locator_status"] == "approximate"
    assert legacy_body["citation"]["chunk_id"] is None
    assert any(line["highlight"] for line in legacy_body["citation_preview"]["lines"])

    feedback = client.post(
        "/api/feedback",
        json={"query_log_id": body["query_log_id"], "feedback": "wrong_source"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["knowledge_gap_id"]


def test_user_chat_app_public_api_safe_citations_policy_and_feedback(tmp_path: Path) -> None:
    write_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-010", "1.0", "Lead")
    client = TestClient(create_app(tmp_path))

    page = client.get("/chat")
    assert page.status_code == 200
    assert "sourceDrawer" in page.text
    assert "Tôi có thể giúp gì cho bạn hôm nay?" in page.text
    assert "Policy" not in page.text
    assert "Liên quan" not in page.text
    assert "Pin" not in page.text

    bootstrap = client.get("/api/user/bootstrap")
    assert bootstrap.status_code == 200
    boot = bootstrap.json()
    assert boot["ui"]["default_drawer_tab"] == "sources"
    assert boot["ui"]["show_policy_debug"] is False
    assert {style["id"] for style in boot["answer_styles"]} == {"brief", "steps", "checklist", "workflow"}
    assert [card["label"] for card in boot["welcome_cards"]] == [
        "Quy trình Phương Đông",
        "Biểu mẫu & Hồ sơ",
        "Xử lý sự cố",
        "Tài liệu kỹ thuật",
    ]
    assert "policy_id" not in boot["policy"]
    assert {group["id"] for group in boot["templates"]["groups"]} == {
        "procedure",
        "form_checklist",
        "incident",
        "vendor_document",
    }

    chat = client.post(
        "/api/user/chat",
        json={
            "query": "quy trinh nghiem thu checklist can gi",
            "template_id": "procedure_steps",
            "answer_style": "checklist",
            "session_id": "session-user-test",
            "use_llm": False,
        },
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["citations"]
    citation_text = json.dumps(body["citations"], ensure_ascii=False)
    assert "source_path" not in citation_text
    assert "normalized_path" not in citation_text
    assert str(tmp_path) not in citation_text
    assert set(body["citations"][0]) == {
        "title",
        "doc_id",
        "version",
        "display_code",
        "display_version",
        "excerpt",
        "anchor_id",
    }
    assert "score" not in citation_text
    assert "chunk" not in citation_text
    assert "provider" not in json.dumps(body.get("trace", {}), ensure_ascii=False)
    assert "policy_version" not in json.dumps(body.get("trace", {}), ensure_ascii=False)
    assert body["trace"]["source_count"] == len(body["citations"])
    public_text = json.dumps(body, ensure_ascii=False)
    assert "answer_source" not in body
    assert "llm_used" not in body
    assert "llm_error" not in body
    assert "fallback_reason" not in body
    assert "provider timeout" not in public_text
    assert body["trace_steps"]
    assert body["answer_style"] == "checklist"
    assert body["answer_text"] == body["answer"]
    assert body["confidence"] == "high"
    assert body["response_contract_version"] == "answer_blocks.v1"
    assert body["block_plan"]["checklist"]["enabled"] is True
    assert any(block["type"] == "checklist" for block in body["blocks"])
    assert "Tóm tắt:" in body["answer"]
    assert "Các bước / Nội dung chính:" in body["answer"]
    assert "Nguồn:" in body["answer"]

    public_citation = body["citations"][0]
    public_detail = client.get(
        f"/api/user/documents/{public_citation['doc_id']}/{public_citation['version']}/citation/{public_citation['anchor_id']}"
    )
    assert public_detail.status_code == 200
    public_body = public_detail.json()
    public_text = json.dumps(public_body, ensure_ascii=False)
    assert str(tmp_path) not in public_text
    assert "source_path" not in public_text
    assert "normalized_path" not in public_text
    assert "chunk_id" not in public_text
    assert "category" not in public_body["record"]
    assert public_body["record"]["doc_id"] == public_citation["doc_id"]
    assert public_body["source_file"]["exists"] is True
    assert public_body["source_file"]["download_url"] == (
        f"/api/user/documents/{public_citation['doc_id']}/{public_citation['version']}/source-file"
    )
    assert "path" not in public_body["source_file"]
    assert any(line["highlight"] for line in public_body["preview"]["lines"])

    public_source = client.get(
        f"/api/user/documents/{public_citation['doc_id']}/{public_citation['version']}/source-file"
    )
    assert public_source.status_code == 200
    assert b"Quy trinh nghiem thu" in public_source.content

    public_legacy_detail = client.get(
        f"/api/user/documents/{public_citation['doc_id']}/{public_citation['version']}/citation",
        params={"excerpt": public_citation["excerpt"]},
    )
    assert public_legacy_detail.status_code == 200
    public_legacy_body = public_legacy_detail.json()
    assert public_legacy_body["citation"]["locator_status"] == "approximate"
    assert "chunk_id" not in json.dumps(public_legacy_body, ensure_ascii=False)
    assert any(line["highlight"] for line in public_legacy_body["preview"]["lines"])

    queries = client.get("/api/queries")
    assert queries.status_code == 200
    latest = queries.json()[0]
    assert latest["session_id"] == "session-user-test"
    assert latest["template_id"] == "procedure_steps"
    assert latest["policy_id"] == "production-user-chat"
    assert latest["policy_version"]

    feedback = client.post(
        "/api/user/feedback",
        json={"log_id": body["log_id"], "rating": "missing_source", "session_id": "session-user-test"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["knowledge_gap_id"]


def test_public_source_file_prefers_supporting_pdf_for_user_verification(tmp_path: Path) -> None:
    write_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-010", "1.0", "Lead")

    pdf_path = tmp_path / "source" / "technical" / "procedure" / "KT-QT-010_original.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\noriginal pdf evidence\n%%EOF")
    records_path = tmp_path / "manifest" / "records.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    records[0].setdefault("extra", {})
    records[0]["extra"].update(
        {
            "primary_source_type": "xlsx",
            "primary_source_path": records[0]["source_path"],
            "supporting_sources": [
                {
                    "type": "pdf",
                    "path": str(pdf_path),
                    "role": "display_print_version",
                    "used_for_retrieval": False,
                }
            ],
        }
    )
    records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    client = TestClient(create_app(tmp_path))
    citation_detail = client.get(
        "/api/user/documents/KT-QT-010/1.0/citation",
        params={"excerpt": "Can kiem tra checklist"},
    )
    assert citation_detail.status_code == 200
    assert citation_detail.json()["source_file"]["kind"] == "pdf"
    assert citation_detail.json()["source_file"]["file_name"] == "KT-QT-010_original.pdf"
    assert "path" not in citation_detail.json()["source_file"]

    source_file = client.get("/api/user/documents/KT-QT-010/1.0/source-file")
    assert source_file.status_code == 200
    assert source_file.content == b"%PDF-1.4\noriginal pdf evidence\n%%EOF"
    assert "KT-QT-010_original.pdf" in source_file.headers["content-disposition"]


def test_user_bootstrap_exposes_qa_agent_flags(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KB_QA_AGENT_WORKFLOW_ENABLED", "true")
    monkeypatch.setenv("KB_QA_AGENT_STREAMING_ENABLED", "true")
    monkeypatch.setenv("KB_USER_CHAT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("KB_USER_CHAT_COOLDOWN_SECONDS", "15")
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/user/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["qa_agent"] == {
        "enabled": True,
        "streaming": True,
        "trace_visibility": "detailed_safe_rationale",
    }
    assert body["queue"]["enabled"] is True
    assert body["queue"]["mode"] == "sequential"
    assert body["queue"]["cooldown_seconds"] == 15


def test_user_chat_queue_cooldown_rejects_same_session(tmp_path: Path, monkeypatch) -> None:
    clear_user_chat_queue_state()
    monkeypatch.setenv("KB_USER_CHAT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("KB_USER_CHAT_COOLDOWN_SECONDS", "15")
    monkeypatch.setenv("KB_USER_CHAT_QUEUE_MAX_WAIT_SECONDS", "1")

    def fake_user_chat_response(*args, **kwargs):
        return {"answer": "ok", "citations": [], "trace_steps": [], "query_log_id": 1}

    monkeypatch.setattr(webapp_module, "user_chat_response", fake_user_chat_response)
    client = TestClient(webapp_module.create_app(tmp_path))

    first = client.post(
        "/api/user/chat",
        json={"query": "quy trinh lap dat", "session_id": "queue-session", "use_llm": False},
    )
    assert first.status_code == 200
    assert first.json()["queue"]["enabled"] is True
    assert first.json()["queue"]["mode"] == "sequential"

    second = client.post(
        "/api/user/chat",
        json={"query": "quy trinh bao duong", "session_id": "queue-session", "use_llm": False},
    )
    assert second.status_code == 429
    assert second.headers["retry-after"] == "15"


def test_user_chat_queue_serializes_different_sessions(monkeypatch) -> None:
    clear_user_chat_queue_state()
    monkeypatch.setenv("KB_USER_CHAT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("KB_USER_CHAT_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("KB_USER_CHAT_QUEUE_MAX_WAIT_SECONDS", "1")
    first_payload = webapp_module.UserChatRequest(query="q1", session_id="queue-a")
    second_payload = webapp_module.UserChatRequest(query="q2", session_id="queue-b")

    first_ticket = webapp_module.acquire_user_chat_queue_ticket(first_payload)
    acquired = threading.Event()
    released = threading.Event()

    def acquire_second() -> None:
        second_ticket = webapp_module.acquire_user_chat_queue_ticket(second_payload)
        acquired.set()
        webapp_module.release_user_chat_queue_ticket(second_ticket)
        released.set()

    thread = threading.Thread(target=acquire_second)
    thread.start()
    time.sleep(0.05)
    assert not acquired.is_set()

    webapp_module.release_user_chat_queue_ticket(first_ticket)
    assert acquired.wait(1)
    assert released.wait(1)
    thread.join(timeout=1)


def test_user_chat_qa_agent_scope_reject_preserves_safe_reply(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KB_QA_AGENT_WORKFLOW_ENABLED", "true")
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/user/chat",
        json={"query": "thoi tiet hom nay the nao", "session_id": "scope-reject-session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "ngoai pham vi" in normalized_text(body["answer"])
    assert body["format_type"] == "no_answer_card"
    assert body["response_contract_version"] == "answer_blocks.v1"
    assert body["format_plan"]["primary_format"] == "no_answer_card"
    assert body["block_plan"]["scope_reject"]["enabled"] is True
    assert body["structured_answer"]["answer_type"] == "no_answer"
    assert body["blocks"][0]["type"] == "scope_reject"
    assert body["quality_decision"]["decision"] == "scope_reject"
    assert body["knowledge_gap_id"]
    assert body["citations"] == []


def test_user_chat_scope_guard_runs_without_qa_agent_flag(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/user/chat",
        json={"query": "thoi tiet hom nay the nao", "session_id": "scope-default-session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == body["answer"]
    assert body["confidence"] == "low"
    assert body["format_type"] == "no_answer_card"
    assert body["blocks"][0]["type"] == "scope_reject"
    assert body["quality_decision"]["decision"] == "scope_reject"
    assert body["citations"] == []
    assert "ngoai pham vi" in normalized_text(body["answer"])


def test_user_chat_qa_agent_flag_on_returns_public_payload(tmp_path: Path, monkeypatch) -> None:
    from poc_workflow import user_chat as user_chat_module

    def fake_workflow(root, query, **kwargs):
        return {
            "answer": "Tom tat:\nPhong Ky thuat co 3 quy trinh.\n\nNguon:\nKT-QT-215 v1.0",
            "citations": [
                {
                    "title": "Danh sach SOP",
                    "doc_id": "KT-QT-215",
                    "version": "1.0",
                    "display_code": "PD-IC-A-001",
                    "display_version": "Rev 10",
                    "excerpt": "Phong Ky thuat co 3 quy trinh.",
                    "anchor_id": "chunk-1",
                    "status": "active",
                    "score": 0.93,
                }
            ],
            "trace_steps": [
                {
                    "id": "retrieval_plan",
                    "label": "Ke hoach truy xuat",
                    "status": "done",
                    "detail": "3 query tren 1 dataset allowlist.",
                    "metadata": {
                        "queries": ["danh sach quy trinh phong ky thuat"],
                        "datasets": ["dataset-a"],
                        "filters": ["status=active"],
                    },
                }
            ],
            "evidence_summary": {"selected_chunks": 1, "doc_ids": ["KT-QT-215"]},
            "quality_decision": {"decision": "pass", "rationale": "ok"},
            "procedure_compliance": {
                "procedure_compliance": "passed",
                "final_decision": "release",
                "citation_coverage": 1.0,
            },
            "format_type": "table",
            "format_plan": {
                "primary_format": "table",
                "secondary_blocks": ["sources"],
                "render_hints": {"show_timeline": False},
            },
            "structured_answer": {
                "answer_type": "table",
                "title": "Danh sach SOP",
                "summary": "Phong Ky thuat co 3 quy trinh.",
                "steps": [],
                "responsibilities": [],
                "forms_records": [],
                "notes": [],
                "sources": [{"doc_id": "KT-QT-215", "version": "1.0", "title": "Danh sach SOP"}],
                "markdown": "| Ma | Ten |\n| --- | --- |\n| KT-QT-215 | Danh sach SOP |",
            },
            "evidence_pack": {
                "verified_evidence": [
                    {
                        "claim": "Phong Ky thuat co 3 quy trinh.",
                        "doc_id": "KT-QT-215",
                        "version": "1.0",
                        "citation": "chunk-1",
                        "confidence": 0.95,
                    }
                ],
                "missing_evidence": [],
                "conflicts": [],
            },
            "answer_run": {
                "answer_run_id": "run_test_payload",
                "user_question": query,
                "intent": "catalog/list_procedure",
                "stage": "finalized",
                "retrieval_round": 1,
                "revision_round": 1,
                "answer_quality_status": "passed",
                "evidence_status": "sufficient",
                "citations_required": True,
                "final_confidence": 0.95,
            },
            "answer_source": "qa_agent_llm",
            "fallback_reason": None,
            "latency_ms": 42,
            "llm_used": True,
            "llm_error": None,
            "llm_provider": "custom",
            "llm_model": "test-model",
            "needs_clarification": False,
        }

    monkeypatch.setenv("KB_QA_AGENT_WORKFLOW_ENABLED", "true")
    monkeypatch.setattr(user_chat_module, "run_qa_agent_workflow", fake_workflow)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/user/chat",
        json={"query": "cac quy trinh cua phong ky thuat", "session_id": "qa-agent-session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_text"] == body["answer"]
    assert body["confidence"] == "high"
    assert body["citations"][0]["doc_id"] == "KT-QT-215"
    assert set(body["citations"][0]) == {
        "title",
        "doc_id",
        "version",
        "display_code",
        "display_version",
        "excerpt",
        "anchor_id",
        "score",
    }
    assert body["format_type"] == "table"
    assert body["quality_decision"]["decision"] == "pass"
    assert body["procedure_compliance"]["final_decision"] == "release"
    assert body["format_plan"]["primary_format"] == "table"
    assert body["response_contract_version"] == "answer_blocks.v1"
    assert body["block_plan"]["table"]["enabled"] is True
    assert any(block["type"] == "table" for block in body["blocks"])
    assert body["structured_answer"]["title"] == "Danh sach SOP"
    assert body["answer_run"]["stage"] == "finalized"
    assert body["evidence_pack"]["verified_evidence"][0]["doc_id"] == "KT-QT-215"
    assert body["evidence_summary"]["selected_chunks"] == 1
    assert body["trace_steps"][0]["metadata"]["queries"] == ["danh sach quy trinh phong ky thuat"]
    assert "answer_source" not in body
    assert "llm_error" not in body
    with QualityDatabase(tmp_path).connect() as conn:
        row = conn.execute("SELECT * FROM answer_runs WHERE answer_run_id = ?", ("run_test_payload",)).fetchone()
        assert row is not None
        assert row["stage"] == "finalized"
    context = QualityDatabase(tmp_path).user_chat_context("qa-agent-session")
    assert context["active_doc_id"] == "KT-QT-215"
    assert context["last_answer_style"] == "brief"


def test_user_chat_stream_emits_trace_then_final(tmp_path: Path, monkeypatch) -> None:
    from poc_workflow import user_chat as user_chat_module

    def fake_workflow(root, query, **kwargs):
        emit = kwargs.get("emit")
        trace_steps = [
            {
                "id": "analyze",
                "label": "Phan tich cau hoi",
                "status": "done",
                "detail": "Intent catalog/list_procedure.",
                "metadata": {"confidence": "high"},
            },
            {
                "id": "critic",
                "label": "Kiem dinh cau tra loi",
                "status": "done",
                "detail": "pass",
                "metadata": {"quality_decision": {"decision": "pass"}},
            },
        ]
        if emit:
            emit({"event": "trace", "step": trace_steps[0], "trace_steps": trace_steps[:1]})
            emit({"event": "trace", "step": trace_steps[1], "trace_steps": trace_steps})
        return {
            "answer": "Tom tat:\nCo can cu.\n\nNguon:\nKT-QT-215 v1.0",
            "citations": [
                {
                    "title": "Danh sach SOP",
                    "doc_id": "KT-QT-215",
                    "version": "1.0",
                    "excerpt": "Co can cu.",
                    "anchor_id": "chunk-1",
                    "status": "active",
                }
            ],
            "trace_steps": trace_steps,
            "evidence_summary": {"selected_chunks": 1},
            "quality_decision": {"decision": "pass"},
            "procedure_compliance": {
                "procedure_compliance": "passed",
                "final_decision": "release",
                "citation_coverage": 1.0,
            },
            "format_type": "markdown",
            "format_plan": {
                "primary_format": "summary",
                "secondary_blocks": ["sources"],
                "render_hints": {},
            },
            "structured_answer": {
                "answer_type": "summary",
                "title": "Can cu",
                "summary": "Co can cu.",
                "steps": [],
                "responsibilities": [],
                "forms_records": [],
                "notes": [],
                "sources": [{"doc_id": "KT-QT-215", "version": "1.0", "title": "Danh sach SOP"}],
            },
            "evidence_pack": {
                "verified_evidence": [
                    {
                        "claim": "Co can cu.",
                        "doc_id": "KT-QT-215",
                        "version": "1.0",
                        "citation": "chunk-1",
                        "confidence": 0.92,
                    }
                ],
                "missing_evidence": [],
                "conflicts": [],
            },
            "answer_run": {
                "answer_run_id": "run_stream_payload",
                "user_question": query,
                "intent": "catalog/list_procedure",
                "stage": "finalized",
                "retrieval_round": 1,
                "revision_round": 1,
                "answer_quality_status": "passed",
                "evidence_status": "sufficient",
                "citations_required": True,
                "final_confidence": 0.92,
            },
            "answer_source": "qa_agent_llm",
            "fallback_reason": None,
            "latency_ms": 12,
            "llm_used": True,
            "llm_error": None,
            "llm_provider": "custom",
            "llm_model": "test-model",
            "needs_clarification": False,
        }

    monkeypatch.setenv("KB_QA_AGENT_WORKFLOW_ENABLED", "true")
    monkeypatch.setenv("KB_QA_AGENT_STREAMING_ENABLED", "true")
    monkeypatch.setattr(user_chat_module, "run_qa_agent_workflow", fake_workflow)
    client = TestClient(create_app(tmp_path))

    with client.stream(
        "POST",
        "/api/user/chat/stream",
        json={"query": "cac quy trinh cua phong ky thuat", "session_id": "stream-session"},
    ) as response:
        text = response.read().decode("utf-8")

    assert response.status_code == 200
    assert text.count("event: trace") == 2
    assert "event: final" in text
    assert "quality_decision" in text
    assert "answer_source" not in text


def test_user_chat_rejects_unknown_template_and_no_answer_trace(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    unknown_template = client.post(
        "/api/user/chat",
        json={"query": "quy trinh khong ton tai", "template_id": "missing-template"},
    )
    assert unknown_template.status_code == 400
    assert "Unknown template_id" in unknown_template.json()["detail"]

    no_answer = client.post(
        "/api/user/chat",
        json={"query": "quy trinh khong ton tai", "session_id": "session-no-answer", "use_llm": False},
    )
    assert no_answer.status_code == 200
    body = no_answer.json()
    assert body["answer"] == NO_SOURCE_ANSWER
    assert body["citations"] == []
    assert body["trace"]["source_count"] == 0
    assert "no_answer_reason" not in body["trace"]

    clarification = client.post(
        "/api/user/chat",
        json={
            "query": "Quy trình này gồm những bước nào?",
            "session_id": "session-clarification",
            "use_llm": False,
        },
    )
    assert clarification.status_code == 200
    clarify_body = clarification.json()
    assert clarify_body["needs_clarification"] is True
    assert clarify_body["response_contract_version"] == "answer_blocks.v1"
    assert clarify_body["block_plan"]["clarification"]["enabled"] is True
    assert clarify_body["blocks"][0]["type"] == "clarification"
    assert clarify_body["answer"] != NO_SOURCE_ANSWER
    assert "mã hoặc tên tài liệu" in clarify_body["answer"]
    assert clarify_body["citations"] == []
    assert clarify_body["trace"]["source_count"] == 0


def test_user_chat_asks_for_context_when_question_is_ambiguous(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/user/chat",
        json={
            "query": "Quy trình này gồm những bước nào?",
            "session_id": "clarify-session",
            "use_llm": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["needs_clarification"] is True
    assert body["response_contract_version"] == "answer_blocks.v1"
    assert body["block_plan"]["clarification"]["enabled"] is True
    assert body["blocks"][0]["type"] == "clarification"
    assert body["citations"] == []
    assert "mã hoặc tên tài liệu" in body["answer"]
    assert "Không tìm thấy căn cứ" not in body["answer"]
    assert any("Cần thêm" in step["detail"] for step in body["trace_steps"])


def test_user_chat_keeps_context_for_follow_up_questions(tmp_path: Path) -> None:
    write_context_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-CTX", "1.0", "Lead")
    client = TestClient(create_app(tmp_path))

    first = client.post(
        "/api/user/chat",
        json={
            "query": "quy trinh bao tri may nen gom nhung gi",
            "session_id": "context-session",
            "device_id": "device-a",
            "use_llm": False,
        },
    )
    assert first.status_code == 200
    assert first.json()["citations"]
    assert first.json()["trace"]["context"]["context_used"] is False

    follow_up = client.post(
        "/api/user/chat",
        json={
            "query": "buoc 2 ai duyet",
            "session_id": "context-session",
            "device_id": "device-a",
            "use_llm": False,
        },
    )
    assert follow_up.status_code == 200
    body = follow_up.json()
    assert body["citations"]
    assert body["citations"][0]["doc_id"] == "KT-QT-CTX"
    assert body["trace"]["context"]["context_used"] is True
    assert body["trace"]["context"]["turns_used"] == 1

    latest_query = client.get("/api/queries").json()[0]
    assert latest_query["query"] == "buoc 2 ai duyet"
    assert latest_query["session_id"] == "context-session"

    turns = QualityDatabase(tmp_path).recent_user_chat_turns("context-session")
    assert len(turns) == 2
    assert "Boi canh hoi thoai" in turns[-1]["effective_query"]

    deictic_follow_up = client.post(
        "/api/user/chat",
        json={
            "query": "quy trinh nay gom nhung buoc nao",
            "session_id": "context-session",
            "device_id": "device-a",
            "use_llm": False,
        },
    )
    assert deictic_follow_up.status_code == 200
    deictic_body = deictic_follow_up.json()
    assert deictic_body["needs_clarification"] is False
    assert deictic_body["answer_style"] == "steps"
    assert deictic_body["citations"]
    assert deictic_body["citations"][0]["doc_id"] == "KT-QT-CTX"
    assert deictic_body["trace"]["context"]["context_used"] is True

    unrelated = client.post(
        "/api/user/chat",
        json={
            "query": "Bien tan E-07 encoder parameter P191 cach sua nhu the nao?",
            "session_id": "context-session",
            "device_id": "device-a",
            "use_llm": False,
        },
    )
    assert unrelated.status_code == 200
    unrelated_body = unrelated.json()
    assert "phạm vi" in unrelated_body["answer"].lower() or unrelated_body["answer"] == NO_SOURCE_ANSWER
    assert unrelated_body["citations"] == []
    assert unrelated_body["trace"]["context"]["context_used"] is False


def test_user_chat_infers_workflow_style_and_returns_mermaid(tmp_path: Path) -> None:
    write_context_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-CTX", "1.0", "Lead")
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/user/chat",
        json={
            "query": "Flow quy trinh bao tri may nen tu tiep nhan den luu ho so",
            "answer_style": "brief",
            "session_id": "workflow-session",
            "use_llm": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_style"] == "workflow"
    assert body["citations"][0]["doc_id"] == "KT-QT-CTX"
    assert "Workflow:" in body["answer"]
    assert "```mermaid" in body["answer"]
    assert "flowchart TD" in body["answer"]
    assert "KT-QT-CTX v1.0" in body["answer"]
    assert any(step["id"] == "verify_answer" and step["status"] == "done" for step in body["trace_steps"])


def test_user_chat_lists_technical_department_procedures_from_active_catalog(tmp_path: Path) -> None:
    write_catalog_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-215", "1.0", "Lead")
    client = TestClient(create_app(tmp_path))

    queries = [
        "cac quy trinh cua phong ky thuat",
        "Quy trình phòng kỹ thuật có bao nhiêu tài liệu?",
        "Có bao nhiêu tài liệu quy trình kỹ thuật?",
    ]
    for index, query in enumerate(queries, start=1):
        response = client.post(
            "/api/user/chat",
            json={
                "query": query,
                "answer_style": "steps",
                "session_id": f"catalog-session-{index}",
                "use_llm": False,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["citations"][0]["doc_id"] == "KT-QT-215"
        assert "Hệ thống Phương Đông có 3 tài liệu quy trình" in body["answer"]
        assert "Quy trình lắp đặt máy móc, thiết bị" in body["answer"]
        assert "Quy trình Sửa chữa máy móc, thiết bị" in body["answer"]
        assert "Quy trình bảo dưỡng thiết bị" in body["answer"]

    count_variant = client.post(
        "/api/user/chat",
        json={
            "query": "Quy trình phòng kỹ thuật có bao nhiêu tài liệu?",
            "answer_style": "steps",
            "session_id": "catalog-count-session",
            "use_llm": False,
        },
    )
    assert count_variant.status_code == 200
    count_body = count_variant.json()
    assert count_body["citations"][0]["doc_id"] == "KT-QT-215"
    assert "Hệ thống Phương Đông có 3 tài liệu quy trình" in count_body["answer"]


def test_user_session_heartbeat_and_stale_cleanup(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    heartbeat = client.post(
        "/api/user/session/heartbeat",
        json={"session_id": "cleanup-session", "device_id": "device-a"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["session_id"] == "cleanup-session"
    assert heartbeat.json()["device_id"] == "device-a"

    db = QualityDatabase(tmp_path)
    db.log_user_chat_turn(
        "cleanup-session",
        query="hello",
        effective_query="hello",
        answer="hi",
        citation_doc_ids=["KT-QT-001"],
    )
    expired = "2000-01-01T00:00:00+00:00"
    cleanup = db.cleanup_stale_user_chat_sessions(now=expired)
    assert cleanup["deleted_sessions"] == 0

    with db.connect() as conn:
        conn.execute(
            "UPDATE user_chat_sessions SET expires_at = ? WHERE session_id = ?",
            (expired, "cleanup-session"),
        )

    cleanup = db.cleanup_stale_user_chat_sessions()
    assert cleanup["deleted_sessions"] == 1
    assert cleanup["deleted_turns"] == 1
    assert db.get_user_chat_session("cleanup-session") is None
    assert db.recent_user_chat_turns("cleanup-session") == []


def test_user_session_history_apis(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    # Log a query that creates a session and turn
    chat_resp = client.post(
        "/api/user/chat",
        json={
            "query": "Quy trình Phương Đông thế nào?",
            "session_id": "test-history-session",
            "device_id": "device-test-123",
            "use_llm": False,
        },
    )
    assert chat_resp.status_code == 200

    # Retrieve sessions by device
    sessions_resp = client.get("/api/user/sessions?device_id=device-test-123")
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "test-history-session"
    assert sessions[0]["title"] == "Quy trình Phương Đông thế nào?"

    # Retrieve turns by session
    turns_resp = client.get("/api/user/sessions/test-history-session/turns")
    assert turns_resp.status_code == 200
    turns = turns_resp.json()
    assert len(turns) == 1
    assert turns[0]["query"] == "Quy trình Phương Đông thế nào?"

    # Delete session
    del_resp = client.delete("/api/user/sessions/test-history-session")
    assert del_resp.status_code == 200
    assert del_resp.json()["session_id"] == "test-history-session"
    assert del_resp.json()["deleted_turns"] == 1

    # Verify deleted
    sessions_resp = client.get("/api/user/sessions?device_id=device-test-123")
    assert sessions_resp.json() == []


def test_dashboard_tabs_are_role_scoped() -> None:
    index = (Path(__file__).parents[1] / "poc_workflow" / "static" / "index.html").read_text(encoding="utf-8")

    assert 'data-view="chat"' in index
    assert 'data-view="documents"' in index
    assert 'data-view="quality"' not in index
    assert 'data-view="system"' not in index
    assert 'data-view="operations"' in index
    assert 'class="view admin-only" id="view-upload"' in index
    assert 'class="view admin-only" id="view-review"' in index
    assert 'class="view admin-only" id="view-operations"' in index
    assert 'id="answerFeedback"' in index
    assert 'id="documentSearchInput"' in index
    assert 'id="documentInspector"' in index
    assert 'id="reviewInspector"' in index
    assert 'id="failedReviewList"' in index
    assert "document-inspector-panel" in index
    assert 'data-review-key="title_correct"' in index
    assert 'data-review-key="steps_order_correct"' in index
    assert 'data-review-key="source_output_audit_passed"' in index


def test_document_inspector_uses_current_quality_status() -> None:
    app_js = (Path(__file__).parents[1] / "poc_workflow" / "static" / "app.js").read_text(encoding="utf-8")

    assert "function qaDisplayStatus" in app_js
    assert "data.quality_status || data.status" in app_js
    assert "await refreshSelectedDetails();" in app_js


def test_web_ragflow_only_fails_closed_when_not_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    monkeypatch.delenv("RAGFLOW_CHAT_ID", raising=False)
    monkeypatch.delenv("RAGFLOW_SEARCH_ID", raising=False)
    client = TestClient(create_app(tmp_path))

    chat = client.post(
        "/api/chat",
        json={"query": "unknown question", "provider": "ragflow"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["provider"] == "ragflow"
    assert body["citations"] == []
    assert body["knowledge_gap_id"]


def test_web_upload_queue_generates_agent_prompt_and_manual_statuses(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    content = base64.b64encode(b"# Quy trinh upload\n\nNoi dung duoc upload tu dashboard.").decode("ascii")
    vendor_content = base64.b64encode(b"# Manual A\n\nTai lieu hang cho thiet bi A.").decode("ascii")

    upload = client.post(
        "/api/inbox/upload",
        json={
            "filename": "quy_trinh_upload_v1.0.md",
            "category": "procedure",
            "content_base64": content,
        },
    )
    assert upload.status_code == 200
    assert upload.json()["relative_path"] == "procedure/quy_trinh_upload_v1.0.md"

    vendor_upload = client.post(
        "/api/inbox/upload",
        json={
            "filename": "manual_a_v1.0.md",
            "category": "vendor_document",
            "content_base64": vendor_content,
        },
    )
    assert vendor_upload.status_code == 200

    inbox = client.get("/api/inbox")
    assert inbox.status_code == 200
    assert {item["category_hint"] for item in inbox.json()} == {"procedure", "vendor_document"}

    queue = client.get("/api/upload-queue")
    assert queue.status_code == 200
    assert queue.json()["summary"]["queue"] == 2
    assert {item["status"] for item in queue.json()["items"]} == {"queue"}
    assert {item["processing_step"] for item in queue.json()["items"]} == {"waiting"}

    templates = client.get("/api/agent-prompts/templates")
    assert templates.status_code == 200
    template_body = templates.json()
    prompt_modes = {mode["id"] for mode in template_body["modes"]}
    assert template_body["default_mode"] == "process_raw"
    assert any(packet["packet"] == "evidence_packet" for packet in template_body["prompt_architecture"])
    assert any(packet["packet"] == "skill_contract_packet" for packet in template_body["prompt_architecture"])
    assert template_body["orchestration_contract"]["contract_version"] == "upload-data-orchestration-v1"
    assert any(role["role"] == "orchestrator" for role in template_body["orchestration_contract"]["roles"])
    assert {
        "process_raw",
        "classify_discuss",
        "update_existing",
        "policy_change",
        "run_workflow",
        "repair_from_qa",
        "human_review_packet",
    }.issubset(prompt_modes)

    generated = client.post(
        "/api/agent-prompts/generate",
        json={
            "relative_paths": ["procedure/quy_trinh_upload_v1.0.md", "vendor_document/manual_a_v1.0.md"],
            "prompt_mode": "classify_discuss",
            "admin_request": "Hay tu nhan dien them moi hay cap nhat va hoi admin neu mo ho.",
        },
    )
    assert generated.status_code == 200
    body = generated.json()
    prompt = body["prompt"]
    assert body["prompt_id"].startswith("agent-task-")
    assert body["prompt_version"] == "agent-task-v3"
    assert body["prompt_mode"] == "classify_discuss"
    assert len(body["files"]) == 2
    assert "# Agent Task: Upload Data Automation Prompt" in prompt
    assert "## Situation" in prompt
    assert "## Batch xử lý" not in prompt
    assert "total_files: `2`" in prompt
    assert "batch_index: `1`" in prompt
    assert "batch_index: `2`" in prompt
    assert "procedure/quy_trinh_upload_v1.0.md" in prompt
    assert "vendor_document/manual_a_v1.0.md" in prompt
    assert "KT-QT-xxx" in prompt
    assert '"prompt_id":' in prompt
    assert '"prompt_version":' in prompt
    assert '"prompt_mode": "classify_discuss"' in prompt
    assert '"requires_admin_clarification": false' in prompt
    assert '"admin_questions": []' in prompt
    assert '"classification_hypothesis":' in prompt
    assert '"validation_status": "needs_review"' in prompt
    assert "- validation_status: `pass`, `fail`, `needs_review`" in prompt
    assert "khong tra ve chuoi dang `a | b | c`" in prompt
    assert "admin_request_is_context_only: `true`" in prompt
    assert "khong duoc override Project Policies" in prompt
    assert "## Session Init Bat Buoc" in prompt
    assert "Treat this prompt as self-contained" in prompt
    assert "Claim exactly one queued file or one related PDF/XLS/XLSX/DOC/DOCX business-document group at a time" in prompt
    assert "## Skill Workflow Bat Buoc" in prompt
    assert "## Orchestration Contract" in prompt
    assert "## Kien Truc Prompt Va Handoff" in prompt
    assert "## Handoff Schema Bat Buoc" in prompt
    assert "## Dashboard Workflow Event Bat Buoc" in prompt
    assert "## Checkpoint Proof Matrix" in prompt
    assert "| Checkpoint | Owner skill | Dashboard step | Required proof |" in prompt
    assert "/api/upload-queue/workflow-event" in prompt
    assert "Role matrix:" in prompt
    assert '"orchestration":' in prompt
    assert '"subagent_handoff_required": true' in prompt
    assert "`source_packet`" in prompt
    assert "`mineru_artifact_index`" in prompt
    assert "`skill_contract_packet`" in prompt
    assert "`skill_read_receipts`" in prompt
    assert "`handoff_checker`" in prompt
    assert "Khong bat dau convert neu muc dich" in prompt
    assert "Hay tu nhan dien them moi hay cap nhat" in prompt
    assert "`mineru-source-converter`" in prompt
    assert "`source-output-quality-auditor`" in prompt
    assert "`rag-markdown-repairer`" in prompt
    assert "`ragflow-schema-indexer` chỉ được chạy khi" in prompt
    assert "`data-skill-evolution`" in prompt
    assert "`run_id`, `step`, `status`, `source_ids`, `artifacts`, `quality_gates`, `next_skill`" in prompt
    assert "RAG-ready chi pass khi co artifacts" in prompt

    queue_after_prompt = client.get("/api/upload-queue")
    assert {item["status"] for item in queue_after_prompt.json()["items"]} == {"queue"}
    assert {item["prompt_version"] for item in queue_after_prompt.json()["items"]} == {"agent-task-v3"}
    assert {item["prompt_mode"] for item in queue_after_prompt.json()["items"]} == {"classify_discuss"}
    assert {item["prompt_id"] for item in queue_after_prompt.json()["items"]} == {body["prompt_id"]}

    goal_generated = client.post(
        "/api/agent-prompts/generate-goal",
        json={
            "relative_paths": ["procedure/quy_trinh_upload_v1.0.md"],
            "branch": "codex/upload-data-goal-test",
            "goal_target": "Make demo-chatbot-engineerworkflow prove Upload GOAL prompting on branch codex/upload-data-goal-test, with immutable raw files and verified prompt APIs.",
            "verification": "Run pytest for upload prompt APIs.",
            "admin_request": "Long-run den khi queue het file.",
        },
    )
    assert goal_generated.status_code == 200
    goal_body = goal_generated.json()
    goal_prompt = goal_body["prompt"]
    assert goal_body["prompt_version"] == "agent-goal-v2"
    assert goal_body["prompt_mode"] == "goal_long_run"
    assert goal_body["goal_branch"] == "codex/upload-data-goal-test"
    assert goal_prompt.startswith("/goal Make demo-chatbot-engineerworkflow prove Upload GOAL prompting")
    assert "Onboard into `demo-chatbot-engineerworkflow` as the Upload Data Pipeline Super-Agent." in goal_prompt
    assert "## Branch And Git Safety" in goal_prompt
    assert "Work on branch `codex/upload-data-goal-test`" in goal_prompt
    assert "Do not commit, push, or switch branches" in goal_prompt
    assert "## Target End State" in goal_prompt
    assert "## Session Init Contract" in goal_prompt
    assert "after one item reaches `pending_review`, `failed`, or `ocr_required`, inspect the queue again" in goal_prompt
    assert "Phase boundary: this data-processing prompt stops at RAG-ready + human review queue" in goal_prompt
    assert "## Orchestration Contract" in goal_prompt
    assert "## Prompt Architecture Contract" in goal_prompt
    assert "## Handoff Contract" in goal_prompt
    assert "## Dashboard Workflow Event Contract" in goal_prompt
    assert "## Checkpoint Execution Matrix" in goal_prompt
    assert "| Checkpoint | Owner skill | Dashboard step | Required proof |" in goal_prompt
    assert "`mineru-source-converter`" in goal_prompt
    assert "A checkpoint cannot pass on prose alone" in goal_prompt
    assert "## Per-File Not Done Until" in goal_prompt
    assert "not done merely because one file completed" in goal_prompt
    assert "## Checkpoint And Self-Check Loop" in goal_prompt
    assert "## Resumable Execution Rule" in goal_prompt
    assert "## Definition Of Done" in goal_prompt
    assert "## Long-Run Execution Loop" in goal_prompt
    assert "## Stop Conditions" in goal_prompt
    assert "Long-run den khi queue het file." in goal_prompt
    assert ".cursor/active-context.md" in goal_prompt

    queue_after_goal_prompt = client.get("/api/upload-queue")
    goal_item = next(
        item for item in queue_after_goal_prompt.json()["items"] if item["relative_path"] == "procedure/quy_trinh_upload_v1.0.md"
    )
    assert goal_item["prompt_version"] == "agent-goal-v2"
    assert goal_item["prompt_mode"] == "goal_long_run"

    active = client.post(
        "/api/upload-queue/status",
        json={"relative_paths": ["procedure/quy_trinh_upload_v1.0.md"], "status": "active"},
    )
    assert active.status_code == 400
    assert "cannot set Active" in active.json()["detail"]

    processing = client.post(
        "/api/upload-queue/status",
        json={"relative_paths": ["procedure/quy_trinh_upload_v1.0.md", "vendor_document/manual_a_v1.0.md"], "status": "processing"},
    )
    assert processing.status_code == 200
    assert processing.json()["summary"]["processing"] == 2
    assert {item["processing_step"] for item in processing.json()["items"]} == {"prepare"}
    assert (tmp_path / ".Workplace" / "processing" / "procedure" / "quy_trinh_upload_v1.0.md").exists()

    event = client.post(
        "/api/upload-queue/workflow-event",
        json={
            "relative_paths": ["procedure/quy_trinh_upload_v1.0.md"],
            "status": "processing",
            "step": "mineru_convert",
            "detail": "Agent started MinerU conversion",
            "checkpoint": "convert",
            "handoff_path": ".Workplace/artifacts/procedure/quy_trinh_upload_v1.0/workflow/handoffs.jsonl",
            "quality_gates": {"mineru_only": True, "raw_source_immutable": True},
            "next_skill": "source-output-quality-auditor",
            "artifacts": [{"type": "converted", "path": "converted_raw/procedure/quy_trinh_upload_v1.0.md"}],
        },
    )
    assert event.status_code == 200
    event_item = next(
        item for item in event.json()["items"] if item["original_relative_path"] == "procedure/quy_trinh_upload_v1.0.md"
    )
    assert event_item["processing_step"] == "mineru_convert"
    assert event_item["checkpoint"] == "convert"
    assert event_item["handoff_path"].endswith("handoffs.jsonl")
    assert event_item["quality_gates"]["mineru_only"] is True
    assert event_item["next_skill"] == "source-output-quality-auditor"
    assert len(event_item["artifacts"]) == 1

    done = client.post(
        "/api/upload-queue/status",
        json={"relative_paths": ["procedure/quy_trinh_upload_v1.0.md"], "status": "done"},
    )
    assert done.status_code == 200
    assert done.json()["summary"]["done"] == 1
    assert done.json()["summary"]["processing"] == 1
    assert (tmp_path / "inbox" / "procedure" / "done" / "quy_trinh_upload_v1.0.md").exists()

    failed = client.post(
        "/api/upload-queue/status",
        json={"relative_paths": ["vendor_document/manual_a_v1.0.md"], "status": "failed"},
    )
    assert failed.status_code == 200
    assert failed.json()["summary"]["failed"] == 1
    assert (tmp_path / "inbox" / "vendor_document" / "failed" / "manual_a_v1.0.md").exists()

    assert client.post("/api/prepare-inbox", json={}).status_code == 404
    assert client.post("/api/process-source", json={}).status_code == 404


def test_upload_workflow_event_moves_queued_file_and_records_handoff(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    content = base64.b64encode(b"# Quy trinh event\n\nNoi dung can agent xu ly.").decode("ascii")
    upload = client.post(
        "/api/inbox/upload",
        json={"filename": "quy_trinh_event_v1.0.md", "category": "procedure", "content_base64": content},
    )
    assert upload.status_code == 200

    event = client.post(
        "/api/upload-queue/workflow-event",
        json={
            "relative_paths": ["procedure/quy_trinh_event_v1.0.md"],
            "status": "processing",
            "step": "classify",
            "detail": "Orchestrator classified one procedure file",
            "checkpoint": "plan",
            "handoff_path": ".Workplace/artifacts/procedure/quy_trinh_event_v1.0/workflow/handoffs.jsonl",
            "quality_gates": {"single_file_run": True},
            "next_skill": "mineru-source-converter",
        },
    )

    assert event.status_code == 200
    body = event.json()
    assert body["summary"]["processing"] == 1
    item = body["items"][0]
    assert item["source"] == "workplace"
    assert item["relative_path"] == "procedure/quy_trinh_event_v1.0.md"
    assert item["original_relative_path"] == "procedure/quy_trinh_event_v1.0.md"
    assert item["processing_step"] == "classify"
    assert item["checkpoint"] == "plan"
    assert item["quality_gates"]["single_file_run"] is True
    assert item["next_skill"] == "mineru-source-converter"
    assert (tmp_path / ".Workplace" / "processing" / "procedure" / "quy_trinh_event_v1.0.md").exists()
    assert not (tmp_path / "inbox" / "procedure" / "quy_trinh_event_v1.0.md").exists()


def test_upload_queue_reflects_manifest_approval_and_hides_done_from_inbox(tmp_path: Path) -> None:
    from poc_workflow.manifest import ManifestStore
    from poc_workflow.models import ManifestRecord

    client = TestClient(create_app(tmp_path))
    content = base64.b64encode(b"%PDF-1.4\nprocessed document").decode("ascii")
    upload = client.post(
        "/api/inbox/upload",
        json={"filename": "quy_trinh_duyet.pdf", "category": "procedure", "content_base64": content},
    )
    assert upload.status_code == 200

    event = client.post(
        "/api/upload-queue/workflow-event",
        json={
            "relative_paths": ["procedure/quy_trinh_duyet.pdf"],
            "status": "processing",
            "step": "qa",
            "metadata": {
                "doc_id": "KT-QT-999",
                "title": "Quy trinh duyet",
                "version": "rev01",
                "category": "procedure",
            },
        },
    )
    assert event.status_code == 200
    done = client.post(
        "/api/upload-queue/status",
        json={"relative_paths": ["procedure/quy_trinh_duyet.pdf"], "status": "done"},
    )
    assert done.status_code == 200

    source_path = tmp_path / "inbox" / "procedure" / "done" / "quy_trinh_duyet.pdf"
    normalized_path = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-999_rev01.md"
    normalized_path.parent.mkdir(parents=True)
    normalized_path.write_text("# Quy trinh duyet\n\nNoi dung da duyet.", encoding="utf-8")
    review_path = tmp_path / "review" / "upload" / "PD-TECH-A-999_rev01" / "human_review.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(
        json.dumps({"review_status": "approved", "reviewer": "simulation-admin", "simulated_approval": True}),
        encoding="utf-8",
    )
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-999",
                title="Quy trinh duyet",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="rev01",
                status="active",
                effective_from="2026-05-27",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path=str(source_path),
                normalized_path=str(normalized_path),
                content_hash="hash",
                approved_by="simulation-admin",
                extra={
                    "display_code": "PD-TECH-A-999",
                    "human_review_path": str(review_path),
                    "ragflow_ingestion": "not_run",
                },
            )
        ]
    )

    assert client.get("/api/inbox").json() == []
    queue = client.get("/api/upload-queue")
    assert queue.status_code == 200
    body = queue.json()
    assert body["summary"]["done"] == 0
    assert body["summary"]["approved"] == 1
    item = body["items"][0]
    assert item["status"] == "done"
    assert item["display_status"] == "approved"
    assert item["manifest_status"] == "active"
    assert item["review_status"] == "approved"
    assert item["display_code"] == "PD-TECH-A-999"
    assert item["ragflow_ingestion"] == "not_run"


def test_web_operator_auth_when_required(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KB_REQUIRE_AUTH", "true")
    monkeypatch.setenv("KB_AUTH_TOKEN", "secret-token")
    client = TestClient(create_app(tmp_path))

    assert client.get("/api/auth-status").json() == {"required": True, "configured": True}
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/user/bootstrap").status_code == 200
    assert client.get("/chat").status_code == 200
    assert client.get("/api/health", headers={"X-KB-Token": "secret-token"}).status_code == 200


def test_web_auth_fails_closed_if_required_without_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KB_REQUIRE_AUTH", "true")
    monkeypatch.delenv("KB_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/health")
    assert response.status_code == 503
    assert "KB_AUTH_TOKEN" in response.json()["detail"]


def test_web_incidents_and_diagnostics(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    created = client.post(
        "/api/incidents",
        json={
            "severity": "warning",
            "component": "llm",
            "title": "LLM fallback",
            "detail": "Provider timed out and fallback answer was used.",
            "context": {"query_log_id": 123},
        },
    )
    assert created.status_code == 200
    incident_id = created.json()["incident_id"]

    incidents = client.get("/api/incidents")
    assert incidents.status_code == 200
    assert incidents.json()[0]["id"] == incident_id

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["incidents"]["open"] == 1

    diagnostics = client.get("/api/diagnostics?include_logs=false")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["summary"]["open_incidents"] == 1
    assert diagnostics.json()["status"] in {"attention", "not_ready"}

    agent_prompt = client.get(f"/api/incidents/{incident_id}/agent-prompt")
    assert agent_prompt.status_code == 200
    prompt = agent_prompt.json()["prompt"]
    assert "incident #" in prompt
    assert "LLM fallback" in prompt
    assert "Provider timed out" in prompt
    assert "python -m pytest tests\\test_webapp.py --basetemp .pytest-tmp-codex" in prompt

    # Test dynamic prompt test command determination for ingestion component
    created_ingestion = client.post(
        "/api/incidents",
        json={
            "severity": "critical",
            "component": "pipeline_ingestion",
            "title": "Ingestion failed",
            "detail": "Failed to parse pdf metadata.",
            "context": {"file_path": "doc.pdf"},
        },
    )
    assert created_ingestion.status_code == 200
    ingestion_id = created_ingestion.json()["incident_id"]
    ingestion_prompt = client.get(f"/api/incidents/{ingestion_id}/agent-prompt")
    assert ingestion_prompt.status_code == 200
    prompt_ingestion = ingestion_prompt.json()["prompt"]
    assert "python -m pytest tests\\test_pipeline.py tests\\test_intake.py --basetemp .pytest-tmp-codex" in prompt_ingestion

    missing_prompt = client.get("/api/incidents/9999/agent-prompt")
    assert missing_prompt.status_code == 404

    resolved = client.post(
        "/api/incidents/resolve",
        json={"incident_id": incident_id, "status": "resolved"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_web_service_status_and_maintenance_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KB_MAINTENANCE_MODE", "true")
    monkeypatch.setenv("KB_MAINTENANCE_MESSAGE", "Dang bao tri theo lich.")
    client = TestClient(create_app(tmp_path))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["service_status"] == {
        "state": "maintenance",
        "can_chat": False,
        "title": "He thong dang bao tri",
        "message": "Dang bao tri theo lich.",
    }

    chat = client.post("/api/chat", json={"query": "quy trinh xu ly su co", "provider": "local"})
    assert chat.status_code == 503
    assert chat.json()["detail"] == "Dang bao tri theo lich."


def test_llm_status_endpoint_reports_config_and_smoke(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("POC_LLM_BASE_URL", "http://127.0.0.1:3001/v1")
    monkeypatch.setenv("POC_LLM_API_KEY", "local-secret")
    monkeypatch.setenv("POC_LLM_MODEL", "auto")

    def fake_list_models(self, timeout: float = 8) -> dict[str, object]:
        return {"count": 2, "sample": ["auto", "demo-model"]}

    def fake_smoke(self, timeout: float = 12) -> str:
        return "ok"

    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.list_models", fake_list_models)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.smoke", fake_smoke)

    client = TestClient(create_app(tmp_path))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["llm"]["configured"] is True
    assert health.json()["llm"]["state"] == "configured"
    assert health.json()["llm"]["live_checked"] is False

    status = client.get("/api/llm/status?smoke=true")
    assert status.status_code == 200
    body = status.json()
    assert body["state"] == "ready"
    assert body["proxy_online"] is True
    assert body["models_ok"] is True
    assert body["smoke_ok"] is True
    assert body["model_count"] == 2


def test_llm_dashboard_config_presets_and_secret_redaction(tmp_path: Path, monkeypatch) -> None:
    def fake_list_models(self, timeout: float = 8) -> dict[str, object]:
        return {"count": 1, "sample": [self.config.model]}

    def fake_smoke(self, timeout: float = 12) -> str:
        return "ok"

    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.list_models", fake_list_models)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.smoke", fake_smoke)

    client = TestClient(create_app(tmp_path))

    presets = client.get("/api/llm/presets")
    assert presets.status_code == 200
    preset_ids = {item["id"] for item in presets.json()}
    assert {"ollama", "freellmapi", "freemodel", "freemmlai", "openai", "deepseek", "gemini", "custom"} <= preset_ids

    missing_key = client.post(
        "/api/llm/test",
        json={"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini"},
    )
    assert missing_key.status_code == 400
    assert "API key" in missing_key.json()["detail"]

    saved = client.put(
        "/api/llm/config",
        json={
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "llama3.2",
            "api_key": "",
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["status"]["state"] == "ready"
    assert body["config"]["source"] == "runtime"
    assert body["config"]["provider"] == "ollama"
    assert body["config"]["api_key_configured"] is True
    assert "api_key_mask" not in body["config"]

    openai_saved = client.put(
        "/api/llm/config",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "api_key": "sk-test-secret-123456",
        },
    )
    assert openai_saved.status_code == 200

    config = client.get("/api/llm/config")
    assert config.status_code == 200
    assert config.json()["model"] == "gpt-4.1-mini"
    redacted = json.dumps(config.json())
    assert "sk-test-secret-123456" not in redacted
    assert '"api_key":' not in redacted
    assert "api_key_mask" not in config.json()

    reset = client.post("/api/llm/config/reset")
    assert reset.status_code == 200
    assert reset.json()["source"] in {"none", "env", "autodetect"}


def test_llm_switch_uses_provider_key_from_env_without_persisting_secret(tmp_path: Path, monkeypatch) -> None:
    def fake_list_models(self, timeout: float = 8) -> dict[str, object]:
        return {"count": 1, "sample": [self.config.model]}

    def fake_smoke(self, timeout: float = 12) -> str:
        return "ok"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-env-secret")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.list_models", fake_list_models)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.smoke", fake_smoke)

    client = TestClient(create_app(tmp_path))

    switched = client.post("/api/llm/config/switch", json={"provider": "deepseek"})

    assert switched.status_code == 200
    body = switched.json()
    assert body["switched"] is True
    assert body["config"]["provider"] == "deepseek"
    assert body["config"]["model"] == "deepseek-chat"
    assert body["config"]["api_key_configured"] is True
    assert body["status"]["state"] == "ready"
    secrets_text = (tmp_path / ".runtime" / "llm-secrets.json").read_text(encoding="utf-8")
    assert "deepseek-env-secret" not in secrets_text

    config = client.get("/api/llm/config")
    assert config.status_code == 200
    assert config.json()["provider"] == "deepseek"
    assert config.json()["api_key_configured"] is True


def test_llm_env_freemodel_is_not_reported_as_freellmapi(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("POC_LLM_BASE_URL", "https://api.freemodel.dev/v1")
    monkeypatch.setenv("POC_LLM_API_KEY", "freemodel-secret")
    monkeypatch.setenv("POC_LLM_MODEL", "auto")
    monkeypatch.setenv("POC_LLM_FREELLMAPI_AUTODETECT", "false")

    client = TestClient(create_app(tmp_path))

    response = client.get("/api/llm/config")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "freemodel"
    assert body["base_url"] == "https://api.freemodel.dev/v1"
    assert body["model"] == "auto"
    assert body["api_key_configured"] is True


def test_llm_config_save_requires_successful_smoke(tmp_path: Path, monkeypatch) -> None:
    def fake_list_models(self, timeout: float = 8) -> dict[str, object]:
        return {"count": 1, "sample": [self.config.model]}

    def failing_smoke(self, timeout: float = 12) -> str:
        from poc_workflow.llm import LLMError

        raise LLMError("provider timeout")

    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.list_models", fake_list_models)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.smoke", failing_smoke)

    client = TestClient(create_app(tmp_path))
    response = client.put(
        "/api/llm/config",
        json={
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "llama3.2",
        },
    )
    assert response.status_code == 400
    assert "provider timeout" in response.json()["detail"]
    assert not (tmp_path / ".runtime" / "llm-config.json").exists()


def test_chat_uses_active_dashboard_llm_config(tmp_path: Path, monkeypatch) -> None:
    write_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-010", "1.0", "Lead")

    def fake_list_models(self, timeout: float = 8) -> dict[str, object]:
        return {"count": 1, "sample": [self.config.model]}

    def fake_smoke(self, timeout: float = 12) -> str:
        return "ok"

    def fake_answer(self, query, hits, answer_style="brief") -> str:
        return f"runtime {self.config.provider} {self.config.model}"

    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.list_models", fake_list_models)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.smoke", fake_smoke)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.answer", fake_answer)

    client = TestClient(create_app(tmp_path))
    saved = client.put(
        "/api/llm/config",
        json={
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "local-test-model",
        },
    )
    assert saved.status_code == 200

    chat = client.post(
        "/api/chat",
        json={"query": "quy trinh nghiem thu can gi", "provider": "local", "use_llm": True},
    )
    assert chat.status_code == 200
    assert chat.json()["llm_used"] is True
    assert chat.json()["answer"] == "runtime ollama local-test-model"


def test_xlsx_preview_multi_sheets(tmp_path: Path) -> None:
    from openpyxl import Workbook
    from poc_workflow.webapp import _xlsx_preview

    xlsx_path = tmp_path / "test_multi_sheets.xlsx"
    wb = Workbook()
    for i in range(5):
        ws = wb.create_sheet(title=f"Sheet_{i}")
        ws.append([f"S{i}_R1_C1", f"S{i}_R1_C2"])
        ws.append([f"S{i}_R2_C1", f"S{i}_R2_C2"])

    if "Sheet" in wb.sheetnames:
        wb.remove(wb["Sheet"])

    wb.save(xlsx_path)

    preview = _xlsx_preview(xlsx_path)
    assert preview["error"] is None
    assert preview["sheet_count"] == 5
    assert len(preview["sheets"]) == 5
    assert preview["sheets"][0]["name"] == "Sheet_0"
    assert preview["sheets"][0]["rows"][0][0] == "S0_R1_C1"
    assert preview["sheets"][4]["name"] == "Sheet_4"
    assert preview["sheets"][4]["rows"][0][0] == "S4_R1_C1"


def test_annotations_and_variables(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    
    # 1. Test POST /api/annotations
    res = client.post(
        "/api/annotations",
        json={
            "query": "Quy trình lắp đặt máy tính là gì?",
            "annotated_answer": "Hãy cắm dây nguồn và bật nút nguồn.",
            "doc_id": "KT-QT-011",
            "version": "1.0"
        }
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    ann_id = body["id"]
    
    # 2. Test GET /api/annotations
    res = client.get("/api/annotations")
    assert res.status_code == 200
    anns = res.json()
    assert len(anns) == 1
    assert anns[0]["query"] == "Quy trình lắp đặt máy tính là gì?"
    assert anns[0]["annotated_answer"] == "Hãy cắm dây nguồn và bật nút nguồn."
    assert anns[0]["doc_id"] == "KT-QT-011"
    
    # 3. Test annotation match in user chat
    chat_res = client.post(
        "/api/user/chat",
        json={
            "query": "  quy trình lắp đặt máy tính là gì?  ",
            "use_llm": False
        }
    )
    assert chat_res.status_code == 200
    chat_body = chat_res.json()
    assert chat_body["answer"] == "Hãy cắm dây nguồn và bật nút nguồn."
    assert chat_body["citations"][0]["doc_id"] == "KT-QT-011"
    assert chat_body["trace"]["latency_ms"] == 0
    assert chat_body["trace"]["tokens_prompt"] == 0
    
    # 4. Test DELETE /api/annotations/{id}
    del_res = client.delete(f"/api/annotations/{ann_id}")
    assert del_res.status_code == 200
    
    # Verify deleted
    res = client.get("/api/annotations")
    assert len(res.json()) == 0


def test_bulk_operations(tmp_path: Path) -> None:
    db = QualityDatabase(tmp_path)
    client = TestClient(create_app(tmp_path))

    # 1. Test Gaps bulk status & bulk delete
    gap_id1 = db.create_gap("gap query 1", "missing_doc", "owner1")
    gap_id2 = db.create_gap("gap query 2", "outdated_doc", "owner2")
    
    # Verify created
    gaps = db.list_gaps()
    assert len(gaps) == 2

    # Bulk status update
    res = client.post("/api/gaps/bulk-status", json={"ids": [gap_id1, gap_id2], "status": "resolved"})
    assert res.status_code == 200
    assert db.list_gaps()[0]["status"] == "resolved"

    # Bulk delete
    res = client.post("/api/gaps/bulk-delete", json={"ids": [gap_id1, gap_id2]})
    assert res.status_code == 200
    assert len(db.list_gaps()) == 0


    # 2. Test Queries feedback & bulk delete
    q_id1 = db.log_query("query 1", None, [], True, 100, "answer 1")
    q_id2 = db.log_query("query 2", None, [], False, 150, "answer 2")

    # Bulk feedback update
    res = client.post("/api/queries/bulk-feedback", json={"ids": [q_id1, q_id2], "feedback": "wrong_source"})
    assert res.status_code == 200
    queries = db.list_queries()
    assert queries[0]["feedback"] == "wrong_source"

    # Bulk delete
    res = client.post("/api/queries/bulk-delete", json={"ids": [q_id1, q_id2]})
    assert res.status_code == 200
    assert len(db.list_queries()) == 0


    # 3. Test Ingestion Runs bulk delete
    db.log_ingestion("started", "doc-1", "1.0", None, "run-1")
    db.log_ingestion("finished", "doc-2", "1.0", None, "run-2")
    runs = db.list_ingestion_runs()
    run_id1 = runs[1]["id"]
    run_id2 = runs[0]["id"]

    # Bulk delete
    res = client.post("/api/ingestion-runs/bulk-delete", json={"ids": [run_id1, run_id2]})
    assert res.status_code == 200
    assert len(db.list_ingestion_runs()) == 0


    # 4. Test Incidents bulk resolve & bulk delete
    inc_id1 = db.create_incident("warning", "component1", "title1", "detail1")
    inc_id2 = db.create_incident("critical", "component2", "title2", "detail2")

    # Bulk resolve
    res = client.post("/api/incidents/bulk-resolve", json={"ids": [inc_id1, inc_id2], "status": "resolved"})
    assert res.status_code == 200
    incidents = db.list_incidents()
    assert incidents[0]["status"] == "resolved"

    # Bulk delete
    res = client.post("/api/incidents/bulk-delete", json={"ids": [inc_id1, inc_id2]})
    assert res.status_code == 200
    assert len(db.list_incidents()) == 0



def test_clear_diagnostics_logs(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    # Create dummy log files
    log_dir = tmp_path / ".runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file1 = log_dir / "test-1.log"
    log_file2 = log_dir / "test-2.log"
    log_file1.write_text("log line 1\nlog line 2", encoding="utf-8")
    log_file2.write_text("another log line", encoding="utf-8")

    assert log_file1.exists()
    assert log_file2.exists()

    # Clear logs endpoint call
    res = client.post("/api/diagnostics/clear-logs", json={"files": [".runtime/test-1.log", ".runtime/test-2.log"]})
    assert res.status_code == 200
    
    # Verify unlinked
    assert not log_file1.exists()
    assert not log_file2.exists()
