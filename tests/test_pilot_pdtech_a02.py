from __future__ import annotations

import json
from pathlib import Path

import pytest

from poc_workflow.converter import MinerUConverter
from poc_workflow.manifest import ManifestStore
from poc_workflow.models import ManifestRecord
from poc_workflow.pilot_pdtech_a02 import (
    PILOT_ARTIFACT_STEM,
    PILOT_DISPLAY_CODE,
    PILOT_DOC_ID,
    normalize_mineru_raw,
    pilot_paths,
    run_pdtech_a02_agent_sandbox,
    run_pdtech_a02_pilot,
    verify_normalized_markdown,
)
from poc_workflow import ragflow_http
from poc_workflow.ragflow_http import sync_active_to_ragflow


class FakeMinerUConverter:
    def __init__(self, raw_text: str | None = None) -> None:
        self.calls: list[Path] = []
        self.raw_text = raw_text or """
# PD-TECH-A-02 Rev 04 Quy trinh bao duong

## Sheet: Quy trinh

| Ma tai lieu | PD-TECH-A-02 |
| --- | --- |
| Phien ban | Rev 04 |
| Muc dich | Dam bao hoat dong bao duong duoc thuc hien dung ke hoach. |
| Trach nhiem | Ky thuat Vung thuc hien bao duong va ghi nhan ket qua. |
| Quy trinh thuc hien |  |
| Buoc 1 | Lap ke hoach bao duong tu MinerU raw |
| Buoc 2 | Thong bao khach hang va chuan bi cong cu |
| Buoc 3 | Thuc hien bao duong va ky BBDVKT |
| Ho so / bieu mau lien quan | PD-TECH-A-02/BM-06 Bien ban dich vu ky thuat |
"""

    def convert(self, source_path: Path, output_md: Path, **kwargs: object) -> Path:
        raise AssertionError("pilot must call convert_with_mineru, not legacy convert")

    def convert_with_mineru(self, source_path: Path, output_md: Path, **kwargs: object) -> Path:
        self.calls.append(source_path)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(self.raw_text.strip() + "\n", encoding="utf-8")
        artifact_root = Path(kwargs["artifact_root"])
        result_root = artifact_root / "fake-job"
        metadata_root = result_root / "mineru_artifacts" / "metadata"
        image_root = result_root / "mineru_artifacts" / "images"
        metadata_root.mkdir(parents=True, exist_ok=True)
        image_root.mkdir(parents=True, exist_ok=True)
        content_list = metadata_root / "content_list_v2.json"
        content_list.write_text(
            json.dumps(
                [
                    [
                        {
                            "type": "table",
                            "content": {
                                "table_body": "Lap ke hoach bao duong tu MinerU raw Thong bao khach hang"
                            },
                            "bbox": [10, 20, 300, 420],
                        },
                        {
                            "type": "image",
                            "content": {"image_source": {"path": "images/workflow.jpg"}},
                            "bbox": [30, 40, 160, 180],
                        },
                    ]
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (image_root / "workflow.jpg").write_bytes(b"fake-image")
        (result_root / "mineru_artifact_index.json").write_text(
            json.dumps(
                {
                    "schema_version": "mineru_artifact_index_v1",
                    "output_markdown_path": str(output_md),
                    "selected_markdown": "fake/doc.md",
                    "summary": {
                        "has_content_list": False,
                        "has_content_list_v2": True,
                        "has_middle_json": False,
                        "has_model_json": False,
                        "image_count": 1,
                        "rich_artifact_count": 2,
                    },
                    "artifacts": [
                        {"artifact_id": "mineru_markdown_selected", "type": "markdown", "path": str(output_md)},
                        {"artifact_id": "content", "type": "content_list_v2", "path": str(content_list)},
                        {"artifact_id": "image", "type": "image", "path": str(image_root / "workflow.jpg")},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return output_md

    def profile_dict(self) -> dict[str, object]:
        return {"command": "fake-mineru", "method": "auto", "backend": "pipeline"}


def write_pilot_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "QT"
    sheet.append(["Ma tai lieu", PILOT_DISPLAY_CODE])
    sheet.append(["Phien ban", "Rev 04"])
    sheet.append(["Muc dich"])
    sheet.append(["Dam bao hoat dong bao duong duoc thuc hien dung ke hoach."])
    sheet.append(["Pham vi ap dung"])
    sheet.append(["Ap dung cho thiet bi can bao duong dinh ky."])
    sheet.append(["Trach nhiem"])
    sheet.append(["Ky thuat Vung", "Thuc hien bao duong va ghi nhan ket qua."])
    sheet.append(["Quy trinh thuc hien"])
    sheet.append(["Buoc 1", "Lap ke hoach bao duong"])
    sheet.append(["Buoc 2", "Thong bao khach hang va chuan bi cong cu"])
    sheet.append(["Buoc 3", "Thuc hien bao duong va ky BBDVKT"])
    sheet.append(["Ho so / bieu mau lien quan"])
    sheet.append(["PD-TECH-A-02/BM-06", "Bien ban dich vu ky thuat"])
    sheet["A57"] = "1. Muc dich:"
    sheet["A58"] = "Dam bao hoat dong bao duong duoc thuc hien dung ke hoach."
    sheet["A61"] = "2. Pham vi ap dung"
    sheet["A62"] = "Ap dung cho thiet bi can bao duong dinh ky."
    sheet["A64"] = "3. Tai lieu vien dan, tham khao\n- Quy trinh lap dat"
    sheet["A65"] = "4. Dinh nghia, tu ngu viet tat"
    sheet["A66"] = "BBDVKT: Bien ban dich vu ky thuat"
    sheet["A68"] = "5. Trach nhiem / Bo phan lien quan."
    sheet["A69"] = "Ky thuat Vung thuc hien bao duong va ghi nhan ket qua."
    sheet["A77"] = "6. Noi dung cong viec."
    sheet["A78"] = "STT"
    sheet["H78"] = "RACI"
    sheet["Y78"] = "Ket qua"
    sheet["AA78"] = "Tan suat"
    sheet["AD78"] = "Noi dung chi tiet"
    sheet["AE78"] = "Bieu mau"
    sheet["A85"] = 1
    sheet["H85"] = "R"
    sheet["Y85"] = "Ke hoach bao duong"
    sheet["AA85"] = "Hang thang"
    sheet["AD85"] = "Lap ke hoach bao duong tu workbook."
    sheet["AE85"] = "PD-TECH-A-02/BM-05"
    sheet["A88"] = 2
    sheet["H88"] = "R"
    sheet["Y88"] = "Lich bao duong dinh ky"
    sheet["AD88"] = "Thong bao khach hang va chuan bi cong cu."
    sheet["A91"] = 3
    sheet["H91"] = "R"
    sheet["Y91"] = "BBDVKT"
    sheet["AD91"] = "Thuc hien bao duong va ky BBDVKT."
    sheet["AE91"] = "PD-TECH-A-02/BM-06"
    sheet["A129"] = "7. Ho so, tai lieu dinh kem"
    sheet["A130"] = "7.1. PD-TECH-A-02/BM-05"
    sheet["E130"] = ": Ke hoach bao duong"
    sheet["A131"] = "7.2. PD-TECH-A-02/BM-06"
    sheet["E131"] = ": Lich bao duong dinh ky"
    workbook.save(path)


def write_pilot_pdf(path: Path) -> None:
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    pdf.drawString(72, 720, "PD-TECH-A-02 Rev 04 Quy trinh bao duong")
    pdf.drawString(72, 700, "Ban in tham khao cho quy trinh bao duong.")
    pdf.save()


def test_pdtech_a02_pilot_builds_single_approved_primary_record(tmp_path: Path) -> None:
    xlsx = tmp_path / "root_source" / "technical" / "PD-TECH-A-02.Rev 04. Quy trinh bao duong_29.05.23.xlsx"
    pdf = tmp_path / "root_source" / "technical" / "PD-TECH-A-02. Rev 04. Quy trinh bao duong.pdf"
    write_pilot_xlsx(xlsx)
    write_pilot_pdf(pdf)
    duplicate_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-401_v1.0.md"
    duplicate_md.parent.mkdir(parents=True, exist_ok=True)
    duplicate_md.write_text("# Duplicate\n\nPDF duplicate content.", encoding="utf-8")
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id="KT-QT-401",
                title="PD TECH A 02. Rev 04. Quy trinh bao duong",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="1.0",
                status="active",
                effective_from="2026-01-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path=str(pdf),
                normalized_path=str(duplicate_md),
                content_hash="duplicate",
                extra={"display_code": PILOT_DISPLAY_CODE},
            )
        ]
    )

    fake_mineru = FakeMinerUConverter()
    result = run_pdtech_a02_pilot(
        tmp_path,
        approve_review=True,
        reviewer="pilot-reviewer",
        converter=fake_mineru,
    )

    assert result["status"] == "active"
    assert result["primary_source"] == "xlsx"
    assert result["raw_converter"] == "mineru"
    paths = pilot_paths(tmp_path)
    assert paths.probe_report.exists()
    raw_path = paths.converted_raw / f"{PILOT_ARTIFACT_STEM}_raw.md"
    assert raw_path.exists()
    assert "Lap ke hoach bao duong tu MinerU raw" in raw_path.read_text(encoding="utf-8")
    assert paths.normalized.exists()
    assert paths.citation_map.exists()
    assert paths.mineru_artifact_index.exists()
    assert paths.normalized.name == f"{PILOT_ARTIFACT_STEM}.md"
    assert "Lap ke hoach bao duong tu MinerU raw" in paths.normalized.read_text(encoding="utf-8")
    assert "mojibake" not in paths.normalized.read_text(encoding="utf-8")
    assert fake_mineru.calls == [xlsx.resolve()]

    records = ManifestStore(tmp_path).load()
    pilot = next(record for record in records if record.doc_id == PILOT_DOC_ID)
    duplicate = next(record for record in records if record.doc_id == "KT-QT-401")
    assert pilot.status == "active"
    assert duplicate.status == "archived"
    assert pilot.extra["display_code"] == PILOT_DISPLAY_CODE
    assert pilot.extra["display_version"] == "Rev 04"
    assert pilot.extra["primary_source_decision"]["selected"] == "xlsx"
    assert pilot.extra["quality_status"] == "passed"
    assert pilot.extra["raw_converter"] == "mineru"
    assert pilot.extra["raw_conversion_policy"] == "mineru_only_no_fallback"
    assert pilot.extra["raw_markdown_path"] == str(raw_path)
    assert pilot.extra["mineru_artifact_index_path"] == str(paths.mineru_artifact_index)
    assert pilot.extra["mineru_artifact_summary"]["has_content_list_v2"] is True
    assert pilot.extra["mineru_profile"]["command"] == "fake-mineru"

    citation_map = json.loads(paths.citation_map.read_text(encoding="utf-8"))
    assert citation_map
    assert all(citation["source_type"] == "xlsx" for citation in citation_map)
    assert any("row_start" in citation["source_locator"] for citation in citation_map)
    assert any("raw_markdown_line_start" in citation["source_locator"] for citation in citation_map)
    assert any(citation["source_locator"].get("mineru_block_ids") for citation in citation_map)
    assert any(citation.get("source_json") == "content_list_v2" for citation in citation_map)


def test_pdtech_a02_agent_sandbox_stops_at_pending_review_with_handoffs(tmp_path: Path) -> None:
    xlsx = tmp_path / "root_source" / "technical" / "PD-TECH-A-02.Rev 04. Quy trinh bao duong_29.05.23.xlsx"
    pdf = tmp_path / "root_source" / "technical" / "PD-TECH-A-02. Rev 04. Quy trinh bao duong.pdf"
    write_pilot_xlsx(xlsx)
    write_pilot_pdf(pdf)

    result = run_pdtech_a02_agent_sandbox(
        tmp_path,
        converter=FakeMinerUConverter(),
        stamp="test-run",
    )

    sandbox = Path(result["sandbox_path"])
    assert sandbox == tmp_path / ".quality-sandbox" / "single-doc-agent-run-test-run"
    assert result["status"] == "pending_review"
    assert result["primary_source"] == "xlsx"
    assert result["ragflow_ingestion"] == "not_run"
    assert result["smoke_chat"] == "not_run"
    assert (sandbox / "source" / "xlsx" / xlsx.name).exists()
    assert (sandbox / "source" / "pdf" / pdf.name).exists()
    assert (sandbox / "converted_raw" / "xlsx" / f"{PILOT_ARTIFACT_STEM}_xlsx_raw.md").exists()
    assert (sandbox / "converted_raw" / "pdf" / f"{PILOT_ARTIFACT_STEM}_pdf_raw.md").exists()
    assert (sandbox / "mineru_artifact_index" / "xlsx_mineru_artifact_index.json").exists()
    assert (sandbox / "normalized" / "technical" / "procedure" / f"{PILOT_ARTIFACT_STEM}.md").exists()
    assert (sandbox / "indexes" / f"{PILOT_ARTIFACT_STEM}_metadata.json").exists()
    assert (sandbox / "indexes" / f"{PILOT_ARTIFACT_STEM}_section_index.json").exists()
    assert (sandbox / "indexes" / f"{PILOT_ARTIFACT_STEM}_chunk_plan.json").exists()
    assert (sandbox / "indexes" / f"{PILOT_ARTIFACT_STEM}_citation_map.json").exists()
    assert (sandbox / "reports" / "source_probe_report.json").exists()
    assert (sandbox / "reports" / "quality_report.json").exists()
    assert (sandbox / "reports" / "repair_log.json").exists()
    assert (sandbox / "reports" / "run_report.md").exists()
    assert (sandbox / "reports" / "evolution_report.md").exists()
    assert (sandbox / "review" / "human_review.json").exists()

    handoffs = [
        json.loads(line)
        for line in (sandbox / "workflow_handoffs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [handoff["step"] for handoff in handoffs] == [
        "plan",
        "convert",
        "audit",
        "repair",
        "audit",
        "index",
        "evolve",
    ]
    assert handoffs[-1]["next_skill"] is None
    assert handoffs[1]["quality_gates"]["duplicate_retrieval_blocked"] is True
    assert all(handoff["skill_read_receipts"] for handoff in handoffs)
    assert all(handoff["handoff_checker"]["status"] == "passed" for handoff in handoffs)

    records = ManifestStore(sandbox).load()
    assert len(records) == 1
    record = records[0]
    assert record.doc_id == PILOT_DOC_ID
    assert record.status == "pending_review"
    assert record.extra["ragflow_ingestion"] == "not_run"
    assert record.extra["smoke_chat"] == "not_run"
    assert record.extra["raw_conversion_policy"] == "mineru_only_no_fallback"
    assert record.extra["primary_source_decision"]["selected"] == "xlsx"

    normalized = (sandbox / "normalized" / "technical" / "procedure" / f"{PILOT_ARTIFACT_STEM}.md").read_text(
        encoding="utf-8"
    )
    assert "<table" not in normalized.lower()
    assert "<td" not in normalized.lower()
    quality = json.loads((sandbox / "reports" / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["quality_status"] == "passed"
    assert quality["raw_html_table_markup_remaining"] is False
    assert quality["strict_rag_readiness"] is True
    assert quality["rag_readiness_metrics"]["required_section_pass"] is True
    assert quality["rag_readiness_metrics"]["source_locator_precision"] >= 0.8
    assert quality["rag_readiness_metrics"]["procedure_step_count"] >= 1
    citations = json.loads((sandbox / "indexes" / f"{PILOT_ARTIFACT_STEM}_citation_map.json").read_text(encoding="utf-8"))
    assert citations
    assert all(citation["source_locator"] for citation in citations)
    assert all(citation["source_locator"].get("row_basis") != "mineru_raw_line" for citation in citations)
    assert any(citation["source_locator"].get("mineru_block_ids") for citation in citations)


def test_pdtech_a02_pilot_requires_mineru_for_raw_conversion(tmp_path: Path) -> None:
    xlsx = tmp_path / "root_source" / "technical" / "PD-TECH-A-02.Rev 04. Quy trinh bao duong_29.05.23.xlsx"
    pdf = tmp_path / "root_source" / "technical" / "PD-TECH-A-02. Rev 04. Quy trinh bao duong.pdf"
    write_pilot_xlsx(xlsx)
    write_pilot_pdf(pdf)

    with pytest.raises(Exception):
        run_pdtech_a02_pilot(
            tmp_path,
            approve_review=True,
            reviewer="pilot-reviewer",
            converter=MinerUConverter(command="missing-mineru"),
        )

    paths = pilot_paths(tmp_path)
    assert not paths.normalized.exists()


def test_pilot_verify_blocks_synthetic_headings(tmp_path: Path) -> None:
    markdown = tmp_path / "draft.md"
    markdown.write_text("# Quy trnh bo dng\n\n## Fixing Metadata\n\nKhng hp l.\n", encoding="utf-8")
    citation_map = tmp_path / "citation_map.json"
    citation_map.write_text(
        json.dumps(
            [
                {
                    "anchor_id": "KT-QT-002-S01-C01",
                    "source_type": "xlsx",
                    "source_locator": {"sheet": "Quy trnh", "row_start": 1, "row_end": 2},
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verify_normalized_markdown(markdown, citation_map_path=citation_map, primary_source_type="xlsx")

    assert report["quality_status"] == "needs_review"
    assert any(issue["type"] == "synthetic_heading_not_in_source" for issue in report["issues"])


def test_pilot_verify_blocks_synthetic_heading_in_mineru_raw(tmp_path: Path) -> None:
    markdown = tmp_path / "draft.md"
    markdown.write_text("# Quy trnh bo dng\n\n## Mc ch\n\nNi dung.\n", encoding="utf-8")
    raw = tmp_path / "raw.md"
    raw.write_text("# PD-TECH-A-02 Rev 04\n\n## Smart Fix\n\nPrompt leak.\n", encoding="utf-8")
    citation_map = tmp_path / "citation_map.json"
    citation_map.write_text(
        json.dumps(
            [
                {
                    "anchor_id": "KT-QT-002-S01-C01",
                    "source_type": "xlsx",
                    "source_locator": {"sheet": "Quy trnh", "row_start": 1, "row_end": 2},
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verify_normalized_markdown(
        markdown,
        citation_map_path=citation_map,
        primary_source_type="xlsx",
        raw_markdown_path=raw,
        raw_converter="mineru",
    )

    assert report["quality_status"] == "needs_review"
    assert report["raw_conversion_engine"] == "mineru"
    assert report["raw_synthetic_heading_count"] == 1
    assert any(issue["location"] == "raw_markdown" for issue in report["issues"])


def test_pilot_verify_blocks_missing_citation_anchor(tmp_path: Path) -> None:
    markdown = tmp_path / "draft.md"
    markdown.write_text("# Quy trnh bo dng\n\n## Mc ch\n\nNi dung.\n", encoding="utf-8")
    citation_map = tmp_path / "citation_map.json"
    citation_map.write_text("[]", encoding="utf-8")

    report = verify_normalized_markdown(markdown, citation_map_path=citation_map, primary_source_type="xlsx")

    assert report["quality_status"] == "needs_review"
    assert any(issue["type"] == "missing_citation_anchor" for issue in report["issues"])


def test_pilot_strict_rag_readiness_blocks_weak_structure_and_locators(tmp_path: Path) -> None:
    markdown = tmp_path / "draft.md"
    markdown.write_text(
        "# Quy trinh bao duong\n\n## Quy trinh thuc hien\n\n## Lich su chinh sua\n\nNoisy metadata.\n",
        encoding="utf-8",
    )
    citation_map = tmp_path / "citation_map.json"
    citation_map.write_text(
        json.dumps(
            [
                {
                    "anchor_id": "KT-QT-002-S01-C01",
                    "source_type": "xlsx",
                    "source_locator": {
                        "sheet": "MinerU raw",
                        "row_start": 1,
                        "row_end": 3,
                        "row_basis": "mineru_raw_line",
                        "columns": ["raw"],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    report = verify_normalized_markdown(
        markdown,
        citation_map_path=citation_map,
        primary_source_type="xlsx",
        strict_rag_readiness=True,
    )

    assert report["quality_status"] == "needs_review"
    issue_types = {issue["type"] for issue in report["issues"]}
    assert "missing_required_rag_section" in issue_types
    assert "weak_source_locator_precision" in issue_types
    assert "missing_procedure_steps" in issue_types


def test_mineru_raw_html_tables_are_precleaned_before_normalize(tmp_path: Path) -> None:
    raw = tmp_path / "raw.md"
    raw.write_text(
        """
# Sheet: Quy trinh

<table>
<tr><th>Muc dich</th></tr>
<tr><td>Dam bao bao duong dung ke hoach.</td></tr>
</table>

<table>
<tr><th>Quy trinh thuc hien</th></tr>
<tr><td>Buoc 1</td><td>Lap ke hoach bao duong</td></tr>
<tr><td>Buoc 2</td><td>Thuc hien bao duong</td></tr>
</table>
""",
        encoding="utf-8",
    )

    normalized, section_index, citation_map = normalize_mineru_raw(raw, tmp_path / "PD-TECH-A-02.xlsx", "xlsx")

    assert "<table" not in normalized.lower()
    assert "<td" not in normalized.lower()
    assert "Dam bao bao duong dung ke hoach" in normalized
    assert "Lap ke hoach bao duong" in normalized
    assert section_index
    assert citation_map


def test_ragflow_sync_uploads_only_passed_primary_source_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pilot_md = tmp_path / "normalized" / "technical" / "procedure" / f"{PILOT_ARTIFACT_STEM}.md"
    support_md = tmp_path / "normalized" / "technical" / "procedure" / "KT-QT-401_v1.0.md"
    pilot_md.parent.mkdir(parents=True, exist_ok=True)
    pilot_md.write_text("# Quy trnh bo dng\n\nNi dung sch.", encoding="utf-8")
    support_md.write_text("# Quy trnh bo dng\n\nBn trng.", encoding="utf-8")
    citation_map = tmp_path / "indexes" / f"{PILOT_ARTIFACT_STEM}_citation_map.json"
    citation_map.parent.mkdir(parents=True, exist_ok=True)
    citation_map.write_text("[{}]", encoding="utf-8")
    ManifestStore(tmp_path).save(
        [
            ManifestRecord(
                doc_id=PILOT_DOC_ID,
                title="PD-TECH-A-02 Rev 04 - Quy trnh bo dng",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="1.0",
                status="active",
                effective_from="2026-01-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path="/root_source/pilot.xlsx",
                normalized_path=str(pilot_md),
                content_hash="pilot",
                extra={
                    "display_code": PILOT_DISPLAY_CODE,
                    "display_version": "Rev 04",
                    "canonical_business_code": PILOT_DISPLAY_CODE,
                    "source_revision": "Rev 04",
                    "artifact_stem": PILOT_ARTIFACT_STEM,
                    "ingest_policy": "primary_source_only",
                    "quality_status": "passed",
                    "citation_map_path": str(citation_map),
                    "raw_converter": "mineru",
                    "raw_conversion_policy": "mineru_only_no_fallback",
                    "raw_markdown_path": "/converted_raw/pilot/PD-TECH-A-02/KT-QT-002_rev04_raw.md",
                    "mineru_profile": {"command": "mineru", "method": "auto"},
                    "primary_source_decision": {"selected": "xlsx", "reason": "test"},
                },
            ),
            ManifestRecord(
                doc_id="KT-QT-401",
                title="PD TECH A 02. Rev 04. Quy trnh bo dng",
                department="technical",
                category="procedure",
                source_type="internal_procedure",
                language="vi",
                version="1.0",
                status="active",
                effective_from="2026-01-01",
                owner="Phong Ky thuat",
                access_group="technical",
                source_path="/root_source/support.pdf",
                normalized_path=str(support_md),
                content_hash="support",
                extra={
                    "display_code": PILOT_DISPLAY_CODE,
                    "used_for_retrieval": False,
                },
            ),
        ]
    )
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def __init__(self, base_url: str, api_key: str):
            calls.append(("init", (base_url, api_key)))

        def upload_document(self, dataset_id: str, path: Path, display_name: str | None = None):
            calls.append(("upload", display_name))
            return {"id": f"doc-{display_name}"}

        def update_document_metadata(self, dataset_id: str, document_id: str, metadata: dict[str, str]):
            calls.append(("metadata", metadata))
            return {"code": 0}

        def parse_documents(self, dataset_id: str, document_ids: list[str]):
            calls.append(("parse", document_ids))
            return {"code": 0}

    monkeypatch.setattr(ragflow_http, "RAGFlowHTTPClient", FakeClient)

    result = sync_active_to_ragflow(tmp_path, "http://ragflow", "key", "dataset-1")

    assert result["uploaded_count"] == 1
    assert ("upload", f"{PILOT_ARTIFACT_STEM}.md") in calls
    assert ("upload", "KT-QT-401_v1.0_procedure.md") not in calls
    metadata = [payload for name, payload in calls if name == "metadata"][0]
    assert metadata["display_code"] == PILOT_DISPLAY_CODE
    assert metadata["display_version"] == "Rev 04"
    assert metadata["raw_converter"] == "mineru"
    assert metadata["raw_conversion_policy"] == "mineru_only_no_fallback"
    assert metadata["mineru_profile"]
