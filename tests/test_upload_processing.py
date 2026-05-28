from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from poc_workflow.agent_prompt_queue import list_upload_queue
from poc_workflow.manifest import ManifestError, validate_record_for_approval
from poc_workflow.manifest import ManifestStore
from poc_workflow.upload_processing import (
    CandidateConversion,
    UploadDocumentGroup,
    business_document_identity,
    build_rag_summary_section,
    list_upload_document_groups,
    looks_like_corrupted_metadata_text,
    normalized_title_quality_issues,
    process_upload_queue,
    source_text_unavailable_but_mineru_ocr_evidence_is_rich,
    strip_generated_rag_summary_blocks,
    upload_run_paths,
)
from poc_workflow.webapp import create_app


class FakeUploadMinerUConverter:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def profile_dict(self) -> dict[str, object]:
        return {"command": "fake-mineru", "method": "auto", "backend": "pipeline"}

    def convert_with_mineru(
        self,
        source_path: Path,
        output_md: Path,
        language: str = "vi",
        artifact_root: Path | None = None,
    ) -> Path:
        self.calls.append(source_path.resolve())
        output_md.parent.mkdir(parents=True, exist_ok=True)
        source_type = source_path.suffix.lower().lstrip(".")
        output_md.write_text(
            "\n".join(
                [
                    "# PD-TECH-A-02 Rev 04 Quy trinh bao duong",
                    "",
                    "## Muc dich",
                    "Dam bao thiet bi duoc bao duong theo ke hoach.",
                    "",
                    "## Trach nhiem",
                    "Phong Ky thuat lap ke hoach va thuc hien bao duong.",
                    "",
                    "## Quy trinh thuc hien",
                    "1. Lap ke hoach bao duong.",
                    "2. Thong bao khach hang va chuan bi vat tu.",
                    "3. Thuc hien bao duong va ghi nhan ket qua.",
                    "",
                    "## Ho so bieu mau",
                    "Luu phieu bao duong va bien ban nghiem thu.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        root = artifact_root or output_md.parent / "mineru_raw"
        metadata = root / "mineru_artifacts" / "metadata"
        image_dir = root / "mineru_artifacts" / "images"
        metadata.mkdir(parents=True, exist_ok=True)
        image_dir.mkdir(parents=True, exist_ok=True)
        content_list = metadata / "content_list_v2.json"
        content_list.write_text(
            json.dumps(
                [
                    {
                        "id": f"{source_type}-block-1",
                        "type": "text",
                        "page_idx": 0,
                        "text": "Lap ke hoach bao duong Thong bao khach hang Thuc hien bao duong",
                        "bbox": [10, 20, 300, 160],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        middle = metadata / "middle.json"
        middle.write_text(json.dumps({"pdf_info": [{"page_idx": 0}]}), encoding="utf-8")
        model = metadata / "model.json"
        model.write_text(json.dumps({"layout": "fake"}), encoding="utf-8")
        image = image_dir / "page_1.png"
        image.write_bytes(b"fake-image")
        index = {
            "schema_version": "mineru_artifact_index_v1",
            "source_path": str(source_path),
            "output_markdown_path": str(output_md),
            "summary": {
                "has_content_list": False,
                "has_content_list_v2": True,
                "has_middle_json": True,
                "has_model_json": True,
                "image_count": 1,
                "rich_artifact_count": 4,
            },
            "artifacts": [
                {"artifact_id": "markdown", "type": "markdown", "path": str(output_md), "selected": True},
                {"artifact_id": "content", "type": "content_list_v2", "path": str(content_list), "selected": False},
                {"artifact_id": "middle", "type": "middle_json", "path": str(middle), "selected": False},
                {"artifact_id": "model", "type": "model_json", "path": str(model), "selected": False},
                {"artifact_id": "image", "type": "image", "path": str(image), "selected": False},
            ],
        }
        (root / "mineru_artifact_index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        return output_md


def write_upload_pair(root: Path, *, inbox_subdir: str = "procedure", code: str = "PD-TECH-A-02") -> tuple[Path, Path]:
    from openpyxl import Workbook

    inbox = root / "inbox" / Path(inbox_subdir)
    inbox.mkdir(parents=True, exist_ok=True)
    xlsx = inbox / f"{code}. Rev 04. Quy trinh bao duong.xlsx"
    pdf = inbox / f"{code}. Rev 04. Quy trinh bao duong.pdf"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "QT"
    rows = [
        [code, "Rev 04", "Quy trinh bao duong"],
        ["Muc dich", "Dam bao thiet bi duoc bao duong theo ke hoach"],
        ["Trach nhiem", "Phong Ky thuat"],
        ["Quy trinh thuc hien", "Buoc", "Noi dung", "Ho so"],
        ["1", "Lap ke hoach bao duong", "Ke hoach"],
        ["2", "Thong bao khach hang va chuan bi vat tu", "Thong bao"],
        ["3", "Thuc hien bao duong va ghi nhan ket qua", "Phieu bao duong"],
        ["Ho so bieu mau", "Phieu bao duong", "Bien ban nghiem thu"],
    ]
    for row in rows:
        sheet.append(row)
    workbook.save(xlsx)
    pdf.write_bytes(b"%PDF-1.4\n% fake pdf for MinerU fake converter\n")
    return xlsx, pdf


def test_upload_queue_groups_pdf_xlsx_and_processes_one_primary_source(tmp_path: Path) -> None:
    xlsx, pdf = write_upload_pair(tmp_path)

    groups = list_upload_document_groups(tmp_path)

    assert len(groups) == 1
    assert groups[0].display_code == "PD-TECH-A-02"
    assert groups[0].source_revision == "Rev 04"
    assert groups[0].doc_id == "KT-QT-002"
    assert groups[0].title == "Quy trinh bao duong"
    assert set(groups[0].sources) == {"pdf", "xlsx"}

    fake = FakeUploadMinerUConverter()
    result = process_upload_queue(tmp_path, converter=fake, limit_groups=1)

    assert result[0]["status"] == "pending_review"
    assert result[0]["doc_id"] == "KT-QT-002"
    assert result[0]["artifact_stem"] == "KT-QT-002_rev04"
    assert fake.calls == [
        (tmp_path / ".Workplace" / "processing" / "procedure" / xlsx.name).resolve(),
        (tmp_path / ".Workplace" / "processing" / "procedure" / pdf.name).resolve(),
    ]

    queue = list_upload_queue(tmp_path)
    assert queue["summary"]["done"] == 0
    assert queue["summary"]["pending_review"] == 2
    assert {item["status"] for item in queue["items"]} == {"done"}
    assert {item["display_status"] for item in queue["items"]} == {"pending_review"}
    assert (tmp_path / "inbox" / "procedure" / "done" / xlsx.name).exists()
    assert (tmp_path / "inbox" / "procedure" / "done" / pdf.name).exists()

    records = ManifestStore(tmp_path).load()
    assert len(records) == 1
    record = records[0]
    assert record.status == "pending_review"
    assert record.extra["primary_source_decision"]["selected"] == "xlsx"
    assert record.extra["ingest_policy"] == "primary_source_only"
    assert record.extra["ragflow_ingestion"] == "not_run"
    assert record.extra["raw_conversion_policy"] == "mineru_only_no_fallback"
    try:
        validate_record_for_approval(record)
    except ManifestError as exc:
        assert "review_status=approved" in str(exc)
    else:
        raise AssertionError("expected human review gate to block approval")

    artifact_stem = "KT-QT-002_rev04"
    assert (tmp_path / "converted_raw" / "upload" / "PD-TECH-A-02_rev04" / "xlsx" / f"{artifact_stem}_xlsx_raw.md").exists()
    assert (tmp_path / "converted_raw" / "upload" / "PD-TECH-A-02_rev04" / "pdf" / f"{artifact_stem}_pdf_raw.md").exists()
    assert (tmp_path / "normalized" / "technical" / "procedure" / f"{artifact_stem}.md").exists()
    assert (tmp_path / "indexes" / f"{artifact_stem}_metadata.json").exists()
    assert (tmp_path / "indexes" / f"{artifact_stem}_section_index.json").exists()
    assert (tmp_path / "indexes" / f"{artifact_stem}_chunk_plan.json").exists()
    citation_map = json.loads((tmp_path / "indexes" / f"{artifact_stem}_citation_map.json").read_text(encoding="utf-8"))
    assert citation_map
    assert any(citation.get("source_json") == "content_list_v2" for citation in citation_map)
    assert any(citation.get("source_locator") for citation in citation_map)
    citation_response = TestClient(create_app(tmp_path)).get(f"/api/documents/KT-QT-002/rev04/citation/{citation_map[0]['anchor_id']}")
    assert citation_response.status_code == 200
    citation_body = citation_response.json()
    assert citation_body["citation"]["anchor_id"] == citation_map[0]["anchor_id"]
    assert citation_body["citation_preview"]["lines"]
    detail_response = TestClient(create_app(tmp_path)).get("/api/documents/KT-QT-002/rev04")
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["qa_report"]["exists"] is True
    assert detail_body["citations"]

    quality = json.loads((tmp_path / "indexes" / f"{artifact_stem}_quality_report.json").read_text(encoding="utf-8"))
    assert quality["quality_status"] == "passed"
    assert quality["quality_gates"]["supporting_source_not_ingested"] is True
    assert quality["quality_gates"]["ragflow_ingestion_not_run"] is True

    handoffs = [
        json.loads(line)
        for line in (tmp_path / ".Workplace" / "artifacts" / "procedure" / artifact_stem / "workflow" / "handoffs.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert [handoff["step"] for handoff in handoffs] == ["plan", "convert", "audit", "repair", "audit", "index", "evolve"]
    assert all(handoff["skill_read_receipts"] for handoff in handoffs)
    assert all(handoff["handoff_checker"]["status"] == "passed" for handoff in handoffs)

    review_path = tmp_path / "review" / "upload" / "PD-TECH-A-02_rev04" / "human_review.json"
    assert review_path.exists()
    assert record.extra["human_review_path"] == str(review_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_status"] = "approved"
    review["reviewer"] = "human-admin"
    review["checklist"] = {key: True for key in review["checklist"]}
    review_path.write_text(json.dumps(review), encoding="utf-8")
    validate_record_for_approval(record)
    assert (tmp_path / "rag_ready" / "technical" / "procedure" / artifact_stem / "schema_manifest.json").exists()


def test_upload_queue_preserves_non_technical_department_paths(tmp_path: Path) -> None:
    write_upload_pair(tmp_path, inbox_subdir="procedure/human_resources", code="PD-HR-A-02")

    groups = list_upload_document_groups(tmp_path)

    assert len(groups) == 1
    group = groups[0]
    assert group.department == "human_resources"
    assert group.department_name == "Phong Nhan su"
    assert group.display_code == "PD-HR-A-02"
    assert group.doc_id == "PD-HR-A-02"
    assert group.artifact_stem == "PD-HR-A-02_rev04"

    result = process_upload_queue(tmp_path, converter=FakeUploadMinerUConverter(), limit_groups=1)

    assert result[0]["status"] == "pending_review"
    record = ManifestStore(tmp_path).load()[0]
    assert record.department == "human_resources"
    assert record.access_group == "human_resources"
    assert record.extra["department_name"] == "Phong Nhan su"
    assert (tmp_path / "normalized" / "human_resources" / "procedure" / "PD-HR-A-02_rev04.md").exists()
    assert (tmp_path / "rag_ready" / "human_resources" / "procedure" / "PD-HR-A-02_rev04" / "schema_manifest.json").exists()
    queue = list_upload_queue(tmp_path)
    assert queue["summary"]["pending_review"] == 2
    assert (tmp_path / "inbox" / "procedure" / "done" / "human_resources" / "PD-HR-A-02. Rev 04. Quy trinh bao duong.xlsx").exists()


def test_upload_queue_groups_doc_docx_xls_candidates(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox" / "procedure" / "accounting"
    inbox.mkdir(parents=True)
    for suffix in ("doc", "docx", "xls"):
        (inbox / f"PD-ACC-A-09. Rev 02. Quy trinh thanh toan.{suffix}").write_bytes(b"fake office source")

    groups = list_upload_document_groups(tmp_path)

    assert len(groups) == 1
    group = groups[0]
    assert group.department == "accounting"
    assert group.doc_id == "PD-ACC-A-09"
    assert group.source_revision == "Rev 02"
    assert set(group.sources) == {"doc", "docx", "xls"}


def test_upload_queue_blocks_missing_business_code_before_mineru(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox" / "procedure" / "accounting"
    inbox.mkdir(parents=True)
    source = inbox / "Thoa thuan PĐ-TA.pdf"
    source.write_bytes(b"%PDF-1.4")

    groups = list_upload_document_groups(tmp_path)

    assert len(groups) == 1
    assert groups[0].code_detected is False

    fake = FakeUploadMinerUConverter()
    result = process_upload_queue(tmp_path, converter=fake, limit_groups=1)

    assert fake.calls == []
    assert result[0]["status"] == "failed"
    quality = json.loads(Path(result[0]["quality_report_path"]).read_text(encoding="utf-8"))
    assert quality["quality_status"] == "needs_human_input"
    assert quality["issues"][0]["type"] == "missing_or_unrecognized_business_document_code"
    assert (tmp_path / "inbox" / "procedure" / "failed" / "accounting" / source.name).exists()


def test_business_document_identity_normalizes_underscore_codes_and_forms() -> None:
    assert business_document_identity("PD_ACC_A_02. Rev 01. Quy trình hủy hàng.pdf")["code"] == "PD-ACC-A-02"
    assert business_document_identity("PD-ACC-A-018-Rev04 Quy trình kiểm kê kho.xlsx")["code"] == "PD-ACC-A-018"
    assert business_document_identity("PD-HR-051. Rev 06. Quy trình xin nghỉ việc.pdf")["code"] == "PD-HR-051"
    assert business_document_identity("BM-029.01_Rev 03. Báo cáo hạn dùng.docx")["code"] == "BM-029.01"
    assert business_document_identity("PL-092.01 Rev 04. Quy trình đăng ký đối tác.pdf")["code"] == "PL-092.01"


def test_upload_run_paths_shorten_long_missing_code_business_keys(tmp_path: Path) -> None:
    long_key = (
        "tender_legal_"
        + ("0_REGULATION_TERUMO-GROUP-THIRD-PARTY-ANTI-CORRUPTION-AND-ANTI-BRIBERY-POLICY_" * 2)
        + "rev01"
    )
    group = UploadDocumentGroup(
        business_key=long_key,
        canonical_business_code="LONG-FALLBACK-CODE",
        code_detected=False,
        display_code="LONG-FALLBACK-CODE",
        source_revision="Rev 01",
        revision_slug="rev01",
        doc_id="LONG-FALLBACK-CODE",
        title="Long tender policy",
        department="tender_legal",
        department_name="Tender Legal",
        category="procedure",
        artifact_stem=long_key,
        sources={},
    )

    paths = upload_run_paths(tmp_path, group)

    assert len(paths.staging.name) <= 96
    assert len(paths.converted_raw.name) <= 96
    assert len(paths.artifact_root.name) <= 96
    assert paths.staging.name == paths.converted_raw.name


def test_pdf_ocr_source_text_unavailable_can_use_rich_mineru_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4")
    primary = CandidateConversion(
        source_type="pdf",
        source_path=source,
        staged_source_path=source,
        raw_markdown_path=tmp_path / "raw.md",
        artifact_root=tmp_path / "mineru",
        mineru_artifact_index_path=tmp_path / "mineru" / "mineru_artifact_index.json",
        status="passed",
    )

    assert source_text_unavailable_but_mineru_ocr_evidence_is_rich(
        {"issues": ["source_text_unavailable"]},
        primary,
        {"has_content_list_v2": True, "has_middle_json": True},
        [{"locator_status": "resolved"}, {"locator_status": "resolved"}],
    )


def test_legacy_office_source_text_unavailable_can_use_rich_mineru_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source.xls"
    source.write_bytes(b"legacy workbook")
    primary = CandidateConversion(
        source_type="xls",
        source_path=source,
        staged_source_path=source,
        raw_markdown_path=tmp_path / "raw.md",
        artifact_root=tmp_path / "mineru",
        mineru_artifact_index_path=tmp_path / "mineru" / "mineru_artifact_index.json",
        status="passed",
    )

    assert source_text_unavailable_but_mineru_ocr_evidence_is_rich(
        {"issues": ["source_text_unavailable"]},
        primary,
        {"has_content_list": True, "has_middle_json": True},
        [{"locator_status": "resolved"}] * 5,
    )


def test_upload_approval_gate_requires_quality_and_primary_source_contract(tmp_path: Path) -> None:
    write_upload_pair(tmp_path)
    process_upload_queue(tmp_path, converter=FakeUploadMinerUConverter(), limit_groups=1)
    record = ManifestStore(tmp_path).load()[0]

    record.extra["quality_status"] = "needs_review"
    try:
        validate_record_for_approval(record)
    except ManifestError as exc:
        assert "quality_status=passed" in str(exc)
    else:
        raise AssertionError("expected quality gate to block approval")

    record.extra["quality_status"] = "passed"
    record.extra.pop("citation_map_path")
    try:
        validate_record_for_approval(record)
    except ManifestError as exc:
        assert "citation_map_path" in str(exc)
    else:
        raise AssertionError("expected citation map gate to block approval")

    record = ManifestStore(tmp_path).load()[0]
    review_path = Path(record.extra["human_review_path"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_status"] = "approved"
    review["reviewer"] = "ai-agent-quality-gate"
    review["checklist"] = {key: True for key in review["checklist"]}
    review_path.write_text(json.dumps(review), encoding="utf-8")
    try:
        validate_record_for_approval(record)
    except ManifestError as exc:
        assert "human reviewer" in str(exc)
    else:
        raise AssertionError("expected AI reviewer gate to block approval")


def test_upload_human_review_api_controls_approval(tmp_path: Path) -> None:
    write_upload_pair(tmp_path)
    process_upload_queue(tmp_path, converter=FakeUploadMinerUConverter(), limit_groups=1)
    client = TestClient(create_app(tmp_path))

    blocked = client.post(
        "/api/approve",
        json={"doc_id": "KT-QT-002", "version": "rev04", "approved_by": "Lead"},
    )
    assert blocked.status_code == 400
    assert "review_status=approved" in blocked.json()["detail"]

    checklist = {
        "title_correct": True,
        "revision_correct": True,
        "headings_source_based": True,
        "steps_order_correct": True,
        "no_synthetic_content": True,
        "citations_correct": True,
        "source_output_audit_passed": True,
    }
    review = client.post(
        "/api/human-review",
        json={
            "doc_id": "KT-QT-002",
            "version": "rev04",
            "review_status": "approved",
            "reviewer": "Lead",
            "checklist": checklist,
            "notes": "Approved after source comparison.",
        },
    )
    assert review.status_code == 200
    assert review.json()["review_status"] == "approved"

    approved = client.post(
        "/api/approve",
        json={"doc_id": "KT-QT-002", "version": "rev04", "approved_by": "Lead"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

    detail = client.get("/api/documents/KT-QT-002/rev04").json()
    assert detail["human_review"]["data"]["review_status"] == "approved"
    assert detail["human_review"]["data"]["checklist"] == checklist


def test_upload_rejected_review_is_visible_for_repair_queue(tmp_path: Path) -> None:
    write_upload_pair(tmp_path)
    process_upload_queue(tmp_path, converter=FakeUploadMinerUConverter(), limit_groups=1)
    client = TestClient(create_app(tmp_path))

    checklist = {
        "title_correct": True,
        "revision_correct": True,
        "headings_source_based": True,
        "steps_order_correct": False,
        "no_synthetic_content": True,
        "citations_correct": True,
        "source_output_audit_passed": True,
    }
    review = client.post(
        "/api/human-review",
        json={
            "doc_id": "KT-QT-002",
            "version": "rev04",
            "review_status": "rejected",
            "reviewer": "Lead",
            "checklist": checklist,
            "notes": "Step order needs repair.",
        },
    )
    assert review.status_code == 200

    rejected = client.post(
        "/api/reject",
        json={"doc_id": "KT-QT-002", "version": "rev04", "reason": "Step order needs repair."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed_review"

    queue = client.get("/api/review-queue")
    assert queue.status_code == 200
    body = queue.json()
    assert body["summary"] == {"pending_review": 0, "failed_review": 1}
    failed = body["failed_review"][0]
    assert failed["doc_id"] == "KT-QT-002"
    assert failed["status_reason"] == "Step order needs repair."
    assert failed["human_review"]["review_status"] == "rejected"
    assert failed["human_review"]["checklist"]["steps_order_correct"] is False


def test_upload_quality_flags_corrupted_title_text() -> None:
    assert looks_like_corrupted_metadata_text("Quy tr?nh b?o d??ng") is True
    assert looks_like_corrupted_metadata_text("H??ng d?n theo d?i CCDT k? s?") is True
    assert looks_like_corrupted_metadata_text("Quy trình bảo dưỡng") is False

    group = UploadDocumentGroup(
        business_key="PD-TECH-A-02_rev04",
        canonical_business_code="PD-TECH-A-02",
        code_detected=True,
        display_code="PD-TECH-A-02",
        source_revision="Rev 04",
        revision_slug="rev04",
        doc_id="KT-QT-002",
        title="Quy tr?nh b?o d??ng",
        department="technical",
        department_name="Phong Ky thuat",
        category="procedure",
        artifact_stem="KT-QT-002_rev04",
        sources={},
    )
    text = '---\ntitle: "Quy tr?nh b?o d??ng"\n---\n\n# PD-TECH-A-02 Rev 04 - Quy tr?nh b?o d??ng\n'

    issues = normalized_title_quality_issues(group, text)

    assert {issue["field"] for issue in issues} == {"group.title", "frontmatter.title", "h1"}
    assert all(issue["severity"] == "high" for issue in issues)


def test_build_rag_summary_section_extracts_steps_responsibilities_and_records() -> None:
    lines = [
        "5. Trách nhiệm / Bộ phận liên quan.",
        "5.1. Phòng Kỹ thuật:",
        "- Thực hiện bảo dưỡng",
        "6. Nội dung công việc.",
        "STT",
        "RACI",
        "1",
        "R",
        "Kế hoạch bảo dưỡng",
        "Hàng tháng",
        "*Thời gian thực hiện: Trước ngày 20 hàng tháng",
        "PD-TECH-A-02/BM-05",
        "2",
        "I,C",
        "R",
        "Lịch bảo dưỡng định kỳ",
        "*NV CSKH làm lịch bảo dưỡng chi tiết",
        "PD-TECH-A-02/BM-06",
        "3",
        "Khi phát sinh",
        "Đối chiếu dữ liệu kiểm kê thực tế",
        "BM-018.03",
        "7. Hồ sơ, tài liệu đính kèm",
        "7.1. PD-TECH-A-02/BM-05",
        ": Kế hoạch bảo dưỡng",
    ]

    summary = "\n".join(build_rag_summary_section(lines))

    assert "## Tóm tắt cấu trúc phục vụ RAG" in summary
    assert "Bước 1: Kế hoạch bảo dưỡng" in summary
    assert "Bước 2: Lịch bảo dưỡng định kỳ" in summary
    assert "Bước 3: Đối chiếu dữ liệu kiểm kê thực tế" in summary
    assert "Bước 3: Khi phát sinh" not in summary
    assert "5.1. Phòng Kỹ thuật" in summary
    assert "PD-TECH-A-02/BM-05" in summary


def test_generated_rag_summary_is_stripped_before_rebuild() -> None:
    lines = [
        "## Tom tat cau truc phuc vu RAG",
        "### Quy trinh thuc hien",
        "1. Buoc 1: stale generated summary",
        "### Trach nhiem",
        "- stale",
        "## Source section",
        "Source-backed content",
    ]

    cleaned = strip_generated_rag_summary_blocks(lines)

    assert cleaned == ["## Source section", "Source-backed content"]
