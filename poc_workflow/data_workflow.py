from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .rag_index import chunk_markdown_with_metadata, stable_anchor_id
from .utils import content_hash, read_json, safe_filename, tokenize, utc_now, write_json


class DataWorkflowError(RuntimeError):
    pass


REQUIRED_SKILLS = {
    "data-pipeline-orchestrator",
    "mineru-source-converter",
    "source-output-quality-auditor",
    "rag-markdown-repairer",
    "ragflow-schema-indexer",
    "data-skill-evolution",
}

REQUIRED_HANDOFF_KEYS = {"run_id", "step", "status", "source_ids", "artifacts", "quality_gates", "next_skill"}
HANDOFF_STATUS_VALUES = {"ready", "passed", "needs_repair", "blocked", "failed"}
UPLOAD_RUNTIME_STATUSES = {"queue", "processing", "done", "failed", "ocr_required"}
PROCESSING_RUNTIME_STEPS = {
    "waiting",
    "prepare",
    "classify",
    "check_service",
    "submit",
    "queue",
    "parse",
    "download",
    "extract_artifacts",
    "build_outputs",
    "mineru_convert",
    "compare_sources",
    "preclean",
    "domain_agent",
    "handoff_check",
    "qa",
    "repair_loop",
    "rag_ready",
    "review",
    "done",
    "ocr_required",
    "failed",
}


def agent_skills_root() -> Path:
    return Path(__file__).resolve().parent / "agent_skills"


def load_agent_skill_registry() -> dict[str, Any]:
    path = agent_skills_root() / "registry.json"
    if not path.exists():
        return {}
    return read_json(path)


def validate_agent_skill_registry(registry: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    default_order = registry.get("default_order")
    if not isinstance(default_order, list) or not default_order:
        issues.append("registry.default_order is missing")
    elif set(default_order) < REQUIRED_SKILLS:
        issues.append("registry.default_order must include all required data workflow skills")

    status_values = set(((registry.get("handoff_contract") or {}).get("status_values") or []))
    if status_values and status_values != HANDOFF_STATUS_VALUES:
        issues.append("handoff_contract.status_values must match runtime status values")

    handoff_keys = set(((registry.get("handoff_contract") or {}).get("required_keys") or []))
    missing_handoff = sorted(REQUIRED_HANDOFF_KEYS - handoff_keys)
    if missing_handoff:
        issues.append(f"handoff_contract missing keys: {', '.join(missing_handoff)}")

    workflow_steps = registry.get("workflow_steps")
    if not isinstance(workflow_steps, list) or not workflow_steps:
        issues.append("registry.workflow_steps is missing")
    else:
        seen_steps = {str(item.get("step") or "") for item in workflow_steps if isinstance(item, dict)}
        for required_step in {"plan", "convert", "audit", "repair", "index", "evolve"}:
            if required_step not in seen_steps:
                issues.append(f"registry.workflow_steps missing step: {required_step}")

    execution_contract = registry.get("agent_execution_contract")
    if not isinstance(execution_contract, dict):
        issues.append("registry.agent_execution_contract is missing")
    else:
        if execution_contract.get("skill_read_required") is not True:
            issues.append("agent_execution_contract.skill_read_required must be true")
        receipt_fields = execution_contract.get("skill_read_receipt_required_fields")
        for key in {"skill", "path", "checksum", "read_at", "applies_to_step"}:
            if not isinstance(receipt_fields, list) or key not in receipt_fields:
                issues.append(f"agent_execution_contract.skill_read_receipt_required_fields missing: {key}")

    rag_contract = registry.get("rag_readiness_contract")
    if not isinstance(rag_contract, dict):
        issues.append("registry.rag_readiness_contract is missing")
    else:
        required_outputs = set(rag_contract.get("required_outputs") or [])
        for key in {
            "normalized_markdown",
            "metadata_json",
            "section_index_json",
            "chunk_plan_json",
            "citation_map_json",
            "quality_report_json",
        }:
            if key not in required_outputs:
                issues.append(f"rag_readiness_contract.required_outputs missing: {key}")
    return issues


def validate_processing_event(*, status: str, step: str) -> None:
    if status not in UPLOAD_RUNTIME_STATUSES:
        raise DataWorkflowError(f"Unsupported upload runtime status: {status}")
    if step not in PROCESSING_RUNTIME_STEPS:
        raise DataWorkflowError(f"Unsupported processing workflow step: {step}")


def workflow_run_id(doc_id: str, version: str) -> str:
    timestamp = utc_now().replace(":", "").replace("+", "Z")
    return f"ragflow-run-{safe_filename(doc_id)}-v{safe_filename(version)}-{timestamp}"


def validate_workflow_handoff(handoff: dict[str, Any], registry: dict[str, Any] | None = None) -> None:
    missing = sorted(REQUIRED_HANDOFF_KEYS - set(handoff))
    if missing:
        raise DataWorkflowError(f"Workflow handoff missing keys: {', '.join(missing)}")
    if handoff["status"] not in HANDOFF_STATUS_VALUES:
        raise DataWorkflowError(f"Unsupported handoff status: {handoff['status']}")
    if not isinstance(handoff.get("source_ids"), list) or not handoff["source_ids"]:
        raise DataWorkflowError("Workflow handoff source_ids must be a non-empty list")
    artifacts = handoff.get("artifacts")
    if not isinstance(artifacts, list):
        raise DataWorkflowError("Workflow handoff artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise DataWorkflowError("Workflow handoff artifact must be an object")
        for key in ("artifact_id", "path", "type", "source_id", "checksum"):
            if key not in artifact:
                raise DataWorkflowError(f"Workflow handoff artifact missing key: {key}")
    if registry:
        issues = validate_agent_skill_registry(registry)
        if issues:
            raise DataWorkflowError("; ".join(issues))
        execution_contract = registry.get("agent_execution_contract") or {}
        if execution_contract.get("skill_read_required"):
            validate_skill_read_receipts(
                handoff.get("skill_read_receipts"),
                execution_contract.get("skill_read_receipt_required_fields") or [],
            )
        checker = handoff.get("handoff_checker")
        if execution_contract.get("handoff_checker_required") and not isinstance(checker, dict):
            raise DataWorkflowError("Workflow handoff missing handoff_checker contract payload")
        if isinstance(checker, dict) and checker.get("status") not in {"passed", "skipped"}:
            raise DataWorkflowError("Workflow handoff checker status must be passed or skipped")


def validate_skill_read_receipts(receipts: Any, required_fields: list[str]) -> None:
    if not isinstance(receipts, list) or not receipts:
        raise DataWorkflowError("Workflow handoff must include non-empty skill_read_receipts")
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise DataWorkflowError("Workflow skill_read_receipt must be an object")
        for key in required_fields:
            if key not in receipt:
                raise DataWorkflowError(f"Workflow skill_read_receipt missing key: {key}")
        skill_path = Path(str(receipt.get("path") or ""))
        if not skill_path.exists():
            raise DataWorkflowError(f"Workflow skill_read_receipt path does not exist: {skill_path}")


def append_workflow_handoff(root: Path, artifact_root: Path, handoff: dict[str, Any]) -> Path:
    registry = load_agent_skill_registry()
    validate_workflow_handoff(handoff, registry=registry)
    handoff_dir = artifact_root / "workflow"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    log_path = handoff_dir / "handoffs.jsonl"
    previous = _read_handoff_log(log_path)
    validate_handoff_transition(previous, handoff, registry)
    handoff = {**handoff, "recorded_at": utc_now()}
    latest = handoff_dir / "latest_handoff.json"
    write_json(latest, handoff)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(handoff, ensure_ascii=False) + "\n")
    return log_path


def validate_handoff_transition(previous: list[dict[str, Any]], handoff: dict[str, Any], registry: dict[str, Any]) -> None:
    step = str(handoff.get("step") or "")
    if not previous:
        if step != "plan":
            raise DataWorkflowError("First workflow handoff must be step=plan")
        return

    last = previous[-1]
    last_step = str(last.get("step") or "")
    last_status = str(last.get("status") or "")
    allowed = {
        "plan": {"convert"},
        "convert": {"audit"},
        "audit": {"repair", "index"},
        "repair": {"audit"},
        "index": {"evolve"},
        "evolve": set(),
    }
    if step not in allowed.get(last_step, set()):
        raise DataWorkflowError(f"Invalid workflow transition: {last_step} -> {step}")
    if last_step == "audit" and last_status == "needs_repair" and step != "repair":
        raise DataWorkflowError("Audit needs_repair must transition to repair")
    if last_step == "audit" and last_status == "passed" and step != "index":
        raise DataWorkflowError("Audit passed must transition to index")

    max_repairs = int(((registry.get("loop_policy") or {}).get("repair_loop") or {}).get("max_iterations") or 3)
    if step == "repair":
        repair_count = sum(1 for item in previous if item.get("step") == "repair")
        if repair_count >= max_repairs:
            raise DataWorkflowError(f"Repair loop exceeded max_iterations={max_repairs}")


def _read_handoff_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                events.append(json.loads(line))
    return events


def make_handoff(
    *,
    run_id: str,
    step: str,
    status: str,
    source_id: str,
    artifacts: list[dict[str, Any]] | None = None,
    quality_gates: dict[str, Any] | None = None,
    next_skill: str | None,
    skill_read_receipts: list[dict[str, Any]] | None = None,
    handoff_checker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = load_agent_skill_registry()
    receipts = skill_read_receipts
    if receipts is None:
        receipts = skill_read_receipts_for_step(step, registry=registry)
    checker = handoff_checker
    if checker is None:
        checker = handoff_checker_payload(step=step, registry=registry, receipt_count=len(receipts))
    return {
        "run_id": run_id,
        "step": step,
        "status": status,
        "source_ids": [source_id],
        "artifacts": artifacts or [],
        "quality_gates": quality_gates or {},
        "next_skill": next_skill,
        "skill_read_receipts": receipts,
        "handoff_checker": checker,
    }


def skill_read_receipts_for_step(step: str, registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    registry = registry or load_agent_skill_registry()
    skill = skill_for_workflow_step(step, registry)
    if not skill:
        return []
    path = agent_skills_root() / skill / "SKILL.md"
    return [
        {
            "skill": skill,
            "path": str(path),
            "checksum": content_hash(path) if path.exists() else None,
            "read_at": utc_now(),
            "applies_to_step": step,
        }
    ]


def skill_for_workflow_step(step: str, registry: dict[str, Any] | None = None) -> str | None:
    registry = registry or load_agent_skill_registry()
    for item in registry.get("workflow_steps") or []:
        if isinstance(item, dict) and item.get("step") == step:
            skill = item.get("skill")
            return str(skill) if skill else None
    return None


def handoff_checker_payload(*, step: str, registry: dict[str, Any], receipt_count: int) -> dict[str, Any]:
    execution_contract = registry.get("agent_execution_contract") or {}
    return {
        "status": "passed",
        "contract_version": registry.get("registry_version") or "unknown",
        "step": step,
        "skill_read_required": bool(execution_contract.get("skill_read_required")),
        "subagent_contract_inherited": bool(execution_contract.get("subagent_inherits_contract")),
        "receipt_count": receipt_count,
        "checked_at": utc_now(),
    }


def artifact_record(path: Path, *, artifact_id: str, artifact_type: str, source_id: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "type": artifact_type,
        "source_id": source_id,
        "checksum": content_hash(path) if path.exists() and path.is_file() else None,
    }


def build_rag_ready_package(
    root: Path,
    *,
    metadata: dict[str, Any],
    source_path: Path,
    normalized_path: Path,
    qa_report: dict[str, Any],
) -> dict[str, Any]:
    doc_id = str(metadata["doc_id"])
    version = str(metadata["version"])
    department = str(metadata.get("department") or "technical")
    category = str(metadata.get("category") or "procedure")
    artifact_stem = f"{safe_filename(doc_id)}_v{safe_filename(version)}"
    index_root = root / "indexes"
    index_root.mkdir(parents=True, exist_ok=True)
    package_root = root / "rag_ready" / department / category / f"{safe_filename(doc_id)}_v{safe_filename(version)}"
    package_root.mkdir(parents=True, exist_ok=True)

    content_path = package_root / "normalized.md"
    shutil.copy2(normalized_path, content_path)
    text = normalized_path.read_text(encoding="utf-8", errors="replace")
    chunks = chunk_markdown_with_metadata(text)
    section_records = build_section_index(text, normalized_path, doc_id, version)
    source_blocks = mineru_source_blocks(metadata.get("mineru_artifact_index_path")) + source_evidence_blocks(source_path)
    chunk_records: list[dict[str, Any]] = []
    citation_records: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        anchor_id = stable_anchor_id(doc_id, version, index)
        chunk_id = f"{doc_id}_v{version}_c{index}"
        section = section_for_chunk(section_records, int(chunk["line_start"]))
        citation = build_citation_record(
            doc_id=doc_id,
            version=version,
            chunk_id=chunk_id,
            anchor_id=anchor_id,
            chunk=chunk,
            source_path=source_path,
            normalized_path=normalized_path,
            source_blocks=source_blocks,
            section=section,
        )
        chunk_records.append(
            {
                "chunk_id": chunk_id,
                "anchor_id": anchor_id,
                "section_anchor_id": section.get("anchor_id") if section else None,
                "section_title": section.get("title") if section else None,
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "content_path": str(content_path),
                "checksum": content_hash(content_path),
                "text_hash": stable_text_hash(str(chunk.get("text") or "")),
                "chunk_strategy": "markdown_blocks",
                "max_chars": 1200,
            }
        )
        citation_records.append(citation)

    locator_coverage = citation_locator_coverage(citation_records)
    quality_report = {
        **qa_report,
        "artifact_schema_version": "rag_artifacts_v1",
        "quality_gates": {
            **(qa_report.get("metrics", {}).get("quality_gates") or {}),
            "citation_anchors_present": bool(citation_records),
            "source_locator_coverage": locator_coverage,
            "source_locators_review_required": locator_coverage < 1.0,
        },
    }
    metadata_artifact = build_metadata_artifact(
        metadata=metadata,
        source_path=source_path,
        normalized_path=normalized_path,
        content_path=content_path,
        qa_report=quality_report,
    )

    schema_manifest = {
        "artifact_schema_version": "rag_artifacts_v1",
        "doc_id": doc_id,
        "version": version,
        "title": metadata.get("title"),
        "department": department,
        "category": category,
        "language": metadata.get("language"),
        "source_path": str(source_path),
        "normalized_path": str(normalized_path),
        "content_path": str(content_path),
        "chunk_policy": {"strategy": "markdown_blocks", "max_chars": 1200},
        "metadata_fields": sorted(metadata.keys()),
        "qa_status": qa_report.get("status"),
        "canonical_artifacts": {},
    }
    index_manifest = {
        "artifact_schema_version": "rag_artifacts_v1",
        "doc_id": doc_id,
        "version": version,
        "chunks": chunk_records,
        "source_checksum": content_hash(source_path),
        "normalized_checksum": content_hash(normalized_path),
        "created_at": utc_now(),
    }
    citation_manifest = {
        "artifact_schema_version": "rag_artifacts_v1",
        "doc_id": doc_id,
        "version": version,
        "citations": citation_records,
    }
    metadata_path = index_root / f"{artifact_stem}_metadata.json"
    section_index_path = index_root / f"{artifact_stem}_section_index.json"
    chunk_plan_path = index_root / f"{artifact_stem}_chunk_plan.json"
    citation_map_path = index_root / f"{artifact_stem}_citation_map.json"
    quality_report_path = index_root / f"{artifact_stem}_quality_report.json"
    schema_path = package_root / "schema_manifest.json"
    citation_path = package_root / "citation_manifest.json"
    index_path = package_root / "index_manifest.json"
    artifact_paths = {
        "normalized_markdown": str(normalized_path),
        "metadata_json": str(metadata_path),
        "section_index_json": str(section_index_path),
        "chunk_plan_json": str(chunk_plan_path),
        "citation_map_json": str(citation_map_path),
        "quality_report_json": str(quality_report_path),
    }
    if metadata.get("mineru_artifact_index_path"):
        artifact_paths["mineru_artifact_index_json"] = str(metadata["mineru_artifact_index_path"])
    schema_manifest["canonical_artifacts"] = artifact_paths
    write_json(metadata_path, metadata_artifact)
    write_json(section_index_path, section_records)
    write_json(chunk_plan_path, chunk_records)
    write_json(citation_map_path, citation_records)
    write_json(quality_report_path, quality_report)
    write_json(schema_path, schema_manifest)
    write_json(citation_path, citation_manifest)
    write_json(index_path, index_manifest)

    return {
        "package_root": str(package_root),
        "content_path": str(content_path),
        "metadata_json_path": str(metadata_path),
        "section_index_path": str(section_index_path),
        "chunk_plan_path": str(chunk_plan_path),
        "citation_map_path": str(citation_map_path),
        "quality_report_path": str(quality_report_path),
        "schema_manifest_path": str(schema_path),
        "citation_manifest_path": str(citation_path),
        "index_manifest_path": str(index_path),
        "chunk_count": len(chunk_records),
        "source_locator_coverage": locator_coverage,
    }


def build_metadata_artifact(
    *,
    metadata: dict[str, Any],
    source_path: Path,
    normalized_path: Path,
    content_path: Path,
    qa_report: dict[str, Any],
) -> dict[str, Any]:
    copied = {
        key: value
        for key, value in metadata.items()
        if value is not None and key not in {"prompt", "raw_text", "content"}
    }
    return {
        "artifact_schema_version": "rag_artifacts_v1",
        "document": copied,
        "source": {
            "path": str(source_path),
            "type": source_path.suffix.lower().lstrip(".") or "file",
            "checksum": content_hash(source_path),
        },
        "normalized": {
            "path": str(normalized_path),
            "checksum": content_hash(normalized_path),
        },
        "rag_ready_content": {
            "path": str(content_path),
            "checksum": content_hash(content_path),
        },
        "quality": {
            "status": qa_report.get("status"),
            "issues": qa_report.get("issues") or [],
            "checked_at": qa_report.get("checked_at"),
        },
        "created_at": utc_now(),
    }


def build_section_index(text: str, normalized_path: Path, doc_id: str, version: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    headings: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append(
                {
                    "heading_level": len(match.group(1)),
                    "title": match.group(2).strip(),
                    "line_start": index,
                }
            )
    if not headings:
        return [
            {
                "anchor_id": f"{doc_id}_v{version}_s1",
                "title": "Document",
                "heading_level": 0,
                "line_start": 1,
                "line_end": max(1, len(lines)),
                "normalized_path": str(normalized_path),
            }
        ]
    sections: list[dict[str, Any]] = []
    for index, heading in enumerate(headings, start=1):
        next_heading = headings[index] if index < len(headings) else None
        sections.append(
            {
                "anchor_id": f"{doc_id}_v{version}_s{index}",
                "title": heading["title"],
                "heading_level": heading["heading_level"],
                "line_start": heading["line_start"],
                "line_end": (int(next_heading["line_start"]) - 1) if next_heading else max(heading["line_start"], len(lines)),
                "normalized_path": str(normalized_path),
            }
        )
    return sections


def section_for_chunk(sections: list[dict[str, Any]], line_start: int) -> dict[str, Any] | None:
    for section in sections:
        if int(section["line_start"]) <= line_start <= int(section["line_end"]):
            return section
    return sections[-1] if sections else None


def build_citation_record(
    *,
    doc_id: str,
    version: str,
    chunk_id: str,
    anchor_id: str,
    chunk: dict[str, Any],
    source_path: Path,
    normalized_path: Path,
    source_blocks: list[dict[str, Any]],
    section: dict[str, Any] | None,
) -> dict[str, Any]:
    chunk_text = str(chunk.get("text") or "")
    match = best_source_match(chunk_text, source_blocks)
    record = {
        "artifact_schema_version": "rag_artifacts_v1",
        "doc_id": doc_id,
        "version": version,
        "anchor_id": anchor_id,
        "chunk_id": chunk_id,
        "section_anchor_id": section.get("anchor_id") if section else None,
        "section_title": section.get("title") if section else None,
        "source_path": str(source_path),
        "source_type": source_path.suffix.lower().lstrip(".") or "file",
        "normalized_locator": {
            "path": str(normalized_path),
            "line_start": int(chunk["line_start"]),
            "line_end": int(chunk["line_end"]),
        },
        "source_locator": None,
        "display_locator": "Source locator unresolved; use normalized Markdown line range for review.",
        "locator_status": "unresolved",
        "locator_confidence": 0.0,
        "locator_basis": "not_enough_source_overlap",
        "evidence_terms": [],
        "requires_human_review": True,
    }
    if match:
        record.update(
            {
                "source_locator": match["locator"],
                "display_locator": match["display_locator"],
                "locator_status": "resolved",
                "locator_confidence": match["confidence"],
                "locator_basis": match["basis"],
                "evidence_terms": match["evidence_terms"],
                "requires_human_review": match["confidence"] < 0.35,
                "source_json": match.get("source_json"),
                "image_ref": match.get("image_ref"),
            }
        )
    return record


def citation_locator_coverage(citations: list[dict[str, Any]]) -> float:
    if not citations:
        return 0.0
    resolved = sum(1 for item in citations if item.get("locator_status") == "resolved")
    return round(resolved / len(citations), 4)


def best_source_match(chunk_text: str, source_blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    chunk_terms = meaningful_terms(chunk_text)
    if not chunk_terms:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    best_terms: set[str] = set()
    for block in source_blocks:
        block_terms = meaningful_terms(str(block.get("text") or ""))
        if not block_terms:
            continue
        matched = chunk_terms & block_terms
        if not matched:
            continue
        recall = len(matched) / max(1, len(chunk_terms))
        precision = len(matched) / max(1, len(block_terms))
        score = round((recall * 0.75) + (precision * 0.25), 4)
        if score > best_score:
            best = block
            best_score = score
            best_terms = matched
    if not best:
        return None
    if len(best_terms) < 2 and best_score < 0.35:
        return None
    return {
        "locator": best["locator"],
        "display_locator": best["display_locator"],
        "confidence": best_score,
        "basis": best.get("basis") or "text_overlap",
        "evidence_terms": sorted(best_terms)[:20],
        "source_json": best.get("source_json"),
        "image_ref": best.get("image_ref"),
    }


def source_evidence_blocks(source_path: Path) -> list[dict[str, Any]]:
    suffix = source_path.suffix.lower()
    try:
        if suffix in {".md", ".markdown", ".txt", ".csv"}:
            return text_file_source_blocks(source_path)
        if suffix == ".xlsx":
            return xlsx_source_blocks(source_path)
        if suffix == ".pdf":
            return pdf_source_blocks(source_path)
        if suffix == ".docx":
            return docx_source_blocks(source_path)
    except Exception:
        return []
    return []


def mineru_source_blocks(index_path_value: object) -> list[dict[str, Any]]:
    if not index_path_value:
        return []
    index_path = Path(str(index_path_value))
    if not index_path.exists():
        return []
    try:
        artifact_index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    content_artifact = None
    artifacts = artifact_index.get("artifacts") or []
    if isinstance(artifacts, list):
        for artifact_type in ("content_list_v2", "content_list"):
            content_artifact = next(
                (item for item in artifacts if isinstance(item, dict) and item.get("type") == artifact_type),
                None,
            )
            if content_artifact:
                break
    if not content_artifact or not content_artifact.get("path"):
        return []
    content_path = Path(str(content_artifact["path"]))
    if not content_path.exists():
        return []
    try:
        payload = json.loads(content_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    blocks: list[dict[str, Any]] = []
    if isinstance(payload, list) and payload and all(isinstance(item, list) for item in payload):
        for page_index, page_blocks in enumerate(payload):
            for block in page_blocks:
                append_mineru_source_block(blocks, block, page_index, content_artifact, content_path)
    elif isinstance(payload, list):
        for block in payload:
            append_mineru_source_block(blocks, block, None, content_artifact, content_path)
    return blocks


def append_mineru_source_block(
    blocks: list[dict[str, Any]],
    block: Any,
    page_index: int | None,
    content_artifact: dict[str, Any],
    content_path: Path,
) -> None:
    if not isinstance(block, dict):
        return
    text = mineru_block_text(block)
    if not text:
        return
    block_type = str(block.get("type") or "unknown")
    page_idx = block.get("page_idx")
    if not isinstance(page_idx, int):
        page_idx = page_index
    bbox = block.get("bbox")
    locator: dict[str, Any] = {
        "type": "mineru",
        "content_type": block_type,
        "mineru_block_id": str(block.get("id") or f"mineru-{len(blocks) + 1:04d}"),
        "source_json": content_artifact.get("type"),
    }
    display_locator = "MinerU content block"
    if isinstance(page_idx, int):
        locator["page_start"] = page_idx + 1
        locator["page_end"] = page_idx + 1
        display_locator = f"MinerU page {page_idx + 1}"
    if bbox:
        locator["bbox"] = bbox
    image_path = mineru_block_image_path(block)
    image_ref = None
    if image_path:
        image_ref = str((content_path.parent.parent / image_path).resolve()) if not Path(image_path).is_absolute() else image_path
        locator["image_ref"] = image_ref
    blocks.append(
        {
            "text": text,
            "locator": locator,
            "display_locator": display_locator,
            "basis": "mineru_content_list_overlap",
            "source_json": content_artifact.get("type"),
            "image_ref": image_ref,
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
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


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


def text_file_source_blocks(source_path: Path) -> list[dict[str, Any]]:
    lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks: list[dict[str, Any]] = []
    current: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        if line.strip():
            current.append((index, line))
        elif current:
            blocks.append(text_line_block(source_path, current))
            current = []
    if current:
        blocks.append(text_line_block(source_path, current))
    return blocks


def text_line_block(source_path: Path, lines: list[tuple[int, str]]) -> dict[str, Any]:
    start = lines[0][0]
    end = lines[-1][0]
    return {
        "text": "\n".join(line for _, line in lines),
        "locator": {
            "type": source_path.suffix.lower().lstrip(".") or "text",
            "line_start": start,
            "line_end": end,
        },
        "display_locator": f"Source lines {start}-{end}",
        "basis": "source_line_text_overlap",
    }


def pdf_source_blocks(source_path: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    try:
        import pdfplumber

        with pdfplumber.open(source_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(pdf_page_block(index, text))
                for table_index, table in enumerate(page.extract_tables() or [], start=1):
                    table_text = "\n".join(" | ".join(str(cell or "") for cell in row) for row in table)
                    if table_text.strip():
                        block = pdf_page_block(index, table_text)
                        block["locator"]["table_index"] = table_index
                        block["display_locator"] = f"Page {index}, table {table_index}"
                        block["basis"] = "pdf_table_text_overlap"
                        pages.append(block)
    except Exception:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(source_path))
            for index, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(pdf_page_block(index, text))
        except Exception:
            return []
    return pages


def pdf_page_block(page: int, text: str) -> dict[str, Any]:
    return {
        "text": text,
        "locator": {"type": "pdf", "page_start": page, "page_end": page},
        "display_locator": f"Page {page}",
        "basis": "pdf_page_text_overlap",
    }


def docx_source_blocks(source_path: Path) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    with zipfile.ZipFile(source_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        index = 0
        for paragraph in root.findall(".//{*}p"):
            text = "".join(node.text or "" for node in paragraph.findall(".//{*}t")).strip()
            if text:
                index += 1
                blocks.append(
                    {
                        "text": text,
                        "locator": {"type": "docx", "paragraph_start": index, "paragraph_end": index},
                        "display_locator": f"Paragraph {index}",
                        "basis": "docx_paragraph_text_overlap",
                    }
                )
    return blocks


def xlsx_source_blocks(source_path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(source_path) as archive:
        shared_strings = xlsx_shared_strings(archive)
        sheet_names = xlsx_sheet_names(archive)
        row_blocks: list[dict[str, Any]] = []
        for sheet_path in sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml")):
            sheet_name = sheet_names.get(sheet_path, Path(sheet_path).stem)
            rows = xlsx_rows(archive, sheet_path, shared_strings)
            row_blocks.extend(xlsx_window_blocks(sheet_name, rows))
        return row_blocks


def xlsx_rows(archive: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[dict[str, Any]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: list[dict[str, Any]] = []
    for row in root.findall(".//{*}row"):
        row_index = int(row.attrib.get("r") or len(rows) + 1)
        values: list[str] = []
        columns: list[str] = []
        for cell in row.findall("{*}c"):
            value = xlsx_cell_value(cell, shared_strings)
            if value:
                values.append(value)
                columns.append(column_from_cell_ref(cell.attrib.get("r") or ""))
        if values:
            rows.append({"row": row_index, "columns": columns, "text": " | ".join(values)})
    return rows


def xlsx_window_blocks(sheet_name: str, rows: list[dict[str, Any]], window_size: int = 6) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for start in range(len(rows)):
        for end in range(start, min(len(rows), start + window_size)):
            window = rows[start : end + 1]
            columns = sorted({column for row in window for column in row["columns"]}, key=column_sort_key)
            row_start = int(window[0]["row"])
            row_end = int(window[-1]["row"])
            blocks.append(
                {
                    "text": "\n".join(str(row["text"]) for row in window),
                    "locator": {
                        "type": "xlsx",
                        "sheet": sheet_name,
                        "row_start": row_start,
                        "row_end": row_end,
                        "columns": columns,
                    },
                    "display_locator": f"Sheet {sheet_name}, rows {row_start}-{row_end}",
                    "basis": "xlsx_row_text_overlap",
                }
            )
    return blocks


def xlsx_sheet_names(archive: zipfile.ZipFile) -> dict[str, str]:
    if "xl/workbook.xml" not in archive.namelist():
        return {}
    rels: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in archive.namelist():
        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for rel in rels_root.findall(".//{*}Relationship"):
            rel_id = rel.attrib.get("Id")
            target = rel.attrib.get("Target")
            if rel_id and target:
                rels[rel_id] = normalize_xlsx_target(target)
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    names: dict[str, str] = {}
    for sheet in workbook.findall(".//{*}sheet"):
        name = sheet.attrib.get("name")
        rel_id = None
        for attr_key, attr_val in sheet.attrib.items():
            if attr_key.endswith("}id") or attr_key == "id":
                rel_id = attr_val
                break
        if name and rel_id and rel_id in rels:
            names[rels[rel_id]] = name
    return names


def normalize_xlsx_target(target: str) -> str:
    cleaned = target.replace("\\", "/").lstrip("/")
    if cleaned.startswith("xl/"):
        return cleaned
    return "xl/" + cleaned


def xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//{*}t")) for item in root.findall(".//{*}si")]


def xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{*}t")).strip()
    value_node = cell.find("{*}v")
    raw_value = (value_node.text or "") if value_node is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except Exception:
            return raw_value.strip()
    return raw_value.strip()


def column_from_cell_ref(cell_ref: str) -> str:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    return match.group(1) if match else "?"


def column_sort_key(column: str) -> tuple[int, str]:
    value = 0
    for char in column:
        if "A" <= char <= "Z":
            value = (value * 26) + (ord(char) - ord("A") + 1)
    return value, column


def meaningful_terms(text: str) -> set[str]:
    return {term for term in tokenize(text) if len(term) >= 3 and not term.isdigit()}


def stable_text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
