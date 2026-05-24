from __future__ import annotations

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
