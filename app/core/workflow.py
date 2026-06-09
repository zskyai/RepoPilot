from __future__ import annotations

from pathlib import Path

from app.agents.analyst import AnalystAgent
from app.agents.critic import CriticAgent
from app.agents.planner import PlannerAgent
from app.agents.reporter import ReporterAgent
from app.agents.retriever import RetrieverAgent
from app.core.llm import LLMClient, build_llm
from app.core.models import ResearchTask, TaskStatus
from app.eval.judge import JudgeAgent
from app.eval.optimizer import OptimizerAgent
from app.rag.index import LocalKnowledgeBase


class EnterpriseAgentWorkflow:
    """Production-shaped multi-agent workflow.

    The code intentionally keeps orchestration explicit so interviewers can see
    planning, retrieval, analysis, critique, reporting, judging, and iteration.
    """

    def __init__(self, kb_dir: str | Path, llm: LLMClient | None = None) -> None:
        self.llm = llm or build_llm()
        self.knowledge_base = LocalKnowledgeBase(kb_dir)
        self.agents = [
            PlannerAgent(self.llm),
            RetrieverAgent(self.llm, self.knowledge_base),
            AnalystAgent(self.llm),
            CriticAgent(self.llm),
            ReporterAgent(self.llm),
            JudgeAgent(),
            OptimizerAgent(),
        ]

    def run(self, query: str, user_type: str = "enterprise_user") -> ResearchTask:
        task = ResearchTask(query=query, user_type=user_type)
        task.mark(TaskStatus.RUNNING)
        task.add_trace("workflow", "start", agent_count=len(self.agents))
        try:
            for agent in self.agents:
                task = agent.run(task)
            task.mark(TaskStatus.SUCCEEDED)
            task.add_trace("workflow", "finish", status=task.status.value)
            return task
        except Exception as exc:
            task.mark(TaskStatus.FAILED)
            task.add_trace("workflow", "error", error=repr(exc))
            raise

