from __future__ import annotations

import zipfile
import json
from pathlib import Path

from poc_workflow.data_workflow import best_source_match, mineru_source_block_summary, mineru_source_blocks, xlsx_source_blocks
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


def test_mineru_source_blocks_use_content_middle_model_and_image_refs(tmp_path: Path) -> None:
    metadata = tmp_path / "mineru_artifacts" / "metadata"
    images = tmp_path / "mineru_artifacts" / "images"
    metadata.mkdir(parents=True)
    images.mkdir(parents=True)
    image = images / "flow.png"
    image.write_bytes(b"image")
    content_list = metadata / "content_list_v2.json"
    content_list.write_text(
        json.dumps(
            [
                [
                    {
                        "id": "content-1",
                        "type": "text",
                        "text": "Lap ke hoach bao duong",
                        "bbox": [1, 2, 3, 4],
                    }
                ]
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    middle = metadata / "middle.json"
    middle.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "para_blocks": [
                            {
                                "type": "image",
                                "bbox": [10, 20, 30, 40],
                                "lines": [{"spans": [{"text": "Flowchart phe duyet bao duong"}]}],
                                "content": {"image_source": {"path": "images/flow.png"}},
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    model = metadata / "model.json"
    model.write_text(
        json.dumps(
            [
                [
                    {
                        "type": "table",
                        "page_idx": 0,
                        "content": "<table><tr><td>Ho so bao duong</td></tr></table>",
                    }
                ]
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    index_path = tmp_path / "mineru_artifact_index.json"
    index_path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {"type": "content_list_v2", "path": str(content_list)},
                    {"type": "middle_json", "path": str(middle)},
                    {"type": "model_json", "path": str(model)},
                    {"type": "image", "path": str(image)},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    blocks = mineru_source_blocks(index_path)
    summary = mineru_source_block_summary(blocks)

    assert {block["source_json"] for block in blocks} >= {"content_list_v2", "middle_json", "model_json"}
    assert any("Flowchart phe duyet" in block["text"] for block in blocks)
    assert any(block["locator"].get("bbox") == [10, 20, 30, 40] for block in blocks)
    assert any(str(block.get("image_ref") or "").endswith("flow.png") for block in blocks)
    assert any("Ho so bao duong" in block["text"] for block in blocks)
    assert summary["source_json_counts"]["middle_json"] == 1
    assert summary["bbox_count"] >= 2
    assert summary["image_ref_count"] == 1


def test_best_source_match_prefers_richer_mineru_locator_on_tie() -> None:
    chunk_text = "Flowchart phe duyet bao duong"
    blocks = [
        {
            "text": chunk_text,
            "locator": {"type": "mineru", "source_json": "content_list_v2", "page_start": 1, "page_end": 1},
            "display_locator": "MinerU content_list_v2 page 1",
            "source_json": "content_list_v2",
        },
        {
            "text": chunk_text,
            "locator": {
                "type": "mineru",
                "source_json": "middle_json",
                "page_start": 1,
                "page_end": 1,
                "bbox": [10, 20, 30, 40],
                "image_ref": "images/flow.png",
            },
            "display_locator": "MinerU middle_json page 1",
            "source_json": "middle_json",
            "image_ref": "images/flow.png",
        },
    ]

    match = best_source_match(chunk_text, blocks)

    assert match is not None
    assert match["source_json"] == "middle_json"
    assert match["locator"]["bbox"] == [10, 20, 30, 40]
    assert match["image_ref"] == "images/flow.png"
