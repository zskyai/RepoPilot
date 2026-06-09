from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class Evidence:
    source: str
    title: str
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceEvent:
    agent: str
    event: str
    detail: dict[str, Any]
    timestamp: str = field(default_factory=utc_now)


@dataclass
class ResearchTask:
    query: str
    user_type: str = "enterprise_user"
    task_id: str = field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = TaskStatus.CREATED
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    plan: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    critique: dict[str, Any] = field(default_factory=dict)
    report: str = ""
    evaluation: dict[str, Any] = field(default_factory=dict)
    optimization: dict[str, Any] = field(default_factory=dict)
    trace: list[TraceEvent] = field(default_factory=list)

    def mark(self, status: TaskStatus) -> None:
        self.status = status
        self.updated_at = utc_now()

    def add_trace(self, agent: str, event: str, **detail: Any) -> None:
        self.trace.append(TraceEvent(agent=agent, event=event, detail=detail))
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "user_type": self.user_type,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan": self.plan,
            "evidence": [item.__dict__ for item in self.evidence],
            "analysis": self.analysis,
            "critique": self.critique,
            "report": self.report,
            "evaluation": self.evaluation,
            "optimization": self.optimization,
            "trace": [item.__dict__ for item in self.trace],
        }

