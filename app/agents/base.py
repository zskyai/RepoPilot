from __future__ import annotations

from app.core.llm import LLMClient
from app.core.models import ResearchTask


class BaseAgent:
    name = "base"

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, task: ResearchTask) -> ResearchTask:
        raise NotImplementedError

