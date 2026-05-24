from __future__ import annotations

import json
from pathlib import Path

from poc_workflow.evaluation import latest_report, run_evaluation
from poc_workflow.pipeline import approve_record, init_workspace, process_sources


def test_evaluation_reports_kpis_and_saves_latest(tmp_path: Path) -> None:
    init_workspace(tmp_path, with_sample=True)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-003", "1.0", "Lead")

    report = run_evaluation(tmp_path, provider="local")

    assert report["pass"] is True
    assert report["metrics"]["top3_doc_hit_rate"] == 1
    assert report["metrics"]["citation_accuracy"] == 1
    assert report["metrics"]["no_answer_accuracy"] == 1
    assert report["results"][0]["query_log_id"]
    assert latest_report(tmp_path)["finished_at"] == report["finished_at"]


def test_evaluation_checks_answer_quality_and_clarification(tmp_path: Path) -> None:
    init_workspace(tmp_path, with_sample=True)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-003", "1.0", "Lead")
    cases = tmp_path / "eval" / "answer_quality_cases.json"
    cases.write_text(
        json.dumps(
            [
                {
                    "id": "incident-user-chat-visual",
                    "query": "Trong quy trình xử lý sự cố kỹ thuật, quy trình như thế nào?",
                    "should_answer": True,
                    "expected_doc_ids": ["KT-QT-003"],
                    "answer_style": "brief",
                    "user_chat": True,
                    "expected_answer_terms": ["Tóm tắt", "Các bước", "Nguồn"],
                    "source_support_terms": ["ticket", "dong ticket"],
                    "forbidden_answer_terms": ["<table", "rowspan"],
                },
                {
                    "id": "ambiguous-asks-follow-up",
                    "query": "Quy trình này gồm những bước nào?",
                    "should_answer": False,
                    "user_chat": True,
                    "should_clarify": True,
                    "expected_answer_terms": ["mã hoặc tên tài liệu"],
                    "forbidden_answer_terms": ["Không tìm thấy căn cứ"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_evaluation(tmp_path, cases_path=cases, provider="local")

    assert report["pass"] is True
    assert report["metrics"]["answer_quality_accuracy"] == 1
    assert report["metrics"]["clarification_accuracy"] == 1
    assert all(result["answer_quality_ok"] for result in report["results"])
