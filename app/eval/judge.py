from __future__ import annotations

from app.core.models import ResearchTask


class JudgeAgent:
    name = "judge"

    def run(self, task: ResearchTask) -> ResearchTask:
        task.add_trace(self.name, "start")
        scores = {
            "task_completion": self._score(bool(task.report), 0.95, 0.2),
            "grounding": min(1.0, len(task.evidence) / 4),
            "actionability": self._score("推荐落地架构" in task.report, 0.9, 0.3),
            "safety": self._score(task.critique.get("quality_gate_passed", False), 0.85, 0.55),
            "observability": min(1.0, len(task.trace) / 12),
        }
        overall = round(sum(scores.values()) / len(scores), 3)
        task.evaluation = {
            "scores": {key: round(value, 3) for key, value in scores.items()},
            "overall": overall,
            "passed": overall >= 0.72,
            "rubric": {
                "task_completion": "是否回答用户核心问题",
                "grounding": "是否有足够证据支撑",
                "actionability": "是否给出可落地动作",
                "safety": "是否通过风险审查",
                "observability": "是否记录完整执行轨迹",
            },
        }
        task.add_trace(self.name, "finish", overall=overall, passed=task.evaluation["passed"])
        return task

    def _score(self, condition: bool, yes: float, no: float) -> float:
        return yes if condition else no

