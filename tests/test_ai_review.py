from __future__ import annotations

import json
from pathlib import Path

from poc_workflow.ai_review import ai_review_pending_records, refill_quality_for_ai_review
from poc_workflow.manifest import ManifestStore
from poc_workflow.models import ManifestRecord
from poc_workflow.utils import content_hash, write_json


def test_ai_review_can_approve_quality_passed_record_with_explicit_override(tmp_path: Path) -> None:
    normalized = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-002_rev04.md"
    source = tmp_path / "staging" / "source.xlsx"
    citation_map = tmp_path / "indexes" / "KT-QT-002_rev04_citation_map.json"
    quality_report = tmp_path / "indexes" / "KT-QT-002_rev04_quality_report.json"
    review_path = tmp_path / "review" / "KT-QT-002_rev04" / "human_review.json"
    normalized.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    normalized.write_text(
        "# Quy trình bảo dưỡng\n\n"
        "## Quy trình thực hiện\n\n"
        "Bước 1. Lập kế hoạch bảo dưỡng định kỳ cho thiết bị.\n\n"
        "Bước 2. Thực hiện bảo dưỡng, ghi nhận kết quả và lưu hồ sơ theo biểu mẫu.",
        encoding="utf-8",
    )
    source.write_text("source", encoding="utf-8")
    write_json(
        citation_map,
        [
            {
                "anchor_id": "a1",
                "source_json": "content_list_v2",
                "source_locator": {"type": "mineru", "page_start": 1, "page_end": 1},
            }
        ],
    )
    write_json(
        quality_report,
        {
            "quality_status": "passed",
            "quality_gates": {
                "no_synthetic_heading": True,
                "no_prompt_or_status_leak": True,
                "source_locator_coverage": 1.0,
                "mineru_sidecars_parsed_for_citation": True,
                "mineru_source_jsons_used": ["content_list_v2"],
            },
        },
    )
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-002",
                title="Quy trình bảo dưỡng",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="rev04",
                status="pending_review",
                effective_from="2026-05-28",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path=str(source),
                normalized_path=str(normalized),
                content_hash=content_hash(source),
                extra={
                    "ingest_policy": "primary_source_only",
                    "quality_status": "passed",
                    "citation_map_path": str(citation_map),
                    "quality_report_path": str(quality_report),
                    "human_review_path": str(review_path),
                    "primary_source_decision": {"selected": "xlsx", "reason": "test"},
                },
            )
        ]
    )

    dry_run = ai_review_pending_records(tmp_path)
    assert dry_run["eligible_count"] == 1

    applied = ai_review_pending_records(tmp_path, apply=True)
    assert applied["applied_count"] == 1
    record = ManifestStore(tmp_path).get("KT-QT-002", "rev04")
    assert record is not None
    assert record.status == "active"
    assert record.approved_by == "ai-agent-reviewer"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["ai_reviewer_override"] is True
    assert review["review_policy"] == "user_requested_ai_review_skip_human_gate"


def test_ai_review_writes_review_path_when_record_has_no_human_review_path(tmp_path: Path) -> None:
    normalized = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-010_rev01.md"
    source = tmp_path / "staging" / "source.xlsx"
    citation_map = tmp_path / "indexes" / "KT-QT-010_rev01_citation_map.json"
    quality_report = tmp_path / "indexes" / "KT-QT-010_rev01_quality_report.json"
    normalized.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    normalized.write_text(
        "# Quy trinh kiem tra\n\n"
        "## Quy trinh thuc hien\n\n"
        "Buoc 1. Tiep nhan yeu cau va kiem tra thong tin.\n\n"
        "Buoc 2. Ghi nhan ket qua vao ho so theo bieu mau lien quan.",
        encoding="utf-8",
    )
    source.write_text("source", encoding="utf-8")
    write_json(
        citation_map,
        [
            {
                "anchor_id": "a1",
                "source_json": "content_list_v2",
                "source_locator": {"type": "mineru", "page_start": 1, "page_end": 1},
            }
        ],
    )
    write_json(
        quality_report,
        {
            "quality_status": "passed",
            "quality_gates": {
                "no_synthetic_heading": True,
                "no_prompt_or_status_leak": True,
                "source_locator_coverage": 1.0,
                "mineru_sidecars_parsed_for_citation": True,
                "mineru_source_jsons_used": ["content_list_v2"],
            },
        },
    )
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-010",
                title="Quy trinh kiem tra",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="rev01",
                status="pending_review",
                effective_from="2026-05-28",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path=str(source),
                normalized_path=str(normalized),
                content_hash=content_hash(source),
                extra={
                    "artifact_stem": "KT-QT-010_rev01",
                    "ingest_policy": "primary_source_only",
                    "quality_status": "passed",
                    "citation_map_path": str(citation_map),
                    "quality_report_path": str(quality_report),
                    "primary_source_decision": {"selected": "xlsx", "reason": "test"},
                },
            )
        ]
    )

    applied = ai_review_pending_records(tmp_path, apply=True)
    assert applied["applied_count"] == 1
    record = ManifestStore(tmp_path).get("KT-QT-010", "rev01")
    assert record is not None
    assert record.status == "active"
    review_path = Path(str(record.extra["human_review_path"]))
    assert review_path.exists()
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["reviewer"] == "ai-agent-reviewer"


def test_ai_refill_quality_promotes_stale_source_text_issue_with_mineru_evidence(tmp_path: Path) -> None:
    normalized = tmp_path / "normalized" / "warehouse_gdp" / "procedure" / "BM-029.01_rev03.md"
    source = tmp_path / "staging" / "source.docx"
    citation_map = tmp_path / "indexes" / "BM-029.01_rev03_citation_map.json"
    quality_report = tmp_path / "indexes" / "BM-029.01_rev03_quality_report.json"
    normalized.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    normalized.write_text(
        "# Bao cao han dung va chat luong thuoc\n\n"
        "## Noi dung bao cao\n\n"
        "Tai lieu ghi nhan thong tin han dung, tinh trang chat luong va ket qua xu ly theo tung lo thuoc.",
        encoding="utf-8",
    )
    source.write_text("source", encoding="utf-8")
    write_json(
        citation_map,
        [
            {
                "anchor_id": "a1",
                "source_json": "middle_json",
                "source_locator": {"type": "mineru", "page_start": 1, "page_end": 1},
            },
            {
                "anchor_id": "a2",
                "source_json": "model_json",
                "source_locator": {"type": "mineru", "page_start": 1, "page_end": 1},
            },
        ],
    )
    write_json(
        quality_report,
        {
            "quality_status": "needs_review",
            "issues": [
                {"type": "source_output_qa_failed", "severity": "high", "details": ["source_text_unavailable"]},
                {"type": "low_source_locator_coverage", "severity": "high", "coverage": 0.5},
            ],
            "quality_gates": {
                "source_locator_coverage": 0.5,
                "mineru_rich_metadata_available": True,
                "mineru_sidecars_parsed_for_citation": True,
                "mineru_source_block_summary": {
                    "block_count": 4,
                    "has_content_list": True,
                    "has_middle_json": True,
                    "has_model_json": True,
                },
            },
        },
    )
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="BM-029.01",
                title="Bao cao han dung va chat luong thuoc",
                department="warehouse_gdp",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="rev03",
                status="pending_review",
                effective_from="2026-05-28",
                owner="Kho GDP",
                access_group="warehouse_gdp",
                source_path=str(source),
                normalized_path=str(normalized),
                content_hash=content_hash(source),
                extra={
                    "ingest_policy": "primary_source_only",
                    "citation_map_path": str(citation_map),
                    "quality_report_path": str(quality_report),
                    "primary_source_decision": {"selected": "docx", "reason": "test"},
                },
            )
        ]
    )

    dry_run = refill_quality_for_ai_review(tmp_path)
    assert dry_run["refillable_count"] == 1

    applied = refill_quality_for_ai_review(tmp_path, apply=True)
    assert applied["applied_count"] == 1
    record = ManifestStore(tmp_path).get("BM-029.01", "rev03")
    assert record is not None
    assert record.extra["quality_status"] == "passed"
    report = json.loads(quality_report.read_text(encoding="utf-8"))
    assert report["quality_status"] == "passed"
    issue_types = {issue["type"] for issue in report["issues"]}
    assert "source_text_unavailable_validated_by_mineru_sidecars" in issue_types
    assert "stale_low_source_locator_coverage_repaired" in issue_types
