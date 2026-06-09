from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

try:
    from langgraph.graph import END, START, StateGraph as LangGraphStateGraph
except Exception:  # pragma: no cover
    END = "__end__"
    START = "__start__"
    LangGraphStateGraph = None

from app.core.observability import RepoPilotTraceStore
from app.core.state_graph import StateGraph as LocalStateGraph
from app.scenarios.repo_pilot import RepoDiagnosisResult, RepoPilotWorkflow


class GraphState(TypedDict, total=False):
    payload: dict[str, Any]


class RepoPilotGraphWorkflow:
    """StateGraph architecture for Coding Agent workflows.

    Pattern: Plan -> Act -> Verify -> Repair loop -> Judge -> PR.
    The production path uses LangGraph when installed and records each node into
    SQLite plus OpenTelemetry spans for durable, inspectable execution evidence.
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
        ci_feedback: bool = False,
        use_memory: bool = True,
        save_memory: bool = True,
        pr_number: int | None = None,
        comment_body: str = "",
    ) -> RepoDiagnosisResult:
        repo = Path(repo_path).resolve()
        configured_trace_db = os.getenv("REPOPILOT_TRACE_DB", "").strip()
        trace_db_path = Path(configured_trace_db) if configured_trace_db else repo / ".repopilot" / "traces.sqlite3"
        if not trace_db_path.is_absolute():
            trace_db_path = repo / trace_db_path
        state = {
            "payload": {
                "repo_path": repo,
                "issue": issue,
                "run_tests": run_tests,
                "apply_sandbox": apply_sandbox,
                "apply_worktree": apply_worktree,
                "create_pr": create_pr,
                "poll_ci": poll_ci,
                "ci_feedback": ci_feedback,
                "use_memory": use_memory,
                "save_memory": save_memory,
                "pr_number": pr_number,
                "comment_body": comment_body,
                "repair_round": 0,
                "graph_trace": [],
                "graph_run_id": str(uuid4()),
                "trace_db_path": str(trace_db_path),
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
        result.task.analysis["graph_run_id"] = payload.get("graph_run_id")
        result.task.analysis["trace_db_path"] = payload.get("trace_db_path")
        result.task.analysis["persistent_trace"] = self._trace_store(payload).read_run(payload.get("graph_run_id", ""))
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
        with self._trace_store(payload).span(payload["graph_run_id"], "plan", "execute"):
            payload["phase"] = "plan"
            payload["graph_trace"].append({"node": "plan"})
        return {"payload": payload}

    def _act(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "act", "execute"):
            payload["graph_trace"].append({"node": "act"})
            payload["result"] = self.base.run(
                payload["repo_path"],
                payload["issue"],
                run_tests=payload["run_tests"],
                apply_sandbox=payload.get("apply_sandbox", False),
                apply_worktree=payload.get("apply_worktree", False),
                create_pr=payload.get("create_pr", False),
                poll_ci=payload.get("poll_ci", False),
                ci_feedback=payload.get("ci_feedback", False),
                use_memory=payload.get("use_memory", True),
                save_memory=payload.get("save_memory", True),
                pr_number=payload.get("pr_number"),
                comment_body=payload.get("comment_body", ""),
            )
        return {"payload": payload}

    def _verify(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "verify", "execute"):
            payload["graph_trace"].append({"node": "verify"})
            result: RepoDiagnosisResult = payload["result"]
            evaluation = result.task.evaluation
            scores = evaluation.get("scores", {})
            tests_ok = scores.get("executed_tests", 0) >= 1.0 if payload.get("run_tests") else True
            payload["verified"] = (
                scores.get("patch_apply_check", 0) >= 1.0
                and tests_ok
                and evaluation.get("passed", False)
            )
        return {"payload": payload}

    def _repair(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "repair", "execute"):
            payload["graph_trace"].append({"node": "repair"})
            payload["repair_round"] = int(payload.get("repair_round", 0)) + 1
            payload["issue"] = (
                payload["issue"]
                + "\nPrevious validation failed. Generate a smaller patch using patch-check, test, and judge feedback."
            )
        return {"payload": payload}

    def _judge(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "judge", "execute"):
            payload["graph_trace"].append({"node": "judge"})
        return {"payload": payload}

    def _pr_ready(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "pr_ready", "execute"):
            payload["graph_trace"].append({"node": "pr_ready"})
        return {"payload": payload}

    def _route_after_verify(self, state: dict[str, Any]) -> str | None:
        payload = state["payload"]
        if payload.get("verified"):
            return "judge"
        if int(payload.get("repair_round", 0)) < self.max_repair_rounds:
            return "repair"
        return "judge"

    def _trace_store(self, payload: dict[str, Any]) -> RepoPilotTraceStore:
        return RepoPilotTraceStore(payload["trace_db_path"])
