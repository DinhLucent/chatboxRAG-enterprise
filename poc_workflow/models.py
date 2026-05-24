from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ManifestRecord:
    doc_id: str
    title: str
    department: str
    category: str
    source_type: str
    language: str
    version: str
    status: str
    effective_from: str
    owner: str
    access_group: str
    source_path: str
    normalized_path: str
    content_hash: str
    status_reason: str | None = None
    effective_to: str | None = None
    review_at: str | None = None
    approved_by: str | None = None
    supersedes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.doc_id}::{self.version}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["extra"]:
            data.pop("extra")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ManifestRecord":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        payload = {key: value for key, value in data.items() if key in known}
        extra = {key: value for key, value in data.items() if key not in known}
        payload.setdefault("extra", extra)
        return cls(**payload)

