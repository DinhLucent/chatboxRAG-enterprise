from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .chatbot import NO_SOURCE_ANSWER, ask
from .utils import utc_now, write_json


DEFAULT_CASES_PATH = Path("eval") / "regression_cases.json"


@dataclass
class EvaluationCase:
    id: str
    query: str
    should_answer: bool = True
    expected_doc_ids: list[str] = field(default_factory=list)
    expected_category: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationCase":
        if not data.get("id"):
            raise ValueError("Evaluation case is missing id")
        if not data.get("query"):
            raise ValueError(f"Evaluation case {data.get('id')} is missing query")
        expected_doc_ids = data.get("expected_doc_ids") or []
        if not isinstance(expected_doc_ids, list):
            raise ValueError(f"Evaluation case {data['id']} expected_doc_ids must be a list")
        return cls(
            id=str(data["id"]),
            query=str(data["query"]),
            should_answer=bool(data.get("should_answer", True)),
            expected_doc_ids=[str(doc_id) for doc_id in expected_doc_ids],
            expected_category=data.get("expected_category"),
        )


def load_cases(root: Path, cases_path: str | Path | None = None) -> list[EvaluationCase]:
    path = resolve_cases_path(root, cases_path)
    if not path.exists():
        raise FileNotFoundError(f"Evaluation cases not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Evaluation cases file must be a JSON array")
    return [EvaluationCase.from_dict(item) for item in data]


def resolve_cases_path(root: Path, cases_path: str | Path | None = None) -> Path:
    path = Path(cases_path) if cases_path else DEFAULT_CASES_PATH
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def run_evaluation(
    root: Path,
    cases_path: str | Path | None = None,
    provider: str = "local",
    use_llm: bool = False,
    latency_target_ms: int = 12_000,
    user_id: str = "evaluation",
) -> dict[str, Any]:
    cases = load_cases(root, cases_path)
    started_at = utc_now()
    results = [
        evaluate_case(root, case, provider, use_llm, latency_target_ms, user_id)
        for case in cases
    ]
    report = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "cases_path": str(resolve_cases_path(root, cases_path)),
        "provider": provider,
        "use_llm": use_llm,
        "latency_target_ms": latency_target_ms,
        "metrics": summarize_results(results, latency_target_ms),
        "results": results,
    }
    report["pass"] = bool(report["metrics"]["pass"])
    save_report(root, report)
    return report


def evaluate_case(
    root: Path,
    case: EvaluationCase,
    provider: str,
    use_llm: bool,
    latency_target_ms: int,
    user_id: str,
) -> dict[str, Any]:
    answer = ask(root, case.query, user_id=user_id, use_llm=use_llm, provider=provider)
    citations = answer.get("citations") or []
    doc_ids = sorted(
        {
            str(citation.get("doc_id"))
            for citation in citations
            if isinstance(citation, dict) and citation.get("doc_id")
        }
    )
    expected = set(case.expected_doc_ids)
    retrieved = set(doc_ids)
    has_expected_doc = bool(expected & retrieved) if expected else None
    answer_text = str(answer.get("answer") or "")
    no_answer = not citations and NO_SOURCE_ANSWER in answer_text
    latency_ms = int(answer.get("latency_ms") or 0)

    if case.should_answer:
        citation_ok = bool(citations) if not expected else bool(has_expected_doc)
        no_answer_ok = None
    else:
        citation_ok = None
        no_answer_ok = no_answer

    latency_ok = latency_ms <= latency_target_ms
    checks = [latency_ok]
    if has_expected_doc is not None:
        checks.append(has_expected_doc)
    if citation_ok is not None:
        checks.append(citation_ok)
    if no_answer_ok is not None:
        checks.append(no_answer_ok)

    return {
        "id": case.id,
        "query": case.query,
        "should_answer": case.should_answer,
        "expected_doc_ids": case.expected_doc_ids,
        "expected_category": case.expected_category,
        "retrieved_doc_ids": doc_ids,
        "answer_has_citation": bool(citations),
        "has_expected_doc": has_expected_doc,
        "citation_ok": citation_ok,
        "no_answer_ok": no_answer_ok,
        "latency_ms": latency_ms,
        "latency_ok": latency_ok,
        "provider": answer.get("provider"),
        "query_log_id": answer.get("query_log_id"),
        "knowledge_gap_id": answer.get("knowledge_gap_id"),
        "pass": all(checks),
    }


def summarize_results(results: list[dict[str, Any]], latency_target_ms: int) -> dict[str, Any]:
    latencies = sorted(int(result["latency_ms"]) for result in results)
    top3_cases = [result for result in results if result["has_expected_doc"] is not None]
    citation_cases = [result for result in results if result["citation_ok"] is not None]
    no_answer_cases = [result for result in results if result["no_answer_ok"] is not None]
    latency_cases = [result for result in results if result["latency_ok"] is not None]
    metrics = {
        "total_cases": len(results),
        "passed_cases": sum(1 for result in results if result["pass"]),
        "top3_doc_hit_rate": rate(top3_cases, "has_expected_doc"),
        "citation_accuracy": rate(citation_cases, "citation_ok"),
        "no_answer_accuracy": rate(no_answer_cases, "no_answer_ok"),
        "latency_pass_rate": rate(latency_cases, "latency_ok"),
        "average_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "targets": {
            "top3_doc_hit_rate": 0.85,
            "citation_accuracy": 0.90,
            "no_answer_accuracy": 0.95,
            "latency_p95_ms": latency_target_ms,
        },
    }
    metrics["pass"] = (
        (metrics["top3_doc_hit_rate"] is None or metrics["top3_doc_hit_rate"] >= 0.85)
        and (metrics["citation_accuracy"] is None or metrics["citation_accuracy"] >= 0.90)
        and (metrics["no_answer_accuracy"] is None or metrics["no_answer_accuracy"] >= 0.95)
        and metrics["p95_latency_ms"] <= latency_target_ms
        and metrics["passed_cases"] == metrics["total_cases"]
    )
    return metrics


def rate(results: list[dict[str, Any]], key: str) -> float | None:
    if not results:
        return None
    return sum(1 for result in results if result[key]) / len(results)


def percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, int(round((len(values) - 1) * quantile)))
    return values[index]


def save_report(root: Path, report: dict[str, Any]) -> None:
    report_dir = root / "data" / "evaluation"
    report_dir.mkdir(parents=True, exist_ok=True)
    safe_stamp = report["finished_at"].replace(":", "-")
    write_json(report_dir / f"{safe_stamp}.json", report)
    write_json(report_dir / "latest.json", report)


def latest_report(root: Path) -> dict[str, Any] | None:
    path = root / "data" / "evaluation" / "latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
