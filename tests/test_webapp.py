from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

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
