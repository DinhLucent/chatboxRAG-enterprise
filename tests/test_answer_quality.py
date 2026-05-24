from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from poc_workflow.llm import LLMError, OpenAICompatibleConfig
from poc_workflow.pipeline import approve_record, process_sources
from poc_workflow.rag_index import LocalRagIndex
from poc_workflow.text_cleaning import contains_raw_markup, clean_retrieval_text
from poc_workflow.user_chat import format_user_answer
from poc_workflow.webapp import create_app


DIRTY_MARKUP = """
<table>
  <tr>
    <th rowspan="4" colspan="5"><p><img src="images/logo.png"/></p></th>
    <th colspan="21"><p>QUY TRINH KIEM SOAT RUI RO VA SU CO</p></th>
  </tr>
  <tr><td colspan="2"><p>Ma tai lieu</p></td><td colspan="2"><p>PD-IC-A-046</p></td></tr>
  <tr><td><p></p></td><td><p></p></td><td><p></p></td></tr>
</table>

<h2>Trinh tu xu ly su co</h2>
<table>
  <tr><td>1</td><td>Tiep nhan thong tin su co va ghi nhan vao ticket.</td></tr>
  <tr><td>2</td><td>Danh gia muc do anh huong, khoanh vung rui ro va thong bao Truong phong Ky thuat.</td></tr>
  <tr><td>3</td><td>Thuc hien bien phap khac phuc, cap nhat ket qua va luu ho so su co.</td></tr>
</table>
"""


RAW_MARKERS = ("<table", "<tr", "<td", "<th", "<img", "rowspan", "colspan", "src=")


def write_dirty_procedure(root: Path) -> None:
    path = root / "source" / "technical" / "procedure" / "KT-FAQ-008_v1.0.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DIRTY_MARKUP, encoding="utf-8")
    path.with_name(path.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "KT-FAQ-008",
                "title": "PD IC A 046. Rev 03. Quy trinh kiem soat rui ro va su co",
                "department": "technical",
                "category": "faq_troubleshooting",
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2025-01-01",
                "review_at": "2025-12-31",
                "owner": "Phong Ky thuat",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_rank_source(
    root: Path,
    *,
    doc_id: str,
    title: str,
    category: str,
    filename: str,
    body: str,
) -> None:
    path = root / "source" / "technical" / category / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.with_name(path.stem + ".metadata.json").write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "title": title,
                "department": "technical",
                "category": category,
                "source_type": "internal_procedure",
                "language": "vi",
                "version": "1.0",
                "effective_from": "2025-01-01",
                "review_at": "2025-12-31",
                "owner": "Phong Ky thuat",
                "access_group": "technical",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def assert_no_raw_markup(value: str) -> None:
    lowered = value.lower()
    assert not any(marker in lowered for marker in RAW_MARKERS), value


def test_clean_retrieval_text_removes_table_markup_but_keeps_business_content() -> None:
    cleaned = clean_retrieval_text(DIRTY_MARKUP)

    assert "Trinh tu xu ly su co" in cleaned
    assert "Tiep nhan thong tin su co" in cleaned
    assert "luu ho so su co" in cleaned
    assert not contains_raw_markup(cleaned)
    assert_no_raw_markup(cleaned)


def test_retrieval_prefers_business_content_over_aggregate_document_list(tmp_path: Path) -> None:
    aggregate_rows = "\n".join(
        f"{index}. Quy trinh | Su co | Ky thuat | Tinh trang da ban hanh"
        for index in range(40)
    )
    write_rank_source(
        tmp_path,
        doc_id="KT-QT-LIST",
        title="Tong hop danh sach quy dinh quy trinh huong dan",
        category="procedure",
        filename="KT-QT-LIST_v1.0.md",
        body=f"# Tong hop danh sach quy dinh quy trinh huong dan\n\n{aggregate_rows}",
    )
    write_rank_source(
        tmp_path,
        doc_id="KT-FAQ-008",
        title="PD IC A 046. Quy trinh kiem soat rui ro va su co",
        category="faq_troubleshooting",
        filename="KT-FAQ-008_v1.0.md",
        body=(
            "# Quy trinh kiem soat rui ro va su co\n\n"
            "6. Noi dung cong viec\n\n"
            "Khi su co da xay ra, bo phan lien quan tiep nhan thong tin, danh gia muc do anh huong, "
            "de xuat phuong an xu ly su co va luu ho so sau khi hoan thanh."
        ),
    )
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-QT-LIST", "1.0", "Lead")
    approve_record(tmp_path, "KT-FAQ-008", "1.0", "Lead")

    hits = LocalRagIndex(tmp_path).search("Quy trinh xu ly su co cua Ky Thuat?", category="procedure", limit=3)

    assert hits
    assert hits[0].doc_id == "KT-FAQ-008"
    assert "Tong hop danh sach" not in hits[0].text


def test_user_answer_formatter_normalizes_llm_markdown_headings_without_wrapping_again() -> None:
    answer = (
        "**Tom tắt:** Quy trinh yeu cau tiep nhan va xu ly su co.\n\n"
        "**Các bước/ Nội dung chính:**\n"
        "1. Tiep nhan su co.\n"
        "2. Luu ho so.\n\n"
        "**Nguồn:**\nKT-FAQ-008 v1.0"
    )
    citations = [{"doc_id": "KT-FAQ-008", "version": "1.0", "title": "Quy trinh", "excerpt": "noi dung"}]

    formatted = format_user_answer(answer, citations, "steps")

    assert formatted.count("Tóm tắt:") == 1
    assert "**Tom tắt:**" not in formatted
    assert "Tóm tắt: **" not in formatted
    assert formatted.startswith("### Tóm tắt:")


def test_user_chat_fallback_is_clean_and_audited_when_llm_fails(tmp_path: Path, monkeypatch) -> None:
    write_dirty_procedure(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-FAQ-008", "1.0", "Lead")

    def fake_config(root: Path) -> OpenAICompatibleConfig:
        return OpenAICompatibleConfig(
            api_key="local",
            model="quality-test-model",
            base_url="http://127.0.0.1:3001/v1",
            provider="freellmapi",
            source="test",
        )

    def failing_answer(self, query, hits, answer_style="brief", extra_instruction=None) -> str:
        raise LLMError("provider timeout")

    monkeypatch.setattr("poc_workflow.chatbot.resolve_llm_config", fake_config)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.answer", failing_answer)

    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/user/chat",
        json={
            "query": "Quy trinh xu ly su co cua Ky Thuat?",
            "template_id": "procedure_steps",
            "answer_style": "steps",
            "session_id": "quality-session",
            "use_llm": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_source"] == "fallback_clean_excerpt"
    assert body["llm_used"] is False
    assert body["llm_error"] == "provider timeout"
    assert body["fallback_reason"] == "llm_error"
    assert_no_raw_markup(body["answer"])
    assert body["citations"]
    assert all(set(citation) == {"title", "doc_id", "version", "excerpt"} for citation in body["citations"])
    for citation in body["citations"]:
        assert_no_raw_markup(citation["excerpt"])
    assert any("trich doan da lam sach" in step["detail"].lower() for step in body["trace_steps"])

    latest_query = client.get("/api/queries").json()[0]
    assert latest_query["llm_used"] == 0
    assert latest_query["llm_error"] == "provider timeout"
    assert latest_query["answer_source"] == "fallback_clean_excerpt"
    assert latest_query["llm_provider"] == "freellmapi"
    assert latest_query["llm_model"] == "quality-test-model"


def test_user_chat_uses_llm_and_retries_dirty_model_answer(tmp_path: Path, monkeypatch) -> None:
    write_dirty_procedure(tmp_path)
    process_sources(tmp_path)
    approve_record(tmp_path, "KT-FAQ-008", "1.0", "Lead")
    calls: list[str | None] = []

    def fake_config(root: Path) -> OpenAICompatibleConfig:
        return OpenAICompatibleConfig(
            api_key="local",
            model="quality-test-model",
            base_url="http://127.0.0.1:3001/v1",
            provider="freellmapi",
            source="test",
        )

    def fake_answer(self, query, hits, answer_style="brief", extra_instruction=None) -> str:
        calls.append(extra_instruction)
        if extra_instruction is None:
            return "<table><tr><td>raw</td></tr></table>"
        return (
            "Tom tat:\nQuy trinh yeu cau tiep nhan, danh gia va khac phuc su co.\n\n"
            "Cac buoc / Noi dung chinh:\n"
            "1. Tiep nhan thong tin su co va ghi nhan ticket.\n"
            "2. Danh gia muc do anh huong va thong bao Truong phong Ky thuat.\n"
            "3. Cap nhat ket qua va luu ho so su co.\n\n"
            "Nguon:\nKT-FAQ-008 v1.0"
        )

    monkeypatch.setattr("poc_workflow.chatbot.resolve_llm_config", fake_config)
    monkeypatch.setattr("poc_workflow.llm.OpenAICompatibleClient.answer", fake_answer)

    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/user/chat",
        json={
            "query": "Quy trinh xu ly su co cua Ky Thuat?",
            "answer_style": "steps",
            "session_id": "quality-llm-session",
            "use_llm": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [None, "clean_answer"]
    assert body["answer_source"] == "llm"
    assert body["llm_used"] is True
    assert body["llm_error"] is None
    assert body["fallback_reason"] is None
    assert_no_raw_markup(body["answer"])
    assert any("LLM" in step["detail"] for step in body["trace_steps"])

    latest_query = client.get("/api/queries").json()[0]
    assert latest_query["llm_used"] == 1
    assert latest_query["answer_source"] == "llm"
    assert latest_query["llm_provider"] == "freellmapi"
    assert latest_query["llm_model"] == "quality-test-model"
