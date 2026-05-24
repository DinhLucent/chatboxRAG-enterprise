from __future__ import annotations

import os
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent_prompt_queue import generate_agent_prompt, list_upload_queue, update_upload_status
from .auth import public_auth_status, require_operator_auth
from .chatbot import apply_feedback, ask
from .database import QualityDatabase
from .document_qa import mojibake_score
from .evaluation import latest_report, run_evaluation
from .intake import list_inbox, save_upload_to_inbox
from .manifest import ManifestStore
from .operations import diagnostic_snapshot, maintenance_enabled, public_service_status, record_incident
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


class ApproveRequest(BaseModel):
    doc_id: str
    version: str
    approved_by: str


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


class UploadQueueStatusRequest(BaseModel):
    relative_paths: list[str]
    status: str
    error: str | None = None


class IncidentRequest(BaseModel):
    severity: str = "warning"
    component: str
    title: str
    detail: str
    context: dict[str, Any] | None = None


class ResolveIncidentRequest(BaseModel):
    incident_id: int
    status: str = "resolved"


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


def _markdown_quality(content: str) -> dict[str, int]:
    return {
        "characters": len(content),
        "lines": content.count("\n") + 1 if content else 0,
        "mojibake_score": mojibake_score(content),
        "replacement_characters": content.count("\ufffd") + content.count("ï¿½"),
        "question_marks": content.count("?"),
    }


def _document_detail_payload(workspace: Path, doc_id: str, version: str) -> dict[str, Any]:
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
    qa_report = _read_json_preview(qa_path)
    metadata_sidecar = _read_json_preview(metadata_path)

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
        qa_status = str((qa_report.get("data") or {}).get("status") or "")
        if qa_status and qa_status not in {"pass", "repaired"}:
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

    return {
        "record": record.to_dict(),
        "metadata_sidecar": metadata_sidecar,
        "qa_report": qa_report,
        "markdown": markdown,
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
    }


def create_app(root: Path | None = None) -> FastAPI:
    workspace = (root or Path(os.getenv("KB_WORKSPACE_ROOT", ".")).resolve()).resolve()
    init_workspace(workspace)

    app = FastAPI(title="Internal Procedure Chatbot", version="0.1.0")
    app.state.workspace = workspace
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def operator_auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in {"/api/auth-status"}:
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
        llm_configured = bool((os.getenv("POC_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")) and os.getenv("POC_LLM_MODEL"))
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
            "llm": {
                "configured": llm_configured,
                "base_url": os.getenv("POC_LLM_BASE_URL", "https://api.openai.com/v1"),
                "model": os.getenv("POC_LLM_MODEL"),
            },
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

    @app.get("/api/readiness")
    def readiness_api(check_network: bool = False) -> dict[str, Any]:
        return deployment_readiness(workspace, check_network=check_network)

    @app.get("/api/taxonomy")
    def taxonomy() -> dict[str, Any]:
        path = workspace / "manifest" / "taxonomy.json"
        return read_json(path) if path.exists() else {}

    @app.get("/api/manifest")
    def manifest() -> list[dict[str, Any]]:
        return [record.to_dict() for record in ManifestStore(workspace).load()]

    @app.get("/api/documents/{doc_id}/{version}")
    def document_detail(doc_id: str, version: str) -> dict[str, Any]:
        return _document_detail_payload(workspace, doc_id, version)

    @app.get("/api/manifest/summary")
    def manifest_summary_api() -> list[dict[str, str | None]]:
        return manifest_summary(workspace)

    @app.get("/api/inbox")
    def inbox_api() -> list[dict[str, Any]]:
        return list_inbox(workspace)

    @app.get("/api/upload-queue")
    def upload_queue_api() -> dict[str, Any]:
        return list_upload_queue(workspace)

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
            return generate_agent_prompt(workspace, payload.relative_paths)
        except Exception as exc:
            record_incident(
                workspace,
                "error",
                "intake",
                "Agent prompt generation failed",
                str(exc),
                {"relative_paths": payload.relative_paths},
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
