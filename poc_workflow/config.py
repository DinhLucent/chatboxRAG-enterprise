from __future__ import annotations

from pathlib import Path

COMMON_CATEGORIES = {
    "procedure",
    "vendor_document",
    "form_checklist",
    "faq_troubleshooting",
}

DEPARTMENT_DISPLAY_NAMES = {
    "general": "Tai lieu chung",
    "internal_control": "Phong Kiem soat noi bo",
    "administration": "Phong Hanh chinh",
    "human_resources": "Phong Nhan su",
    "accounting": "Phong Ke toan",
    "sales": "Phong Ban hang",
    "tender_legal": "Phong Thau Phap che",
    "marcom": "Phong Marcom",
    "regulatory_affairs": "Phong RA",
    "customer_service": "Phong Dich vu khach hang",
    "app": "Phong APP",
    "technical": "Phong Ky thuat",
    "procurement_import_export": "Phong Xuat nhap khau Mua hang",
    "it": "Phong IT",
    "marketing": "Phong Marketing",
    "governance": "Phong Quan tri",
    "warehouse_gdp": "Kho GDP",
}

ALLOWED_DEPARTMENTS = set(DEPARTMENT_DISPLAY_NAMES)

ALLOWED_CATEGORIES = {department: set(COMMON_CATEGORIES) for department in ALLOWED_DEPARTMENTS}

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
    "root_source",
    "converted_raw",
    "inbox",
    "source",
    "staging",
    "normalized",
    "indexes",
    "review",
    "manifest",
    "archive",
    "failed",
    "rag_ready",
    "ragflow_index",
    "data",
    "eval",
]

SUPPORTED_SOURCE_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".pdf",
    ".doc",
    ".docx",
    ".pptx",
    ".xls",
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
