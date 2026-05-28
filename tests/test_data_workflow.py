from __future__ import annotations

import zipfile
from pathlib import Path

from poc_workflow.data_workflow import xlsx_source_blocks
from poc_workflow.document_qa import extract_source_text


def test_xlsx_source_blocks_ignores_empty_shared_string_value_nodes(tmp_path: Path) -> None:
    source = tmp_path / "empty-shared-string.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            """<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets><sheet name="Quy trinh" sheetId="1" r:id="rId1"/></sheets>
            </workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
            </Relationships>""",
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            """<sst><si><t></t></si><si><t>Buoc 1: Tiep nhan yeu cau</t></si></sst>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet><sheetData><row r="1">
              <c r="A1" t="s"><v/></c>
              <c r="B1" t="s"><v>1</v></c>
            </row></sheetData></worksheet>""",
        )

    blocks = xlsx_source_blocks(source)

    assert blocks
    assert any("Buoc 1" in block["text"] for block in blocks)
    assert blocks[0]["locator"]["type"] == "xlsx"

    text, extraction = extract_source_text(source)
    assert extraction["method"] == "xlsx_xml"
    assert "Buoc 1" in text
