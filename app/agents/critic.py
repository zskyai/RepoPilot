from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.models import ResearchTask


class CriticAgent(BaseAgent):
    name = "critic"

    def run(self, task: ResearchTask) -> ResearchTask:
        task.add_trace(self.name, "start")
        risks = []
        if len(task.evidence) < 2:
            risks.append("证据来源不足，报告可信度偏低。")
        if not task.analysis.get("recommended_architecture"):
            risks.append("缺少可执行架构建议。")
        if "评测" not in task.query and "evaluation" not in task.query.lower():
            risks.append("建议补充自动化评测指标，证明系统可持续优化。")
        task.critique = {
            "risks": risks,
            "quality_gate_passed": len(risks) <= 1,
            "required_checks": [
                "事实是否可追溯",
                "方案是否可服务化",
                "是否包含评测指标",
                "是否能沉淀 badcase",
            ],
        }
        task.add_trace(self.name, "finish", risk_count=len(risks))
        return task

