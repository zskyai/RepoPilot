from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from app.core.models import Evidence


TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    return [item.lower() for item in TOKEN_RE.findall(text)]


class LocalKnowledgeBase:
    """Small BM25-style retriever for offline enterprise RAG demos."""

    def __init__(self, kb_dir: str | Path) -> None:
        self.kb_dir = Path(kb_dir)
        self.documents: list[dict[str, str]] = []
        self.doc_terms: list[Counter[str]] = []
        self.doc_freq: Counter[str] = Counter()
        self.avg_len = 1.0
        self._load()

    def _load(self) -> None:
        self.documents.clear()
        for path in sorted(self.kb_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                self.documents.append(json.loads(line))
        self.doc_terms = [Counter(tokenize(doc["content"])) for doc in self.documents]
        self.doc_freq = Counter()
        for terms in self.doc_terms:
            self.doc_freq.update(terms.keys())
        total_len = sum(sum(terms.values()) for terms in self.doc_terms)
        self.avg_len = total_len / max(1, len(self.doc_terms))

    def search(self, query: str, top_k: int = 5) -> list[Evidence]:
        query_terms = tokenize(query)
        scored: list[tuple[float, dict[str, str]]] = []
        for doc, terms in zip(self.documents, self.doc_terms):
            score = self._bm25(query_terms, terms)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            Evidence(
                source=doc.get("source", "local_kb"),
                title=doc.get("title", "Untitled"),
                content=doc["content"],
                score=round(score, 4),
                metadata={"doc_id": doc.get("id", "")},
            )
            for score, doc in scored[:top_k]
        ]

    def _bm25(self, query_terms: list[str], terms: Counter[str]) -> float:
        k1 = 1.5
        b = 0.75
        doc_len = sum(terms.values())
        total_docs = max(1, len(self.documents))
        score = 0.0
        for term in query_terms:
            tf = terms.get(term, 0)
            if tf == 0:
                continue
            df = self.doc_freq.get(term, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1 - b + b * doc_len / self.avg_len)
            score += idf * tf * (k1 + 1) / denom
        return score

