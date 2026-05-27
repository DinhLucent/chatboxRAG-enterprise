from __future__ import annotations

from poc_workflow.qa_agent_eval import run_qa_agent_eval


def test_qa_agent_eval_contract_mode_covers_core_scenarios(tmp_path) -> None:
    report = run_qa_agent_eval(tmp_path, mode="contract", write_report=True)

    assert report["pass"] is True
    assert report["metrics"]["total_cases"] >= 6
    assert report["metrics"]["passed_cases"] == report["metrics"]["total_cases"]
    result_by_id = {result["id"]: result for result in report["results"]}
    assert result_by_id["catalog_procedures"]["format_type"] == "table"
    assert result_by_id["procedure_detail"]["format_type"] == "step_by_step"
    assert result_by_id["workflow_visual"]["format_type"] == "mermaid"
    assert result_by_id["no_active_source"]["format_type"] == "no_answer_card"
    assert result_by_id["out_of_scope"]["quality_decision"] == "scope_reject"
    assert (tmp_path / "data" / "qa_agent_eval" / "latest.json").exists()
    assert (tmp_path / "docs" / "qa-agent-eval-latest.md").exists()
