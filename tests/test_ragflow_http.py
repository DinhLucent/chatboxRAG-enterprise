from __future__ import annotations

from pathlib import Path

from poc_workflow.models import ManifestRecord
from poc_workflow.manifest import ManifestStore
from poc_workflow import ragflow_http
from poc_workflow.ragflow_http import (
    RAGFlowHTTPClient,
    bootstrap_ragflow_resources,
    extract_reference_citations,
    record_to_ragflow_metadata,
    ragflow_sync_preflight,
    ragflow_uploadable_records,
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


def test_retrieve_chunks_sends_dataset_allowlist_and_active_filter(monkeypatch) -> None:
    calls: list[tuple[str, str, dict | None]] = []
    client = RAGFlowHTTPClient("http://ragflow", "key")

    def fake_json_request(method: str, path: str, payload: dict | None = None) -> dict:
        calls.append((method, path, payload))
        return {"code": 0, "data": {"chunks": []}}

    monkeypatch.setattr(client, "_json_request", fake_json_request)
    condition = {
        "logic": "and",
        "conditions": [{"name": "status", "comparison_operator": "is", "value": "active"}],
    }

    result = client.retrieve_chunks(
        ["dataset-a", "dataset-b"],
        "danh sach quy trinh",
        top_k=24,
        page_size=24,
        metadata_condition=condition,
        rerank_id="reranker-1",
    )

    assert result["code"] == 0
    assert calls == [
        (
            "POST",
            "/api/v1/chunks/retrieval",
            {
                "dataset_ids": ["dataset-a", "dataset-b"],
                "question": "danh sach quy trinh",
                "page": 1,
                "page_size": 24,
                "top_k": 24,
                "similarity_threshold": 0.0,
                "vector_similarity_weight": 0.3,
                "highlight": False,
                "reference_metadata": {"include": True},
                "metadata_condition": condition,
                "rerank_id": "reranker-1",
            },
        )
    ]


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


def test_ragflow_uploadable_records_accepts_docx_primary_source(tmp_path: Path) -> None:
    md = tmp_path / "normalized" / "tender_legal" / "procedure" / "PL-092.01_rev04.md"
    md.parent.mkdir(parents=True)
    md.write_text("# Quy trinh\n\nNoi dung.", encoding="utf-8")
    record = ManifestRecord(
        doc_id="PL-092.01",
        title="Quy trinh doi tac",
        department="tender_legal",
        category="procedure",
        source_type="internal_procedure",
        language="vi",
        version="rev04",
        status="active",
        effective_from="2025-01-01",
        owner="Phong Thau Phap che",
        access_group="tender_legal",
        source_path="/source/PL-092.01.docx",
        normalized_path=str(md),
        content_hash="hash",
        extra={
            "ingest_policy": "primary_source_only",
            "quality_status": "passed",
            "citation_map_path": "/indexes/PL-092.01_rev04_citation_map.json",
            "primary_source_decision": {"selected": "docx"},
        },
    )

    assert ragflow_uploadable_records([record]) == [record]


def test_ragflow_sync_preflight_writes_upload_plan_without_network(tmp_path: Path) -> None:
    md = tmp_path / "normalized" / "tender_legal" / "procedure" / "PL-092.01_rev04.md"
    citation_map = tmp_path / "indexes" / "PL-092.01_rev04_citation_map.json"
    mineru_index = tmp_path / "converted_raw" / "PL-092.01" / "mineru_artifact_index.json"
    md.parent.mkdir(parents=True)
    citation_map.parent.mkdir(parents=True)
    mineru_index.parent.mkdir(parents=True)
    md.write_text("# Quy trinh\n\nNoi dung.", encoding="utf-8")
    citation_map.write_text("[]", encoding="utf-8")
    mineru_index.write_text("{}", encoding="utf-8")
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="PL-092.01",
                title="Quy trinh doi tac",
                department="tender_legal",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="rev04",
                status="active",
                effective_from="2025-01-01",
                owner="Phong Thau Phap che",
                access_group="tender_legal",
                source_path="/source/PL-092.01.docx",
                normalized_path=str(md),
                content_hash="hash",
                extra={
                    "ingest_policy": "primary_source_only",
                    "quality_status": "passed",
                    "citation_map_path": str(citation_map),
                    "mineru_artifact_index_path": str(mineru_index),
                    "primary_source_decision": {"selected": "docx"},
                },
            )
        ]
    )

    result = ragflow_sync_preflight(tmp_path)

    assert result["ready_for_sync"] is False
    assert result["missing_config"] == [
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID",
    ]
    assert result["policy_uploadable_count"] == 1
    assert result["blocking_record_count"] == 0
    report = Path(result["report_path"])
    assert report.exists()
    assert "PL-092.01" in report.read_text(encoding="utf-8")
    assert result["upload_sample"][0]["quality_status"] == "passed"
    assert result["upload_sample"][0]["primary_source_selected"] == "docx"


def test_ragflow_sync_preflight_blocks_missing_citation_artifact(tmp_path: Path) -> None:
    md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-002_rev04.md"
    mineru_index = tmp_path / "converted_raw" / "KT-QT-002" / "mineru_artifact_index.json"
    md.parent.mkdir(parents=True)
    mineru_index.parent.mkdir(parents=True)
    md.write_text("# Quy trinh\n\nNoi dung.", encoding="utf-8")
    mineru_index.write_text("{}", encoding="utf-8")
    missing_citation = tmp_path / "indexes" / "KT-QT-002_rev04_citation_map.json"
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-002",
                title="Quy trinh bao duong",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="rev04",
                status="active",
                effective_from="2025-01-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path="/source/KT-QT-002.xlsx",
                normalized_path=str(md),
                content_hash="hash",
                extra={
                    "ingest_policy": "primary_source_only",
                    "quality_status": "passed",
                    "citation_map_path": str(missing_citation),
                    "mineru_artifact_index_path": str(mineru_index),
                    "primary_source_decision": {"selected": "xlsx"},
                },
            )
        ]
    )

    result = ragflow_sync_preflight(tmp_path, base_url="http://ragflow", api_key="key", dataset_id="dataset")

    assert result["ready_for_sync"] is False
    assert result["missing_config"] == []
    assert result["blocking_record_count"] == 1
    assert result["blocked_sample"][0]["issues"][0]["type"] == "citation_map_file_missing"


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
