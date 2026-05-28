"""Small OpenAI-compatible embedding server for local RAGFlow development.

This server intentionally implements only the endpoint RAGFlow needs:
POST /v1/embeddings. It uses a locally cached HuggingFace transformer model
and returns normalized mean-pooled embeddings.
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer


DEFAULT_MODEL_PATH = (
    Path.home()
    / ".cache"
    / "huggingface"
    / "hub"
    / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    / "snapshots"
    / "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
)
DEFAULT_MODEL_NAME = "local-multilingual-minilm"


class Embedder:
    def __init__(self, model_path: Path):
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
        self.model = AutoModel.from_pretrained(str(model_path), local_files_only=True)
        self.model.eval()
        self.dimension = int(self.model.config.hidden_size)

    @torch.inference_mode()
    def encode(self, texts: list[str]) -> list[list[float]]:
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        output = self.model(**encoded)
        token_embeddings = output.last_hidden_state
        attention_mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
        summed = torch.sum(token_embeddings * attention_mask, dim=1)
        counts = torch.clamp(attention_mask.sum(dim=1), min=1e-9)
        embeddings = F.normalize(summed / counts, p=2, dim=1)
        return embeddings.cpu().tolist()


class EmbeddingHandler(BaseHTTPRequestHandler):
    server_version = "LocalOpenAIEmbedding/0.1"
    embedder: Embedder
    model_name: str

    def do_GET(self) -> None:
        if self.path in {"/", "/health", "/v1/health"}:
            self._send_json({"status": "ok", "model": self.model_name, "dimension": self.embedder.dimension})
            return
        if self.path == "/v1/models":
            self._send_json({"object": "list", "data": [{"id": self.model_name, "object": "model"}]})
            return
        self._send_json({"error": {"message": "not found"}}, status=404)

    def do_POST(self) -> None:
        if self.path != "/v1/embeddings":
            self._send_json({"error": {"message": "not found"}}, status=404)
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            raw_input = payload.get("input", [])
            if isinstance(raw_input, str):
                texts = [raw_input]
            else:
                texts = ["" if item is None else str(item) for item in raw_input]
            if not texts:
                texts = [""]
            embeddings = self.embedder.encode(texts)
            data = [
                {"object": "embedding", "index": idx, "embedding": embedding}
                for idx, embedding in enumerate(embeddings)
            ]
            self._send_json(
                {
                    "object": "list",
                    "model": payload.get("model") or self.model_name,
                    "data": data,
                    "usage": {
                        "prompt_tokens": sum(max(1, len(text.split())) for text in texts),
                        "total_tokens": sum(max(1, len(text.split())) for text in texts),
                    },
                }
            )
        except Exception as exc:
            self._send_json({"error": {"message": str(exc)}}, status=500)

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("LOCAL_EMBEDDING_SERVER_QUIET", "1") != "1":
            super().log_message(fmt, *args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=19002)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    args = parser.parse_args()

    if not args.model_path.exists():
        raise SystemExit(f"Model path not found: {args.model_path}")

    EmbeddingHandler.embedder = Embedder(args.model_path)
    EmbeddingHandler.model_name = args.model_name
    server = ThreadingHTTPServer((args.host, args.port), EmbeddingHandler)
    print(
        json.dumps(
            {
                "status": "ready",
                "host": args.host,
                "port": args.port,
                "model": args.model_name,
                "dimension": EmbeddingHandler.embedder.dimension,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
