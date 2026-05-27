from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_prompt_queue import list_upload_queue, record_upload_workflow_event
from .config import ALLOWED_CATEGORIES
from .converter import ConversionError, MinerUConverter, find_mineru_artifact_index
from .data_workflow import (
    append_workflow_handoff,
    artifact_record,
    build_citation_record,
    build_section_index,
    mineru_source_blocks,
    source_evidence_blocks,
    workflow_run_id,
    make_handoff,
)
from .database import QualityDatabase
from .document_qa import mojibake_score, qa_source_output
from .manifest import ManifestStore
from .models import ManifestRecord
from .pipeline import init_workspace, rebuild_indexes
from .rag_index import chunk_markdown_with_metadata, stable_anchor_id
from .utils import content_hash, copy_file, safe_filename, utc_now, write_json


UPLOAD_RUN_SCHEMA_VERSION = "upload_agent_run_v1"
SUPPORTED_GROUP_SUFFIXES = {".pdf", ".xlsx"}
SYNTHETIC_HEADINGS = {
    "fixing metadata",
    "incident response",
    "smart fix",
    "fix review",
}
PROMPT_DEBUG_MARKERS = {
    "agent task",
    "debug",
    "quality gate",
    "repair loop",
    "submitting mineru",
    "task completed",
}
GENERATED_RAG_SUMMARY_KEY = "tom tat cau truc phuc vu rag"
TITLE_CORRUPTION_PATTERN = re.compile(r"(?iu)[\wÀ-ỹ]\?+[\wÀ-ỹ]|\?\?")


class UploadProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadSource:
    source_type: str
    original_relative_path: str
    current_relative_path: str
    absolute_path: Path
    file_name: str
    size_bytes: int


@dataclass(frozen=True)
class UploadDocumentGroup:
    business_key: str
    canonical_business_code: str
    display_code: str
    source_revision: str
    revision_slug: str
    doc_id: str
    title: str
    category: str
    artifact_stem: str
    sources: dict[str, UploadSource]

    @property
    def relative_paths(self) -> list[str]:
        return [source.current_relative_path for source in self.sources.values()]


@dataclass(frozen=True)
class CandidateConversion:
    source_type: str
    source_path: Path
    staged_source_path: Path
    raw_markdown_path: Path
    artifact_root: Path
    mineru_artifact_index_path: Path | None
    status: str
    error: str | None = None


@dataclass(frozen=True)
class UploadRunPaths:
    artifact_root: Path
    converted_raw: Path
    staging: Path
    normalized: Path
    indexes: Path
    review: Path
    reports: Path
    source_probe_report: Path
    quality_report: Path
    repair_handoff: Path
    repair_log: Path
    review_report: Path
    run_report: Path
    evolution_report: Path
    metadata_json: Path
    section_index: Path
    chunk_plan: Path
    citation_map: Path
    schema_manifest: Path
    citation_manifest: Path
    index_manifest: Path


def process_upload_queue(
    root: Path,
    *,
    converter: MinerUConverter | None = None,
    limit_groups: int | None = None,
    category: str | None = "procedure",
) -> list[dict[str, Any]]:
    """Process Upload/Inbox items one business-document group at a time.

    This is the runtime counterpart of the Upload GOAL prompt. It intentionally
    stops at pending_review and never calls RAGFlow ingestion.
    """
    init_workspace(root)
    converter = converter or MinerUConverter.from_env()
    processed: list[dict[str, Any]] = []

    while limit_groups is None or len(processed) < limit_groups:
        groups = list_upload_document_groups(root, category=category)
        if not groups:
            break
        group = groups[0]
        processed.append(process_upload_document_group(root, group, converter=converter))
    return processed


def list_upload_document_groups(root: Path, *, category: str | None = "procedure") -> list[UploadDocumentGroup]:
    queue = list_upload_queue(root)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in queue.get("items") or []:
        if item.get("status") != "queue":
            continue
        if category and item.get("suggested_type") != category:
            continue
        suffix = Path(str(item.get("file_name") or "")).suffix.lower()
        if suffix not in SUPPORTED_GROUP_SUFFIXES:
            continue
        identity = business_document_identity(str(item.get("file_name") or ""))
        grouped.setdefault(identity["business_key"], []).append(item)

    groups: list[UploadDocumentGroup] = []
    for business_key, items in grouped.items():
        sources: dict[str, UploadSource] = {}
        for item in items:
            suffix = Path(str(item["file_name"])).suffix.lower()
            source_type = suffix.lstrip(".")
            if source_type in sources:
                # Keep the earliest stable queue item; duplicates remain for a later run.
                continue
            sources[source_type] = UploadSource(
                source_type=source_type,
                original_relative_path=str(item["original_relative_path"]),
                current_relative_path=str(item["relative_path"]),
                absolute_path=Path(str(item["absolute_path"])),
                file_name=str(item["file_name"]),
                size_bytes=int(item.get("size_bytes") or 0),
            )
        if not sources:
            continue
        identity = business_document_identity(items[0]["file_name"])
        groups.append(
            UploadDocumentGroup(
                business_key=business_key,
                canonical_business_code=identity["code"],
                display_code=identity["code"],
                source_revision=identity["revision"],
                revision_slug=identity["revision_slug"],
                doc_id=internal_doc_id(identity["code"]),
                title=identity["title"],
                category=str(items[0].get("suggested_type") or "procedure"),
                artifact_stem=f"{internal_doc_id(identity['code'])}_{identity['revision_slug']}",
                sources=sources,
            )
        )
    return sorted(groups, key=lambda group: group.business_key)


def process_upload_document_group(
    root: Path,
    group: UploadDocumentGroup,
    *,
    converter: MinerUConverter,
    primary_source: str = "auto",
) -> dict[str, Any]:
    if group.category not in ALLOWED_CATEGORIES["technical"]:
        raise UploadProcessingError(f"Unsupported Upload category: {group.category}")
    paths = upload_run_paths(root, group)
    create_upload_run_dirs(paths)
    run_id = workflow_run_id(group.doc_id, group.revision_slug)
    source_id = group.artifact_stem

    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing",
        step="classify",
        detail=f"Orchestrator claimed business document group {group.display_code} {group.source_revision}",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        checkpoint="plan",
        quality_gates={"single_business_document_group": True, "parallel_batch": False},
        next_skill="mineru-source-converter",
    )
    processing_sources = resolve_processing_sources(root, group)
    staged_sources = stage_group_sources(processing_sources, paths.staging / "sources")
    plan_handoff = append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="plan",
            status="ready",
            source_id=source_id,
            artifacts=[
                artifact_record(path, artifact_id=f"source_{source_type}_{source_id}", artifact_type="raw", source_id=source_id)
                for source_type, path in staged_sources.items()
            ],
            quality_gates={
                "single_business_document_group": True,
                "source_count": len(staged_sources),
                "pdf_xlsx_dedupe_required": {"pdf", "xlsx"}.issubset(staged_sources),
            },
            next_skill="mineru-source-converter",
        ),
    )
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing",
        step="handoff_check",
        detail="Plan handoff contract passed",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        handoff_path=str(plan_handoff),
        checkpoint="plan",
        quality_gates={"handoff_checker": True},
        next_skill="mineru-source-converter",
    )

    probe = build_upload_source_probe_report(group, staged_sources)
    conversions: dict[str, CandidateConversion] = {}
    for source_type in ("xlsx", "pdf"):
        if source_type not in staged_sources:
            continue
        conversions[source_type] = convert_upload_candidate(
            converter=converter,
            group=group,
            source_type=source_type,
            source_path=processing_sources[source_type],
            staged_source_path=staged_sources[source_type],
            paths=paths,
        )
    selected = select_upload_primary_source(probe, conversions, primary_source)
    if not selected:
        failure = terminal_upload_failure(
            root=root,
            group=group,
            paths=paths,
            run_id=run_id,
            conversions=conversions,
            probe=probe,
            reason="MinerU did not produce usable Markdown for any candidate source.",
        )
        return failure

    decision = {
        "selected": selected,
        "reason": primary_source_decision_reason(probe, conversions, selected, primary_source),
        "decided_at": utc_now(),
        "decided_by": "human" if primary_source in {"xlsx", "pdf"} else "system",
        "probe_report_path": str(paths.source_probe_report),
    }
    probe["recommended_primary_source"] = selected
    probe["reason"] = decision["reason"]
    probe["candidate_conversions"] = {
        source_type: candidate_summary(candidate) for source_type, candidate in conversions.items()
    }
    write_json(paths.source_probe_report, probe)

    convert_handoff = append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="convert",
            status="passed",
            source_id=source_id,
            artifacts=[
                *conversion_artifact_records(conversions, source_id),
                artifact_record(paths.source_probe_report, artifact_id=f"source_probe_{source_id}", artifact_type="audit", source_id=source_id),
            ],
            quality_gates={
                "mineru_only": True,
                "any_candidate_converted": True,
                "primary_source_selected": True,
                "selected_primary_source": selected,
                "duplicate_retrieval_blocked": True,
            },
            next_skill="source-output-quality-auditor",
        ),
    )
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing",
        step="extract_artifacts",
        detail="MinerU conversion completed and rich artifacts indexed",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        handoff_path=str(convert_handoff),
        checkpoint="convert",
        artifacts=[
            {
                "type": "converted",
                "source_type": candidate.source_type,
                "path": str(candidate.raw_markdown_path),
                "mineru_artifact_index_path": str(candidate.mineru_artifact_index_path)
                if candidate.mineru_artifact_index_path
                else None,
            }
            for candidate in conversions.values()
        ],
        quality_gates={"mineru_only": True, "primary_source_selected": True},
        mineru_profile=converter.profile_dict() if hasattr(converter, "profile_dict") else None,
        next_skill="source-output-quality-auditor",
    )

    initial_audit = build_initial_upload_audit(group, probe, conversions, selected)
    write_json(paths.quality_report, initial_audit)
    write_json(paths.repair_handoff, build_repair_handoff(group, selected, conversions[selected], initial_audit))
    audit_handoff = append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="audit",
            status="needs_repair",
            source_id=source_id,
            artifacts=[
                artifact_record(paths.quality_report, artifact_id=f"initial_quality_report_{source_id}", artifact_type="audit", source_id=source_id),
                artifact_record(paths.repair_handoff, artifact_id=f"repair_handoff_{source_id}", artifact_type="audit", source_id=source_id),
            ],
            quality_gates={
                "raw_markdown_non_empty": True,
                "mineru_artifact_index_checked": bool(conversions[selected].mineru_artifact_index_path),
                "repair_required_for_normalized_markdown": True,
            },
            next_skill="rag-markdown-repairer",
        ),
    )
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing",
        step="qa",
        detail="Initial QA created repair handoff for RAG Markdown normalization",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        handoff_path=str(audit_handoff),
        qa_report_path=str(paths.quality_report),
        qa_status="needs_repair",
        qa_issues=[issue["type"] for issue in initial_audit.get("issues") or []],
        checkpoint="audit",
        quality_gates={"repair_handoff_created": True},
        next_skill="rag-markdown-repairer",
    )

    primary = conversions[selected]
    normalized_text = normalize_mineru_markdown_for_upload(group, primary.raw_markdown_path)
    paths.normalized.write_text(normalized_text, encoding="utf-8")
    repair_log = {
        "schema_version": UPLOAD_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "doc_id": group.doc_id,
        "display_code": group.display_code,
        "selected_primary_source": selected,
        "repair_iterations": 1,
        "strategy": "mineru_markdown_preclean_and_source_faithful_restructure",
        "input_raw_markdown": str(primary.raw_markdown_path),
        "output_normalized_markdown": str(paths.normalized),
        "created_at": utc_now(),
    }
    write_json(paths.repair_log, repair_log)
    repair_handoff = append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="repair",
            status="passed",
            source_id=source_id,
            artifacts=[
                artifact_record(paths.normalized, artifact_id=f"normalized_markdown_{source_id}", artifact_type="repair", source_id=source_id),
                artifact_record(paths.repair_log, artifact_id=f"repair_log_{source_id}", artifact_type="repair", source_id=source_id),
            ],
            quality_gates={"repair_iterations": 1, "source_unsupported_additions": False},
            next_skill="source-output-quality-auditor",
        ),
    )
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing",
        step="repair_loop",
        detail="Repair agent produced normalized Markdown draft",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        handoff_path=str(repair_handoff),
        checkpoint="repair",
        quality_gates={"repair_iterations": 1},
        next_skill="source-output-quality-auditor",
    )

    qa = qa_source_output(primary.staged_source_path, paths.normalized)
    rag_ready = build_upload_rag_ready_artifacts(
        group=group,
        paths=paths,
        primary=primary,
        selected=selected,
        decision=decision,
        supporting_sources=supporting_sources(staged_sources, selected),
        qa_report=qa.to_dict(),
        converter=converter,
    )
    final_quality = verify_upload_rag_readiness(
        group=group,
        paths=paths,
        primary=primary,
        qa_report=qa.to_dict(),
        rag_ready=rag_ready,
        initial_audit=initial_audit,
    )
    write_json(paths.quality_report, final_quality)
    qa_status = "passed" if final_quality["quality_status"] == "passed" else "needs_repair"
    final_audit_handoff = append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="audit",
            status="passed" if qa_status == "passed" else "blocked",
            source_id=source_id,
            artifacts=[
                artifact_record(paths.quality_report, artifact_id=f"final_quality_report_{source_id}", artifact_type="audit", source_id=source_id)
            ],
            quality_gates=final_quality.get("quality_gates") or {},
            next_skill="ragflow-schema-indexer" if qa_status == "passed" else None,
        ),
    )
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing" if qa_status == "passed" else "failed",
        step="qa" if qa_status == "passed" else "failed",
        detail=f"QA recheck {qa_status}",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        handoff_path=str(final_audit_handoff),
        qa_report_path=str(paths.quality_report),
        qa_status=qa_status,
        qa_issues=[issue["type"] for issue in final_quality.get("issues") or []],
        checkpoint="audit",
        quality_gates=final_quality.get("quality_gates") or {},
        next_skill="ragflow-schema-indexer" if qa_status == "passed" else None,
    )
    if qa_status != "passed":
        write_terminal_reports(paths, group, run_id, selected, decision, final_quality, status="failed")
        return finalize_upload_queue_state(root, group, paths, status="failed", detail="QA recheck failed")

    index_handoff = append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="index",
            status="passed",
            source_id=source_id,
            artifacts=[
                artifact_record(paths.metadata_json, artifact_id=f"metadata_json_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(paths.section_index, artifact_id=f"section_index_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(paths.chunk_plan, artifact_id=f"chunk_plan_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(paths.citation_map, artifact_id=f"citation_map_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(paths.quality_report, artifact_id=f"quality_report_{source_id}", artifact_type="rag_ready", source_id=source_id),
            ],
            quality_gates={
                "canonical_outputs_created": True,
                "ragflow_ingestion_not_run": True,
                "human_review_required": True,
                "supporting_source_not_ingested": True,
            },
            next_skill="data-skill-evolution",
        ),
    )
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing",
        step="rag_ready",
        detail="RAG-ready artifacts created; waiting for human review",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        handoff_path=str(index_handoff),
        qa_report_path=str(paths.quality_report),
        qa_status="passed",
        qa_issues=[],
        checkpoint="index",
        quality_gates={"canonical_outputs_created": True, "ragflow_ingestion_not_run": True},
        next_skill="data-skill-evolution",
    )

    review = build_human_review_packet(group, paths, final_quality)
    write_json(paths.review_report, review)
    record = upsert_upload_manifest_record(
        root=root,
        group=group,
        paths=paths,
        primary=primary,
        selected=selected,
        decision=decision,
        final_quality=final_quality,
        converter=converter,
        supporting=supporting_sources(staged_sources, selected),
    )
    write_terminal_reports(paths, group, run_id, selected, decision, final_quality, status=record.status)
    evolve_handoff = append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="evolve",
            status="passed",
            source_id=source_id,
            artifacts=[
                artifact_record(paths.evolution_report, artifact_id=f"evolution_report_{source_id}", artifact_type="evolution", source_id=source_id),
                artifact_record(paths.run_report, artifact_id=f"run_report_{source_id}", artifact_type="evolution", source_id=source_id),
            ],
            quality_gates={"evolution_report_written": True, "final_status": record.status},
            next_skill=None,
        ),
    )
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status="processing",
        step="review",
        detail="Queued for human review; RAGFlow sync not run",
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        handoff_path=str(evolve_handoff),
        qa_report_path=str(paths.quality_report),
        qa_status="passed",
        checkpoint="evolve",
        quality_gates={"pending_review": True, "ragflow_ingestion_not_run": True},
        next_skill="human-review",
    )
    return finalize_upload_queue_state(root, group, paths, status="done", detail="Ready for human review")


def business_document_identity(file_name: str) -> dict[str, str]:
    stem = Path(file_name).stem
    normalized = re.sub(r"[_]+", " ", stem)
    code_match = re.search(r"([A-Z]{2,5}-[A-Z]{2,8}(?:-[A-Z])?-\d{1,4})", normalized, flags=re.IGNORECASE)
    code = code_match.group(1).upper() if code_match else safe_filename(stem).upper()
    rev_match = re.search(r"\bRev\.?\s*0*(\d{1,3})\b", normalized, flags=re.IGNORECASE)
    rev_number = int(rev_match.group(1)) if rev_match else 1
    revision = f"Rev {rev_number:02d}"
    revision_slug = f"rev{rev_number:02d}"
    title_start = max(
        code_match.end() if code_match else 0,
        rev_match.end() if rev_match else 0,
    )
    title = normalized[title_start:]
    title = re.sub(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b", " ", title)
    title = re.sub(r"^[\s.\-_]+", "", title)
    title = re.sub(r"\s+", " ", title).strip() or stem
    business_key = f"{code}_{revision_slug}"
    return {
        "code": code,
        "revision": revision,
        "revision_slug": revision_slug,
        "title": title,
        "business_key": business_key,
    }


def internal_doc_id(display_code: str) -> str:
    match = re.search(r"(\d{1,4})$", display_code)
    if not match:
        return safe_filename(display_code).upper()
    return f"KT-QT-{int(match.group(1)):03d}"


def upload_run_paths(root: Path, group: UploadDocumentGroup) -> UploadRunPaths:
    group_slug = safe_filename(group.business_key)
    artifact_root = root / ".Workplace" / "artifacts" / group.category / group.artifact_stem
    if (artifact_root / "workflow" / "handoffs.jsonl").exists():
        retry_stamp = safe_filename(utc_now().replace(":", "").replace("+", "Z"))
        artifact_root = artifact_root.with_name(f"{group.artifact_stem}_{retry_stamp}")
    indexes = root / "indexes"
    rag_ready_root = root / "rag_ready" / "technical" / group.category / group.artifact_stem
    return UploadRunPaths(
        artifact_root=artifact_root,
        converted_raw=root / "converted_raw" / "upload" / group_slug,
        staging=root / "staging" / "upload" / group_slug,
        normalized=root / "normalized" / "technical" / group.category / f"{group.artifact_stem}.md",
        indexes=indexes,
        review=root / "review" / "upload" / group_slug,
        reports=artifact_root / "reports",
        source_probe_report=artifact_root / "reports" / "source_probe_report.json",
        quality_report=indexes / f"{group.artifact_stem}_quality_report.json",
        repair_handoff=artifact_root / "reports" / "repair_handoff.json",
        repair_log=artifact_root / "reports" / "repair_log.json",
        review_report=root / "review" / "upload" / group_slug / "human_review.json",
        run_report=artifact_root / "reports" / "run_report.md",
        evolution_report=artifact_root / "reports" / "evolution_report.md",
        metadata_json=indexes / f"{group.artifact_stem}_metadata.json",
        section_index=indexes / f"{group.artifact_stem}_section_index.json",
        chunk_plan=indexes / f"{group.artifact_stem}_chunk_plan.json",
        citation_map=indexes / f"{group.artifact_stem}_citation_map.json",
        schema_manifest=rag_ready_root / "schema_manifest.json",
        citation_manifest=rag_ready_root / "citation_manifest.json",
        index_manifest=rag_ready_root / "index_manifest.json",
    )


def create_upload_run_dirs(paths: UploadRunPaths) -> None:
    for directory in {
        paths.artifact_root,
        paths.converted_raw,
        paths.staging,
        paths.normalized.parent,
        paths.indexes,
        paths.review,
        paths.reports,
        paths.schema_manifest.parent,
    }:
        directory.mkdir(parents=True, exist_ok=True)


def group_metadata(group: UploadDocumentGroup) -> dict[str, Any]:
    return {
        "doc_id": group.doc_id,
        "title": group.title,
        "department": "technical",
        "category": group.category,
        "source_type": "internal_procedure",
        "language": "vi",
        "version": group.revision_slug,
        "internal_version": "1.0",
        "source_revision": group.source_revision,
        "display_version": group.source_revision,
        "display_code": group.display_code,
        "canonical_business_code": group.canonical_business_code,
        "dedupe_group": group.business_key,
        "owner": "Phong Ky thuat",
        "access_group": "technical",
        "effective_from": utc_now()[:10],
        "review_at": utc_now()[:10],
    }


def resolve_processing_sources(root: Path, group: UploadDocumentGroup) -> dict[str, Path]:
    queue = list_upload_queue(root)
    lookup = {str(item["original_relative_path"]): item for item in queue.get("items") or []}
    result: dict[str, Path] = {}
    for source_type, source in group.sources.items():
        item = lookup.get(source.original_relative_path)
        if not item:
            raise UploadProcessingError(f"Processing source disappeared from queue: {source.original_relative_path}")
        result[source_type] = Path(str(item["absolute_path"])).resolve()
    return result


def stage_group_sources(sources: dict[str, Path], source_dir: Path) -> dict[str, Path]:
    staged: dict[str, Path] = {}
    for source_type, source in sources.items():
        destination = source_dir / source_type / source.name
        copy_file(source, destination)
        staged[source_type] = destination.resolve()
    return staged


def build_upload_source_probe_report(group: UploadDocumentGroup, sources: dict[str, Path]) -> dict[str, Any]:
    xlsx_probe = probe_xlsx_source(sources["xlsx"], group.display_code) if "xlsx" in sources else missing_probe("xlsx")
    pdf_probe = probe_pdf_source(sources["pdf"], group.display_code) if "pdf" in sources else missing_probe("pdf")
    recommended = recommended_primary_source(xlsx_probe, pdf_probe)
    return {
        "schema_version": UPLOAD_RUN_SCHEMA_VERSION,
        "doc_id": group.doc_id,
        "doc_code": group.display_code,
        "source_revision": group.source_revision,
        "xlsx_probe": xlsx_probe,
        "pdf_probe": pdf_probe,
        "recommended_primary_source": recommended,
        "reason": primary_probe_reason(xlsx_probe, pdf_probe, recommended),
        "created_at": utc_now(),
    }


def missing_probe(source_type: str) -> dict[str, Any]:
    return {
        "parse_score": 0.0,
        "source_type": source_type,
        "issues": [f"{source_type}_source_missing"],
    }


def probe_xlsx_source(path: Path, display_code: str) -> dict[str, Any]:
    issues: list[str] = []
    try:
        from openpyxl import load_workbook
    except Exception as exc:
        return {"parse_score": 0.0, "sheet_count": 0, "table_quality": "bad", "step_extraction_quality": "bad", "issues": [str(exc)]}
    workbook = load_workbook(filename=path, data_only=True, read_only=False)
    sheet_count = len(workbook.sheetnames)
    non_empty_rows = 0
    non_empty_cells = 0
    merged_ranges = 0
    text_parts: list[str] = []
    drawing_count = 0
    for sheet in workbook.worksheets:
        merged_ranges += len(sheet.merged_cells.ranges)
        drawing_count += len(getattr(sheet, "_images", []) or [])
        for row in sheet.iter_rows(values_only=True):
            values = [str(value).strip() for value in row if value not in (None, "")]
            if not values:
                continue
            non_empty_rows += 1
            non_empty_cells += len(values)
            text_parts.extend(values)
    workbook.close()
    text_key = ascii_key(" ".join(text_parts))
    table_quality = "good" if non_empty_rows >= 8 and non_empty_cells >= 20 else "medium" if non_empty_rows >= 3 else "bad"
    step_hits = sum(1 for term in ("quy trinh", "buoc", "noi dung", "trach nhiem", "ho so", "bieu mau") if term in text_key)
    step_quality = "good" if step_hits >= 3 else "medium" if step_hits else "bad"
    merged_risk = "high" if merged_ranges >= 20 else "medium" if merged_ranges else "low"
    shape_risk = "medium" if drawing_count else "low"
    score = 0.25
    score += {"good": 0.30, "medium": 0.15, "bad": 0.0}[table_quality]
    score += {"good": 0.30, "medium": 0.15, "bad": 0.0}[step_quality]
    score -= {"low": 0.0, "medium": 0.08, "high": 0.18}[merged_risk]
    score -= {"low": 0.0, "medium": 0.05, "high": 0.12}[shape_risk]
    if safe_ascii_code(display_code) not in safe_ascii_code(path.name) and safe_ascii_code(display_code) not in text_key:
        issues.append("doc_code_not_detected_in_xlsx")
        score -= 0.10
    return {
        "parse_score": round(max(0.0, min(1.0, score)), 2),
        "sheet_count": sheet_count,
        "table_quality": table_quality,
        "merged_cells_risk": merged_risk,
        "shape_text_risk": shape_risk,
        "step_extraction_quality": step_quality,
        "issues": issues,
    }


def probe_pdf_source(path: Path, display_code: str) -> dict[str, Any]:
    issues: list[str] = []
    page_count = 0
    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception as exc:
        issues.append(f"pdf_text_probe_failed: {exc}")
    chars_per_page = len(text.strip()) / page_count if page_count else 0
    ocr_quality = "good" if chars_per_page >= 300 else "medium" if chars_per_page >= 80 else "bad"
    layout_quality = "good" if page_count and "\n" in text else "medium" if text.strip() else "bad"
    page_locator_quality = "good" if page_count else "bad"
    score = 0.20
    score += {"good": 0.35, "medium": 0.18, "bad": 0.0}[ocr_quality]
    score += {"good": 0.20, "medium": 0.10, "bad": 0.0}[layout_quality]
    score += {"good": 0.15, "medium": 0.08, "bad": 0.0}[page_locator_quality]
    if safe_ascii_code(display_code) not in safe_ascii_code(path.name) and safe_ascii_code(display_code) not in ascii_key(text):
        issues.append("doc_code_not_detected_in_pdf")
        score -= 0.10
    return {
        "parse_score": round(max(0.0, min(1.0, score)), 2),
        "page_count": page_count,
        "ocr_quality": ocr_quality,
        "layout_quality": layout_quality,
        "page_locator_quality": page_locator_quality,
        "issues": issues,
    }


def recommended_primary_source(xlsx_probe: dict[str, Any], pdf_probe: dict[str, Any]) -> str:
    xlsx_score = float(xlsx_probe.get("parse_score") or 0.0)
    pdf_score = float(pdf_probe.get("parse_score") or 0.0)
    if xlsx_probe.get("step_extraction_quality") == "good" and xlsx_score >= pdf_score - 0.10:
        return "xlsx"
    return "xlsx" if xlsx_score >= pdf_score else "pdf"


def primary_probe_reason(xlsx_probe: dict[str, Any], pdf_probe: dict[str, Any], selected: str) -> str:
    xlsx_score = float(xlsx_probe.get("parse_score") or 0.0)
    pdf_score = float(pdf_probe.get("parse_score") or 0.0)
    if selected == "xlsx":
        return f"XLSX selected by probe because score {xlsx_score} is competitive with PDF score {pdf_score} and table/step extraction is preferred."
    return f"PDF selected by probe because score {pdf_score} is higher than XLSX score {xlsx_score}."


def convert_upload_candidate(
    *,
    converter: MinerUConverter,
    group: UploadDocumentGroup,
    source_type: str,
    source_path: Path,
    staged_source_path: Path,
    paths: UploadRunPaths,
) -> CandidateConversion:
    raw_markdown_path = paths.converted_raw / source_type / f"{group.artifact_stem}_{source_type}_raw.md"
    artifact_root = paths.converted_raw / source_type / "mineru_raw"
    try:
        converter.convert_with_mineru(
            source_path,
            raw_markdown_path,
            language="vi",
            artifact_root=artifact_root,
        )
        mineru_index = find_mineru_artifact_index(artifact_root, raw_markdown_path)
        if not raw_markdown_path.exists() or len(raw_markdown_path.read_text(encoding="utf-8", errors="replace").strip()) < 20:
            raise ConversionError(f"MinerU raw Markdown is empty or too short for {source_type}")
        return CandidateConversion(
            source_type=source_type,
            source_path=source_path,
            staged_source_path=staged_source_path,
            raw_markdown_path=raw_markdown_path,
            artifact_root=artifact_root,
            mineru_artifact_index_path=mineru_index,
            status="passed",
        )
    except Exception as exc:
        return CandidateConversion(
            source_type=source_type,
            source_path=source_path,
            staged_source_path=staged_source_path,
            raw_markdown_path=raw_markdown_path,
            artifact_root=artifact_root,
            mineru_artifact_index_path=None,
            status="blocked",
            error=str(exc),
        )


def select_upload_primary_source(
    probe: dict[str, Any],
    conversions: dict[str, CandidateConversion],
    primary_source: str,
) -> str | None:
    if primary_source not in {"auto", "xlsx", "pdf"}:
        raise UploadProcessingError("primary_source must be auto, xlsx, or pdf")
    if primary_source in {"xlsx", "pdf"}:
        candidate = conversions.get(primary_source)
        return primary_source if candidate and candidate.status == "passed" else None
    passed = [source_type for source_type, candidate in conversions.items() if candidate.status == "passed"]
    if not passed:
        return None
    recommended = probe.get("recommended_primary_source")
    if recommended in passed:
        return str(recommended)
    return max(passed, key=lambda source_type: float((probe.get(f"{source_type}_probe") or {}).get("parse_score") or 0.0))


def primary_source_decision_reason(
    probe: dict[str, Any],
    conversions: dict[str, CandidateConversion],
    selected: str,
    requested: str,
) -> str:
    if requested in {"xlsx", "pdf"}:
        return f"{requested.upper()} selected by explicit operator override after MinerU conversion passed."
    conversion_status = {source_type: candidate.status for source_type, candidate in conversions.items()}
    return f"{selected.upper()} selected by source probe and MinerU conversion status: {conversion_status}. {probe.get('reason')}"


def candidate_summary(candidate: CandidateConversion) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source_type": candidate.source_type,
        "source_path": str(candidate.source_path),
        "staged_source_path": str(candidate.staged_source_path),
        "raw_markdown_path": str(candidate.raw_markdown_path),
        "artifact_root": str(candidate.artifact_root),
        "mineru_artifact_index_path": str(candidate.mineru_artifact_index_path) if candidate.mineru_artifact_index_path else None,
        "status": candidate.status,
        "error": candidate.error,
    }
    if candidate.raw_markdown_path.exists():
        text = candidate.raw_markdown_path.read_text(encoding="utf-8", errors="replace")
        summary["raw_markdown_chars"] = len(text)
        summary["raw_markdown_non_empty"] = len(text.strip()) >= 20
        summary["prompt_debug_marker_count"] = sum(1 for marker in PROMPT_DEBUG_MARKERS if marker in ascii_key(text))
    if candidate.mineru_artifact_index_path and candidate.mineru_artifact_index_path.exists():
        try:
            summary["mineru_artifact_summary"] = json.loads(candidate.mineru_artifact_index_path.read_text(encoding="utf-8")).get("summary")
        except Exception:
            summary["mineru_artifact_summary"] = None
    return summary


def conversion_artifact_records(conversions: dict[str, CandidateConversion], source_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source_type, candidate in conversions.items():
        if candidate.raw_markdown_path.exists():
            records.append(artifact_record(candidate.raw_markdown_path, artifact_id=f"mineru_raw_{source_type}_{source_id}", artifact_type="converted", source_id=source_id))
        if candidate.mineru_artifact_index_path and candidate.mineru_artifact_index_path.exists():
            records.append(artifact_record(candidate.mineru_artifact_index_path, artifact_id=f"mineru_artifact_index_{source_type}_{source_id}", artifact_type="converted", source_id=source_id))
    return records


def build_initial_upload_audit(
    group: UploadDocumentGroup,
    probe: dict[str, Any],
    conversions: dict[str, CandidateConversion],
    selected: str,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for source_type, candidate in conversions.items():
        summary = candidate_summary(candidate)
        if candidate.status != "passed":
            issues.append({"type": "candidate_mineru_conversion_blocked", "severity": "medium", "source_type": source_type, "text": candidate.error})
            continue
        if not summary.get("raw_markdown_non_empty"):
            issues.append({"type": "empty_mineru_raw_markdown", "severity": "high", "source_type": source_type})
        artifact_summary = summary.get("mineru_artifact_summary") or {}
        if not (artifact_summary.get("has_content_list") or artifact_summary.get("has_content_list_v2") or artifact_summary.get("has_middle_json")):
            issues.append({"type": "mineru_rich_metadata_missing", "severity": "high" if source_type == selected else "medium", "source_type": source_type})
        if summary.get("prompt_debug_marker_count"):
            issues.append({"type": "prompt_or_status_leak_in_mineru_raw", "severity": "medium", "source_type": source_type})
    return {
        "schema_version": UPLOAD_RUN_SCHEMA_VERSION,
        "doc_id": group.doc_id,
        "display_code": group.display_code,
        "stage": "initial_source_output_audit",
        "selected_primary_source": selected,
        "quality_status": "needs_repair",
        "quality_score": quality_score(issues),
        "source_probe": probe,
        "candidate_conversions": {source_type: candidate_summary(candidate) for source_type, candidate in conversions.items()},
        "issues": issues,
        "checked_at": utc_now(),
    }


def build_repair_handoff(
    group: UploadDocumentGroup,
    selected: str,
    primary: CandidateConversion,
    audit_report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": UPLOAD_RUN_SCHEMA_VERSION,
        "doc_id": group.doc_id,
        "display_code": group.display_code,
        "source_revision": group.source_revision,
        "task": "repair_mineru_markdown_for_rag",
        "primary_source_type": selected,
        "primary_source_path": str(primary.staged_source_path),
        "raw_markdown_path": str(primary.raw_markdown_path),
        "mineru_artifact_index_path": str(primary.mineru_artifact_index_path) if primary.mineru_artifact_index_path else None,
        "audit_report_summary": {
            "quality_status": audit_report.get("quality_status"),
            "quality_score": audit_report.get("quality_score"),
            "issues": audit_report.get("issues") or [],
        },
        "hard_rules": [
            "Do not add content that is not supported by the source.",
            "Remove prompt/debug/status leaks from Markdown body.",
            "Every procedure section must receive a citation anchor.",
            "Use MinerU content_list/middle/model/images when they provide richer locator evidence.",
        ],
    }


def normalize_mineru_markdown_for_upload(group: UploadDocumentGroup, raw_markdown_path: Path) -> str:
    raw_text = raw_markdown_path.read_text(encoding="utf-8", errors="replace")
    raw_text = preclean_markdown(raw_text)
    body: list[str] = []
    saw_heading = False
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or is_noise_line(line):
            continue
        heading = markdown_heading_text(line)
        if heading:
            if is_synthetic_heading(heading):
                continue
            if safe_ascii_code(group.display_code) in safe_ascii_code(heading):
                continue
            saw_heading = True
            body.append(line)
            continue
        body.append(line)
    body = strip_generated_rag_summary_blocks(body)
    if not saw_heading:
        body.insert(0, "## Noi dung trich xuat")
    frontmatter = [
        "---",
        f"doc_id: {group.doc_id}",
        f"display_code: {group.display_code}",
        f"canonical_business_code: {group.canonical_business_code}",
        f"title: {json.dumps(group.title, ensure_ascii=False)}",
        f"internal_version: \"1.0\"",
        f"source_revision: {json.dumps(group.source_revision, ensure_ascii=False)}",
        f"display_version: {json.dumps(group.source_revision, ensure_ascii=False)}",
        "department: technical",
        f"category: {group.category}",
        "status: pending_review",
        "ragflow_ingestion: not_run",
        "raw_converter: mineru",
        "---",
        "",
        f"# {group.display_code} {group.source_revision} - {group.title}",
        "",
    ]
    summary = build_rag_summary_section(body)
    text = "\n".join(frontmatter + summary + body).strip() + "\n"
    if len(text.strip()) < 80:
        raise UploadProcessingError(f"Normalized Markdown is too short: {raw_markdown_path}")
    return text


def strip_generated_rag_summary_blocks(lines: list[str]) -> list[str]:
    """Remove generated RAG summaries before creating a fresh one."""
    cleaned: list[str] = []
    skipping = False
    skip_level = 0
    for line in lines:
        level = markdown_heading_level(line)
        if is_generated_rag_summary_heading(line):
            skipping = True
            skip_level = level or 2
            continue
        if skipping:
            if level and level <= skip_level:
                skipping = False
            else:
                continue
        if not skipping:
            cleaned.append(line)
    return cleaned


def build_rag_summary_section(lines: list[str]) -> list[str]:
    lines = strip_generated_rag_summary_blocks(lines)
    steps = extract_procedure_steps(lines)
    responsibilities = extract_responsibilities(lines)
    records = extract_record_references(lines)
    if not steps and not responsibilities and not records:
        return []

    summary: list[str] = [
        "## Tóm tắt cấu trúc phục vụ RAG",
        "",
        "> Nội dung dưới đây được trích xuất từ source/MinerU để ưu tiên truy xuất theo bước, trách nhiệm và hồ sơ.",
        "",
    ]
    if steps:
        summary.append("### Quy trình thực hiện")
        for step in steps:
            line = f"{step['number']}. Bước {step['number']}: {step['title']}"
            if step.get("details"):
                line += f" - {step['details']}"
            if step.get("form"):
                line += f" (Biểu mẫu/Hồ sơ: {step['form']})"
            summary.append(line)
        summary.append("")
    if responsibilities:
        summary.append("### Trách nhiệm")
        summary.extend(f"- {item}" for item in responsibilities)
        summary.append("")
    if records:
        summary.append("### Hồ sơ / biểu mẫu liên quan")
        summary.extend(f"- {item}" for item in records)
        summary.append("")
    return summary


def extract_procedure_steps(lines: list[str], max_steps: int = 30) -> list[dict[str, str]]:
    start = find_line_index(lines, ("6. nội dung", "6.nội dung", "noi dung cong viec", "nội dung công việc"))
    if start is None:
        start = find_line_index(lines, ("quy trình thực hiện", "trình tự thực hiện", "so do quy trinh", "sơ đồ quy trình"))
    if start is None:
        return []
    end = find_line_index(lines[start + 1 :], ("7. hồ sơ", "7.hồ sơ", "ho so", "hồ sơ", "phụ lục", "phu luc"))
    window = lines[start + 1 : start + 1 + end] if end is not None else lines[start + 1 : start + 260]
    steps: list[dict[str, str]] = []
    expected = 1
    for idx, line in enumerate(window):
        value = line.strip()
        if not re.fullmatch(r"\d{1,2}", value):
            continue
        number = int(value)
        if number != expected:
            continue
        row = collect_step_row(window, idx + 1)
        if not row:
            continue
        title = first_step_title(row)
        if not title:
            continue
        details = first_step_detail(row, title)
        form = first_form_reference(row)
        steps.append({"number": str(number), "title": title, "details": details, "form": form})
        expected += 1
        if len(steps) >= max_steps:
            break
    return steps


def collect_step_row(lines: list[str], start: int) -> list[str]:
    row: list[str] = []
    for line in lines[start : min(start + 20, len(lines))]:
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"\d{1,2}", stripped) and row:
            break
        row.append(stripped)
    return row


def first_step_title(row: list[str]) -> str:
    for line in row:
        if is_step_noise(line):
            continue
        if len(line) < 4:
            continue
        return clean_summary_line(line)
    return ""


def first_step_detail(row: list[str], title: str) -> str:
    for line in row:
        if line == title or is_step_noise(line):
            continue
        if line.startswith("-") or len(line) >= 28:
            return clean_summary_line(line)
    return ""


def first_form_reference(row: list[str]) -> str:
    for line in row:
        if re.search(r"\b(?:PD|BM|MS)-[A-Z0-9./-]+", line, flags=re.IGNORECASE):
            return clean_summary_line(line)
    return ""


def is_step_noise(line: str) -> bool:
    normalized = safe_ascii_code(line)
    if not normalized:
        return True
    if re.fullmatch(r"[irac,]+", normalized):
        return True
    if normalized in {"r", "a", "i", "c", "ra", "ic", "ri", "ia"}:
        return True
    if normalized in {"hangthang", "khicophatsinh", "theolichbaoduong"}:
        return True
    if normalized in {"stt", "raci", "ketqua", "tansuat", "bieumau"}:
        return True
    if normalized.startswith("trachnhiem"):
        return True
    return False


def extract_responsibilities(lines: list[str], max_items: int = 8) -> list[str]:
    start = find_line_index(lines, ("5. trách nhiệm", "5.trách nhiệm", "trách nhiệm / bộ phận", "trach nhiem"))
    if start is None:
        return []
    end = find_line_index(lines[start + 1 :], ("6. nội dung", "6.nội dung", "noi dung cong viec", "nội dung công việc"))
    window = lines[start + 1 : start + 1 + end] if end is not None else lines[start + 1 : start + 60]
    items: list[str] = []
    current = ""
    for line in window:
        stripped = clean_summary_line(line)
        if not stripped:
            continue
        if re.match(r"^5\.\d+\.?", stripped):
            current = stripped
            items.append(current)
        elif stripped.startswith("-") and items:
            items[-1] = f"{items[-1]} {stripped}"
        if len(items) >= max_items:
            break
    return items


def extract_record_references(lines: list[str], max_items: int = 12) -> list[str]:
    start = find_line_index(lines, ("7. hồ sơ", "7.hồ sơ", "hồ sơ, tài liệu", "ho so", "biểu mẫu liên quan"))
    if start is None:
        return []
    window = lines[start : start + 40]
    items: list[str] = []
    pending_code = ""
    for line in window:
        stripped = clean_summary_line(line)
        if not stripped:
            continue
        code_match = re.search(r"\b(?:PD|BM|MS)-[A-Z0-9./-]+", stripped, flags=re.IGNORECASE)
        if code_match:
            pending_code = stripped
            items.append(stripped)
        elif stripped.startswith(":") and pending_code and items:
            items[-1] = f"{items[-1]} {stripped.lstrip(': ').strip()}"
        if len(items) >= max_items:
            break
    return items


def find_line_index(lines: list[str], needles: tuple[str, ...]) -> int | None:
    normalized_needles = [ascii_key(needle) for needle in needles]
    for idx, line in enumerate(lines):
        value = ascii_key(line)
        if any(needle in value for needle in normalized_needles):
            return idx
    return None


def clean_summary_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip(" -*\t")).strip()


def build_upload_rag_ready_artifacts(
    *,
    group: UploadDocumentGroup,
    paths: UploadRunPaths,
    primary: CandidateConversion,
    selected: str,
    decision: dict[str, Any],
    supporting_sources: list[dict[str, Any]],
    qa_report: dict[str, Any],
    converter: MinerUConverter,
) -> dict[str, Any]:
    text = paths.normalized.read_text(encoding="utf-8", errors="replace")
    sections = build_section_index(text, paths.normalized, group.doc_id, group.revision_slug)
    chunks = chunk_markdown_with_metadata(text)
    mineru_blocks = mineru_source_blocks(primary.mineru_artifact_index_path)
    source_blocks = mineru_blocks + source_evidence_blocks(primary.staged_source_path)
    chunk_records: list[dict[str, Any]] = []
    citation_records: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        anchor_id = stable_anchor_id(group.doc_id, group.revision_slug, index)
        chunk_id = f"{group.artifact_stem}_c{index}"
        section = section_for_chunk(sections, int(chunk["line_start"]))
        citation = build_citation_record(
            doc_id=group.doc_id,
            version=group.revision_slug,
            chunk_id=chunk_id,
            anchor_id=anchor_id,
            chunk=chunk,
            source_path=primary.staged_source_path,
            normalized_path=paths.normalized,
            source_blocks=source_blocks,
            section=section,
        )
        mineru_citation = build_citation_record(
            doc_id=group.doc_id,
            version=group.revision_slug,
            chunk_id=chunk_id,
            anchor_id=anchor_id,
            chunk=chunk,
            source_path=primary.staged_source_path,
            normalized_path=paths.normalized,
            source_blocks=mineru_blocks,
            section=section,
        )
        if mineru_citation.get("locator_status") == "resolved":
            citation["mineru_locator"] = mineru_citation.get("source_locator")
            citation["mineru_display_locator"] = mineru_citation.get("display_locator")
            citation["mineru_locator_confidence"] = mineru_citation.get("locator_confidence")
            citation["mineru_source_json"] = mineru_citation.get("source_json")
            if not citation.get("source_json"):
                citation["source_json"] = mineru_citation.get("source_json")
            if not citation.get("image_ref"):
                citation["image_ref"] = mineru_citation.get("image_ref")
        chunk_records.append(
            {
                "chunk_id": chunk_id,
                "anchor_id": anchor_id,
                "section_anchor_id": section.get("anchor_id") if section else None,
                "section_title": section.get("title") if section else None,
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "content_path": str(paths.normalized),
                "text_hash": stable_text_hash(str(chunk.get("text") or "")),
                "chunk_strategy": "markdown_blocks",
                "max_chars": 1200,
            }
        )
        citation_records.append(citation)

    metadata_artifact = {
        "artifact_schema_version": "upload_rag_metadata_v1",
        "document": {
            **group_metadata(group),
            "artifact_stem": group.artifact_stem,
            "status": "pending_review",
            "primary_source_type": selected,
            "primary_source_path": str(primary.staged_source_path),
            "supporting_sources": supporting_sources,
            "primary_source_decision": decision,
            "ingest_policy": "primary_source_only",
            "ragflow_ingestion": "not_run",
            "raw_converter": "mineru",
            "raw_conversion_policy": "mineru_only_no_fallback",
            "raw_markdown_path": str(primary.raw_markdown_path),
            "mineru_artifact_index_path": str(primary.mineru_artifact_index_path) if primary.mineru_artifact_index_path else None,
            "mineru_profile": converter.profile_dict() if hasattr(converter, "profile_dict") else {},
        },
        "source": {"path": str(primary.staged_source_path), "type": selected, "checksum": content_hash(primary.staged_source_path)},
        "normalized": {"path": str(paths.normalized), "checksum": content_hash(paths.normalized)},
        "quality": {"status": qa_report.get("status"), "issues": qa_report.get("issues") or []},
        "created_at": utc_now(),
    }
    write_json(paths.metadata_json, metadata_artifact)
    write_json(paths.section_index, sections)
    write_json(paths.chunk_plan, chunk_records)
    write_json(paths.citation_map, citation_records)
    paths.schema_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.normalized, paths.schema_manifest.parent / "normalized.md")
    schema_manifest = {
        "artifact_schema_version": "upload_rag_ready_v1",
        "doc_id": group.doc_id,
        "version": group.revision_slug,
        "display_code": group.display_code,
        "display_version": group.source_revision,
        "artifact_stem": group.artifact_stem,
        "status": "pending_review",
        "ragflow_ingestion": "not_run",
        "canonical_artifacts": {
            "normalized_markdown": str(paths.normalized),
            "metadata_json": str(paths.metadata_json),
            "section_index_json": str(paths.section_index),
            "chunk_plan_json": str(paths.chunk_plan),
            "citation_map_json": str(paths.citation_map),
            "quality_report_json": str(paths.quality_report),
            "mineru_artifact_index_json": str(primary.mineru_artifact_index_path) if primary.mineru_artifact_index_path else None,
        },
        "created_at": utc_now(),
    }
    write_json(paths.schema_manifest, schema_manifest)
    write_json(paths.citation_manifest, {"artifact_schema_version": "upload_citation_manifest_v1", "doc_id": group.doc_id, "version": group.revision_slug, "citations": citation_records})
    write_json(paths.index_manifest, {"artifact_schema_version": "upload_index_manifest_v1", "doc_id": group.doc_id, "version": group.revision_slug, "chunks": chunk_records, "created_at": utc_now()})
    return {
        "sections": sections,
        "chunks": chunk_records,
        "citations": citation_records,
        "source_locator_coverage": source_locator_coverage(citation_records),
        "schema_manifest": schema_manifest,
    }


def verify_upload_rag_readiness(
    *,
    group: UploadDocumentGroup,
    paths: UploadRunPaths,
    primary: CandidateConversion,
    qa_report: dict[str, Any],
    rag_ready: dict[str, Any],
    initial_audit: dict[str, Any],
) -> dict[str, Any]:
    text = paths.normalized.read_text(encoding="utf-8", errors="replace")
    citations = rag_ready.get("citations") or []
    issues: list[dict[str, Any]] = []
    issues.extend(normalized_title_quality_issues(group, text))
    summary_count = generated_rag_summary_count(text)
    if summary_count > 1:
        issues.append({"type": "duplicate_generated_rag_summary", "severity": "high", "count": summary_count})
    for heading in re.findall(r"^\s{0,3}#{1,6}\s+(.+)$", text, flags=re.MULTILINE):
        if is_synthetic_heading(heading):
            issues.append({"type": "synthetic_heading_not_in_source", "severity": "high", "text": heading})
    if qa_report.get("status") == "fail":
        issues.append({"type": "source_output_qa_failed", "severity": "high", "details": qa_report.get("issues") or []})
    if not citations:
        issues.append({"type": "missing_citation_anchor", "severity": "high"})
    locator_coverage = source_locator_coverage(citations)
    if locator_coverage < 0.8:
        issues.append({"type": "low_source_locator_coverage", "severity": "high", "coverage": locator_coverage})
    weak_citation_count = sum(
        1
        for citation in citations
        if citation.get("requires_human_review") or float(citation.get("locator_confidence") or 0.0) < 0.35
    )
    if weak_citation_count:
        issues.append({"type": "citation_locator_needs_review", "severity": "low", "count": weak_citation_count})
    rich_summary = {}
    if primary.mineru_artifact_index_path and primary.mineru_artifact_index_path.exists():
        try:
            rich_summary = json.loads(primary.mineru_artifact_index_path.read_text(encoding="utf-8")).get("summary") or {}
        except Exception:
            rich_summary = {}
    if not (rich_summary.get("has_content_list") or rich_summary.get("has_content_list_v2") or rich_summary.get("has_middle_json")):
        issues.append({"type": "mineru_rich_metadata_missing", "severity": "high"})
    canonical_paths = {
        "normalized_markdown": paths.normalized,
        "metadata_json": paths.metadata_json,
        "section_index_json": paths.section_index,
        "chunk_plan_json": paths.chunk_plan,
        "citation_map_json": paths.citation_map,
        "quality_report_json": paths.quality_report,
    }
    missing_artifacts = [name for name, path in canonical_paths.items() if name != "quality_report_json" and not path.exists()]
    if missing_artifacts:
        issues.append({"type": "canonical_artifact_missing", "severity": "high", "artifacts": missing_artifacts})
    high = any(issue.get("severity") == "high" for issue in issues)
    return {
        "schema_version": UPLOAD_RUN_SCHEMA_VERSION,
        "doc_id": group.doc_id,
        "display_code": group.display_code,
        "quality_status": "needs_review" if high else "passed",
        "quality_score": quality_score([*(initial_audit.get("issues") or []), *issues]),
        "issues": issues,
        "initial_audit": initial_audit,
        "qa_source_output": qa_report,
        "mineru_artifact_summary": rich_summary,
        "quality_gates": {
            "no_synthetic_heading": not any(issue.get("type") == "synthetic_heading_not_in_source" for issue in issues),
            "no_duplicate_generated_rag_summary": summary_count <= 1,
            "title_text_clean": not any(issue.get("type") == "metadata_title_text_corrupted" for issue in issues),
            "no_prompt_or_status_leak": not any(marker in ascii_key(text) for marker in PROMPT_DEBUG_MARKERS),
            "citation_anchors_present": bool(citations),
            "source_locator_coverage": locator_coverage,
            "citation_locator_review_required_count": weak_citation_count,
            "mineru_rich_metadata_available": bool(rich_summary),
            "supporting_source_not_ingested": True,
            "ragflow_ingestion_not_run": True,
        },
        "checked_at": utc_now(),
    }


def upsert_upload_manifest_record(
    *,
    root: Path,
    group: UploadDocumentGroup,
    paths: UploadRunPaths,
    primary: CandidateConversion,
    selected: str,
    decision: dict[str, Any],
    final_quality: dict[str, Any],
    converter: MinerUConverter,
    supporting: list[dict[str, Any]],
) -> ManifestRecord:
    now = utc_now()
    metadata = group_metadata(group)
    extra = {
        **metadata,
        "artifact_stem": group.artifact_stem,
        "display_code": group.display_code,
        "display_version": group.source_revision,
        "canonical_business_code": group.canonical_business_code,
        "primary_source_type": selected,
        "primary_source_path": str(primary.staged_source_path),
        "supporting_sources": supporting,
        "primary_source_decision": decision,
        "ingest_policy": "primary_source_only",
        "ragflow_ingestion": "not_run",
        "smoke_chat": "not_run",
        "raw_converter": "mineru",
        "raw_conversion_policy": "mineru_only_no_fallback",
        "raw_markdown_path": str(primary.raw_markdown_path),
        "mineru_artifact_index_path": str(primary.mineru_artifact_index_path) if primary.mineru_artifact_index_path else None,
        "mineru_profile": converter.profile_dict() if hasattr(converter, "profile_dict") else {},
        "metadata_json_path": str(paths.metadata_json),
        "section_index_path": str(paths.section_index),
        "chunk_plan_path": str(paths.chunk_plan),
        "citation_map_path": str(paths.citation_map),
        "quality_report_path": str(paths.quality_report),
        "human_review_path": str(paths.review_report),
        "schema_manifest_path": str(paths.schema_manifest),
        "citation_manifest_path": str(paths.citation_manifest),
        "index_manifest_path": str(paths.index_manifest),
        "quality_status": final_quality.get("quality_status"),
    }
    record = ManifestRecord(
        doc_id=group.doc_id,
        title=group.title,
        department="technical",
        category=group.category,
        source_type="internal_procedure",
        language="vi",
        version=group.revision_slug,
        status="pending_review",
        status_reason="Awaiting human review after Upload agent processing",
        effective_from=str(metadata["effective_from"]),
        review_at=str(metadata["review_at"]),
        owner="Phong Ky thuat",
        access_group="technical",
        source_path=str(primary.staged_source_path),
        normalized_path=str(paths.normalized),
        content_hash=content_hash(primary.staged_source_path),
        created_at=now,
        updated_at=now,
        extra=extra,
    )
    ManifestStore(root).upsert(record)
    QualityDatabase(root).log_ingestion("pending_review", group.doc_id, group.revision_slug)
    rebuild_indexes(root)
    return record


def build_human_review_packet(group: UploadDocumentGroup, paths: UploadRunPaths, quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_status": "pending_review",
        "reviewer": "human",
        "doc_id": group.doc_id,
        "display_code": group.display_code,
        "display_version": group.source_revision,
        "artifacts": {
            "normalized_markdown": str(paths.normalized),
            "metadata_json": str(paths.metadata_json),
            "section_index_json": str(paths.section_index),
            "chunk_plan_json": str(paths.chunk_plan),
            "citation_map_json": str(paths.citation_map),
            "quality_report_json": str(paths.quality_report),
        },
        "checklist": {
            "title_correct": False,
            "revision_correct": False,
            "headings_source_based": quality.get("quality_gates", {}).get("no_synthetic_heading") is True,
            "steps_order_correct": False,
            "no_synthetic_content": quality.get("quality_gates", {}).get("no_synthetic_heading") is True,
            "citations_correct": quality.get("quality_gates", {}).get("citation_anchors_present") is True,
            "source_output_audit_passed": quality.get("quality_status") == "passed",
        },
        "notes": "Human approval is required before any RAGFlow ingestion.",
        "created_at": utc_now(),
    }


def write_terminal_reports(
    paths: UploadRunPaths,
    group: UploadDocumentGroup,
    run_id: str,
    selected: str,
    decision: dict[str, Any],
    quality: dict[str, Any],
    *,
    status: str,
) -> None:
    run_report = [
        f"# Upload Agent Run Report - {group.display_code} {group.source_revision}",
        "",
        f"- run_id: `{run_id}`",
        f"- status: `{status}`",
        f"- doc_id: `{group.doc_id}`",
        f"- primary_source: `{selected}`",
        f"- ragflow_ingestion: `not_run`",
        f"- normalized_markdown: `{paths.normalized}`",
        f"- citation_map: `{paths.citation_map}`",
        f"- quality_status: `{quality.get('quality_status')}`",
        f"- quality_score: `{quality.get('quality_score')}`",
        "",
        "## Primary Source Decision",
        "",
        decision.get("reason", ""),
        "",
        "## Remaining Issues",
        "",
    ]
    issues = quality.get("issues") or []
    if issues:
        run_report.extend(f"- `{issue.get('type')}`: {issue.get('severity')}" for issue in issues)
    else:
        run_report.append("- None from automated QA. Human review is still required.")
    paths.run_report.write_text("\n".join(run_report).strip() + "\n", encoding="utf-8")
    evolution_report = [
        f"# Data Skill Evolution Report - {group.display_code} {group.source_revision}",
        "",
        "- auto_modify_skills: `false`",
        "- recommendation: keep MinerU sidecars in citation evidence and preserve source locator coverage checks.",
        "- rule_candidate: if PDF/XLSX pair shares `canonical_business_code`, convert/probe both but create exactly one pending review record.",
        f"- generated_at: `{utc_now()}`",
    ]
    paths.evolution_report.write_text("\n".join(evolution_report) + "\n", encoding="utf-8")


def terminal_upload_failure(
    *,
    root: Path,
    group: UploadDocumentGroup,
    paths: UploadRunPaths,
    run_id: str,
    conversions: dict[str, CandidateConversion],
    probe: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    source_id = group.artifact_stem
    quality = {
        "schema_version": UPLOAD_RUN_SCHEMA_VERSION,
        "doc_id": group.doc_id,
        "display_code": group.display_code,
        "quality_status": "blocked",
        "quality_score": 0.0,
        "issues": [{"type": "mineru_conversion_blocked", "severity": "high", "text": reason}],
        "source_probe": probe,
        "candidate_conversions": {source_type: candidate_summary(candidate) for source_type, candidate in conversions.items()},
        "checked_at": utc_now(),
    }
    write_json(paths.quality_report, quality)
    append_workflow_handoff(
        root,
        paths.artifact_root,
        make_handoff(
            run_id=run_id,
            step="convert",
            status="blocked",
            source_id=source_id,
            artifacts=conversion_artifact_records(conversions, source_id),
            quality_gates={"any_candidate_converted": False, "mineru_only": True},
            next_skill=None,
        ),
    )
    write_terminal_reports(paths, group, run_id, "none", {"reason": reason}, quality, status="blocked")
    return finalize_upload_queue_state(root, group, paths, status="failed", detail=reason)


def finalize_upload_queue_state(
    root: Path,
    group: UploadDocumentGroup,
    paths: UploadRunPaths,
    *,
    status: str,
    detail: str,
) -> dict[str, Any]:
    record_upload_workflow_event(
        root,
        group.relative_paths,
        status=status,
        step=status if status in {"failed", "ocr_required"} else "done",
        detail=detail,
        metadata=group_metadata(group),
        artifact_path=str(paths.artifact_root),
        qa_report_path=str(paths.quality_report) if paths.quality_report.exists() else None,
    )
    queue = list_upload_queue(root)
    return {
        "ok": status == "done",
        "status": "pending_review" if status == "done" else status,
        "doc_id": group.doc_id,
        "version": group.revision_slug,
        "display_code": group.display_code,
        "display_version": group.source_revision,
        "artifact_stem": group.artifact_stem,
        "normalized_path": str(paths.normalized),
        "quality_report_path": str(paths.quality_report),
        "citation_map_path": str(paths.citation_map),
        "run_report_path": str(paths.run_report),
        "queue_summary": queue.get("summary"),
    }


def supporting_sources(staged_sources: dict[str, Path], selected: str) -> list[dict[str, Any]]:
    supporting: list[dict[str, Any]] = []
    for source_type, path in staged_sources.items():
        if source_type == selected:
            continue
        supporting.append(
            {
                "type": source_type,
                "path": str(path),
                "role": "display_print_version" if source_type == "pdf" else "supporting_workbook",
                "used_for_retrieval": False,
            }
        )
    return supporting


def source_locator_coverage(citations: list[dict[str, Any]]) -> float:
    if not citations:
        return 0.0
    resolved = sum(1 for item in citations if item.get("locator_status") == "resolved")
    return round(resolved / len(citations), 4)


def normalized_title_quality_issues(group: UploadDocumentGroup, text: str) -> list[dict[str, Any]]:
    samples = [
        {"field": "group.title", "text": group.title},
    ]
    for line in text.splitlines()[:40]:
        stripped = line.strip()
        if stripped.startswith("title:"):
            samples.append({"field": "frontmatter.title", "text": stripped})
        if stripped.startswith("# "):
            samples.append({"field": "h1", "text": stripped})
            break

    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for sample in samples:
        value = str(sample.get("text") or "")
        if not looks_like_corrupted_metadata_text(value):
            continue
        key = (str(sample["field"]), value)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            {
                "type": "metadata_title_text_corrupted",
                "severity": "high",
                "field": sample["field"],
                "text": value[:160],
            }
        )
    return issues


def looks_like_corrupted_metadata_text(value: str) -> bool:
    if not value:
        return False
    if "\ufffd" in value or "\u00ef\u00bf\u00bd" in value:
        return True
    if mojibake_score(value):
        return True
    return bool(TITLE_CORRUPTION_PATTERN.search(value))


def section_for_chunk(sections: list[dict[str, Any]], line_start: int) -> dict[str, Any] | None:
    for section in sections:
        if int(section["line_start"]) <= line_start <= int(section["line_end"]):
            return section
    return sections[-1] if sections else None


def stable_text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def preclean_markdown(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def markdown_heading_text(line: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
    return match.group(1).strip() if match else None


def markdown_heading_level(line: str) -> int | None:
    match = re.match(r"^\s{0,3}(#{1,6})\s+.+?\s*$", line)
    return len(match.group(1)) if match else None


def is_generated_rag_summary_heading(line: str) -> bool:
    heading = markdown_heading_text(line)
    return bool(heading and GENERATED_RAG_SUMMARY_KEY in ascii_key(heading))


def generated_rag_summary_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if is_generated_rag_summary_heading(line))


def is_noise_line(line: str) -> bool:
    normalized = ascii_key(line)
    return any(marker in normalized for marker in PROMPT_DEBUG_MARKERS)


def is_synthetic_heading(heading: str) -> bool:
    return ascii_key(heading).strip("# ") in SYNTHETIC_HEADINGS


def quality_score(issues: list[dict[str, Any]]) -> float:
    score = 1.0
    for issue in issues:
        severity = issue.get("severity")
        if severity == "high":
            score -= 0.20
        elif severity == "medium":
            score -= 0.10
        else:
            score -= 0.03
    return round(max(0.0, min(1.0, score)), 2)


def ascii_key(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def safe_ascii_code(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", ascii_key(value))
