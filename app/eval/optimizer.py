from __future__ import annotations

from app.core.models import ResearchTask


class OptimizerAgent:
    name = "optimizer"

    def run(self, task: ResearchTask) -> ResearchTask:
        task.add_trace(self.name, "start")
        suggestions = []
        scores = task.evaluation.get("scores", {})
        if scores.get("grounding", 0) < 0.75:
            suggestions.append("扩展知识库或启用外部检索，提升证据覆盖率。")
        if scores.get("observability", 0) < 0.85:
            suggestions.append("补充工具调用、耗时、异常和模型输出的链路日志。")
        if task.critique.get("risks"):
            suggestions.append("将 Critic Agent 的风险项转化为下一轮检索或重写任务。")
        if not suggestions:
            suggestions.append("当前版本通过基础质量门禁，可进入更多业务场景回归测试。")
        task.optimization = {
            "badcase_type": self._badcase_type(task),
            "suggestions": suggestions,
            "next_iteration": [
                "构建 50-100 条黄金评测集",
                "引入虚拟用户生成多轮测试样本",
                "记录线上 badcase 并每周回归",
            ],
        }
        task.add_trace(self.name, "finish", suggestions=len(suggestions))
        return task

    def _badcase_type(self, task: ResearchTask) -> str:
        if not task.evidence:
            return "retrieval_failure"
        if task.critique.get("risks"):
            return "quality_gate_warning"
        if not task.evaluation.get("passed", False):
            return "evaluation_regression"
        return "none"

