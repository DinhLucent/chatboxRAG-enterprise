from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .intake import unique_path
from .upload_processing import business_document_identity
from .utils import content_hash, copy_file, utc_now, write_json


PHUONG_DONG_FOLDER_NAME = "Quy Trình Phương Đông"
TECHNICAL_FOLDER_PREFIX = "12"
PROCEDURE_SOURCE_SUFFIXES = {".pdf", ".xlsx", ".xls", ".docx", ".doc"}

DEPARTMENT_BY_FOLDER_PREFIX = {
    "01": "general",
    "02": "internal_control",
    "03": "administration",
    "04": "human_resources",
    "05": "accounting",
    "06": "sales",
    "07": "tender_legal",
    "08": "marcom",
    "09": "regulatory_affairs",
    "10": "customer_service",
    "11": "app",
    "12": "technical",
    "13": "procurement_import_export",
    "14": "it",
    "15": "marketing",
    "16": "governance",
    "17": "warehouse_gdp",
}


def resolve_phuong_dong_source_root(root: Path, source_root: Path | None = None) -> Path:
    if source_root:
        return source_root.resolve()
    default = root / "root_source" / PHUONG_DONG_FOLDER_NAME
    if default.exists():
        return default.resolve()
    root_source = root / "root_source"
    if root_source.exists():
        for candidate in root_source.iterdir():
            if candidate.is_dir() and candidate.name.startswith("Quy"):
                return candidate.resolve()
    raise FileNotFoundError(f"Phuong Dong source root not found under {root_source}")


def inventory_phuong_dong_procedures(
    root: Path,
    *,
    source_root: Path | None = None,
    include_technical: bool = False,
    write_report: bool = True,
) -> dict[str, Any]:
    source = resolve_phuong_dong_source_root(root, source_root)
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for path in _iter_source_files(source):
        relative = _relative_to_source(path, source)
        parts = relative.parts
        top_folder = parts[0] if parts else ""
        folder_prefix = _folder_prefix(top_folder)
        department = DEPARTMENT_BY_FOLDER_PREFIX.get(folder_prefix or "", "general")
        if not include_technical and folder_prefix == TECHNICAL_FOLDER_PREFIX:
            skipped.append(
                {
                    "reason": "technical_excluded",
                    "source_path": str(_normal_path(path)),
                    "relative_path": relative.as_posix(),
                    "department": department,
                }
            )
            continue
        identity = business_document_identity(path.name)
        items.append(
            {
                "source_path": str(_normal_path(path)),
                "relative_path": relative.as_posix(),
                "file_name": path.name,
                "suffix": path.suffix.lower(),
                "top_folder": top_folder,
                "department": department,
                "category": "procedure",
                "canonical_business_code": identity["code"],
                "business_document_code_detected": identity["code_detected"],
                "source_revision": identity["revision"],
                "business_key": f"{department}/{identity['business_key']}",
                "size_bytes": path.stat().st_size,
            }
        )

    report = {
        "schema_version": "phuong_dong_source_inventory_v1",
        "source_root": str(source),
        "include_technical": include_technical,
        "discovered_count": len(items),
        "skipped_count": len(skipped),
        "skipped_technical_count": sum(1 for item in skipped if item["reason"] == "technical_excluded"),
        "by_department": _count_by(items, "department"),
        "by_suffix": _count_by(items, "suffix"),
        "items": sorted(items, key=lambda item: (item["department"], item["relative_path"])),
        "skipped": skipped,
        "created_at": utc_now(),
    }
    if write_report:
        write_json(root / "manifest" / "all_departments_source_inventory.json", report)
    return report


def enqueue_phuong_dong_procedures(
    root: Path,
    *,
    source_root: Path | None = None,
    include_technical: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    inventory = inventory_phuong_dong_procedures(
        root,
        source_root=source_root,
        include_technical=include_technical,
        write_report=not dry_run,
    )
    copied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    selected = inventory["items"][:limit] if limit else inventory["items"]
    inbox = root / "inbox" / "procedure"

    for item in selected:
        source = _long_path(Path(item["source_path"]))
        source_name = _normal_path(source).name
        target_dir = inbox / str(item["department"])
        target = target_dir / source_name
        existing = _same_content_target(target_dir, source_name, source)
        if existing:
            skipped.append(
                {
                    **item,
                    "reason": "same_file_already_in_inbox",
                    "target_path": str(existing),
                    "target_relative_path": existing.relative_to(root / "inbox").as_posix(),
                }
            )
            continue
        if target.exists():
            target = unique_path(target)
        result = {
            **item,
            "target_path": str(target.resolve()),
            "target_relative_path": target.relative_to(root / "inbox").as_posix(),
            "dry_run": dry_run,
        }
        if not dry_run:
            copy_file(source, target)
            write_json(target.with_name(target.stem + ".metadata.json"), _sidecar_metadata(item, target))
        copied.append(result)

    report = {
        "schema_version": "phuong_dong_enqueue_v1",
        "source_root": inventory["source_root"],
        "include_technical": include_technical,
        "dry_run": dry_run,
        "limit": limit,
        "inventory_count": inventory["discovered_count"],
        "selected_count": len(selected),
        "copied_count": len(copied),
        "skipped_count": len(skipped),
        "copied": copied,
        "skipped": skipped,
        "created_at": utc_now(),
    }
    if not dry_run:
        write_json(root / "manifest" / "all_departments_enqueue_report.json", report)
    return report


def _iter_source_files(source_root: Path) -> list[Path]:
    root = _long_path(source_root)
    return sorted(
        [
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in PROCEDURE_SOURCE_SUFFIXES
        ],
        key=lambda path: _relative_to_source(path, source_root).as_posix(),
    )


def _folder_prefix(folder_name: str) -> str | None:
    match = re.match(r"^\s*(\d{1,2})\s*\.?", folder_name)
    return f"{int(match.group(1)):02d}" if match else None


def _relative_to_source(path: Path, source_root: Path) -> Path:
    return _normal_path(path).relative_to(source_root.resolve())


def _normal_path(path: Path) -> Path:
    value = str(path)
    if value.startswith("\\\\?\\"):
        return Path(value[4:])
    return path


def _long_path(path: Path) -> Path:
    resolved = path.resolve()
    if os.name != "nt":
        return resolved
    value = str(resolved)
    if value.startswith("\\\\?\\"):
        return resolved
    return Path("\\\\?\\" + value)


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _same_content_target(target_dir: Path, file_name: str, source: Path) -> Path | None:
    if not target_dir.exists():
        return None
    source_hash = content_hash(source)
    for candidate in target_dir.glob(f"{Path(file_name).stem}*{Path(file_name).suffix}"):
        if candidate.is_file() and content_hash(candidate) == source_hash:
            return candidate.resolve()
    return None


def _sidecar_metadata(item: dict[str, Any], target: Path) -> dict[str, Any]:
    return {
        "schema_version": "phuong_dong_inbox_sidecar_v1",
        "department": item["department"],
        "category": "procedure",
        "source_type": "internal_procedure",
        "language": "vi",
        "canonical_business_code": item["canonical_business_code"],
        "business_document_code_detected": item["business_document_code_detected"],
        "source_revision": item["source_revision"],
        "business_key": item["business_key"],
        "original_source_path": item["source_path"],
        "original_relative_path": item["relative_path"],
        "inbox_path": str(target.resolve()),
        "ingest_policy": "primary_source_only",
        "raw_conversion_policy": "mineru_only_no_fallback",
        "created_at": utc_now(),
    }
