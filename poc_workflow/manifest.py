from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import (
    ALLOWED_CATEGORIES,
    ALLOWED_DEPARTMENTS,
    ALLOWED_STATUSES,
    REQUIRED_APPROVAL_FIELDS,
    REQUIRED_METADATA_FIELDS,
)
from .models import ManifestRecord
from .utils import utc_now, version_key, write_json


class ManifestError(ValueError):
    pass


class ManifestStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "manifest" / "records.json"

    def load(self) -> list[ManifestRecord]:
        if not self.path.exists():
            return []
        import json

        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [ManifestRecord.from_dict(item) for item in data]

    def save(self, records: list[ManifestRecord]) -> None:
        records = sorted(records, key=lambda record: (record.doc_id, version_key(record.version)))
        write_json(self.path, [record.to_dict() for record in records])

    def get(self, doc_id: str, version: str) -> ManifestRecord | None:
        for record in self.load():
            if record.doc_id == doc_id and record.version == version:
                return record
        return None

    def upsert(self, record: ManifestRecord) -> None:
        records = self.load()
        for index, existing in enumerate(records):
            if existing.key == record.key:
                records[index] = record
                self.save(records)
                return
        records.append(record)
        self.save(records)

    def replace_many(self, updated: list[ManifestRecord]) -> None:
        by_key = {record.key: record for record in updated}
        records = []
        seen = set()
        for record in self.load():
            if record.key in by_key:
                records.append(by_key[record.key])
                seen.add(record.key)
            else:
                records.append(record)
        for record in updated:
            if record.key not in seen:
                records.append(record)
        self.save(records)

    def active_for_doc(self, doc_id: str) -> ManifestRecord | None:
        active = [record for record in self.load() if record.doc_id == doc_id and record.status == "active"]
        if not active:
            return None
        return sorted(active, key=lambda record: version_key(record.version))[-1]

    def by_status(self, statuses: set[str]) -> list[ManifestRecord]:
        return [record for record in self.load() if record.status in statuses]


def validate_metadata(metadata: dict[str, object]) -> None:
    missing = sorted(field for field in REQUIRED_METADATA_FIELDS if not metadata.get(field))
    if missing:
        raise ManifestError(f"Missing required metadata fields: {', '.join(missing)}")

    department = str(metadata["department"])
    category = str(metadata["category"])
    if department not in ALLOWED_DEPARTMENTS:
        raise ManifestError(f"Unsupported department: {department}")
    if category not in ALLOWED_CATEGORIES[department]:
        raise ManifestError(f"Unsupported category for {department}: {category}")


def validate_record_for_approval(record: ManifestRecord) -> None:
    data = record.to_dict()
    missing = sorted(field for field in REQUIRED_APPROVAL_FIELDS if not data.get(field))
    if missing:
        raise ManifestError(f"Record cannot be approved; missing: {', '.join(missing)}")
    if record.status != "pending_review":
        raise ManifestError(f"Only pending_review records can be approved; current status is {record.status}")
    normalized_path = Path(record.normalized_path)
    if not normalized_path.exists():
        raise ManifestError(f"Normalized file does not exist: {normalized_path}")
    if len(normalized_path.read_text(encoding="utf-8", errors="ignore").strip()) < 20:
        raise ManifestError("Normalized Markdown is too short for approval")


def ensure_status(status: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise ManifestError(f"Unsupported status: {status}")


def archive_previous_active(
    store: ManifestStore,
    new_record: ManifestRecord,
    reason: str | None = None,
) -> list[ManifestRecord]:
    records = store.load()
    updated: list[ManifestRecord] = []
    new_family = record_family_key(new_record)
    for record in records:
        if record_family_key(record) == new_family and record.status == "active" and record.key != new_record.key:
            if record_latest_key(record) >= record_latest_key(new_record):
                raise ManifestError(
                    f"New version/revision {new_record.version} must be newer than active version/revision {record.version}"
                )
            record.status = "archived"
            record.status_reason = reason or f"Replaced by {new_record.doc_id}_v{new_record.version}"
            record.effective_to = new_record.effective_from
            record.updated_at = utc_now()
            updated.append(record)
    return updated


def latest_active_records(records: list[ManifestRecord]) -> list[ManifestRecord]:
    latest: dict[str, ManifestRecord] = {}
    for record in records:
        if record.status != "active":
            continue
        key = record_family_key(record)
        current = latest.get(key)
        if current is None or (record_latest_key(record), record.key) > (record_latest_key(current), current.key):
            latest[key] = record
    return sorted(latest.values(), key=lambda record: (record.doc_id, record_latest_key(record), record.key))


def record_family_key(record: ManifestRecord) -> str:
    family = record.extra.get("canonical_doc_id") or record.extra.get("document_family_id")
    if family:
        return f"{record.department}/{family}"
    business_code = record_business_code(record)
    if business_code:
        source_role = record.extra.get("source_role")
        if source_role and record.extra.get("active_scope_id"):
            return f"{record.department}/{business_code}/{source_role}"
        return f"{record.department}/{business_code}"
    family = record.doc_id
    return f"{record.department}/{record.category}/{family}"


def record_latest_key(record: ManifestRecord) -> tuple[int, int, tuple[int, ...]]:
    revision = record_revision_number(record)
    return (1 if revision is not None else 0, revision or 0, version_key(record.version))


def record_business_code(record: ManifestRecord) -> str | None:
    hint = _compact_record_hint(record)
    match = re.search(r"\bPD\s+([A-Z]+)\s+([A-Z])\s+0*([0-9]{1,3})\b", hint)
    if match:
        return f"PD-{match.group(1)}-{match.group(2)}-{int(match.group(3)):03d}"
    match = re.search(r"\bBM\s+0*([0-9]{1,3})(?:\s+0*([0-9]{1,3}))?\b", hint)
    if match:
        if match.group(2):
            return f"BM-{int(match.group(1)):03d}.{int(match.group(2)):02d}"
        return f"BM-{int(match.group(1)):03d}"
    match = re.search(r"\bMS\s*0*([0-9]{1,3})(?:\s+0*([0-9]{1,3}))?\b", hint)
    if match:
        if match.group(2):
            return f"MS-{int(match.group(1)):03d}.{int(match.group(2)):02d}"
        return f"MS-{int(match.group(1)):03d}"
    return None


def record_revision_number(record: ManifestRecord) -> int | None:
    match = re.search(r"\bREV\s*0*([0-9]{1,3})\b", _compact_record_hint(record))
    return int(match.group(1)) if match else None


def _compact_record_hint(record: ManifestRecord) -> str:
    extra = record.extra or {}
    parts = [
        record.title,
        record.doc_id,
        extra.get("canonical_doc_id"),
        extra.get("document_family_id"),
        extra.get("inbox_relative_path"),
        record.source_path,
        record.normalized_path,
    ]
    text = " ".join(str(part) for part in parts if part)
    text = "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()
