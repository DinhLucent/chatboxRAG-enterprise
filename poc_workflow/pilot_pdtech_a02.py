from __future__ import annotations

import json
import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .converter import MinerUConverter, find_mineru_artifact_index
from .database import QualityDatabase
from .data_workflow import (
    artifact_record,
    load_agent_skill_registry,
    make_handoff,
    validate_handoff_transition,
    validate_workflow_handoff,
)
from .manifest import ManifestStore
from .models import ManifestRecord
from .pipeline import approve_record, init_workspace, rebuild_indexes
from .utils import content_hash, safe_filename, utc_now, write_json


PILOT_DOC_ID = "KT-QT-002"
PILOT_INTERNAL_VERSION = "1.0"
PILOT_ARTIFACT_STEM = "KT-QT-002_rev04"
PILOT_DISPLAY_CODE = "PD-TECH-A-02"
PILOT_TITLE = "Quy trình bảo dưỡng"
PILOT_SOURCE_REVISION = "Rev 04"
PILOT_SCOPE_ID = "pdtech_a02_rev04_pilot"
SYNTHETIC_HEADINGS = {
    "fixing metadata",
    "incident response",
    "smart fix",
    "fix review",
}
RAW_PROMPT_DEBUG_MARKERS = {
    "agent task",
    "debug",
    "submitting mineru",
    "task completed",
    "quality gate",
    "repair loop",
}
CANONICAL_SECTION_TITLES = {
    "muc dich": "Mục đích",
    "pham vi": "Phạm vi áp dụng",
    "trach nhiem": "Trách nhiệm",
    "quy trinh": "Quy trình thực hiện",
    "noi dung cong viec": "Quy trình thực hiện",
    "cac buoc": "Quy trình thực hiện",
    "ho so": "Hồ sơ / biểu mẫu liên quan",
    "bieu mau": "Hồ sơ / biểu mẫu liên quan",
    "tai lieu lien quan": "Tài liệu liên quan",
}


class PilotError(RuntimeError):
    pass


@dataclass(frozen=True)
class PilotPaths:
    converted_raw: Path
    staging: Path
    normalized: Path
    section_index: Path
    chunk_plan: Path
    citation_map: Path
    mineru_artifact_index: Path
    probe_report: Path
    quality_report: Path
    review_report: Path


@dataclass(frozen=True)
class AgentSandboxPaths:
    sandbox: Path
    source_dir: Path
    converted_raw: Path
    mineru_artifact_index: Path
    staging: Path
    normalized: Path
    indexes: Path
    reports: Path
    workflow_handoffs: Path
    source_probe_report: Path
    quality_report: Path
    repair_log: Path
    review_report: Path
    run_report: Path
    evolution_report: Path


@dataclass(frozen=True)
class AgentCandidateConversion:
    source_type: str
    source_path: Path
    raw_markdown_path: Path
    artifact_root: Path
    mineru_artifact_index_path: Path | None
    status: str
    error: str | None = None


def run_pdtech_a02_agent_sandbox(
    root: Path,
    *,
    xlsx_path: Path | None = None,
    pdf_path: Path | None = None,
    primary_source: str = "auto",
    converter: MinerUConverter | None = None,
    stamp: str | None = None,
) -> dict[str, Any]:
    """Run the PD-TECH-A-02 agent workflow in an isolated quality sandbox."""
    root = root.resolve()
    sources = resolve_pilot_sources(root, xlsx_path=xlsx_path, pdf_path=pdf_path)
    paths = create_agent_sandbox_paths(root, stamp=stamp)
    create_agent_sandbox_dirs(paths)
    init_workspace(paths.sandbox)

    sandbox_sources = copy_sources_to_agent_sandbox(sources, paths.source_dir)
    converter = converter or MinerUConverter.from_env()
    run_id = workflow_agent_run_id(stamp=stamp)
    source_id = f"{PILOT_ARTIFACT_STEM}"

    append_agent_sandbox_handoff(
        paths,
        make_handoff(
            run_id=run_id,
            step="plan",
            status="ready",
            source_id=source_id,
            artifacts=[
                artifact_record(
                    sandbox_sources["xlsx"],
                    artifact_id=f"source_xlsx_{source_id}",
                    artifact_type="raw",
                    source_id=source_id,
                ),
                artifact_record(
                    sandbox_sources["pdf"],
                    artifact_id=f"source_pdf_{source_id}",
                    artifact_type="raw",
                    source_id=source_id,
                ),
            ],
            quality_gates={"single_business_document": True, "sandbox_isolated": True, "mineru_only": True},
            next_skill="mineru-source-converter",
        ),
    )

    probe = build_source_probe_report(sandbox_sources["xlsx"], sandbox_sources["pdf"])
    conversions: dict[str, AgentCandidateConversion] = {}
    for candidate_type in ("xlsx", "pdf"):
        conversions[candidate_type] = convert_agent_candidate(
            converter,
            sandbox_sources[candidate_type],
            candidate_type,
            paths,
        )
    selected = select_agent_primary_source(probe, conversions, primary_source)
    if not selected:
        write_agent_failure_reports(
            paths=paths,
            run_id=run_id,
            conversions=conversions,
            probe=probe,
            reason="MinerU did not produce a usable Markdown output for any candidate source.",
        )
        append_agent_sandbox_handoff(
            paths,
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
        raise PilotError("Agent sandbox blocked: no candidate source converted successfully with MinerU.")

    decision = {
        "selected": selected,
        "reason": agent_primary_decision_reason(probe, conversions, selected, primary_source),
        "decided_at": utc_now(),
        "decided_by": "human" if primary_source in {"xlsx", "pdf"} else "system",
        "probe_report_path": str(paths.source_probe_report),
    }
    probe["recommended_primary_source"] = selected
    probe["reason"] = decision["reason"]
    probe["candidate_conversions"] = {
        source_type: candidate_conversion_summary(candidate) for source_type, candidate in conversions.items()
    }
    write_json(paths.source_probe_report, probe)

    append_agent_sandbox_handoff(
        paths,
        make_handoff(
            run_id=run_id,
            step="convert",
            status="passed",
            source_id=source_id,
            artifacts=[
                *conversion_artifact_records(conversions, source_id),
                artifact_record(
                    paths.source_probe_report,
                    artifact_id=f"source_probe_report_{source_id}",
                    artifact_type="audit",
                    source_id=source_id,
                ),
            ],
            quality_gates={
                "any_candidate_converted": True,
                "primary_source_selected": True,
                "selected_primary_source": selected,
                "duplicate_retrieval_blocked": True,
                "mineru_only": True,
            },
            next_skill="source-output-quality-auditor",
        ),
    )

    primary = conversions[selected]
    audit_report = build_agent_initial_audit_report(probe, conversions, selected)
    repair_request_path = paths.reports / "repair_handoff.json"
    write_json(paths.quality_report, audit_report)
    write_json(repair_request_path, build_agent_repair_handoff(audit_report, primary))
    append_agent_sandbox_handoff(
        paths,
        make_handoff(
            run_id=run_id,
            step="audit",
            status="needs_repair",
            source_id=source_id,
            artifacts=[
                artifact_record(
                    paths.quality_report,
                    artifact_id=f"initial_audit_report_{source_id}",
                    artifact_type="audit",
                    source_id=source_id,
                ),
                artifact_record(
                    repair_request_path,
                    artifact_id=f"repair_request_{source_id}",
                    artifact_type="audit",
                    source_id=source_id,
                ),
            ],
            quality_gates={
                "raw_outputs_reviewed": True,
                "repair_required_for_rag_markdown": True,
                "mineru_artifact_index_checked": bool(primary.mineru_artifact_index_path),
            },
            next_skill="rag-markdown-repairer",
        ),
    )

    normalized_text, section_index, citation_map = normalize_primary_source(
        primary.source_path,
        selected,
        primary.raw_markdown_path,
        mineru_artifact_index_path=primary.mineru_artifact_index_path,
    )
    draft_path = paths.staging / f"{PILOT_ARTIFACT_STEM}_draft.md"
    section_index_path = paths.indexes / f"{PILOT_ARTIFACT_STEM}_section_index.json"
    chunk_plan_path = paths.indexes / f"{PILOT_ARTIFACT_STEM}_chunk_plan.json"
    citation_map_path = paths.indexes / f"{PILOT_ARTIFACT_STEM}_citation_map.json"
    repair_strategies: list[dict[str, Any]] = [
        {
            "iteration": 1,
            "strategy": "mineru_raw_restructure",
            "input": str(primary.raw_markdown_path),
            "rationale": "Use MinerU Markdown and sidecars as the first repair draft.",
        }
    ]
    write_agent_normalized_outputs(
        normalized_text=normalized_text,
        section_index=section_index,
        citation_map=citation_map,
        draft_path=draft_path,
        normalized_path=paths.normalized,
        section_index_path=section_index_path,
        chunk_plan_path=chunk_plan_path,
        citation_map_path=citation_map_path,
    )
    final_quality = verify_normalized_markdown(
        draft_path,
        citation_map_path=citation_map_path,
        primary_source_type=selected,
        raw_markdown_path=primary.raw_markdown_path,
        raw_converter="mineru",
        mineru_artifact_index_path=primary.mineru_artifact_index_path,
        strict_rag_readiness=True,
    )
    if final_quality["quality_status"] != "passed" and selected == "xlsx":
        repaired_text, repaired_sections, repaired_citations = normalize_source_assisted_xlsx(
            primary.source_path,
            mineru_artifact_index_path=primary.mineru_artifact_index_path,
        )
        normalized_text = repaired_text
        section_index = repaired_sections
        citation_map = repaired_citations
        write_agent_normalized_outputs(
            normalized_text=normalized_text,
            section_index=section_index,
            citation_map=citation_map,
            draft_path=draft_path,
            normalized_path=paths.normalized,
            section_index_path=section_index_path,
            chunk_plan_path=chunk_plan_path,
            citation_map_path=citation_map_path,
        )
        repair_strategies.append(
            {
                "iteration": 2,
                "strategy": "source_assisted_xlsx_rebuild",
                "input": str(primary.source_path),
                "rationale": "Strict QA rejected weak MinerU raw structure or locator precision; rebuild from workbook rows and keep MinerU refs.",
                "trigger_issues": [issue.get("type") for issue in final_quality.get("issues") or []],
            }
        )
        final_quality = verify_normalized_markdown(
            draft_path,
            citation_map_path=citation_map_path,
            primary_source_type=selected,
            raw_markdown_path=primary.raw_markdown_path,
            raw_converter="mineru",
            mineru_artifact_index_path=primary.mineru_artifact_index_path,
            strict_rag_readiness=True,
        )
    write_json(section_index_path, section_index)
    chunk_plan = build_chunk_plan(citation_map)
    write_json(chunk_plan_path, chunk_plan)
    write_json(citation_map_path, citation_map)
    repair_log = build_agent_repair_log(
        selected=selected,
        draft_path=draft_path,
        normalized_path=paths.normalized,
        section_index_path=section_index_path,
        chunk_plan_path=chunk_plan_path,
        citation_map_path=citation_map_path,
        section_index=section_index,
        chunk_plan=chunk_plan,
        citation_map=citation_map,
        repair_strategies=repair_strategies,
        final_quality=final_quality,
    )
    write_json(paths.repair_log, repair_log)
    append_agent_sandbox_handoff(
        paths,
        make_handoff(
            run_id=run_id,
            step="repair",
            status="passed",
            source_id=source_id,
            artifacts=[
                artifact_record(draft_path, artifact_id=f"draft_markdown_{source_id}", artifact_type="repair", source_id=source_id),
                artifact_record(paths.normalized, artifact_id=f"normalized_markdown_{source_id}", artifact_type="repair", source_id=source_id),
                artifact_record(paths.repair_log, artifact_id=f"repair_log_{source_id}", artifact_type="repair", source_id=source_id),
            ],
            quality_gates={
                "normalized_markdown_created": True,
                "section_index_created": bool(section_index),
                "citation_map_created": bool(citation_map),
                "repair_iterations": len(repair_strategies),
            },
            next_skill="source-output-quality-auditor",
        ),
    )
    final_quality["initial_audit"] = audit_report
    write_json(paths.quality_report, final_quality)
    if final_quality["quality_status"] != "passed":
        write_agent_terminal_reports(
            paths=paths,
            run_id=run_id,
            selected=selected,
            decision=decision,
            conversions=conversions,
            quality_report=final_quality,
            review=None,
            stopped_at="qa_recheck",
        )
        append_agent_sandbox_handoff(
            paths,
            make_handoff(
                run_id=run_id,
                step="audit",
                status="blocked",
                source_id=source_id,
                artifacts=[
                    artifact_record(
                        paths.quality_report,
                        artifact_id=f"final_quality_report_{source_id}",
                        artifact_type="audit",
                        source_id=source_id,
                    )
                ],
                quality_gates={
                    "quality_status": final_quality["quality_status"],
                    "quality_score": final_quality["quality_score"],
                    "required_quality_passed": False,
                },
                next_skill=None,
            ),
        )
        return agent_sandbox_result(paths, run_id, selected, final_quality, status="blocked")

    append_agent_sandbox_handoff(
        paths,
        make_handoff(
            run_id=run_id,
            step="audit",
            status="passed",
            source_id=source_id,
            artifacts=[
                artifact_record(
                    paths.quality_report,
                    artifact_id=f"final_quality_report_{source_id}",
                    artifact_type="audit",
                    source_id=source_id,
                )
            ],
            quality_gates={
                "quality_status": final_quality["quality_status"],
                "quality_score": final_quality["quality_score"],
                "synthetic_heading_count": final_quality["synthetic_heading_count"],
                "missing_citation_anchor_count": final_quality["missing_citation_anchor_count"],
            },
            next_skill="ragflow-schema-indexer",
        ),
    )

    metadata_path = paths.indexes / f"{PILOT_ARTIFACT_STEM}_metadata.json"
    schema_manifest_path = paths.indexes / f"{PILOT_ARTIFACT_STEM}_schema_manifest.json"
    metadata_artifact = build_agent_metadata_artifact(
        primary=primary,
        selected=selected,
        decision=decision,
        supporting_sources=build_supporting_sources(sandbox_sources, selected),
        paths=paths,
        section_index_path=section_index_path,
        chunk_plan_path=chunk_plan_path,
        citation_map_path=citation_map_path,
        quality_report=final_quality,
        converter=converter,
    )
    write_json(metadata_path, metadata_artifact)
    write_json(
        schema_manifest_path,
        {
            "artifact_schema_version": "agent_sandbox_rag_ready_v1",
            "doc_id": PILOT_DOC_ID,
            "artifact_stem": PILOT_ARTIFACT_STEM,
            "status": "pending_review",
            "ragflow_ingestion": "not_run",
            "canonical_artifacts": {
                "normalized_markdown": str(paths.normalized),
                "metadata_json": str(metadata_path),
                "section_index_json": str(section_index_path),
                "chunk_plan_json": str(chunk_plan_path),
                "citation_map_json": str(citation_map_path),
                "quality_report_json": str(paths.quality_report),
                "mineru_artifact_index_json": str(primary.mineru_artifact_index_path) if primary.mineru_artifact_index_path else None,
            },
            "created_at": utc_now(),
        },
    )
    append_agent_sandbox_handoff(
        paths,
        make_handoff(
            run_id=run_id,
            step="index",
            status="passed",
            source_id=source_id,
            artifacts=[
                artifact_record(metadata_path, artifact_id=f"metadata_json_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(section_index_path, artifact_id=f"section_index_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(chunk_plan_path, artifact_id=f"chunk_plan_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(citation_map_path, artifact_id=f"citation_map_{source_id}", artifact_type="rag_ready", source_id=source_id),
                artifact_record(schema_manifest_path, artifact_id=f"schema_manifest_{source_id}", artifact_type="rag_ready", source_id=source_id),
            ],
            quality_gates={
                "rag_ready_created": True,
                "ragflow_ingestion_not_run": True,
                "human_review_required": True,
            },
            next_skill="data-skill-evolution",
        ),
    )

    review = build_review_report(approved=False, reviewer="human")
    review["review_status"] = "pending_review"
    write_json(paths.review_report, review)
    record = upsert_agent_sandbox_record(
        paths.sandbox,
        primary=primary,
        selected=selected,
        decision=decision,
        metadata_path=metadata_path,
        section_index_path=section_index_path,
        chunk_plan_path=chunk_plan_path,
        citation_map_path=citation_map_path,
        schema_manifest_path=schema_manifest_path,
        quality_report=final_quality,
        review=review,
        converter=converter,
        supporting_sources=build_supporting_sources(sandbox_sources, selected),
    )
    rebuild_indexes(paths.sandbox)
    write_agent_terminal_reports(
        paths=paths,
        run_id=run_id,
        selected=selected,
        decision=decision,
        conversions=conversions,
        quality_report=final_quality,
        review=review,
        stopped_at="pending_review",
    )
    append_agent_sandbox_handoff(
        paths,
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
    return agent_sandbox_result(paths, run_id, selected, final_quality, status=record.status)


def run_pdtech_a02_pilot(
    root: Path,
    *,
    xlsx_path: Path | None = None,
    pdf_path: Path | None = None,
    primary_source: str = "auto",
    approve_review: bool = False,
    reviewer: str = "human",
    converter: MinerUConverter | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    init_workspace(root)
    paths = pilot_paths(root)
    for directory in {
        paths.converted_raw,
        paths.staging,
        paths.normalized.parent,
        paths.section_index.parent,
        paths.review_report.parent,
    }:
        directory.mkdir(parents=True, exist_ok=True)

    sources = resolve_pilot_sources(root, xlsx_path=xlsx_path, pdf_path=pdf_path)
    probe = build_source_probe_report(sources["xlsx"], sources["pdf"])
    selected = select_primary_source(probe, primary_source)
    decision = {
        "selected": selected,
        "reason": primary_decision_reason(probe, selected, primary_source),
        "decided_at": utc_now(),
        "decided_by": "human" if primary_source in {"xlsx", "pdf"} else "system",
        "probe_report_path": str(paths.probe_report),
    }
    probe["recommended_primary_source"] = selected
    probe["reason"] = decision["reason"]
    write_json(paths.probe_report, probe)

    primary_path = sources[selected]
    supporting_sources = build_supporting_sources(sources, selected)
    raw_md = paths.converted_raw / f"{PILOT_ARTIFACT_STEM}_raw.md"
    converter = converter or MinerUConverter.from_env()
    converter.convert_with_mineru(
        primary_path,
        raw_md,
        language="vi",
        artifact_root=paths.converted_raw / "mineru_raw",
    )
    dynamic_mineru_index = find_mineru_artifact_index(paths.converted_raw / "mineru_raw", raw_md)
    mineru_artifact_index_path: Path | None = None
    if dynamic_mineru_index:
        shutil.copy2(dynamic_mineru_index, paths.mineru_artifact_index)
        mineru_artifact_index_path = paths.mineru_artifact_index

    normalized_text, section_index, citation_map = normalize_primary_source(
        primary_path,
        selected,
        raw_md,
        mineru_artifact_index_path=mineru_artifact_index_path,
    )
    paths.staging.mkdir(parents=True, exist_ok=True)
    draft_path = paths.staging / f"{PILOT_ARTIFACT_STEM}_draft.md"
    draft_path.write_text(normalized_text, encoding="utf-8")
    write_json(paths.section_index, section_index)
    chunk_plan = build_chunk_plan(citation_map)
    write_json(paths.chunk_plan, chunk_plan)
    write_json(paths.citation_map, citation_map)

    quality_report = verify_normalized_markdown(
        draft_path,
        citation_map_path=paths.citation_map,
        primary_source_type=selected,
        raw_markdown_path=raw_md,
        raw_converter="mineru",
        mineru_artifact_index_path=mineru_artifact_index_path,
    )
    write_json(paths.quality_report, quality_report)
    if quality_report["quality_status"] != "passed":
        raise PilotError(f"Pilot verification failed: {quality_report['issues']}")

    paths.normalized.write_text(normalized_text, encoding="utf-8")
    review = build_review_report(approved=approve_review, reviewer=reviewer)
    write_json(paths.review_report, review)

    record = upsert_pilot_record(
        root,
        primary_path=primary_path,
        selected=selected,
        decision=decision,
        supporting_sources=supporting_sources,
        paths=paths,
        quality_report=quality_report,
        review=review,
        mineru_profile=converter.profile_dict() if hasattr(converter, "profile_dict") else {},
        mineru_artifact_index_path=mineru_artifact_index_path,
    )
    if approve_review:
        retire_duplicate_business_records(root, keep_key=record.key)
        record = approve_record(root, record.doc_id, record.version, reviewer)
    else:
        rebuild_indexes(root)

    return {
        "ok": True,
        "doc_id": record.doc_id,
        "version": record.version,
        "display_code": PILOT_DISPLAY_CODE,
        "display_version": PILOT_SOURCE_REVISION,
        "status": record.status,
        "primary_source": selected,
        "raw_converter": "mineru",
        "raw_path": str(raw_md),
        "mineru_artifact_index_path": str(mineru_artifact_index_path) if mineru_artifact_index_path else None,
        "mineru_profile": converter.profile_dict() if hasattr(converter, "profile_dict") else {},
        "normalized_path": str(paths.normalized),
        "probe_report_path": str(paths.probe_report),
        "citation_map_path": str(paths.citation_map),
        "review_report_path": str(paths.review_report),
        "quality_status": quality_report["quality_status"],
        "quality_score": quality_report["quality_score"],
    }


def pilot_paths(root: Path) -> PilotPaths:
    return PilotPaths(
        converted_raw=root / "converted_raw" / "pilot" / PILOT_DISPLAY_CODE,
        staging=root / "staging" / "pilot" / PILOT_DISPLAY_CODE,
        normalized=root / "normalized" / "technical" / "procedure" / f"{PILOT_ARTIFACT_STEM}.md",
        section_index=root / "indexes" / f"{PILOT_ARTIFACT_STEM}_section_index.json",
        chunk_plan=root / "indexes" / f"{PILOT_ARTIFACT_STEM}_chunk_plan.json",
        citation_map=root / "indexes" / f"{PILOT_ARTIFACT_STEM}_citation_map.json",
        mineru_artifact_index=root
        / "converted_raw"
        / "pilot"
        / PILOT_DISPLAY_CODE
        / f"{PILOT_ARTIFACT_STEM}_mineru_artifact_index.json",
        probe_report=root / "converted_raw" / "pilot" / PILOT_DISPLAY_CODE / "source_probe_report.json",
        quality_report=root / "converted_raw" / "pilot" / PILOT_DISPLAY_CODE / "quality_report.json",
        review_report=root / "review" / "pilot" / PILOT_DISPLAY_CODE / "human_review.json",
    )


def create_agent_sandbox_paths(root: Path, *, stamp: str | None = None) -> AgentSandboxPaths:
    stamp = stamp or utc_now().replace(":", "").replace("+", "Z")
    sandbox = root / ".quality-sandbox" / f"single-doc-agent-run-{safe_filename(stamp)}"
    return AgentSandboxPaths(
        sandbox=sandbox,
        source_dir=sandbox / "source",
        converted_raw=sandbox / "converted_raw",
        mineru_artifact_index=sandbox / "mineru_artifact_index",
        staging=sandbox / "staging",
        normalized=sandbox / "normalized" / "technical" / "procedure" / f"{PILOT_ARTIFACT_STEM}.md",
        indexes=sandbox / "indexes",
        reports=sandbox / "reports",
        workflow_handoffs=sandbox / "workflow_handoffs.jsonl",
        source_probe_report=sandbox / "reports" / "source_probe_report.json",
        quality_report=sandbox / "reports" / "quality_report.json",
        repair_log=sandbox / "reports" / "repair_log.json",
        review_report=sandbox / "review" / "human_review.json",
        run_report=sandbox / "reports" / "run_report.md",
        evolution_report=sandbox / "reports" / "evolution_report.md",
    )


def create_agent_sandbox_dirs(paths: AgentSandboxPaths) -> None:
    for directory in {
        paths.source_dir,
        paths.converted_raw / "pdf",
        paths.converted_raw / "xlsx",
        paths.mineru_artifact_index,
        paths.staging,
        paths.normalized.parent,
        paths.indexes,
        paths.reports,
        paths.review_report.parent,
    }:
        directory.mkdir(parents=True, exist_ok=True)


def copy_sources_to_agent_sandbox(sources: dict[str, Path], source_dir: Path) -> dict[str, Path]:
    copied: dict[str, Path] = {}
    for source_type, path in sources.items():
        destination = source_dir / source_type / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied[source_type] = destination.resolve()
    return copied


def workflow_agent_run_id(*, stamp: str | None = None) -> str:
    stamp = stamp or utc_now().replace(":", "").replace("+", "Z")
    return f"agent-run-{PILOT_ARTIFACT_STEM}-{safe_filename(stamp)}"


def append_agent_sandbox_handoff(paths: AgentSandboxPaths, handoff: dict[str, Any]) -> Path:
    registry = load_agent_skill_registry()
    validate_workflow_handoff(handoff, registry=registry)
    previous = read_agent_sandbox_handoffs(paths.workflow_handoffs)
    validate_handoff_transition(previous, handoff, registry)
    payload = {**handoff, "recorded_at": utc_now()}
    paths.workflow_handoffs.parent.mkdir(parents=True, exist_ok=True)
    with paths.workflow_handoffs.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    write_json(paths.sandbox / "latest_handoff.json", payload)
    return paths.workflow_handoffs


def read_agent_sandbox_handoffs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def convert_agent_candidate(
    converter: MinerUConverter,
    source_path: Path,
    source_type: str,
    paths: AgentSandboxPaths,
) -> AgentCandidateConversion:
    raw_markdown_path = paths.converted_raw / source_type / f"{PILOT_ARTIFACT_STEM}_{source_type}_raw.md"
    artifact_root = paths.converted_raw / source_type / "mineru_raw"
    try:
        converter.convert_with_mineru(
            source_path,
            raw_markdown_path,
            language="vi",
            artifact_root=artifact_root,
        )
        mineru_index = find_mineru_artifact_index(artifact_root, raw_markdown_path)
        if mineru_index:
            destination = paths.mineru_artifact_index / f"{source_type}_mineru_artifact_index.json"
            shutil.copy2(mineru_index, destination)
            mineru_index = destination
        if not raw_markdown_path.exists() or len(raw_markdown_path.read_text(encoding="utf-8", errors="ignore").strip()) < 20:
            raise PilotError(f"MinerU raw Markdown is empty or too short for {source_type}")
        return AgentCandidateConversion(
            source_type=source_type,
            source_path=source_path,
            raw_markdown_path=raw_markdown_path,
            artifact_root=artifact_root,
            mineru_artifact_index_path=mineru_index,
            status="passed",
        )
    except Exception as exc:
        return AgentCandidateConversion(
            source_type=source_type,
            source_path=source_path,
            raw_markdown_path=raw_markdown_path,
            artifact_root=artifact_root,
            mineru_artifact_index_path=None,
            status="blocked",
            error=str(exc),
        )


def select_agent_primary_source(
    probe: dict[str, Any],
    conversions: dict[str, AgentCandidateConversion],
    primary_source: str,
) -> str | None:
    if primary_source not in {"auto", "xlsx", "pdf"}:
        raise PilotError("primary_source must be auto, xlsx, or pdf")
    if primary_source in {"xlsx", "pdf"}:
        return primary_source if conversions[primary_source].status == "passed" else None
    passed = [source_type for source_type, candidate in conversions.items() if candidate.status == "passed"]
    if not passed:
        return None
    recommended = select_primary_source(probe, "auto")
    if recommended in passed:
        return recommended
    return max(
        passed,
        key=lambda source_type: float((probe.get(f"{source_type}_probe") or {}).get("parse_score") or 0.0),
    )


def agent_primary_decision_reason(
    probe: dict[str, Any],
    conversions: dict[str, AgentCandidateConversion],
    selected: str,
    requested: str,
) -> str:
    if requested in {"xlsx", "pdf"}:
        return f"{requested.upper()} selected by explicit operator override after MinerU conversion passed."
    conversion_status = {
        source_type: candidate.status for source_type, candidate in conversions.items()
    }
    return f"{selected.upper()} selected by source probe and MinerU conversion status: {conversion_status}."


def candidate_conversion_summary(candidate: AgentCandidateConversion) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source_type": candidate.source_type,
        "source_path": str(candidate.source_path),
        "raw_markdown_path": str(candidate.raw_markdown_path),
        "artifact_root": str(candidate.artifact_root),
        "mineru_artifact_index_path": str(candidate.mineru_artifact_index_path)
        if candidate.mineru_artifact_index_path
        else None,
        "status": candidate.status,
        "error": candidate.error,
    }
    if candidate.raw_markdown_path.exists():
        text = candidate.raw_markdown_path.read_text(encoding="utf-8", errors="ignore")
        summary["raw_markdown_chars"] = len(text)
        summary["raw_markdown_non_empty"] = len(text.strip()) >= 20
        summary["raw_prompt_debug_count"] = count_raw_prompt_debug_markers(text)
    if candidate.mineru_artifact_index_path and candidate.mineru_artifact_index_path.exists():
        try:
            summary["mineru_artifact_summary"] = json.loads(
                candidate.mineru_artifact_index_path.read_text(encoding="utf-8")
            ).get("summary")
        except Exception:
            summary["mineru_artifact_summary"] = None
    return summary


def conversion_artifact_records(
    conversions: dict[str, AgentCandidateConversion],
    source_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source_type, candidate in conversions.items():
        if candidate.raw_markdown_path.exists():
            records.append(
                artifact_record(
                    candidate.raw_markdown_path,
                    artifact_id=f"mineru_raw_{source_type}_{source_id}",
                    artifact_type="converted",
                    source_id=source_id,
                )
            )
        if candidate.mineru_artifact_index_path and candidate.mineru_artifact_index_path.exists():
            records.append(
                artifact_record(
                    candidate.mineru_artifact_index_path,
                    artifact_id=f"mineru_artifact_index_{source_type}_{source_id}",
                    artifact_type="converted",
                    source_id=source_id,
                )
            )
    return records


def build_agent_initial_audit_report(
    probe: dict[str, Any],
    conversions: dict[str, AgentCandidateConversion],
    selected: str,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for source_type, candidate in conversions.items():
        if candidate.status != "passed":
            issues.append(
                {
                    "type": "candidate_mineru_conversion_blocked",
                    "severity": "medium",
                    "source_type": source_type,
                    "text": candidate.error,
                }
            )
            continue
        summary = candidate_conversion_summary(candidate)
        if not summary.get("raw_markdown_non_empty"):
            issues.append(
                {
                    "type": "empty_mineru_raw_markdown",
                    "severity": "high",
                    "source_type": source_type,
                }
            )
        artifact_summary = summary.get("mineru_artifact_summary") or {}
        if not (
            artifact_summary.get("has_content_list")
            or artifact_summary.get("has_content_list_v2")
            or artifact_summary.get("has_middle_json")
        ):
            issues.append(
                {
                    "type": "mineru_rich_metadata_missing",
                    "severity": "high" if source_type == selected else "medium",
                    "source_type": source_type,
                }
            )
    score = quality_score(issues)
    return {
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "stage": "initial_source_output_audit",
        "selected_primary_source": selected,
        "quality_status": "needs_repair",
        "quality_score": score,
        "source_probe": probe,
        "candidate_conversions": {
            source_type: candidate_conversion_summary(candidate) for source_type, candidate in conversions.items()
        },
        "issues": issues,
        "checked_at": utc_now(),
    }


def build_agent_repair_handoff(
    audit_report: dict[str, Any],
    primary: AgentCandidateConversion,
) -> dict[str, Any]:
    return {
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "source_revision": PILOT_SOURCE_REVISION,
        "task": "repair_mineru_markdown_for_rag",
        "primary_source_type": primary.source_type,
        "primary_source_path": str(primary.source_path),
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


def build_agent_repair_log(
    *,
    selected: str,
    draft_path: Path,
    normalized_path: Path,
    section_index_path: Path,
    chunk_plan_path: Path,
    citation_map_path: Path,
    section_index: list[dict[str, Any]],
    chunk_plan: list[dict[str, Any]],
    citation_map: list[dict[str, Any]],
    repair_strategies: list[dict[str, Any]] | None = None,
    final_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    strategies = repair_strategies or []
    return {
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "source_revision": PILOT_SOURCE_REVISION,
        "repair_iterations": len(strategies) or 1,
        "repair_strategies": strategies,
        "selected_primary_source": selected,
        "outputs": {
            "draft_markdown": str(draft_path),
            "normalized_markdown": str(normalized_path),
            "section_index_json": str(section_index_path),
            "chunk_plan_json": str(chunk_plan_path),
            "citation_map_json": str(citation_map_path),
        },
        "counts": {
            "sections": len(section_index),
            "chunks": len(chunk_plan),
            "citations": len(citation_map),
        },
        "final_quality_status": (final_quality or {}).get("quality_status"),
        "rag_readiness_metrics": (final_quality or {}).get("rag_readiness_metrics"),
        "created_at": utc_now(),
    }


def build_agent_metadata_artifact(
    *,
    primary: AgentCandidateConversion,
    selected: str,
    decision: dict[str, Any],
    supporting_sources: list[dict[str, Any]],
    paths: AgentSandboxPaths,
    section_index_path: Path,
    chunk_plan_path: Path,
    citation_map_path: Path,
    quality_report: dict[str, Any],
    converter: MinerUConverter,
) -> dict[str, Any]:
    return {
        "artifact_schema_version": "agent_sandbox_metadata_v1",
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "canonical_business_code": PILOT_DISPLAY_CODE,
        "title": PILOT_TITLE,
        "internal_version": PILOT_INTERNAL_VERSION,
        "source_revision": PILOT_SOURCE_REVISION,
        "display_version": PILOT_SOURCE_REVISION,
        "artifact_stem": PILOT_ARTIFACT_STEM,
        "status": "pending_review",
        "primary_source_type": selected,
        "primary_source_path": str(primary.source_path),
        "supporting_sources": supporting_sources,
        "primary_source_decision": decision,
        "ingest_policy": "primary_source_only",
        "ragflow_ingestion": "not_run",
        "raw_converter": "mineru",
        "raw_conversion_policy": "mineru_only_no_fallback",
        "raw_markdown_path": str(primary.raw_markdown_path),
        "mineru_artifact_index_path": str(primary.mineru_artifact_index_path) if primary.mineru_artifact_index_path else None,
        "mineru_artifact_summary": quality_report.get("mineru_artifact_summary"),
        "mineru_profile": converter.profile_dict() if hasattr(converter, "profile_dict") else {},
        "artifacts": {
            "normalized_markdown": str(paths.normalized),
            "section_index_json": str(section_index_path),
            "chunk_plan_json": str(chunk_plan_path),
            "citation_map_json": str(citation_map_path),
            "quality_report_json": str(paths.quality_report),
            "review_report_json": str(paths.review_report),
        },
        "created_at": utc_now(),
    }


def upsert_agent_sandbox_record(
    root: Path,
    *,
    primary: AgentCandidateConversion,
    selected: str,
    decision: dict[str, Any],
    metadata_path: Path,
    section_index_path: Path,
    chunk_plan_path: Path,
    citation_map_path: Path,
    schema_manifest_path: Path,
    quality_report: dict[str, Any],
    review: dict[str, Any],
    converter: MinerUConverter,
    supporting_sources: list[dict[str, Any]],
) -> ManifestRecord:
    now = utc_now()
    record = ManifestRecord(
        doc_id=PILOT_DOC_ID,
        title=f"{PILOT_DISPLAY_CODE} {PILOT_SOURCE_REVISION} - {PILOT_TITLE}",
        department="technical",
        category="procedure",
        source_type="internal_procedure",
        language="vi",
        version=PILOT_INTERNAL_VERSION,
        status="pending_review",
        status_reason="Agent sandbox stopped before human approval",
        effective_from=now[:10],
        owner="Phong Ky thuat",
        approved_by=None,
        source_path=str(primary.source_path),
        normalized_path=str(root / "normalized" / "technical" / "procedure" / f"{PILOT_ARTIFACT_STEM}.md"),
        content_hash=content_hash(primary.source_path),
        access_group="technical",
        created_at=now,
        updated_at=now,
        extra={
            "display_code": PILOT_DISPLAY_CODE,
            "canonical_business_code": PILOT_DISPLAY_CODE,
            "original_name": PILOT_TITLE,
            "original_filename": primary.source_path.name,
            "internal_version": PILOT_INTERNAL_VERSION,
            "source_revision": PILOT_SOURCE_REVISION,
            "display_version": PILOT_SOURCE_REVISION,
            "primary_source_type": selected,
            "primary_source_path": str(primary.source_path),
            "supporting_sources": supporting_sources,
            "keep_original_filename": True,
            "dedupe_group": PILOT_DISPLAY_CODE,
            "ingest_policy": "primary_source_only",
            "used_for_retrieval": True,
            "artifact_stem": PILOT_ARTIFACT_STEM,
            "raw_converter": "mineru",
            "raw_conversion_policy": "mineru_only_no_fallback",
            "raw_markdown_path": str(primary.raw_markdown_path),
            "mineru_artifact_index_path": str(primary.mineru_artifact_index_path) if primary.mineru_artifact_index_path else None,
            "mineru_artifact_summary": quality_report.get("mineru_artifact_summary"),
            "mineru_profile": converter.profile_dict() if hasattr(converter, "profile_dict") else {},
            "primary_source_decision": decision,
            "metadata_json_path": str(metadata_path),
            "section_index_path": str(section_index_path),
            "chunk_plan_path": str(chunk_plan_path),
            "citation_map_path": str(citation_map_path),
            "schema_manifest_path": str(schema_manifest_path),
            "quality_report_path": str(root / "reports" / "quality_report.json"),
            "quality_status": quality_report["quality_status"],
            "quality_score": quality_report["quality_score"],
            "review_report_path": str(root / "review" / "human_review.json"),
            "review_status": review["review_status"],
            "ragflow_ingestion": "not_run",
            "smoke_chat": "not_run",
            "active_scope_id": PILOT_SCOPE_ID,
        },
    )
    ManifestStore(root).upsert(record)
    QualityDatabase(root).log_ingestion("agent_sandbox_pending_review", record.doc_id, record.version)
    return record


def write_agent_failure_reports(
    *,
    paths: AgentSandboxPaths,
    run_id: str,
    conversions: dict[str, AgentCandidateConversion],
    probe: dict[str, Any],
    reason: str,
) -> None:
    quality_report = {
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "quality_status": "blocked",
        "quality_score": 0.0,
        "reason": reason,
        "source_probe": probe,
        "candidate_conversions": {
            source_type: candidate_conversion_summary(candidate) for source_type, candidate in conversions.items()
        },
        "issues": [{"type": "mineru_conversion_blocked", "severity": "high", "text": reason}],
        "checked_at": utc_now(),
    }
    write_json(paths.quality_report, quality_report)
    write_agent_terminal_reports(
        paths=paths,
        run_id=run_id,
        selected=None,
        decision=None,
        conversions=conversions,
        quality_report=quality_report,
        review=None,
        stopped_at="mineru_convert",
    )


def write_agent_terminal_reports(
    *,
    paths: AgentSandboxPaths,
    run_id: str,
    selected: str | None,
    decision: dict[str, Any] | None,
    conversions: dict[str, AgentCandidateConversion],
    quality_report: dict[str, Any],
    review: dict[str, Any] | None,
    stopped_at: str,
) -> None:
    write_json(
        paths.reports / "run_summary.json",
        {
            "run_id": run_id,
            "doc_id": PILOT_DOC_ID,
            "display_code": PILOT_DISPLAY_CODE,
            "artifact_stem": PILOT_ARTIFACT_STEM,
            "selected_primary_source": selected,
            "primary_source_decision": decision,
            "candidate_conversions": {
                source_type: candidate_conversion_summary(candidate) for source_type, candidate in conversions.items()
            },
            "quality_status": quality_report.get("quality_status"),
            "quality_score": quality_report.get("quality_score"),
            "review_status": (review or {}).get("review_status"),
            "stopped_at": stopped_at,
            "ragflow_ingestion": "not_run",
            "smoke_chat": "not_run",
            "created_at": utc_now(),
        },
    )
    paths.run_report.write_text(
        render_agent_run_report(
            run_id=run_id,
            selected=selected,
            decision=decision,
            conversions=conversions,
            quality_report=quality_report,
            review=review,
            stopped_at=stopped_at,
        ),
        encoding="utf-8",
    )
    paths.evolution_report.write_text(
        render_agent_evolution_report(selected=selected, conversions=conversions, quality_report=quality_report),
        encoding="utf-8",
    )


def render_agent_run_report(
    *,
    run_id: str,
    selected: str | None,
    decision: dict[str, Any] | None,
    conversions: dict[str, AgentCandidateConversion],
    quality_report: dict[str, Any],
    review: dict[str, Any] | None,
    stopped_at: str,
) -> str:
    lines = [
        f"# Agent Sandbox Run - {PILOT_DISPLAY_CODE} {PILOT_SOURCE_REVISION}",
        "",
        f"- run_id: `{run_id}`",
        f"- doc_id: `{PILOT_DOC_ID}`",
        f"- artifact_stem: `{PILOT_ARTIFACT_STEM}`",
        f"- selected_primary_source: `{selected or 'none'}`",
        f"- quality_status: `{quality_report.get('quality_status')}`",
        f"- quality_score: `{quality_report.get('quality_score')}`",
        f"- final_status: `{(review or {}).get('review_status') or stopped_at}`",
        "- ragflow_ingestion: `not_run`",
        "- smoke_chat: `not_run`",
        "",
        "## Primary Source Decision",
        "",
        (decision or {}).get("reason") or "No primary source selected.",
        "",
        "## MinerU Candidate Conversions",
        "",
    ]
    for source_type, candidate in conversions.items():
        lines.extend(
            [
                f"### {source_type.upper()}",
                "",
                f"- status: `{candidate.status}`",
                f"- source: `{candidate.source_path}`",
                f"- raw_markdown: `{candidate.raw_markdown_path}`",
                f"- mineru_artifact_index: `{candidate.mineru_artifact_index_path}`",
            ]
        )
        if candidate.error:
            lines.append(f"- error: `{candidate.error}`")
        lines.append("")
    lines.extend(
        [
            "## Quality Issues",
            "",
        ]
    )
    issues = quality_report.get("issues") or []
    if not issues:
        lines.append("- None")
    else:
        for issue in issues:
            lines.append(f"- {issue.get('severity', 'unknown')}: {issue.get('type')} - {issue.get('text', '')}")
    lines.extend(
        [
            "",
            "## Output",
            "",
            "- normalized_markdown: `normalized/technical/procedure/KT-QT-002_rev04.md`",
            "- metadata_json: `indexes/KT-QT-002_rev04_metadata.json`",
            "- section_index_json: `indexes/KT-QT-002_rev04_section_index.json`",
            "- chunk_plan_json: `indexes/KT-QT-002_rev04_chunk_plan.json`",
            "- citation_map_json: `indexes/KT-QT-002_rev04_citation_map.json`",
            "- quality_report_json: `reports/quality_report.json`",
            "",
        ]
    )
    return "\n".join(lines)


def render_agent_evolution_report(
    *,
    selected: str | None,
    conversions: dict[str, AgentCandidateConversion],
    quality_report: dict[str, Any],
) -> str:
    issues = quality_report.get("issues") or []
    lines = [
        f"# Skill Evolution Notes - {PILOT_DISPLAY_CODE} {PILOT_SOURCE_REVISION}",
        "",
        f"- selected_primary_source: `{selected or 'none'}`",
        f"- quality_status: `{quality_report.get('quality_status')}`",
        f"- remaining_issue_count: `{len(issues)}`",
        "",
        "## Lessons",
        "",
    ]
    lessons = []
    if selected:
        lessons.append("Keep primary-source-only ingestion; supporting PDF/XLSX must remain display/supporting evidence.")
    if any(candidate.mineru_artifact_index_path for candidate in conversions.values()):
        lessons.append("MinerU sidecars must be preserved because citation anchors can reuse content blocks, bbox, images, and JSON source names.")
    if issues:
        lessons.append("Repeated high-severity QA issues should become explicit repair rules before batch processing.")
    else:
        lessons.append("No blocking QA issue remained after one repair pass; keep the current audit-repair-index sequence for this document family.")
    for lesson in lessons:
        lines.append(f"- {lesson}")
    lines.extend(
        [
            "",
            "## Rule Candidates",
            "",
            "- Block RAG-ready promotion if selected source lacks `mineru_artifact_index.json`.",
            "- Keep citation locators source-type-specific: XLSX sheet/row/columns, PDF page/bbox.",
            "- Do not run RAGFlow ingestion or chat smoke before human review approval in this phase.",
            "",
        ]
    )
    return "\n".join(lines)


def agent_sandbox_result(
    paths: AgentSandboxPaths,
    run_id: str,
    selected: str | None,
    quality_report: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    return {
        "ok": status in {"pending_review", "active"},
        "run_id": run_id,
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "display_version": PILOT_SOURCE_REVISION,
        "artifact_stem": PILOT_ARTIFACT_STEM,
        "status": status,
        "primary_source": selected,
        "sandbox_path": str(paths.sandbox),
        "workflow_handoffs_path": str(paths.workflow_handoffs),
        "normalized_path": str(paths.normalized),
        "source_probe_report_path": str(paths.source_probe_report),
        "quality_report_path": str(paths.quality_report),
        "run_report_path": str(paths.run_report),
        "evolution_report_path": str(paths.evolution_report),
        "quality_status": quality_report.get("quality_status"),
        "quality_score": quality_report.get("quality_score"),
        "ragflow_ingestion": "not_run",
        "smoke_chat": "not_run",
    }


def resolve_pilot_sources(root: Path, *, xlsx_path: Path | None, pdf_path: Path | None) -> dict[str, Path]:
    xlsx = resolve_source_path(root, xlsx_path, ".xlsx")
    pdf = resolve_source_path(root, pdf_path, ".pdf")
    if not xlsx or not pdf:
        missing = []
        if not xlsx:
            missing.append("XLSX")
        if not pdf:
            missing.append("PDF")
        raise PilotError(
            "Missing pilot source(s): "
            + ", ".join(missing)
            + ". Place the original PD-TECH-A-02 Rev 04 files under root_source or pass explicit paths."
        )
    return {"xlsx": xlsx.resolve(), "pdf": pdf.resolve()}


def resolve_source_path(root: Path, explicit_path: Path | None, suffix: str) -> Path | None:
    if explicit_path:
        path = explicit_path if explicit_path.is_absolute() else root / explicit_path
        if not path.exists():
            raise PilotError(f"Source file does not exist: {path}")
        return path
    source_root = root / "root_source"
    if not source_root.exists():
        return None
    candidates = [
        path
        for path in source_root.rglob(f"*{suffix}")
        if PILOT_DISPLAY_CODE.replace("-", "").lower() in re.sub(r"[^A-Za-z0-9]+", "", path.name).lower()
        or "bao duong" in ascii_key(path.name)
    ]
    return sorted(candidates, key=lambda path: len(str(path)))[0] if candidates else None


def build_source_probe_report(xlsx_path: Path, pdf_path: Path) -> dict[str, Any]:
    xlsx_probe = probe_xlsx(xlsx_path)
    pdf_probe = probe_pdf(pdf_path)
    recommended = recommended_primary_source(xlsx_probe, pdf_probe)
    return {
        "doc_code": PILOT_DISPLAY_CODE,
        "source_revision": PILOT_SOURCE_REVISION,
        "xlsx_probe": xlsx_probe,
        "pdf_probe": pdf_probe,
        "recommended_primary_source": recommended,
        "reason": primary_decision_reason(
            {"xlsx_probe": xlsx_probe, "pdf_probe": pdf_probe},
            recommended,
            "auto",
        ),
    }


def probe_xlsx(path: Path) -> dict[str, Any]:
    issues: list[str] = []
    try:
        from openpyxl import load_workbook
    except Exception as exc:  # pragma: no cover - dependency guard
        return {
            "parse_score": 0.0,
            "sheet_count": 0,
            "table_quality": "bad",
            "merged_cells_risk": "high",
            "shape_text_risk": "high",
            "step_extraction_quality": "bad",
            "issues": [f"openpyxl_unavailable: {exc}"],
        }

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
    text = ascii_key(" ".join(text_parts))
    table_quality = "good" if non_empty_rows >= 8 and non_empty_cells >= 20 else "medium" if non_empty_rows >= 3 else "bad"
    merged_risk = "high" if merged_ranges >= 20 else "medium" if merged_ranges else "low"
    shape_risk = "medium" if drawing_count else "low"
    step_hits = sum(1 for term in ["quy trinh", "buoc", "noi dung", "trach nhiem", "ho so", "bieu mau"] if term in text)
    step_quality = "good" if step_hits >= 3 else "medium" if step_hits else "bad"
    score = 0.25
    score += {"good": 0.30, "medium": 0.15, "bad": 0.0}[table_quality]
    score += {"good": 0.30, "medium": 0.15, "bad": 0.0}[step_quality]
    score -= {"low": 0.0, "medium": 0.08, "high": 0.18}[merged_risk]
    score -= {"low": 0.0, "medium": 0.05, "high": 0.12}[shape_risk]
    if PILOT_DISPLAY_CODE.lower() not in path.name.lower() and "pd tech a 02" not in text:
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


def probe_pdf(path: Path) -> dict[str, Any]:
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
    if PILOT_DISPLAY_CODE.lower() not in path.name.lower() and "pd tech a 02" not in ascii_key(text):
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


def select_primary_source(probe: dict[str, Any], primary_source: str) -> str:
    if primary_source not in {"auto", "xlsx", "pdf"}:
        raise PilotError("primary_source must be auto, xlsx, or pdf")
    if primary_source in {"xlsx", "pdf"}:
        return primary_source
    return str(
        probe.get("recommended_primary_source")
        or recommended_primary_source(probe.get("xlsx_probe") or {}, probe.get("pdf_probe") or {})
    )


def recommended_primary_source(xlsx_probe: dict[str, Any], pdf_probe: dict[str, Any]) -> str:
    xlsx_score = float(xlsx_probe.get("parse_score") or 0)
    pdf_score = float(pdf_probe.get("parse_score") or 0)
    if xlsx_probe.get("step_extraction_quality") == "good" and xlsx_score >= pdf_score - 0.10:
        return "xlsx"
    return "xlsx" if xlsx_score >= pdf_score else "pdf"


def primary_decision_reason(probe: dict[str, Any], selected: str, requested: str) -> str:
    if requested in {"xlsx", "pdf"}:
        return f"{requested.upper()} selected by explicit operator override."
    xlsx_score = float((probe.get("xlsx_probe") or {}).get("parse_score") or 0)
    pdf_score = float((probe.get("pdf_probe") or {}).get("parse_score") or 0)
    if selected == "xlsx":
        return f"XLSX selected because its parse score ({xlsx_score}) is >= PDF score ({pdf_score}) and table/step extraction is preferred."
    return f"PDF selected because its parse score ({pdf_score}) is higher than XLSX score ({xlsx_score})."


def build_supporting_sources(sources: dict[str, Path], selected: str) -> list[dict[str, Any]]:
    supporting = []
    for source_type, path in sources.items():
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


def write_agent_normalized_outputs(
    *,
    normalized_text: str,
    section_index: list[dict[str, Any]],
    citation_map: list[dict[str, Any]],
    draft_path: Path,
    normalized_path: Path,
    section_index_path: Path,
    chunk_plan_path: Path,
    citation_map_path: Path,
) -> None:
    draft_path.write_text(normalized_text, encoding="utf-8")
    normalized_path.write_text(normalized_text, encoding="utf-8")
    write_json(section_index_path, section_index)
    write_json(chunk_plan_path, build_chunk_plan(citation_map))
    write_json(citation_map_path, citation_map)


def normalize_primary_source(
    primary_path: Path,
    source_type: str,
    raw_markdown_path: Path | None = None,
    mineru_artifact_index_path: Path | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if raw_markdown_path is not None:
        return normalize_mineru_raw(
            raw_markdown_path,
            primary_path,
            source_type,
            mineru_artifact_index_path=mineru_artifact_index_path,
        )
    if source_type == "xlsx":
        return normalize_xlsx(primary_path)
    return normalize_pdf(primary_path)


def normalize_mineru_raw(
    raw_markdown_path: Path,
    primary_path: Path,
    source_type: str,
    *,
    mineru_artifact_index_path: Path | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    raw_text = raw_markdown_path.read_text(encoding="utf-8", errors="ignore")
    raw_text = preclean_mineru_markdown_text(raw_text)
    if len(raw_text.strip()) < 20:
        raise PilotError(f"MinerU raw Markdown is empty or too short: {raw_markdown_path}")
    mineru_blocks = mineru_content_blocks(mineru_artifact_index_path)

    lines = frontmatter_lines(source_type, primary_path)
    section_index: list[dict[str, Any]] = []
    citation_map: list[dict[str, Any]] = []
    active_section: dict[str, Any] | None = None
    body_lines: list[str] = []
    anchor_counter = 0
    current_sheet: str | None = None
    current_page: int | None = None

    for raw_line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or raw_line_is_noise(line):
            continue

        heading_text = markdown_heading_text(line)
        if heading_text:
            sheet_name = sheet_title_from_heading(heading_text)
            if sheet_name:
                current_sheet = sheet_name
                continue
            page_number = page_number_from_heading(heading_text)
            if page_number:
                current_page = page_number
            canonical_heading = canonical_heading_for_text(heading_text)
            if canonical_heading and not is_document_title_heading(heading_text):
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        source_type,
                        mineru_blocks=mineru_blocks,
                    )
                    body_lines = []
                active_section = raw_section(
                    canonical_heading,
                    raw_line_number,
                    source_type,
                    current_sheet=current_sheet,
                    current_page=current_page,
                )
                continue
            if is_document_title_heading(heading_text):
                continue

        values = markdown_table_values(line)
        normalized_line = ""
        if values is not None:
            if not values:
                continue
            canonical_heading = canonical_heading_for_text(" | ".join(values))
            if canonical_heading and len(values) <= 2:
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        source_type,
                        mineru_blocks=mineru_blocks,
                    )
                    body_lines = []
                active_section = raw_section(
                    canonical_heading,
                    raw_line_number,
                    source_type,
                    current_sheet=current_sheet,
                    current_page=current_page,
                    column_count=len(values),
                )
                continue
            normalized_line = markdown_line_for_values(values)
            column_count = len(values)
        else:
            canonical_heading = canonical_heading_for_text(line)
            if canonical_heading and len(line) <= 80:
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        source_type,
                        mineru_blocks=mineru_blocks,
                    )
                    body_lines = []
                active_section = raw_section(
                    canonical_heading,
                    raw_line_number,
                    source_type,
                    current_sheet=current_sheet,
                    current_page=current_page,
                )
                continue
            normalized_line = clean_cell(line)
            column_count = 1

        if not active_section:
            active_section = raw_section(
                PILOT_TITLE,
                raw_line_number,
                source_type,
                current_sheet=current_sheet,
                current_page=current_page,
                column_count=column_count,
            )
        active_section["raw_line_end"] = raw_line_number
        active_section["columns"] = columns_for_values(max(column_count, len(active_section.get("columns", []))))
        if current_page and source_type == "pdf":
            active_section["page_end"] = current_page
        body_lines.append(normalized_line)

    if active_section:
        finalize_section(
            active_section,
            body_lines,
            lines,
            section_index,
            citation_map,
            anchor_counter,
            source_type,
            mineru_blocks=mineru_blocks,
        )
    return "\n".join(lines).strip() + "\n", section_index, citation_map


def raw_section(
    title: str,
    raw_line_number: int,
    source_type: str,
    *,
    current_sheet: str | None = None,
    current_page: int | None = None,
    column_count: int = 1,
) -> dict[str, Any]:
    section: dict[str, Any] = {
        "title": title,
        "raw_line_start": raw_line_number,
        "raw_line_end": raw_line_number,
        "columns": columns_for_values(column_count),
    }
    if source_type == "xlsx":
        section["sheet"] = current_sheet or "MinerU raw"
    if source_type == "pdf":
        section["page_start"] = current_page or 1
        section["page_end"] = current_page or 1
    return section


def preclean_mineru_markdown_text(text: str) -> str:
    text = convert_html_tables_to_markdown(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = "\n".join(clean_cell(line) for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def convert_html_tables_to_markdown(text: str) -> str:
    table_pattern = re.compile(r"<table\b[^>]*>.*?</table>", flags=re.IGNORECASE | re.DOTALL)
    return table_pattern.sub(lambda match: "\n" + markdown_from_html_table(match.group(0)) + "\n", text)


def markdown_from_html_table(table_html: str) -> str:
    rows = html_table_rows(table_html)
    lines: list[str] = []
    for row in rows:
        values = [value for value in row if value]
        if not values:
            continue
        if len(values) == 1:
            lines.append(values[0])
        else:
            lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def html_table_rows(table_html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_match in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL):
        row_html = row_match.group(1)
        cells: list[str] = []
        for cell_match in re.finditer(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL):
            cell_text = re.sub(r"<br\s*/?>", "\n", cell_match.group(1), flags=re.IGNORECASE)
            cell_text = re.sub(r"<[^>]+>", " ", cell_text)
            cells.append(clean_cell(html.unescape(cell_text)))
        rows.append(cells)
    return rows


def markdown_heading_text(line: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
    return match.group(1).strip() if match else None


def sheet_title_from_heading(heading: str) -> str | None:
    match = re.match(r"sheet\s*:\s*(.+)$", heading, flags=re.IGNORECASE)
    return clean_cell(match.group(1)) if match else None


def page_number_from_heading(heading: str) -> int | None:
    match = re.match(r"(?:page|trang)\s+(\d+)", ascii_key(heading), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def is_document_title_heading(heading: str) -> bool:
    normalized = ascii_key(heading)
    return PILOT_DISPLAY_CODE.lower().replace("-", " ") in normalized or "quy trinh bao duong" in normalized


def markdown_table_values(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or "|" not in stripped[1:]:
        return None
    cells = [clean_cell(cell) for cell in stripped.strip("|").split("|")]
    if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells if cell):
        return []
    return [cell for cell in cells if cell]


def raw_line_is_noise(line: str) -> bool:
    normalized = ascii_key(line)
    return any(marker in normalized for marker in RAW_PROMPT_DEBUG_MARKERS)


def count_raw_prompt_debug_markers(text: str) -> int:
    normalized = ascii_key(text)
    return sum(1 for marker in RAW_PROMPT_DEBUG_MARKERS if marker in normalized)


def normalize_xlsx(path: Path) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    from openpyxl import load_workbook

    workbook = load_workbook(filename=path, data_only=True, read_only=True)
    lines = frontmatter_lines("xlsx", path)
    section_index: list[dict[str, Any]] = []
    citation_map: list[dict[str, Any]] = []
    active_section: dict[str, Any] | None = None
    body_lines: list[str] = []
    anchor_counter = 0

    for sheet in workbook.worksheets:
        for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = [clean_cell(value) for value in row]
            values = [value for value in values if value]
            if not values:
                continue
            joined = " | ".join(values)
            heading = canonical_heading_for_text(joined)
            if heading:
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        "xlsx",
                    )
                    body_lines = []
                active_section = {
                    "title": heading,
                    "sheet": sheet.title,
                    "row_start": row_number,
                    "row_end": row_number,
                    "columns": columns_for_values(len(values)),
                }
                continue
            if not active_section:
                active_section = {
                    "title": PILOT_TITLE,
                    "sheet": sheet.title,
                    "row_start": row_number,
                    "row_end": row_number,
                    "columns": columns_for_values(len(values)),
                }
            active_section["row_end"] = row_number
            active_section["columns"] = columns_for_values(max(len(values), len(active_section.get("columns", []))))
            body_lines.append(markdown_line_for_values(values))

    if active_section:
        finalize_section(active_section, body_lines, lines, section_index, citation_map, anchor_counter, "xlsx")
    workbook.close()
    return "\n".join(lines).strip() + "\n", section_index, citation_map


def normalize_source_assisted_xlsx(
    path: Path,
    *,
    mineru_artifact_index_path: Path | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    from openpyxl import load_workbook

    workbook = load_workbook(filename=path, data_only=True, read_only=True)
    if "QT" not in workbook.sheetnames:
        workbook.close()
        return normalize_xlsx(path)

    sheet = workbook["QT"]
    if not sheet_cell_lines(sheet, 57, 1) or not sheet_cell_lines(sheet, 77, 1):
        workbook.close()
        return normalize_xlsx(path)

    mineru_blocks = mineru_content_blocks(mineru_artifact_index_path)
    lines = frontmatter_lines("xlsx", path)
    section_index: list[dict[str, Any]] = []
    citation_map: list[dict[str, Any]] = []
    anchor_counter = 0

    def add_section(
        title: str,
        body: list[str],
        row_start: int,
        row_end: int,
        columns: list[str],
        *,
        source_sheet: str | None = None,
    ) -> None:
        nonlocal anchor_counter
        body = [line for line in body if line.strip()]
        if not body:
            return
        anchor_counter = finalize_section(
            {
                "title": title,
                "sheet": source_sheet or sheet.title,
                "row_start": row_start,
                "row_end": row_end,
                "columns": columns,
            },
            body,
            lines,
            section_index,
            citation_map,
            anchor_counter,
            "xlsx",
            mineru_blocks=mineru_blocks,
        )

    add_section(
        "Thông tin tài liệu",
        [
            f"- Mã tài liệu: {PILOT_DISPLAY_CODE}",
            f"- Phiên bản hiển thị: {PILOT_SOURCE_REVISION}",
            f"- Tên tài liệu: {PILOT_TITLE}",
            f"- Nguồn chính: XLSX `{path.name}`",
        ],
        1,
        15,
        ["A", "E", "J"],
    )
    revision_rows = []
    for row_number in (7, 9, 11, 13, 15):
        revision = first_cell_text(sheet, row_number, [1])
        date = first_cell_text(sheet, row_number, [5])
        content = first_cell_text(sheet, row_number, [10])
        if revision or content:
            revision_rows.append(f"| {revision} | {date} | {content} |")
    if revision_rows:
        add_section(
            "Lịch sử chỉnh sửa",
            ["| Rev | Ngày | Nội dung |", "| --- | --- | --- |", *revision_rows],
            5,
            15,
            ["A", "E", "J"],
        )
    add_section("1. Mục đích", bullet_lines_from_rows(sheet, [58, 59, 60]), 57, 60, ["A"])
    add_section("2. Phạm vi áp dụng", bullet_lines_from_rows(sheet, [62, 63]), 61, 63, ["A"])
    add_section("3. Tài liệu viện dẫn, tham khảo", bullet_lines_from_cell(sheet, 64, 1, skip_first=True), 64, 64, ["A"])
    add_section("4. Định nghĩa, từ ngữ viết tắt", bullet_lines_from_cell(sheet, 66, 1), 65, 66, ["A"])
    add_section("5. Trách nhiệm", bullet_lines_from_cell(sheet, 69, 1), 68, 69, ["A"])

    add_section(
        "6. Quy trình thực hiện",
        [
            "- Các bước dưới đây được chuẩn hóa từ bảng quy trình tại sheet `QT`.",
            "- Locator chính dùng sheet/row/column của workbook; MinerU sidecars được giữ trong citation khi match được block.",
        ],
        77,
        84,
        ["A", "H", "K", "L", "M", "P", "Y", "AA", "AD", "AE"],
    )
    for row_number in (85, 88, 91, 94, 97, 100, 110, 111, 112, 113, 118, 123):
        step_body = procedure_step_body(sheet, row_number)
        if not step_body:
            continue
        step_number = first_cell_text(sheet, row_number, [1])
        result = first_cell_text(sheet, row_number, [25])
        detail_lines_for_title = sheet_cell_lines(sheet, row_number, 30)
        detail_title = detail_lines_for_title[0] if detail_lines_for_title else ""
        title = f"Bước {step_number}. {result or short_heading(detail_title) or 'Nội dung thực hiện'}"
        add_section(
            title,
            step_body,
            row_number,
            row_number,
            ["A", "H", "K", "L", "M", "P", "Y", "AA", "AD", "AE"],
        )

    add_section(
        "7. Hồ sơ / biểu mẫu liên quan",
        form_lines_from_rows(sheet, [130, 131, 132]),
        129,
        132,
        ["A", "E"],
    )
    note_lines = bullet_lines_from_rows(sheet, [134])
    if note_lines:
        add_section("Ghi chú áp dụng", note_lines, 134, 134, ["A"])
    for form_sheet_name in ("PD-TECH-A-02 BM-05", "PD-TECH-A-02 BM-06", "PD-TECH-A-01 BM-05"):
        if form_sheet_name in workbook.sheetnames:
            form_sheet = workbook[form_sheet_name]
            add_section(
                f"Biểu mẫu: {form_sheet_name}",
                form_sheet_preview_lines(form_sheet),
                1,
                min(form_sheet.max_row or 1, 12),
                columns_for_values(min(form_sheet.max_column or 1, 8)),
                source_sheet=form_sheet.title,
            )

    workbook.close()
    return "\n".join(lines).strip() + "\n", section_index, citation_map


def short_heading(text: str, *, limit: int = 80) -> str:
    text = clean_cell(text).lstrip("-+* ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def sheet_cell_lines(sheet: Any, row: int, column: int) -> list[str]:
    value = sheet.cell(row=row, column=column).value
    if value is None:
        return []
    return [clean_cell(line) for line in str(value).replace("\r", "\n").split("\n") if clean_cell(line)]


def first_cell_text(sheet: Any, row: int, columns: list[int]) -> str:
    for column in columns:
        lines = sheet_cell_lines(sheet, row, column)
        if lines:
            return " ".join(lines)
    return ""


def bullet_lines_from_rows(sheet: Any, rows: list[int]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        for value in sheet_cell_lines(sheet, row, 1):
            lines.append(value if value.startswith(("-", "+", "*")) else f"- {value}")
    return lines


def bullet_lines_from_cell(sheet: Any, row: int, column: int, *, skip_first: bool = False) -> list[str]:
    values = sheet_cell_lines(sheet, row, column)
    if skip_first and values:
        values = values[1:]
    return [value if value.startswith(("-", "+", "*")) else f"- {value}" for value in values]


def procedure_step_body(sheet: Any, row: int) -> list[str]:
    result = first_cell_text(sheet, row, [25])
    frequency = first_cell_text(sheet, row, [27])
    detail_lines = sheet_cell_lines(sheet, row, 30)
    form = first_cell_text(sheet, row, [31])
    if not (result or frequency or detail_lines or form):
        return []
    raci = raci_line(sheet, row)
    lines = []
    if raci:
        lines.append(f"- RACI: {raci}")
    if result:
        lines.append(f"- Kết quả: {result}")
    if frequency:
        lines.append(f"- Tần suất: {frequency}")
    if detail_lines:
        lines.append("- Nội dung chi tiết:")
        lines.extend(f"  - {line.lstrip('-+* ').strip()}" for line in detail_lines if line.strip())
    if form:
        lines.append(f"- Biểu mẫu: {form}")
    return lines


def raci_line(sheet: Any, row: int) -> str:
    roles = [(8, "Kỹ thuật"), (11, "DVKH"), (12, "TSC"), (13, "CSKH"), (16, "Kinh doanh")]
    values = []
    for column, label in roles:
        role = first_cell_text(sheet, row, [column])
        if role:
            values.append(f"{label}={role}")
    return "; ".join(values)


def form_lines_from_rows(sheet: Any, rows: list[int]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        code = first_cell_text(sheet, row, [1])
        title = first_cell_text(sheet, row, [5]).lstrip(":").strip()
        if code or title:
            lines.append(f"- {code} - {title}".strip())
    return lines


def form_sheet_preview_lines(sheet: Any) -> list[str]:
    rows: list[str] = []
    for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row or 1, 12), values_only=True):
        values = [clean_cell(value) for value in row]
        values = [value for value in values if value]
        if values:
            rows.append("- " + " | ".join(values[:8]))
    return rows[:10] or ["- Biểu mẫu có trong workbook, cần human review nếu cần trích đầy đủ."]


def normalize_pdf(path: Path) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    lines = frontmatter_lines("pdf", path)
    section_index: list[dict[str, Any]] = []
    citation_map: list[dict[str, Any]] = []
    anchor_counter = 0
    for page_index, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if not page_text:
            continue
        heading = canonical_heading_for_text(page_text.splitlines()[0]) or f"Trang {page_index}"
        lines.extend([f"## {heading}", ""])
        start_line = len(lines) + 1
        page_lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        lines.extend(page_lines)
        lines.append("")
        anchor_counter += 1
        anchor_id = f"KT-QT-002-S{anchor_counter:02d}-C01"
        section_index.append(
            {
                "anchor_id": anchor_id,
                "title": heading,
                "line_start": start_line,
                "line_end": len(lines) - 1,
            }
        )
        citation_map.append(
            {
                "anchor_id": anchor_id,
                "source_type": "pdf",
                "section_title": heading,
                "source_locator": {"page_start": page_index, "page_end": page_index},
                "display_locator": f"Trang {page_index}",
                "normalized_path": f"normalized/technical/procedure/{PILOT_ARTIFACT_STEM}.md",
            }
        )
    return "\n".join(lines).strip() + "\n", section_index, citation_map


def frontmatter_lines(source_type: str, source_path: Path) -> list[str]:
    return [
        "---",
        f"doc_id: {PILOT_DOC_ID}",
        f"display_code: {PILOT_DISPLAY_CODE}",
        f"canonical_business_code: {PILOT_DISPLAY_CODE}",
        f"title: {PILOT_TITLE}",
        f"internal_version: {PILOT_INTERNAL_VERSION}",
        f"source_revision: {PILOT_SOURCE_REVISION}",
        f"display_version: {PILOT_SOURCE_REVISION}",
        f"primary_source_type: {source_type}",
        f"primary_source_file: {source_path.name}",
        "quality_status: passed",
        "---",
        "",
        f"# {PILOT_TITLE}",
        "",
    ]


def mineru_content_blocks(mineru_artifact_index_path: Path | None) -> list[dict[str, Any]]:
    if not mineru_artifact_index_path or not mineru_artifact_index_path.exists():
        return []
    try:
        artifact_index = json.loads(mineru_artifact_index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    for content_artifact in mineru_rich_json_artifacts(artifact_index):
        path_value = content_artifact.get("path")
        if not path_value:
            continue
        content_path = Path(str(path_value))
        if not content_path.exists():
            continue
        try:
            payload = json.loads(content_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        blocks = flatten_mineru_content_payload(
            payload,
            source_json=content_artifact.get("type") or "content_list",
            artifact_path=content_path,
        )
        if blocks:
            return blocks
    return []


def preferred_mineru_content_artifact(artifact_index: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = mineru_rich_json_artifacts(artifact_index)
    return artifacts[0] if artifacts else None


def mineru_rich_json_artifacts(artifact_index: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = artifact_index.get("artifacts") or []
    if not isinstance(artifacts, list):
        return []
    ordered: list[dict[str, Any]] = []
    for artifact_type in ("content_list_v2", "content_list", "model_json", "middle_json"):
        for artifact in artifacts:
            if isinstance(artifact, dict) and artifact.get("type") == artifact_type:
                ordered.append(artifact)
    return ordered


def flatten_mineru_content_payload(
    payload: Any,
    *,
    source_json: str,
    artifact_path: Path,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if isinstance(payload, list) and payload and all(isinstance(item, list) for item in payload):
        for page_index, page_blocks in enumerate(payload):
            for block in page_blocks:
                append_mineru_block(blocks, block, page_index=page_index, source_json=source_json, artifact_path=artifact_path)
    elif isinstance(payload, list):
        for block in payload:
            append_mineru_block(blocks, block, page_index=None, source_json=source_json, artifact_path=artifact_path)
    return blocks


def append_mineru_block(
    blocks: list[dict[str, Any]],
    block: Any,
    *,
    page_index: int | None,
    source_json: str,
    artifact_path: Path,
) -> None:
    if not isinstance(block, dict):
        return
    block_type = str(block.get("type") or "unknown")
    page_idx = block.get("page_idx")
    if not isinstance(page_idx, int):
        page_idx = page_index
    block_id = str(block.get("id") or f"mineru-{len(blocks) + 1:04d}")
    image_path = mineru_block_image_path(block)
    image_ref = None
    if image_path:
        image_ref = str((artifact_path.parent.parent / image_path).resolve()) if not Path(image_path).is_absolute() else image_path
    blocks.append(
        {
            "block_id": block_id,
            "content_type": block_type,
            "page_idx": page_idx,
            "bbox": block.get("bbox"),
            "text": mineru_block_text(block),
            "image_ref": image_ref,
            "source_json": source_json,
        }
    )


def mineru_block_text(block: Any) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("text", "table_body", "content"):
                item = value.get(key)
                if isinstance(item, str):
                    parts.append(item)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(block)
    return clean_cell(" ".join(parts))


def mineru_block_image_path(block: dict[str, Any]) -> str | None:
    for key in ("img_path", "image_path"):
        value = block.get(key)
        if isinstance(value, str) and value:
            return value
    content = block.get("content")
    if isinstance(content, dict):
        image_source = content.get("image_source")
        if isinstance(image_source, dict):
            value = image_source.get("path")
            if isinstance(value, str) and value:
                return value
    return None


def match_mineru_blocks_for_section(body_lines: list[str], mineru_blocks: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not mineru_blocks:
        return None
    section_tokens = set(re.findall(r"[a-z0-9]{3,}", ascii_key(" ".join(body_lines))))
    if not section_tokens:
        return None
    scored: list[tuple[int, dict[str, Any]]] = []
    for block in mineru_blocks:
        block_tokens = set(re.findall(r"[a-z0-9]{3,}", ascii_key(block.get("text") or "")))
        overlap = len(section_tokens & block_tokens)
        if overlap:
            scored.append((overlap, block))
    if not scored:
        return None
    selected = [block for _, block in sorted(scored, key=lambda item: item[0], reverse=True)[:6]]
    pages = sorted({int(block["page_idx"]) + 1 for block in selected if isinstance(block.get("page_idx"), int)})
    content_types = sorted({str(block.get("content_type") or "unknown") for block in selected})
    image_refs = [str(block["image_ref"]) for block in selected if block.get("image_ref")]
    bboxes = [block.get("bbox") for block in selected if block.get("bbox")]
    return {
        "block_ids": [str(block["block_id"]) for block in selected],
        "content_types": content_types,
        "page_start": pages[0] if pages else None,
        "page_end": pages[-1] if pages else None,
        "bbox": bboxes[0] if bboxes else None,
        "image_refs": image_refs,
        "source_json": selected[0].get("source_json"),
    }


def finalize_section(
    section: dict[str, Any],
    body_lines: list[str],
    lines: list[str],
    section_index: list[dict[str, Any]],
    citation_map: list[dict[str, Any]],
    anchor_counter: int,
    source_type: str,
    *,
    mineru_blocks: list[dict[str, Any]] | None = None,
) -> int:
    if not body_lines:
        return anchor_counter
    anchor_counter += 1
    anchor_id = f"KT-QT-002-S{anchor_counter:02d}-C01"
    lines.extend([f"## {section['title']}", ""])
    start_line = len(lines) + 1
    lines.extend(body_lines)
    lines.append("")
    section_index.append(
        {
            "anchor_id": anchor_id,
            "title": section["title"],
            "line_start": start_line,
            "line_end": len(lines) - 1,
        }
    )
    if "raw_line_start" in section:
        locator = {
            "raw_markdown_line_start": section["raw_line_start"],
            "raw_markdown_line_end": section["raw_line_end"],
        }
        if source_type == "xlsx":
            locator.update(
                {
                    "sheet": section.get("sheet") or "MinerU raw",
                    "row_start": section["raw_line_start"],
                    "row_end": section["raw_line_end"],
                    "row_basis": "mineru_raw_line",
                    "columns": section.get("columns") or ["raw"],
                }
            )
            display_locator = (
                f"MinerU raw từ XLSX"
                f"{' - Sheet ' + str(section.get('sheet')) if section.get('sheet') else ''}, "
                f"dòng {section['raw_line_start']}-{section['raw_line_end']}"
            )
        else:
            locator.update(
                {
                    "page_start": section.get("page_start", 1),
                    "page_end": section.get("page_end", section.get("page_start", 1)),
                }
            )
            display_locator = (
                f"MinerU raw từ PDF, dòng {section['raw_line_start']}-{section['raw_line_end']}; "
                f"trang {locator['page_start']}-{locator['page_end']}"
            )
    elif source_type == "xlsx":
        locator = {
            "sheet": section["sheet"],
            "row_start": section["row_start"],
            "row_end": section["row_end"],
            "columns": section["columns"],
        }
        display_locator = f"Sheet {section['sheet']}, dòng {section['row_start']}-{section['row_end']}"
    else:
        locator = {"page_start": section["page_start"], "page_end": section["page_end"]}
        display_locator = f"Trang {section['page_start']}-{section['page_end']}"
    mineru_match = match_mineru_blocks_for_section(body_lines, mineru_blocks)
    if mineru_match:
        locator["mineru_block_ids"] = mineru_match["block_ids"]
        locator["content_types"] = mineru_match["content_types"]
        if mineru_match.get("bbox"):
            locator["bbox"] = mineru_match["bbox"]
        if source_type == "pdf" and mineru_match.get("page_start"):
            locator["page_start"] = mineru_match["page_start"]
            locator["page_end"] = mineru_match["page_end"] or mineru_match["page_start"]
            display_locator = f"Trang {locator['page_start']}-{locator['page_end']}"
    citation_map.append(
        {
            "anchor_id": anchor_id,
            "source_type": source_type,
            "section_title": section["title"],
            "source_locator": locator,
            "display_locator": display_locator,
            "normalized_path": f"normalized/technical/procedure/{PILOT_ARTIFACT_STEM}.md",
            "mineru_refs": mineru_match,
            "source_json": mineru_match.get("source_json") if mineru_match else None,
            "image_refs": mineru_match.get("image_refs") if mineru_match else [],
        }
    )
    return anchor_counter


def verify_normalized_markdown(
    markdown_path: Path,
    *,
    citation_map_path: Path,
    primary_source_type: str,
    raw_markdown_path: Path | None = None,
    raw_converter: str | None = None,
    mineru_artifact_index_path: Path | None = None,
    strict_rag_readiness: bool = False,
) -> dict[str, Any]:
    text = markdown_path.read_text(encoding="utf-8", errors="ignore")
    citation_map = json.loads(citation_map_path.read_text(encoding="utf-8")) if citation_map_path.exists() else []
    issues: list[dict[str, Any]] = []
    raw_text = ""
    raw_non_empty: bool | None = None
    raw_prompt_debug_count = 0
    raw_synthetic_heading_count = 0
    mineru_artifact_summary: dict[str, Any] | None = None
    if mineru_artifact_index_path is not None:
        if not mineru_artifact_index_path.exists():
            issues.append(
                {
                    "type": "missing_mineru_artifact_index",
                    "severity": "high",
                    "text": str(mineru_artifact_index_path),
                }
            )
        else:
            try:
                artifact_index = json.loads(mineru_artifact_index_path.read_text(encoding="utf-8"))
                mineru_artifact_summary = artifact_index.get("summary") or {}
                if not (
                    mineru_artifact_summary.get("has_content_list")
                    or mineru_artifact_summary.get("has_content_list_v2")
                    or mineru_artifact_summary.get("has_middle_json")
                ):
                    issues.append(
                        {
                            "type": "mineru_rich_metadata_missing",
                            "severity": "high",
                            "text": str(mineru_artifact_index_path),
                        }
                    )
            except Exception as exc:
                issues.append(
                    {
                        "type": "invalid_mineru_artifact_index",
                        "severity": "high",
                        "text": str(exc),
                    }
                )
    if raw_markdown_path is not None:
        if not raw_markdown_path.exists():
            raw_non_empty = False
            issues.append(
                {
                    "type": "missing_mineru_raw_markdown",
                    "severity": "high",
                    "text": str(raw_markdown_path),
                }
            )
        else:
            raw_text = raw_markdown_path.read_text(encoding="utf-8", errors="ignore")
            raw_non_empty = len(raw_text.strip()) >= 20
            if not raw_non_empty:
                issues.append(
                    {
                        "type": "empty_mineru_raw_markdown",
                        "severity": "high",
                        "text": str(raw_markdown_path),
                    }
                )
            raw_prompt_debug_count = count_raw_prompt_debug_markers(raw_text)
            if raw_prompt_debug_count:
                issues.append(
                    {
                        "type": "raw_prompt_debug_or_status_leak",
                        "severity": "high",
                        "text": str(raw_prompt_debug_count),
                    }
                )
            for heading in markdown_headings(raw_text):
                if ascii_key(heading) in SYNTHETIC_HEADINGS:
                    raw_synthetic_heading_count += 1
                    issues.append(
                        {
                            "type": "synthetic_heading_not_in_source",
                            "severity": "high",
                            "text": heading,
                            "location": "raw_markdown",
                            "action": "remove_or_move_to_internal_metadata",
                        }
                    )
    for heading in markdown_headings(text):
        if ascii_key(heading) in SYNTHETIC_HEADINGS:
            issues.append(
                {
                    "type": "synthetic_heading_not_in_source",
                    "severity": "high",
                    "text": heading,
                    "action": "remove_or_move_to_internal_metadata",
                }
            )
    if has_raw_html_table_markup(text):
        issues.append(
            {
                "type": "raw_html_table_not_cleaned",
                "severity": "high",
                "text": "normalized Markdown still contains table/tr/td/th HTML tags",
            }
        )
    if not citation_map:
        issues.append(
            {
                "type": "missing_citation_anchor",
                "severity": "high",
                "text": "citation_map_empty",
            }
        )
    for item in citation_map:
        if not item.get("anchor_id") or not item.get("source_locator"):
            issues.append(
                {
                    "type": "missing_citation_anchor",
                    "severity": "high",
                    "text": str(item.get("section_title") or item),
                }
            )
        if item.get("source_type") != primary_source_type:
            issues.append(
                {
                    "type": "citation_source_type_mismatch",
                    "severity": "high",
                    "text": str(item.get("anchor_id") or ""),
                }
            )
    rag_metrics = rag_readiness_metrics(text, citation_map, primary_source_type=primary_source_type)
    if strict_rag_readiness:
        for issue in rag_readiness_issues(rag_metrics):
            issues.append(issue)
    score = quality_score(issues)
    combined_text = ascii_key(raw_text + "\n" + text)
    return {
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "quality_status": "passed" if score >= 0.90 and not any(issue["severity"] == "high" for issue in issues) else "needs_review",
        "quality_score": score,
        "raw_conversion_engine": raw_converter or "unknown",
        "raw_markdown_path": str(raw_markdown_path) if raw_markdown_path else None,
        "mineru_artifact_index_path": str(mineru_artifact_index_path) if mineru_artifact_index_path else None,
        "mineru_artifact_summary": mineru_artifact_summary,
        "mineru_rich_metadata_available": bool(
            mineru_artifact_summary
            and (
                mineru_artifact_summary.get("has_content_list")
                or mineru_artifact_summary.get("has_content_list_v2")
                or mineru_artifact_summary.get("has_middle_json")
            )
        ),
        "raw_non_empty": raw_non_empty,
        "normalized_non_empty": len(text.strip()) >= 20,
        "source_revision_detected": "rev 04" in combined_text,
        "display_code_detected": "pd tech a 02" in combined_text or "pdtecha02" in combined_text.replace(" ", ""),
        "synthetic_heading_count": sum(1 for issue in issues if issue["type"] == "synthetic_heading_not_in_source"),
        "raw_synthetic_heading_count": raw_synthetic_heading_count,
        "raw_prompt_debug_count": raw_prompt_debug_count,
        "raw_html_table_markup_remaining": has_raw_html_table_markup(text),
        "missing_citation_anchor_count": sum(1 for issue in issues if issue["type"] == "missing_citation_anchor"),
        "strict_rag_readiness": strict_rag_readiness,
        "rag_readiness_metrics": rag_metrics,
        "issues": issues,
        "checked_at": utc_now(),
    }


def rag_readiness_metrics(text: str, citation_map: list[dict[str, Any]], *, primary_source_type: str) -> dict[str, Any]:
    heading_keys = [ascii_key(heading) for heading in markdown_headings(text)]
    core_markers = {
        "muc_dich": "muc dich",
        "trach_nhiem": "trach nhiem",
        "quy_trinh_thuc_hien": "quy trinh thuc hien",
    }
    present = {
        key: any(marker in heading for heading in heading_keys)
        for key, marker in core_markers.items()
    }
    duplicate_core_heading_count = 0
    for marker in core_markers.values():
        count = sum(1 for heading in heading_keys if marker == heading or heading.endswith(marker))
        if count > 1:
            duplicate_core_heading_count += count - 1
    locator_count = len(citation_map)
    precise_locator_count = sum(
        1 for item in citation_map if citation_locator_is_precise(item, primary_source_type=primary_source_type)
    )
    source_locator_precision = round(precise_locator_count / locator_count, 2) if locator_count else 0.0
    procedure_step_count = sum(
        1 for heading in markdown_headings(text) if re.match(r"^buoc\s+\d+", ascii_key(heading))
    )
    if procedure_step_count == 0:
        procedure_step_count = len(re.findall(r"(?im)^\s*[-*]\s*B(?:u|ư|uoc|ước)", text))
    procedure_noise_count = count_procedure_noise(text)
    return {
        "required_sections_present": present,
        "required_section_pass": all(present.values()),
        "duplicate_core_heading_count": duplicate_core_heading_count,
        "procedure_step_count": procedure_step_count,
        "procedure_noise_count": procedure_noise_count,
        "citation_count": locator_count,
        "precise_locator_count": precise_locator_count,
        "source_locator_precision": source_locator_precision,
    }


def citation_locator_is_precise(item: dict[str, Any], *, primary_source_type: str) -> bool:
    if item.get("source_type") != primary_source_type:
        return False
    locator = item.get("source_locator") or {}
    if primary_source_type == "xlsx":
        return bool(
            locator.get("sheet")
            and locator.get("sheet") != "MinerU raw"
            and locator.get("row_start")
            and locator.get("row_end")
            and locator.get("columns")
            and locator.get("row_basis") != "mineru_raw_line"
        )
    if primary_source_type == "pdf":
        return bool(locator.get("page_start") and locator.get("page_end"))
    return bool(locator)


def count_procedure_noise(text: str) -> int:
    normalized = ascii_key(text)
    markers = [
        "bìa",
        "bia",
        "lich su chinh sua",
        "nguoi soan",
        "ma so tai lieu",
        "so chinh sua",
    ]
    procedure_start = normalized.find("quy trinh thuc hien")
    procedure_text = normalized[procedure_start:] if procedure_start >= 0 else normalized
    return sum(1 for marker in markers if marker in procedure_text)


def rag_readiness_issues(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for key, present in (metrics.get("required_sections_present") or {}).items():
        if not present:
            issues.append(
                {
                    "type": "missing_required_rag_section",
                    "severity": "high",
                    "text": key,
                }
            )
    if int(metrics.get("duplicate_core_heading_count") or 0) > 0:
        issues.append(
            {
                "type": "duplicate_core_heading",
                "severity": "high",
                "text": str(metrics.get("duplicate_core_heading_count")),
            }
        )
    if int(metrics.get("procedure_noise_count") or 0) > 0:
        issues.append(
            {
                "type": "procedure_section_contains_metadata_noise",
                "severity": "high",
                "text": str(metrics.get("procedure_noise_count")),
            }
        )
    if int(metrics.get("procedure_step_count") or 0) < 1:
        issues.append(
            {
                "type": "missing_procedure_steps",
                "severity": "high",
                "text": "No numbered procedure step heading detected.",
            }
        )
    if float(metrics.get("source_locator_precision") or 0.0) < 0.8:
        issues.append(
            {
                "type": "weak_source_locator_precision",
                "severity": "high",
                "text": str(metrics.get("source_locator_precision")),
            }
        )
    return issues


def quality_score(issues: list[dict[str, Any]]) -> float:
    score = 1.0
    for issue in issues:
        severity = issue.get("severity")
        if severity == "high":
            score -= 0.25
        elif severity == "medium":
            score -= 0.10
        else:
            score -= 0.03
    return round(max(0.0, score), 2)


def has_raw_html_table_markup(text: str) -> bool:
    return bool(re.search(r"</?(?:table|tr|td|th)\b", text, flags=re.IGNORECASE))


def build_chunk_plan(citation_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks = []
    for index, citation in enumerate(citation_map, start=1):
        chunks.append(
            {
                "chunk_id": f"KT-QT-002-S{index:02d}-C01",
                "anchor_id": citation["anchor_id"],
                "doc_id": PILOT_DOC_ID,
                "display_code": PILOT_DISPLAY_CODE,
                "source_revision": PILOT_SOURCE_REVISION,
                "section_title": citation.get("section_title"),
                "source_type": citation.get("source_type"),
                "display_locator": citation.get("display_locator"),
                "source_json": citation.get("source_json"),
                "mineru_block_ids": (citation.get("source_locator") or {}).get("mineru_block_ids"),
                "content_types": (citation.get("source_locator") or {}).get("content_types"),
                "image_refs": citation.get("image_refs") or [],
            }
        )
    return chunks


def build_review_report(*, approved: bool, reviewer: str) -> dict[str, Any]:
    status = "approved" if approved else "needs_fix"
    checklist = {
        "title_correct": approved,
        "revision_correct": approved,
        "headings_source_based": approved,
        "steps_order_correct": approved,
        "no_synthetic_content": approved,
        "citations_correct": approved,
        "source_output_audit_reviewed": approved,
        "mineru_rich_artifacts_reviewed": approved,
    }
    return {
        "review_status": status,
        "reviewer": reviewer,
        "reviewed_at": utc_now() if approved else None,
        "checklist": checklist,
        "notes": "" if approved else "Awaiting human review approval.",
    }


def upsert_pilot_record(
    root: Path,
    *,
    primary_path: Path,
    selected: str,
    decision: dict[str, Any],
    supporting_sources: list[dict[str, Any]],
    paths: PilotPaths,
    quality_report: dict[str, Any],
    review: dict[str, Any],
    mineru_profile: dict[str, Any],
    mineru_artifact_index_path: Path | None = None,
) -> ManifestRecord:
    now = utc_now()
    record = ManifestRecord(
        doc_id=PILOT_DOC_ID,
        title=f"{PILOT_DISPLAY_CODE} {PILOT_SOURCE_REVISION} - {PILOT_TITLE}",
        department="technical",
        category="procedure",
        source_type="internal_procedure",
        language="vi",
        version=PILOT_INTERNAL_VERSION,
        status="pending_review",
        status_reason="Awaiting human review" if review["review_status"] != "approved" else None,
        effective_from=now[:10],
        review_at=None,
        owner="Phong Ky thuat",
        approved_by=None,
        source_path=str(primary_path),
        normalized_path=str(paths.normalized),
        content_hash=content_hash(primary_path),
        access_group="technical",
        created_at=now,
        updated_at=now,
        extra={
            "display_code": PILOT_DISPLAY_CODE,
            "canonical_business_code": PILOT_DISPLAY_CODE,
            "original_name": PILOT_TITLE,
            "original_filename": primary_path.name,
            "internal_version": PILOT_INTERNAL_VERSION,
            "source_revision": PILOT_SOURCE_REVISION,
            "display_version": PILOT_SOURCE_REVISION,
            "primary_source_type": selected,
            "primary_source_path": str(primary_path),
            "supporting_sources": supporting_sources,
            "keep_original_filename": True,
            "dedupe_group": PILOT_DISPLAY_CODE,
            "ingest_policy": "primary_source_only",
            "used_for_retrieval": True,
            "artifact_stem": PILOT_ARTIFACT_STEM,
            "raw_converter": "mineru",
            "raw_conversion_policy": "mineru_only_no_fallback",
            "raw_markdown_path": str(paths.converted_raw / f"{PILOT_ARTIFACT_STEM}_raw.md"),
            "mineru_artifact_index_path": str(mineru_artifact_index_path) if mineru_artifact_index_path else None,
            "mineru_artifact_summary": quality_report.get("mineru_artifact_summary"),
            "mineru_profile": mineru_profile,
            "source_probe_report_path": str(paths.probe_report),
            "primary_source_decision": decision,
            "section_index_path": str(paths.section_index),
            "chunk_plan_path": str(paths.chunk_plan),
            "citation_map_path": str(paths.citation_map),
            "quality_report_path": str(paths.quality_report),
            "quality_status": quality_report["quality_status"],
            "quality_score": quality_report["quality_score"],
            "review_report_path": str(paths.review_report),
            "review_status": review["review_status"],
            "active_scope_id": PILOT_SCOPE_ID,
        },
    )
    ManifestStore(root).upsert(record)
    QualityDatabase(root).log_ingestion("pilot_pending_review", record.doc_id, record.version)
    return record


def retire_duplicate_business_records(root: Path, *, keep_key: str) -> None:
    store = ManifestStore(root)
    records = store.load()
    changed = False
    now = utc_now()
    for record in records:
        if record.key == keep_key:
            continue
        if record_business_identity(record) != PILOT_DISPLAY_CODE:
            continue
        if record.status in {"active", "pending_review", "normalized", "staging"}:
            record.status = "archived"
            record.status_reason = f"Deduped by pilot {PILOT_DOC_ID} {PILOT_SOURCE_REVISION}; primary_source_only."
            record.effective_to = record.effective_to or now[:10]
            record.updated_at = now
            changed = True
    if changed:
        store.save(records)


def record_business_identity(record: ManifestRecord) -> str | None:
    extra = record.extra or {}
    for key in ("canonical_business_code", "display_code", "dedupe_group", "canonical_doc_id"):
        value = extra.get(key)
        if value and str(value).upper() == PILOT_DISPLAY_CODE:
            return PILOT_DISPLAY_CODE
    if PILOT_DISPLAY_CODE in str(record.title).upper().replace(" ", "-"):
        return PILOT_DISPLAY_CODE
    return None


def markdown_headings(text: str) -> list[str]:
    headings = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(1).strip())
    return headings


def canonical_heading_for_text(text: str) -> str | None:
    normalized = ascii_key(text)
    for marker, title in CANONICAL_SECTION_TITLES.items():
        if marker in normalized:
            return title
    return None


def markdown_line_for_values(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return "- " + " | ".join(values)


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", "\n").split()).strip()


def columns_for_values(count: int) -> list[str]:
    return [column_label(index) for index in range(1, count + 1)]


def column_label(index: int) -> str:
    label = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def ascii_key(value: object) -> str:
    import unicodedata

    raw = str(value).replace("Đ", "D").replace("đ", "d")
    text = "".join(
        char for char in unicodedata.normalize("NFD", raw) if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
