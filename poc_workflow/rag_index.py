from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ACTIVE_DATASET, ARCHIVE_DATASET
from .models import ManifestRecord
from .text_cleaning import (
    CONTENT_HEADING_TERMS,
    LOW_VALUE_TERMS,
    clean_retrieval_text,
    contains_raw_markup,
    is_aggregate_document_list,
    is_low_value_retrieval_text,
    is_procedure_like,
    normalized_text,
)
from .utils import tokenize


@dataclass
class SearchHit:
    doc_id: str
    version: str
    title: str
    category: str
    chunk_id: str
    text: str
    score: int
    source_path: str
    normalized_path: str
    display_code: str | None = None
    display_version: str | None = None
    source_role: str | None = None
    source_revision: str | None = None
    anchor_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass
class IndexEntry:
    doc_id: str
    version: str
    title: str
    department: str
    category: str
    status: str
    chunk_id: str
    text: str
    source_path: str
    normalized_path: str
    title_terms: set[str]
    text_terms: set[str]
    normalized_target: str
    content_hits: int
    base_quality_adjustment: int
    display_code: str | None = None
    display_version: str | None = None
    source_role: str | None = None
    source_revision: str | None = None
    active_scope_id: str | None = None
    anchor_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None


INDEX_CACHE: dict[Path, tuple[float, int, list[IndexEntry]]] = {}

QUERY_STOPWORDS = {
    "ai",
    "ban",
    "bang",
    "bo",
    "buoc",
    "cac",
    "cach",
    "can",
    "cho",
    "co",
    "cua",
    "duoc",
    "den",
    "de",
    "di",
    "gi",
    "ghi",
    "gom",
    "hay",
    "hoi",
    "khong",
    "khi",
    "la",
    "lam",
    "ma",
    "mot",
    "nao",
    "neu",
    "nguon",
    "nhan",
    "nhung",
    "noi",
    "o",
    "phan",
    "phong",
    "quy",
    "sau",
    "tai",
    "the",
    "theo",
    "thi",
    "trinh",
    "trong",
    "tu",
    "ve",
    "va",
}


class LocalRagIndex:
    def __init__(self, root: Path):
        self.root = root
        self.index_dir = root / "ragflow_index"

    def rebuild(self, active_records: list[ManifestRecord], archive_records: list[ManifestRecord]) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._write_dataset(ACTIVE_DATASET, active_records)
        self._write_dataset(ARCHIVE_DATASET, archive_records)

    def _write_dataset(self, dataset: str, records: list[ManifestRecord]) -> None:
        path = self.index_dir / f"{dataset}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                normalized = Path(record.normalized_path)
                if not normalized.exists():
                    continue
                text = normalized.read_text(encoding="utf-8", errors="ignore")
                raw_chunks = chunk_markdown_with_metadata(text)
                valid_index = 0
                for c_idx, raw_chunk in enumerate(raw_chunks):
                    chunk_text = raw_chunk["text"]
                    cleaned = clean_retrieval_text(chunk_text)
                    if not cleaned or is_low_value_retrieval_text(cleaned):
                        continue
                    valid_index += 1
                    chunk_id = f"{record.doc_id}_v{record.version}_c{valid_index}"
                    payload = {
                        "dataset": dataset,
                        "doc_id": record.doc_id,
                        "version": record.version,
                        "title": record.title,
                        "department": record.department,
                        "category": record.category,
                        "status": record.status,
                        "language": record.language,
                        "access_group": record.access_group,
                        "chunk_id": chunk_id,
                        "anchor_id": stable_anchor_id(record.doc_id, record.version, valid_index),
                        "line_start": raw_chunk["line_start"],
                        "line_end": raw_chunk["line_end"],
                        "text": cleaned,
                        "source_path": record.source_path,
                        "normalized_path": record.normalized_path,
                        "display_code": record.extra.get("display_code"),
                        "display_version": record.extra.get("display_version"),
                        "source_role": record.extra.get("source_role"),
                        "source_revision": record.extra.get("source_revision"),
                        "canonical_business_code": record.extra.get("canonical_business_code"),
                        "citation_map_path": record.extra.get("citation_map_path"),
                        "active_scope_id": record.extra.get("active_scope_id"),
                    }
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def search(
        self,
        query: str,
        dataset: str = ACTIVE_DATASET,
        department: str = "technical",
        category: str | None = None,
        limit: int = 3,
    ) -> list[SearchHit]:
        path = self.index_dir / f"{dataset}.jsonl"
        if not path.exists():
            return []
        query_terms = meaningful_terms(query)
        normalized_query = normalized_text(query)
        hits: list[SearchHit] = []
        for entry in self._load_entries(path):
            if entry.department != department:
                continue
            if entry.status != "active":
                continue
            if category and not category_matches(entry, category):
                continue
            if "su co" in normalized_query and not any(
                term in entry.normalized_target for term in ["su co", "khac phuc", "loi", "hong"]
            ):
                continue
            if not query_terms and entry.doc_id.lower() not in query.lower():
                continue
            text_overlap = entry.text_terms & query_terms
            title_overlap = entry.title_terms & query_terms
            score = len(text_overlap) + (len(title_overlap) * 4)
            if entry.doc_id.lower() in query.lower():
                score += 12
            if entry.display_code and normalized_text(entry.display_code) in normalized_query:
                score += 16
            if entry.doc_id == "KT-QT-215" and "kiem soat" in normalized_query:
                score += 10
            score += incident_workflow_boost(entry, normalized_query)
            if score <= 0:
                continue
            score += phrase_score_normalized(normalized_query, entry.normalized_target)
            normalized_title = normalized_text(entry.title)
            if "su co" in normalized_query and "ky thuat" in normalized_query:
                if any(term in normalized_title for term in ["khac phuc su co", "su co su dung thiet bi"]):
                    score += 20
                if not any(term in normalized_title for term in ["su co", "khac phuc", "thiet bi", "ky thuat"]):
                    score -= 20
            score += quality_adjustment(entry, normalized_query)
            score += source_role_adjustment(entry, normalized_query)
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    doc_id=entry.doc_id,
                    version=entry.version,
                    title=entry.title,
                    category=entry.category,
                    chunk_id=entry.chunk_id,
                    text=entry.text,
                    score=score,
                    source_path=entry.source_path,
                    normalized_path=entry.normalized_path,
                    display_code=entry.display_code,
                    display_version=entry.display_version,
                    source_role=entry.source_role,
                    source_revision=entry.source_revision,
                    anchor_id=entry.anchor_id,
                    line_start=entry.line_start,
                    line_end=entry.line_end,
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    def _load_entries(self, path: Path) -> list[IndexEntry]:
        stat = path.stat()
        cache_key = path.resolve()
        cached = INDEX_CACHE.get(cache_key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
        entries: list[IndexEntry] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                text = clean_retrieval_text(payload.get("text") or "")
                if not text or is_low_value_retrieval_text(text):
                    continue
                title = str(payload.get("title") or "")
                doc_id = str(payload.get("doc_id") or "")
                display_code = payload.get("display_code")
                display_version = payload.get("display_version")
                source_role = payload.get("source_role")
                source_revision = payload.get("source_revision")
                active_scope_id = payload.get("active_scope_id")
                title_terms = meaningful_terms(f"{title} {doc_id} {display_code or ''}")
                text_terms = meaningful_terms(text)
                normalized_target = normalized_text(
                    f"{title} {display_code or ''} {text} {payload.get('category') or ''}"
                )
                content_hits = sum(1 for term in CONTENT_HEADING_TERMS if term in normalized_target)
                low_hits = sum(1 for term in LOW_VALUE_TERMS if term in normalized_text(text))
                base_quality_adjustment = -low_hits
                if is_aggregate_document_list(text, title):
                    base_quality_adjustment -= 30
                if contains_raw_markup(text):
                    base_quality_adjustment -= 2
                if "lich su chinh sua" in normalized_text(text) or "so chinh sua" in normalized_text(text):
                    base_quality_adjustment -= 30
                entries.append(
                    IndexEntry(
                        doc_id=doc_id,
                        version=str(payload.get("version") or ""),
                        title=title,
                        department=str(payload.get("department") or ""),
                        category=str(payload.get("category") or ""),
                        status=str(payload.get("status") or ""),
                        chunk_id=str(payload.get("chunk_id") or ""),
                        text=text,
                        source_path=str(payload.get("source_path") or ""),
                        normalized_path=str(payload.get("normalized_path") or ""),
                        title_terms=title_terms,
                        text_terms=text_terms,
                        normalized_target=normalized_target,
                        content_hits=content_hits,
                        base_quality_adjustment=base_quality_adjustment,
                        display_code=str(display_code) if display_code else None,
                        display_version=str(display_version) if display_version else None,
                        source_role=str(source_role) if source_role else None,
                        source_revision=str(source_revision) if source_revision else None,
                        active_scope_id=str(active_scope_id) if active_scope_id else None,
                        anchor_id=payload.get("anchor_id"),
                        line_start=payload.get("line_start"),
                        line_end=payload.get("line_end"),
                    )
                )
        INDEX_CACHE[cache_key] = (stat.st_mtime, stat.st_size, entries)
        return entries


def chunk_markdown_with_metadata(text: str, max_chars: int = 1200) -> list[dict[str, Any]]:
    raw_lines = text.splitlines()
    blocks_raw = []
    current_block = []

    for idx, line in enumerate(raw_lines):
        line_num = idx + 1
        if line.strip():
            current_block.append((line, line_num))
        else:
            if current_block:
                blocks_raw.append(current_block)
                current_block = []
    if current_block:
        blocks_raw.append(current_block)

    chunks = []
    current_chunk_blocks = []

    def add_chunk(block_list):
        if not block_list:
            return
        chunk_text = "\n\n".join(
            "\n".join(line_content for line_content, _ in b)
            for b in block_list
        )
        all_nums = [num for b in block_list for _, num in b]
        if all_nums:
            chunks.append({
                "text": chunk_text,
                "line_start": min(all_nums),
                "line_end": max(all_nums)
            })

    def find_line_range_for_part(block, part_text):
        part_lines = [l.strip() for l in part_text.splitlines() if l.strip()]
        if not part_lines:
            return block[0][1], block[-1][1]
        matched_line_nums = []
        block_idx = 0
        for p_line in part_lines:
            while block_idx < len(block):
                b_line, b_num = block[block_idx]
                if p_line in b_line or b_line.strip() in p_line:
                    matched_line_nums.append(b_num)
                    block_idx += 1
                    break
                block_idx += 1
        if matched_line_nums:
            return min(matched_line_nums), max(matched_line_nums)
        return block[0][1], block[-1][1]

    for block in blocks_raw:
        block_text = "\n".join(l for l, _ in block)
        if len(block_text) > max_chars:
            if current_chunk_blocks:
                add_chunk(current_chunk_blocks)
                current_chunk_blocks = []
            split_parts = split_long_block(block_text, max_chars=max_chars)
            for part in split_parts:
                start_l, end_l = find_line_range_for_part(block, part)
                chunks.append({
                    "text": part,
                    "line_start": start_l,
                    "line_end": end_l
                })
            continue

        simulated_blocks = current_chunk_blocks + [block]
        simulated_text = "\n\n".join("\n".join(l for l, _ in b) for b in simulated_blocks)

        if len(simulated_text) > max_chars:
            add_chunk(current_chunk_blocks)
            current_chunk_blocks = [block]
        else:
            current_chunk_blocks.append(block)

    if current_chunk_blocks:
        add_chunk(current_chunk_blocks)

    if not chunks and text.strip():
        chunks.append({
            "text": text.strip(),
            "line_start": 1,
            "line_end": len(raw_lines) or 1
        })

    return chunks


def stable_anchor_id(doc_id: str, version: str, chunk_number: int) -> str:
    doc_part = re.sub(r"[^A-Za-z0-9]+", "-", doc_id).strip("-") or "doc"
    version_part = re.sub(r"[^A-Za-z0-9]+", "-", version).strip("-") or "v"
    return f"{doc_part}-v{version_part}-c{chunk_number}"


def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_long_block(block, max_chars=max_chars))
            continue
        if current and len(current) + len(block) + 2 > max_chars:
            chunks.append(current.strip())
            current = block
        else:
            current = f"{current}\n\n{block}".strip()
    if current:
        chunks.append(current.strip())
    return chunks or [text.strip()]


def split_long_block(block: str, max_chars: int = 1200) -> list[str]:
    if re.search(r"</\s*tr\s*>", block, flags=re.IGNORECASE):
        parts = re.split(r"(?i)(</\s*tr\s*>)", block)
        rows = []
        for index in range(0, len(parts), 2):
            row = parts[index]
            if index + 1 < len(parts):
                row += parts[index + 1]
            row = row.strip()
            if row:
                rows.append(row)
        return pack_chunk_parts(rows, max_chars=max_chars)

    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) > 1:
        return pack_chunk_parts(lines, max_chars=max_chars)
    return [block[index : index + max_chars].strip() for index in range(0, len(block), max_chars) if block[index : index + max_chars].strip()]


def pack_chunk_parts(parts: list[str], max_chars: int = 1200) -> list[str]:
    chunks: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) + 1 > max_chars:
            chunks.append(current.strip())
            current = part
        elif len(part) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(
                part[index : index + max_chars].strip()
                for index in range(0, len(part), max_chars)
                if part[index : index + max_chars].strip()
            )
        else:
            current = f"{current}\n{part}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def category_matches(payload: object, category: str) -> bool:
    if isinstance(payload, IndexEntry):
        payload_category = payload.category
        title = payload.title
    else:
        payload_category = str(payload.get("category") or "")  # type: ignore[union-attr]
        title = payload.get("title")  # type: ignore[union-attr]
    if payload_category == category:
        return True
    if category == "procedure" and is_procedure_like(title, payload_category):
        return True
    if category == "faq_troubleshooting" and is_procedure_like(title, payload_category):
        return True
    return False


def meaningful_terms(value: object) -> set[str]:
    terms = tokenize(normalized_text(value))
    return {term for term in terms if len(term) > 1 and term not in QUERY_STOPWORDS}


def quality_adjustment(entry: IndexEntry, normalized_query: str) -> int:
    adjustment = entry.base_quality_adjustment
    is_query_procedure = any(
        term in normalized_query for term in ["quy trinh", "quy dinh", "huong dan", "chinh sach", "sop", "policy"]
    )
    if entry.content_hits >= 2 and is_query_procedure:
        adjustment += entry.content_hits * 2
    if "ticket" in normalized_query and "ticket" not in entry.normalized_target:
        adjustment -= 8
    if "ky thuat" in normalized_query and not any(
        term in entry.normalized_target for term in ["ky thuat", "thiet bi", "khac phuc"]
    ):
        adjustment -= 6
    if "su co" in normalized_query and not any(
        term in entry.normalized_target for term in ["su co", "khac phuc", "loi", "hong"]
    ):
        adjustment -= 12
    if "quy trinh" in normalized_query and is_procedure_like(entry.title, entry.category):
        adjustment += 4
    adjustment += procedure_topic_adjustment(entry, normalized_query)
    adjustment += query_intent_adjustment(entry, normalized_query)
    if is_query_procedure and any(term in entry.normalized_target for term in ["noi dung cong viec", "noi dung chi tiet"]):
        adjustment += 18
        if re.search(r"(^|\n|\s)1\s*\|", entry.normalized_target):
            adjustment += 35
    if is_query_procedure and any(
        term in entry.normalized_target for term in ["ma bieu mau", "thong tin khach hang", "dai dien khach hang"]
    ):
        adjustment -= 20
    return adjustment


def query_intent_adjustment(entry: IndexEntry, normalized_query: str) -> int:
    target = entry.normalized_target
    adjustment = 0
    intent_rules = [
        (["muc dich"], ["muc dich", "dam bao", "nham"], 70),
        (["ap dung", "khi nao"], ["pham vi ap dung", "ap dung khi", "phat sinh"], 70),
        (["trach nhiem", "chiu trach nhiem"], ["trach nhiem", "bo phan lien quan"], 65),
        (["khao sat", "dieu kien lap dat"], ["khao sat dieu kien", "ban dat may", "nhiet do", "he thong dien"], 65),
        (["khong du dieu kien", "chua dat"], ["khong du dieu kien", "tu van khach hang", "co so vat chat"], 70),
        (["cap nhat thong tin", "phan mem"], ["cap nhat thong tin", "ten bv", "serial", "sn may", "thoi gian di chuyen"], 70),
        (["ky bbdvkt", "ky nhan bbdvkt"], ["ky nhan bbdvkt", "ky gop", "so phieu giao viec"], 70),
        (["bbdvkt"], ["bbdvkt", "bien ban dich vu ky thuat", "ky nhan bbdvkt", "ky gop"], 55),
        (["ho so", "bieu mau", "dinh kem"], ["ho so", "tai lieu dinh kem", "bieu mau", "bm-"], 60),
        (["ke hoach bao duong"], ["ke hoach bao duong", "danh sach may dat", "hop dong"], 65),
        (["lich bao duong"], ["lich bao duong", "truoc ngay 30", "cskh"], 65),
        (["xuat vat tu", "linh kien", "phu kien"], ["xuat phu kien", "vat tu", "linh kien", "phu kien"], 55),
        (["du tru phu kien", "danh sach yeu cau"], ["du tru phu kien", "yeu cau du tru", "danh sach yeu cau", "bm-125"], 65),
        (["thoi gian dap ung"], ["thoi gian dap ung", "phieu giao viec"], 65),
        (["dien thoai"], ["dien thoai", "ho tro", "huong dan"], 55),
        (["serial", "so serial"], ["serial", "so serial", "chung chi", "nhan hieu chuan"], 65),
        (["muon ccdc"], ["muon", "ccdc", "ngay tra du kien", "trang thai thiet bi"], 65),
        (["ccdc"], ["ccdc", "hieu chuan", "dung cu"], 40),
        (["sap het han", "het han"], ["het han", "nho hon 6 thang", "nho hon 06 thang"], 65),
        (["chung chi dao tao", "ccdt"], ["chung chi dao tao", "ccdt", "bm-075"], 55),
    ]
    for query_terms, target_terms, weight in intent_rules:
        if not any(term in normalized_query for term in query_terms):
            continue
        if any(term in target for term in target_terms):
            adjustment += weight
        else:
            adjustment -= min(25, weight // 2)

    history_terms = ["lich su chinh sua", "sua doi", "thay doi ten", "la trung thien", "ngay ban hanh"]
    if any(term in target for term in history_terms) and not any(term in normalized_query for term in ["sua doi", "phien ban", "ban hanh"]):
        adjustment -= 55
    form_terms = ["thong tin khach hang", "ten thiet bi", "ngay gio gui yeu cau", "y kien cua khach hang"]
    if any(term in target for term in form_terms) and not any(term in normalized_query for term in ["bieu mau", "mau", "form"]):
        adjustment -= 35
    header_terms = ["stt", "raci", "responsible", "accountable", "consulted", "informed"]
    if sum(1 for term in header_terms if term in target) >= 3:
        adjustment -= 35
    return adjustment


def procedure_topic_adjustment(entry: IndexEntry, normalized_query: str) -> int:
    normalized_title = normalized_text(f"{entry.title} {entry.display_code or ''}")
    topics = [
        ("lap dat", ["lap dat"]),
        ("bao duong", ["bao duong", "bao tri"]),
        (
            "sua chua",
            [
                "sua chua",
                "chan doan",
                "ho tro khach hang qua dien thoai",
                "ho tro qua dien thoai",
                "khong huong dan duoc",
                "thoi gian dap ung",
                "phat sinh them phu kien",
                "quay lai",
                "lien he lai khach hang",
            ],
        ),
        ("dat hang phu kien", ["dat hang phu kien", "du tru phu kien", "phu kien du tru", "yeu cau du tru", "ycmh"]),
        ("hieu chuan", ["hieu chuan", "ccdc", "serial", "so serial", "muon ccdc"]),
        ("chung chi dao tao", ["chung chi", "dao tao", "ccdt"]),
    ]
    matched_topics = [
        (canonical, hints)
        for canonical, hints in topics
        if any(hint in normalized_query for hint in hints)
    ]
    if not matched_topics:
        return 0
    for canonical, hints in matched_topics:
        if canonical in normalized_title or any(hint in normalized_title for hint in hints):
            return 55
    return -55


def source_role_adjustment(entry: IndexEntry, normalized_query: str) -> int:
    if not entry.source_role:
        return 0
    asks_workbook = any(
        term in normalized_query
        for term in [
            "excel",
            "xlsx",
            "workbook",
            "bang tinh",
            "bang bieu",
            "bieu mau",
            "checklist",
            "file mau",
            "mau bieu",
        ]
    )
    asks_broad_procedure_steps = any(
        term in normalized_query
        for term in [
            "cac buoc",
            "gom cac buoc",
            "gom nhung buoc",
            "buoc nao",
            "tung buoc",
            "nhu the nao",
            "lam sao",
            "workflow",
            "so do",
        ]
    )
    if entry.source_role == "primary_pdf" and asks_broad_procedure_steps and not asks_workbook:
        return 18
    if entry.source_role == "supporting_workbook" and asks_workbook:
        return 14
    if entry.source_role == "supporting_workbook" and asks_broad_procedure_steps:
        return -18
    return 0


def incident_workflow_boost(entry: IndexEntry, normalized_query: str) -> int:
    if entry.doc_id != "KT-QT-003":
        return 0
    if "kt-qt-003" in normalized_query or "kt qt 003" in normalized_query:
        return 100
    incident_terms = [
        "su co",
        "ticket",
        "tiep nhan",
        "phan loai",
        "muc do anh huong",
        "nguoi dung",
        "he thong giam sat",
        "thoi gian",
        "nguoi bao loi",
        "uu tien",
        "chuyen cap",
        "dong ticket",
        "cap nhat",
    ]
    hits = sum(1 for term in incident_terms if term in normalized_query)
    if "thoi gian" in normalized_query and (
        "bao loi" in normalized_query or ("ghi nhan" in normalized_query and "thong tin" in normalized_query)
    ):
        return 55
    if "muc do uu tien" in normalized_query and (
        "phan loai" in normalized_query or "bo phan" in normalized_query or "quy dinh" in normalized_query
    ):
        return 55
    if "su co" in normalized_query and ("ky thuat" in normalized_query or hits >= 2):
        return 55
    if "ticket" in normalized_query and hits >= 2:
        return 45
    return 0


def phrase_score(*, query: str, text: str, title: object = "") -> int:
    normalized_query = normalized_text(query)
    normalized_target = normalized_text(f"{title} {text}")
    return phrase_score_normalized(normalized_query, normalized_target)


def phrase_score_normalized(normalized_query: str, normalized_target: str) -> int:
    score = 0
    if "xu ly su co" in normalized_query and "xu ly su co" in normalized_target:
        score += 10
    if "su co" in normalized_query and "su co" in normalized_target:
        score += 4
    if "ky thuat" in normalized_query and "ky thuat" in normalized_target:
        score += 8
    if "ticket" in normalized_query and "ticket" in normalized_target:
        score += 10
    if "tiep nhan" in normalized_query and "tiep nhan" in normalized_target:
        score += 4
    if "phan loai" in normalized_query and "phan loai" in normalized_target:
        score += 4
    if "khac phuc su co" in normalized_query and "khac phuc su co" in normalized_target:
        score += 8
    if "quy trinh" in normalized_query and "quy trinh" in normalized_target:
        score += 2
    return score
