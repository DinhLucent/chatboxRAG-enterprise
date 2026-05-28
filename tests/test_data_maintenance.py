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


def test_audit_manifest_taxonomy_reports_done_upload_missing_manifest(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    done = tmp_path / "inbox" / "procedure" / "done"
    done.mkdir(parents=True)
    (done / "PD-TECH-A-02. Rev 04. Quy trinh bao duong.pdf").write_bytes(b"pdf")

    report = audit_manifest_taxonomy(tmp_path)

    assert any(issue["rule"] == "processed_upload_missing_manifest_record" for issue in report["issues"])
    issue = next(issue for issue in report["issues"] if issue["rule"] == "processed_upload_missing_manifest_record")
    assert issue["record_key"] == "KT-QT-002::rev04"
    assert issue["display_code"] == "PD-TECH-A-02"
    assert issue["severity"] == "blocker"


def test_audit_manifest_taxonomy_reports_orphan_index_metadata(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    metadata_path = tmp_path / "indexes" / "KT-QT-002_rev04_metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "artifact_schema_version": "upload_rag_metadata_v1",
                "document": {
                    "doc_id": "KT-QT-002",
                    "version": "rev04",
                    "display_code": "BM-046.02",
                    "title": "Bao cao giai trinh su co",
                    "department": "technical",
                    "category": "faq_troubleshooting",
                    "status": "pending_review",
                    "primary_source_path": str(tmp_path / "staging" / "BM-046.02.xlsx"),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = audit_manifest_taxonomy(tmp_path)

    assert any(issue["rule"] == "orphan_index_metadata" for issue in report["issues"])
    issue = next(issue for issue in report["issues"] if issue["rule"] == "orphan_index_metadata")
    assert issue["record_key"] == "KT-QT-002::rev04"
    assert issue["display_code"] == "BM-046.02"
    assert issue["severity"] == "blocker"


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


def test_plan_taxonomy_remediation_preserves_department_and_business_doc_id(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    source = tmp_path / "source" / "app" / "faq_troubleshooting" / "PD-APP-A-02_vrev01.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Quy trinh khac phuc su co\n\nNoi dung du de tao record.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "PD-APP-A-02",
                "title": "Quy trinh khac phuc su co",
                "department": "app",
                "category": "faq_troubleshooting",
                "source_type": "faq",
                "language": "vi",
                "version": "rev01",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "app",
                "display_code": "PD-APP-A-02",
                "canonical_business_code": "PD-APP-A-02",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    process_sources(tmp_path)

    report = plan_taxonomy_remediation(tmp_path)

    assert report["action_count"] == 1
    action = report["actions"][0]
    assert action["target"]["doc_id"] == "PD-APP-A-02"
    assert action["target"]["department"] == "app"
    assert action["target"]["category"] == "procedure"
    assert Path(action["target"]["source_path"]).parts[-4:-1] == ("source", "app", "procedure")
    assert Path(action["target"]["normalized_path"]).parts[-4:-1] == ("normalized", "app", "procedure")
    assert "source\\technical" not in action["target"]["source_path"]


def test_plan_taxonomy_remediation_keeps_form_code_native_for_department(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    source = tmp_path / "source" / "warehouse_gdp" / "procedure" / "BM-001_vrev01.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Phieu truy tim nguon goc\n\nNoi dung du de tao record.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "BM-001",
                "title": "Phieu truy tim nguon goc",
                "department": "warehouse_gdp",
                "category": "procedure",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "rev01",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "warehouse_gdp",
                "display_code": "BM-001",
                "canonical_business_code": "BM-001",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    process_sources(tmp_path)

    report = plan_taxonomy_remediation(tmp_path)

    assert report["action_count"] == 1
    action = report["actions"][0]
    assert action["target"]["doc_id"] == "BM-001"
    assert action["target"]["department"] == "warehouse_gdp"
    assert action["target"]["category"] == "form_checklist"
    assert Path(action["target"]["source_path"]).parts[-4:-1] == ("source", "warehouse_gdp", "form_checklist")
    assert "KT-BM-" not in action["target"]["doc_id"]


def test_plan_taxonomy_remediation_requires_review_when_current_source_missing(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    source = tmp_path / "source" / "app" / "faq_troubleshooting" / "PD-APP-A-02_vrev01.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Quy trinh khac phuc su co\n\nNoi dung du de tao record.", encoding="utf-8")
    source.with_name(source.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "PD-APP-A-02",
                "title": "Quy trinh khac phuc su co",
                "department": "app",
                "category": "faq_troubleshooting",
                "source_type": "faq",
                "language": "vi",
                "version": "rev01",
                "effective_from": "2026-01-01",
                "owner": "Quality",
                "access_group": "app",
                "display_code": "PD-APP-A-02",
                "canonical_business_code": "PD-APP-A-02",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    process_sources(tmp_path)
    source.unlink()

    report = plan_taxonomy_remediation(tmp_path)

    action = report["actions"][0]
    assert action["auto_apply_safe"] is False
    assert action["requires_review"] is True
    assert any("missing current source" in conflict for conflict in action["conflicts"])


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
