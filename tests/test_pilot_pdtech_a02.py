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
    pilot_paths,
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
        return output_md

    def profile_dict(self) -> dict[str, object]:
        return {"command": "fake-mineru", "method": "auto", "backend": "pipeline"}


def write_pilot_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quy trinh"
    sheet.append(["Ma tai lieu", PILOT_DISPLAY_CODE])
    sheet.append(["Phien ban", "Rev 04"])
    sheet.append(["Muc dich"])
    sheet.append(["Dam bao hoat dong bao duong duoc thuc hien dung ke hoach."])
    sheet.append(["Trach nhiem"])
    sheet.append(["Ky thuat Vung", "Thuc hien bao duong va ghi nhan ket qua."])
    sheet.append(["Quy trinh thuc hien"])
    sheet.append(["Buoc 1", "Lap ke hoach bao duong"])
    sheet.append(["Buoc 2", "Thong bao khach hang va chuan bi cong cu"])
    sheet.append(["Buoc 3", "Thuc hien bao duong va ky BBDVKT"])
    sheet.append(["Ho so / bieu mau lien quan"])
    sheet.append(["PD-TECH-A-02/BM-06", "Bien ban dich vu ky thuat"])
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
    assert pilot.extra["mineru_profile"]["command"] == "fake-mineru"

    citation_map = json.loads(paths.citation_map.read_text(encoding="utf-8"))
    assert citation_map
    assert all(citation["source_type"] == "xlsx" for citation in citation_map)
    assert any("row_start" in citation["source_locator"] for citation in citation_map)
    assert any("raw_markdown_line_start" in citation["source_locator"] for citation in citation_map)


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
