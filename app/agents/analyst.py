from __future__ import annotations

from collections import Counter

from app.agents.base import BaseAgent
from app.core.models import ResearchTask
from app.rag.index import tokenize


class AnalystAgent(BaseAgent):
    name = "analyst"

    def run(self, task: ResearchTask) -> ResearchTask:
        task.add_trace(self.name, "start", evidence_count=len(task.evidence))
        joined = "\n".join(item.content for item in task.evidence)
        keywords = [word for word, _ in Counter(tokenize(joined)).most_common(12)]
        task.analysis = {
            "key_findings": self._findings(task),
            "keywords": keywords,
            "evidence_coverage": len(task.evidence),
            "recommended_architecture": [
                "LangGraph 状态图编排",
                "RAG 检索增强",
                "LLM-as-a-Judge 自动评测",
                "Badcase 数据闭环",
                "FastAPI 服务化与异步任务",
            ],
        }
        task.add_trace(self.name, "finish", keywords=keywords[:6])
        return task

    def _findings(self, task: ResearchTask) -> list[str]:
        if not task.evidence:
            return ["未检索到足够证据，需要扩展知识库或改写查询。"]
        findings = []
        for item in task.evidence[:3]:
            findings.append(f"{item.title}: {item.content[:120]}")
        return findings

