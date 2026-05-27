from __future__ import annotations

import base64
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ALLOWED_CATEGORIES, SUPPORTED_SOURCE_SUFFIXES
from .manifest import ManifestStore
from .utils import content_hash, read_json, safe_filename, write_json


CATEGORY_PREFIX = {
    "procedure": "KT-QT",
    "vendor_document": "KT-HANG",
    "form_checklist": "KT-BM",
    "faq_troubleshooting": "KT-FAQ",
}

SOURCE_TYPE_BY_CATEGORY = {
    "procedure": "internal_procedure",
    "vendor_document": "vendor_document",
    "form_checklist": "form",
    "faq_troubleshooting": "faq",
}

LIFECYCLE_FOLDERS = {"done", "failed", "ocr_required"}


def prepare_inbox(root: Path, dry_run: bool = False) -> dict[str, Any]:
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    source_root = root / "source"
    used_doc_ids = collect_used_doc_ids(root)
    prepared: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for file_path in iter_inbox_files(inbox, include_lifecycle=False):
        try:
            draft = build_metadata_draft(root, file_path, used_doc_ids)
            used_doc_ids.add(draft["doc_id"])
            target_dir = source_root / draft["department"] / draft["category"]
            target_file = target_dir / safe_filename(f"{draft['doc_id']}_v{draft['version']}{file_path.suffix.lower()}")
            target_metadata = target_file.with_name(target_file.stem + ".metadata.json")

            if target_file.exists() and content_hash(target_file) == content_hash(file_path):
                skipped.append({"path": str(file_path), "reason": "same file already exists in source"})
                continue
            if target_file.exists() and content_hash(target_file) != content_hash(file_path):
                target_file = target_dir / safe_filename(
                    f"{draft['doc_id']}_v{draft['version']}_{content_hash(file_path)[:8]}{file_path.suffix.lower()}"
                )
                target_metadata = target_file.with_name(target_file.stem + ".metadata.json")

            result = {
                "inbox_path": str(file_path.resolve()),
                "source_path": str(target_file.resolve()),
                "metadata_path": str(target_metadata.resolve()),
                "metadata": draft,
            }
            if not dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, target_file)
                write_json(target_metadata, draft)
            prepared.append(result)
        except Exception as exc:
            skipped.append({"path": str(file_path), "reason": str(exc)})

    report = {
        "prepared_count": len(prepared),
        "skipped_count": len(skipped),
        "prepared": prepared,
        "skipped": skipped,
        "dry_run": dry_run,
    }
    if not dry_run:
        write_json(root / "manifest" / "inbox_prepare_report.json", report)
    return report


def list_inbox(root: Path, *, include_lifecycle: bool = False) -> list[dict[str, Any]]:
    inbox = root / "inbox"
    items: list[dict[str, Any]] = []
    for path in iter_inbox_files(inbox, include_lifecycle=include_lifecycle):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        items.append(
            {
                "name": path.name,
                "path": str(path.resolve()),
                "relative_path": path.relative_to(inbox).as_posix(),
                "category_hint": infer_category(path),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "has_sidecar_metadata": path.with_name(path.stem + ".metadata.json").exists(),
            }
        )
    return items


def save_upload_to_inbox(
    root: Path,
    filename: str,
    content_base64: str,
    category: str | None = None,
) -> dict[str, Any]:
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(Path(filename).name)
    if not safe_name:
        raise ValueError("filename is required")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_SOURCE_SUFFIXES:
        raise ValueError(f"Unsupported file suffix: {suffix}")
    if category:
        if category not in ALLOWED_CATEGORIES["technical"]:
            raise ValueError(f"Unsupported inbox category: {category}")
        target_dir = inbox / category
    else:
        target_dir = inbox
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / safe_name)
    payload = content_base64.split(",", 1)[-1].strip()
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("content_base64 must be valid base64") from exc
    target.write_bytes(data)
    return {
        "name": target.name,
        "path": str(target.resolve()),
        "relative_path": target.relative_to(inbox).as_posix(),
        "category_hint": infer_category(target),
        "size_bytes": len(data),
    }


def iter_inbox_files(inbox: Path, include_lifecycle: bool = False) -> list[Path]:
    files: list[Path] = []
    if not inbox.exists():
        return files
    for path in inbox.rglob("*"):
        if not path.is_file():
            continue
        if path.name.lower() in {"readme.md", "classification_standard.md", ".gitkeep"}:
            continue
        if path.name.endswith(".metadata.json"):
            continue
        if path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            continue
        if not include_lifecycle and _has_lifecycle_folder(path.relative_to(inbox)):
            continue
        files.append(path)
    return sorted(files)


def _has_lifecycle_folder(relative_path: Path) -> bool:
    return any(part in LIFECYCLE_FOLDERS for part in relative_path.parts)


def list_ocr_required(root: Path, category: str | None = None) -> list[dict[str, Any]]:
    inbox = root / "inbox"
    items: list[dict[str, Any]] = []
    categories = ALLOWED_CATEGORIES["technical"]
    for file_path in iter_inbox_files(inbox, include_lifecycle=True):
        try:
            relative_path = file_path.relative_to(inbox)
        except ValueError:
            continue
        parts = relative_path.parts
        if len(parts) < 2 or parts[1] != "ocr_required":
            continue
        file_category = parts[0] if parts[0] in categories else infer_category(file_path)
        if category and file_category != category:
            continue
        stat = file_path.stat()
        items.append(
            {
                "path": str(file_path.resolve()),
                "relative_path": relative_path.as_posix(),
                "category": file_category,
                "file_name": file_path.name,
                "size_bytes": stat.st_size,
            }
        )
    return sorted(items, key=lambda item: (item["category"] != "procedure", item["size_bytes"], item["relative_path"]))


def requeue_ocr_required(
    root: Path,
    limit: int = 1,
    category: str | None = "procedure",
    dry_run: bool = False,
    max_safe_limit: int = 5,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if limit > max_safe_limit:
        raise ValueError(f"limit must be <= {max_safe_limit} for OCR-required requeue batches")
    if category and category not in ALLOWED_CATEGORIES["technical"]:
        raise ValueError(f"Unsupported category: {category}")

    inbox = root / "inbox"
    selected = list_ocr_required(root, category=category)[:limit]
    moved: list[dict[str, Any]] = []
    for item in selected:
        source = Path(str(item["path"]))
        relative_path = source.relative_to(inbox)
        parts = list(relative_path.parts)
        parts.pop(1)
        target = unique_path(inbox / Path(*parts))
        result = {
            **item,
            "target_relative_path": target.relative_to(inbox).as_posix(),
            "target_path": str(target.resolve()),
        }
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            metadata_source = source.with_name(source.stem + ".metadata.json")
            if metadata_source.exists():
                metadata_target = unique_path(target.with_name(target.stem + ".metadata.json"))
                shutil.move(str(metadata_source), str(metadata_target))
        moved.append(result)

    return {
        "selected_count": len(selected),
        "dry_run": dry_run,
        "category": category,
        "limit": limit,
        "moved": moved,
    }


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def build_metadata_draft(root: Path, file_path: Path, used_doc_ids: set[str]) -> dict[str, Any]:
    sidecar = file_path.with_name(file_path.stem + ".metadata.json")
    if sidecar.exists():
        metadata = read_json(sidecar)
    else:
        metadata = {}

    category = str(metadata.get("category") or infer_category(file_path))
    department = str(metadata.get("department") or "technical")
    if category not in ALLOWED_CATEGORIES.get(department, set()):
        raise ValueError(f"Unsupported taxonomy: {department}/{category}")

    version = str(metadata.get("version") or infer_version(file_path) or "1.0")
    if metadata.get("doc_id"):
        doc_id = str(metadata["doc_id"])
    else:
        inferred_doc_id = infer_doc_id(file_path)
        doc_id = inferred_doc_id if inferred_doc_id and inferred_doc_id not in used_doc_ids else next_doc_id(category, used_doc_ids)
    title = str(metadata.get("title") or infer_title(file_path))
    effective_from = str(metadata.get("effective_from") or datetime.now(timezone.utc).date().isoformat())
    review_at = metadata.get("review_at") or (datetime.now(timezone.utc).date() + timedelta(days=365)).isoformat()

    draft = {
        "doc_id": doc_id,
        "title": title,
        "department": department,
        "category": category,
        "source_type": metadata.get("source_type") or SOURCE_TYPE_BY_CATEGORY[category],
        "language": metadata.get("language") or infer_language(file_path),
        "version": version,
        "effective_from": effective_from,
        "review_at": review_at,
        "owner": metadata.get("owner") or "Phong Ky thuat",
        "access_group": metadata.get("access_group") or "technical",
        "status_reason": "Metadata drafted from inbox; requires human review after conversion.",
        "inbox_relative_path": file_path.relative_to(root / "inbox").as_posix(),
        "inbox_path": str(file_path.resolve()),
    }
    for key in ["effective_to", "approved_by", "supersedes"]:
        if metadata.get(key):
            draft[key] = metadata[key]
    return draft


def collect_used_doc_ids(root: Path) -> set[str]:
    ids = {record.doc_id for record in ManifestStore(root).load()}
    for metadata_path in (root / "source").rglob("*.metadata.json"):
        try:
            data = read_json(metadata_path)
            if data.get("doc_id"):
                ids.add(str(data["doc_id"]))
        except Exception:
            continue
    return ids


def infer_category(file_path: Path) -> str:
    haystack = " ".join(part.lower() for part in [*file_path.parts, file_path.stem])
    if any(term in haystack for term in ["vendor", "hang", "hãng", "manual", "datasheet", "catalog", "catalogue"]):
        return "vendor_document"
    if any(term in haystack for term in ["form", "bieu-mau", "bieu mau", "biểu mẫu", "checklist", "mau", "mẫu"]):
        return "form_checklist"
    if any(term in haystack for term in ["faq", "troubleshoot", "troubleshooting", "loi", "lỗi", "su-co", "sự cố"]):
        return "faq_troubleshooting"
    return "procedure"


def infer_doc_id(file_path: Path) -> str | None:
    match = re.search(r"([A-Za-z]{2,5}-[A-Za-z]{2,8}-\d{3,})", file_path.stem)
    return match.group(1).upper() if match else None


def infer_version(file_path: Path) -> str | None:
    match = re.search(r"(?:^|[_\-\s])v(\d+(?:\.\d+)*)", file_path.stem, flags=re.IGNORECASE)
    return match.group(1) if match else None


def infer_title(file_path: Path) -> str:
    title = re.sub(r"[_\-]+", " ", file_path.stem)
    title = re.sub(r"\bv\d+(?:\.\d+)*\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    return title or file_path.stem


def infer_language(file_path: Path) -> str:
    text = " ".join(part.lower() for part in file_path.parts)
    if re.search(r"(^|[_\-\s])(en|english)([_\-\s]|$)", text):
        return "en"
    return "vi"


def next_doc_id(category: str, used_doc_ids: set[str]) -> str:
    prefix = CATEGORY_PREFIX[category]
    numbers = []
    for doc_id in used_doc_ids:
        if not doc_id.startswith(prefix + "-"):
            continue
        suffix = doc_id.removeprefix(prefix + "-")
        if suffix.isdigit():
            numbers.append(int(suffix))
    number = max(numbers, default=0) + 1
    candidate = f"{prefix}-{number:03d}"
    while candidate in used_doc_ids:
        number += 1
        candidate = f"{prefix}-{number:03d}"
    return candidate
