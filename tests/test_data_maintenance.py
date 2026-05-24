from __future__ import annotations

import json
from pathlib import Path

from poc_workflow.data_maintenance import (
    apply_taxonomy_remediation,
    audit_manifest_taxonomy,
    backfill_missing_qa_reports,
    plan_taxonomy_remediation,
)
from poc_workflow.manifest import ManifestStore
from poc_workflow.pipeline import approve_record, init_workspace, process_sources


def write_source(root: Path) -> None:
    source = root / "source" / "technical" / "procedure" / "KT-QT-020_v1.0.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# QA backfill\n\nNoi dung du de tao QA report.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-QT-020",
                "title": "QA backfill",
                "department": "technical",
                "category": "procedure",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_backfill_missing_qa_reports_updates_manifest_extra(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-020", "1.0", "Lead")

    store = ManifestStore(tmp_path)
    record = store.get("KT-QT-020", "1.0")
    assert record is not None
    qa_path = Path(record.extra["qa_report_path"])
    qa_path.unlink()
    record.extra.pop("qa_report_path", None)
    record.extra.pop("qa_status", None)
    store.upsert(record)

    result = backfill_missing_qa_reports(tmp_path)

    assert result["updated_count"] == 1
    updated = ManifestStore(tmp_path).get("KT-QT-020", "1.0")
    assert updated is not None
    assert updated.extra["qa_status"] == "pass"
    assert Path(updated.extra["qa_report_path"]).exists()


def test_backfill_missing_qa_reports_dry_run_does_not_write(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-020", "1.0", "Lead")

    store = ManifestStore(tmp_path)
    record = store.get("KT-QT-020", "1.0")
    assert record is not None
    qa_path = Path(record.extra["qa_report_path"])
    qa_path.unlink()
    record.extra.pop("qa_report_path", None)
    store.upsert(record)

    result = backfill_missing_qa_reports(tmp_path, dry_run=True)

    assert result["candidate_count"] == 1
    assert result["updated_count"] == 0
    assert not qa_path.exists()


def test_audit_manifest_taxonomy_reports_suspicious_category(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    source = tmp_path / "source" / "technical" / "faq_troubleshooting" / "KT-FAQ-900_v1.0.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Quy trình kiểm soát rủi ro\n\nNoi dung du de tao record.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-FAQ-900",
                "title": "Quy trình kiểm soát rủi ro",
                "department": "technical",
                "category": "faq_troubleshooting",
                "source_type": "faq",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-FAQ-900", "1.0", "Lead")

    report = audit_manifest_taxonomy(tmp_path)

    assert report["issue_count"] == 1
    assert report["issues"][0]["suggested_category"] == "procedure"
    assert report["issues"][0]["recommended_action"] == "review_metadata_category_then_rebuild_index"
    assert (tmp_path / "data" / "data_audit" / "taxonomy_latest.json").exists()
    assert (tmp_path / "docs" / "taxonomy-audit-latest.md").exists()


def test_audit_manifest_taxonomy_allows_native_business_doc_ids(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    source = tmp_path / "source" / "technical" / "procedure" / "PD-HR-051_v1.0.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Quy trình xin nghỉ việc\n\nNoi dung du de tao record.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "PD-HR-051",
                "title": "PD HR 051. Rev 06. Quy trình xin nghỉ việc",
                "department": "technical",
                "category": "procedure",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "PD-HR-051", "1.0", "Lead")

    report = audit_manifest_taxonomy(tmp_path)

    assert report["issue_count"] == 0


def test_plan_taxonomy_remediation_proposes_new_safe_doc_id(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    write_source(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-020", "1.0", "Lead")

    source = tmp_path / "source" / "technical" / "faq_troubleshooting" / "KT-FAQ-900_v1.0.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Quy trình kiểm soát rủi ro\n\nNoi dung du de tao record.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-FAQ-900",
                "title": "Quy trình kiểm soát rủi ro",
                "department": "technical",
                "category": "faq_troubleshooting",
                "source_type": "faq",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    process_sources(tmp_path)

    report = plan_taxonomy_remediation(tmp_path)

    assert report["action_count"] == 1
    action = report["actions"][0]
    assert action["current"]["doc_id"] == "KT-FAQ-900"
    assert action["target"]["doc_id"] == "KT-QT-021"
    assert action["target"]["category"] == "procedure"
    assert action["auto_apply_safe"] is True
    assert (tmp_path / "docs" / "taxonomy-remediation-plan.md").exists()


def test_apply_taxonomy_remediation_moves_pending_review_assets(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    source = tmp_path / "source" / "technical" / "faq_troubleshooting" / "KT-FAQ-900_v1.0.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Quy trình kiểm soát rủi ro\n\nNoi dung du de tao record.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-FAQ-900",
                "title": "Quy trình kiểm soát rủi ro",
                "department": "technical",
                "category": "faq_troubleshooting",
                "source_type": "faq",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    process_sources(tmp_path)

    result = apply_taxonomy_remediation(tmp_path, dry_run=False)

    assert result["applied_count"] == 1
    updated = ManifestStore(tmp_path).get("KT-QT-001", "1.0")
    assert updated is not None
    assert updated.category == "procedure"
    assert updated.source_type == "internal_procedure"
    assert updated.extra["original_doc_id"] == "KT-FAQ-900"
    assert Path(updated.source_path).exists()
    assert Path(updated.normalized_path).exists()
    assert Path(updated.extra["qa_report_path"]).exists()
    assert not source.exists()
    assert audit_manifest_taxonomy(tmp_path)["issue_count"] == 0
