from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

try:
    from langgraph.graph import END, START, StateGraph as LangGraphStateGraph
except Exception:  # pragma: no cover
    END = "__end__"
    START = "__start__"
    LangGraphStateGraph = None

from app.core.state_graph import StateGraph as LocalStateGraph
from app.scenarios.repo_pilot import RepoDiagnosisResult, RepoPilotWorkflow


class GraphState(TypedDict, total=False):
    payload: dict[str, Any]


class RepoPilotGraphWorkflow:
    """StateGraph architecture for Coding Agent workflows.

    Pattern: Plan -> Retrieve -> Diagnose -> Patch -> Verify -> Repair loop -> Judge -> PR.
    This wraps the mature RepoPilot v0.3 capabilities while exposing a modern
    graph architecture suitable for migration to LangGraph.
    """

    def __init__(
        self,
        use_llm: bool = False,
        require_llm: bool = False,
        max_repair_rounds: int = 2,
    ) -> None:
        self.base = RepoPilotWorkflow(use_llm=use_llm, require_llm=require_llm)
        self.max_repair_rounds = max_repair_rounds
        self.graph = self._build_graph()

    def run(
        self,
        repo_path: str | Path,
        issue: str,
        run_tests: bool = False,
        apply_sandbox: bool = False,
        apply_worktree: bool = False,
        create_pr: bool = False,
        poll_ci: bool = False,
        pr_number: int | None = None,
        comment_body: str = "",
    ) -> RepoDiagnosisResult:
        state = {
            "payload": {
                "repo_path": Path(repo_path).resolve(),
                "issue": issue,
                "run_tests": run_tests,
                "apply_sandbox": apply_sandbox,
                "apply_worktree": apply_worktree,
                "create_pr": create_pr,
                "poll_ci": poll_ci,
                "pr_number": pr_number,
                "comment_body": comment_body,
                "repair_round": 0,
                "graph_trace": [],
            }
        }
        final = self.graph.invoke(state) if hasattr(self.graph, "invoke") else self.graph.run(state)
        payload = final["payload"]
        result: RepoDiagnosisResult = payload["result"]
        result.task.analysis["graph_architecture"] = (
            "LangGraph Plan-Act-Verify-Repair"
            if LangGraphStateGraph
            else "Plan-Act-Verify-Repair StateGraph"
        )
        result.task.analysis["graph_trace"] = payload.get("graph_trace", [])
        result.task.analysis["repair_rounds"] = payload.get("repair_round", 0)
        result.task.add_trace("state_graph", "finish", nodes=[item["node"] for item in payload.get("graph_trace", [])])
        return result

    def _build_graph(self):
        if LangGraphStateGraph:
            graph = LangGraphStateGraph(GraphState)
            graph.add_node("plan", self._plan)
            graph.add_node("act", self._act)
            graph.add_node("verify", self._verify)
            graph.add_node("repair", self._repair)
            graph.add_node("judge", self._judge)
            graph.add_node("pr_ready", self._pr_ready)
            graph.add_edge(START, "plan")
            graph.add_edge("plan", "act")
            graph.add_edge("act", "verify")
            graph.add_conditional_edges(
                "verify",
                self._route_after_verify,
                {"repair": "repair", "judge": "judge"},
            )
            graph.add_edge("repair", "act")
            graph.add_edge("judge", "pr_ready")
            graph.add_edge("pr_ready", END)
            return graph.compile()

        graph = LocalStateGraph(max_steps=16)
        graph.add_node("plan", self._plan)
        graph.add_node("act", self._act)
        graph.add_node("verify", self._verify)
        graph.add_node("repair", self._repair)
        graph.add_node("judge", self._judge)
        graph.add_node("pr_ready", self._pr_ready)
        graph.set_entrypoint("plan")
        graph.add_edge("plan", "act")
        graph.add_edge("act", "verify")
        graph.add_conditional_edges("verify", self._route_after_verify)
        graph.add_edge("repair", "act")
        graph.add_edge("judge", "pr_ready")
        return graph

    def _plan(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        payload["phase"] = "plan"
        payload["graph_trace"].append({"node": "plan"})
        return {"payload": payload}

    def _act(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        payload["graph_trace"].append({"node": "act"})
        result = self.base.run(
            payload["repo_path"],
            payload["issue"],
            run_tests=payload["run_tests"],
            apply_sandbox=payload.get("apply_sandbox", False),
            apply_worktree=payload.get("apply_worktree", False),
            create_pr=payload.get("create_pr", False),
            poll_ci=payload.get("poll_ci", False),
            pr_number=payload.get("pr_number"),
            comment_body=payload.get("comment_body", ""),
        )
        payload["result"] = result
        return {"payload": payload}

    def _verify(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        payload["graph_trace"].append({"node": "verify"})
        result: RepoDiagnosisResult = payload["result"]
        evaluation = result.task.evaluation
        scores = evaluation.get("scores", {})
        payload["verified"] = (
            scores.get("patch_apply_check", 0) >= 1.0
            and scores.get("executed_tests", 0) >= 1.0
            and evaluation.get("passed", False)
        )
        return {"payload": payload}

    def _repair(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        payload["graph_trace"].append({"node": "repair"})
        payload["repair_round"] = int(payload.get("repair_round", 0)) + 1
        issue = payload["issue"]
        payload["issue"] = (
            issue
            + "\n上一轮未通过验证，请基于 patch 校验、测试结果和 Judge 意见生成更小、更可应用的修复。"
        )
        return {"payload": payload}

    def _judge(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        payload["graph_trace"].append({"node": "judge"})
        return {"payload": payload}

    def _pr_ready(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        payload["graph_trace"].append({"node": "pr_ready"})
        return {"payload": payload}

    def _route_after_verify(self, state: dict[str, Any]) -> str | None:
        payload = state["payload"]
        if payload.get("verified"):
            return "judge"
        if int(payload.get("repair_round", 0)) < self.max_repair_rounds:
            return "repair"
        return "judge"
