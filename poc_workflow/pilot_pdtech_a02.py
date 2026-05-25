from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .converter import MinerUConverter
from .database import QualityDatabase
from .manifest import ManifestStore
from .models import ManifestRecord
from .pipeline import approve_record, init_workspace, rebuild_indexes
from .utils import content_hash, safe_filename, utc_now, write_json


PILOT_DOC_ID = "KT-QT-002"
PILOT_INTERNAL_VERSION = "1.0"
PILOT_ARTIFACT_STEM = "KT-QT-002_rev04"
PILOT_DISPLAY_CODE = "PD-TECH-A-02"
PILOT_TITLE = "Quy trình bảo dưỡng"
PILOT_SOURCE_REVISION = "Rev 04"
PILOT_SCOPE_ID = "pdtech_a02_rev04_pilot"
SYNTHETIC_HEADINGS = {
    "fixing metadata",
    "incident response",
    "smart fix",
    "fix review",
}
RAW_PROMPT_DEBUG_MARKERS = {
    "agent task",
    "debug",
    "submitting mineru",
    "task completed",
    "quality gate",
    "repair loop",
}
CANONICAL_SECTION_TITLES = {
    "muc dich": "Mục đích",
    "pham vi": "Phạm vi áp dụng",
    "trach nhiem": "Trách nhiệm",
    "quy trinh": "Quy trình thực hiện",
    "noi dung cong viec": "Quy trình thực hiện",
    "cac buoc": "Quy trình thực hiện",
    "ho so": "Hồ sơ / biểu mẫu liên quan",
    "bieu mau": "Hồ sơ / biểu mẫu liên quan",
    "tai lieu lien quan": "Tài liệu liên quan",
}


class PilotError(RuntimeError):
    pass


@dataclass(frozen=True)
class PilotPaths:
    converted_raw: Path
    staging: Path
    normalized: Path
    section_index: Path
    chunk_plan: Path
    citation_map: Path
    probe_report: Path
    quality_report: Path
    review_report: Path


def run_pdtech_a02_pilot(
    root: Path,
    *,
    xlsx_path: Path | None = None,
    pdf_path: Path | None = None,
    primary_source: str = "auto",
    approve_review: bool = False,
    reviewer: str = "human",
    converter: MinerUConverter | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    init_workspace(root)
    paths = pilot_paths(root)
    for directory in {
        paths.converted_raw,
        paths.staging,
        paths.normalized.parent,
        paths.section_index.parent,
        paths.review_report.parent,
    }:
        directory.mkdir(parents=True, exist_ok=True)

    sources = resolve_pilot_sources(root, xlsx_path=xlsx_path, pdf_path=pdf_path)
    probe = build_source_probe_report(sources["xlsx"], sources["pdf"])
    selected = select_primary_source(probe, primary_source)
    decision = {
        "selected": selected,
        "reason": primary_decision_reason(probe, selected, primary_source),
        "decided_at": utc_now(),
        "decided_by": "human" if primary_source in {"xlsx", "pdf"} else "system",
        "probe_report_path": str(paths.probe_report),
    }
    probe["recommended_primary_source"] = selected
    probe["reason"] = decision["reason"]
    write_json(paths.probe_report, probe)

    primary_path = sources[selected]
    supporting_sources = build_supporting_sources(sources, selected)
    raw_md = paths.converted_raw / f"{PILOT_ARTIFACT_STEM}_raw.md"
    converter = converter or MinerUConverter.from_env()
    converter.convert_with_mineru(
        primary_path,
        raw_md,
        language="vi",
        artifact_root=paths.converted_raw / "mineru_raw",
    )

    normalized_text, section_index, citation_map = normalize_primary_source(primary_path, selected, raw_md)
    paths.staging.mkdir(parents=True, exist_ok=True)
    draft_path = paths.staging / f"{PILOT_ARTIFACT_STEM}_draft.md"
    draft_path.write_text(normalized_text, encoding="utf-8")
    write_json(paths.section_index, section_index)
    chunk_plan = build_chunk_plan(citation_map)
    write_json(paths.chunk_plan, chunk_plan)
    write_json(paths.citation_map, citation_map)

    quality_report = verify_normalized_markdown(
        draft_path,
        citation_map_path=paths.citation_map,
        primary_source_type=selected,
        raw_markdown_path=raw_md,
        raw_converter="mineru",
    )
    write_json(paths.quality_report, quality_report)
    if quality_report["quality_status"] != "passed":
        raise PilotError(f"Pilot verification failed: {quality_report['issues']}")

    paths.normalized.write_text(normalized_text, encoding="utf-8")
    review = build_review_report(approved=approve_review, reviewer=reviewer)
    write_json(paths.review_report, review)

    record = upsert_pilot_record(
        root,
        primary_path=primary_path,
        selected=selected,
        decision=decision,
        supporting_sources=supporting_sources,
        paths=paths,
        quality_report=quality_report,
        review=review,
        mineru_profile=converter.profile_dict() if hasattr(converter, "profile_dict") else {},
    )
    if approve_review:
        retire_duplicate_business_records(root, keep_key=record.key)
        record = approve_record(root, record.doc_id, record.version, reviewer)
    else:
        rebuild_indexes(root)

    return {
        "ok": True,
        "doc_id": record.doc_id,
        "version": record.version,
        "display_code": PILOT_DISPLAY_CODE,
        "display_version": PILOT_SOURCE_REVISION,
        "status": record.status,
        "primary_source": selected,
        "raw_converter": "mineru",
        "raw_path": str(raw_md),
        "mineru_profile": converter.profile_dict() if hasattr(converter, "profile_dict") else {},
        "normalized_path": str(paths.normalized),
        "probe_report_path": str(paths.probe_report),
        "citation_map_path": str(paths.citation_map),
        "review_report_path": str(paths.review_report),
        "quality_status": quality_report["quality_status"],
        "quality_score": quality_report["quality_score"],
    }


def pilot_paths(root: Path) -> PilotPaths:
    return PilotPaths(
        converted_raw=root / "converted_raw" / "pilot" / PILOT_DISPLAY_CODE,
        staging=root / "staging" / "pilot" / PILOT_DISPLAY_CODE,
        normalized=root / "normalized" / "technical" / "procedure" / f"{PILOT_ARTIFACT_STEM}.md",
        section_index=root / "indexes" / f"{PILOT_ARTIFACT_STEM}_section_index.json",
        chunk_plan=root / "indexes" / f"{PILOT_ARTIFACT_STEM}_chunk_plan.json",
        citation_map=root / "indexes" / f"{PILOT_ARTIFACT_STEM}_citation_map.json",
        probe_report=root / "converted_raw" / "pilot" / PILOT_DISPLAY_CODE / "source_probe_report.json",
        quality_report=root / "converted_raw" / "pilot" / PILOT_DISPLAY_CODE / "quality_report.json",
        review_report=root / "review" / "pilot" / PILOT_DISPLAY_CODE / "human_review.json",
    )


def resolve_pilot_sources(root: Path, *, xlsx_path: Path | None, pdf_path: Path | None) -> dict[str, Path]:
    xlsx = resolve_source_path(root, xlsx_path, ".xlsx")
    pdf = resolve_source_path(root, pdf_path, ".pdf")
    if not xlsx or not pdf:
        missing = []
        if not xlsx:
            missing.append("XLSX")
        if not pdf:
            missing.append("PDF")
        raise PilotError(
            "Missing pilot source(s): "
            + ", ".join(missing)
            + ". Place the original PD-TECH-A-02 Rev 04 files under root_source or pass explicit paths."
        )
    return {"xlsx": xlsx.resolve(), "pdf": pdf.resolve()}


def resolve_source_path(root: Path, explicit_path: Path | None, suffix: str) -> Path | None:
    if explicit_path:
        path = explicit_path if explicit_path.is_absolute() else root / explicit_path
        if not path.exists():
            raise PilotError(f"Source file does not exist: {path}")
        return path
    source_root = root / "root_source"
    if not source_root.exists():
        return None
    candidates = [
        path
        for path in source_root.rglob(f"*{suffix}")
        if PILOT_DISPLAY_CODE.replace("-", "").lower() in re.sub(r"[^A-Za-z0-9]+", "", path.name).lower()
        or "bao duong" in ascii_key(path.name)
    ]
    return sorted(candidates, key=lambda path: len(str(path)))[0] if candidates else None


def build_source_probe_report(xlsx_path: Path, pdf_path: Path) -> dict[str, Any]:
    xlsx_probe = probe_xlsx(xlsx_path)
    pdf_probe = probe_pdf(pdf_path)
    recommended = recommended_primary_source(xlsx_probe, pdf_probe)
    return {
        "doc_code": PILOT_DISPLAY_CODE,
        "source_revision": PILOT_SOURCE_REVISION,
        "xlsx_probe": xlsx_probe,
        "pdf_probe": pdf_probe,
        "recommended_primary_source": recommended,
        "reason": primary_decision_reason(
            {"xlsx_probe": xlsx_probe, "pdf_probe": pdf_probe},
            recommended,
            "auto",
        ),
    }


def probe_xlsx(path: Path) -> dict[str, Any]:
    issues: list[str] = []
    try:
        from openpyxl import load_workbook
    except Exception as exc:  # pragma: no cover - dependency guard
        return {
            "parse_score": 0.0,
            "sheet_count": 0,
            "table_quality": "bad",
            "merged_cells_risk": "high",
            "shape_text_risk": "high",
            "step_extraction_quality": "bad",
            "issues": [f"openpyxl_unavailable: {exc}"],
        }

    workbook = load_workbook(filename=path, data_only=True, read_only=False)
    sheet_count = len(workbook.sheetnames)
    non_empty_rows = 0
    non_empty_cells = 0
    merged_ranges = 0
    text_parts: list[str] = []
    drawing_count = 0
    for sheet in workbook.worksheets:
        merged_ranges += len(sheet.merged_cells.ranges)
        drawing_count += len(getattr(sheet, "_images", []) or [])
        for row in sheet.iter_rows(values_only=True):
            values = [str(value).strip() for value in row if value not in (None, "")]
            if not values:
                continue
            non_empty_rows += 1
            non_empty_cells += len(values)
            text_parts.extend(values)
    workbook.close()
    text = ascii_key(" ".join(text_parts))
    table_quality = "good" if non_empty_rows >= 8 and non_empty_cells >= 20 else "medium" if non_empty_rows >= 3 else "bad"
    merged_risk = "high" if merged_ranges >= 20 else "medium" if merged_ranges else "low"
    shape_risk = "medium" if drawing_count else "low"
    step_hits = sum(1 for term in ["quy trinh", "buoc", "noi dung", "trach nhiem", "ho so", "bieu mau"] if term in text)
    step_quality = "good" if step_hits >= 3 else "medium" if step_hits else "bad"
    score = 0.25
    score += {"good": 0.30, "medium": 0.15, "bad": 0.0}[table_quality]
    score += {"good": 0.30, "medium": 0.15, "bad": 0.0}[step_quality]
    score -= {"low": 0.0, "medium": 0.08, "high": 0.18}[merged_risk]
    score -= {"low": 0.0, "medium": 0.05, "high": 0.12}[shape_risk]
    if PILOT_DISPLAY_CODE.lower() not in path.name.lower() and "pd tech a 02" not in text:
        issues.append("doc_code_not_detected_in_xlsx")
        score -= 0.10
    return {
        "parse_score": round(max(0.0, min(1.0, score)), 2),
        "sheet_count": sheet_count,
        "table_quality": table_quality,
        "merged_cells_risk": merged_risk,
        "shape_text_risk": shape_risk,
        "step_extraction_quality": step_quality,
        "issues": issues,
    }


def probe_pdf(path: Path) -> dict[str, Any]:
    issues: list[str] = []
    page_count = 0
    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception as exc:
        issues.append(f"pdf_text_probe_failed: {exc}")
    chars_per_page = len(text.strip()) / page_count if page_count else 0
    ocr_quality = "good" if chars_per_page >= 300 else "medium" if chars_per_page >= 80 else "bad"
    layout_quality = "good" if page_count and "\n" in text else "medium" if text.strip() else "bad"
    page_locator_quality = "good" if page_count else "bad"
    score = 0.20
    score += {"good": 0.35, "medium": 0.18, "bad": 0.0}[ocr_quality]
    score += {"good": 0.20, "medium": 0.10, "bad": 0.0}[layout_quality]
    score += {"good": 0.15, "medium": 0.08, "bad": 0.0}[page_locator_quality]
    if PILOT_DISPLAY_CODE.lower() not in path.name.lower() and "pd tech a 02" not in ascii_key(text):
        issues.append("doc_code_not_detected_in_pdf")
        score -= 0.10
    return {
        "parse_score": round(max(0.0, min(1.0, score)), 2),
        "page_count": page_count,
        "ocr_quality": ocr_quality,
        "layout_quality": layout_quality,
        "page_locator_quality": page_locator_quality,
        "issues": issues,
    }


def select_primary_source(probe: dict[str, Any], primary_source: str) -> str:
    if primary_source not in {"auto", "xlsx", "pdf"}:
        raise PilotError("primary_source must be auto, xlsx, or pdf")
    if primary_source in {"xlsx", "pdf"}:
        return primary_source
    return str(
        probe.get("recommended_primary_source")
        or recommended_primary_source(probe.get("xlsx_probe") or {}, probe.get("pdf_probe") or {})
    )


def recommended_primary_source(xlsx_probe: dict[str, Any], pdf_probe: dict[str, Any]) -> str:
    xlsx_score = float(xlsx_probe.get("parse_score") or 0)
    pdf_score = float(pdf_probe.get("parse_score") or 0)
    if xlsx_probe.get("step_extraction_quality") == "good" and xlsx_score >= pdf_score - 0.10:
        return "xlsx"
    return "xlsx" if xlsx_score >= pdf_score else "pdf"


def primary_decision_reason(probe: dict[str, Any], selected: str, requested: str) -> str:
    if requested in {"xlsx", "pdf"}:
        return f"{requested.upper()} selected by explicit operator override."
    xlsx_score = float((probe.get("xlsx_probe") or {}).get("parse_score") or 0)
    pdf_score = float((probe.get("pdf_probe") or {}).get("parse_score") or 0)
    if selected == "xlsx":
        return f"XLSX selected because its parse score ({xlsx_score}) is >= PDF score ({pdf_score}) and table/step extraction is preferred."
    return f"PDF selected because its parse score ({pdf_score}) is higher than XLSX score ({xlsx_score})."


def build_supporting_sources(sources: dict[str, Path], selected: str) -> list[dict[str, Any]]:
    supporting = []
    for source_type, path in sources.items():
        if source_type == selected:
            continue
        supporting.append(
            {
                "type": source_type,
                "path": str(path),
                "role": "display_print_version" if source_type == "pdf" else "supporting_workbook",
                "used_for_retrieval": False,
            }
        )
    return supporting


def normalize_primary_source(
    primary_path: Path,
    source_type: str,
    raw_markdown_path: Path | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if raw_markdown_path is not None:
        return normalize_mineru_raw(raw_markdown_path, primary_path, source_type)
    if source_type == "xlsx":
        return normalize_xlsx(primary_path)
    return normalize_pdf(primary_path)


def normalize_mineru_raw(
    raw_markdown_path: Path,
    primary_path: Path,
    source_type: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    raw_text = raw_markdown_path.read_text(encoding="utf-8", errors="ignore")
    if len(raw_text.strip()) < 20:
        raise PilotError(f"MinerU raw Markdown is empty or too short: {raw_markdown_path}")

    lines = frontmatter_lines(source_type, primary_path)
    section_index: list[dict[str, Any]] = []
    citation_map: list[dict[str, Any]] = []
    active_section: dict[str, Any] | None = None
    body_lines: list[str] = []
    anchor_counter = 0
    current_sheet: str | None = None
    current_page: int | None = None

    for raw_line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or raw_line_is_noise(line):
            continue

        heading_text = markdown_heading_text(line)
        if heading_text:
            sheet_name = sheet_title_from_heading(heading_text)
            if sheet_name:
                current_sheet = sheet_name
                continue
            page_number = page_number_from_heading(heading_text)
            if page_number:
                current_page = page_number
            canonical_heading = canonical_heading_for_text(heading_text)
            if canonical_heading and not is_document_title_heading(heading_text):
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        source_type,
                    )
                    body_lines = []
                active_section = raw_section(
                    canonical_heading,
                    raw_line_number,
                    source_type,
                    current_sheet=current_sheet,
                    current_page=current_page,
                )
                continue
            if is_document_title_heading(heading_text):
                continue

        values = markdown_table_values(line)
        normalized_line = ""
        if values is not None:
            if not values:
                continue
            canonical_heading = canonical_heading_for_text(" | ".join(values))
            if canonical_heading and len(values) <= 2:
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        source_type,
                    )
                    body_lines = []
                active_section = raw_section(
                    canonical_heading,
                    raw_line_number,
                    source_type,
                    current_sheet=current_sheet,
                    current_page=current_page,
                    column_count=len(values),
                )
                continue
            normalized_line = markdown_line_for_values(values)
            column_count = len(values)
        else:
            canonical_heading = canonical_heading_for_text(line)
            if canonical_heading and len(line) <= 80:
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        source_type,
                    )
                    body_lines = []
                active_section = raw_section(
                    canonical_heading,
                    raw_line_number,
                    source_type,
                    current_sheet=current_sheet,
                    current_page=current_page,
                )
                continue
            normalized_line = clean_cell(line)
            column_count = 1

        if not active_section:
            active_section = raw_section(
                PILOT_TITLE,
                raw_line_number,
                source_type,
                current_sheet=current_sheet,
                current_page=current_page,
                column_count=column_count,
            )
        active_section["raw_line_end"] = raw_line_number
        active_section["columns"] = columns_for_values(max(column_count, len(active_section.get("columns", []))))
        if current_page and source_type == "pdf":
            active_section["page_end"] = current_page
        body_lines.append(normalized_line)

    if active_section:
        finalize_section(active_section, body_lines, lines, section_index, citation_map, anchor_counter, source_type)
    return "\n".join(lines).strip() + "\n", section_index, citation_map


def raw_section(
    title: str,
    raw_line_number: int,
    source_type: str,
    *,
    current_sheet: str | None = None,
    current_page: int | None = None,
    column_count: int = 1,
) -> dict[str, Any]:
    section: dict[str, Any] = {
        "title": title,
        "raw_line_start": raw_line_number,
        "raw_line_end": raw_line_number,
        "columns": columns_for_values(column_count),
    }
    if source_type == "xlsx":
        section["sheet"] = current_sheet or "MinerU raw"
    if source_type == "pdf":
        section["page_start"] = current_page or 1
        section["page_end"] = current_page or 1
    return section


def markdown_heading_text(line: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
    return match.group(1).strip() if match else None


def sheet_title_from_heading(heading: str) -> str | None:
    match = re.match(r"sheet\s*:\s*(.+)$", heading, flags=re.IGNORECASE)
    return clean_cell(match.group(1)) if match else None


def page_number_from_heading(heading: str) -> int | None:
    match = re.match(r"(?:page|trang)\s+(\d+)", ascii_key(heading), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def is_document_title_heading(heading: str) -> bool:
    normalized = ascii_key(heading)
    return PILOT_DISPLAY_CODE.lower().replace("-", " ") in normalized or "quy trinh bao duong" in normalized


def markdown_table_values(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or "|" not in stripped[1:]:
        return None
    cells = [clean_cell(cell) for cell in stripped.strip("|").split("|")]
    if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells if cell):
        return []
    return [cell for cell in cells if cell]


def raw_line_is_noise(line: str) -> bool:
    normalized = ascii_key(line)
    return any(marker in normalized for marker in RAW_PROMPT_DEBUG_MARKERS)


def count_raw_prompt_debug_markers(text: str) -> int:
    normalized = ascii_key(text)
    return sum(1 for marker in RAW_PROMPT_DEBUG_MARKERS if marker in normalized)


def normalize_xlsx(path: Path) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    from openpyxl import load_workbook

    workbook = load_workbook(filename=path, data_only=True, read_only=True)
    lines = frontmatter_lines("xlsx", path)
    section_index: list[dict[str, Any]] = []
    citation_map: list[dict[str, Any]] = []
    active_section: dict[str, Any] | None = None
    body_lines: list[str] = []
    anchor_counter = 0

    for sheet in workbook.worksheets:
        for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = [clean_cell(value) for value in row]
            values = [value for value in values if value]
            if not values:
                continue
            joined = " | ".join(values)
            heading = canonical_heading_for_text(joined)
            if heading:
                if active_section:
                    anchor_counter = finalize_section(
                        active_section,
                        body_lines,
                        lines,
                        section_index,
                        citation_map,
                        anchor_counter,
                        "xlsx",
                    )
                    body_lines = []
                active_section = {
                    "title": heading,
                    "sheet": sheet.title,
                    "row_start": row_number,
                    "row_end": row_number,
                    "columns": columns_for_values(len(values)),
                }
                continue
            if not active_section:
                active_section = {
                    "title": PILOT_TITLE,
                    "sheet": sheet.title,
                    "row_start": row_number,
                    "row_end": row_number,
                    "columns": columns_for_values(len(values)),
                }
            active_section["row_end"] = row_number
            active_section["columns"] = columns_for_values(max(len(values), len(active_section.get("columns", []))))
            body_lines.append(markdown_line_for_values(values))

    if active_section:
        finalize_section(active_section, body_lines, lines, section_index, citation_map, anchor_counter, "xlsx")
    workbook.close()
    return "\n".join(lines).strip() + "\n", section_index, citation_map


def normalize_pdf(path: Path) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    lines = frontmatter_lines("pdf", path)
    section_index: list[dict[str, Any]] = []
    citation_map: list[dict[str, Any]] = []
    anchor_counter = 0
    for page_index, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if not page_text:
            continue
        heading = canonical_heading_for_text(page_text.splitlines()[0]) or f"Trang {page_index}"
        lines.extend([f"## {heading}", ""])
        start_line = len(lines) + 1
        page_lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        lines.extend(page_lines)
        lines.append("")
        anchor_counter += 1
        anchor_id = f"KT-QT-002-S{anchor_counter:02d}-C01"
        section_index.append(
            {
                "anchor_id": anchor_id,
                "title": heading,
                "line_start": start_line,
                "line_end": len(lines) - 1,
            }
        )
        citation_map.append(
            {
                "anchor_id": anchor_id,
                "source_type": "pdf",
                "section_title": heading,
                "source_locator": {"page_start": page_index, "page_end": page_index},
                "display_locator": f"Trang {page_index}",
                "normalized_path": f"normalized/technical/procedure/{PILOT_ARTIFACT_STEM}.md",
            }
        )
    return "\n".join(lines).strip() + "\n", section_index, citation_map


def frontmatter_lines(source_type: str, source_path: Path) -> list[str]:
    return [
        "---",
        f"doc_id: {PILOT_DOC_ID}",
        f"display_code: {PILOT_DISPLAY_CODE}",
        f"canonical_business_code: {PILOT_DISPLAY_CODE}",
        f"title: {PILOT_TITLE}",
        f"internal_version: {PILOT_INTERNAL_VERSION}",
        f"source_revision: {PILOT_SOURCE_REVISION}",
        f"display_version: {PILOT_SOURCE_REVISION}",
        f"primary_source_type: {source_type}",
        f"primary_source_file: {source_path.name}",
        "quality_status: passed",
        "---",
        "",
        f"# {PILOT_TITLE}",
        "",
    ]


def finalize_section(
    section: dict[str, Any],
    body_lines: list[str],
    lines: list[str],
    section_index: list[dict[str, Any]],
    citation_map: list[dict[str, Any]],
    anchor_counter: int,
    source_type: str,
) -> int:
    if not body_lines:
        return anchor_counter
    anchor_counter += 1
    anchor_id = f"KT-QT-002-S{anchor_counter:02d}-C01"
    lines.extend([f"## {section['title']}", ""])
    start_line = len(lines) + 1
    lines.extend(body_lines)
    lines.append("")
    section_index.append(
        {
            "anchor_id": anchor_id,
            "title": section["title"],
            "line_start": start_line,
            "line_end": len(lines) - 1,
        }
    )
    if "raw_line_start" in section:
        locator = {
            "raw_markdown_line_start": section["raw_line_start"],
            "raw_markdown_line_end": section["raw_line_end"],
        }
        if source_type == "xlsx":
            locator.update(
                {
                    "sheet": section.get("sheet") or "MinerU raw",
                    "row_start": section["raw_line_start"],
                    "row_end": section["raw_line_end"],
                    "row_basis": "mineru_raw_line",
                    "columns": section.get("columns") or ["raw"],
                }
            )
            display_locator = (
                f"MinerU raw từ XLSX"
                f"{' - Sheet ' + str(section.get('sheet')) if section.get('sheet') else ''}, "
                f"dòng {section['raw_line_start']}-{section['raw_line_end']}"
            )
        else:
            locator.update(
                {
                    "page_start": section.get("page_start", 1),
                    "page_end": section.get("page_end", section.get("page_start", 1)),
                }
            )
            display_locator = (
                f"MinerU raw từ PDF, dòng {section['raw_line_start']}-{section['raw_line_end']}; "
                f"trang {locator['page_start']}-{locator['page_end']}"
            )
    elif source_type == "xlsx":
        locator = {
            "sheet": section["sheet"],
            "row_start": section["row_start"],
            "row_end": section["row_end"],
            "columns": section["columns"],
        }
        display_locator = f"Sheet {section['sheet']}, dòng {section['row_start']}-{section['row_end']}"
    else:
        locator = {"page_start": section["page_start"], "page_end": section["page_end"]}
        display_locator = f"Trang {section['page_start']}-{section['page_end']}"
    citation_map.append(
        {
            "anchor_id": anchor_id,
            "source_type": source_type,
            "section_title": section["title"],
            "source_locator": locator,
            "display_locator": display_locator,
            "normalized_path": f"normalized/technical/procedure/{PILOT_ARTIFACT_STEM}.md",
        }
    )
    return anchor_counter


def verify_normalized_markdown(
    markdown_path: Path,
    *,
    citation_map_path: Path,
    primary_source_type: str,
    raw_markdown_path: Path | None = None,
    raw_converter: str | None = None,
) -> dict[str, Any]:
    text = markdown_path.read_text(encoding="utf-8", errors="ignore")
    citation_map = json.loads(citation_map_path.read_text(encoding="utf-8")) if citation_map_path.exists() else []
    issues: list[dict[str, Any]] = []
    raw_text = ""
    raw_non_empty: bool | None = None
    raw_prompt_debug_count = 0
    raw_synthetic_heading_count = 0
    if raw_markdown_path is not None:
        if not raw_markdown_path.exists():
            raw_non_empty = False
            issues.append(
                {
                    "type": "missing_mineru_raw_markdown",
                    "severity": "high",
                    "text": str(raw_markdown_path),
                }
            )
        else:
            raw_text = raw_markdown_path.read_text(encoding="utf-8", errors="ignore")
            raw_non_empty = len(raw_text.strip()) >= 20
            if not raw_non_empty:
                issues.append(
                    {
                        "type": "empty_mineru_raw_markdown",
                        "severity": "high",
                        "text": str(raw_markdown_path),
                    }
                )
            raw_prompt_debug_count = count_raw_prompt_debug_markers(raw_text)
            if raw_prompt_debug_count:
                issues.append(
                    {
                        "type": "raw_prompt_debug_or_status_leak",
                        "severity": "high",
                        "text": str(raw_prompt_debug_count),
                    }
                )
            for heading in markdown_headings(raw_text):
                if ascii_key(heading) in SYNTHETIC_HEADINGS:
                    raw_synthetic_heading_count += 1
                    issues.append(
                        {
                            "type": "synthetic_heading_not_in_source",
                            "severity": "high",
                            "text": heading,
                            "location": "raw_markdown",
                            "action": "remove_or_move_to_internal_metadata",
                        }
                    )
    for heading in markdown_headings(text):
        if ascii_key(heading) in SYNTHETIC_HEADINGS:
            issues.append(
                {
                    "type": "synthetic_heading_not_in_source",
                    "severity": "high",
                    "text": heading,
                    "action": "remove_or_move_to_internal_metadata",
                }
            )
    if not citation_map:
        issues.append(
            {
                "type": "missing_citation_anchor",
                "severity": "high",
                "text": "citation_map_empty",
            }
        )
    for item in citation_map:
        if not item.get("anchor_id") or not item.get("source_locator"):
            issues.append(
                {
                    "type": "missing_citation_anchor",
                    "severity": "high",
                    "text": str(item.get("section_title") or item),
                }
            )
        if item.get("source_type") != primary_source_type:
            issues.append(
                {
                    "type": "citation_source_type_mismatch",
                    "severity": "high",
                    "text": str(item.get("anchor_id") or ""),
                }
            )
    score = quality_score(issues)
    combined_text = ascii_key(raw_text + "\n" + text)
    return {
        "doc_id": PILOT_DOC_ID,
        "display_code": PILOT_DISPLAY_CODE,
        "quality_status": "passed" if score >= 0.90 and not any(issue["severity"] == "high" for issue in issues) else "needs_review",
        "quality_score": score,
        "raw_conversion_engine": raw_converter or "unknown",
        "raw_markdown_path": str(raw_markdown_path) if raw_markdown_path else None,
        "raw_non_empty": raw_non_empty,
        "normalized_non_empty": len(text.strip()) >= 20,
        "source_revision_detected": "rev 04" in combined_text,
        "display_code_detected": "pd tech a 02" in combined_text or "pdtecha02" in combined_text.replace(" ", ""),
        "synthetic_heading_count": sum(1 for issue in issues if issue["type"] == "synthetic_heading_not_in_source"),
        "raw_synthetic_heading_count": raw_synthetic_heading_count,
        "raw_prompt_debug_count": raw_prompt_debug_count,
        "missing_citation_anchor_count": sum(1 for issue in issues if issue["type"] == "missing_citation_anchor"),
        "issues": issues,
        "checked_at": utc_now(),
    }


def quality_score(issues: list[dict[str, Any]]) -> float:
    score = 1.0
    for issue in issues:
        severity = issue.get("severity")
        if severity == "high":
            score -= 0.25
        elif severity == "medium":
            score -= 0.10
        else:
            score -= 0.03
    return round(max(0.0, score), 2)


def build_chunk_plan(citation_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks = []
    for index, citation in enumerate(citation_map, start=1):
        chunks.append(
            {
                "chunk_id": f"KT-QT-002-S{index:02d}-C01",
                "anchor_id": citation["anchor_id"],
                "doc_id": PILOT_DOC_ID,
                "display_code": PILOT_DISPLAY_CODE,
                "source_revision": PILOT_SOURCE_REVISION,
                "section_title": citation.get("section_title"),
                "source_type": citation.get("source_type"),
                "display_locator": citation.get("display_locator"),
            }
        )
    return chunks


def build_review_report(*, approved: bool, reviewer: str) -> dict[str, Any]:
    status = "approved" if approved else "needs_fix"
    checklist = {
        "title_correct": approved,
        "revision_correct": approved,
        "headings_source_based": approved,
        "steps_order_correct": approved,
        "no_synthetic_content": approved,
        "citations_correct": approved,
        "chat_step_by_step_passed": approved,
    }
    return {
        "review_status": status,
        "reviewer": reviewer,
        "reviewed_at": utc_now() if approved else None,
        "checklist": checklist,
        "notes": "" if approved else "Awaiting human review approval.",
    }


def upsert_pilot_record(
    root: Path,
    *,
    primary_path: Path,
    selected: str,
    decision: dict[str, Any],
    supporting_sources: list[dict[str, Any]],
    paths: PilotPaths,
    quality_report: dict[str, Any],
    review: dict[str, Any],
    mineru_profile: dict[str, Any],
) -> ManifestRecord:
    now = utc_now()
    record = ManifestRecord(
        doc_id=PILOT_DOC_ID,
        title=f"{PILOT_DISPLAY_CODE} {PILOT_SOURCE_REVISION} - {PILOT_TITLE}",
        department="technical",
        category="procedure",
        source_type="internal_procedure",
        language="vi",
        version=PILOT_INTERNAL_VERSION,
        status="pending_review",
        status_reason="Awaiting human review" if review["review_status"] != "approved" else None,
        effective_from=now[:10],
        review_at=None,
        owner="Phong Ky thuat",
        approved_by=None,
        source_path=str(primary_path),
        normalized_path=str(paths.normalized),
        content_hash=content_hash(primary_path),
        access_group="technical",
        created_at=now,
        updated_at=now,
        extra={
            "display_code": PILOT_DISPLAY_CODE,
            "canonical_business_code": PILOT_DISPLAY_CODE,
            "original_name": PILOT_TITLE,
            "original_filename": primary_path.name,
            "internal_version": PILOT_INTERNAL_VERSION,
            "source_revision": PILOT_SOURCE_REVISION,
            "display_version": PILOT_SOURCE_REVISION,
            "primary_source_type": selected,
            "primary_source_path": str(primary_path),
            "supporting_sources": supporting_sources,
            "keep_original_filename": True,
            "dedupe_group": PILOT_DISPLAY_CODE,
            "ingest_policy": "primary_source_only",
            "used_for_retrieval": True,
            "artifact_stem": PILOT_ARTIFACT_STEM,
            "raw_converter": "mineru",
            "raw_conversion_policy": "mineru_only_no_fallback",
            "raw_markdown_path": str(paths.converted_raw / f"{PILOT_ARTIFACT_STEM}_raw.md"),
            "mineru_profile": mineru_profile,
            "source_probe_report_path": str(paths.probe_report),
            "primary_source_decision": decision,
            "section_index_path": str(paths.section_index),
            "chunk_plan_path": str(paths.chunk_plan),
            "citation_map_path": str(paths.citation_map),
            "quality_report_path": str(paths.quality_report),
            "quality_status": quality_report["quality_status"],
            "quality_score": quality_report["quality_score"],
            "review_report_path": str(paths.review_report),
            "review_status": review["review_status"],
            "active_scope_id": PILOT_SCOPE_ID,
        },
    )
    ManifestStore(root).upsert(record)
    QualityDatabase(root).log_ingestion("pilot_pending_review", record.doc_id, record.version)
    return record


def retire_duplicate_business_records(root: Path, *, keep_key: str) -> None:
    store = ManifestStore(root)
    records = store.load()
    changed = False
    now = utc_now()
    for record in records:
        if record.key == keep_key:
            continue
        if record_business_identity(record) != PILOT_DISPLAY_CODE:
            continue
        if record.status in {"active", "pending_review", "normalized", "staging"}:
            record.status = "archived"
            record.status_reason = f"Deduped by pilot {PILOT_DOC_ID} {PILOT_SOURCE_REVISION}; primary_source_only."
            record.effective_to = record.effective_to or now[:10]
            record.updated_at = now
            changed = True
    if changed:
        store.save(records)


def record_business_identity(record: ManifestRecord) -> str | None:
    extra = record.extra or {}
    for key in ("canonical_business_code", "display_code", "dedupe_group", "canonical_doc_id"):
        value = extra.get(key)
        if value and str(value).upper() == PILOT_DISPLAY_CODE:
            return PILOT_DISPLAY_CODE
    if PILOT_DISPLAY_CODE in str(record.title).upper().replace(" ", "-"):
        return PILOT_DISPLAY_CODE
    return None


def markdown_headings(text: str) -> list[str]:
    headings = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(1).strip())
    return headings


def canonical_heading_for_text(text: str) -> str | None:
    normalized = ascii_key(text)
    for marker, title in CANONICAL_SECTION_TITLES.items():
        if marker in normalized:
            return title
    return None


def markdown_line_for_values(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return "- " + " | ".join(values)


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", "\n").split()).strip()


def columns_for_values(count: int) -> list[str]:
    return [column_label(index) for index in range(1, count + 1)]


def column_label(index: int) -> str:
    label = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def ascii_key(value: object) -> str:
    import unicodedata

    text = "".join(
        char for char in unicodedata.normalize("NFD", str(value)) if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
