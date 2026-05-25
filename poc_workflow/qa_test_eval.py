from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .chatbot import ask
from .text_cleaning import normalized_text
from .utils import utc_now, write_json


DEFAULT_QA_TEST_PATH = Path("QA-test") / "tech_chatbot_qa_test_cases.csv"
QA_REPORT_JSON = Path("data") / "qa_test" / "latest.json"
QA_REPORT_MARKDOWN = Path("docs") / "qa-test-latest.md"

STYLE_MAP = {
    "Ngắn gọn": "brief",
    "Checklist": "checklist",
    "Từng bước": "steps",
    "Workflow": "workflow",
    "Workflow/Mermaid": "workflow",
    "Mermaid": "workflow",
}


def run_qa_test(
    root: Path,
    *,
    cases_path: str | Path | None = None,
    provider: str = "local",
    use_llm: bool = False,
    write_report: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    path = resolve_qa_cases_path(root, cases_path)
    cases = load_qa_cases(path)
    results = [
        evaluate_qa_case(root, case, provider=provider, use_llm=use_llm)
        for case in cases
    ]
    report = {
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "cases_path": str(path),
        "provider": provider,
        "use_llm": use_llm,
        "metrics": summarize_qa_results(results),
        "results": results,
    }
    report["pass"] = bool(report["metrics"]["passed_cases"] == report["metrics"]["total_cases"])
    if write_report:
        write_qa_reports(root, report)
    return report


def resolve_qa_cases_path(root: Path, cases_path: str | Path | None = None) -> Path:
    path = Path(cases_path) if cases_path else DEFAULT_QA_TEST_PATH
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def load_qa_cases(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"QA test cases not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def evaluate_qa_case(root: Path, case: dict[str, str], *, provider: str, use_llm: bool) -> dict[str, Any]:
    style = STYLE_MAP.get(case.get("answer_style") or "", "brief")
    answer = ask(
        root,
        case.get("question") or "",
        provider=provider,
        use_llm=use_llm,
        answer_style=style,
        user_id="qa-test-eval",
    )
    answer_text = str(answer.get("answer") or "")
    citations = [citation for citation in answer.get("citations") or [] if isinstance(citation, dict)]
    expected_source = str(case.get("source_doc_id") or "")
    no_source_expected = expected_source == "NO_SOURCE" or str(case.get("evaluation_type") or "") == "no_answer"
    display_codes = sorted({str(citation.get("display_code") or "") for citation in citations if citation.get("display_code")})
    doc_ids = sorted({str(citation.get("doc_id") or "") for citation in citations if citation.get("doc_id")})
    missing_keywords = [
        keyword
        for keyword in split_keywords(case.get("must_include_keywords") or "")
        if normalized_text(keyword) not in normalized_text(answer_text)
    ]
    source_ok = not citations if no_source_expected else expected_source in display_codes
    keyword_ok = not missing_keywords
    no_source_text_ok = True
    if no_source_expected:
        no_source_text_ok = "khong tim thay can cu" in normalized_text(answer_text)
        keyword_ok = keyword_ok and no_source_text_ok
    passed = bool(source_ok and keyword_ok)
    return {
        "id": case.get("test_id"),
        "question": case.get("question"),
        "expected_source": expected_source,
        "actual_display_codes": display_codes,
        "actual_doc_ids": doc_ids,
        "citation_count": len(citations),
        "missing_keywords": missing_keywords,
        "source_ok": source_ok,
        "keyword_ok": keyword_ok,
        "pass": passed,
        "latency_ms": answer.get("latency_ms"),
        "fallback_reason": answer.get("fallback_reason"),
        "answer_excerpt": answer_text[:800],
    }


def split_keywords(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def summarize_qa_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.get("pass"))
    source_failures = sum(1 for result in results if not result.get("source_ok"))
    keyword_failures = sum(1 for result in results if not result.get("keyword_ok"))
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "pass_rate": passed / total if total else None,
        "source_failures": source_failures,
        "keyword_failures": keyword_failures,
    }


def write_qa_reports(root: Path, report: dict[str, Any]) -> None:
    write_json(root / QA_REPORT_JSON, report)
    markdown = [
        "# QA Test Latest",
        "",
        f"- Status: {'pass' if report.get('pass') else 'fail'}",
        f"- Cases: {report['metrics']['passed_cases']}/{report['metrics']['total_cases']}",
        f"- Source failures: {report['metrics']['source_failures']}",
        f"- Keyword failures: {report['metrics']['keyword_failures']}",
        "",
        "## Failed Cases",
        "",
        "| ID | Expected source | Actual source | Missing keywords |",
        "| --- | --- | --- | --- |",
    ]
    failures = [result for result in report["results"] if not result.get("pass")]
    for result in failures[:50]:
        markdown.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(result.get("id")),
                    markdown_cell(result.get("expected_source")),
                    markdown_cell(", ".join(result.get("actual_display_codes") or [])),
                    markdown_cell(", ".join(result.get("missing_keywords") or [])),
                ]
            )
            + " |"
        )
    if not failures:
        markdown.append("| None |  |  |  |")
    (root / QA_REPORT_MARKDOWN).parent.mkdir(parents=True, exist_ok=True)
    (root / QA_REPORT_MARKDOWN).write_text("\n".join(markdown) + "\n", encoding="utf-8")


def markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()
