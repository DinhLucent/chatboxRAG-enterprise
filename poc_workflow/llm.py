from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import error, request

from .rag_index import SearchHit


class LLMError(RuntimeError):
    pass


@dataclass
class OpenAICompatibleConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleConfig | None":
        api_key = os.getenv("POC_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("POC_LLM_MODEL")
        base_url = os.getenv("POC_LLM_BASE_URL", "https://api.openai.com/v1")
        if not api_key or not model:
            return None
        return cls(api_key=api_key, model=model, base_url=base_url)


class OpenAICompatibleClient:
    def __init__(self, config: OpenAICompatibleConfig):
        self.config = config

    def answer(self, query: str, hits: list[SearchHit]) -> str:
        context = "\n\n".join(
            f"[{hit.doc_id} v{hit.version} {hit.chunk_id}]\n{hit.text}"
            for hit in hits
        )
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ban la chatbot noi bo tra loi cau hoi ve quy trinh. "
                        "Chi tra loi dua tren CONTEXT duoc cung cap. "
                        "Khong tu suy doan neu context khong du. "
                        "Luon neu nguon theo dang doc_id + version. "
                        "Neu khong co can cu hop le, tra loi chinh xac: "
                        "Khong tim thay can cu trong tai lieu hien hanh."
                    ),
                },
                {
                    "role": "user",
                    "content": f"QUESTION:\n{query}\n\nCONTEXT:\n{context}",
                },
            ],
            "temperature": 0.1,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            raise LLMError(f"LLM HTTP {exc.code}: {raw}") from exc
        except error.URLError as exc:
            raise LLMError(f"LLM connection failed: {exc.reason}") from exc
        data = json.loads(raw)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response: {data}") from exc
        if not content:
            raise LLMError("LLM returned an empty answer")
        return str(content).strip()

