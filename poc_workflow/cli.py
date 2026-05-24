from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .chatbot import apply_feedback, ask
from .data_maintenance import (
    apply_taxonomy_remediation,
    audit_manifest_taxonomy,
    backfill_missing_qa_reports,
    plan_taxonomy_remediation,
)
from .database import QualityDatabase
from .evaluation import run_evaluation
from .intake import prepare_inbox, requeue_ocr_required
from .operations import diagnostic_snapshot, record_incident
from .pipeline import (
    approve_record,
    init_workspace,
    manifest_summary,
    process_sources,
    rebuild_indexes,
    retire_record,
)
from .quality_gate import run_quality_gate
from .ragflow_http import bootstrap_ragflow_resources, sync_active_to_ragflow
from .readiness import deployment_readiness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Governed RAG POC workflow CLI")
    parser.add_argument("--root", default=".", help="Workspace root. Defaults to current directory.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create POC directories, taxonomy, and SQLite schema.")
    init.add_argument("--with-sample", action="store_true", help="Create a sample technical procedure source file.")

    prepare = sub.add_parser("prepare-inbox", help="Draft metadata for files dropped into inbox/ and copy them into source/.")
    prepare.add_argument("--dry-run", action="store_true", help="Preview metadata drafts without copying files.")

    requeue_ocr = sub.add_parser("requeue-ocr-required", help="Move a small batch from inbox/*/ocr_required back to the active inbox.")
    requeue_ocr.add_argument("--limit", type=int, default=1, help="Files to requeue. Default 1, maximum 5.")
    requeue_ocr.add_argument(
        "--category",
        default="procedure",
        choices=["procedure", "vendor_document", "form_checklist", "faq_troubleshooting", "all"],
        help="Category to requeue. Default procedure; use all only for small mixed batches.",
    )
    requeue_ocr.add_argument("--dry-run", action="store_true", help="Preview selected files without moving them.")

    process = sub.add_parser("process-source", help="Convert and validate source files into pending_review records.")
    process.add_argument("--limit", type=int, help="Process at most this many new/changed source files.")
    process.add_argument("--source-path", action="append", help="Process only this source file path. Can be repeated.")

    ocr_process = sub.add_parser("process-ocr-required", help="Requeue and process a small OCR-required batch.")
    ocr_process.add_argument("--limit", type=int, default=1, help="Files to requeue and process. Default 1, maximum 5.")
    ocr_process.add_argument(
        "--category",
        default="procedure",
        choices=["procedure", "vendor_document", "form_checklist", "faq_troubleshooting", "all"],
        help="Category to process. Default procedure; use all only for small mixed batches.",
    )
    ocr_process.add_argument("--dry-run", action="store_true", help="Preview selected files without moving or processing.")

    approve = sub.add_parser("approve", help="Approve a pending_review record into the active index.")
    approve.add_argument("doc_id")
    approve.add_argument("version")
    approve.add_argument("--approved-by", required=True)

    retire = sub.add_parser("retire", help="Retire an existing manifest record.")
    retire.add_argument("doc_id")
    retire.add_argument("version")
    retire.add_argument("--reason", required=True)

    sub.add_parser("rebuild-index", help="Rebuild active/archive indexes from manifest and normalized files.")
    sub.add_parser("manifest", help="Show manifest summary.")

    sync = sub.add_parser("sync-ragflow", help="Upload active normalized Markdown files to a RAGFlow dataset.")
    sync.add_argument("--base-url", default=os.getenv("RAGFLOW_BASE_URL"))
    sync.add_argument("--api-key", default=os.getenv("RAGFLOW_API_KEY"))
    sync.add_argument("--dataset-id", default=os.getenv("RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID"))
    sync.add_argument("--delete-all", action="store_true", help="Delete all dataset documents before upload.")
    sync.add_argument("--no-parse", action="store_true", help="Upload documents but do not request parsing.")

    bootstrap = sub.add_parser("bootstrap-ragflow", help="Create or find the RAGFlow dataset and chat assistant.")
    bootstrap.add_argument("--base-url", default=os.getenv("RAGFLOW_BASE_URL"))
    bootstrap.add_argument("--api-key", default=os.getenv("RAGFLOW_API_KEY"))
    bootstrap.add_argument("--dataset-name", default=os.getenv("RAGFLOW_TECHNICAL_ACTIVE_DATASET_NAME", "technical_active"))
    bootstrap.add_argument("--chat-name", default=os.getenv("RAGFLOW_CHAT_NAME", "technical_procedure_chat"))
    bootstrap.add_argument("--llm-id", default=os.getenv("RAGFLOW_BOOTSTRAP_LLM_ID"))
    bootstrap.add_argument("--no-chat", action="store_true")

    ask_cmd = sub.add_parser("ask", help="Ask the local POC chatbot over active documents.")
    ask_cmd.add_argument("query")
    ask_cmd.add_argument("--user-id")
    ask_cmd.add_argument("--provider", choices=["auto", "ragflow", "local"], default="auto")
    ask_cmd.add_argument("--use-llm", action="store_true", help="Use an OpenAI-compatible LLM after retrieval.")

    feedback = sub.add_parser("feedback", help="Attach feedback to a query log and create a knowledge gap if needed.")
    feedback.add_argument("query_log_id", type=int)
    feedback.add_argument("feedback", choices=["correct", "wrong", "missing_source", "wrong_source", "no_answer"])

    evaluate = sub.add_parser("evaluate", help="Run regression questions and report POC quality KPIs.")
    evaluate.add_argument("--cases", help="JSON cases path. Defaults to eval/regression_cases.json.")
    evaluate.add_argument("--provider", choices=["auto", "ragflow", "local"], default="local")
    evaluate.add_argument("--use-llm", action="store_true")
    evaluate.add_argument("--latency-target-ms", type=int, default=12_000)

    readiness = sub.add_parser("readiness", help="Check production deployment readiness.")
    readiness.add_argument("--check-network", action="store_true", help="Call RAGFlow health endpoint.")

    quality_gate = sub.add_parser("quality-gate", help="Run the production workflow quality gate.")
    quality_gate.add_argument("--mode", choices=["local", "production"], default="local")
    quality_gate.add_argument("--provider", choices=["auto", "ragflow", "local"], default="local")
    quality_gate.add_argument("--cases", help="Quality gate case suite path. Defaults to eval/quality_gate_cases.json.")
    quality_gate.add_argument("--check-network", action="store_true", help="Check networked services in readiness.")
    quality_gate.add_argument("--keep-sandbox", action="store_true", help="Keep .quality-sandbox run directory after pass.")
    quality_gate.add_argument("--skip-pytest", action="store_true", help="Skip the unit/integration pytest gate.")
    quality_gate.add_argument("--skip-evaluation", action="store_true", help="Skip the regression retrieval gate.")
    quality_gate.add_argument("--latency-target-ms", type=int, default=12_000)

    sub.add_parser("gaps", help="List knowledge gaps.")
    sub.add_parser("queries", help="List query logs.")
    incidents = sub.add_parser("incidents", help="List operational incidents.")
    incidents.add_argument("--status", choices=["open", "resolved", "ignored"])
    incidents.add_argument("--limit", type=int, default=100)

    incident = sub.add_parser("incident", help="Create an operational incident.")
    incident.add_argument("severity", choices=["info", "warning", "error", "critical"])
    incident.add_argument("component")
    incident.add_argument("title")
    incident.add_argument("--detail", required=True)

    resolve = sub.add_parser("resolve-incident", help="Resolve or ignore an operational incident.")
    resolve.add_argument("incident_id", type=int)
    resolve.add_argument("--status", choices=["resolved", "ignored"], default="resolved")

    diagnostics = sub.add_parser("diagnostics", help="Export a diagnostic snapshot for engineers or AI agents.")
    diagnostics.add_argument("--no-logs", action="store_true", help="Skip runtime log tails.")

    backfill_qa = sub.add_parser("backfill-qa-reports", help="Backfill missing Markdown QA reports for manifest records.")
    backfill_qa.add_argument("--limit", type=int, help="Backfill at most this many records.")
    backfill_qa.add_argument("--dry-run", action="store_true", help="Preview records without writing reports or manifest updates.")
    backfill_qa.add_argument(
        "--status",
        action="append",
        choices=["active", "pending_review", "archived", "retired", "failed_review"],
        help="Record status to include. Can be repeated. Defaults to active and pending_review.",
    )

    taxonomy_audit = sub.add_parser("audit-taxonomy", help="Audit manifest taxonomy and doc_id prefix consistency.")
    taxonomy_audit.add_argument(
        "--status",
        action="append",
        choices=["active", "pending_review", "archived", "retired", "failed_review"],
        help="Record status to include. Can be repeated. Defaults to active and pending_review.",
    )
    taxonomy_audit.add_argument("--no-report", action="store_true", help="Do not write JSON/Markdown audit reports.")

    taxonomy_plan = sub.add_parser("plan-taxonomy-remediation", help="Create a safe taxonomy remediation plan.")
    taxonomy_plan.add_argument(
        "--status",
        action="append",
        choices=["active", "pending_review", "archived", "retired", "failed_review"],
        help="Record status to include. Can be repeated. Defaults to active and pending_review.",
    )
    taxonomy_plan.add_argument("--no-report", action="store_true", help="Do not write JSON/Markdown plan reports.")

    taxonomy_apply = sub.add_parser("apply-taxonomy-remediation", help="Apply safe pending-review taxonomy remediations.")
    taxonomy_apply.add_argument("--apply", action="store_true", help="Write changes. Without this flag, performs a dry run.")
    taxonomy_apply.add_argument("--limit", type=int, help="Apply at most this many safe actions.")
    taxonomy_apply.add_argument(
        "--status",
        action="append",
        choices=["active", "pending_review", "archived", "retired", "failed_review"],
        help="Record status to include. Defaults to active and pending_review; only auto-safe pending_review records are changed.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        result: Any
        if args.command == "init":
            init_workspace(root, with_sample=args.with_sample)
            result = {"ok": True, "root": str(root), "sample_created": args.with_sample}
        elif args.command == "prepare-inbox":
            init_workspace(root)
            result = prepare_inbox(root, dry_run=args.dry_run)
        elif args.command == "requeue-ocr-required":
            init_workspace(root)
            category = None if args.category == "all" else args.category
            result = requeue_ocr_required(root, limit=args.limit, category=category, dry_run=args.dry_run)
        elif args.command == "process-source":
            source_paths = [Path(path) for path in args.source_path] if args.source_path else None
            records = process_sources(root, limit=args.limit, source_paths=source_paths)
            result = {"processed": [record.to_dict() for record in records]}
        elif args.command == "process-ocr-required":
            init_workspace(root)
            category = None if args.category == "all" else args.category
            requeue_result = requeue_ocr_required(root, limit=args.limit, category=category, dry_run=args.dry_run)
            if args.dry_run or not requeue_result["moved"]:
                result = {"requeue": requeue_result, "prepared": None, "processed": []}
            else:
                prepared = prepare_inbox(root)
                prepared_source_paths = [Path(entry["source_path"]) for entry in prepared.get("prepared", [])]
                records = process_sources(root, limit=args.limit, source_paths=prepared_source_paths)
                result = {
                    "requeue": requeue_result,
                    "prepared": prepared,
                    "processed": [record.to_dict() for record in records],
                }
        elif args.command == "approve":
            record = approve_record(root, args.doc_id, args.version, args.approved_by)
            result = record.to_dict()
        elif args.command == "retire":
            record = retire_record(root, args.doc_id, args.version, args.reason)
            result = record.to_dict()
        elif args.command == "rebuild-index":
            rebuild_indexes(root)
            result = {"ok": True}
        elif args.command == "sync-ragflow":
            if not args.base_url or not args.api_key or not args.dataset_id:
                raise ValueError(
                    "sync-ragflow requires --base-url, --api-key, and --dataset-id "
                    "or RAGFLOW_BASE_URL, RAGFLOW_API_KEY, RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID"
                )
            result = sync_active_to_ragflow(
                root,
                args.base_url,
                args.api_key,
                args.dataset_id,
                delete_all=args.delete_all,
                parse_after_upload=not args.no_parse,
            )
        elif args.command == "bootstrap-ragflow":
            if not args.base_url or not args.api_key:
                raise ValueError("bootstrap-ragflow requires --base-url and --api-key or RAGFLOW_BASE_URL and RAGFLOW_API_KEY")
            result = bootstrap_ragflow_resources(
                args.base_url,
                args.api_key,
                dataset_name=args.dataset_name,
                chat_name=args.chat_name,
                llm_id=args.llm_id,
                create_chat=not args.no_chat,
            )
        elif args.command == "manifest":
            result = manifest_summary(root)
        elif args.command == "ask":
            result = ask(root, args.query, user_id=args.user_id, use_llm=args.use_llm, provider=args.provider)
        elif args.command == "feedback":
            result = apply_feedback(root, args.query_log_id, args.feedback)
        elif args.command == "evaluate":
            result = run_evaluation(
                root,
                cases_path=args.cases,
                provider=args.provider,
                use_llm=args.use_llm,
                latency_target_ms=args.latency_target_ms,
            )
        elif args.command == "readiness":
            result = deployment_readiness(root, check_network=args.check_network)
        elif args.command == "quality-gate":
            result = run_quality_gate(
                root,
                mode=args.mode,
                cases_path=args.cases,
                provider=args.provider,
                check_network=args.check_network,
                keep_sandbox=args.keep_sandbox,
                run_pytest=not args.skip_pytest,
                run_regression=not args.skip_evaluation,
                latency_target_ms=args.latency_target_ms,
            )
            write_json_output(result)
            return 0 if result.get("status") == "accepted" else 1
        elif args.command == "gaps":
            result = QualityDatabase(root).list_gaps()
        elif args.command == "queries":
            result = QualityDatabase(root).list_queries()
        elif args.command == "incidents":
            result = QualityDatabase(root).list_incidents(status=args.status, limit=args.limit)
        elif args.command == "incident":
            incident_id = record_incident(
                root,
                args.severity,
                args.component,
                args.title,
                args.detail,
            )
            result = {"incident_id": incident_id}
        elif args.command == "resolve-incident":
            result = QualityDatabase(root).resolve_incident(args.incident_id, args.status)
        elif args.command == "diagnostics":
            result = diagnostic_snapshot(root, include_logs=not args.no_logs)
        elif args.command == "backfill-qa-reports":
            result = backfill_missing_qa_reports(
                root,
                statuses=set(args.status) if args.status else None,
                limit=args.limit,
                dry_run=args.dry_run,
            )
        elif args.command == "audit-taxonomy":
            result = audit_manifest_taxonomy(
                root,
                statuses=set(args.status) if args.status else None,
                write_report=not args.no_report,
            )
        elif args.command == "plan-taxonomy-remediation":
            result = plan_taxonomy_remediation(
                root,
                statuses=set(args.status) if args.status else None,
                write_report=not args.no_report,
            )
        elif args.command == "apply-taxonomy-remediation":
            result = apply_taxonomy_remediation(
                root,
                statuses=set(args.status) if args.status else None,
                dry_run=not args.apply,
                limit=args.limit,
            )
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
        write_json_output(result)
        return 0
    except Exception as exc:
        write_json_output({"ok": False, "error": str(exc)})
        return 1


def write_json_output(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
