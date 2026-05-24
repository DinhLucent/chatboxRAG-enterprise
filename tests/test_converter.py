from __future__ import annotations

from pathlib import Path

from poc_workflow.converter import MinerUConverter


def test_converter_extracts_xlsx_to_markdown(tmp_path: Path) -> None:
    from openpyxl import Workbook

    source = tmp_path / "checklist.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Checklist"
    sheet.append(["Step", "Owner"])
    sheet.append(["Kiem tra tem", "Kho"])
    workbook.save(source)

    output = tmp_path / "checklist.md"
    MinerUConverter(command="missing-mineru").convert(source, output)

    text = output.read_text(encoding="utf-8")
    assert "## Sheet: Checklist" in text
    assert "| Step | Owner |" in text
    assert "Kiem tra tem" in text


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


def test_converter_falls_back_to_pdf_text_when_mineru_fails(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    source = tmp_path / "procedure.pdf"
    pdf = canvas.Canvas(str(source))
    pdf.drawString(72, 720, "Quy trinh kiem tra nhiet do kho")
    pdf.drawString(72, 700, "Ghi nhan nhiet do va do am hang ngay.")
    pdf.save()

    output = tmp_path / "procedure.md"
    MinerUConverter(command="missing-mineru").convert(source, output)

    text = output.read_text(encoding="utf-8")
    assert "MinerU conversion was attempted first" in text
    assert "Quy trinh kiem tra nhiet do kho" in text
    assert "Ghi nhan nhiet do" in text


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
