from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent_prompt_queue import (
    generate_agent_goal_prompt,
    generate_agent_prompt,
    list_agent_prompt_templates,
    list_upload_queue,
    record_upload_workflow_event,
    update_upload_status,
)
from .auth import public_auth_status, require_operator_auth
from .chatbot import apply_feedback, ask
from .database import QualityDatabase
from .document_qa import mojibake_score
from .evaluation import latest_report, run_evaluation
from .intake import list_inbox, save_upload_to_inbox
from .llm import (
    LLMError,
    llm_presets,
    llm_runtime_status,
    redacted_llm_config,
    reset_llm_runtime_config,
    save_llm_runtime_config,
    transient_llm_config,
)
from .manifest import ManifestStore, latest_active_records
from .operations import (
    build_incident_agent_prompt,
    diagnostic_snapshot,
    maintenance_enabled,
    public_service_status,
    record_incident,
)
from .pipeline import (
    approve_record,
    init_workspace,
    manifest_summary,
    rebuild_indexes,
    reject_record,
    retire_record,
)
from .ragflow_http import (
    RAGFlowConfig,
    RAGFlowHTTPClient,
    RAGFlowHTTPError,
    bootstrap_ragflow_resources,
    sync_active_to_ragflow,
)
from .readiness import deployment_readiness
from .runtime import allowed_providers, local_fallback_enabled, provider_allowed
from .text_cleaning import clean_excerpt
from .user_chat import (
    answer_styles_payload,
    cleanup_stale_sessions,
    heartbeat_session,
    load_curated_templates,
    load_policy_pack,
    public_policy_summary,
    normalize_answer_style,
    template_exists,
    user_chat_response,
    user_session_cleanup_interval_seconds,
    welcome_cards_payload,
)
from .utils import utc_now, write_json
from .utils import read_json


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


class ChatRequest(BaseModel):
    query: str
    user_id: str | None = None
    provider: str = "auto"
    use_llm: bool = False


class FeedbackRequest(BaseModel):
    query_log_id: int
    feedback: str


class UserChatRequest(BaseModel):
    query: str
    template_id: str | None = None
    answer_style: str | None = "brief"
    session_id: str | None = None
    device_id: str | None = None
    use_llm: bool = True


class UserFeedbackRequest(BaseModel):
    query_log_id: int | None = None
    log_id: int | None = None
    feedback: str | None = None
    rating: str | None = None
    session_id: str | None = None


class UserSessionHeartbeatRequest(BaseModel):
    session_id: str | None = None
    device_id: str | None = None


class ApproveRequest(BaseModel):
    doc_id: str
    version: str
    approved_by: str


class HumanReviewRequest(BaseModel):
    doc_id: str
    version: str
    review_status: str
    reviewer: str
    checklist: dict[str, bool]
    notes: str = ""


class RejectRequest(BaseModel):
    doc_id: str
    version: str
    reason: str


class RetireRequest(BaseModel):
    doc_id: str
    version: str
    reason: str


class SyncRAGFlowRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    dataset_id: str | None = None
    delete_all: bool = False
    parse_after_upload: bool = True


class BootstrapRAGFlowRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    dataset_name: str = "technical_active"
    chat_name: str = "technical_procedure_chat"
    llm_id: str | None = None
    create_chat: bool = True


class EvaluateRequest(BaseModel):
    cases_path: str | None = None
    provider: str = "local"
    use_llm: bool = False
    latency_target_ms: int = 12_000


class UploadInboxRequest(BaseModel):
    filename: str
    content_base64: str
    category: str | None = None


class GenerateAgentPromptRequest(BaseModel):
    relative_paths: list[str]
    prompt_mode: str | None = None
    admin_request: str | None = None


class GenerateAgentGoalPromptRequest(BaseModel):
    relative_paths: list[str]
    goal_target: str | None = None
    branch: str | None = None
    verification: str | None = None
    admin_request: str | None = None


class UploadQueueStatusRequest(BaseModel):
    relative_paths: list[str]
    status: str
    error: str | None = None


class UploadWorkflowEventRequest(BaseModel):
    relative_paths: list[str]
    status: str = "processing"
    step: str
    detail: str | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None
    artifact_path: str | None = None
    qa_report_path: str | None = None
    qa_status: str | None = None
    qa_issues: list[str] | None = None
    mineru_profile: dict[str, Any] | None = None
    handoff_path: str | None = None
    checkpoint: str | None = None
    artifacts: list[dict[str, Any]] | None = None
    quality_gates: dict[str, Any] | None = None
    next_skill: str | None = None


class IncidentRequest(BaseModel):
    severity: str = "warning"
    component: str
    title: str
    detail: str
    context: dict[str, Any] | None = None


class ResolveIncidentRequest(BaseModel):
    incident_id: int
    status: str = "resolved"


class LLMConfigRequest(BaseModel):
    provider: str = "ollama"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 8


def model_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value or "") if unicodedata.category(char) != "Mn"
    )


def _compact_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", _strip_accents(value).upper()).strip()


def _document_source_hint(record: Any) -> str:
    extra = getattr(record, "extra", {}) or {}
    parts = [
        record.title,
        record.doc_id,
        extra.get("canonical_doc_id"),
        extra.get("document_family_id"),
        extra.get("inbox_relative_path"),
        record.source_path,
    ]
    return " | ".join(str(part) for part in parts if part)


def _canonical_document_key(record: Any) -> str:
    extra = getattr(record, "extra", {}) or {}
    family = extra.get("canonical_doc_id") or extra.get("document_family_id")
    if family:
        return f"{record.department}/{family}"
    hint = _compact_text(_document_source_hint(record))
    match = re.search(r"\bPD\s+([A-Z]+)\s+(?:([A-Z])\s+)?0*([0-9]{1,3})\b", hint)
    if match:
        code = "-".join(
            part for part in (match.group(1), match.group(2), f"{int(match.group(3)):03d}") if part
        )
        return f"{record.department}/PD-{code}"
    match = re.search(r"\bBM\s+0*([0-9]{1,3})(?:\s+0*([0-9]{1,3}))?\b", hint)
    if match:
        code = "-".join(
            part
            for part in (f"{int(match.group(1)):03d}", f"{int(match.group(2)):03d}" if match.group(2) else None)
            if part
        )
        return f"{record.department}/BM-{code}"
    return f"{record.department}/{record.category}/{record.doc_id}"


def _revision_number(record: Any) -> int | None:
    match = re.search(r"\bREV\s*0*([0-9]{1,3})\b", _compact_text(_document_source_hint(record)))
    return int(match.group(1)) if match else None


def _category_hint(record: Any) -> str | None:
    source = _compact_text(_document_source_hint(record))
    title = _compact_text(record.title or "")
    if re.search(r"^(BM|MS)\b", title) or re.search(
        r"\b(BIEU MAU|CHECKLIST|PHIEU|MAU |HOP DONG|PHU LUC|CONG VAN|CV )\b",
        source,
    ):
        return "form_checklist"
    if re.search(
        r"\b(MANUAL|CATALOG|DATASHEET|ANNEX|REGISTER FORM|PROFILE SHEET|COMPLIANCE CERT|CHANNEL PARTNER)\b",
        source,
    ):
        return "vendor_document"
    if re.search(r"^(PD)\b", title) or re.search(r"\b(QUY TRINH|QUY DINH|HUONG DAN|CHUONG TRINH|SO TAY)\b", source):
        return "procedure"
    return None


def _record_path(workspace: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else workspace / path


def _read_text_preview(path: Path | None, max_chars: int = 120_000) -> dict[str, Any]:
    if not path or not path.exists():
        return {"exists": False, "path": str(path) if path else None, "content": "", "truncated": False, "size_bytes": 0}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {
        "exists": True,
        "path": str(path),
        "content": content[:max_chars],
        "truncated": len(content) > max_chars,
        "size_bytes": path.stat().st_size,
    }


def _read_json_preview(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {"exists": False, "path": str(path) if path else None, "data": None}
    try:
        return {"exists": True, "path": str(path), "data": read_json(path)}
    except Exception as exc:
        return {"exists": True, "path": str(path), "data": None, "error": str(exc)}


def _source_preview_payload(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {"exists": False, "kind": "missing", "path": str(path) if path else None}
    suffix = path.suffix.lower()
    payload: dict[str, Any] = {
        "exists": True,
        "kind": _source_preview_kind(suffix),
        "path": str(path),
        "file_name": path.name,
        "suffix": suffix,
        "size_bytes": path.stat().st_size,
    }
    if suffix in {".md", ".markdown", ".txt", ".csv", ".json", ".html", ".htm", ".xml"}:
        payload["text"] = _read_text_preview(path, max_chars=80_000)
    elif suffix == ".xlsx":
        payload["excel"] = _xlsx_preview(path)
    elif suffix == ".xls":
        payload["note"] = "Legacy XLS preview is not rendered in browser; open the original source file for review."
    return payload


def _source_preview_kind(suffix: str) -> str:
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".xlsx", ".xls"}:
        return "excel"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return "image"
    if suffix in {".md", ".markdown", ".txt", ".csv", ".json", ".html", ".htm", ".xml"}:
        return "text"
    return "binary"


def _xlsx_preview(path: Path, *, max_rows: int = 40, max_cols: int = 12) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = _xlsx_shared_strings(archive)
            sheets = _xlsx_sheet_paths(archive)
            previews = []
            for sheet in sheets[:15]:
                rows = _xlsx_sheet_rows(
                    archive,
                    sheet["path"],
                    shared_strings=shared_strings,
                    max_rows=max_rows,
                    max_cols=max_cols,
                )
                previews.append({"name": sheet["name"], "rows": rows, "truncated": len(rows) >= max_rows})
            return {"sheets": previews, "sheet_count": len(sheets), "error": None}
    except Exception as exc:
        return {"sheets": [], "sheet_count": 0, "error": str(exc)}


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall(".//{*}si"):
        text = "".join(node.text or "" for node in item.findall(".//{*}t"))
        strings.append(text)
    return strings


def _xlsx_sheet_paths(archive: zipfile.ZipFile) -> list[dict[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_lookup = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels.findall(".//{*}Relationship")
    }
    sheets: list[dict[str, str]] = []
    for sheet in workbook.findall(".//{*}sheet"):
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_lookup.get(rel_id, "")
        if not target:
            continue
        clean_target = target.lstrip('/')
        sheet_path = clean_target if clean_target.startswith("xl/") else f"xl/{clean_target}"
        sheets.append({"name": sheet.attrib.get("name", "Sheet"), "path": sheet_path})
    return sheets


def _xlsx_sheet_rows(
    archive: zipfile.ZipFile,
    sheet_path: str,
    *,
    shared_strings: list[str],
    max_rows: int,
    max_cols: int,
) -> list[list[str]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall(".//{*}sheetData/{*}row"):
        values = [""] * max_cols
        has_value = False
        for cell in row.findall("{*}c"):
            col_index = _xlsx_column_index(cell.attrib.get("r", ""))
            if col_index is None or col_index >= max_cols:
                continue
            value = _xlsx_cell_value(cell, shared_strings)
            if value:
                has_value = True
            values[col_index] = value
        if has_value:
            rows.append(values)
        if len(rows) >= max_rows:
            break
    return rows


def _xlsx_column_index(cell_ref: str) -> int | None:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        return None
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{*}t")).strip()
    value_node = cell.find("{*}v")
    raw_value = value_node.text if value_node is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except Exception:
            return raw_value.strip()
    return raw_value.strip()


def _markdown_quality(content: str) -> dict[str, int]:
    return {
        "characters": len(content),
        "lines": content.count("\n") + 1 if content else 0,
        "mojibake_score": mojibake_score(content),
        "replacement_characters": content.count("\ufffd") + content.count("ï¿½"),
        "question_marks": content.count("?"),
    }


def locate_excerpt_in_markdown(content: str, excerpt: str) -> tuple[int, int, str]:
    if not excerpt or not excerpt.strip():
        return 1, 1, "approximate"
    lines = content.splitlines()
    excerpt_lines = [l.strip() for l in excerpt.splitlines() if l.strip()]
    if not excerpt_lines:
        return 1, 1, "approximate"
    for i in range(len(lines) - len(excerpt_lines) + 1):
        window = [lines[i + j].strip() for j in range(len(excerpt_lines))]
        match = True
        for j, el in enumerate(excerpt_lines):
            if el not in window[j] and window[j] not in el:
                match = False
                break
        if match:
            return i + 1, i + len(excerpt_lines), "exact"
    first_el = excerpt_lines[0]
    for i, line in enumerate(lines):
        if first_el in line or line.strip() in first_el:
            last_el = excerpt_lines[-1]
            for k in range(i, min(i + 50, len(lines))):
                if last_el in lines[k] or lines[k].strip() in last_el:
                    return i + 1, k + 1, "approximate"
            return i + 1, i + 1, "approximate"
    return 1, len(lines) or 1, "approximate"


def _index_datasets_for_lookup(public: bool = False) -> list[str]:
    return ["active"] if public else ["active", "archive"]


def _chunk_number_from_anchor(anchor_id: str | None) -> int | None:
    if not anchor_id:
        return None
    match = re.search(r"(?:^anchor|[_-]c)(\d+)$", anchor_id)
    return int(match.group(1)) if match else None


def _lookup_index_locator(
    workspace: Path,
    doc_id: str,
    version: str,
    anchor_id: str | None,
    *,
    public: bool = False,
) -> dict[str, Any] | None:
    chunk_number = _chunk_number_from_anchor(anchor_id)
    for dataset in _index_datasets_for_lookup(public):
        index_path = workspace / "ragflow_index" / f"technical_{dataset}.jsonl"
        if not index_path.exists():
            continue
        ordinal = 0
        with index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if payload.get("doc_id") != doc_id or str(payload.get("version") or "") != version:
                    continue
                ordinal += 1
                anchor_matches = bool(anchor_id and payload.get("anchor_id") == anchor_id)
                ordinal_matches = bool(chunk_number and ordinal == chunk_number)
                if not anchor_matches and not ordinal_matches:
                    continue
                line_start = payload.get("line_start")
                line_end = payload.get("line_end")
                if line_start is None or line_end is None:
                    return None
                return {
                    "anchor_id": payload.get("anchor_id") or anchor_id,
                    "chunk_id": payload.get("chunk_id"),
                    "line_start": int(line_start),
                    "line_end": int(line_end),
                    "locator_status": "exact" if anchor_matches else "approximate",
                    "matched_excerpt": clean_excerpt(payload.get("text") or ""),
                }
    if not public:
        return _lookup_manifest_citation_locator(workspace, doc_id, version, anchor_id)
    return None


def _lookup_manifest_citation_locator(
    workspace: Path,
    doc_id: str,
    version: str,
    anchor_id: str | None,
) -> dict[str, Any] | None:
    chunk_number = _chunk_number_from_anchor(anchor_id)
    record = next((item for item in ManifestStore(workspace).load() if item.doc_id == doc_id and item.version == version), None)
    if not record:
        return None
    extra = getattr(record, "extra", {}) or {}
    citation_path_value = extra.get("citation_map_path")
    if not citation_path_value:
        return None
    citation_path = _record_path(workspace, str(citation_path_value))
    if not citation_path or not citation_path.exists():
        return None
    try:
        citations = json.loads(citation_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(citations, list):
        return None
    for ordinal, citation in enumerate(citations, start=1):
        if not isinstance(citation, dict):
            continue
        anchor_matches = bool(anchor_id and citation.get("anchor_id") == anchor_id)
        ordinal_matches = bool(chunk_number and ordinal == chunk_number)
        if not anchor_matches and not ordinal_matches:
            continue
        normalized = citation.get("normalized_locator") or {}
        line_start = normalized.get("line_start")
        line_end = normalized.get("line_end")
        if line_start is None or line_end is None:
            return None
        return {
            "anchor_id": citation.get("anchor_id") or anchor_id,
            "chunk_id": citation.get("chunk_id"),
            "line_start": int(line_start),
            "line_end": int(line_end),
            "locator_status": "exact" if anchor_matches else "approximate",
            "matched_excerpt": clean_excerpt(citation.get("section_title") or citation.get("display_locator") or ""),
            "source_locator": citation.get("source_locator"),
            "display_locator": citation.get("display_locator"),
        }
    return None


def _record_citation_map(workspace: Path, record: Any) -> list[dict[str, Any]]:
    extra = getattr(record, "extra", {}) or {}
    citation_path_value = extra.get("citation_map_path")
    if not citation_path_value:
        return []
    citation_path = _record_path(workspace, str(citation_path_value))
    if not citation_path or not citation_path.exists():
        return []
    try:
        citations = json.loads(citation_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(citations, list):
        return []
    return [item for item in citations if isinstance(item, dict)]


def _record_human_review_path(workspace: Path, record: Any) -> Path | None:
    extra = getattr(record, "extra", {}) or {}
    review_path = extra.get("human_review_path") or extra.get("review_report_path")
    if review_path:
        return _record_path(workspace, str(review_path))
    display_code = str(extra.get("display_code") or record.doc_id)
    version = str(extra.get("revision_slug") or record.version)
    return workspace / "review" / "upload" / f"{display_code}_{version}" / "human_review.json"


def _write_human_review_packet(workspace: Path, payload: HumanReviewRequest) -> dict[str, Any]:
    if payload.review_status not in {"approved", "rejected", "needs_fix", "pending_review"}:
        raise HTTPException(status_code=400, detail="review_status must be approved, rejected, needs_fix, or pending_review")
    reviewer = payload.reviewer.strip()
    if not reviewer:
        raise HTTPException(status_code=400, detail="reviewer is required")
    store = ManifestStore(workspace)
    record = store.get(payload.doc_id, payload.version)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")
    review_path = _record_human_review_path(workspace, record)
    if not review_path:
        raise HTTPException(status_code=400, detail="Human review path is unavailable")
    existing_preview = _read_json_preview(review_path)
    existing = existing_preview.get("data") if existing_preview.get("exists") else {}
    if not isinstance(existing, dict):
        existing = {}
    packet = {
        **existing,
        "review_status": payload.review_status,
        "reviewer": reviewer,
        "doc_id": payload.doc_id,
        "display_code": (record.extra or {}).get("display_code") or payload.doc_id,
        "display_version": (record.extra or {}).get("display_version") or record.version,
        "checklist": payload.checklist,
        "notes": payload.notes,
        "reviewed_at": utc_now(),
    }
    write_json(review_path, packet)
    record.extra = {**(record.extra or {}), "human_review_path": str(review_path)}
    store.upsert(record)
    return packet


def _review_queue_payload(workspace: Path) -> dict[str, Any]:
    records = ManifestStore(workspace).load()

    def item_payload(record: Any) -> dict[str, Any]:
        review = _read_json_preview(_record_human_review_path(workspace, record))
        return {
            "doc_id": record.doc_id,
            "version": record.version,
            "title": record.title,
            "status": record.status,
            "status_reason": record.status_reason,
            "category": record.category,
            "owner": record.owner,
            "normalized_path": record.normalized_path,
            "quality_status": (record.extra or {}).get("quality_status"),
            "quality_report_path": (record.extra or {}).get("quality_report_path"),
            "human_review_path": (record.extra or {}).get("human_review_path") or (record.extra or {}).get("review_report_path"),
            "human_review": review.get("data") if review.get("exists") else None,
        }

    pending = [item_payload(record) for record in records if record.status == "pending_review"]
    failed = [item_payload(record) for record in records if record.status == "failed_review"]
    return {
        "pending_review": pending,
        "failed_review": failed,
        "summary": {
            "pending_review": len(pending),
            "failed_review": len(failed),
        },
    }


def _citation_locator(
    workspace: Path,
    *,
    doc_id: str,
    version: str,
    content: str,
    anchor_id: str | None = None,
    excerpt: str | None = None,
    public: bool = False,
) -> dict[str, Any] | None:
    locator = _lookup_index_locator(workspace, doc_id, version, anchor_id, public=public)
    if locator:
        return locator
    if excerpt:
        line_start, line_end, _locator_status = locate_excerpt_in_markdown(content, excerpt)
        return {
            "anchor_id": anchor_id,
            "chunk_id": None,
            "line_start": line_start,
            "line_end": line_end,
            "locator_status": "approximate",
            "matched_excerpt": clean_excerpt(excerpt),
        }
    return None


def _markdown_preview_lines(
    content: str,
    citation: dict[str, Any] | None,
    *,
    context_lines: int = 8,
) -> dict[str, Any] | None:
    if not content or not citation:
        return None
    lines = content.splitlines()
    if not lines:
        return None
    line_start = max(1, int(citation.get("line_start") or 1))
    line_end = max(line_start, int(citation.get("line_end") or line_start))
    preview_start = max(1, line_start - context_lines)
    preview_end = min(len(lines), line_end + context_lines)
    return {
        "line_start": preview_start,
        "line_end": preview_end,
        "highlight_line_start": line_start,
        "highlight_line_end": line_end,
        "anchor_id": citation.get("anchor_id"),
        "locator_status": citation.get("locator_status"),
        "matched_excerpt": citation.get("matched_excerpt"),
        "content": "\n".join(lines[preview_start - 1 : preview_end]),
        "lines": [
            {
                "line": line_number,
                "text": lines[line_number - 1],
                "highlight": line_start <= line_number <= line_end,
                "anchor_id": citation.get("anchor_id") if line_start <= line_number <= line_end else None,
            }
            for line_number in range(preview_start, preview_end + 1)
        ],
    }


def _read_full_markdown(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _document_detail_payload(
    workspace: Path,
    doc_id: str,
    version: str,
    anchor_id: str | None = None,
    excerpt: str | None = None,
) -> dict[str, Any]:
    records = ManifestStore(workspace).load()
    record = next((item for item in records if item.doc_id == doc_id and item.version == version), None)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")

    extra = getattr(record, "extra", {}) or {}
    source_path = _record_path(workspace, record.source_path)
    normalized_path = _record_path(workspace, record.normalized_path)
    metadata_path = source_path.with_name(source_path.stem + ".metadata.json") if source_path else None
    qa_path = None
    if extra.get("qa_report_path"):
        qa_path = _record_path(workspace, str(extra["qa_report_path"]))
    if not qa_path and extra.get("quality_report_path"):
        qa_path = _record_path(workspace, str(extra["quality_report_path"]))
    if not qa_path:
        qa_path = (
            workspace
            / ".Workplace"
            / "artifacts"
            / record.category
            / f"{record.doc_id}_v{record.version}"
            / "qa_report.json"
        )

    markdown = _read_text_preview(normalized_path)
    markdown["quality"] = _markdown_quality(str(markdown.get("content") or ""))
    source_preview = _source_preview_payload(source_path)
    source_preview["file_url"] = f"/api/documents/{doc_id}/{version}/source-file" if source_preview.get("exists") else None
    qa_report = _read_json_preview(qa_path)
    metadata_sidecar = _read_json_preview(metadata_path)
    citations = _record_citation_map(workspace, record)
    human_review = _read_json_preview(_record_human_review_path(workspace, record))

    canonical_key = _canonical_document_key(record)
    related = [
        item
        for item in records
        if item.key != record.key and _canonical_document_key(item) == canonical_key
    ]
    latest_revision = max([rev for rev in (_revision_number(item) for item in [record, *related]) if rev is not None], default=None)
    current_revision = _revision_number(record)

    warnings: list[dict[str, str]] = []
    if not markdown["exists"]:
        warnings.append({"level": "error", "code": "missing_markdown", "message": "Normalized Markdown file is missing."})
    elif len(str(markdown["content"]).strip()) < 200:
        warnings.append({"level": "warning", "code": "short_markdown", "message": "Markdown output is very short."})
    if markdown["exists"]:
        quality = markdown["quality"]
        if quality["mojibake_score"]:
            warnings.append({"level": "error", "code": "possible_mojibake", "message": "Markdown still contains mojibake markers."})
        if quality["replacement_characters"]:
            warnings.append({"level": "error", "code": "replacement_characters", "message": "Markdown contains replacement characters."})
        if quality["question_marks"] > 20:
            warnings.append({"level": "warning", "code": "ocr_uncertain_text", "message": "Markdown has many question marks; OCR output should be reviewed."})
    if qa_report["exists"]:
        qa_data = qa_report.get("data") or {}
        qa_status = str(qa_data.get("status") or qa_data.get("quality_status") or "")
        if qa_status and qa_status not in {"pass", "passed", "repaired"}:
            warnings.append({"level": "error", "code": "qa_not_passed", "message": f"QA status is {qa_status}."})
        if qa_report.get("error"):
            warnings.append({"level": "warning", "code": "qa_report_unreadable", "message": str(qa_report["error"])})
    else:
        warnings.append({"level": "warning", "code": "missing_qa_report", "message": "QA report is missing."})
    if re.search(
        r"\b(?:quy tr nh|h ng d n|th m nh|c ph c|s d ng|x l|thu h i|t i li u|ch t l ng|ki m so t|ng u nhi t|gi i thi u)\b|[a-f0-9]{8}$",
        record.title or "",
        re.I,
    ):
        warnings.append({"level": "warning", "code": "title_needs_review", "message": "Title looks slugged or missing Vietnamese accents."})
    category_hint = _category_hint(record)
    if category_hint and category_hint != record.category:
        warnings.append(
            {
                "level": "warning",
                "code": "category_mismatch",
                "message": f"Filename/title suggests {category_hint}, current category is {record.category}.",
            }
        )
    if related:
        warnings.append(
            {
                "level": "warning",
                "code": "related_versions",
                "message": f"{len(related)} related record(s) share the same document family.",
            }
        )
    if record.status == "active" and latest_revision is not None and current_revision is not None and current_revision < latest_revision:
        warnings.append(
            {
                "level": "error",
                "code": "older_active_version",
                "message": f"Active record appears older than Rev {latest_revision}.",
            }
        )

    citation_info = None
    citation_preview = None
    if markdown.get("exists") and (anchor_id or excerpt):
        citation_content = _read_full_markdown(normalized_path)
        citation_info = _citation_locator(
            workspace,
            doc_id=doc_id,
            version=version,
            content=citation_content,
            anchor_id=anchor_id,
            excerpt=excerpt,
        )
        citation_preview = _markdown_preview_lines(citation_content, citation_info)

    return {
        "record": record.to_dict(),
        "metadata_sidecar": metadata_sidecar,
        "qa_report": qa_report,
        "markdown": markdown,
        "source_preview": source_preview,
        "canonical_key": canonical_key,
        "current_revision": current_revision,
        "latest_related_revision": latest_revision,
        "related_records": [
            {
                "doc_id": item.doc_id,
                "version": item.version,
                "status": item.status,
                "category": item.category,
                "title": item.title,
                "revision": _revision_number(item),
                "approved_by": item.approved_by,
            }
            for item in sorted(related, key=lambda item: (item.status, item.doc_id, item.version))
        ],
        "warnings": warnings,
        "citations": citations,
        "human_review": human_review,
        "citation": citation_info,
        "citation_preview": citation_preview,
    }


def _public_document_citation_payload(
    workspace: Path,
    doc_id: str,
    version: str,
    *,
    anchor_id: str | None = None,
    excerpt: str | None = None,
) -> dict[str, Any]:
    records = ManifestStore(workspace).load()
    active_latest = {
        (record.doc_id, record.version)
        for record in latest_active_records(records)
    }
    if (doc_id, version) not in active_latest:
        raise HTTPException(status_code=404, detail="Document not found")
    record = next((item for item in records if item.doc_id == doc_id and item.version == version), None)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")
    normalized_path = _record_path(workspace, record.normalized_path)
    content = _read_full_markdown(normalized_path)
    if not content:
        raise HTTPException(status_code=404, detail="Markdown not found")
    citation = _citation_locator(
        workspace,
        doc_id=doc_id,
        version=version,
        content=content,
        anchor_id=anchor_id,
        excerpt=excerpt,
        public=True,
    )
    if not citation:
        raise HTTPException(status_code=404, detail="Citation not found")
    safe_citation = {
        "anchor_id": citation.get("anchor_id"),
        "line_start": citation.get("line_start"),
        "line_end": citation.get("line_end"),
        "locator_status": citation.get("locator_status"),
        "matched_excerpt": citation.get("matched_excerpt"),
    }
    return {
        "record": {
            "title": record.title,
            "doc_id": record.doc_id,
            "version": record.version,
        },
        "citation": safe_citation,
        "preview": _markdown_preview_lines(content, citation),
    }


@contextlib.asynccontextmanager
async def _app_lifespan(app: FastAPI):
    workspace = app.state.workspace
    cleanup_stale_sessions(workspace)
    task = asyncio.create_task(_user_session_cleanup_loop(workspace))
    app.state.user_session_cleanup_task = task
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app(root: Path | None = None) -> FastAPI:
    workspace = (root or Path(os.getenv("KB_WORKSPACE_ROOT", ".")).resolve()).resolve()
    init_workspace(workspace)

    app = FastAPI(title="Internal Procedure Chatbot", version="0.1.0", lifespan=_app_lifespan)
    app.state.workspace = workspace
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def operator_auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in {"/api/auth-status"} and not path.startswith("/api/user/"):
            try:
                require_operator_auth(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        try:
            response = await call_next(request)
            if path == "/" or path.startswith("/static/"):
                response.headers["Cache-Control"] = "no-store, max-age=0"
            return response
        except Exception as exc:
            incident_id = record_incident(
                workspace,
                "critical",
                "api",
                "Unhandled API error",
                str(exc),
                {"path": path, "method": request.method},
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal API error", "incident_id": incident_id},
            )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/chat")
    def user_chat_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "user" / "index.html")

    @app.get("/user")
    def user_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "user" / "index.html")

    @app.get("/api/auth-status")
    def auth_status() -> dict[str, bool]:
        return public_auth_status()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        db = QualityDatabase(workspace)
        ragflow = ragflow_status()
        mineru_command = os.getenv("MINERU_EXECUTABLE", "mineru")
        mineru_path = shutil.which(mineru_command)
        records = ManifestStore(workspace).load()
        active_count = len([record for record in records if record.status == "active"])
        pending_count = len([record for record in records if record.status == "pending_review"])
        quality_stats = db.stats()
        llm = llm_runtime_status(root=workspace, check_live=False)
        llm_configured = bool(llm["configured"])
        service_status = public_service_status(
            active_documents=active_count,
            open_incidents=quality_stats["open_incident_count"],
            critical_incidents=quality_stats["critical_incident_count"],
            llm_configured=llm_configured,
        )
        return {
            "workspace": str(workspace),
            "auth": public_auth_status(),
            "ragflow": ragflow,
            "mineru": {
                "available": bool(mineru_path),
                "command": mineru_command,
                "path": mineru_path,
                "method": os.getenv("MINERU_METHOD", "auto"),
                "backend": os.getenv("MINERU_BACKEND"),
                "api_url": os.getenv("MINERU_API_URL"),
                "backend_url": os.getenv("MINERU_BACKEND_URL"),
                "max_pages": os.getenv("MINERU_MAX_PAGES"),
                "formula": os.getenv("MINERU_FORMULA"),
                "table": os.getenv("MINERU_TABLE"),
                "image_analysis": os.getenv("MINERU_IMAGE_ANALYSIS"),
            },
            "providers": {
                "allowed": sorted(allowed_providers()),
                "local_fallback_enabled": local_fallback_enabled(),
            },
            "llm": llm,
            "manifest": {
                "records": len(records),
                "active": active_count,
                "pending_review": pending_count,
            },
            "quality": quality_stats,
            "incidents": {
                "open": quality_stats["open_incident_count"],
                "critical": quality_stats["critical_incident_count"],
            },
            "service_status": service_status,
            "evaluation": latest_report(workspace),
            "readiness": deployment_readiness(workspace, check_network=False),
        }

    @app.get("/api/user/bootstrap")
    def user_bootstrap_api() -> dict[str, Any]:
        policy = load_policy_pack(workspace)
        return {
            "service_status": health()["service_status"],
            "templates": load_curated_templates(workspace),
            "welcome_cards": welcome_cards_payload(),
            "answer_styles": answer_styles_payload(),
            "policy": public_policy_summary(policy),
            "ui": {
                "default_drawer_tab": "sources",
                "drawer_can_hide": True,
                "drawer_can_pin": False,
                "citation_visibility": "excerpt_metadata",
                "show_policy_debug": False,
            },
        }

    @app.post("/api/user/chat")
    def user_chat_api(payload: UserChatRequest) -> dict[str, Any]:
        if maintenance_enabled():
            message = os.getenv("KB_MAINTENANCE_MESSAGE", "He thong dang duoc bao tri. Vui long quay lai sau.")
            raise HTTPException(status_code=503, detail=message)
        if not payload.query.strip():
            raise HTTPException(status_code=400, detail="query is required")
        templates = load_curated_templates(workspace)
        if not template_exists(templates, payload.template_id):
            raise HTTPException(status_code=400, detail=f"Unknown template_id: {payload.template_id}")
        answer_style = normalize_answer_style(payload.answer_style)
        return user_chat_response(
            workspace,
            payload.query,
            template_id=payload.template_id,
            answer_style=answer_style,
            session_id=payload.session_id,
            device_id=payload.device_id,
            use_llm=payload.use_llm,
        )

    @app.post("/api/user/session/heartbeat")
    def user_session_heartbeat_api(payload: UserSessionHeartbeatRequest) -> dict[str, Any]:
        return heartbeat_session(workspace, payload.session_id, payload.device_id)

    @app.post("/api/user/feedback")
    def user_feedback_api(payload: UserFeedbackRequest) -> dict[str, object]:
        log_id = payload.log_id or payload.query_log_id
        feedback = payload.rating or payload.feedback
        if not log_id:
            raise HTTPException(status_code=400, detail="log_id is required")
        if not feedback:
            raise HTTPException(status_code=400, detail="rating is required")
        try:
            return apply_feedback(workspace, log_id, feedback)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/readiness")
    def readiness_api(check_network: bool = False) -> dict[str, Any]:
        return deployment_readiness(workspace, check_network=check_network)

    @app.get("/api/llm/status")
    def llm_status_api(check_live: bool = True, smoke: bool = False) -> dict[str, Any]:
        timeout = float(os.getenv("KB_LLM_HEALTH_TIMEOUT_SECONDS", "8"))
        return llm_runtime_status(root=workspace, check_live=check_live, smoke=smoke, timeout=timeout)

    @app.get("/api/llm/presets")
    def llm_presets_api() -> list[dict[str, Any]]:
        return llm_presets()

    @app.get("/api/llm/config")
    def llm_config_api() -> dict[str, Any]:
        return redacted_llm_config(workspace)

    @app.post("/api/llm/test")
    def llm_test_api(payload: LLMConfigRequest | None = None, smoke: bool = True) -> dict[str, Any]:
        timeout = float((payload.timeout_seconds if payload else None) or os.getenv("KB_LLM_HEALTH_TIMEOUT_SECONDS", "8"))
        try:
            config = transient_llm_config(model_payload(payload) if payload else {}) if payload else None
            return llm_runtime_status(root=workspace, config=config, check_live=True, smoke=smoke, timeout=timeout)
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/llm/config")
    def llm_save_config_api(payload: LLMConfigRequest) -> dict[str, Any]:
        timeout = float(payload.timeout_seconds or os.getenv("KB_LLM_HEALTH_TIMEOUT_SECONDS", "8"))
        try:
            payload_data = model_payload(payload)
            config = transient_llm_config(payload_data)
            status = llm_runtime_status(config=config, check_live=True, smoke=True, timeout=timeout)
            if status.get("state") != "ready":
                raise LLMError(str(status.get("last_error") or "LLM smoke test failed."))
            saved = save_llm_runtime_config(workspace, payload_data)
            return {"config": saved, "status": status}
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/llm/config/reset")
    def llm_reset_config_api() -> dict[str, Any]:
        reset_llm_runtime_config(workspace)
        return redacted_llm_config(workspace)

    @app.get("/api/taxonomy")
    def taxonomy() -> dict[str, Any]:
        path = workspace / "manifest" / "taxonomy.json"
        return read_json(path) if path.exists() else {}

    @app.get("/api/manifest")
    def manifest() -> list[dict[str, Any]]:
        return [record.to_dict() for record in ManifestStore(workspace).load()]

    @app.get("/api/documents/{doc_id}/{version}")
    def document_detail(
        doc_id: str,
        version: str,
        anchor_id: str | None = None,
        excerpt: str | None = None,
    ) -> dict[str, Any]:
        return _document_detail_payload(workspace, doc_id, version, anchor_id=anchor_id, excerpt=excerpt)

    @app.get("/api/documents/{doc_id}/{version}/source-file")
    def document_source_file(doc_id: str, version: str) -> FileResponse:
        record = next(
            (item for item in ManifestStore(workspace).load() if item.doc_id == doc_id and item.version == version),
            None,
        )
        if not record:
            raise HTTPException(status_code=404, detail="Document not found")
        source_path = _record_path(workspace, record.source_path)
        if not source_path or not source_path.exists():
            raise HTTPException(status_code=404, detail="Source file not found")
        return FileResponse(source_path, filename=source_path.name)

    @app.get("/api/documents/{doc_id}/{version}/citation")
    def document_citation_by_excerpt(doc_id: str, version: str, excerpt: str | None = None) -> dict[str, Any]:
        return _document_detail_payload(workspace, doc_id, version, excerpt=excerpt)

    @app.get("/api/documents/{doc_id}/{version}/citation/{anchor_id}")
    def document_citation(doc_id: str, version: str, anchor_id: str) -> dict[str, Any]:
        return _document_detail_payload(workspace, doc_id, version, anchor_id=anchor_id)

    @app.get("/api/user/documents/{doc_id}/{version}/citation")
    def public_document_citation_by_excerpt(doc_id: str, version: str, excerpt: str | None = None) -> dict[str, Any]:
        return _public_document_citation_payload(workspace, doc_id, version, excerpt=excerpt)

    @app.get("/api/user/documents/{doc_id}/{version}/citation/{anchor_id}")
    def public_document_citation(doc_id: str, version: str, anchor_id: str) -> dict[str, Any]:
        return _public_document_citation_payload(workspace, doc_id, version, anchor_id=anchor_id)

    @app.get("/api/manifest/summary")
    def manifest_summary_api() -> list[dict[str, str | None]]:
        return manifest_summary(workspace)

    @app.get("/api/review-queue")
    def review_queue_api() -> dict[str, Any]:
        return _review_queue_payload(workspace)

    @app.get("/api/inbox")
    def inbox_api() -> list[dict[str, Any]]:
        return list_inbox(workspace)

    @app.get("/api/upload-queue")
    def upload_queue_api() -> dict[str, Any]:
        return list_upload_queue(workspace)

    @app.get("/api/agent-prompts/templates")
    def agent_prompt_templates_api() -> dict[str, Any]:
        return list_agent_prompt_templates()

    @app.post("/api/inbox/upload")
    def upload_inbox_api(payload: UploadInboxRequest) -> dict[str, Any]:
        try:
            return save_upload_to_inbox(
                workspace,
                payload.filename,
                payload.content_base64,
                category=payload.category,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "intake",
                "Inbox upload failed",
                str(exc),
                {"filename": payload.filename, "category": payload.category},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent-prompts/generate")
    def generate_agent_prompt_api(payload: GenerateAgentPromptRequest) -> dict[str, Any]:
        try:
            return generate_agent_prompt(
                workspace,
                payload.relative_paths,
                prompt_mode=payload.prompt_mode,
                admin_request=payload.admin_request,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "intake",
                "Agent prompt generation failed",
                str(exc),
                {
                    "relative_paths": payload.relative_paths,
                    "prompt_mode": payload.prompt_mode,
                },
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent-prompts/generate-goal")
    def generate_agent_goal_prompt_api(payload: GenerateAgentGoalPromptRequest) -> dict[str, Any]:
        try:
            return generate_agent_goal_prompt(
                workspace,
                payload.relative_paths,
                goal_target=payload.goal_target,
                branch=payload.branch,
                verification=payload.verification,
                admin_request=payload.admin_request,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "intake",
                "Agent GOAL prompt generation failed",
                str(exc),
                {
                    "relative_paths": payload.relative_paths,
                    "branch": payload.branch,
                },
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/upload-queue/status")
    def update_upload_queue_status_api(payload: UploadQueueStatusRequest) -> dict[str, Any]:
        try:
            return update_upload_status(
                workspace,
                payload.relative_paths,
                payload.status,
                error=payload.error,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "intake",
                "Upload queue status update failed",
                str(exc),
                {"relative_paths": payload.relative_paths, "status": payload.status},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/upload-queue/workflow-event")
    def upload_queue_workflow_event_api(payload: UploadWorkflowEventRequest) -> dict[str, Any]:
        try:
            return record_upload_workflow_event(
                workspace,
                payload.relative_paths,
                status=payload.status,
                step=payload.step,
                detail=payload.detail,
                error=payload.error,
                metadata=payload.metadata,
                artifact_path=payload.artifact_path,
                qa_report_path=payload.qa_report_path,
                qa_status=payload.qa_status,
                qa_issues=payload.qa_issues,
                mineru_profile=payload.mineru_profile,
                handoff_path=payload.handoff_path,
                checkpoint=payload.checkpoint,
                artifacts=payload.artifacts,
                quality_gates=payload.quality_gates,
                next_skill=payload.next_skill,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "intake",
                "Upload workflow event update failed",
                str(exc),
                {
                    "relative_paths": payload.relative_paths,
                    "status": payload.status,
                    "step": payload.step,
                },
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/approve")
    def approve_api(payload: ApproveRequest) -> dict[str, Any]:
        try:
            return approve_record(workspace, payload.doc_id, payload.version, payload.approved_by).to_dict()
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "lifecycle",
                "Document approval failed",
                str(exc),
                {"doc_id": payload.doc_id, "version": payload.version},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/human-review")
    def human_review_api(payload: HumanReviewRequest) -> dict[str, Any]:
        try:
            return _write_human_review_packet(workspace, payload)
        except HTTPException:
            raise
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "lifecycle",
                "Human review packet update failed",
                str(exc),
                {"doc_id": payload.doc_id, "version": payload.version, "review_status": payload.review_status},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reject")
    def reject_api(payload: RejectRequest) -> dict[str, Any]:
        try:
            return reject_record(workspace, payload.doc_id, payload.version, payload.reason).to_dict()
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "lifecycle",
                "Document rejection failed",
                str(exc),
                {"doc_id": payload.doc_id, "version": payload.version},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/retire")
    def retire_api(payload: RetireRequest) -> dict[str, Any]:
        try:
            return retire_record(workspace, payload.doc_id, payload.version, payload.reason).to_dict()
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "lifecycle",
                "Document retirement failed",
                str(exc),
                {"doc_id": payload.doc_id, "version": payload.version},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/rebuild-index")
    def rebuild_index_api() -> dict[str, bool]:
        rebuild_indexes(workspace)
        return {"ok": True}

    @app.post("/api/sync-ragflow")
    def sync_ragflow_api(payload: SyncRAGFlowRequest) -> dict[str, Any]:
        config = RAGFlowConfig.from_env()
        base_url = payload.base_url or (config.base_url if config else None)
        api_key = payload.api_key or (config.api_key if config else None)
        dataset_id = payload.dataset_id or (config.dataset_id if config else None)
        if not base_url or not api_key or not dataset_id:
            raise HTTPException(
                status_code=400,
                detail="RAGFlow base_url, api_key, and dataset_id are required",
            )
        try:
            return sync_active_to_ragflow(
                workspace,
                base_url,
                api_key,
                dataset_id,
                delete_all=payload.delete_all,
                parse_after_upload=payload.parse_after_upload,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "ragflow",
                "RAGFlow sync failed",
                str(exc),
                {"dataset_id_configured": bool(dataset_id), "delete_all": payload.delete_all},
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/bootstrap-ragflow")
    def bootstrap_ragflow_api(payload: BootstrapRAGFlowRequest) -> dict[str, Any]:
        config = RAGFlowConfig.from_env()
        base_url = payload.base_url or (config.base_url if config else None)
        api_key = payload.api_key or (config.api_key if config else None)
        if not base_url or not api_key:
            raise HTTPException(status_code=400, detail="RAGFlow base_url and api_key are required")
        try:
            return bootstrap_ragflow_resources(
                base_url,
                api_key,
                dataset_name=payload.dataset_name,
                chat_name=payload.chat_name,
                llm_id=payload.llm_id,
                create_chat=payload.create_chat,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "ragflow",
                "RAGFlow bootstrap failed",
                str(exc),
                {"dataset_name": payload.dataset_name, "chat_name": payload.chat_name},
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/evaluate")
    def evaluate_api(payload: EvaluateRequest) -> dict[str, Any]:
        if payload.provider not in {"auto", "ragflow", "local"}:
            raise HTTPException(status_code=400, detail="provider must be auto, ragflow, or local")
        try:
            return run_evaluation(
                workspace,
                cases_path=payload.cases_path,
                provider=payload.provider,
                use_llm=payload.use_llm,
                latency_target_ms=payload.latency_target_ms,
            )
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "evaluation",
                "Regression evaluation failed",
                str(exc),
                {"provider": payload.provider, "cases_path": payload.cases_path},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/chat")
    def chat_api(payload: ChatRequest) -> dict[str, Any]:
        if maintenance_enabled():
            message = os.getenv("KB_MAINTENANCE_MESSAGE", "He thong dang duoc bao tri. Vui long quay lai sau.")
            raise HTTPException(status_code=503, detail=message)
        if not payload.query.strip():
            raise HTTPException(status_code=400, detail="query is required")
        if not provider_allowed(payload.provider):
            raise HTTPException(status_code=400, detail=f"Provider is not allowed: {payload.provider}")
        result = ask(
            workspace,
            payload.query,
            user_id=payload.user_id,
            provider=payload.provider,
            use_llm=payload.use_llm,
        )
        if result.get("ragflow_error"):
            record_incident(
                workspace,
                "warning",
                "retrieval",
                "Retrieval provider warning",
                str(result["ragflow_error"]),
                {"query_log_id": result.get("query_log_id"), "provider": result.get("provider")},
            )
        if result.get("llm_error"):
            record_incident(
                workspace,
                "warning",
                "llm",
                "LLM answer fallback used",
                str(result["llm_error"]),
                {"query_log_id": result.get("query_log_id"), "provider": result.get("provider")},
            )
        slow_ms = int(os.getenv("KB_SLOW_RESPONSE_MS", "12000"))
        if int(result.get("latency_ms") or 0) > slow_ms:
            record_incident(
                workspace,
                "warning",
                "latency",
                "Slow chat response",
                f"Chat latency exceeded {slow_ms} ms",
                {"query_log_id": result.get("query_log_id"), "latency_ms": result.get("latency_ms")},
            )
        return result

    @app.post("/api/feedback")
    def feedback_api(payload: FeedbackRequest) -> dict[str, object]:
        try:
            return apply_feedback(workspace, payload.query_log_id, payload.feedback)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/gaps")
    def gaps_api() -> list[dict[str, Any]]:
        return QualityDatabase(workspace).list_gaps()

    @app.get("/api/queries")
    def queries_api() -> list[dict[str, Any]]:
        return QualityDatabase(workspace).list_queries()

    @app.get("/api/ingestion-runs")
    def ingestion_runs_api() -> list[dict[str, Any]]:
        return QualityDatabase(workspace).list_ingestion_runs()

    @app.get("/api/incidents")
    def incidents_api(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return QualityDatabase(workspace).list_incidents(status=status, limit=limit)

    @app.get("/api/incidents/{incident_id}/agent-prompt")
    def incident_agent_prompt_api(incident_id: int) -> dict[str, Any]:
        try:
            return {"incident_id": incident_id, "prompt": build_incident_agent_prompt(workspace, incident_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/incidents")
    def create_incident_api(payload: IncidentRequest) -> dict[str, int]:
        try:
            incident_id = record_incident(
                workspace,
                payload.severity,
                payload.component,
                payload.title,
                payload.detail,
                payload.context,
            )
            return {"incident_id": incident_id}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/incidents/resolve")
    def resolve_incident_api(payload: ResolveIncidentRequest) -> dict[str, Any]:
        try:
            return QualityDatabase(workspace).resolve_incident(payload.incident_id, payload.status)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/diagnostics")
    def diagnostics_api(include_logs: bool = True) -> dict[str, Any]:
        return diagnostic_snapshot(workspace, include_logs=include_logs)

    return app


async def _user_session_cleanup_loop(workspace: Path) -> None:
    interval = user_session_cleanup_interval_seconds()
    while True:
        await asyncio.sleep(interval)
        try:
            cleanup_stale_sessions(workspace)
        except Exception as exc:
            record_incident(
                workspace,
                "warning",
                "user_session",
                "User session cleanup failed",
                str(exc),
                {"interval_seconds": interval},
            )


def ragflow_status() -> dict[str, Any]:
    config = RAGFlowConfig.from_env()
    if not config:
        return {"configured": False, "available": False, "message": "RAGFlow env is not configured"}
    result: dict[str, Any] = {
        "configured": True,
        "available": False,
        "base_url": config.base_url,
        "dataset_id_configured": bool(config.dataset_id),
        "chat_id_configured": bool(config.chat_id),
        "search_id_configured": bool(config.search_id),
    }
    try:
        health = RAGFlowHTTPClient(config.base_url, config.api_key).health()
        result.update({"available": True, "health": health})
    except RAGFlowHTTPError as exc:
        result["message"] = str(exc)
    return result


app = create_app()


def main() -> int:
    import uvicorn

    host = os.getenv("KB_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("KB_WEB_PORT", "8088"))
    uvicorn.run("poc_workflow.webapp:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
