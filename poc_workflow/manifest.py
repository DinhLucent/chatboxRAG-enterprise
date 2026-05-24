from __future__ import annotations

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
        if record_family_key(record) == new_family and record.status == "active" and record.version != new_record.version:
            if version_key(record.version) >= version_key(new_record.version):
                raise ManifestError(
                    f"New version {new_record.version} must be newer than active version {record.version}"
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
        if current is None or version_key(record.version) > version_key(current.version):
            latest[key] = record
    return sorted(latest.values(), key=lambda record: (record.doc_id, version_key(record.version)))


def record_family_key(record: ManifestRecord) -> str:
    family = record.extra.get("canonical_doc_id") or record.extra.get("document_family_id") or record.doc_id
    return f"{record.department}/{record.category}/{family}"
