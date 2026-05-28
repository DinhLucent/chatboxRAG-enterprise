from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from poc_workflow.converter import (
    ConversionError,
    MinerUConverter,
    collect_mineru_directory_artifacts,
    collect_mineru_zip_artifacts,
    find_mineru_artifact_index,
)


def test_converter_requires_mineru_for_xlsx_sources(tmp_path: Path) -> None:
    from openpyxl import Workbook

    source = tmp_path / "checklist.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Checklist"
    sheet.append(["Step", "Owner"])
    sheet.append(["Kiem tra tem", "Kho"])
    workbook.save(source)

    output = tmp_path / "checklist.md"
    with pytest.raises(ConversionError):
        MinerUConverter(command="missing-mineru").convert(source, output)

    assert not output.exists()


def test_converter_extracts_docx_to_markdown(tmp_path: Path) -> None:
    from docx import Document

    source = tmp_path / "procedure.docx"
    document = Document()
    document.add_paragraph("Quy trinh kiem tra hang hoa")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Buoc"
    table.cell(0, 1).text = "Mo ta"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "Doi chieu chung tu"
    document.save(source)

    output = tmp_path / "procedure.md"
    MinerUConverter(command="missing-mineru").convert(source, output)

    text = output.read_text(encoding="utf-8")
    assert "Quy trinh kiem tra hang hoa" in text
    assert "| Buoc | Mo ta |" in text
    assert "Doi chieu chung tu" in text


def test_converter_requires_mineru_for_pdf_sources(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    source = tmp_path / "procedure.pdf"
    pdf = canvas.Canvas(str(source))
    pdf.drawString(72, 720, "Quy trinh kiem tra nhiet do kho")
    pdf.drawString(72, 700, "Ghi nhan nhiet do va do am hang ngay.")
    pdf.save()

    output = tmp_path / "procedure.md"
    with pytest.raises(ConversionError):
        MinerUConverter(command="missing-mineru").convert(source, output)

    assert not output.exists()


def test_convert_with_mineru_routes_xlsx_through_mineru(tmp_path: Path) -> None:
    from openpyxl import Workbook

    class StrictMinerUConverter(MinerUConverter):
        def _convert_with_mineru(self, source_path: Path, output_md: Path, *args, **kwargs) -> Path:
            output_md.write_text(f"# MinerU raw\n\nsource={source_path.name}\n", encoding="utf-8")
            return output_md

    source = tmp_path / "checklist.xlsx"
    workbook = Workbook()
    workbook.active.append(["Step", "Owner"])
    workbook.save(source)
    output = tmp_path / "checklist.md"

    StrictMinerUConverter(command="missing-mineru").convert_with_mineru(source, output)

    assert "source=checklist.xlsx" in output.read_text(encoding="utf-8")


def test_convert_with_mineru_does_not_pdf_fallback_when_mineru_is_missing(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    source = tmp_path / "procedure.pdf"
    pdf = canvas.Canvas(str(source))
    pdf.drawString(72, 720, "Quy trinh kiem tra nhiet do kho")
    pdf.save()

    output = tmp_path / "procedure.md"
    with pytest.raises(ConversionError):
        MinerUConverter(command="missing-mineru").convert_with_mineru(source, output)

    assert not output.exists()


def test_converter_reads_mineru_options_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MINERU_METHOD", "ocr")
    monkeypatch.setenv("MINERU_BACKEND", "pipeline")
    monkeypatch.setenv("MINERU_FORMULA", "false")
    monkeypatch.setenv("MINERU_TABLE", "true")
    monkeypatch.setenv("MINERU_IMAGE_ANALYSIS", "false")
    monkeypatch.setenv("MINERU_MAX_PAGES", "300")

    converter = MinerUConverter.from_env()

    assert converter.method == "ocr"
    assert converter.backend == "pipeline"
    assert converter.formula is False
    assert converter.table is True
    assert converter.image_analysis is False
    assert converter.max_pages == 300


def test_mineru_input_staging_defaults_to_ascii_filename(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_ASCII_STAGE_INPUT", raising=False)
    monkeypatch.delenv("MINERU_STAGE_STEM_MAX_CHARS", raising=False)
    source = tmp_path / "PD-ADM-A-064 Rev02. Quy trình lưu trữ tài liệu.xlsx"
    source.write_bytes(b"fake workbook")

    staged = MinerUConverter(command="missing-mineru")._stage_input_for_mineru(source, tmp_path / "raw")

    assert staged.name.endswith(".xlsx")
    assert all(ord(char) < 128 for char in staged.name)
    assert staged.read_bytes() == b"fake workbook"


def test_mineru_input_staging_shortens_long_filenames_for_windows_temp_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_ASCII_STAGE_INPUT", raising=False)
    monkeypatch.delenv("MINERU_STAGE_STEM_MAX_CHARS", raising=False)
    source = tmp_path / "PD-IC-D-004_Rev 03. Quy định về chống hối lộ và chống tham nhũng ABAC rất dài.pdf"
    source.write_bytes(b"%PDF-1.4")

    staged = MinerUConverter(command="missing-mineru")._stage_input_for_mineru(source, tmp_path / "raw")

    assert staged.suffix == ".pdf"
    assert len(staged.stem) <= 48
    assert "-" in staged.stem
    assert staged.read_bytes() == b"%PDF-1.4"


def test_collect_mineru_zip_artifacts_indexes_sidecars_and_images(tmp_path: Path) -> None:
    zip_path = tmp_path / "mineru_result.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("doc/auto/doc.md", "# Doc\n\nBody\n")
        archive.writestr(
            "doc/auto/doc_content_list_v2.json",
            json.dumps(
                [
                    [
                        {
                            "type": "text",
                            "content": {"paragraph_content": [{"type": "text", "content": "Step one"}]},
                            "bbox": [1, 2, 3, 4],
                        }
                    ]
                ]
            ),
        )
        archive.writestr("doc/auto/doc_middle.json", json.dumps({"pdf_info": [{"preproc_blocks": []}]}))
        archive.writestr("doc/auto/doc_model.json", json.dumps({"layout": "test"}))
        archive.writestr("doc/auto/doc_layout_extra.json", json.dumps({"extra": "kept"}))
        archive.writestr("doc/auto/doc_notes.md", "secondary markdown")
        archive.writestr("doc/auto/debug.log", "mineru warning")
        archive.writestr("doc/auto/images/figure.jpg", b"image-bytes")
        archive.writestr("doc/auto/doc_origin.pdf", b"%PDF-1.4")

    output_md = tmp_path / "out.md"
    output_md.write_text("# Doc\n\nBody\n", encoding="utf-8")

    index_path = collect_mineru_zip_artifacts(
        zip_path=zip_path,
        result_root=tmp_path / "raw",
        output_md=output_md,
        selected_markdown_name="doc/auto/doc.md",
        source_path=tmp_path / "source.pdf",
        job_id="job-1",
    )

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["summary"]["has_content_list_v2"] is True
    assert index["summary"]["has_middle_json"] is True
    assert index["summary"]["has_model_json"] is True
    assert index["summary"]["image_count"] == 1
    assert index["summary"]["generic_json_count"] == 1
    assert index["summary"]["other_artifact_count"] == 1
    assert index["summary"]["markdown_count"] == 2
    assert any(item["type"] == "content_list_v2" and Path(item["path"]).exists() for item in index["artifacts"])
    assert any(item["type"] == "json" and item.get("json_summary", {}).get("parseable") is True for item in index["artifacts"])
    assert any(item["type"] == "other" and Path(item["path"]).exists() for item in index["artifacts"])
    assert find_mineru_artifact_index(tmp_path / "raw", output_md) == index_path


def test_collect_mineru_directory_artifacts_preserves_unrecognized_sidecars(tmp_path: Path) -> None:
    source_root = tmp_path / "mineru_dir"
    auto_root = source_root / "doc" / "auto"
    auto_root.mkdir(parents=True)
    selected = auto_root / "doc.md"
    selected.write_text("# Doc\n\nBody\n", encoding="utf-8")
    (auto_root / "doc_content_list.json").write_text(json.dumps([{"type": "text", "text": "Body"}]), encoding="utf-8")
    (auto_root / "trace.json").write_text(json.dumps({"trace": "kept"}), encoding="utf-8")
    (auto_root / "notes.txt").write_text("diagnostic", encoding="utf-8")

    output_md = tmp_path / "out.md"
    output_md.write_text("# Doc\n\nBody\n", encoding="utf-8")

    index_path = collect_mineru_directory_artifacts(
        source_root=source_root,
        output_md=output_md,
        selected_markdown_path=selected,
        source_path=tmp_path / "source.pdf",
    )

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["summary"]["has_content_list"] is True
    assert index["summary"]["generic_json_count"] == 1
    assert index["summary"]["other_artifact_count"] == 1
    assert any(item["type"] == "json" and Path(item["path"]).exists() for item in index["artifacts"])
    assert any(item["type"] == "other" and Path(item["path"]).exists() for item in index["artifacts"])
