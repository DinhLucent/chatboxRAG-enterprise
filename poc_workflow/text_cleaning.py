from __future__ import annotations

import html
import re
import unicodedata

RAW_MARKUP_MARKERS = (
    "<table",
    "<tr",
    "<td",
    "<th",
    "<img",
    "rowspan",
    "colspan",
    "src=",
)

CONTENT_HEADING_TERMS = (
    "muc dich",
    "pham vi",
    "noi dung",
    "trinh tu",
    "trach nhiem",
    "bieu mau",
    "ho so",
    "xu ly",
    "su co",
    "quy trinh",
)

LOW_VALUE_TERMS = (
    "tong hop danh sach",
    "danh muc cac tai lieu",
    "danh sach quy trinh",
    "loai tai lieu",
    "tinh trang",
    "ghi chu bieu mau",
    "so do quy trinh",
    "raci",
    "tan suat",
    "ket qua",
    "trach nhiem thuc hien",
    "trach nhiem phe duyet",
    "column 1",
    "column 2",
    "lich su chinh sua",
    "nguoi soan",
    "nguoi phe duyet",
    "ma tai lieu",
    "phien ban",
    "so trang",
    "ngay ban hanh",
    "ngay ban hanh sua doi",
)


def contains_raw_markup(value: object) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in RAW_MARKUP_MARKERS)


def clean_retrieval_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    if not text.strip():
        return ""

    text = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)
    text = re.sub(r"<\s*img\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsrc\s*=\s*(['\"])[^'\"]*\1", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:rowspan|colspan)\s*=\s*(['\"])?\d+\1?", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(?:p|div|section|article|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(?:td|th)\s*>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*tr\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(?:table|thead|tbody)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\b(?:rowspan|colspan)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bimages/[^\s)'\"]+", " ", text, flags=re.IGNORECASE)

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" |")
        line = re.sub(r"(?:\s*\|\s*){2,}", " | ", line).strip(" |")
        if not line or line in {"|", "-", "--"}:
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def clean_excerpt(value: object, max_chars: int = 720) -> str:
    text = re.sub(r"\s+", " ", clean_retrieval_text(value)).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def normalized_text(value: object) -> str:
    text = str(value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.lower()


def is_low_value_retrieval_text(value: object) -> bool:
    cleaned = clean_retrieval_text(value)
    if len(cleaned) < 30:
        return True
    normalized = normalized_text(cleaned)
    if "tom tat cau truc phuc vu rag" in normalized and "buoc " not in normalized and "ho so" not in normalized:
        return True
    low_hits = sum(1 for term in LOW_VALUE_TERMS if term in normalized)
    content_hits = sum(1 for term in CONTENT_HEADING_TERMS if term in normalized)
    if low_hits >= 4 and content_hits == 0:
        return True
    alpha_chars = len(re.findall(r"[A-Za-zÀ-ỹ]", cleaned))
    return alpha_chars < 20


def retrieval_quality_adjustment(*, text: object, title: object = "", category: object = "", query: object = "") -> int:
    cleaned = clean_retrieval_text(text)
    normalized = normalized_text(" ".join([cleaned, str(title or ""), str(category or "")]))
    adjustment = 0
    
    norm_query = normalized_text(str(query or ""))
    is_query_procedure = any(term in norm_query for term in ["quy trinh", "quy dinh", "huong dan", "chinh sach", "sop", "policy"])
    
    content_hits = sum(1 for term in CONTENT_HEADING_TERMS if term in normalized)
    if content_hits >= 2 and is_query_procedure:
        adjustment += content_hits * 2
    low_hits = sum(1 for term in LOW_VALUE_TERMS if term in normalized_text(cleaned))
    adjustment -= low_hits
    if "lich su chinh sua" in normalized_text(cleaned) or "so chinh sua" in normalized_text(cleaned):
        adjustment -= 12
    if is_aggregate_document_list(cleaned, title):
        adjustment -= 30
    if "ticket" in norm_query and "ticket" not in normalized:
        adjustment -= 8
    if "ky thuat" in norm_query and not any(term in normalized for term in ["ky thuat", "thiet bi", "khac phuc"]):
        adjustment -= 6
    if "su co" in norm_query and not any(term in normalized for term in ["su co", "khac phuc", "loi", "hong"]):
        adjustment -= 12
    if contains_raw_markup(text):
        adjustment -= 2
    if is_low_value_retrieval_text(cleaned):
        adjustment -= 4
    if "quy trinh" in normalized_text(query) and is_procedure_like(title, category):
        adjustment += 4
    return adjustment


def is_procedure_like(title: object = "", category: object = "") -> bool:
    normalized = normalized_text(f"{title} {category}")
    return "procedure" in normalized or "quy trinh" in normalized or "quy dinh" in normalized or "huong dan" in normalized


def is_aggregate_document_list(text: object = "", title: object = "") -> bool:
    normalized_title = normalized_text(str(title or ""))
    if "kiem soat tai lieu" in normalized_title:
        return False
    normalized = normalized_text(f"{title} {text}")
    aggregate_terms = (
        "tong hop danh sach",
        "danh muc cac tai lieu",
        "danh sach quy trinh",
        "loai tai lieu",
        "tinh trang",
        "ghi chu bieu mau",
    )
    return any(term in normalized for term in aggregate_terms)
