from __future__ import annotations

import hashlib
import math
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.rag.index import tokenize


@dataclass
class VectorSearchHit:
    key: str
    score: float
    payload: dict[str, Any]


class VectorStore(Protocol):
    backend: str

    def upsert(self, items: list[dict[str, Any]], vectors: list[list[float]], sparse_texts: list[str] | None = None) -> None:
        ...

    def search(self, vector: list[float], top_k: int, sparse_text: str = "") -> list[VectorSearchHit]:
        ...


class QdrantHybridVectorStore:
    """Local Qdrant-backed dense+sparse hybrid vector index for repository chunks."""

    backend = "qdrant_local_dense_sparse_rrf"
    sparse_dims = 1_000_003

    def __init__(self, repo_path: str | Path, collection_name: str, vector_size: int) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, SparseVectorParams, VectorParams

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
            vectors_config={"dense": VectorParams(size=vector_size, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )

    def upsert(self, items: list[dict[str, Any]], vectors: list[list[float]], sparse_texts: list[str] | None = None) -> None:
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=index + 1,
                vector={
                    "dense": vector,
                    "sparse": sparse_vector(sparse_texts[index] if sparse_texts else item_text(item)),
                },
                payload={**item, "vector_key": item.get("key", str(index + 1))},
            )
            for index, (item, vector) in enumerate(zip(items, vectors))
        ]
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points, wait=True)

    def search(self, vector: list[float], top_k: int, sparse_text: str = "") -> list[VectorSearchHit]:
        from qdrant_client.models import Fusion, FusionQuery, Prefetch

        response = self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                Prefetch(query=vector, using="dense", limit=max(top_k * 4, 20)),
                Prefetch(query=sparse_vector(sparse_text), using="sparse", limit=max(top_k * 4, 20)),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
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
    backend = "in_memory_dense_sparse_rrf"

    def __init__(self, fallback_reason: str = "") -> None:
        self.items: list[dict[str, Any]] = []
        self.vectors: list[list[float]] = []
        self.fallback_reason = fallback_reason

    def upsert(self, items: list[dict[str, Any]], vectors: list[list[float]], sparse_texts: list[str] | None = None) -> None:
        self.items = items
        self.vectors = vectors
        self.sparse_texts = sparse_texts or [item_text(item) for item in items]

    def search(self, vector: list[float], top_k: int, sparse_text: str = "") -> list[VectorSearchHit]:
        from app.core.retrieval import cosine_similarity

        query_terms = Counter(tokenize(sparse_text))
        scored = [
            VectorSearchHit(
                key=item.get("key", str(index)),
                score=0.7 * cosine_similarity(vector, candidate)
                + 0.3 * sparse_overlap(query_terms, Counter(tokenize(self.sparse_texts[index]))),
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


def item_text(item: dict[str, Any]) -> str:
    return "\n".join(
        [
            str(item.get("path", "")),
            " ".join(item.get("symbols", []) or []),
            " ".join(item.get("calls", []) or []),
            str(item.get("language", "")),
        ]
    )


def sparse_vector(text: str) -> Any:
    from qdrant_client.models import SparseVector

    counts = Counter(tokenize(text))
    if not counts:
        return SparseVector(indices=[0], values=[0.0])
    weighted: dict[int, float] = {}
    for token, count in counts.items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % QdrantHybridVectorStore.sparse_dims
        weighted[index] = weighted.get(index, 0.0) + 1.0 + math.log(count)
    norm = math.sqrt(sum(value * value for value in weighted.values())) or 1.0
    ordered = sorted(weighted.items())
    return SparseVector(
        indices=[index for index, _value in ordered],
        values=[value / norm for _index, value in ordered],
    )


def sparse_overlap(query_terms: Counter[str], doc_terms: Counter[str]) -> float:
    if not query_terms or not doc_terms:
        return 0.0
    overlap = sum(min(query_terms[token], doc_terms.get(token, 0)) for token in query_terms)
    return overlap / max(1, sum(query_terms.values()))
