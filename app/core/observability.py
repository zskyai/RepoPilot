from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.core.models import utc_now


class RepoPilotTraceStore:
    """SQLite trace store plus OpenTelemetry spans for agent workflow events."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()
        try:
            from opentelemetry import trace

            self.tracer = trace.get_tracer("repopilot")
            self.otel_enabled = True
        except Exception:
            self.tracer = None
            self.otel_enabled = False

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    node TEXT NOT NULL,
                    event TEXT NOT NULL,
                    detail TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def span(self, run_id: str, node: str, event: str, **detail: Any) -> Iterator[None]:
        self.record(run_id, node, f"{event}.start", detail)
        if self.tracer:
            with self.tracer.start_as_current_span(f"repopilot.{node}.{event}") as span:
                for key, value in detail.items():
                    span.set_attribute(f"repopilot.{key}", self._safe_attr(value))
                try:
                    yield
                finally:
                    self.record(run_id, node, f"{event}.finish", detail)
        else:
            try:
                yield
            finally:
                self.record(run_id, node, f"{event}.finish", detail)

    def record(self, run_id: str, node: str, event: str, detail: dict[str, Any] | None = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO trace_events (run_id, created_at, node, event, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_now(),
                    node,
                    event,
                    json.dumps(detail or {}, ensure_ascii=False, default=str),
                ),
            )

    def read_run(self, run_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT created_at, node, event, detail
                FROM trace_events
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "created_at": row[0],
                "node": row[1],
                "event": row[2],
                "detail": json.loads(row[3]),
            }
            for row in rows
        ]

    def _safe_attr(self, value: Any) -> str | int | float | bool:
        if isinstance(value, (str, int, float, bool)):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)[:1000]
