from __future__ import annotations

from pathlib import Path

from poc_workflow.user_chat_render_smoke import (
    find_browser,
    render_harness_html,
    sample_public_citation_payload,
    sample_result_payload,
    sample_table_result_payload,
)


def test_user_chat_render_smoke_harness_contains_required_ui_blocks(tmp_path: Path) -> None:
    html = render_harness_html(Path.cwd())
    workflow = sample_result_payload()
    table = sample_table_result_payload()

    assert "sampleResult" in html
    assert "sampleTableResult" in html
    assert "renderStructuredAnswer" in html
    assert "renderSources" in html
    assert "renderTrace" in html
    assert "evidence_pack" in html
    assert "sampleCitationPreview" in html
    assert "/api/user/documents/" in html
    assert workflow["format_type"] == "mermaid"
    assert workflow["evidence_pack"]["verified_evidence"]
    assert table["format_type"] == "table"
    assert table["evidence_pack"]["verified_evidence"]
    assert table["structured_answer"]["markdown"]
    preview = sample_public_citation_payload()
    assert any(line["highlight"] for line in preview["preview"]["lines"])
    assert preview["preview"]["locator_status"] == "exact"
    assert preview["source_file"]["download_url"] == "/api/user/documents/KT-QT-CTX/1.0/source-file"


def test_user_chat_render_smoke_browser_discovery_is_non_throwing() -> None:
    browser = find_browser()

    assert browser is None or browser.exists()
