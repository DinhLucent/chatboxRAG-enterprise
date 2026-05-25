from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .rag_index import chunk_markdown_with_metadata, stable_anchor_id
from .utils import content_hash, read_json, safe_filename, utc_now, write_json


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
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "step": step,
        "status": status,
        "source_ids": [source_id],
        "artifacts": artifacts or [],
        "quality_gates": quality_gates or {},
        "next_skill": next_skill,
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
    package_root = root / "rag_ready" / department / category / f"{safe_filename(doc_id)}_v{safe_filename(version)}"
    package_root.mkdir(parents=True, exist_ok=True)

    content_path = package_root / "normalized.md"
    shutil.copy2(normalized_path, content_path)
    text = normalized_path.read_text(encoding="utf-8", errors="replace")
    chunks = chunk_markdown_with_metadata(text)
    chunk_records = []
    citation_records = []
    for index, chunk in enumerate(chunks, start=1):
        anchor_id = stable_anchor_id(doc_id, version, index)
        chunk_id = f"{doc_id}_v{version}_c{index}"
        chunk_records.append(
            {
                "chunk_id": chunk_id,
                "anchor_id": anchor_id,
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "content_path": str(content_path),
                "checksum": content_hash(content_path),
            }
        )
        citation_records.append(
            {
                "anchor_id": anchor_id,
                "chunk_id": chunk_id,
                "source_path": str(source_path),
                "normalized_path": str(normalized_path),
                "line_start": chunk["line_start"],
                "line_end": chunk["line_end"],
                "source_locator": {
                    "type": source_path.suffix.lower().lstrip(".") or "file",
                    "path": str(source_path),
                },
            }
        )

    schema_manifest = {
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
    }
    index_manifest = {
        "doc_id": doc_id,
        "version": version,
        "chunks": chunk_records,
        "source_checksum": content_hash(source_path),
        "normalized_checksum": content_hash(normalized_path),
        "created_at": utc_now(),
    }
    citation_manifest = {
        "doc_id": doc_id,
        "version": version,
        "citations": citation_records,
    }
    schema_path = package_root / "schema_manifest.json"
    citation_path = package_root / "citation_manifest.json"
    index_path = package_root / "index_manifest.json"
    write_json(schema_path, schema_manifest)
    write_json(citation_path, citation_manifest)
    write_json(index_path, index_manifest)

    return {
        "package_root": str(package_root),
        "content_path": str(content_path),
        "schema_manifest_path": str(schema_path),
        "citation_manifest_path": str(citation_path),
        "index_manifest_path": str(index_path),
        "chunk_count": len(chunk_records),
    }
