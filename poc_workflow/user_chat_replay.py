from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from .text_cleaning import normalized_text
from .utils import utc_now, write_json
from .webapp import create_app


DEFAULT_CASES = Path("eval") / "user_chat_orchestration_cases.json"
DEFAULT_REPORT = Path(".runtime") / "user-chat-replay.json"


def run_user_chat_replay(
    root: Path,
    *,
    cases_path: Path = DEFAULT_CASES,
    tags: list[str] | None = None,
    force_use_llm: bool | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    cases = load_cases(root / cases_path if not cases_path.is_absolute() else cases_path)
    selected = filter_cases(cases, tags or [])
    run_id = uuid.uuid4().hex[:8]
    client = TestClient(create_app(root))
    results = []
    for case in selected:
        case_result = run_case(client, case, force_use_llm=force_use_llm, run_id=run_id)
        results.append(case_result)
    report = {
        "started_at": utc_now(),
        "root": str(root),
        "cases_path": str(cases_path),
        "run_id": run_id,
        "tags": tags or [],
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "results": results,
    }
    report["pass"] = report["failed"] == 0
    report["finished_at"] = utc_now()
    write_json(root / DEFAULT_REPORT, report)
    return report


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Replay case file must contain a JSON list.")
    return [item for item in data if isinstance(item, dict)]


def filter_cases(cases: list[dict[str, Any]], tags: list[str]) -> list[dict[str, Any]]:
    if not tags:
        return cases
    wanted = set(tags)
    return [case for case in cases if wanted.intersection(set(case.get("tags") or []))]


def run_case(
    client: TestClient,
    case: dict[str, Any],
    *,
    force_use_llm: bool | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    failures: list[str] = []
    turns = []
    base_session_id = str(case.get("session_id") or f"replay-{case.get('name', 'case')}")
    session_id = f"{base_session_id}-{run_id}" if run_id else base_session_id
    env_failures = missing_required_env(case.get("requires_env"))
    failures.extend(env_failures)
    for index, turn in enumerate(case.get("turns") or [], start=1):
        payload = {
            "query": str(turn.get("query") or ""),
            "session_id": session_id,
            "answer_style": str(turn.get("answer_style") or "brief"),
        }
        if force_use_llm is not None:
            payload["use_llm"] = force_use_llm
        elif "use_llm" in turn:
            payload["use_llm"] = bool(turn.get("use_llm"))
        response = client.post("/api/user/chat", json=payload)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        turn_failures = validate_turn(turn, body, response.status_code)
        failures.extend([f"turn {index}: {failure}" for failure in turn_failures])
        turns.append(
            {
                "query": payload["query"],
                "status_code": response.status_code,
                "answer_preview": str(body.get("answer") or "")[:400],
                "action": infer_action(body),
                "block_types": block_types(body),
                "doc_ids": citation_doc_ids(body),
                "failures": turn_failures,
            }
        )
    return {
        "name": case.get("name") or session_id,
        "tags": case.get("tags") or [],
        "session_id": session_id,
        "passed": not failures,
        "failures": failures,
        "turns": turns,
    }


def missing_required_env(requirements: object) -> list[str]:
    if not isinstance(requirements, dict):
        return []
    missing = []
    for name, expected in requirements.items():
        value = os.environ.get(str(name))
        if expected == "set":
            if not value:
                missing.append(f"missing env {name}")
        elif value != str(expected):
            missing.append(f"env {name} expected {expected!r}, got {value!r}")
    return missing


def validate_turn(turn: dict[str, Any], body: dict[str, Any], status_code: int) -> list[str]:
    failures = []
    if status_code != 200:
        return [f"HTTP {status_code}"]
    expected_action = str(turn.get("expected_action") or "")
    action = infer_action(body)
    if expected_action == "answer_or_clarify":
        if action not in {"answer", "clarify"}:
            failures.append(f"expected answer_or_clarify, got {action}")
    elif expected_action and action != expected_action:
        failures.append(f"expected action {expected_action}, got {action}")
    expected_blocks = [str(item) for item in turn.get("expected_blocks") or []]
    present_blocks = set(block_types(body))
    for block_type in expected_blocks:
        if block_type not in present_blocks:
            failures.append(f"missing block {block_type}")
    expected_any = [str(item) for item in turn.get("expected_blocks_any") or []]
    if expected_any and not present_blocks.intersection(expected_any):
        failures.append(f"missing any block from {expected_any}")
    doc_ids = set(citation_doc_ids(body))
    required_doc_ids = [str(item) for item in turn.get("expected_doc_ids") or []]
    for doc_id in required_doc_ids:
        if doc_id not in doc_ids:
            failures.append(f"missing doc_id {doc_id}")
    any_doc_ids = [str(item) for item in turn.get("expected_doc_ids_any") or []]
    if any_doc_ids and not doc_ids.intersection(any_doc_ids):
        failures.append(f"missing any doc_id from {any_doc_ids}")
    answer_text = normalized_text(str(body.get("answer") or ""))
    for term in turn.get("required_terms") or []:
        if normalized_text(str(term)) not in answer_text:
            failures.append(f"missing term {term!r}")
    for term in turn.get("forbidden_terms") or []:
        if normalized_text(str(term)) in answer_text:
            failures.append(f"forbidden term {term!r}")
    if body.get("response_contract_version") and body.get("response_contract_version") != "answer_blocks.v1":
        failures.append("unexpected response_contract_version")
    return failures


def infer_action(body: dict[str, Any]) -> str:
    if body.get("needs_clarification"):
        return "clarify"
    if (body.get("quality_decision") or {}).get("decision") == "scope_reject":
        return "scope_reject"
    if body.get("format_type") == "no_answer_card":
        return "no_answer"
    if body.get("citations"):
        return "answer"
    return "unknown"


def block_types(body: dict[str, Any]) -> list[str]:
    blocks = body.get("blocks")
    if not isinstance(blocks, list):
        structured = body.get("structured_answer") if isinstance(body.get("structured_answer"), dict) else {}
        blocks = structured.get("blocks") if isinstance(structured.get("blocks"), list) else []
    types = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type"):
            types.append(str(block["type"]))
    return types


def citation_doc_ids(body: dict[str, Any]) -> list[str]:
    citations = body.get("citations") if isinstance(body.get("citations"), list) else []
    return [str(item.get("doc_id")) for item in citations if isinstance(item, dict) and item.get("doc_id")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay user-chat orchestration scenarios.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--use-llm", choices=["auto", "true", "false"], default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    force_use_llm = None
    if args.use_llm == "true":
        force_use_llm = True
    elif args.use_llm == "false":
        force_use_llm = False
    report = run_user_chat_replay(
        args.root,
        cases_path=args.cases,
        tags=args.tag,
        force_use_llm=force_use_llm,
    )
    print(json.dumps({"pass": report["pass"], "passed": report["passed"], "failed": report["failed"]}, ensure_ascii=False))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
