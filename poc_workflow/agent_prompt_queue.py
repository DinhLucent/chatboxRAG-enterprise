from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .config import ALLOWED_CATEGORIES, SUPPORTED_SOURCE_SUFFIXES
from .intake import infer_version, list_inbox, unique_path
from .utils import read_json, utc_now, write_json


UPLOAD_STATUSES = {
    "queue",
    "processing",
    "done",
    "failed",
    "ocr_required",
}

MANUAL_UPLOAD_STATUSES = {
    "queue",
    "processing",
    "done",
    "failed",
    "ocr_required",
}

STATUS_ORDER = [
    "queue",
    "processing",
    "done",
    "ocr_required",
    "failed",
]

LIFECYCLE_FOLDERS = {"done", "failed", "ocr_required"}
PROMPT_TEMPLATE_VERSION = "agent-task-v1"
PROCESSING_STEP_ORDER = [
    "waiting",
    "prepare",
    "check_service",
    "submit",
    "queue",
    "parse",
    "download",
    "build_outputs",
    "qa",
    "done",
    "ocr_required",
    "failed",
]

PROCESSING_STEP_LABELS = {
    "waiting": "Waiting",
    "prepare": "Prepare",
    "check_service": "Check service",
    "submit": "Submit",
    "queue": "Queue",
    "parse": "Parse",
    "download": "Download",
    "build_outputs": "Build outputs",
    "qa": "QA check",
    "done": "Done",
    "ocr_required": "OCR required",
    "failed": "Failed",
}


def list_upload_queue(root: Path) -> dict[str, Any]:
    state = _load_state(root)
    items = [_inbox_item(file_item, state) for file_item in list_inbox(root)]
    items.extend(_processing_item(root, path, state) for path in _iter_processing_files(root))
    return {
        "items": sorted(
            items,
            key=lambda item: (STATUS_ORDER.index(item["status"]), item["file_name"], item["relative_path"]),
        ),
        "summary": _summary(items),
    }


def generate_agent_prompt(root: Path, relative_paths: list[str]) -> dict[str, Any]:
    selected_paths = _normalize_relative_paths(relative_paths)
    if not selected_paths:
        raise ValueError("relative_paths is required")

    queue = list_upload_queue(root)
    queue_items = {
        item["relative_path"]: item
        for item in queue["items"]
        if item.get("status") == "queue"
    }
    missing = [path for path in selected_paths if path not in queue_items]
    if missing:
        raise ValueError(f"Files are not in the active queue: {', '.join(missing)}")

    selected = [queue_items[path] for path in selected_paths]
    now = utc_now()
    prompt_id = _prompt_id(selected_paths, now)
    prompt = _render_prompt(selected, prompt_id, PROMPT_TEMPLATE_VERSION)

    state = _load_state(root)
    for item in selected:
        key = item["original_relative_path"]
        state["items"][key] = {
            **state["items"].get(key, {}),
            "original_relative_path": key,
            "prompt_id": prompt_id,
            "prompt_version": PROMPT_TEMPLATE_VERSION,
            "prompt": prompt,
            "file_name": item["file_name"],
            "suggested_type": item["suggested_type"],
            "version": item["version"],
            "updated_at": now,
            "error": None,
        }
    _save_state(root, state)

    return {
        "prompt_id": prompt_id,
        "prompt_version": PROMPT_TEMPLATE_VERSION,
        "prompt": prompt,
        "files": selected,
        "updated_at": now,
    }


def update_upload_status(
    root: Path,
    relative_paths: list[str],
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    selected_paths = _normalize_relative_paths(relative_paths)
    if not selected_paths:
        raise ValueError("relative_paths is required")
    if status == "active":
        raise ValueError("Upload queue cannot set Active; approve documents from the Review page")
    if status not in MANUAL_UPLOAD_STATUSES:
        raise ValueError(f"Unsupported upload queue status: {status}")

    queue = list_upload_queue(root)
    lookup: dict[str, dict[str, Any]] = {}
    for item in queue["items"]:
        lookup[item["relative_path"]] = item
        lookup[item["original_relative_path"]] = item
    missing = [path for path in selected_paths if path not in lookup]
    if missing:
        raise ValueError(f"Files are not in the upload queue: {', '.join(missing)}")

    now = utc_now()
    state = _load_state(root)
    for path in selected_paths:
        item = lookup[path]
        moved = _move_for_status(root, item, status)
        key = moved["original_relative_path"]
        state["items"][key] = {
            **state["items"].get(key, {}),
            "original_relative_path": key,
            "status": status,
            "processing_step": _default_step_for_status(status),
            "processing_step_label": PROCESSING_STEP_LABELS.get(_default_step_for_status(status)),
            "processing_detail": PROCESSING_STEP_LABELS.get(_default_step_for_status(status)),
            "current_relative_path": moved["relative_path"],
            "file_name": moved["file_name"],
            "suggested_type": moved["suggested_type"],
            "version": moved["version"],
            "updated_at": now,
            "error": error if status == "failed" else None,
        }
    _save_state(root, state)
    return list_upload_queue(root)


def record_processing_status(
    root: Path,
    relative_path: str,
    *,
    status: str,
    step: str,
    detail: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    artifact_path: str | None = None,
    qa_report_path: str | None = None,
    qa_status: str | None = None,
    qa_issues: list[str] | None = None,
    mineru_profile: dict[str, Any] | None = None,
) -> None:
    normalized = _normalize_relative_paths([relative_path])
    if not normalized:
        return
    original_relative_path = _original_relative_path(normalized[0])
    now = utc_now()
    state = _load_state(root)
    saved = state["items"].get(original_relative_path, {})
    event = {
        "step": step,
        "status": status,
        "detail": detail or PROCESSING_STEP_LABELS.get(step, step),
        "updated_at": now,
    }
    history = saved.get("processing_history")
    if not isinstance(history, list):
        history = []
    if not history or any(history[-1].get(key) != event[key] for key in ("step", "status", "detail")):
        history.append(event)

    item = {
        **saved,
        "original_relative_path": original_relative_path,
        "status": status,
        "processing_step": step,
        "processing_step_label": PROCESSING_STEP_LABELS.get(step, step),
        "processing_detail": detail or PROCESSING_STEP_LABELS.get(step, step),
        "processing_history": history[-80:],
        "updated_at": now,
        "error": error if status in {"failed", "ocr_required"} else None,
    }
    if metadata:
        item.update(
            {
                "file_name": Path(original_relative_path).name,
                "suggested_type": str(metadata.get("category") or item.get("suggested_type") or "procedure"),
                "version": str(metadata.get("version") or item.get("version") or "1.0"),
                "doc_id": metadata.get("doc_id") or item.get("doc_id"),
                "title": metadata.get("title") or item.get("title"),
            }
        )
    if artifact_path:
        item["artifact_path"] = artifact_path
    if qa_report_path:
        item["qa_report_path"] = qa_report_path
    if qa_status:
        item["qa_status"] = qa_status
    if qa_issues is not None:
        item["qa_issues"] = qa_issues
    if mineru_profile:
        item["mineru_profile"] = mineru_profile
    state["items"][original_relative_path] = item
    _save_state(root, state)


def _state_path(root: Path) -> Path:
    return root / "manifest" / "agent_prompt_queue.json"


def _load_state(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {"items": {}}
    data = read_json(path)
    items = data.get("items")
    if not isinstance(items, dict):
        return {"items": {}}
    return {"items": items}


def _save_state(root: Path, state: dict[str, Any]) -> None:
    write_json(_state_path(root), {"items": state.get("items", {})})


def _normalize_relative_paths(relative_paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in relative_paths:
        path = str(raw or "").replace("\\", "/").strip().lstrip("/")
        if not path or ".." in Path(path).parts:
            continue
        if path not in normalized:
            normalized.append(path)
    return normalized


def _inbox_item(file_item: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    relative_path = str(file_item["relative_path"])
    original_relative_path = _original_relative_path(relative_path)
    saved = state["items"].get(original_relative_path, {})
    status = _status_from_inbox_relative(relative_path)
    path = Path(file_item["path"])
    return {
        "id": f"inbox:{relative_path}",
        "source": "inbox",
        "relative_path": relative_path,
        "original_relative_path": original_relative_path,
        "file_name": str(file_item["name"]),
        "suggested_type": str(file_item["category_hint"]),
        "status": status,
        "version": str(saved.get("version") or infer_version(path) or "1.0"),
        "updated_at": str(saved.get("updated_at") or file_item["modified_at"]),
        "absolute_path": str(file_item["path"]),
        "size_bytes": int(file_item.get("size_bytes") or 0),
        "has_sidecar_metadata": bool(file_item.get("has_sidecar_metadata")),
        "prompt_id": saved.get("prompt_id"),
        "prompt_version": saved.get("prompt_version"),
        "prompt": saved.get("prompt"),
        "error": saved.get("error"),
        "processing_step": saved.get("processing_step") or _default_step_for_status(status),
        "processing_step_label": saved.get("processing_step_label")
        or PROCESSING_STEP_LABELS.get(_default_step_for_status(status)),
        "processing_detail": saved.get("processing_detail"),
        "processing_history": saved.get("processing_history") or [],
        "artifact_path": saved.get("artifact_path"),
        "qa_report_path": saved.get("qa_report_path"),
        "qa_status": saved.get("qa_status"),
        "qa_issues": saved.get("qa_issues") or [],
        "mineru_profile": saved.get("mineru_profile"),
        "doc_id": saved.get("doc_id"),
        "title": saved.get("title"),
    }


def _processing_item(root: Path, path: Path, state: dict[str, Any]) -> dict[str, Any]:
    processing_root = root / ".Workplace" / "processing"
    relative_path = path.relative_to(processing_root).as_posix()
    original_relative_path = _original_relative_path(relative_path)
    saved = state["items"].get(original_relative_path, {})
    stat = path.stat()
    return {
        "id": f"workplace:{relative_path}",
        "source": "workplace",
        "relative_path": relative_path,
        "original_relative_path": original_relative_path,
        "file_name": path.name,
        "suggested_type": _category_from_relative_path(original_relative_path),
        "status": "processing",
        "version": str(saved.get("version") or infer_version(path) or "1.0"),
        "updated_at": str(saved.get("updated_at") or _mtime_iso(stat.st_mtime)),
        "absolute_path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "has_sidecar_metadata": path.with_name(path.stem + ".metadata.json").exists(),
        "prompt_id": saved.get("prompt_id"),
        "prompt_version": saved.get("prompt_version"),
        "prompt": saved.get("prompt"),
        "error": saved.get("error"),
        "processing_step": saved.get("processing_step") or "prepare",
        "processing_step_label": saved.get("processing_step_label") or PROCESSING_STEP_LABELS["prepare"],
        "processing_detail": saved.get("processing_detail"),
        "processing_history": saved.get("processing_history") or [],
        "artifact_path": saved.get("artifact_path"),
        "qa_report_path": saved.get("qa_report_path"),
        "qa_status": saved.get("qa_status"),
        "qa_issues": saved.get("qa_issues") or [],
        "mineru_profile": saved.get("mineru_profile"),
        "doc_id": saved.get("doc_id"),
        "title": saved.get("title"),
    }


def _status_from_inbox_relative(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 2 and parts[1] in LIFECYCLE_FOLDERS:
        return parts[1]
    return "queue"


def _original_relative_path(relative_path: str) -> str:
    parts = list(Path(relative_path).parts)
    if len(parts) >= 2 and parts[1] in LIFECYCLE_FOLDERS:
        parts.pop(1)
    return Path(*parts).as_posix() if parts else relative_path


def _category_from_relative_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    categories = ALLOWED_CATEGORIES["technical"]
    if parts and parts[0] in categories:
        return parts[0]
    return "procedure"


def _move_for_status(root: Path, item: dict[str, Any], status: str) -> dict[str, Any]:
    source = Path(item["absolute_path"])
    original_relative_path = item["original_relative_path"]
    target = _target_path_for_status(root, original_relative_path, status)
    if source.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = unique_path(target)
        shutil.move(str(source), str(target))
    return _moved_item(root, target, original_relative_path, status, item)


def _target_path_for_status(root: Path, original_relative_path: str, status: str) -> Path:
    if status == "processing":
        return root / ".Workplace" / "processing" / Path(original_relative_path)
    if status == "queue":
        return root / "inbox" / Path(original_relative_path)

    parts = list(Path(original_relative_path).parts)
    categories = ALLOWED_CATEGORIES["technical"]
    if parts and parts[0] in categories:
        category = parts[0]
        tail = parts[1:]
    else:
        category = "procedure"
        tail = parts
    return root / "inbox" / category / status / Path(*tail)


def _moved_item(
    root: Path,
    path: Path,
    original_relative_path: str,
    status: str,
    previous: dict[str, Any],
) -> dict[str, Any]:
    if status == "processing":
        relative_path = path.relative_to(root / ".Workplace" / "processing").as_posix()
        source = "workplace"
    else:
        relative_path = path.relative_to(root / "inbox").as_posix()
        source = "inbox"
    return {
        **previous,
        "id": f"{source}:{relative_path}",
        "source": source,
        "relative_path": relative_path,
        "original_relative_path": original_relative_path,
        "file_name": path.name,
        "absolute_path": str(path.resolve()),
        "status": status,
    }


def _iter_processing_files(root: Path) -> list[Path]:
    processing_root = root / ".Workplace" / "processing"
    if not processing_root.exists():
        return []
    files: list[Path] = []
    for path in processing_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.endswith(".metadata.json"):
            continue
        if path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _mtime_iso(timestamp: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {status: 0 for status in STATUS_ORDER}
    for item in items:
        status = item.get("status")
        if status in summary:
            summary[status] += 1
    return summary


def _default_step_for_status(status: str) -> str:
    defaults = {
        "queue": "waiting",
        "processing": "prepare",
        "done": "done",
        "ocr_required": "ocr_required",
        "failed": "failed",
    }
    return defaults.get(status, "waiting")


def _prompt_id(relative_paths: list[str], timestamp: str) -> str:
    digest = hashlib.sha1("\n".join([timestamp, *relative_paths]).encode("utf-8")).hexdigest()[:10]
    return f"agent-task-{timestamp.replace(':', '').replace('+', 'Z')}-{digest}"


def _render_prompt(files: list[dict[str, Any]], prompt_id: str, prompt_version: str) -> str:
    file_list = "\n".join(
        [
            (
                f"{index}. `{item['relative_path']}` | batch_index: `{index}` | "
                f"suggested_type: `{item['suggested_type']}` | "
                f"version: `{item['version']}` | size: `{item['size_bytes']}` bytes | "
                f"updated_at: `{item['updated_at']}` | absolute_path: `{item['absolute_path']}`"
            )
            for index, item in enumerate(files, start=1)
        ]
    )
    return f"""# Agent Task: Xử lý tài liệu cho Chatbot phòng Kỹ thuật

## Batch xử lý
- prompt_id: `{prompt_id}`
- prompt_version: `{prompt_version}`
- total_files: `{len(files)}`

## Mục tiêu
Hãy xử lý các tài liệu được liệt kê bên dưới để chuẩn bị đưa vào chatbot nội bộ phòng Kỹ thuật.

## Danh sách file
{file_list}

## Taxonomy cần phân loại
- procedure: Tài liệu quy trình phòng Kỹ thuật
- vendor_document: Tài liệu hãng, manual, catalog, datasheet, hướng dẫn kỹ thuật
- form_checklist: Biểu mẫu, checklist, mẫu biên bản
- faq_troubleshooting: FAQ, kinh nghiệm xử lý lỗi, hướng dẫn troubleshooting

## Quy ước doc_id
- KT-QT-xxx cho tài liệu quy trình
- KT-HANG-xxx cho tài liệu hãng
- KT-BM-xxx cho biểu mẫu/checklist
- KT-FAQ-xxx cho FAQ/kinh nghiệm xử lý

## Yêu cầu xử lý
Với mỗi file, hãy thực hiện:

1. Đọc nội dung tài liệu.
2. Phân loại tài liệu theo taxonomy.
3. Đề xuất doc_id phù hợp.
4. Trích xuất metadata:
   - doc_id
   - title
   - department
   - category
   - source_type
   - language
   - version
   - status
   - owner
   - source_path
   - access_group
5. Nếu có thể, chuyển nội dung sang Markdown.
6. Kiểm tra lỗi:
   - tài liệu rỗng
   - OCR kém
   - bảng không đọc được
   - thiếu metadata
   - trùng doc_id/version
7. Trả về kết quả theo JSON chuẩn.

## Output bắt buộc

Trả về JSON array. Mỗi object tương ứng đúng một file trong batch và phải giữ nguyên `prompt_id`, `prompt_version`, `batch_index`, `file_path`.

Schema:

```json
[
  {{
    "prompt_id": "{prompt_id}",
    "prompt_version": "{prompt_version}",
    "batch_index": 1,
    "file_path": "...",
    "doc_id": "...",
    "title": "...",
    "department": "technical",
    "category": "procedure | vendor_document | form_checklist | faq_troubleshooting",
    "source_type": "...",
    "language": "vi | en | mixed",
    "version": "1.0",
    "status": "pending_review",
    "owner": "Phòng Kỹ thuật",
    "source_path": "...",
    "normalized_path": "...",
    "access_group": "technical",
    "validation_status": "pass | fail",
    "issues": [],
    "recommended_next_action": "approve_to_active | fix_metadata | reprocess"
  }}
]
```

## Nguyên tắc bắt buộc

- Không đưa tài liệu vào active nếu thiếu metadata.
- Không tự bịa nội dung không có trong tài liệu.
- Nếu không đọc được file, đánh dấu validation_status = fail.
- Nếu tài liệu là tài liệu hãng, giữ nguyên ý nghĩa kỹ thuật, chỉ tóm tắt và phân loại.
- Kết quả phải sẵn sàng để người phụ trách review trước khi đưa vào chatbot.
"""
