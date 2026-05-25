from __future__ import annotations

import json
import inspect
import shutil
from pathlib import Path

from .agent_prompt_queue import record_processing_status
from .config import ALLOWED_CATEGORIES, ARCHIVE_DATASET, DEFAULT_DIRS, SUPPORTED_SOURCE_SUFFIXES
from .converter import ConversionError, MinerUConverter, OcrRequiredError
from .data_workflow import (
    append_workflow_handoff,
    artifact_record,
    build_rag_ready_package,
    make_handoff,
    workflow_run_id,
)
from .database import QualityDatabase
from .document_qa import qa_source_output
from .manifest import (
    ManifestError,
    ManifestStore,
    archive_previous_active,
    latest_active_records,
    validate_metadata,
    validate_record_for_approval,
)
from .models import ManifestRecord
from .rag_index import LocalRagIndex
from .utils import content_hash, copy_file, read_json, safe_filename, utc_now, version_key, write_json


class PipelineError(RuntimeError):
    pass


def init_workspace(root: Path, with_sample: bool = False) -> None:
    for directory in DEFAULT_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    create_inbox_readme(root)
    create_inbox_classification_standard(root)
    create_workplace_readme(root)
    write_json(
        root / "manifest" / "taxonomy.json",
        {
            "company": {
                "department": {
                    "technical": [
                        "procedure",
                        "vendor_document",
                        "form_checklist",
                        "faq_troubleshooting",
                    ]
                }
            }
        },
    )
    QualityDatabase(root).init()
    if with_sample:
        create_sample_source(root)


def create_inbox_readme(root: Path) -> None:
    readme = root / "inbox" / "README.md"
    if readme.exists():
        return
    readme.write_text(
        """# Inbox Tai Lieu

Tha tai lieu can nap vao thu muc nay. Agent se chay `python -m poc_workflow prepare-inbox`
de tao metadata nhap va copy tai lieu sang `source/technical/<category>/`.

Goi y thu muc:

- `inbox/procedure/`
- `inbox/vendor_document/`
- `inbox/form_checklist/`
- `inbox/faq_troubleshooting/`

Khong dat tai lieu mat/chua duoc phep vao day neu chua co phe duyet noi bo.
""",
        encoding="utf-8",
    )


def create_inbox_classification_standard(root: Path) -> None:
    standard = root / "inbox" / "CLASSIFICATION_STANDARD.md"
    if standard.exists():
        return
    standard.write_text(
        """# Document Classification Standard For AI Agent

Use this file as the intake rulebook. The document owner only provides files; the AI agent classifies, drafts metadata, runs intake, and stops at `pending_review`.

## Allowed Categories

- `procedure`: internal process, SOP, work instruction, policy, approval workflow.
- `vendor_document`: manual, datasheet, catalog, installation guide, maintenance guide, vendor troubleshooting.
- `form_checklist`: form, template, checklist, report, pass/fail sheet, signature document.
- `faq_troubleshooting`: FAQ, fault code, symptom, root cause, confirmed fix, lesson learned.

## Quick Rules

```text
Internal steps or policy        -> procedure
Vendor/product/device material  -> vendor_document
Fillable/checkable template     -> form_checklist
Error/fault/fix knowledge       -> faq_troubleshooting
```

## Required Metadata

```json
{
  "doc_id": "KT-QT-001",
  "title": "Document title",
  "department": "technical",
  "category": "procedure",
  "source_type": "internal_procedure",
  "language": "vi",
  "version": "1.0",
  "effective_from": "2026-01-01",
  "review_at": "2026-12-31",
  "owner": "Phong Ky thuat",
  "access_group": "technical"
}
```

## Doc ID Prefixes

- `procedure`: `KT-QT-###`
- `vendor_document`: `KT-HANG-###`
- `form_checklist`: `KT-BM-###`
- `faq_troubleshooting`: `KT-FAQ-###`

Never approve automatically. Only a reviewer can move a document to `active`.
""",
        encoding="utf-8",
    )


def create_workplace_readme(root: Path) -> None:
    readme = root / ".Workplace" / "README.md"
    if readme.exists():
        return
    readme.write_text(
        """# .Workplace

Thu muc tam cho tung file dang duoc AI Agent/MinerU xu ly.

- `.Workplace/processing/`: file dang xu ly, giu duong dan tuong ung voi `inbox/`.
- `.Workplace/artifacts/`: output phu cua MinerU va `qa_report.json` theo tung `doc_id/version`.
- Ket qua hoan tat sau Convert + QA duoc dua ve `inbox/<category>/done/`.
- File loi duoc dua ve `inbox/<category>/failed/`.

Khong dua file trong `.Workplace` vao chatbot truc tiep. Chi tai lieu da review/approve moi duoc dua vao active index.
""",
        encoding="utf-8",
    )


def create_sample_source(root: Path) -> None:
    source = root / "source" / "technical" / "procedure" / "KT-QT-003_v1.0.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        source.write_text(
            """# Quy trinh xu ly su co ky thuat

## Muc dich

Tai lieu nay huong dan nhan vien phong Ky thuat tiep nhan, phan loai va xu ly su co ky thuat.

## Cac buoc thuc hien

1. Tiep nhan thong tin su co tu nguoi dung hoac he thong giam sat.
2. Ghi nhan ma ticket, thoi gian, nguoi bao loi va muc do anh huong.
3. Phan loai muc do uu tien theo quy dinh cua phong Ky thuat.
4. Thuc hien xu ly hoac chuyen cap neu vuot tham quyen.
5. Cap nhat ket qua xu ly va dong ticket sau khi nguoi yeu cau xac nhan.

## Nguon

KT-QT-003 v1.0.
""",
            encoding="utf-8",
        )
    metadata = source.with_name(source.stem + ".metadata.json")
    if not metadata.exists():
        write_json(
            metadata,
            {
                "doc_id": "KT-QT-003",
                "title": "Quy trinh xu ly su co ky thuat",
                "department": "technical",
                "category": "procedure",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2025-01-01",
                "review_at": "2025-12-31",
                "owner": "Phong Ky thuat",
                "access_group": "technical",
            },
        )
    sample_eval = root / "eval" / "regression_cases.json"
    if not sample_eval.exists():
        write_json(
            sample_eval,
            [
                {
                    "id": "procedure-incident-flow",
                    "query": "Quy trinh xu ly su co ky thuat gom nhung buoc nao?",
                    "should_answer": True,
                    "expected_doc_ids": ["KT-QT-003"],
                    "expected_category": "procedure",
                },
                {
                    "id": "unknown-vendor-error",
                    "query": "Bien tan E-07 encoder parameter P191",
                    "should_answer": False,
                    "expected_doc_ids": [],
                    "expected_category": "vendor_document",
                },
            ],
        )


def process_sources(
    root: Path,
    converter: MinerUConverter | None = None,
    limit: int | None = None,
    source_paths: list[Path] | None = None,
) -> list[ManifestRecord]:
    init_workspace(root)
    converter = converter or MinerUConverter.from_env()
    db = QualityDatabase(root)
    store = ManifestStore(root)
    processed: list[ManifestRecord] = []

    for source_file in selected_source_files(root, source_paths):
        if limit is not None and len(processed) >= limit:
            break
        metadata_path = source_file.with_name(source_file.stem + ".metadata.json")
        metadata: dict[str, object] = {}
        doc_id: str | None = None
        version: str | None = None
        try:
            if not metadata_path.exists():
                raise ManifestError(f"Missing sidecar metadata: {metadata_path}")
            metadata = read_json(metadata_path)
            validate_metadata(metadata)
            doc_id = str(metadata["doc_id"])
            version = str(metadata["version"])
            queue_relative_path = processing_relative_path(source_file, metadata)
            record_processing_status(
                root,
                queue_relative_path,
                status="processing",
                step="prepare",
                detail="Preparing metadata and .Workplace input",
                metadata=metadata,
                mineru_profile=converter.profile_dict() if hasattr(converter, "profile_dict") else None,
            )

            existing = store.get(doc_id, version)
            source_hash = content_hash(source_file)
            if existing and existing.content_hash == source_hash:
                db.log_ingestion("skipped_unchanged", doc_id, version)
                record_processing_status(
                    root,
                    queue_relative_path,
                    status="done",
                    step="done",
                    detail="Skipped unchanged document",
                    metadata=metadata,
                )
                move_inbox_lifecycle(root, source_file, metadata, "done")
                continue
            if existing and existing.content_hash != source_hash:
                raise ManifestError(f"Duplicate doc_id + version with different content: {doc_id} {version}")

            workplace_source = prepare_workplace_source(root, source_file, metadata)
            artifact_root = workplace_artifact_root(root, metadata)
            normalized_path = normalized_markdown_path(root, metadata)
            run_id = workflow_run_id(doc_id, version)
            source_id = f"{doc_id}_v{version}"
            append_workflow_handoff(
                root,
                artifact_root,
                make_handoff(
                    run_id=run_id,
                    step="plan",
                    status="ready",
                    source_id=source_id,
                    artifacts=[
                        artifact_record(source_file, artifact_id=f"source_{source_id}", artifact_type="raw", source_id=source_id)
                    ],
                    quality_gates={"metadata_valid": True, "single_file_run": True},
                    next_skill="mineru-source-converter",
                ),
            )
            convert_with_optional_status(
                converter,
                workplace_source,
                normalized_path,
                language=str(metadata.get("language", "vi")),
                artifact_root=artifact_root / "mineru_raw",
                status_callback=lambda step, detail: record_processing_status(
                    root,
                    queue_relative_path,
                    status="processing",
                    step=step,
                    detail=detail,
                    metadata=metadata,
                    artifact_path=str(artifact_root.resolve()),
                    mineru_profile=converter.profile_dict() if hasattr(converter, "profile_dict") else None,
                ),
            )
            record_processing_status(
                root,
                queue_relative_path,
                status="processing",
                step="mineru_convert",
                detail="MinerU/source conversion completed",
                metadata=metadata,
                artifact_path=str(artifact_root.resolve()),
                mineru_profile=converter.profile_dict() if hasattr(converter, "profile_dict") else None,
            )
            append_workflow_handoff(
                root,
                artifact_root,
                make_handoff(
                    run_id=run_id,
                    step="convert",
                    status="passed",
                    source_id=source_id,
                    artifacts=[
                        artifact_record(
                            normalized_path,
                            artifact_id=f"converted_markdown_{source_id}",
                            artifact_type="converted",
                            source_id=source_id,
                        )
                    ],
                    quality_gates={"converted_markdown_exists": normalized_path.exists()},
                    next_skill="source-output-quality-auditor",
                ),
            )
            record_processing_status(
                root,
                queue_relative_path,
                status="processing",
                step="qa",
                detail="Auditing source file against normalized Markdown",
                metadata=metadata,
                artifact_path=str(artifact_root.resolve()),
            )
            qa_report = qa_source_output(source_file, normalized_path, artifact_root / "qa_report.json")
            metadata["qa_status"] = qa_report.status
            metadata["qa_issues"] = qa_report.issues
            metadata["qa_report_path"] = qa_report.report_path
            if hasattr(converter, "profile_dict"):
                metadata["mineru_profile"] = converter.profile_dict()
            record_processing_status(
                root,
                queue_relative_path,
                status="processing" if qa_report.status != "fail" else "failed",
                step="qa",
                detail=f"QA {qa_report.status}",
                metadata=metadata,
                artifact_path=str(artifact_root.resolve()),
                qa_report_path=qa_report.report_path,
                qa_status=qa_report.status,
                qa_issues=qa_report.issues,
            )
            append_workflow_handoff(
                root,
                artifact_root,
                make_handoff(
                    run_id=run_id,
                    step="audit",
                    status="passed" if qa_report.status != "fail" else "needs_repair",
                    source_id=source_id,
                    artifacts=[
                        artifact_record(
                            Path(qa_report.report_path or artifact_root / "qa_report.json"),
                            artifact_id=f"audit_report_{source_id}",
                            artifact_type="audit",
                            source_id=source_id,
                        )
                    ],
                    quality_gates=(qa_report.metrics.get("quality_gates") or {}),
                    next_skill="ragflow-schema-indexer" if qa_report.status != "fail" else "rag-markdown-repairer",
                ),
            )
            if qa_report.status == "fail":
                raise ConversionError(f"QA failed: {', '.join(qa_report.issues)}")
            validate_normalized_markdown(normalized_path)
            record_processing_status(
                root,
                queue_relative_path,
                status="processing",
                step="rag_ready",
                detail="Building RAG-ready schema, citation, and index manifests",
                metadata=metadata,
                artifact_path=str(artifact_root.resolve()),
                qa_report_path=qa_report.report_path,
                qa_status=qa_report.status,
                qa_issues=qa_report.issues,
            )
            rag_ready = build_rag_ready_package(
                root,
                metadata=metadata,
                source_path=source_file,
                normalized_path=normalized_path,
                qa_report=qa_report.to_dict(),
            )
            metadata["rag_ready_package"] = rag_ready["package_root"]
            metadata["schema_manifest_path"] = rag_ready["schema_manifest_path"]
            metadata["citation_manifest_path"] = rag_ready["citation_manifest_path"]
            metadata["index_manifest_path"] = rag_ready["index_manifest_path"]
            append_workflow_handoff(
                root,
                artifact_root,
                make_handoff(
                    run_id=run_id,
                    step="index",
                    status="passed",
                    source_id=source_id,
                    artifacts=[
                        artifact_record(
                            Path(rag_ready["schema_manifest_path"]),
                            artifact_id=f"schema_manifest_{source_id}",
                            artifact_type="rag_ready",
                            source_id=source_id,
                        ),
                        artifact_record(
                            Path(rag_ready["citation_manifest_path"]),
                            artifact_id=f"citation_manifest_{source_id}",
                            artifact_type="rag_ready",
                            source_id=source_id,
                        ),
                        artifact_record(
                            Path(rag_ready["index_manifest_path"]),
                            artifact_id=f"index_manifest_{source_id}",
                            artifact_type="rag_ready",
                            source_id=source_id,
                        ),
                    ],
                    quality_gates={
                        "audit_passed": True,
                        "schema_created": True,
                        "citations_complete": True,
                        "chunks_indexed": rag_ready["chunk_count"] > 0,
                    },
                    next_skill="data-skill-evolution",
                ),
            )
            evolution_path = artifact_root / "evolution_report.json"
            write_json(
                evolution_path,
                {
                    "run_id": run_id,
                    "source_id": source_id,
                    "status": "no_op",
                    "reason": "No repeated workflow issue detected during this run.",
                    "created_at": utc_now(),
                },
            )
            append_workflow_handoff(
                root,
                artifact_root,
                make_handoff(
                    run_id=run_id,
                    step="evolve",
                    status="passed",
                    source_id=source_id,
                    artifacts=[
                        artifact_record(
                            evolution_path,
                            artifact_id=f"evolution_report_{source_id}",
                            artifact_type="evolution",
                            source_id=source_id,
                        )
                    ],
                    quality_gates={"evolution_recorded": True},
                    next_skill=None,
                ),
            )
            staged_path = stage_source(root, source_file, metadata)

            now = utc_now()
            record = ManifestRecord(
                doc_id=doc_id,
                title=str(metadata["title"]),
                department=str(metadata["department"]),
                category=str(metadata["category"]),
                source_type=str(metadata["source_type"]),
                language=str(metadata["language"]),
                version=version,
                status="pending_review",
                status_reason="Awaiting human review",
                effective_from=str(metadata["effective_from"]),
                effective_to=metadata.get("effective_to"),
                review_at=metadata.get("review_at"),
                owner=str(metadata["owner"]),
                approved_by=metadata.get("approved_by"),
                source_path=str(source_file.resolve()),
                normalized_path=str(normalized_path.resolve()),
                content_hash=source_hash,
                access_group=str(metadata["access_group"]),
                supersedes=metadata.get("supersedes"),
                created_at=now,
                updated_at=now,
                extra={key: value for key, value in metadata.items() if key not in ManifestRecord.__dataclass_fields__},
            )
            store.upsert(record)
            db.log_ingestion("pending_review", doc_id, version)
            record_processing_status(
                root,
                queue_relative_path,
                status="done",
                step="done",
                detail="Ready for human review",
                metadata=metadata,
                artifact_path=str(artifact_root.resolve()),
                qa_report_path=str((artifact_root / "qa_report.json").resolve()),
                qa_status=str(metadata.get("qa_status")),
                qa_issues=list(metadata.get("qa_issues") or []),
            )
            move_inbox_lifecycle(root, source_file, metadata, "done")
            cleanup_workplace_processing(root, metadata)
            processed.append(record)
        except Exception as exc:
            failure_status = "ocr_required" if isinstance(exc, OcrRequiredError) else "failed_review"
            lifecycle_status = "ocr_required" if isinstance(exc, OcrRequiredError) else "failed"
            db.log_ingestion(failure_status, doc_id, version, str(exc))
            record_processing_status(
                root,
                processing_relative_path(source_file, metadata),
                status=lifecycle_status,
                step=lifecycle_status,
                detail=str(exc),
                error=str(exc),
                metadata=metadata if metadata else None,
            )
            move_inbox_lifecycle(root, source_file, metadata, lifecycle_status)
            cleanup_workplace_processing(root, metadata)
            move_failed(root, source_file)
    return processed


def approve_record(root: Path, doc_id: str, version: str, approved_by: str) -> ManifestRecord:
    store = ManifestStore(root)
    record = store.get(doc_id, version)
    if not record:
        raise PipelineError(f"Manifest record not found: {doc_id} {version}")
    validate_record_for_approval(record)

    archived = archive_previous_active(store, record)
    record.status = "active"
    record.status_reason = None
    record.approved_by = approved_by
    if archived:
        record.supersedes = f"{archived[-1].doc_id}_v{archived[-1].version}"
    record.updated_at = utc_now()
    store.replace_many([*archived, record])
    QualityDatabase(root).log_ingestion("active", doc_id, version)
    rebuild_indexes(root)
    return record


def retire_record(root: Path, doc_id: str, version: str, reason: str) -> ManifestRecord:
    store = ManifestStore(root)
    record = store.get(doc_id, version)
    if not record:
        raise PipelineError(f"Manifest record not found: {doc_id} {version}")
    record.status = "retired"
    record.status_reason = reason
    record.effective_to = record.effective_to or utc_now()[:10]
    record.updated_at = utc_now()
    store.upsert(record)
    QualityDatabase(root).log_ingestion("retired", doc_id, version, reason)
    rebuild_indexes(root)
    return record


def reject_record(root: Path, doc_id: str, version: str, reason: str) -> ManifestRecord:
    store = ManifestStore(root)
    record = store.get(doc_id, version)
    if not record:
        raise PipelineError(f"Manifest record not found: {doc_id} {version}")
    if record.status not in {"pending_review", "normalized", "staging"}:
        raise PipelineError(f"Only non-active review records can be rejected; current status is {record.status}")
    record.status = "failed_review"
    record.status_reason = reason
    record.updated_at = utc_now()
    store.upsert(record)
    QualityDatabase(root).log_ingestion("failed_review", doc_id, version, reason)
    return record


def rebuild_indexes(root: Path) -> None:
    store = ManifestStore(root)
    records = store.load()
    active = latest_active_records(records)
    archive = store.by_status({"archived", "retired"})
    LocalRagIndex(root).rebuild(active, archive)


def stage_source(root: Path, source_file: Path, metadata: dict[str, object]) -> Path:
    filename = f"{metadata['doc_id']}_v{metadata['version']}{source_file.suffix.lower()}"
    staged = root / "staging" / str(metadata["department"]) / str(metadata["category"]) / safe_filename(filename)
    copy_file(source_file, staged)
    return staged


def prepare_workplace_source(root: Path, source_file: Path, metadata: dict[str, object]) -> Path:
    work_dir = workplace_processing_root(root, metadata)
    work_dir.mkdir(parents=True, exist_ok=True)
    write_json(work_dir / "metadata.json", metadata)
    target = work_dir / "input" / safe_filename(source_file.name)
    copy_file(source_file, target)
    return target


def workplace_processing_root(root: Path, metadata: dict[str, object]) -> Path:
    return root / ".Workplace" / "processing" / str(metadata["category"]) / safe_filename(
        f"{metadata['doc_id']}_v{metadata['version']}"
    )


def workplace_artifact_root(root: Path, metadata: dict[str, object]) -> Path:
    artifact_root = root / ".Workplace" / "artifacts" / str(metadata["category"]) / safe_filename(
        f"{metadata['doc_id']}_v{metadata['version']}"
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    return artifact_root


def cleanup_workplace_processing(root: Path, metadata: dict[str, object]) -> None:
    if not metadata.get("doc_id") or not metadata.get("version") or not metadata.get("category"):
        return
    processing_root = workplace_processing_root(root, metadata)
    if processing_root.exists():
        shutil.rmtree(processing_root)


def normalized_markdown_path(root: Path, metadata: dict[str, object]) -> Path:
    filename = safe_filename(f"{metadata['doc_id']}_v{metadata['version']}.md")
    return root / "normalized" / str(metadata["department"]) / str(metadata["category"]) / filename


def convert_with_optional_status(
    converter: object,
    source_path: Path,
    output_md: Path,
    *,
    language: str,
    artifact_root: Path,
    status_callback,
) -> Path | None:
    convert = getattr(converter, "convert")
    signature = inspect.signature(convert)
    accepts_status = "status_callback" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    kwargs = {
        "language": language,
        "artifact_root": artifact_root,
    }
    if accepts_status:
        kwargs["status_callback"] = status_callback
    return convert(source_path, output_md, **kwargs)


def processing_relative_path(source_file: Path, metadata: dict[str, object]) -> str:
    for key in ("inbox_relative_path", "original_inbox_relative_path"):
        value = metadata.get(key)
        if value:
            return str(value).replace("\\", "/").strip().lstrip("/")

    category = str(metadata.get("category") or source_file.parent.name or "procedure")
    if category not in ALLOWED_CATEGORIES["technical"]:
        category = "procedure"
    return f"{category}/{source_file.name}"


def validate_normalized_markdown(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if len(text) < 20:
        raise ConversionError(f"Normalized Markdown is empty or too short: {path}")


def iter_source_files(source_root: Path) -> list[Path]:
    if not source_root.exists():
        return []
    files = []
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.endswith(".metadata.json"):
            continue
        if path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def selected_source_files(root: Path, source_paths: list[Path] | None = None) -> list[Path]:
    if not source_paths:
        return iter_source_files(root / "source")
    source_root = (root / "source").resolve()
    selected: list[Path] = []
    for raw_path in source_paths:
        path = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = path.resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise PipelineError(f"Source path is outside workspace source/: {resolved}") from exc
        if not resolved.exists():
            raise PipelineError(f"Source path does not exist: {resolved}")
        if resolved.name.endswith(".metadata.json"):
            continue
        if resolved.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            raise PipelineError(f"Unsupported source suffix: {resolved.suffix}")
        selected.append(resolved)
    return sorted(dict.fromkeys(selected))


def move_failed(root: Path, source_file: Path) -> None:
    if not source_file.exists():
        return
    failed_path = root / "failed" / source_file.name
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    if failed_path.exists():
        failed_path = root / "failed" / f"{source_file.stem}-{utc_now().replace(':', '-')}{source_file.suffix}"
    metadata_path = source_file.with_name(source_file.stem + ".metadata.json")
    shutil.move(str(source_file), failed_path)
    if metadata_path.exists():
        metadata_failed = failed_path.with_name(failed_path.stem + ".metadata.json")
        shutil.move(str(metadata_path), metadata_failed)


def move_inbox_lifecycle(root: Path, source_file: Path, metadata: dict[str, object], status: str) -> Path | None:
    if status not in {"done", "failed", "ocr_required"}:
        raise PipelineError(f"Unsupported inbox lifecycle status: {status}")
    inbox_file = find_inbox_file_for_source(root, source_file, metadata)
    if not inbox_file or not inbox_file.exists():
        return None

    inbox_root = root / "inbox"
    try:
        relative_path = inbox_file.resolve().relative_to(inbox_root.resolve())
    except ValueError:
        return None
    parts = list(relative_path.parts)
    if len(parts) >= 2 and parts[1] == status:
        return inbox_file

    categories = ALLOWED_CATEGORIES["technical"]
    category = str(metadata.get("category") or "").strip()
    if category not in categories:
        category = parts[0] if parts and parts[0] in categories else "procedure"

    if parts and parts[0] in categories:
        tail = parts[1:]
    else:
        tail = parts
    if not tail:
        tail = [inbox_file.name]

    target = compact_lifecycle_target(inbox_root / category / status / Path(*tail), inbox_file, category, status, root)
    if inbox_file.resolve() == target.resolve():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            from .intake import unique_path

            target = unique_path(target)

        metadata_sidecar = inbox_file.with_name(inbox_file.stem + ".metadata.json")
        shutil.move(str(inbox_file), str(target))
        if metadata_sidecar.exists():
            target_sidecar = target.with_name(target.stem + ".metadata.json")
            if target_sidecar.exists():
                from .intake import unique_path

                target_sidecar = unique_path(target_sidecar)
            shutil.move(str(metadata_sidecar), str(target_sidecar))
    except OSError:
        target = compact_lifecycle_target(None, inbox_file, category, status, root)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                from .intake import unique_path

                target = unique_path(target)
            shutil.move(str(inbox_file), str(target))
        except OSError:
            return None
    return target


def compact_lifecycle_target(
    target: Path | None,
    inbox_file: Path,
    category: str,
    status: str,
    root: Path,
) -> Path:
    if target is not None and len(str(target)) < 240:
        return target
    digest = content_hash(inbox_file)[:8] if inbox_file.exists() else utc_now().replace(":", "-")
    filename = safe_filename(f"{inbox_file.stem}-{digest}{inbox_file.suffix.lower()}")
    return root / "inbox" / category / status / filename


def find_inbox_file_for_source(root: Path, source_file: Path, metadata: dict[str, object]) -> Path | None:
    inbox_root = root / "inbox"
    for key in ("inbox_path", "original_inbox_path"):
        value = metadata.get(key)
        if value:
            candidate = Path(str(value))
            if candidate.exists():
                return candidate

    relative_value = metadata.get("inbox_relative_path")
    if relative_value:
        candidate = inbox_root / Path(str(relative_value))
        if candidate.exists():
            return candidate

    report_path = root / "manifest" / "inbox_prepare_report.json"
    if report_path.exists():
        try:
            report = read_json(report_path)
            source_resolved = str(source_file.resolve()).casefold()
            for entry in report.get("prepared", []):
                if str(Path(str(entry.get("source_path", ""))).resolve()).casefold() != source_resolved:
                    continue
                candidate = Path(str(entry.get("inbox_path", "")))
                if candidate.exists():
                    return candidate
                relative = entry.get("metadata", {}).get("inbox_relative_path")
                if relative:
                    candidate = inbox_root / Path(str(relative))
                    if candidate.exists():
                        return candidate
        except Exception:
            return None

    return None


def manifest_summary(root: Path) -> list[dict[str, str | None]]:
    return [
        {
            "doc_id": record.doc_id,
            "version": record.version,
            "status": record.status,
            "category": record.category,
            "title": record.title,
            "approved_by": record.approved_by,
            "status_reason": record.status_reason,
        }
        for record in ManifestStore(root).load()
    ]
