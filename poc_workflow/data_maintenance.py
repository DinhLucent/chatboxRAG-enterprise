from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .document_qa import qa_markdown
from .manifest import ManifestStore
from .utils import safe_filename, utc_now, write_json


DEFAULT_QA_STATUSES = {"active", "pending_review"}
DEFAULT_TAXONOMY_STATUSES = {"active", "pending_review"}
TAXONOMY_REPORT_JSON = Path("data") / "data_audit" / "taxonomy_latest.json"
TAXONOMY_REPORT_MARKDOWN = Path("docs") / "taxonomy-audit-latest.md"
TAXONOMY_REMEDIATION_JSON = Path("data") / "data_audit" / "taxonomy_remediation_plan.json"
TAXONOMY_REMEDIATION_MARKDOWN = Path("docs") / "taxonomy-remediation-plan.md"
CATEGORY_DOC_ID_PREFIXES = {
    "procedure": "KT-QT-",
    "vendor_document": "KT-HANG-",
    "form_checklist": "KT-BM-",
    "faq_troubleshooting": "KT-FAQ-",
}
MANAGED_DOC_ID_PREFIX_CATEGORIES = {prefix: category for category, prefix in CATEGORY_DOC_ID_PREFIXES.items()}
SOURCE_TYPE_BY_CATEGORY = {
    "procedure": "internal_procedure",
    "vendor_document": "vendor_document",
    "form_checklist": "form_checklist",
    "faq_troubleshooting": "faq",
}
TITLE_CATEGORY_HINTS = (
    ("procedure", ("quy trình", "quy trinh")),
    ("form_checklist", ("biểu mẫu", "bieu mau", "checklist", "phiếu", "phieu", "mẫu", "mau")),
)


def backfill_missing_qa_reports(
    root: Path,
    *,
    statuses: set[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    statuses = statuses or DEFAULT_QA_STATUSES
    store = ManifestStore(root)
    records = store.load()
    updated = []
    results: list[dict[str, Any]] = []

    for record in records:
        if limit is not None and len(results) >= limit:
            break
        if record.status not in statuses:
            continue
        qa_path = qa_report_path(root, record)
        needs_report = not qa_path.exists() or not record.extra.get("qa_report_path")
        if not needs_report:
            continue
        normalized_path = Path(record.normalized_path)
        item = {
            "doc_id": record.doc_id,
            "version": record.version,
            "status": record.status,
            "normalized_path": str(normalized_path),
            "qa_report_path": str(qa_path),
            "dry_run": dry_run,
        }
        if not normalized_path.exists():
            item.update({"result": "missing_normalized", "qa_status": None})
            results.append(item)
            continue
        if dry_run:
            item.update({"result": "would_backfill", "qa_status": None})
            results.append(item)
            continue

        report = qa_markdown(normalized_path, qa_path)
        record.extra["qa_report_path"] = str(qa_path.resolve())
        record.extra["qa_status"] = report.status
        record.extra["qa_issues"] = report.issues
        record.extra["qa_corrections"] = report.corrections
        updated.append(record)
        item.update({"result": "backfilled", "qa_status": report.status, "issues": report.issues})
        results.append(item)

    if updated and not dry_run:
        store.replace_many(updated)

    return {
        "dry_run": dry_run,
        "scanned_records": len(records),
        "candidate_count": len(results),
        "updated_count": len(updated),
        "missing_normalized_count": sum(1 for item in results if item["result"] == "missing_normalized"),
        "failed_qa_count": sum(1 for item in results if item.get("qa_status") == "fail"),
        "results": results,
    }


def qa_report_path(root: Path, record: Any) -> Path:
    existing = record.extra.get("qa_report_path")
    if existing:
        path = Path(str(existing))
        return path if path.is_absolute() else root / path
    dirname = safe_filename(f"{record.doc_id}_v{record.version}")
    return root / ".Workplace" / "artifacts" / record.category / dirname / "qa_report.json"


def audit_manifest_taxonomy(
    root: Path,
    *,
    statuses: set[str] | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    statuses = statuses or DEFAULT_TAXONOMY_STATUSES
    records = ManifestStore(root).load()
    issues: list[dict[str, Any]] = []
    scanned = 0

    for record in records:
        if record.status not in statuses:
            continue
        scanned += 1
        issues.extend(taxonomy_issues_for_record(record))

    report = {
        "generated_at": utc_now(),
        "statuses": sorted(statuses),
        "scanned_records": scanned,
        "issue_count": len(issues),
        "severity_counts": severity_counts(issues),
        "issues": issues,
    }
    if write_report:
        write_taxonomy_audit_reports(root, report)
    return report


def taxonomy_issues_for_record(record: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    expected_prefix = CATEGORY_DOC_ID_PREFIXES.get(record.category)
    managed_prefix_category = managed_doc_id_prefix_category(str(record.doc_id))
    if expected_prefix and managed_prefix_category and managed_prefix_category != record.category:
        issues.append(
            taxonomy_issue(
                record,
                rule="category_doc_id_prefix",
                severity="warning",
                suggested_category=record.category,
                summary=f"{record.key} category/doc_id prefix mismatch: {record.category} expects {expected_prefix}",
                recommended_action="review_doc_id_prefix_and_canonical_family_before_reindex",
            )
        )

    normalized_title = str(record.title).casefold()
    for expected_category, title_hints in TITLE_CATEGORY_HINTS:
        if record.category != expected_category and any(hint in normalized_title for hint in title_hints):
            issues.append(
                taxonomy_issue(
                    record,
                    rule="title_category_hint",
                    severity="warning",
                    suggested_category=expected_category,
                    summary=(
                        f"{record.key} title suggests {expected_category} "
                        f"but category is {record.category}: {record.title}"
                    ),
                    recommended_action="review_metadata_category_then_rebuild_index",
                )
            )
            break

    return issues


def managed_doc_id_prefix_category(doc_id: str) -> str | None:
    for prefix, category in MANAGED_DOC_ID_PREFIX_CATEGORIES.items():
        if doc_id.startswith(prefix):
            return category
    return None


def taxonomy_issue(
    record: Any,
    *,
    rule: str,
    severity: str,
    suggested_category: str,
    summary: str,
    recommended_action: str,
) -> dict[str, Any]:
    return {
        "record_key": record.key,
        "doc_id": record.doc_id,
        "version": record.version,
        "status": record.status,
        "title": record.title,
        "current_category": record.category,
        "suggested_category": suggested_category,
        "rule": rule,
        "severity": severity,
        "summary": summary,
        "recommended_action": recommended_action,
        "source_path": record.source_path,
        "normalized_path": record.normalized_path,
    }


def severity_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        severity = str(issue.get("severity") or "unknown")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def write_taxonomy_audit_reports(root: Path, report: dict[str, Any]) -> None:
    write_json(root / TAXONOMY_REPORT_JSON, report)
    markdown = [
        "# Taxonomy Audit Latest",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Statuses: `{', '.join(report['statuses'])}`",
        f"- Scanned records: `{report['scanned_records']}`",
        f"- Issues: `{report['issue_count']}`",
        "",
        "## Issues",
        "",
    ]
    issues = report.get("issues") or []
    if not issues:
        markdown.append("No taxonomy issues detected.")
    else:
        markdown.extend(
            [
                "| Record | Current | Suggested | Rule | Title |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for issue in issues:
            markdown.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(issue["record_key"]),
                        markdown_cell(issue["current_category"]),
                        markdown_cell(issue["suggested_category"]),
                        markdown_cell(issue["rule"]),
                        markdown_cell(issue["title"]),
                    ]
                )
                + " |"
            )
    target = root / TAXONOMY_REPORT_MARKDOWN
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(markdown) + "\n", encoding="utf-8")


def markdown_cell(value: object) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ").strip()


def plan_taxonomy_remediation(
    root: Path,
    *,
    statuses: set[str] | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    statuses = statuses or DEFAULT_TAXONOMY_STATUSES
    records = ManifestStore(root).load()
    records_by_key = {record.key: record for record in records}
    reserved_doc_ids = {str(record.doc_id) for record in records}
    issues = audit_manifest_taxonomy(root, statuses=statuses, write_report=False).get("issues") or []
    actions: list[dict[str, Any]] = []

    for issue in issues:
        if issue.get("rule") != "title_category_hint":
            continue
        record = records_by_key.get(str(issue["record_key"]))
        if not record:
            continue
        target_category = str(issue["suggested_category"])
        target_doc_id = next_doc_id(records, target_category, reserved_doc_ids)
        reserved_doc_ids.add(target_doc_id)
        actions.append(remediation_action(root, record, target_category, target_doc_id, str(issue["summary"])))

    report = {
        "generated_at": utc_now(),
        "statuses": sorted(statuses),
        "action_count": len(actions),
        "actions": actions,
    }
    if write_report:
        write_taxonomy_remediation_reports(root, report)
    return report


def next_doc_id(records: list[Any], category: str, reserved_doc_ids: set[str]) -> str:
    prefix = CATEGORY_DOC_ID_PREFIXES[category]
    max_number = 0
    for record in records:
        doc_id = str(record.doc_id)
        if not doc_id.startswith(prefix):
            continue
        suffix = doc_id.removeprefix(prefix)
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    candidate = max_number + 1
    while True:
        doc_id = f"{prefix}{candidate:03d}"
        if doc_id not in reserved_doc_ids:
            return doc_id
        candidate += 1


def remediation_action(root: Path, record: Any, target_category: str, target_doc_id: str, reason: str) -> dict[str, Any]:
    source_path = Path(record.source_path)
    normalized_path = Path(record.normalized_path)
    target_source = root / "source" / "technical" / target_category / f"{target_doc_id}_v{record.version}{source_path.suffix}"
    target_metadata = target_source.with_name(target_source.stem + ".metadata.json")
    target_normalized = root / "normalized" / "technical" / target_category / f"{target_doc_id}_v{record.version}.md"
    target_artifact = root / ".Workplace" / "artifacts" / target_category / safe_filename(f"{target_doc_id}_v{record.version}")
    qa_path = qa_report_path(root, record)
    target_qa = target_artifact / "qa_report.json"
    conflicts = [
        str(path)
        for path in [target_source, target_metadata, target_normalized, target_qa]
        if path.exists()
    ]
    return {
        "record_key": record.key,
        "status": record.status,
        "reason": reason,
        "current": {
            "doc_id": record.doc_id,
            "category": record.category,
            "source_type": record.source_type,
            "source_path": str(source_path),
            "metadata_path": str(source_path.with_name(source_path.stem + ".metadata.json")),
            "normalized_path": str(normalized_path),
            "qa_report_path": str(qa_path),
        },
        "target": {
            "doc_id": target_doc_id,
            "category": target_category,
            "source_type": SOURCE_TYPE_BY_CATEGORY[target_category],
            "source_path": str(target_source),
            "metadata_path": str(target_metadata),
            "normalized_path": str(target_normalized),
            "qa_report_path": str(target_qa),
        },
        "conflicts": conflicts,
        "auto_apply_safe": not conflicts and record.status == "pending_review",
        "requires_review": record.status == "active" or bool(conflicts),
    }


def write_taxonomy_remediation_reports(root: Path, report: dict[str, Any]) -> None:
    write_json(root / TAXONOMY_REMEDIATION_JSON, report)
    markdown = [
        "# Taxonomy Remediation Plan",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Statuses: `{', '.join(report['statuses'])}`",
        f"- Actions: `{report['action_count']}`",
        "",
        "## Actions",
        "",
    ]
    actions = report.get("actions") or []
    if not actions:
        markdown.append("No remediation actions proposed.")
    else:
        markdown.extend(
            [
                "| Record | Status | Current | Target | Auto Apply Safe | Reason |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for action in actions:
            current = action["current"]
            target = action["target"]
            markdown.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(action["record_key"]),
                        markdown_cell(action["status"]),
                        markdown_cell(f"{current['doc_id']} / {current['category']}"),
                        markdown_cell(f"{target['doc_id']} / {target['category']}"),
                        markdown_cell(action["auto_apply_safe"]),
                        markdown_cell(action["reason"]),
                    ]
                )
                + " |"
            )
    target = root / TAXONOMY_REMEDIATION_MARKDOWN
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(markdown) + "\n", encoding="utf-8")


def apply_taxonomy_remediation(
    root: Path,
    *,
    statuses: set[str] | None = None,
    dry_run: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    store = ManifestStore(root)
    records = store.load()
    records_by_key = {record.key: record for record in records}
    plan = plan_taxonomy_remediation(root, statuses=statuses, write_report=True)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for action in plan.get("actions") or []:
        if limit is not None and len(applied) >= limit:
            break
        if not action.get("auto_apply_safe"):
            skipped.append({"record_key": action["record_key"], "reason": "requires_review"})
            continue
        record = records_by_key.get(str(action["record_key"]))
        if not record:
            skipped.append({"record_key": action["record_key"], "reason": "record_not_found"})
            continue
        if action.get("conflicts"):
            skipped.append({"record_key": action["record_key"], "reason": "target_conflict", "conflicts": action["conflicts"]})
            continue
        if dry_run:
            applied.append({"record_key": action["record_key"], "result": "would_apply", "target": action["target"]})
            continue

        apply_single_taxonomy_action(root, record, action)
        applied.append({"record_key": action["record_key"], "result": "applied", "target": action["target"]})

    if applied and not dry_run:
        store.save(records)
        from .pipeline import rebuild_indexes

        rebuild_indexes(root)
        plan_taxonomy_remediation(root, statuses=statuses, write_report=True)

    return {
        "dry_run": dry_run,
        "planned_count": int(plan.get("action_count") or 0),
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "applied": applied,
        "skipped": skipped,
    }


def apply_single_taxonomy_action(root: Path, record: Any, action: dict[str, Any]) -> None:
    current = action["current"]
    target = action["target"]
    current_source = assert_workspace_path(root, Path(current["source_path"]))
    current_metadata = assert_workspace_path(root, Path(current["metadata_path"]))
    current_normalized = assert_workspace_path(root, Path(current["normalized_path"]))
    current_qa = assert_workspace_path(root, Path(current["qa_report_path"]))
    target_source = assert_workspace_path(root, Path(target["source_path"]))
    target_metadata = assert_workspace_path(root, Path(target["metadata_path"]))
    target_normalized = assert_workspace_path(root, Path(target["normalized_path"]))
    target_qa = assert_workspace_path(root, Path(target["qa_report_path"]))

    move_if_exists(current_source, target_source)
    move_if_exists(current_normalized, target_normalized)
    move_if_exists(current_qa, target_qa)

    metadata = metadata_payload_for_record(record)
    if current_metadata.exists():
        metadata.update(json.loads(current_metadata.read_text(encoding="utf-8")))
        current_metadata.unlink()
    metadata.update(
        {
            "doc_id": target["doc_id"],
            "category": target["category"],
            "source_type": target["source_type"],
            "original_doc_id": record.doc_id,
            "original_category": record.category,
        }
    )
    write_json(target_metadata, metadata)

    original_doc_id = record.doc_id
    original_category = record.category
    record.doc_id = target["doc_id"]
    record.category = target["category"]
    record.source_type = target["source_type"]
    record.source_path = str(target_source)
    record.normalized_path = str(target_normalized)
    record.updated_at = utc_now()
    record.extra["qa_report_path"] = str(target_qa)
    record.extra["original_doc_id"] = original_doc_id
    record.extra["original_category"] = original_category
    record.extra["taxonomy_remediation_reason"] = action["reason"]
    record.extra["taxonomy_remediated_at"] = record.updated_at


def metadata_payload_for_record(record: Any) -> dict[str, Any]:
    return {
        "doc_id": record.doc_id,
        "title": record.title,
        "department": record.department,
        "category": record.category,
        "source_type": record.source_type,
        "language": record.language,
        "version": record.version,
        "effective_from": record.effective_from,
        "review_at": record.review_at,
        "owner": record.owner,
        "access_group": record.access_group,
    }


def move_if_exists(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if target.exists():
        raise FileExistsError(f"Target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))


def assert_workspace_path(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Refusing to edit path outside workspace: {resolved}")
    return resolved
