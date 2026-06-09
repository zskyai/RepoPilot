from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class VectorSearchHit:
    key: str
    score: float
    payload: dict[str, Any]


class VectorStore(Protocol):
    backend: str

    def upsert(self, items: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        ...

    def search(self, vector: list[float], top_k: int) -> list[VectorSearchHit]:
        ...


class QdrantHybridVectorStore:
    """Local Qdrant-backed vector index for repository chunks."""

    backend = "qdrant_local_dense"

    def __init__(self, repo_path: str | Path, collection_name: str, vector_size: int) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self.repo_path = Path(repo_path).resolve()
        configured_path = os.getenv("REPOPILOT_QDRANT_PATH", "").strip()
        self.collection_name = collection_name
        base_path = Path(configured_path) if configured_path else self.repo_path / ".repopilot" / "qdrant"
        if not base_path.is_absolute():
            base_path = self.repo_path / base_path
        self.path = base_path / collection_name
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(self.path))
        if self.client.collection_exists(collection_name=self.collection_name):
            self.client.delete_collection(collection_name=self.collection_name)
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def upsert(self, items: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=index + 1,
                vector=vector,
                payload={**item, "vector_key": item.get("key", str(index + 1))},
            )
            for index, (item, vector) in enumerate(zip(items, vectors))
        ]
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points, wait=True)

    def search(self, vector: list[float], top_k: int) -> list[VectorSearchHit]:
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=top_k,
            with_payload=True,
        )
        points = getattr(response, "points", response)
        return [
            VectorSearchHit(
                key=(point.payload or {}).get("vector_key", str(point.id)),
                score=float(point.score),
                payload=point.payload or {},
            )
            for point in points
        ]

    def close(self) -> None:
        self.client.close()


class InMemoryVectorStore:
    backend = "in_memory_dense"

    def __init__(self, fallback_reason: str = "") -> None:
        self.items: list[dict[str, Any]] = []
        self.vectors: list[list[float]] = []
        self.fallback_reason = fallback_reason

    def upsert(self, items: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        self.items = items
        self.vectors = vectors

    def search(self, vector: list[float], top_k: int) -> list[VectorSearchHit]:
        from app.core.retrieval import cosine_similarity

        scored = [
            VectorSearchHit(
                key=item.get("key", str(index)),
                score=cosine_similarity(vector, candidate),
                payload=item,
            )
            for index, (item, candidate) in enumerate(zip(self.items, self.vectors))
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]


def repo_collection_name(repo_path: str | Path, chunk_count: int) -> str:
    digest = hashlib.sha256(f"{Path(repo_path).resolve()}:{chunk_count}".encode("utf-8")).hexdigest()[:16]
    return f"repopilot_{digest}"


def build_vector_store(repo_path: str | Path, vector_size: int, chunk_count: int) -> VectorStore:
    try:
        return QdrantHybridVectorStore(
            repo_path=repo_path,
            collection_name=repo_collection_name(repo_path, chunk_count),
            vector_size=vector_size,
        )
    except Exception as exc:
        return InMemoryVectorStore(fallback_reason=repr(exc))
