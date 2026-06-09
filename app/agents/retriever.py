from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.models import ResearchTask
from app.rag.index import LocalKnowledgeBase


class RetrieverAgent(BaseAgent):
    name = "retriever"

    def __init__(self, llm, knowledge_base: LocalKnowledgeBase) -> None:
        super().__init__(llm)
        self.knowledge_base = knowledge_base

    def run(self, task: ResearchTask) -> ResearchTask:
        task.add_trace(self.name, "start", top_k=5)
        evidence = self.knowledge_base.search(task.query, top_k=5)
        task.evidence = evidence
        task.add_trace(
            self.name,
            "finish",
            evidence_count=len(evidence),
            titles=[item.title for item in evidence],
        )
        return task

