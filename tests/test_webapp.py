from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from poc_workflow.chatbot import NO_SOURCE_ANSWER
from poc_workflow.database import QualityDatabase
from poc_workflow.pipeline import approve_record, process_sources
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
    assert detail_body["qa_report"]["exists"] is True
    assert detail_body["qa_report"]["data"]["status"] == "pass"
    assert detail_body["canonical_key"]
    assert isinstance(detail_body["related_records"], list)
    assert any(warning["code"] == "short_markdown" for warning in detail_body["warnings"])

    missing_detail = client.get("/api/documents/NOPE/1.0")
    assert missing_detail.status_code == 404

    chat = client.post(
        "/api/chat",
        json={"query": "quy trinh nghiem thu can gi", "provider": "local"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["provider"] == "local"
    assert body["citations"]

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
        "Quy trình kỹ thuật",
        "Biểu mẫu kỹ thuật",
        "Xử lý sự cố",
        "Tài liệu hãng",
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
    assert set(body["citations"][0]) == {"title", "doc_id", "version", "excerpt"}
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
    assert "Tóm tắt:" in body["answer"]
    assert "Các bước / Nội dung chính:" in body["answer"]
    assert "Nguồn:" in body["answer"]

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
    assert unrelated_body["answer"] == NO_SOURCE_ANSWER
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
        assert "Phòng Kỹ thuật có 3 tài liệu quy trình" in body["answer"]
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
    assert "Phòng Kỹ thuật có 3 tài liệu quy trình" in count_body["answer"]


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
    assert "document-inspector-panel" in index


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

    generated = client.post(
        "/api/agent-prompts/generate",
        json={"relative_paths": ["procedure/quy_trinh_upload_v1.0.md", "vendor_document/manual_a_v1.0.md"]},
    )
    assert generated.status_code == 200
    body = generated.json()
    prompt = body["prompt"]
    assert body["prompt_id"].startswith("agent-task-")
    assert body["prompt_version"] == "agent-task-v1"
    assert len(body["files"]) == 2
    assert "# Agent Task: Xử lý tài liệu" in prompt
    assert "## Batch xử lý" in prompt
    assert "total_files: `2`" in prompt
    assert "batch_index: `1`" in prompt
    assert "batch_index: `2`" in prompt
    assert "procedure/quy_trinh_upload_v1.0.md" in prompt
    assert "vendor_document/manual_a_v1.0.md" in prompt
    assert "KT-QT-xxx" in prompt
    assert '"prompt_id":' in prompt
    assert '"prompt_version":' in prompt
    assert '"validation_status": "pass | fail"' in prompt

    queue_after_prompt = client.get("/api/upload-queue")
    assert {item["status"] for item in queue_after_prompt.json()["items"]} == {"queue"}
    assert {item["prompt_version"] for item in queue_after_prompt.json()["items"]} == {"agent-task-v1"}
    assert {item["prompt_id"] for item in queue_after_prompt.json()["items"]} == {body["prompt_id"]}

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
    assert {"ollama", "freellmapi", "openai", "deepseek", "gemini", "custom"} <= preset_ids

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
    assert body["config"]["api_key_mask"] == "••••"

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

    reset = client.post("/api/llm/config/reset")
    assert reset.status_code == 200
    assert reset.json()["source"] in {"none", "env", "autodetect"}


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
