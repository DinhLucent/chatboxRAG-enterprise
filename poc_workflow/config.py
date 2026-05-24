from __future__ import annotations

from pathlib import Path

ALLOWED_DEPARTMENTS = {"technical"}

ALLOWED_CATEGORIES = {
    "technical": {
        "procedure",
        "vendor_document",
        "form_checklist",
        "faq_troubleshooting",
    }
}

ALLOWED_STATUSES = {
    "new",
    "staging",
    "normalized",
    "pending_review",
    "active",
    "archived",
    "retired",
    "failed_review",
}

ACTIVE_DATASET = "technical_active"
ARCHIVE_DATASET = "technical_archive"

DEFAULT_DIRS = [
    ".Workplace",
    ".Workplace/processing",
    ".Workplace/artifacts",
    "inbox",
    "source",
    "staging",
    "normalized",
    "manifest",
    "archive",
    "failed",
    "ragflow_index",
    "data",
    "eval",
]

SUPPORTED_SOURCE_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
}

REQUIRED_METADATA_FIELDS = {
    "doc_id",
    "title",
    "department",
    "category",
    "source_type",
    "language",
    "version",
    "effective_from",
    "owner",
    "access_group",
}

REQUIRED_APPROVAL_FIELDS = REQUIRED_METADATA_FIELDS | {
    "source_path",
    "normalized_path",
    "content_hash",
}

VALID_FEEDBACK = {
    "correct",
    "wrong",
    "missing_source",
    "missing_answer",
    "wrong_source",
    "no_answer",
    "unclear",
}


def workspace_path(root: Path, *parts: str) -> Path:
    return root.joinpath(*parts)
