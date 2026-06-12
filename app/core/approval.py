from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.models import utc_now


@dataclass
class ApprovalDecision:
    approved: bool
    gate_id: str
    reason: str


class ApprovalStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    gate_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    run_id TEXT NOT NULL,
                    node TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    PRIMARY KEY (run_id, node)
                )
                """
            )

    def checkpoint(self, run_id: str, node: str, state: dict[str, Any]) -> None:
        compact = {
            "phase": state.get("phase"),
            "repair_round": state.get("repair_round"),
            "verified": state.get("verified"),
            "issue": state.get("issue", "")[:1000],
            "repo_path": str(state.get("repo_path", "")),
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints (run_id, node, created_at, state)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, node, utc_now(), json.dumps(compact, ensure_ascii=False, default=str)),
            )

    def create_gate(self, gate_id: str, risk: str, payload: dict[str, Any]) -> ApprovalDecision:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT status, reason FROM approvals WHERE gate_id = ?", (gate_id,)).fetchone()
            if row:
                return ApprovalDecision(row[0] == "approved", gate_id, row[1])
            conn.execute(
                """
                INSERT INTO approvals (gate_id, created_at, updated_at, status, risk, payload, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gate_id,
                    utc_now(),
                    utc_now(),
                    "pending",
                    risk,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    "approval required before mutating worktree or GitHub state",
                ),
            )
        return ApprovalDecision(False, gate_id, "pending approval")

    def decide(self, gate_id: str, approved: bool, reason: str = "") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, updated_at = ?, reason = ?
                WHERE gate_id = ?
                """,
                ("approved" if approved else "rejected", utc_now(), reason, gate_id),
            )

    def list_pending(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT gate_id, created_at, risk, payload, reason
                FROM approvals
                WHERE status = 'pending'
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            {
                "gate_id": row[0],
                "created_at": row[1],
                "risk": row[2],
                "payload": json.loads(row[3]),
                "reason": row[4],
            }
            for row in rows
        ]

    def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT node, created_at, state
                FROM checkpoints
                WHERE run_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "node": row[0],
            "created_at": row[1],
            "state": json.loads(row[2]),
        }

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT node, created_at, state
                FROM checkpoints
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "node": row[0],
                "created_at": row[1],
                "state": json.loads(row[2]),
            }
            for row in rows
        ]
