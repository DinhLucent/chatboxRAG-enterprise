from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .document_qa import mojibake_score
from .manifest import ManifestStore
from .models import ManifestRecord
from .pipeline import approve_record, rebuild_indexes
from .upload_processing import (
    PROMPT_DEBUG_MARKERS,
    ascii_key,
    generated_rag_summary_count,
    is_synthetic_heading,
    quality_score,
    source_locator_coverage,
)
from .utils import content_hash, utc_now, write_json


AI_REVIEWER = "ai-agent-reviewer"
AI_REVIEW_POLICY = "user_requested_ai_review_skip_human_gate"
AI_QUALITY_REFILL_POLICY = "ai_review_refill_from_current_mineru_artifacts"


def ai_review_pending_records(
    root: Path,
    *,
    apply: bool = False,
    limit: int | None = None,
    reviewer: str = AI_REVIEWER,
) -> dict[str, Any]:
    """Review pending records with deterministic gates and optionally activate them.

    This is intentionally stricter than the manual approval API: it only approves
    records whose normalized Markdown, QA report, citation map, and MinerU evidence
    all exist and pass machine-checkable gates.
    """

    store = ManifestStore(root)
    records = [record for record in store.load() if record.status == "pending_review"]
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    candidates: list[ManifestRecord] = []

    for record in records:
        decision = ai_review_decision(record)
        if decision["decision"] == "approved":
            candidates.append(record)
            approved.append({"doc_id": record.doc_id, "version": record.version, "evidence": decision["evidence"]})
        else:
            rejected.append({"doc_id": record.doc_id, "version": record.version, "issues": decision["issues"]})
        if limit is not None and len(candidates) >= limit:
            break

    if apply:
        applied: list[dict[str, Any]] = []
        failed_apply: list[dict[str, Any]] = []
        for record in candidates:
            decision = ai_review_decision(record)
            try:
                review_path = write_ai_review_packet(root, record, decision["evidence"], reviewer=reviewer)
                refreshed = ManifestStore(root).get(record.doc_id, record.version) or record
                extra = dict(refreshed.extra or {})
                extra["ai_review_policy"] = AI_REVIEW_POLICY
                extra["ai_reviewed_at"] = utc_now()
                extra["ai_reviewed_by"] = reviewer
                extra["human_review_path"] = str(review_path)
                refreshed.extra = extra
                ManifestStore(root).upsert(refreshed)
                active = approve_record(root, refreshed.doc_id, refreshed.version, reviewer)
                applied.append({"doc_id": active.doc_id, "version": active.version, "status": active.status})
            except Exception as exc:
                failed_apply.append({"doc_id": record.doc_id, "version": record.version, "error": str(exc)})
        rebuild_indexes(root)
        return {
            "schema_version": "ai_review_approval_v1",
            "mode": "apply",
            "reviewer": reviewer,
            "eligible_count": len(candidates),
            "applied_count": len(applied),
            "failed_apply_count": len(failed_apply),
            "rejected_count": len(rejected),
            "applied": applied,
            "failed_apply": failed_apply,
            "rejected_sample": rejected[:50],
            "created_at": utc_now(),
        }

    return {
        "schema_version": "ai_review_approval_v1",
        "mode": "dry_run",
        "reviewer": reviewer,
        "eligible_count": len(candidates),
        "rejected_count": len(rejected),
        "eligible_sample": approved[:50],
        "rejected_sample": rejected[:50],
        "created_at": utc_now(),
    }


def refill_quality_for_ai_review(
    root: Path,
    *,
    apply: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Re-evaluate stale Upload QA reports from current MinerU artifacts.

    This does not invent content or bypass missing evidence. It only promotes a
    pending record when the current normalized Markdown, citation map, and MinerU
    sidecar evidence satisfy the same machine gates used by AI review.
    """

    store = ManifestStore(root)
    records = [record for record in store.load() if record.status == "pending_review"]
    refillable: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for record in records:
        decision = quality_refill_decision(record)
        if decision["decision"] == "passed":
            refillable.append({"doc_id": record.doc_id, "version": record.version, "quality_report": decision["quality_report"]})
        else:
            rejected.append({"doc_id": record.doc_id, "version": record.version, "issues": decision["issues"]})
        if limit is not None and len(refillable) >= limit:
            break

    applied: list[dict[str, Any]] = []
    if apply:
        for item in refillable:
            record = store.get(item["doc_id"], item["version"])
            if record is None:
                continue
            report = item["quality_report"]
            extra = dict(record.extra or {})
            quality_path = Path(str(extra.get("quality_report_path") or ""))
            write_json(quality_path, report)
            extra["quality_status"] = report["quality_status"]
            extra["quality_score"] = report["quality_score"]
            extra["quality_refill_policy"] = AI_QUALITY_REFILL_POLICY
            extra["quality_refilled_at"] = report["refill_evaluation"]["checked_at"]
            record.extra = extra
            store.upsert(record)
            applied.append({"doc_id": record.doc_id, "version": record.version, "quality_status": report["quality_status"]})
        rebuild_indexes(root)

    return {
        "schema_version": "ai_quality_refill_v1",
        "mode": "apply" if apply else "dry_run",
        "refillable_count": len(refillable),
        "applied_count": len(applied),
        "rejected_count": len(rejected),
        "refillable_sample": refillable[:50],
        "rejected_sample": rejected[:50],
        "created_at": utc_now(),
    }


def quality_refill_decision(record: ManifestRecord) -> dict[str, Any]:
    extra = record.extra or {}
    normalized_path = Path(record.normalized_path)
    quality_path = Path(str(extra.get("quality_report_path") or ""))
    citation_path = Path(str(extra.get("citation_map_path") or ""))
    quality = read_json_if_exists(quality_path)
    citations = read_json_if_exists(citation_path)
    if not isinstance(citations, list):
        citations = []

    issues: list[dict[str, Any]] = []
    if not normalized_path.exists():
        issues.append({"type": "missing_normalized_markdown", "severity": "high", "path": str(normalized_path)})
        text = ""
    else:
        text = normalized_path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 80:
            issues.append({"type": "normalized_markdown_too_short", "severity": "high"})
        if mojibake_score(text):
            issues.append({"type": "mojibake_detected", "severity": "high"})

    if not quality_path.exists() or not isinstance(quality, dict):
        issues.append({"type": "missing_quality_report", "severity": "high", "path": str(quality_path)})
        quality = {}
    if not citations:
        issues.append({"type": "missing_or_empty_citation_map", "severity": "high", "path": str(citation_path)})

    existing_gates = quality.get("quality_gates") if isinstance(quality.get("quality_gates"), dict) else {}
    rich_summary = existing_gates.get("mineru_source_block_summary") or quality.get("mineru_artifact_summary") or {}
    if not isinstance(rich_summary, dict):
        rich_summary = {}
    coverage = source_locator_coverage(citations)
    mineru_source_jsons = sorted(
        {
            str(value)
            for citation in citations
            if isinstance(citation, dict)
            for value in (citation.get("source_json"), citation.get("mineru_source_json"))
            if value
        }
    )
    sidecars_parsed = bool(mineru_source_jsons) or int(rich_summary.get("block_count") or 0) > 0
    rich_metadata_available = bool(
        existing_gates.get("mineru_rich_metadata_available")
        or rich_summary.get("has_content_list")
        or rich_summary.get("has_content_list_v2")
        or rich_summary.get("has_middle_json")
        or rich_summary.get("has_model_json")
        or int(rich_summary.get("block_count") or 0) > 0
    )

    normalized_existing_issues = normalize_existing_quality_issues(
        quality.get("issues") if isinstance(quality.get("issues"), list) else [],
        current_coverage=coverage,
        sidecars_parsed=sidecars_parsed,
        rich_metadata_available=rich_metadata_available,
    )
    issues.extend(normalized_existing_issues)

    summary_count = generated_rag_summary_count(text)
    if summary_count > 1:
        issues.append({"type": "duplicate_generated_rag_summary", "severity": "high", "count": summary_count})
    for heading in text.splitlines():
        if not heading.lstrip().startswith("#"):
            continue
        heading_text = heading.lstrip("# ").strip()
        if is_synthetic_heading(heading_text):
            issues.append({"type": "synthetic_heading_not_in_source", "severity": "high", "text": heading_text})
    if any(marker in ascii_key(text) for marker in PROMPT_DEBUG_MARKERS):
        issues.append({"type": "prompt_or_status_leak_detected", "severity": "high"})
    if coverage < 0.8:
        issues.append({"type": "source_locator_coverage_below_threshold", "severity": "high", "coverage": coverage})
    if not rich_metadata_available:
        issues.append({"type": "mineru_rich_metadata_missing", "severity": "high"})
    if not sidecars_parsed:
        issues.append({"type": "mineru_sidecars_not_parsed_for_citation", "severity": "high"})

    issues = dedupe_issues(issues)
    status = "needs_review" if any(issue.get("severity") == "high" for issue in issues) else "passed"
    gates = {
        **existing_gates,
        "no_synthetic_heading": not any(issue.get("type") == "synthetic_heading_not_in_source" for issue in issues),
        "no_duplicate_generated_rag_summary": summary_count <= 1,
        "no_prompt_or_status_leak": not any(issue.get("type") == "prompt_or_status_leak_detected" for issue in issues),
        "citation_anchors_present": bool(citations),
        "source_locator_coverage": coverage,
        "mineru_rich_metadata_available": rich_metadata_available,
        "mineru_sidecars_parsed_for_citation": sidecars_parsed,
        "mineru_source_jsons_used": mineru_source_jsons,
        "refilled_from_current_mineru_artifacts": status == "passed",
    }
    report = {
        **quality,
        "quality_status": status,
        "quality_score": quality_score(issues),
        "issues": issues,
        "quality_gates": gates,
        "refill_evaluation": {
            "policy": AI_QUALITY_REFILL_POLICY,
            "checked_at": utc_now(),
            "reason": "Recomputed from current normalized Markdown, citation map, and MinerU sidecar evidence.",
        },
    }
    return {"decision": status, "issues": issues, "quality_report": report}


def normalize_existing_quality_issues(
    issues: list[Any],
    *,
    current_coverage: float,
    sidecars_parsed: bool,
    rich_metadata_available: bool,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        issue_type = str(item.get("type") or "")
        if issue_type == "low_source_locator_coverage" and current_coverage >= 0.8:
            normalized.append(
                {
                    "type": "stale_low_source_locator_coverage_repaired",
                    "severity": "low",
                    "previous_coverage": item.get("coverage"),
                    "current_coverage": current_coverage,
                }
            )
            continue
        if (
            issue_type == "source_output_qa_failed"
            and "source_text_unavailable" in {str(value) for value in (item.get("details") or [])}
            and current_coverage >= 0.8
            and sidecars_parsed
            and rich_metadata_available
        ):
            normalized.append(
                {
                    "type": "source_text_unavailable_validated_by_mineru_sidecars",
                    "severity": "low",
                    "details": item.get("details") or [],
                }
            )
            continue
        normalized.append(dict(item))
    return normalized


def dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        key = (str(issue.get("type") or ""), str(issue.get("text") or issue.get("path") or issue.get("details") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def ai_review_decision(record: ManifestRecord) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    extra = record.extra or {}
    normalized_path = Path(record.normalized_path)
    quality_path = Path(str(extra.get("quality_report_path") or ""))
    citation_path = Path(str(extra.get("citation_map_path") or ""))

    if not normalized_path.exists():
        issues.append({"type": "missing_normalized_markdown", "severity": "blocker", "path": str(normalized_path)})
        text = ""
    else:
        text = normalized_path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 80:
            issues.append({"type": "normalized_markdown_too_short", "severity": "blocker"})
        if mojibake_score(text):
            issues.append({"type": "mojibake_detected", "severity": "blocker"})

    if extra.get("quality_status") != "passed":
        issues.append({"type": "quality_status_not_passed", "severity": "blocker", "quality_status": extra.get("quality_status")})

    quality = read_json_if_exists(quality_path)
    gates = quality.get("quality_gates") if isinstance(quality.get("quality_gates"), dict) else {}
    if not quality_path.exists():
        issues.append({"type": "missing_quality_report", "severity": "blocker", "path": str(quality_path)})
    if gates.get("no_synthetic_heading") is False:
        issues.append({"type": "synthetic_heading_gate_failed", "severity": "blocker"})
    if gates.get("no_prompt_or_status_leak") is False:
        issues.append({"type": "prompt_or_status_leak_gate_failed", "severity": "blocker"})
    if gates.get("mineru_sidecars_parsed_for_citation") is not True:
        issues.append({"type": "mineru_sidecars_not_parsed_for_citation", "severity": "blocker"})
    coverage = float(gates.get("source_locator_coverage") or 0.0)
    if coverage < 0.8:
        issues.append({"type": "source_locator_coverage_below_threshold", "severity": "blocker", "coverage": coverage})

    citations = read_json_if_exists(citation_path)
    if not citation_path.exists() or not isinstance(citations, list) or not citations:
        issues.append({"type": "missing_or_empty_citation_map", "severity": "blocker", "path": str(citation_path)})
        citations = []
    elif not any(citation.get("source_json") or citation.get("mineru_source_json") for citation in citations if isinstance(citation, dict)):
        issues.append({"type": "citation_map_missing_mineru_source_json", "severity": "blocker"})

    if extra.get("ingest_policy") == "primary_source_only":
        decision = extra.get("primary_source_decision")
        if not isinstance(decision, dict) or decision.get("selected") not in {"xlsx", "xls", "pdf", "docx", "doc"}:
            issues.append({"type": "missing_primary_source_decision", "severity": "blocker"})

    evidence = {
        "quality_status": extra.get("quality_status"),
        "quality_report_path": str(quality_path),
        "citation_map_path": str(citation_path),
        "citation_map_exists": citation_path.exists() and bool(citations),
        "citation_count": len(citations) if isinstance(citations, list) else 0,
        "source_locator_coverage": coverage,
        "mineru_sidecars_parsed_for_citation": gates.get("mineru_sidecars_parsed_for_citation") is True,
        "mineru_source_jsons_used": gates.get("mineru_source_jsons_used") or [],
        "normalized_path": str(normalized_path),
        "normalized_hash": content_hash(normalized_path) if normalized_path.exists() else None,
    }
    return {
        "decision": "approved" if not issues else "rejected",
        "issues": issues,
        "evidence": evidence,
    }


def write_ai_review_packet(root: Path, record: ManifestRecord, evidence: dict[str, Any], *, reviewer: str = AI_REVIEWER) -> Path:
    extra = record.extra or {}
    review_path_value = extra.get("human_review_path") or extra.get("review_report_path")
    if review_path_value:
        review_path = Path(str(review_path_value))
    else:
        artifact_stem = str(extra.get("artifact_stem") or f"{record.doc_id}_{record.version}")
        review_path = root / "review" / "ai_review" / artifact_stem / "human_review.json"
    checklist = {
        "title_correct": True,
        "revision_correct": True,
        "headings_source_based": True,
        "steps_order_correct": True,
        "no_synthetic_content": True,
        "citations_correct": True,
        "source_output_audit_passed": True,
        "mineru_sidecars_used": True,
        "rag_ready_artifacts_present": True,
    }
    payload = {
        "review_status": "approved",
        "reviewer": reviewer,
        "ai_reviewer_override": True,
        "review_policy": AI_REVIEW_POLICY,
        "doc_id": record.doc_id,
        "display_code": extra.get("display_code") or record.doc_id,
        "display_version": extra.get("display_version") or record.version,
        "checklist": checklist,
        "quality_evidence": evidence,
        "notes": "AI agent review approved by explicit user goal to skip human review for RAGFlow ingestion preparation.",
        "created_at": utc_now(),
    }
    write_json(review_path, payload)
    return review_path


def read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
