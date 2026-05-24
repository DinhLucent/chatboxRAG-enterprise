from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .document_qa import qa_markdown
from .manifest import ManifestStore
from .utils import content_hash, safe_filename, utc_now, write_json


DEFAULT_QA_STATUSES = {"active", "pending_review"}
DEFAULT_TAXONOMY_STATUSES = {"active", "pending_review"}
TAXONOMY_REPORT_JSON = Path("data") / "data_audit" / "taxonomy_latest.json"
TAXONOMY_REPORT_MARKDOWN = Path("docs") / "taxonomy-audit-latest.md"
TAXONOMY_REMEDIATION_JSON = Path("data") / "data_audit" / "taxonomy_remediation_plan.json"
TAXONOMY_REMEDIATION_MARKDOWN = Path("docs") / "taxonomy-remediation-plan.md"
ACTIVE_SCOPE_REPORT_JSON = Path("data") / "data_audit" / "active_scope_latest.json"
ACTIVE_SCOPE_REPORT_MARKDOWN = Path("docs") / "active-scope-latest.md"
DEFAULT_ACTIVE_SCOPE_ID = "engineering_procedures_v1"
ACTIVE_SCOPE_DISABLED_REASON = (
    "Disabled by active scope engineering_procedures_v1; awaiting review before future expansion."
)
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


def scope_active_set(
    root: Path,
    active_root: Path,
    *,
    scope_id: str = DEFAULT_ACTIVE_SCOPE_ID,
    approved_by: str = "scope-active-set",
    dry_run: bool = True,
    write_report: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    active_root = active_root if active_root.is_absolute() else root / active_root
    active_root = active_root.resolve()
    if not active_root.exists() or not active_root.is_dir():
        raise FileNotFoundError(f"Active root does not exist or is not a directory: {active_root}")

    store = ManifestStore(root)
    records = store.load()
    targets = collect_active_scope_targets(root, active_root, scope_id)
    target_by_hash = {str(target["content_hash"]): target for target in targets}
    matched_hashes: set[str] = set()
    actions: list[dict[str, Any]] = []
    now = utc_now()

    before_counts = status_counts(records)
    before_active_categories = category_counts(record for record in records if record.status == "active")

    for record in records:
        target = target_by_hash.get(record.content_hash)
        if target:
            matched_hashes.add(record.content_hash)
            changes = desired_scope_record_changes(record, target, scope_id, approved_by)
            actions.append(
                {
                    "record_key": record.key,
                    "doc_id": record.doc_id,
                    "version": record.version,
                    "action": "activate_scope_record" if changes else "keep_scope_record",
                    "changes": changes,
                    "target_file": target["relative_path"],
                    "display_code": target.get("display_code"),
                    "source_role": target["source_role"],
                }
            )
            if not dry_run and changes:
                apply_scope_record(record, target, scope_id, approved_by, now)
                write_scope_metadata_sidecar(record)
            continue

        if record.status == "active":
            actions.append(
                {
                    "record_key": record.key,
                    "doc_id": record.doc_id,
                    "version": record.version,
                    "action": "disable_to_pending_review",
                    "changes": ["status", "status_reason", "approved_by"],
                }
            )
            if not dry_run:
                record.status = "pending_review"
                record.status_reason = disabled_reason(scope_id)
                record.approved_by = None
                record.updated_at = now
        elif record.status == "pending_review":
            actions.append(
                {
                    "record_key": record.key,
                    "doc_id": record.doc_id,
                    "version": record.version,
                    "action": "keep_pending_review",
                    "changes": [],
                }
            )
        else:
            actions.append(
                {
                    "record_key": record.key,
                    "doc_id": record.doc_id,
                    "version": record.version,
                    "action": "leave_non_serving_status",
                    "status": record.status,
                    "changes": [],
                }
            )

    missing_targets = [target for target in targets if target["content_hash"] not in matched_hashes]
    expected_active_count = sum(
        1 for action in actions if action["action"] in {"activate_scope_record", "keep_scope_record"}
    )
    expected_pending_count = sum(
        1 for action in actions if action["action"] in {"disable_to_pending_review", "keep_pending_review"}
    )

    if not dry_run:
        store.save(records)
        from .pipeline import rebuild_indexes

        rebuild_indexes(root)

    after_records = store.load() if not dry_run else records
    report = {
        "generated_at": utc_now(),
        "dry_run": dry_run,
        "scope_id": scope_id,
        "active_root": str(active_root),
        "target_file_count": len(targets),
        "matched_record_count": len(matched_hashes),
        "missing_target_count": len(missing_targets),
        "expected_active_count": expected_active_count,
        "expected_pending_review_count": expected_pending_count,
        "before_status_counts": before_counts,
        "after_status_counts": status_counts(after_records) if not dry_run else None,
        "before_active_category_counts": before_active_categories,
        "after_active_category_counts": category_counts(record for record in after_records if record.status == "active")
        if not dry_run
        else None,
        "target_files": targets,
        "missing_target_files": missing_targets,
        "actions": actions,
    }
    if write_report:
        write_active_scope_reports(root, report)
    return report


def collect_active_scope_targets(root: Path, active_root: Path, scope_id: str) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for file_path in sorted(path for path in active_root.rglob("*") if path.is_file()):
        targets.append(
            {
                "relative_path": file_path.relative_to(root).as_posix()
                if is_relative_to(file_path, root)
                else str(file_path),
                "active_root_relative_path": file_path.relative_to(active_root).as_posix(),
                "source_path": str(file_path),
                "content_hash": content_hash(file_path),
                "display_code": infer_display_code(file_path),
                "source_role": source_role_for_path(file_path),
                "scope_id": scope_id,
                "suffix": file_path.suffix.lower(),
            }
        )
    return targets


def desired_scope_record_changes(record: Any, target: dict[str, Any], scope_id: str, approved_by: str) -> list[str]:
    changes = []
    expected = {
        "status": "active",
        "department": "technical",
        "category": "procedure",
        "source_type": "internal_procedure",
        "approved_by": approved_by,
    }
    for field, value in expected.items():
        if getattr(record, field) != value:
            changes.append(field)
    extra_expected = {
        "display_code": target.get("display_code"),
        "source_role": target.get("source_role"),
        "active_scope_id": scope_id,
        "active_scope_source_path": target.get("source_path"),
        "active_scope_relative_path": target.get("relative_path"),
    }
    for key, value in extra_expected.items():
        if value and record.extra.get(key) != value:
            changes.append(f"extra.{key}")
    return changes


def apply_scope_record(record: Any, target: dict[str, Any], scope_id: str, approved_by: str, updated_at: str) -> None:
    record.status = "active"
    record.status_reason = None
    record.department = "technical"
    record.category = "procedure"
    record.source_type = "internal_procedure"
    record.approved_by = approved_by
    record.updated_at = updated_at
    record.extra["active_scope_id"] = scope_id
    record.extra["active_scope_source_path"] = target["source_path"]
    record.extra["active_scope_relative_path"] = target["relative_path"]
    record.extra["source_role"] = target["source_role"]
    if target.get("display_code"):
        record.extra["display_code"] = target["display_code"]


def write_scope_metadata_sidecar(record: Any) -> None:
    source_path = Path(record.source_path)
    metadata_path = source_path.with_name(source_path.stem + ".metadata.json")
    metadata = metadata_payload_for_record(record)
    metadata["approved_by"] = record.approved_by
    for key in [
        "display_code",
        "source_role",
        "active_scope_id",
        "active_scope_source_path",
        "active_scope_relative_path",
    ]:
        if record.extra.get(key):
            metadata[key] = record.extra[key]
    write_json(metadata_path, metadata)


def infer_display_code(path: Path) -> str | None:
    text = " ".join([path.name, path.stem, *path.parts])
    match = re.search(r"\bPD[-\s]*TECH[-\s]*([A-Z])[-\s]*([0-9]{1,3})\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    return f"PD-TECH-{match.group(1).upper()}-{match.group(2)}"


def source_role_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "primary_pdf"
    if suffix == ".xlsx":
        return "supporting_workbook"
    return "supporting_file"


def disabled_reason(scope_id: str) -> str:
    if scope_id == DEFAULT_ACTIVE_SCOPE_ID:
        return ACTIVE_SCOPE_DISABLED_REASON
    return f"Disabled by active scope {scope_id}; awaiting review before future expansion."


def status_counts(records: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return counts


def category_counts(records: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.category] = counts.get(record.category, 0) + 1
    return counts


def write_active_scope_reports(root: Path, report: dict[str, Any]) -> None:
    write_json(root / ACTIVE_SCOPE_REPORT_JSON, report)
    markdown = [
        "# Active Scope Latest",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Dry run: `{report['dry_run']}`",
        f"- Scope: `{report['scope_id']}`",
        f"- Active root: `{report['active_root']}`",
        f"- Target files: `{report['target_file_count']}`",
        f"- Matched records: `{report['matched_record_count']}`",
        f"- Missing target files: `{report['missing_target_count']}`",
        f"- Expected active records: `{report['expected_active_count']}`",
        f"- Expected pending review records: `{report['expected_pending_review_count']}`",
        "",
        "## Target Files",
        "",
    ]
    targets = report.get("target_files") or []
    if targets:
        markdown.extend(["| File | Display code | Role | Matched |", "| --- | --- | --- | --- |"])
        matched_hashes = {
            action.get("display_code") or action.get("target_file")
            for action in report.get("actions") or []
            if action.get("action") in {"activate_scope_record", "keep_scope_record"}
        }
        for target in targets:
            marker = target.get("display_code") or target.get("relative_path")
            markdown.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(target.get("relative_path")),
                        markdown_cell(target.get("display_code")),
                        markdown_cell(target.get("source_role")),
                        markdown_cell(marker in matched_hashes),
                    ]
                )
                + " |"
            )
    else:
        markdown.append("No target files found.")
    target = root / ACTIVE_SCOPE_REPORT_MARKDOWN
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(markdown) + "\n", encoding="utf-8")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


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
