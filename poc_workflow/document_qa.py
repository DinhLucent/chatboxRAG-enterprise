from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .utils import utc_now, write_json


MOJIBAKE_PATTERNS = (
    re.compile(r"\u00c3[\u0080-\u00bf\u0192\u201a-\u201e\u2020-\u2021\u02c6\u2030\u0160\u2039\u0152\u017d]"),
    re.compile(r"\u00c2[\u0080-\u00bf]"),
    re.compile(r"\u00e2[\u0080-\u20ac][\u0080-\u2122]"),
    re.compile(r"\u00e1[\u00ba\u00bb]"),
    re.compile(r"\u00c4[\u0080-\u01b0]"),
    re.compile(r"\u00c6[\u0080-\u01b0]"),
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


def mojibake_score(text: str) -> int:
    return text.count("\ufffd") + text.count("\u00ef\u00bf\u00bd") + sum(
        len(pattern.findall(text)) for pattern in MOJIBAKE_PATTERNS
    )


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
