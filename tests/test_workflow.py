from pathlib import Path

from app.core.workflow import EnterpriseAgentWorkflow


def test_workflow_returns_report_and_evaluation():
    root = Path(__file__).resolve().parents[1]
    workflow = EnterpriseAgentWorkflow(root / "data" / "knowledge_base")
    task = workflow.run("如何设计一个面向大厂面试的 AI Agent 自动评测平台？")

    assert task.status.value == "succeeded"
    assert "Agent 研究报告" in task.report
    assert task.evaluation["overall"] > 0
    assert len(task.trace) >= 8

