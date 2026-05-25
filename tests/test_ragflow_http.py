from __future__ import annotations

from pathlib import Path

from poc_workflow.models import ManifestRecord
from poc_workflow.manifest import ManifestStore
from poc_workflow import ragflow_http
from poc_workflow.ragflow_http import (
    bootstrap_ragflow_resources,
    extract_reference_citations,
    record_to_ragflow_metadata,
    sync_active_to_ragflow,
)


def test_extract_reference_citations_accepts_openai_reference_list() -> None:
    citations = extract_reference_citations(
        [
            {
                "id": "chunk-1",
                "document_id": "ragflow-doc-id",
                "document_name": "Procedure.md",
                "dataset_id": "dataset-1",
                "similarity": 0.91,
                "document_metadata": {
                    "doc_id": "KT-QT-003",
                    "version": "1.2",
                    "display_code": "PD-TECH-A-02",
                    "display_version": "Rev 04",
                    "category": "procedure",
                    "source_path": "/source/KT-QT-003_v1.2.pdf",
                    "normalized_path": "/normalized/KT-QT-003_v1.2.md",
                },
            }
        ]
    )

    assert citations == [
        {
            "doc_id": "KT-QT-003",
            "version": "1.2",
            "display_code": "PD-TECH-A-02",
            "display_version": "Rev 04",
            "title": "Procedure.md",
            "category": "procedure",
            "chunk_id": "chunk-1",
            "source_path": "/source/KT-QT-003_v1.2.pdf",
            "normalized_path": "/normalized/KT-QT-003_v1.2.md",
            "score": 0.91,
        }
    ]


def test_record_to_ragflow_metadata_carries_source_of_truth_paths() -> None:
    record = ManifestRecord(
        doc_id="KT-QT-003",
        title="Quy trinh xu ly su co",
        department="technical",
        category="procedure",
        source_type="internal_procedure",
        language="vi",
        version="1.2",
        status="active",
        effective_from="2025-01-01",
        owner="Phong Ky thuat",
        access_group="technical",
        source_path="/source/KT-QT-003_v1.2.pdf",
        normalized_path="/normalized/KT-QT-003_v1.2.md",
        content_hash="sha256",
        approved_by="Lead",
    )

    metadata = record_to_ragflow_metadata(record)

    assert metadata["status"] == "active"
    assert metadata["source_path"] == "/source/KT-QT-003_v1.2.pdf"
    assert metadata["normalized_path"] == "/normalized/KT-QT-003_v1.2.md"
    assert metadata["content_hash"] == "sha256"


def test_bootstrap_ragflow_resources_finds_existing_dataset_and_creates_chat(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def __init__(self, base_url: str, api_key: str):
            calls.append(("init", (base_url, api_key)))

        def list_datasets(self, name=None, include_parsing_status=False):
            calls.append(("list_datasets", (name, include_parsing_status)))
            return [{"id": "dataset-1", "name": "technical_active"}]

        def list_chat_assistants(self, name=None):
            calls.append(("list_chats", name))
            return []

        def create_chat_assistant(self, name, dataset_ids, llm_id=None):
            calls.append(("create_chat", (name, dataset_ids, llm_id)))
            return {"id": "chat-1", "name": name, "dataset_ids": dataset_ids}

    monkeypatch.setattr(ragflow_http, "RAGFlowHTTPClient", FakeClient)

    result = bootstrap_ragflow_resources("http://ragflow", "key", llm_id="model@factory")

    assert result["dataset_created"] is False
    assert result["chat_created"] is True
    assert result["env"]["RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID"] == "dataset-1"
    assert result["env"]["RAGFLOW_CHAT_ID"] == "chat-1"
    assert ("create_chat", ("technical_procedure_chat", ["dataset-1"], "model@factory")) in calls


def test_sync_active_to_ragflow_uploads_only_latest_active_version(tmp_path: Path, monkeypatch) -> None:
    old_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-009_v1.0.md"
    new_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-009_v1.2.md"
    old_md.parent.mkdir(parents=True, exist_ok=True)
    old_md.write_text("# Quy trinh\n\nBan cu khong sync.", encoding="utf-8")
    new_md.write_text("# Quy trinh\n\nBan moi sync.", encoding="utf-8")
    ManifestStore(tmp_path).save(
        [
            _record("1.0", old_md, "old"),
            _record("1.2", new_md, "new"),
        ]
    )
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def __init__(self, base_url: str, api_key: str):
            calls.append(("init", (base_url, api_key)))

        def delete_all_documents(self, dataset_id: str):
            calls.append(("delete_all", dataset_id))
            return {"code": 0}

        def upload_document(self, dataset_id: str, path: Path, display_name: str | None = None):
            calls.append(("upload", display_name))
            return {"id": f"doc-{display_name}"}

        def update_document_metadata(self, dataset_id: str, document_id: str, metadata: dict[str, str]):
            calls.append(("metadata", metadata))
            return {"code": 0}

        def parse_documents(self, dataset_id: str, document_ids: list[str]):
            calls.append(("parse", document_ids))
            return {"code": 0}

    monkeypatch.setattr(ragflow_http, "RAGFlowHTTPClient", FakeClient)

    result = sync_active_to_ragflow(tmp_path, "http://ragflow", "key", "dataset-1")

    assert result["uploaded_count"] == 1
    assert ("upload", "KT-QT-009_v1.2_procedure.md") in calls
    assert ("upload", "KT-QT-009_v1.0_procedure.md") not in calls
    metadata_calls = [payload for name, payload in calls if name == "metadata"]
    assert metadata_calls[0]["version"] == "1.2"


def _record(version: str, normalized_path: Path, content_hash: str) -> ManifestRecord:
    return ManifestRecord(
        doc_id="KT-QT-009",
        title="Quy trinh",
        department="technical",
        category="procedure",
        source_type="internal_procedure",
        language="vi",
        version=version,
        status="active",
        effective_from="2025-01-01",
        owner="Phong Ky thuat",
        access_group="technical",
        source_path=f"/source/KT-QT-009_v{version}.pdf",
        normalized_path=str(normalized_path),
        content_hash=content_hash,
    )
