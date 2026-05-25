from __future__ import annotations

import json
from pathlib import Path

from poc_workflow.chatbot import NO_SOURCE_ANSWER, ask, apply_feedback
from poc_workflow.database import QualityDatabase
from poc_workflow.manifest import ManifestStore
from poc_workflow.models import ManifestRecord
from poc_workflow.converter import OcrRequiredError
from poc_workflow.data_maintenance import scope_active_set
from poc_workflow.pipeline import approve_record, init_workspace, process_sources, rebuild_indexes
from poc_workflow.rag_index import LocalRagIndex, chunk_markdown_with_metadata, stable_anchor_id
from poc_workflow.utils import content_hash


def write_source(
    root: Path,
    filename: str,
    version: str,
    body: str,
    metadata_extra: dict[str, object] | None = None,
) -> None:
    path = root / "source" / "technical" / "procedure" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    metadata = {
        "doc_id": "KT-QT-003",
        "title": "Quy trinh xu ly su co ky thuat",
        "department": "technical",
        "category": "procedure",
        "source_type": "internal_procedure",
        "language": "vi",
        "version": version,
        "effective_from": "2025-01-01",
        "review_at": "2025-12-31",
        "owner": "Phong Ky thuat",
        "access_group": "technical",
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    path.with_name(path.stem + ".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_markdown_chunks_include_line_offsets_and_stable_anchors() -> None:
    chunks = chunk_markdown_with_metadata(
        "# Tieu de\n\nBuoc 1: Tiep nhan yeu cau.\n\nBuoc 2: Lap bien ban va luu ho so.",
        max_chars=40,
    )

    assert chunks
    assert all(chunk["line_start"] >= 1 for chunk in chunks)
    assert all(chunk["line_end"] >= chunk["line_start"] for chunk in chunks)
    assert stable_anchor_id("KT-QT-010", "1.0", 2) == "KT-QT-010-v1-0-c2"


def test_lifecycle_archives_old_active_and_searches_only_new_version(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(
        tmp_path,
        "KT-QT-003_v1.0.md",
        "1.0",
        "# Xu ly su co\n\nBan 1 yeu cau tiep nhan ticket va xu ly trong 24 gio.",
    )

    processed = process_sources(tmp_path)
    assert len(processed) == 1
    assert processed[0].status == "pending_review"
    approve_record(tmp_path, "KT-QT-003", "1.0", "Lead")

    write_source(
        tmp_path,
        "KT-QT-003_v1.1.md",
        "1.1",
        "# Xu ly su co\n\nBan 2 yeu cau tiep nhan ticket, phan loai muc do va xu ly trong 8 gio.",
        {"effective_from": "2025-02-01"},
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-003", "1.1", "Lead")

    records = ManifestStore(tmp_path).load()
    v1 = next(record for record in records if record.version == "1.0")
    v11 = next(record for record in records if record.version == "1.1")
    assert v1.status == "archived"
    assert v11.status == "active"

    hits = LocalRagIndex(tmp_path).search("xu ly su co trong bao lau")
    assert hits
    assert {hit.version for hit in hits} == {"1.1"}


def test_missing_metadata_is_not_ingested(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    path = tmp_path / "source" / "technical" / "procedure" / "KT-QT-004_v1.0.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Missing metadata\n\nThis should fail review.", encoding="utf-8")

    processed = process_sources(tmp_path)
    assert processed == []
    assert ManifestStore(tmp_path).load() == []
    runs = QualityDatabase(tmp_path).connect().execute("SELECT status FROM ingestion_runs").fetchall()
    assert [row[0] for row in runs] == ["failed_review"]


def test_ocr_required_error_is_classified_separately(tmp_path: Path) -> None:
    class NeedsOcrConverter:
        def convert(self, source_path: Path, output_md: Path, language: str = "vi", artifact_root: Path | None = None) -> None:
            raise OcrRequiredError("MinerU failed and PDF text fallback found no embedded text")

    init_workspace(tmp_path)
    path = tmp_path / "source" / "technical" / "procedure" / "KT-QT-004_v1.0.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n")
    path.with_name(path.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-QT-004",
                "title": "Scan can OCR",
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

    processed = process_sources(tmp_path, converter=NeedsOcrConverter())

    assert processed == []
    assert ManifestStore(tmp_path).load() == []
    runs = QualityDatabase(tmp_path).connect().execute("SELECT status FROM ingestion_runs").fetchall()
    assert [row[0] for row in runs] == ["ocr_required"]


def test_processing_status_and_qa_repair_basic_mojibake(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(
        tmp_path,
        "KT-QT-005_v1.0.md",
        "1.0",
        "# Quy tr\u00c3\u00acnh\n\nN\u00e1\u00bb\u2122i dung th\u00e1\u00bb\u00ad nghi\u00e1\u00bb\u2021m cho QA.",
        {"doc_id": "KT-QT-005", "title": "Quy trinh QA"},
    )

    processed = process_sources(tmp_path)

    assert len(processed) == 1
    normalized = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-005_v1.0.md"
    assert "Quy trình" in normalized.read_text(encoding="utf-8")
    report = json.loads(
        (tmp_path / ".Workplace" / "artifacts" / "procedure" / "KT-QT-005_v1.0" / "qa_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["status"] == "repaired"
    state = json.loads((tmp_path / "manifest" / "agent_prompt_queue.json").read_text(encoding="utf-8"))
    item = state["items"]["procedure/KT-QT-005_v1.0.md"]
    assert item["status"] == "done"
    assert item["processing_step"] == "done"
    assert item["qa_status"] == "repaired"
    assert [event["step"] for event in item["processing_history"]][-2:] == ["qa", "done"]


def test_query_log_feedback_and_knowledge_gap(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(
        tmp_path,
        "KT-QT-003_v1.0.md",
        "1.0",
        "# Xu ly su co\n\nQuy trinh yeu cau ghi nhan ticket va cap nhat ket qua xu ly.",
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-003", "1.0", "Lead")

    answered = ask(tmp_path, "quy trinh xu ly su co")
    assert answered["query_log_id"]
    assert answered["citations"]

    feedback = apply_feedback(tmp_path, int(answered["query_log_id"]), "wrong_source")
    assert feedback["knowledge_gap_id"]

    no_answer = ask(tmp_path, "bien tan E-07 encoder parameter P191")
    assert no_answer["knowledge_gap_id"]
    gaps = QualityDatabase(tmp_path).list_gaps()
    assert len(gaps) >= 2


def test_local_chat_rejects_low_confidence_token_overlap(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(
        tmp_path,
        "KT-QT-012_v1.0.md",
        "1.0",
        "# Data integrity\n\nTai lieu noi ve technical parameter trong ho so chat luong.",
        {"doc_id": "KT-QT-012", "title": "Data integrity"},
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-012", "1.0", "Lead")

    answer = ask(tmp_path, "Bien tan E-07 encoder parameter P191")

    assert answer["citations"] == []
    assert answer["knowledge_gap_id"]
    assert answer["answer"] == NO_SOURCE_ANSWER


def test_incident_log_and_resolution(tmp_path: Path) -> None:
    db = QualityDatabase(tmp_path)
    incident_id = db.create_incident(
        "warning",
        "ingestion",
        "Metadata missing",
        "Required sidecar metadata was not found.",
        {"path": "source/technical/procedure/example.pdf"},
    )

    incidents = db.list_incidents(status="open")
    assert incidents[0]["id"] == incident_id
    assert incidents[0]["context"]["path"].endswith("example.pdf")
    assert db.stats()["open_incident_count"] == 1

    resolved = db.resolve_incident(incident_id)
    assert resolved["status"] == "resolved"
    assert db.stats()["open_incident_count"] == 0


def test_auto_provider_fails_closed_when_local_fallback_is_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KB_ENABLE_LOCAL_FALLBACK", "false")
    monkeypatch.setenv("KB_ALLOWED_PROVIDERS", "auto,ragflow")
    init_workspace(tmp_path)
    write_source(
        tmp_path,
        "KT-QT-003_v1.0.md",
        "1.0",
        "# Xu ly su co\n\nQuy trinh nay dang active nhung production khong duoc fallback local.",
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-003", "1.0", "Lead")

    answer = ask(tmp_path, "quy trinh xu ly su co")

    assert answer["provider"] == "auto"
    assert answer["citations"] == []
    assert answer["knowledge_gap_id"]
    assert answer["ragflow_error"] == "RAGFlow is not configured and local fallback is disabled"


def test_rebuild_index_from_manifest_and_normalized_files(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(
        tmp_path,
        "KT-QT-003_v1.0.md",
        "1.0",
        "# Xu ly su co\n\nNoi dung co the rebuild tu normalized va manifest.",
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-003", "1.0", "Lead")

    index_path = tmp_path / "ragflow_index" / "technical_active.jsonl"
    index_path.unlink()
    rebuild_indexes(tmp_path)
    assert index_path.exists()
    assert LocalRagIndex(tmp_path).search("rebuild normalized manifest")


def test_rebuild_index_uses_only_latest_active_version(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    old_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-009_v1.0.md"
    new_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-009_v1.2.md"
    old_md.parent.mkdir(parents=True, exist_ok=True)
    old_md.write_text("# Quy trinh\n\nNoi dung cu khong duoc dung.", encoding="utf-8")
    new_md.write_text("# Quy trinh\n\nNoi dung moi duoc dung.", encoding="utf-8")

    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-009",
                title="Quy trinh",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="1.0",
                status="active",
                effective_from="2025-01-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path="/source/old.pdf",
                normalized_path=str(old_md),
                content_hash="old",
            ),
            ManifestRecord(
                doc_id="KT-QT-009",
                title="Quy trinh",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="1.2",
                status="active",
                effective_from="2025-03-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path="/source/new.pdf",
                normalized_path=str(new_md),
                content_hash="new",
            ),
        ]
    )

    rebuild_indexes(tmp_path)

    hits = LocalRagIndex(tmp_path).search("Noi dung")
    assert hits
    assert {hit.version for hit in hits} == {"1.2"}


def test_rebuild_index_uses_only_latest_business_revision_for_same_document_code(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    old_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-OLD_v1.0.md"
    new_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-NEW_v1.0.md"
    old_md.parent.mkdir(parents=True, exist_ok=True)
    old_md.write_text("# Quy trinh\n\nNoi dung Rev 03 khong duoc dung.", encoding="utf-8")
    new_md.write_text("# Quy trinh\n\nNoi dung Rev 04 moi duoc dung.", encoding="utf-8")

    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-OLD",
                title="PD SALES A 106 Rev 03 Quy trình bán hàng",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="1.0",
                status="active",
                effective_from="2025-01-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path="/source/old.pdf",
                normalized_path=str(old_md),
                content_hash="old",
            ),
            ManifestRecord(
                doc_id="KT-QT-NEW",
                title="PD SALES A 106 Rev 04 Quy trình bán hàng",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="1.0",
                status="active",
                effective_from="2025-03-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path="/source/new.pdf",
                normalized_path=str(new_md),
                content_hash="new",
            ),
        ]
    )

    rebuild_indexes(tmp_path)

    hits = LocalRagIndex(tmp_path).search("Noi dung")
    assert hits
    assert {hit.doc_id for hit in hits} == {"KT-QT-NEW"}
    assert "Rev 03" not in (tmp_path / "ragflow_index" / "technical_active.jsonl").read_text(encoding="utf-8")


def test_rebuild_index_uses_deterministic_latest_when_business_revision_ties(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    old_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-022_v1.0.md"
    new_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-215_v1.0.md"
    old_md.parent.mkdir(parents=True, exist_ok=True)
    old_md.write_text("# Kiem soat tai lieu\n\nNoi dung duplicate dau tien.", encoding="utf-8")
    new_md.write_text("# Kiem soat tai lieu\n\nNoi dung duplicate duoc phuc vu.", encoding="utf-8")

    common = {
        "title": "PD IC A 001 Rev 10 Quy trinh kiem soat tai lieu, ho so",
        "department": "technical",
        "category": "procedure",
        "source_type": "internal_procedure",
        "language": "vi",
        "version": "1.0",
        "status": "active",
        "effective_from": "2025-01-01",
        "owner": "Phong Ky thuat",
        "access_group": "technical",
    }
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-022",
                source_path="/source/KT-QT-022.pdf",
                normalized_path=str(old_md),
                content_hash="old",
                **common,
            ),
            ManifestRecord(
                doc_id="KT-QT-215",
                source_path="/source/KT-QT-215.pdf",
                normalized_path=str(new_md),
                content_hash="new",
                **common,
            ),
        ]
    )
    rebuild_indexes(tmp_path)

    hits = LocalRagIndex(tmp_path).search("quy trinh kiem soat tai lieu", limit=3)

    assert hits
    assert {hit.doc_id for hit in hits} == {"KT-QT-215"}


def test_incident_workflow_queries_keep_active_ticket_procedure_in_top_hits(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    kt003_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-003_v1.0.md"
    faq_md = tmp_path / "normalized" / "technical" / "faq" / "KT-FAQ-011_v1.0.md"
    generic_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-028_v1.0.md"
    kt003_md.parent.mkdir(parents=True, exist_ok=True)
    faq_md.parent.mkdir(parents=True, exist_ok=True)
    kt003_md.write_text(
        "# Quy trinh xu ly su co ky thuat\n\n"
        "Nhan vien Ky thuat tiep nhan thong tin su co tu nguoi dung hoac he thong giam sat, "
        "ghi nhan ticket, phan loai muc do anh huong, cap nhat ket qua va dong ticket.",
        encoding="utf-8",
    )
    faq_md.write_text(
        "# Cau hoi ve tiep nhan su co\n\n"
        "FAQ giai thich nhanh viec tiep nhan su co nhung khong thay the quy trinh xu ly su co ky thuat.",
        encoding="utf-8",
    )
    generic_md.write_text(
        "# Quy trinh tiep nhan thong tin\n\n"
        "Tai lieu quy dinh kenh tiep nhan thong tin chung va phan hoi cho cac bo phan lien quan.",
        encoding="utf-8",
    )

    common = {
        "department": "technical",
        "source_type": "internal_procedure",
        "language": "vi",
        "version": "1.0",
        "status": "active",
        "effective_from": "2025-01-01",
        "owner": "Phong Ky thuat",
        "access_group": "technical",
    }
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-003",
                title="Quy trinh xu ly su co ky thuat",
                category="procedure",
                source_path="/source/KT-QT-003.md",
                normalized_path=str(kt003_md),
                content_hash="kt003",
                **common,
            ),
            ManifestRecord(
                doc_id="KT-FAQ-011",
                title="FAQ tiep nhan su co ky thuat",
                category="faq",
                source_path="/source/KT-FAQ-011.md",
                normalized_path=str(faq_md),
                content_hash="faq011",
                **common,
            ),
            ManifestRecord(
                doc_id="KT-QT-028",
                title="Quy trinh tiep nhan thong tin",
                category="procedure",
                source_path="/source/KT-QT-028.md",
                normalized_path=str(generic_md),
                content_hash="kt028",
                **common,
            ),
        ]
    )
    rebuild_indexes(tmp_path)

    queries = [
        "Tai lieu nao huong dan nhan vien phong Ky thuat tiep nhan su co?",
        "Thoi gian bao loi co nam trong thong tin can ghi nhan khong?",
        "Muc do uu tien duoc phan loai theo quy dinh cua bo phan nao?",
    ]
    for query in queries:
        hits = LocalRagIndex(tmp_path).search(query, limit=3)
        assert hits
        assert "KT-QT-003" in {hit.doc_id for hit in hits}
        assert hits[0].doc_id == "KT-QT-003"


def test_process_sources_can_target_specific_source_paths(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(
        tmp_path,
        "KT-QT-010_v1.0.md",
        "1.0",
        "# Tai lieu 10\n\nNoi dung tai lieu 10.",
        {"doc_id": "KT-QT-010", "title": "Tai lieu 10"},
    )
    write_source(
        tmp_path,
        "KT-QT-011_v1.0.md",
        "1.0",
        "# Tai lieu 11\n\nNoi dung tai lieu 11.",
        {"doc_id": "KT-QT-011", "title": "Tai lieu 11"},
    )

    selected = tmp_path / "source" / "technical" / "procedure" / "KT-QT-011_v1.0.md"
    processed = process_sources(tmp_path, source_paths=[selected])

    assert [record.doc_id for record in processed] == ["KT-QT-011"]
    assert ManifestStore(tmp_path).get("KT-QT-010", "1.0") is None
    assert ManifestStore(tmp_path).get("KT-QT-011", "1.0") is not None


def test_scope_active_set_dry_run_does_not_mutate_manifest(tmp_path: Path) -> None:
    active_root, pdf_source, workbook_source = write_scope_fixture(tmp_path)
    write_scope_manifest(tmp_path, pdf_source, workbook_source)

    report = scope_active_set(tmp_path, active_root, dry_run=True)
    records = {record.doc_id: record for record in ManifestStore(tmp_path).load()}

    assert report["target_file_count"] == 2
    assert report["matched_record_count"] == 2
    assert report["expected_active_count"] == 2
    assert report["expected_pending_review_count"] == 1
    assert records["KT-QT-PDF"].status == "pending_review"
    assert records["KT-QT-XLSX"].status == "active"
    assert records["KT-QT-OUT"].status == "active"


def test_scope_active_set_apply_activates_only_target_hashes_and_prefers_pdf(tmp_path: Path) -> None:
    active_root, pdf_source, workbook_source = write_scope_fixture(tmp_path)
    write_scope_manifest(tmp_path, pdf_source, workbook_source)

    report = scope_active_set(tmp_path, active_root, dry_run=False, approved_by="Lead")
    records = {record.doc_id: record for record in ManifestStore(tmp_path).load()}

    assert report["after_status_counts"] == {"active": 2, "pending_review": 1}
    assert records["KT-QT-PDF"].status == "active"
    assert records["KT-QT-PDF"].approved_by == "Lead"
    assert records["KT-QT-PDF"].extra["display_code"] == "PD-TECH-A-01"
    assert records["KT-QT-PDF"].extra["source_role"] == "primary_pdf"
    assert records["KT-QT-XLSX"].status == "active"
    assert records["KT-QT-XLSX"].extra["source_role"] == "supporting_workbook"
    assert records["KT-QT-OUT"].status == "pending_review"
    assert records["KT-QT-OUT"].status_reason

    active_index = (tmp_path / "ragflow_index" / "technical_active.jsonl").read_text(encoding="utf-8")
    assert "KT-QT-PDF" in active_index
    assert "KT-QT-XLSX" in active_index
    assert "KT-QT-OUT" not in active_index

    hits = LocalRagIndex(tmp_path).search("quy trinh lap dat gom nhung buoc nao", limit=2)
    assert hits
    assert hits[0].doc_id == "KT-QT-PDF"
    assert hits[0].display_code == "PD-TECH-A-01"

    hits = LocalRagIndex(tmp_path).search("Quy trình lắp đặt gồm những bước nào?", limit=2)
    assert hits
    assert hits[0].doc_id == "KT-QT-PDF"
    assert hits[0].source_role == "primary_pdf"


def write_scope_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    active_root = tmp_path / "root_source" / "12. QUY TRINH KY THUAT"
    active_root.mkdir(parents=True)
    target_pdf = active_root / "PD-TECH-A-01. Rev 04. Quy trinh lap dat.pdf"
    target_workbook = active_root / "PD-TECH-A-01. Rev 04. Quy trinh lap dat.xlsx"
    target_pdf.write_bytes(b"pdf-installation-procedure")
    target_workbook.write_bytes(b"xlsx-installation-workbook")

    source_root = tmp_path / "source" / "technical" / "procedure"
    source_root.mkdir(parents=True)
    pdf_source = source_root / "KT-QT-PDF_v1.0.pdf"
    workbook_source = source_root / "KT-QT-XLSX_v1.0.xlsx"
    pdf_source.write_bytes(target_pdf.read_bytes())
    workbook_source.write_bytes(target_workbook.read_bytes())
    return active_root, pdf_source, workbook_source


def write_scope_manifest(tmp_path: Path, pdf_source: Path, workbook_source: Path) -> None:
    normalized_root = tmp_path / "normalized" / "technical" / "procedure"
    normalized_root.mkdir(parents=True)
    pdf_md = normalized_root / "KT-QT-PDF_v1.0.md"
    workbook_md = normalized_root / "KT-QT-XLSX_v1.0.md"
    outside_md = normalized_root / "KT-QT-OUT_v1.0.md"
    pdf_md.write_text("# PD TECH A 01 Rev 04 Quy trinh lap dat\n\nQuy trinh lap dat gom tiep nhan, lap dat va nghiem thu.", encoding="utf-8")
    workbook_md.write_text("# PD TECH A 01 Rev 04 Bang theo doi lap dat\n\nWorkbook ho tro bang tinh va checklist lap dat.", encoding="utf-8")
    outside_md.write_text("# Quy trinh ngoai pham vi\n\nTai lieu nay khong nam trong scope.", encoding="utf-8")
    outside_source = tmp_path / "source" / "technical" / "procedure" / "KT-QT-OUT_v1.0.md"
    outside_source.write_text("outside", encoding="utf-8")

    common = {
        "department": "technical",
        "category": "procedure",
        "source_type": "internal_procedure",
        "language": "vi",
        "version": "1.0",
        "effective_from": "2025-01-01",
        "owner": "Phong Ky thuat",
        "access_group": "technical",
    }
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-PDF",
                title="PD TECH A 01 Rev 04 Quy trinh lap dat",
                status="pending_review",
                source_path=str(pdf_source),
                normalized_path=str(pdf_md),
                content_hash=content_hash(pdf_source),
                **common,
            ),
            ManifestRecord(
                doc_id="KT-QT-XLSX",
                title="PD TECH A 01 Rev 04 Quy trinh lap dat",
                status="active",
                source_path=str(workbook_source),
                normalized_path=str(workbook_md),
                content_hash=content_hash(workbook_source),
                **common,
            ),
            ManifestRecord(
                doc_id="KT-QT-OUT",
                title="Quy trinh ngoai pham vi",
                status="active",
                source_path=str(outside_source),
                normalized_path=str(outside_md),
                content_hash=content_hash(outside_source),
                **common,
            ),
        ]
    )
