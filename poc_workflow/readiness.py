from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .auth import public_auth_status
from .evaluation import latest_report
from .manifest import ManifestStore
from .ragflow_http import RAGFlowConfig, RAGFlowHTTPClient, RAGFlowHTTPError
from .runtime import local_fallback_enabled


def deployment_readiness(root: Path, check_network: bool = False) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    auth = public_auth_status()
    add_check(
        checks,
        "operator_auth",
        auth["required"] and auth["configured"],
        "Operator auth is required and token is configured.",
        "Set KB_REQUIRE_AUTH=true and KB_AUTH_TOKEN for production.",
        warning=not auth["required"],
    )

    config = RAGFlowConfig.from_env()
    add_check(
        checks,
        "ragflow_config",
        bool(config and config.dataset_id and (config.chat_id or config.search_id)),
        "RAGFlow base URL, API key, active dataset, and chat/search id are configured.",
        "Set RAGFLOW_BASE_URL, RAGFLOW_API_KEY, RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID, and RAGFLOW_CHAT_ID or RAGFLOW_SEARCH_ID.",
    )

    if check_network and config:
        try:
            RAGFlowHTTPClient(config.base_url, config.api_key).health()
            add_check(checks, "ragflow_network", True, "RAGFlow health endpoint responded.", "")
        except RAGFlowHTTPError as exc:
            add_check(checks, "ragflow_network", False, "", f"RAGFlow health check failed: {exc}")

    mineru_command = os.getenv("MINERU_EXECUTABLE", "mineru")
    mineru_path = shutil.which(mineru_command)
    add_check(
        checks,
        "mineru_available",
        bool(mineru_path),
        f"MinerU CLI is available at {mineru_path}.",
        "Install MinerU or configure MINERU_EXECUTABLE before ingesting PDF/Excel/image sources.",
        warning=True,
    )

    records = ManifestStore(root).load()
    active_records = [record for record in records if record.status == "active"]
    add_check(
        checks,
        "active_documents",
        bool(active_records),
        f"{len(active_records)} active document(s) are approved.",
        "Approve at least one pending_review document before enabling users.",
    )

    report = latest_report(root)
    add_check(
        checks,
        "latest_evaluation",
        bool(report and report.get("pass")),
        "Latest regression evaluation passed.",
        "Run python -m poc_workflow evaluate --provider ragflow or --provider local for smoke verification.",
    )

    add_check(
        checks,
        "local_fallback_disabled",
        not local_fallback_enabled(),
        "Local fallback is disabled for production fail-closed behavior.",
        "Set KB_ENABLE_LOCAL_FALLBACK=false in production.",
        warning=local_fallback_enabled(),
    )

    ready = not any(check["status"] == "fail" for check in checks)
    return {
        "ready": ready,
        "checks": checks,
        "active_document_count": len(active_records),
        "latest_evaluation": report,
    }


def add_check(
    checks: list[dict[str, str]],
    name: str,
    passed: bool,
    pass_detail: str,
    fail_detail: str,
    warning: bool = False,
) -> None:
    if passed:
        status = "pass"
        detail = pass_detail
    elif warning:
        status = "warn"
        detail = fail_detail
    else:
        status = "fail"
        detail = fail_detail
    checks.append({"name": name, "status": status, "detail": detail})
