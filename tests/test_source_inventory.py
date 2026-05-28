from __future__ import annotations

from pathlib import Path

from poc_workflow.agent_prompt_queue import list_upload_queue
from poc_workflow.source_inventory import enqueue_phuong_dong_procedures, inventory_phuong_dong_procedures
from poc_workflow.upload_processing import list_upload_document_groups


def test_inventory_phuong_dong_excludes_technical_and_maps_departments(tmp_path: Path) -> None:
    source_root = tmp_path / "root_source" / "Quy Trình Phương Đông"
    hr = source_root / "04. QUY TRÌNH PHÒNG NHÂN SỰ"
    tech = source_root / "12. QUY TRÌNH KỸ THUẬT"
    sales = source_root / "06. QUY TRÌNH BÁN HÀNG"
    hr.mkdir(parents=True)
    tech.mkdir(parents=True)
    sales.mkdir(parents=True)
    (hr / "PD-HR-A-02. Rev 04. Quy trinh bao duong.docx").write_bytes(b"hr docx")
    (sales / "PD-SALES-A-03. Rev 01. Quy trinh ban hang.pdf").write_bytes(b"pdf")
    (tech / "PD-TECH-A-02. Rev 04. Quy trinh bao duong.pdf").write_bytes(b"tech pdf")

    report = inventory_phuong_dong_procedures(tmp_path)

    assert report["discovered_count"] == 2
    assert report["skipped_technical_count"] == 1
    assert report["by_department"] == {"human_resources": 1, "sales": 1}
    assert (tmp_path / "manifest" / "all_departments_source_inventory.json").exists()


def test_inventory_uses_business_code_department_when_folder_prefix_missing(tmp_path: Path) -> None:
    source_root = tmp_path / "root_source" / "Quy TrÃ¬nh PhÆ°Æ¡ng ÄÃ´ng"
    loose = source_root / "LOOSE_UPLOADS"
    loose.mkdir(parents=True)
    (loose / "PD-ACC-A-09. Rev 02. Quy trinh thanh toan.pdf").write_bytes(b"pdf")

    report = inventory_phuong_dong_procedures(tmp_path)

    assert report["discovered_count"] == 1
    assert report["items"][0]["department"] == "accounting"
    assert report["by_department"] == {"accounting": 1}


def test_enqueue_phuong_dong_copies_to_department_inbox_with_sidecar(tmp_path: Path) -> None:
    source_root = tmp_path / "root_source" / "Quy Trình Phương Đông"
    hr = source_root / "04. QUY TRÌNH PHÒNG NHÂN SỰ"
    hr.mkdir(parents=True)
    (hr / "PD-HR-A-02. Rev 04. Quy trinh bao duong.docx").write_bytes(b"hr docx")
    (hr / "PD-HR-A-02. Rev 04. Quy trinh bao duong.pdf").write_bytes(b"hr pdf")

    report = enqueue_phuong_dong_procedures(tmp_path)

    assert report["copied_count"] == 2
    target = tmp_path / "inbox" / "procedure" / "human_resources" / "PD-HR-A-02. Rev 04. Quy trinh bao duong.docx"
    assert target.exists()
    assert target.with_name(target.stem + ".metadata.json").exists()
    queue = list_upload_queue(tmp_path)
    assert queue["summary"]["queue"] == 2
    groups = list_upload_document_groups(tmp_path)
    assert len(groups) == 1
    assert groups[0].department == "human_resources"
    assert set(groups[0].sources) == {"docx", "pdf"}

    second = enqueue_phuong_dong_procedures(tmp_path)
    assert second["copied_count"] == 0
    assert second["skipped_count"] == 2
