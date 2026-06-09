from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.models import ResearchTask


class PlannerAgent(BaseAgent):
    name = "planner"

    def run(self, task: ResearchTask) -> ResearchTask:
        task.add_trace(self.name, "start", query=task.query)
        task.plan = [
            "识别用户目标、业务约束和成功标准",
            "检索企业知识库、技术文档和历史案例",
            "抽取证据并按可信度排序",
            "分析可落地方案、风险和工程成本",
            "生成面向决策的报告",
            "使用 Judge Agent 自动评测输出质量",
            "根据 badcase 给出迭代建议",
        ]
        task.add_trace(self.name, "finish", steps=len(task.plan))
        return task

