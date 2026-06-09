from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.core.models import utc_now


class RunStore:
    def __init__(self, db_path: str | Path = ".repopilot/runs.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    issue TEXT NOT NULL,
                    overall REAL,
                    passed INTEGER,
                    payload TEXT NOT NULL
                )
                """
            )

    def save(self, payload: dict[str, Any]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (created_at, scenario, repo_path, issue, overall, passed, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    payload.get("scenario", "unknown"),
                    payload.get("repo_path", ""),
                    payload.get("issue", ""),
                    payload.get("evaluation", {}).get("overall"),
                    int(bool(payload.get("evaluation", {}).get("passed"))),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

