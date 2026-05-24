from __future__ import annotations

import json
import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib import parse
from urllib import error, request

from .database import QualityDatabase
from .manifest import ManifestStore, latest_active_records
from .models import ManifestRecord
from .utils import write_json


class RAGFlowHTTPError(RuntimeError):
    pass


@dataclass
class RAGFlowConfig:
    base_url: str
    api_key: str
    dataset_id: str | None = None
    chat_id: str | None = None
    search_id: str | None = None
    model: str = "model"

    @classmethod
    def from_env(cls) -> "RAGFlowConfig | None":
        base_url = os.getenv("RAGFLOW_BASE_URL")
        api_key = os.getenv("RAGFLOW_API_KEY")
        if not base_url or not api_key:
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            dataset_id=os.getenv("RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID"),
            chat_id=os.getenv("RAGFLOW_CHAT_ID"),
            search_id=os.getenv("RAGFLOW_SEARCH_ID"),
            model=os.getenv("RAGFLOW_CHAT_MODEL", "model"),
        )


class RAGFlowHTTPClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def upload_document(self, dataset_id: str, path: Path, display_name: str | None = None) -> dict:
        response = self._multipart_post(
            f"/api/v1/datasets/{dataset_id}/documents",
            field_name="file",
            file_path=path,
            display_name=display_name or path.name,
        )
        data = _expect_ok(response)
        if not isinstance(data, list) or not data:
            raise RAGFlowHTTPError("RAGFlow upload returned no document data")
        return data[0]

    def list_datasets(self, name: str | None = None, include_parsing_status: bool = False) -> list[dict]:
        query: dict[str, object] = {}
        if name:
            query["name"] = name
        if include_parsing_status:
            query["include_parsing_status"] = "true"
        path = "/api/v1/datasets"
        if query:
            path = f"{path}?{parse.urlencode(query)}"
        response = self._json_request("GET", path, None)
        data = _expect_ok(response)
        if isinstance(data, dict):
            return data.get("kbs") or data.get("datasets") or []
        if isinstance(data, list):
            return data
        return []

    def create_dataset(
        self,
        name: str,
        description: str = "",
        chunk_method: str = "naive",
        parser_config: dict | None = None,
    ) -> dict:
        response = self._json_request(
            "POST",
            "/api/v1/datasets",
            {
                "name": name,
                "description": description,
                "permission": "me",
                "chunk_method": chunk_method,
                "parser_config": parser_config or {"chunk_token_num": 512, "delimiter": "\n\n"},
            },
        )
        data = _expect_ok(response)
        if not isinstance(data, dict):
            raise RAGFlowHTTPError(f"RAGFlow create dataset returned unexpected data: {data}")
        return data

    def create_chat_assistant(
        self,
        name: str,
        dataset_ids: list[str],
        llm_id: str | None = None,
    ) -> dict:
        payload: dict[str, object] = {
            "name": name,
            "dataset_ids": dataset_ids,
            "prompt_config": {
                "quote": True,
                "empty_response": "Khong tim thay can cu trong tai lieu hien hanh.",
                "system": (
                    "Chi tra loi dua tren noi dung trong {knowledge}. "
                    "Neu khong co can cu trong tai lieu hien hanh, hay noi dung cau tra loi mac dinh."
                ),
                "parameters": [{"key": "knowledge", "optional": False}],
            },
            "similarity_threshold": 0.2,
            "vector_similarity_weight": 0.3,
            "top_n": 6,
        }
        if llm_id:
            payload["llm_id"] = llm_id
        response = self._json_request("POST", "/api/v1/chats", payload)
        data = _expect_ok(response)
        if not isinstance(data, dict):
            raise RAGFlowHTTPError(f"RAGFlow create chat returned unexpected data: {data}")
        return data

    def list_chat_assistants(self, name: str | None = None) -> list[dict]:
        query: dict[str, object] = {}
        if name:
            query["name"] = name
        path = "/api/v1/chats"
        if query:
            path = f"{path}?{parse.urlencode(query)}"
        response = self._json_request("GET", path, None)
        data = _expect_ok(response)
        if isinstance(data, dict):
            return data.get("chats") or []
        if isinstance(data, list):
            return data
        return []

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> dict:
        return self._json_request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            {"document_ids": document_ids},
        )

    def delete_all_documents(self, dataset_id: str) -> dict:
        return self._json_request(
            "DELETE",
            f"/api/v1/datasets/{dataset_id}/documents",
            {"ids": None, "delete_all": True},
        )

    def update_document_metadata(self, dataset_id: str, document_id: str, metadata: dict) -> dict:
        return self._json_request(
            "PUT",
            f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
            {"meta_fields": metadata},
        )

    def chat_completion(self, chat_id: str, question: str, model: str = "model") -> dict:
        return self._json_request(
            "POST",
            f"/api/v1/openai/{chat_id}/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": question}],
                "stream": False,
                "extra_body": {
                    "reference": True,
                    "reference_metadata": {"include": True},
                    "metadata_condition": {
                        "logic": "and",
                        "conditions": [
                            {"name": "status", "comparison_operator": "is", "value": "active"}
                        ],
                    },
                },
            },
        )

    def search_completion(
        self,
        search_id: str,
        question: str,
        kb_ids: list[str] | None = None,
    ) -> dict:
        payload: dict[str, object] = {"question": question}
        if kb_ids:
            payload["kb_ids"] = kb_ids
        return self._sse_json_request("POST", f"/api/v1/searches/{search_id}/completions", payload)

    def health(self) -> dict:
        return self._json_request("GET", "/api/v1/system/healthz", None)

    def _json_request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = None if method == "GET" else json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        return self._send(req)

    def _sse_json_request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                raw = response.read().decode("utf-8", errors="ignore")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            raise RAGFlowHTTPError(f"RAGFlow HTTP {exc.code}: {raw}") from exc
        except error.URLError as exc:
            raise RAGFlowHTTPError(f"RAGFlow connection failed: {exc.reason}") from exc

        last_payload: dict | None = None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            item = line.removeprefix("data:").strip()
            if not item or item == "[DONE]":
                continue
            try:
                parsed = json.loads(item)
            except json.JSONDecodeError:
                continue
            if parsed.get("data") is True:
                continue
            last_payload = parsed
        if last_payload is None:
            raise RAGFlowHTTPError(f"RAGFlow SSE returned no JSON payload: {raw[:300]}")
        return last_payload

    def _multipart_post(self, path: str, field_name: str, file_path: Path, display_name: str) -> dict:
        boundary = f"----kb-poc-{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
        file_bytes = file_path.read_bytes()
        body = b"".join(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{display_name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                file_bytes,
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        req = request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        return self._send(req)

    def _send(self, req: request.Request) -> dict:
        try:
            with request.urlopen(req, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            raise RAGFlowHTTPError(f"RAGFlow HTTP {exc.code}: {raw}") from exc
        except error.URLError as exc:
            raise RAGFlowHTTPError(f"RAGFlow connection failed: {exc.reason}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RAGFlowHTTPError(f"RAGFlow returned non-JSON response: {raw[:300]}") from exc


def sync_active_to_ragflow(
    root: Path,
    base_url: str,
    api_key: str,
    dataset_id: str,
    delete_all: bool = False,
    parse_after_upload: bool = True,
) -> dict:
    client = RAGFlowHTTPClient(base_url, api_key)
    db = QualityDatabase(root)
    store = ManifestStore(root)
    active_records = latest_active_records(store.load())
    uploaded: list[dict] = []

    if delete_all:
        client.delete_all_documents(dataset_id)

    for record in active_records:
        document = upload_record(client, dataset_id, record)
        document_id = document.get("id")
        if document_id:
            client.update_document_metadata(dataset_id, document_id, record_to_ragflow_metadata(record))
        uploaded.append({"doc_id": record.doc_id, "version": record.version, "ragflow_document": document})
        db.log_ingestion("ragflow_uploaded", record.doc_id, record.version)

    document_ids = [item["ragflow_document"]["id"] for item in uploaded if item["ragflow_document"].get("id")]
    parse_response = None
    if parse_after_upload and document_ids:
        parse_response = client.parse_documents(dataset_id, document_ids)
        _expect_ok(parse_response)
        for item in uploaded:
            db.log_ingestion("ragflow_parse_requested", item["doc_id"], item["version"])

    summary = {
        "dataset_id": dataset_id,
        "uploaded_count": len(uploaded),
        "uploaded": uploaded,
        "parse_requested": bool(parse_response),
    }
    write_json(root / "manifest" / "ragflow_sync.json", summary)
    return summary


def bootstrap_ragflow_resources(
    base_url: str,
    api_key: str,
    dataset_name: str = "technical_active",
    chat_name: str = "technical_procedure_chat",
    llm_id: str | None = None,
    create_chat: bool = True,
) -> dict[str, object]:
    client = RAGFlowHTTPClient(base_url, api_key)
    dataset = find_dataset_by_name(client, dataset_name)
    dataset_created = False
    if not dataset:
        dataset = client.create_dataset(
            dataset_name,
            description="Active approved technical procedure knowledge generated from governed manifest.",
        )
        dataset_created = True

    chat = None
    chat_created = False
    if create_chat:
        chat = find_chat_by_name(client, chat_name)
        if not chat:
            chat = client.create_chat_assistant(chat_name, [str(dataset["id"])], llm_id=llm_id)
            chat_created = True

    return {
        "dataset": dataset,
        "dataset_created": dataset_created,
        "chat": chat,
        "chat_created": chat_created,
        "env": {
            "RAGFLOW_BASE_URL": base_url,
            "RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID": dataset.get("id"),
            "RAGFLOW_CHAT_ID": chat.get("id") if isinstance(chat, dict) else None,
        },
    }


def find_dataset_by_name(client: RAGFlowHTTPClient, dataset_name: str) -> dict | None:
    datasets = client.list_datasets(name=dataset_name, include_parsing_status=True)
    for dataset in datasets:
        if str(dataset.get("name", "")).lower() == dataset_name.lower():
            return dataset
    return datasets[0] if datasets else None


def find_chat_by_name(client: RAGFlowHTTPClient, chat_name: str) -> dict | None:
    chats = client.list_chat_assistants(name=chat_name)
    for chat in chats:
        if str(chat.get("name", "")).lower() == chat_name.lower():
            return chat
    return chats[0] if chats else None


def upload_record(client: RAGFlowHTTPClient, dataset_id: str, record: ManifestRecord) -> dict:
    normalized = Path(record.normalized_path)
    if not normalized.exists():
        raise RAGFlowHTTPError(f"Normalized file does not exist: {normalized}")
    display_name = f"{record.doc_id}_v{record.version}_{record.category}.md"
    return client.upload_document(dataset_id, normalized, display_name=display_name)


def record_to_ragflow_metadata(record: ManifestRecord) -> dict[str, str]:
    return {
        "doc_id": record.doc_id,
        "title": record.title,
        "department": record.department,
        "category": record.category,
        "source_type": record.source_type,
        "language": record.language,
        "version": record.version,
        "status": record.status,
        "effective_from": record.effective_from,
        "effective_to": record.effective_to or "",
        "review_at": record.review_at or "",
        "owner": record.owner,
        "approved_by": record.approved_by or "",
        "source_path": record.source_path,
        "normalized_path": record.normalized_path,
        "content_hash": record.content_hash,
        "access_group": record.access_group,
        "supersedes": record.supersedes or "",
    }


def answer_with_ragflow(question: str, config: RAGFlowConfig) -> dict[str, object]:
    client = RAGFlowHTTPClient(config.base_url, config.api_key)
    if config.chat_id:
        response = client.chat_completion(config.chat_id, question, model=config.model)
        answer = response.get("choices", [{}])[0].get("message", {}).get("content") or ""
        reference = response.get("choices", [{}])[0].get("message", {}).get("reference") or {}
        citations = extract_reference_citations(reference)
        return {
            "answer": answer,
            "citations": citations,
            "raw_reference": reference,
            "ragflow_mode": "chat",
        }
    if config.search_id:
        response = client.search_completion(
            config.search_id,
            question,
            kb_ids=[config.dataset_id] if config.dataset_id else None,
        )
        data = response.get("data") or {}
        return {
            "answer": data.get("answer") or "",
            "citations": extract_reference_citations(data.get("reference") or {}),
            "raw_reference": data.get("reference") or {},
            "ragflow_mode": "search",
        }
    raise RAGFlowHTTPError("RAGFLOW_CHAT_ID or RAGFLOW_SEARCH_ID is required for RAGFlow answers")


def extract_reference_citations(reference: object) -> list[dict[str, object]]:
    if isinstance(reference, list):
        chunks = reference
    elif isinstance(reference, dict):
        chunks = reference.get("chunks") or {}
    else:
        chunks = {}
    citations: list[dict[str, object]] = []
    if isinstance(chunks, dict):
        iterable = chunks.values()
    elif isinstance(chunks, list):
        iterable = chunks
    else:
        iterable = []
    for chunk in iterable:
        if not isinstance(chunk, dict):
            continue
        metadata = chunk.get("document_metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        citations.append(
            {
                "doc_id": metadata.get("doc_id") or chunk.get("document_id"),
                "version": metadata.get("version"),
                "title": chunk.get("document_name"),
                "category": metadata.get("category"),
                "chunk_id": chunk.get("id") or chunk.get("chunk_id"),
                "source_path": metadata.get("source_path") or chunk.get("url"),
                "normalized_path": metadata.get("normalized_path"),
                "score": chunk.get("similarity"),
            }
        )
    return citations


def _expect_ok(response: dict):
    if response.get("code") != 0:
        raise RAGFlowHTTPError(response.get("message") or f"RAGFlow API failed: {response}")
    return response.get("data")
