from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.models import utc_now
from app.core.retrieval import build_embedding_client, cosine_similarity, resilient_embed_texts


class MemoryStore:
    def __init__(self, db_path: str | Path = ".repopilot/memory.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_client = build_embedding_client()
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    issue TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def save_from_payload(self, payload: dict[str, Any]) -> int:
        issue = payload.get("issue") or payload.get("query") or ""
        summary = self._summary(payload)
        text = self._memory_text(payload, summary)
        vectors, provider = resilient_embed_texts(self.embedding_client, [text])
        outcome = "passed" if payload.get("evaluation", {}).get("passed") else "failed"
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO memories
                    (created_at, repo_path, issue, summary, outcome, embedding_provider, embedding, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    payload.get("repo_path", ""),
                    issue,
                    summary,
                    outcome,
                    provider,
                    json.dumps(vectors[0]),
                    json.dumps(self._compact_payload(payload), ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def search(self, issue: str, repo_path: str = "", top_k: int = 3) -> list[dict[str, Any]]:
        vectors, provider = resilient_embed_texts(self.embedding_client, [issue])
        query_vector = vectors[0]
        rows = []
        with sqlite3.connect(self.db_path) as conn:
            for row in conn.execute(
                """
                SELECT id, created_at, repo_path, issue, summary, outcome, embedding_provider, embedding, payload
                FROM memories
                ORDER BY id DESC
                LIMIT 300
                """
            ):
                rows.append(row)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            memory_vector = json.loads(row[7])
            score = cosine_similarity(query_vector, memory_vector)
            if repo_path and row[2] and Path(repo_path).resolve().as_posix() == Path(row[2]).resolve().as_posix():
                score += 0.05
            score += self._recency_bonus(row[1])
            if row[5] == "passed":
                score += 0.03
            payload = json.loads(row[8])
            score += self._repair_learning_bonus(payload)
            scored.append(
                (
                    score,
                    {
                        "id": row[0],
                        "created_at": row[1],
                        "repo_path": row[2],
                        "issue": row[3],
                        "summary": row[4],
                        "outcome": row[5],
                        "embedding_provider": row[6],
                        "query_provider": provider,
                        "score": round(score, 4),
                        "payload": payload,
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for score, item in scored[:top_k] if score > 0.05]

    def _recency_bonus(self, created_at: str) -> float:
        try:
            stamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            return 0.0
        age_days = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds() / 86400.0)
        if age_days <= 3:
            return 0.03
        if age_days <= 14:
            return 0.015
        return 0.0

    def _repair_learning_bonus(self, payload: dict[str, Any]) -> float:
        journal = payload.get("repair_journal", []) or []
        if not journal:
            return 0.0
        passed_rounds = sum(1 for item in journal if item.get("passed"))
        focused_rounds = sum(1 for item in journal if len(item.get("target_files", []) or []) <= 2)
        return min(0.05, passed_rounds * 0.01 + focused_rounds * 0.005)

    def _memory_text(self, payload: dict[str, Any], summary: str) -> str:
        analysis = payload.get("analysis", {})
        return "\n".join(
            [
                payload.get("issue", ""),
                summary,
                str(analysis.get("root_cause_hypothesis", "")),
                "\n".join(analysis.get("suspected_files", []) or []),
                "\n".join(analysis.get("change_plan", []) or []),
                json.dumps(payload.get("evaluation", {}), ensure_ascii=False),
            ]
        )

    def _summary(self, payload: dict[str, Any]) -> str:
        analysis = payload.get("analysis", {})
        patch_titles = [
            item.get("title", "")
            for item in analysis.get("patch_suggestions", [])[:3]
            if isinstance(item, dict)
        ]
        ci_feedback = ((payload.get("pr_plan") or {}).get("github") or {}).get("ci_feedback") or {}
        return " | ".join(
            item
            for item in [
                f"overall={payload.get('evaluation', {}).get('overall')}",
                f"passed={payload.get('evaluation', {}).get('passed')}",
                f"root={analysis.get('root_cause_hypothesis', '')[:160]}",
                f"patches={'; '.join(patch_titles)}",
                f"ci={ci_feedback.get('repair_context', '')[:160]}",
            ]
            if item
        )

    def _compact_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        analysis = payload.get("analysis", {})
        return {
            "task_id": payload.get("task_id"),
            "repo_path": payload.get("repo_path"),
            "issue": payload.get("issue"),
            "evaluation": payload.get("evaluation", {}),
            "root_cause_hypothesis": analysis.get("root_cause_hypothesis"),
            "suspected_files": analysis.get("suspected_files", []),
            "change_plan": analysis.get("change_plan", []),
            "patch_suggestions": analysis.get("patch_suggestions", [])[:3],
            "patch_checks": analysis.get("patch_checks", [])[:5],
            "repair_journal": analysis.get("repair_journal", [])[:8],
            "github": (payload.get("pr_plan") or {}).get("github", {}),
        }
