from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .database import QualityDatabase
from .evaluation import latest_report
from .readiness import deployment_readiness
from .utils import utc_now


def record_incident(
    root: Path,
    severity: str,
    component: str,
    title: str,
    detail: str,
    context: dict[str, Any] | None = None,
    notify: bool = True,
) -> int:
    incident_id = QualityDatabase(root).create_incident(
        severity=severity,
        component=component,
        title=title,
        detail=detail,
        context=context,
    )
    if notify:
        send_alert_if_configured(root, incident_id, severity, component, title, detail, context or {})
    return incident_id


def maintenance_enabled() -> bool:
    return os.getenv("KB_MAINTENANCE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def public_service_status(
    *,
    active_documents: int,
    open_incidents: int,
    critical_incidents: int,
    llm_configured: bool,
) -> dict[str, Any]:
    if maintenance_enabled():
        return {
            "state": "maintenance",
            "can_chat": False,
            "title": "He thong dang bao tri",
            "message": os.getenv(
                "KB_MAINTENANCE_MESSAGE",
                "He thong dang duoc bao tri. Vui long quay lai sau.",
            ),
        }
    if critical_incidents:
        return {
            "state": "incident",
            "can_chat": False,
            "title": "He thong dang gap su co",
            "message": "Doi ky thuat da ghi nhan su co va dang xu ly. Vui long thu lai sau.",
        }
    if active_documents <= 0:
        return {
            "state": "not_ready",
            "can_chat": False,
            "title": "Chua co tai lieu san sang",
            "message": "Chua co tai lieu active da duyet de chatbot tra loi.",
        }
    if open_incidents:
        return {
            "state": "degraded",
            "can_chat": True,
            "title": "He thong dang hoat dong han che",
            "message": "Mot so canh bao dang duoc theo doi. Ban van co the dat cau hoi.",
        }
    if not llm_configured:
        return {
            "state": "limited",
            "can_chat": True,
            "title": "Dang dung che do tra cuu co ban",
            "message": "AI dien giai chua cau hinh, he thong van tra loi dua tren tai lieu nguon.",
        }
    return {
        "state": "ok",
        "can_chat": True,
        "title": "He thong san sang",
        "message": "Chatbot dang ket noi voi kho tai lieu noi bo.",
    }


def send_alert_if_configured(
    root: Path,
    incident_id: int,
    severity: str,
    component: str,
    title: str,
    detail: str,
    context: dict[str, Any],
) -> None:
    webhook_url = os.getenv("KB_ALERT_WEBHOOK_URL")
    if not webhook_url:
        return

    payload = {
        "incident_id": incident_id,
        "severity": severity,
        "component": component,
        "title": title,
        "detail": detail,
        "context": context,
        "created_at": utc_now(),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        write_alert_failure(root, incident_id, exc)


def write_alert_failure(root: Path, incident_id: int, exc: BaseException) -> None:
    log_path = root / ".runtime" / "alert-errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"created_at": utc_now(), "incident_id": incident_id, "error": str(exc)},
        ensure_ascii=False,
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def diagnostic_snapshot(root: Path, include_logs: bool = True) -> dict[str, Any]:
    db = QualityDatabase(root)
    stats = db.stats()
    readiness = summarize_readiness(deployment_readiness(root, check_network=False))
    incidents = db.list_incidents(status="open", limit=25)
    ingestion_failures = [
        run for run in db.list_ingestion_runs(limit=50) if run.get("status") == "failed_review"
    ]
    report = latest_report(root)
    snapshot = {
        "generated_at": utc_now(),
        "workspace": str(root),
        "status": infer_operational_status(stats, readiness, incidents),
        "summary": {
            "open_incidents": stats["open_incident_count"],
            "critical_incidents": stats["critical_incident_count"],
            "open_gaps": stats["open_gap_count"],
            "failed_ingestions": stats["failed_ingestion_count"],
            "readiness_ready": readiness["ready"],
            "latest_evaluation_pass": bool(report and report.get("pass")),
        },
        "readiness": readiness,
        "open_incidents": incidents,
        "failed_ingestion_runs": ingestion_failures,
        "recent_knowledge_gaps": db.list_gaps(status="open")[:25],
        "recent_queries": db.list_queries()[:25],
        "latest_evaluation": summarize_evaluation(report),
        "recommendations": recommendations(stats, readiness, incidents, ingestion_failures, report),
    }
    if include_logs:
        snapshot["runtime_logs"] = tail_runtime_logs(root)
    return snapshot


def build_incident_agent_prompt(root: Path, incident_id: int) -> str:
    db = QualityDatabase(root)
    incident = db.get_incident(incident_id)
    if not incident:
        raise ValueError(f"Incident not found: {incident_id}")

    snapshot = diagnostic_snapshot(root, include_logs=True)
    related_incidents = [
        item
        for item in snapshot.get("open_incidents", [])
        if item.get("id") == incident_id or item.get("component") == incident.get("component")
    ][:5]
    payload = {
        "workspace": str(root),
        "incident": incident,
        "operational_summary": snapshot.get("summary"),
        "operational_status": snapshot.get("status"),
        "readiness": snapshot.get("readiness"),
        "related_open_incidents": related_incidents,
        "recommendations": snapshot.get("recommendations", [])[:6],
        "latest_evaluation": snapshot.get("latest_evaluation"),
        "recent_queries": snapshot.get("recent_queries", [])[:8],
        "recent_knowledge_gaps": snapshot.get("recent_knowledge_gaps", [])[:8],
        "runtime_logs": snapshot.get("runtime_logs", [])[:4],
    }
    context = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(context) > 18_000:
        context = context[:18_000].rstrip() + "\n... [context truncated]"

    # Determine recommended test command based on the affected component dynamically
    comp = (incident.get("component") or "").lower()
    if any(k in comp for k in ("intake", "ingestion", "pipeline")):
        test_cmd = "python -m pytest tests\\test_pipeline.py tests\\test_intake.py --basetemp .pytest-tmp-codex"
    elif any(k in comp for k in ("converter", "miner", "pdf")):
        test_cmd = "python -m pytest tests\\test_converter.py --basetemp .pytest-tmp-codex"
    elif any(k in comp for k in ("evaluation", "quality", "gate")):
        test_cmd = "python -m pytest tests\\test_quality_gate.py tests\\test_answer_quality.py --basetemp .pytest-tmp-codex"
    elif "database" in comp or "db" in comp:
        test_cmd = "python -m pytest tests\\test_data_maintenance.py --basetemp .pytest-tmp-codex"
    else:
        test_cmd = "python -m pytest tests\\test_webapp.py --basetemp .pytest-tmp-codex"

    return f"""Bạn là một AI coding agent chuyên nghiệp và kỹ sư hệ thống làm việc trực tiếp trong repository cục bộ (Local Repo) của dự án.

Mục tiêu: phân tích, định vị và khắc phục triệt để lỗi liên quan đến incident #{incident_id} đang xảy ra trong hệ thống chatbot nội bộ.

Thông tin sự cố (Incident Info):
- Mức độ nghiêm trọng (Severity): {incident.get("severity")}
- Thành phần ảnh hưởng (Component): {incident.get("component")}
- Tiêu đề (Title): {incident.get("title")}
- Mô tả chi tiết (Detail): {incident.get("detail")}
- Trạng thái (Status): {incident.get("status")}
- Thời gian phát sinh (Created at): {incident.get("created_at")}

Bối cảnh hệ thống dạng JSON (System Context):
```json
{context}
```

Quy tắc và Ràng buộc bắt buộc (Constraints & Rules):
1. **Kiểm tra trước khi sửa**: Luôn đọc kỹ tệp mã nguồn và các file log liên quan trong `runtime_logs` trước khi tiến hành sửa đổi. KHÔNG ĐƯỢC đoán mò nguyên nhân.
2. **Khắc phục đúng phạm vi**: Chỉ chỉnh sửa các dòng code trực tiếp gây ra lỗi. Tránh viết thêm các cấu trúc trừu tượng (abstraction) không cần thiết hoặc sửa đổi các logic/file không liên quan.
3. **Bảo toàn dữ liệu**: KHÔNG ĐƯỢC chạy lệnh reset git (tránh làm mất các thay đổi chưa commit của user), không xóa dữ liệu runtime trong thư mục `data/` hay làm mất thay đổi hiện hành.
4. **Quy tắc UI/UX**: Nếu sửa đổi giao diện, phải giữ nguyên ngôn ngữ tiếng Việt, sử dụng bảng màu Teal/HSL chủ đạo của hệ thống thiết kế và đảm bảo layout co giãn responsive (không bị tràn khung).
5. **Giữ nguyên tài liệu**: Bảo toàn toàn bộ ghi chú (comments) và docstrings cũ không liên quan.
6. **Xác minh trước khi kết thúc**: Sau khi sửa xong, bắt buộc chạy kiểm thử để xác nhận. Lệnh kiểm thử khuyến nghị: `{test_cmd}`.

Hướng dẫn thực hiện từng bước (Chain-of-Thought):
- Bước 1: Trích xuất thông tin lỗi từ phần `Detail` và đối chiếu với danh sách log lỗi trong `runtime_logs`.
- Bước 2: Tìm các file mã nguồn liên quan đến `Component` bị ảnh hưởng trong thư mục `poc_workflow/`.
- Bước 3: Đọc hiểu và phân tích luồng code để xác định nguyên nhân gốc (root cause).
- Bước 4: Đề xuất phương án sửa tối giản, an toàn và tiến hành chỉnh sửa file.
- Bước 5: Chạy unit test tương ứng để kiểm tra tính đúng đắn.

Yêu cầu định dạng báo cáo kết quả (Output Format):
Hãy phản hồi theo cấu trúc Markdown sau (không thêm văn bản ngoài lề):
### 1. Nguyên nhân gốc (Root Cause)
[Mô tả chi tiết nguyên nhân gây ra sự cố]

### 2. Các file đã chỉnh sửa (Modified Files)
- `[đường dẫn_file_1]` (dòng [bắt đầu]-[kết thúc]): [Tóm tắt thay đổi ngắn gọn]

### 3. Kết quả kiểm thử (Verification & Test Results)
[Lệnh test đã chạy và log kết quả test]

### 4. Khuyến nghị hoặc Thao tác thủ công (nếu có)
[Mô tả các biến môi trường, cổng port hoặc dịch vụ ngoài cần khởi động lại, nếu có]
"""


def infer_operational_status(
    stats: dict[str, Any],
    readiness: dict[str, Any],
    incidents: list[dict[str, Any]],
) -> str:
    if stats["critical_incident_count"] or any(item["severity"] == "critical" for item in incidents):
        return "incident"
    if any(check["status"] == "fail" for check in readiness.get("checks", [])):
        return "not_ready"
    if stats["open_incident_count"] or any(check["status"] == "warn" for check in readiness.get("checks", [])):
        return "attention"
    return "ok"


def summarize_evaluation(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    metrics = report.get("metrics") or {}
    return {
        "pass": bool(report.get("pass")),
        "provider": report.get("provider"),
        "finished_at": report.get("finished_at"),
        "total_cases": metrics.get("total_cases"),
        "passed_cases": metrics.get("passed_cases"),
        "p95_latency_ms": metrics.get("p95_latency_ms"),
    }


def summarize_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready": readiness.get("ready"),
        "checks": readiness.get("checks", []),
        "active_document_count": readiness.get("active_document_count"),
        "latest_evaluation": summarize_evaluation(readiness.get("latest_evaluation")),
    }


def recommendations(
    stats: dict[str, Any],
    readiness: dict[str, Any],
    incidents: list[dict[str, Any]],
    ingestion_failures: list[dict[str, Any]],
    report: dict[str, Any] | None,
) -> list[str]:
    items: list[str] = []
    if incidents:
        items.append("Review /api/incidents first; resolve only after the root cause is fixed.")
    if ingestion_failures:
        items.append("Open failed ingestion runs, fix metadata/conversion, then re-run process-source.")
    for check in readiness.get("checks", []):
        if check["status"] == "fail":
            items.append(f"Fix readiness check {check['name']}: {check['detail']}")
    if report and not report.get("pass"):
        items.append("Re-run regression evaluation after fixing retrieval or citation errors.")
    if stats["open_gap_count"]:
        items.append("Review open knowledge gaps and add or approve missing source documents.")
    if not items:
        items.append("No blocking incident detected. Continue normal document intake and evaluation.")
    return items


def tail_runtime_logs(root: Path, max_files: int = 8, line_limit: int = 80) -> list[dict[str, Any]]:
    runtime_dir = root / ".runtime"
    if not runtime_dir.exists():
        return []
    paths = sorted(runtime_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    logs: list[dict[str, Any]] = []
    for path in paths[:max_files]:
        logs.append(
            {
                "file": str(path.relative_to(root)),
                "lines": tail_file(path, line_limit=line_limit),
            }
        )
    return logs


def tail_file(path: Path, line_limit: int = 80) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"Could not read log: {exc}"]
    return [redact_secrets(line) for line in text.splitlines()[-line_limit:]]


SECRET_PATTERNS = [
    re.compile(r"(KB_AUTH_TOKEN\s*[=:]\s*)\S+", re.IGNORECASE),
    re.compile(r"(POC_LLM_API_KEY\s*[=:]\s*)\S+", re.IGNORECASE),
    re.compile(r"(OPENAI_API_KEY\s*[=:]\s*)\S+", re.IGNORECASE),
    re.compile(r"(RAGFLOW_API_KEY\s*[=:]\s*)\S+", re.IGNORECASE),
]


def redact_secrets(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1[redacted]", redacted)
    return redacted
