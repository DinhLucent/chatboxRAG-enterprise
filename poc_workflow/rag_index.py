from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import ACTIVE_DATASET, ARCHIVE_DATASET
from .models import ManifestRecord
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
                for index, chunk in enumerate(chunk_markdown(text)):
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
                        "chunk_id": f"{record.doc_id}_v{record.version}_c{index + 1}",
                        "text": chunk,
                        "source_path": record.source_path,
                        "normalized_path": record.normalized_path,
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
        query_terms = set(tokenize(query))
        hits: list[SearchHit] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if payload.get("department") != department:
                    continue
                if payload.get("status") != "active":
                    continue
                if category and payload.get("category") != category:
                    continue
                text_terms = tokenize(payload["text"] + " " + payload["title"] + " " + payload["doc_id"])
                score = sum(1 for term in text_terms if term in query_terms)
                if payload["doc_id"].lower() in query.lower():
                    score += 5
                if score <= 0:
                    continue
                hits.append(
                    SearchHit(
                        doc_id=payload["doc_id"],
                        version=payload["version"],
                        title=payload["title"],
                        category=payload["category"],
                        chunk_id=payload["chunk_id"],
                        text=payload["text"],
                        score=score,
                        source_path=payload["source_path"],
                        normalized_path=payload["normalized_path"],
                    )
                )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + len(block) + 2 > max_chars:
            chunks.append(current.strip())
            current = block
        else:
            current = f"{current}\n\n{block}".strip()
    if current:
        chunks.append(current.strip())
    return chunks or [text.strip()]

