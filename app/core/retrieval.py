from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.llm import load_dotenv
from app.rag.index import tokenize


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class HashEmbeddingClient:
    def __init__(self, dims: int = 256) -> None:
        self.dims = dims
        self.provider = "local_hash_embedding"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[slot] += sign
        norm = math.sqrt(sum(item * item for item in vector))
        if norm == 0.0:
            return vector
        return [item / norm for item in vector]


class OpenAICompatibleEmbeddingClient:
    def __init__(self) -> None:
        load_dotenv()
        self.base_url = (
            os.getenv("EMBEDDING_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or os.getenv("QWEN_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or ""
        ).rstrip("/")
        self.api_key = (
            os.getenv("EMBEDDING_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        self.model = (
            os.getenv("EMBEDDING_MODEL")
            or os.getenv("QWEN_EMBEDDING_MODEL")
            or os.getenv("OPENAI_EMBEDDING_MODEL")
            or ""
        )
        self.provider = "openai_compatible_embedding"

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.configured:
            raise RuntimeError("Embedding client is not configured.")
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data") or []
        return [list(item.get("embedding") or []) for item in data]


def build_embedding_client() -> Any:
    remote = OpenAICompatibleEmbeddingClient()
    if remote.configured:
        return remote
    return HashEmbeddingClient()


@dataclass
class RetrievalScore:
    lexical: float
    semantic: float
    structural: float
    total: float
    provider: str
