from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.models import ResearchTask


class ReporterAgent(BaseAgent):
    name = "reporter"

    def run(self, task: ResearchTask) -> ResearchTask:
        task.add_trace(self.name, "start")
        evidence_lines = [
            f"- [{idx}] {item.title}（score={item.score}）：{item.content[:150]}"
            for idx, item in enumerate(task.evidence, start=1)
        ]
        risks = task.critique.get("risks") or ["暂未发现阻断性风险。"]
        report = f"""# Agent 研究报告

## 用户问题
{task.query}

## 任务规划
{chr(10).join(f"{idx}. {step}" for idx, step in enumerate(task.plan, start=1))}

## 核心结论
{chr(10).join(f"- {item}" for item in task.analysis.get("key_findings", []))}

## 推荐落地架构
{chr(10).join(f"- {item}" for item in task.analysis.get("recommended_architecture", []))}

## 风险与审查
{chr(10).join(f"- {item}" for item in risks)}

## 证据来源
{chr(10).join(evidence_lines)}
"""
        task.report = report.strip()
        task.add_trace(self.name, "finish", report_chars=len(task.report))
        return task

