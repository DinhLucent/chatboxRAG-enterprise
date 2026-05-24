from __future__ import annotations

from pathlib import Path

import pytest

from poc_workflow.intake import prepare_inbox, requeue_ocr_required
from poc_workflow.manifest import ManifestStore
from poc_workflow.pipeline import init_workspace, process_sources


def test_prepare_inbox_drafts_metadata_and_processes_to_pending_review(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    incoming = tmp_path / "inbox" / "procedure" / "quy_trinh_bao_tri_v1.0.md"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    incoming.write_text("# Quy trinh bao tri\n\nNoi dung bao tri thiet bi dinh ky.", encoding="utf-8")

    report = prepare_inbox(tmp_path)

    assert report["prepared_count"] == 1
    metadata = report["prepared"][0]["metadata"]
    assert metadata["category"] == "procedure"
    assert metadata["doc_id"] == "KT-QT-001"
    assert metadata["version"] == "1.0"
    assert Path(report["prepared"][0]["metadata_path"]).exists()

    processed = process_sources(tmp_path)

    assert len(processed) == 1
    assert processed[0].status == "pending_review"
    assert ManifestStore(tmp_path).get("KT-QT-001", "1.0") is not None


def test_prepare_inbox_respects_sidecar_metadata(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    incoming = tmp_path / "inbox" / "manual-a.md"
    incoming.write_text("# Manual A\n\nTai lieu huong dan thiet bi A.", encoding="utf-8")
    incoming.with_name("manual-a.metadata.json").write_text(
        """
{
  "doc_id": "KT-HANG-101",
  "title": "Manual thiet bi A",
  "department": "technical",
  "category": "vendor_document",
  "source_type": "vendor_document",
  "language": "vi",
  "version": "2.0",
  "effective_from": "2025-01-01",
  "review_at": "2025-12-31",
  "owner": "Phong Ky thuat",
  "access_group": "technical"
}
""".strip(),
        encoding="utf-8",
    )

    report = prepare_inbox(tmp_path)

    metadata = report["prepared"][0]["metadata"]
    assert metadata["doc_id"] == "KT-HANG-101"
    assert metadata["category"] == "vendor_document"
    assert metadata["version"] == "2.0"


def test_prepare_inbox_avoids_duplicate_inferred_doc_id(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    existing = tmp_path / "inbox" / "procedure" / "PD-HR-051_v1.0.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("# Quy trinh HR\n\nNoi dung hien hanh.", encoding="utf-8")
    prepare_inbox(tmp_path)
    processed = process_sources(tmp_path)
    assert processed[0].doc_id == "PD-HR-051"

    duplicate = tmp_path / "inbox" / "procedure" / "PD-HR-051_rev06.pdf"
    duplicate.write_text("fake pdf text source", encoding="utf-8")
    report = prepare_inbox(tmp_path)

    metadata = report["prepared"][0]["metadata"]
    assert metadata["doc_id"] == "KT-QT-001"


def test_prepare_inbox_ignores_ocr_required_lifecycle_folder(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    incoming = tmp_path / "inbox" / "procedure" / "ocr_required" / "scan.pdf"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    incoming.write_bytes(b"%PDF-1.4\n")

    report = prepare_inbox(tmp_path)

    assert report["prepared_count"] == 0
    assert not list((tmp_path / "source").rglob("scan*"))


def test_requeue_ocr_required_moves_small_batch_only(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    small = tmp_path / "inbox" / "procedure" / "ocr_required" / "small.pdf"
    large = tmp_path / "inbox" / "procedure" / "ocr_required" / "large.pdf"
    other = tmp_path / "inbox" / "vendor_document" / "ocr_required" / "manual.pdf"
    small.parent.mkdir(parents=True, exist_ok=True)
    other.parent.mkdir(parents=True, exist_ok=True)
    small.write_bytes(b"small")
    large.write_bytes(b"large content")
    other.write_bytes(b"manual")

    result = requeue_ocr_required(tmp_path, limit=1, category="procedure")

    assert result["selected_count"] == 1
    assert result["moved"][0]["file_name"] == "small.pdf"
    assert (tmp_path / "inbox" / "procedure" / "small.pdf").exists()
    assert large.exists()
    assert other.exists()


def test_requeue_ocr_required_rejects_large_batch(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    with pytest.raises(ValueError, match="limit must be <= 5"):
        requeue_ocr_required(tmp_path, limit=6)
