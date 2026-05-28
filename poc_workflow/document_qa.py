from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .utils import tokenize, utc_now, write_json


MOJIBAKE_PATTERNS = (
    re.compile(r"\u00c3[\u0080-\u00bf\u0192\u201a-\u201e\u2020-\u2021\u02c6\u2030\u0160\u2039\u0152\u017d]"),
    re.compile(r"\u00c2[\u0080-\u00bf]"),
    re.compile(r"\u00e2[\u0080-\u20ac][\u0080-\u2122]"),
    re.compile(r"\u00e1[\u00ba\u00bb]"),
    re.compile(r"\u00c4[\u0080-\u01b0]"),
    re.compile(r"\u00c6[\u0080-\u01b0]"),
)
COMMON_MOJIBAKE_MARKERS = tuple(
    "".join(chr(codepoint) for codepoint in codepoints)
    for codepoints in (
        (0x00C4,),
        (0x00C5,),
        (0x00C6,),
        (0x00C7,),
        (0x00E1, 0x00BA),
        (0x00E1, 0x00BB),
        (0x00EF, 0x00BC),
        (0x00E2, 0x20AC),
    )
)


@dataclass
class MarkdownQaResult:
    status: str
    issues: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=utc_now)
    markdown_path: str = ""
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def qa_markdown(markdown_path: Path, report_path: Path | None = None) -> MarkdownQaResult:
    text = markdown_path.read_text(encoding="utf-8", errors="replace")
    issues: list[str] = []
    corrections: list[str] = []

    original_score = mojibake_score(text)
    if original_score:
        repaired = repair_mojibake(text)
        if repaired and mojibake_score(repaired) < original_score:
            markdown_path.write_text(repaired, encoding="utf-8")
            text = repaired
            corrections.append("repaired_mojibake_cp1252_utf8")

    stripped = text.strip()
    score = mojibake_score(text)
    replacement_count = text.count("\ufffd") + text.count("\u00ef\u00bf\u00bd")
    empty_table_cells = text.count("<p></p>") + text.count("<p> </p>")

    if len(stripped) < 20:
        issues.append("markdown_empty_or_too_short")
    if score:
        issues.append("possible_mojibake")
    if replacement_count:
        issues.append("replacement_characters_present")
    if empty_table_cells >= 50:
        issues.append("many_empty_table_cells")

    hard_failures = {"markdown_empty_or_too_short", "possible_mojibake", "replacement_characters_present"}
    if any(issue in hard_failures for issue in issues):
        status = "fail"
    elif corrections:
        status = "repaired"
    else:
        status = "pass"

    result = MarkdownQaResult(
        status=status,
        issues=issues,
        corrections=corrections,
        metrics={
            "characters": len(text),
            "lines": text.count("\n") + 1 if text else 0,
            "mojibake_score": score,
            "replacement_characters": replacement_count,
            "empty_table_cells": empty_table_cells,
        },
        markdown_path=str(markdown_path.resolve()),
        report_path=str(report_path.resolve()) if report_path else None,
    )
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(report_path, result.to_dict())
    return result


def qa_source_output(source_path: Path, markdown_path: Path, report_path: Path | None = None) -> MarkdownQaResult:
    result = qa_markdown(markdown_path)
    markdown_status = result.status
    markdown_text = markdown_path.read_text(encoding="utf-8", errors="replace")
    source_text, extraction = extract_source_text(source_path)
    source_compared = bool(source_text.strip())
    source_terms = _meaningful_terms(source_text)
    markdown_terms = _meaningful_terms(markdown_text)
    matched_terms = sorted(source_terms & markdown_terms)
    coverage = round(len(matched_terms) / max(1, len(source_terms)), 4) if source_terms else 0.0
    source_issues: list[str] = []

    if not source_compared:
        source_issues.append("source_text_unavailable")
    elif len(source_terms) >= 30 and coverage < 0.08:
        source_issues.append("source_output_coverage_too_low")
    elif len(source_terms) >= 10 and coverage < 0.03:
        source_issues.append("source_output_coverage_too_low")

    issues = [*result.issues, *source_issues]
    hard_failures = {"markdown_empty_or_too_short", "possible_mojibake", "replacement_characters_present", "source_text_unavailable"}
    if any(issue in hard_failures for issue in issues):
        status = "fail"
    elif "source_output_coverage_too_low" in issues:
        status = "fail"
    elif result.corrections:
        status = "repaired"
    else:
        status = result.status

    result.status = status
    result.issues = issues
    result.metrics = {
        **result.metrics,
        "source_path": str(source_path.resolve()),
        "source_type": source_path.suffix.lower().lstrip(".") or "file",
        "source_compared": source_compared,
        "source_extraction": extraction,
        "source_terms": len(source_terms),
        "matched_source_terms": len(matched_terms),
        "source_token_coverage": coverage,
        "sample_matched_terms": matched_terms[:25],
        "quality_gates": {
            "source_compared": source_compared,
            "required_coverage_passed": "source_output_coverage_too_low" not in source_issues and source_compared,
            "markdown_quality_passed": markdown_status in {"pass", "repaired"},
        },
    }
    result.report_path = str(report_path.resolve()) if report_path else None
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(report_path, result.to_dict())
    return result


def extract_source_text(path: Path) -> tuple[str, dict[str, Any]]:
    suffix = path.suffix.lower()
    try:
        if suffix in {".md", ".markdown", ".txt", ".csv", ".json", ".xml", ".html", ".htm"}:
            return path.read_text(encoding="utf-8", errors="replace"), {"method": "text"}
        if suffix == ".xlsx":
            return _extract_xlsx_text(path), {"method": "xlsx_xml"}
        if suffix == ".docx":
            return _extract_docx_text(path), {"method": "docx_xml"}
        if suffix == ".pdf":
            return _extract_pdf_text(path), {"method": "pdf_text"}
    except Exception as exc:
        return "", {"method": suffix.lstrip(".") or "unknown", "error": str(exc)}
    return "", {"method": "unsupported", "suffix": suffix}


def _extract_pdf_text(path: Path) -> str:
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(text)
                for table in page.extract_tables() or []:
                    for row in table:
                        parts.append(" ".join(str(cell or "") for cell in row))
        return "\n".join(parts)
    except Exception:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_xlsx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        parts: list[str] = []
        for sheet_path in sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml")):
            root = ET.fromstring(archive.read(sheet_path))
            for cell in root.findall(".//{*}c"):
                value = _xlsx_cell_value(cell, shared_strings)
                if value:
                    parts.append(value)
        return "\n".join(parts)


def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        return "\n".join(node.text or "" for node in root.findall(".//{*}t"))


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//{*}t")) for item in root.findall(".//{*}si")]


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{*}t")).strip()
    value_node = cell.find("{*}v")
    raw_value = (value_node.text or "") if value_node is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)].strip()
        except Exception:
            return raw_value.strip()
    return raw_value.strip()


def _meaningful_terms(text: str) -> set[str]:
    return {term for term in tokenize(text) if len(term) >= 3 and not term.isdigit()}


def mojibake_score(text: str) -> int:
    score = text.count("\ufffd") + text.count("\u00ef\u00bf\u00bd")
    score += sum(len(pattern.findall(text)) for pattern in MOJIBAKE_PATTERNS)
    score += sum(text.count(marker) for marker in COMMON_MOJIBAKE_MARKERS)
    return score


def repair_mojibake(text: str) -> str | None:
    candidates: list[str] = []
    for encoding in ("cp1252", "latin1"):
        try:
            candidates.append(text.encode(encoding).decode("utf-8"))
        except UnicodeError:
            continue
    if not candidates:
        return None
    return min(candidates, key=mojibake_score)
