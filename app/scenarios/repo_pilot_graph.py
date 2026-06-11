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

from app.core.approval import ApprovalStore
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
        enable_multi_candidate: bool = True,
        enable_graph_rerank: bool = True,
    ) -> None:
        self.base = RepoPilotWorkflow(
            use_llm=use_llm,
            require_llm=require_llm,
            enable_multi_candidate=enable_multi_candidate,
            enable_graph_rerank=enable_graph_rerank,
        )
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
        auto_repair_ci: bool = False,
        auto_sync_repair: bool = False,
        use_memory: bool = True,
        save_memory: bool = True,
        pr_number: int | None = None,
        comment_body: str = "",
        require_approval: bool = True,
        resume_run_id: str = "",
    ) -> RepoDiagnosisResult:
        repo = Path(repo_path).resolve()
        configured_trace_db = os.getenv("REPOPILOT_TRACE_DB", "").strip()
        trace_db_path = Path(configured_trace_db) if configured_trace_db else repo / ".repopilot" / "traces.sqlite3"
        if not trace_db_path.is_absolute():
            trace_db_path = repo / trace_db_path
        approval_db_path = repo / ".repopilot" / "approvals.sqlite3"
        graph_run_id = resume_run_id or str(uuid4())
        graph_thread_id = f"repopilot:{repo.name}:{graph_run_id}"
        approval_gate = self._approval_gate(
            approval_db_path=approval_db_path,
            graph_run_id=graph_run_id,
            apply_worktree=apply_worktree,
            create_pr=create_pr,
            require_approval=require_approval,
        )
        if approval_gate and not approval_gate["approved"]:
            apply_worktree = False
            create_pr = False
        state = {
            "payload": {
                "repo_path": repo,
                "issue": issue,
                "original_issue": issue,
                "run_tests": run_tests,
                "apply_sandbox": apply_sandbox,
                "apply_worktree": apply_worktree,
                "create_pr": create_pr,
                "poll_ci": poll_ci,
                "ci_feedback": ci_feedback,
                "auto_repair_ci": auto_repair_ci,
                "auto_sync_repair": auto_sync_repair,
                "use_memory": use_memory,
                "save_memory": save_memory,
                "pr_number": pr_number,
                "comment_body": comment_body,
                "repair_round": 0,
                "graph_trace": [],
                "graph_run_id": graph_run_id,
                "graph_thread_id": graph_thread_id,
                "trace_db_path": str(trace_db_path),
                "approval_db_path": str(approval_db_path),
                "approval_gate": approval_gate,
                "resume_run_id": resume_run_id,
                "repair_context": {},
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
        result.task.analysis["graph_thread_id"] = payload.get("graph_thread_id")
        result.task.analysis["trace_db_path"] = payload.get("trace_db_path")
        result.task.analysis["approval_gate"] = payload.get("approval_gate")
        result.task.analysis["resumed_from_checkpoint"] = bool(payload.get("resume_run_id"))
        result.task.analysis["checkpoint_state"] = self._approval_store(payload).latest_checkpoint(payload.get("graph_run_id", ""))
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
            self._approval_store(payload).checkpoint(payload["graph_run_id"], "plan", payload)
            payload["phase"] = "plan"
            payload["graph_trace"].append({"node": "plan"})
        return {"payload": payload}

    def _act(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "act", "execute"):
            self._approval_store(payload).checkpoint(payload["graph_run_id"], "act", payload)
            payload["graph_trace"].append({"node": "act"})
            payload["result"] = self.base.run(
                payload["repo_path"],
                payload.get("original_issue") or payload["issue"],
                run_tests=payload["run_tests"],
                apply_sandbox=payload.get("apply_sandbox", False),
                apply_worktree=payload.get("apply_worktree", False),
                create_pr=payload.get("create_pr", False),
                poll_ci=payload.get("poll_ci", False),
                ci_feedback=payload.get("ci_feedback", False),
                auto_repair_ci=payload.get("auto_repair_ci", False),
                auto_sync_repair=payload.get("auto_sync_repair", False),
                use_memory=payload.get("use_memory", True),
                save_memory=payload.get("save_memory", True),
                pr_number=payload.get("pr_number"),
                comment_body=payload.get("comment_body", ""),
                repair_context=payload.get("repair_context") or None,
                original_issue=payload.get("original_issue") or payload["issue"],
            )
        return {"payload": payload}

    def _verify(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "verify", "execute"):
            self._approval_store(payload).checkpoint(payload["graph_run_id"], "verify", payload)
            payload["graph_trace"].append({"node": "verify"})
            result: RepoDiagnosisResult = payload["result"]
            evaluation = result.task.evaluation
            scores = evaluation.get("scores", {})
            if payload.get("run_tests"):
                executed_test_score = float(scores.get("executed_tests", 0) or 0)
                tests_ok = executed_test_score >= 1.0 or (
                    evaluation.get("passed", False)
                    and scores.get("patch_apply_check", 0) >= 1.0
                    and executed_test_score >= 0.75
                )
            else:
                tests_ok = True
            payload["verified"] = (
                scores.get("patch_apply_check", 0) >= 1.0
                and tests_ok
                and evaluation.get("passed", False)
            )
            payload["last_repair_context"] = self._build_repair_context_from_result(result, payload)
        return {"payload": payload}

    def _repair(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "repair", "execute"):
            self._approval_store(payload).checkpoint(payload["graph_run_id"], "repair", payload)
            payload["graph_trace"].append({"node": "repair"})
            payload["repair_round"] = int(payload.get("repair_round", 0)) + 1
            payload["repair_context"] = dict(payload.get("last_repair_context") or {})
            payload["issue"] = payload.get("original_issue") or payload["issue"]
        return {"payload": payload}

    def _judge(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "judge", "execute"):
            self._approval_store(payload).checkpoint(payload["graph_run_id"], "judge", payload)
            payload["graph_trace"].append({"node": "judge"})
        return {"payload": payload}

    def _pr_ready(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state["payload"]
        with self._trace_store(payload).span(payload["graph_run_id"], "pr_ready", "execute"):
            self._approval_store(payload).checkpoint(payload["graph_run_id"], "pr_ready", payload)
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

    def _approval_store(self, payload: dict[str, Any]) -> ApprovalStore:
        return ApprovalStore(payload["approval_db_path"])

    def _build_repair_context_from_result(
        self,
        result: RepoDiagnosisResult,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        analysis = result.task.analysis
        selected_patch = (analysis.get("selected_patch") or {}).get("selected") or {}
        patch_portfolio = analysis.get("patch_portfolio") or {}
        failure_signals = analysis.get("failure_signals") or []
        learned_policy = analysis.get("learned_repair_policy") or {}
        repair_context = {
            "repair_round": int(payload.get("repair_round", 0) or 0) + 1,
            "previous_overall": result.task.evaluation.get("overall"),
            "previous_passed": result.task.evaluation.get("passed"),
            "strategy": "",
            "summary_lines": [],
            "target_files": [],
            "failure_signals": failure_signals[:8],
            "top_patch_candidates": [],
            "memory_hits": (analysis.get("memory_hits") or [])[:3],
        }
        repair_journal = analysis.get("repair_journal") or []
        if repair_journal:
            latest = repair_journal[-1]
            repair_context["strategy"] = str(latest.get("strategy") or "")
            repair_context["target_files"] = list(latest.get("target_files") or [])[:6]
            repair_context["summary_lines"] = [
                f"latest_strategy={latest.get('strategy', '')}",
                f"latest_family={latest.get('primary_family', '')}",
                f"failed_stages={', '.join(latest.get('failed_stages', [])[:4])}",
            ]
        else:
            repair_context["target_files"] = list((analysis.get("suspected_files") or [])[:6])
        candidates = patch_portfolio.get("top_candidates") or []
        if selected_patch:
            repair_context["top_patch_candidates"].append(selected_patch)
        for item in candidates[:3]:
            if item not in repair_context["top_patch_candidates"]:
                repair_context["top_patch_candidates"].append(item)
        if learned_policy.get("summary_lines"):
            repair_context["summary_lines"].extend(str(item) for item in learned_policy.get("summary_lines", [])[:4])
        repair_context["summary_lines"] = list(dict.fromkeys(item for item in repair_context["summary_lines"] if item))[:8]
        return repair_context

    def _issue_for_repair_round(self, payload: dict[str, Any]) -> str:
        base_issue = payload.get("original_issue") or payload["issue"]
        repair_context = payload.get("repair_context") or {}
        lines = [
            base_issue,
            "",
            f"Repair round: {payload.get('repair_round', 0)}",
            "Previous validation failed. Generate a smaller patch using patch-check, test, and judge feedback.",
        ]
        if repair_context.get("strategy"):
            lines.append(f"Repair strategy: {repair_context['strategy']}")
        if repair_context.get("target_files"):
            lines.append("Target files: " + ", ".join(repair_context.get("target_files", [])[:6]))
        for item in (repair_context.get("failure_signals") or [])[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                "Failure signal: "
                f"{item.get('source', '')}:{item.get('kind', '')} "
                f"{item.get('path', '')}:{item.get('line', '')} "
                f"{str(item.get('message') or '')[:220]}"
            )
        return "\n".join(lines)

    def _approval_gate(
        self,
        *,
        approval_db_path: Path,
        graph_run_id: str,
        apply_worktree: bool,
        create_pr: bool,
        require_approval: bool,
    ) -> dict[str, Any] | None:
        if not require_approval or not (apply_worktree or create_pr):
            return None
        gate_id = f"{graph_run_id}:mutation"
        store = ApprovalStore(approval_db_path)
        decision = store.create_gate(
            gate_id=gate_id,
            risk="worktree_or_github_mutation",
            payload={
                "apply_worktree": apply_worktree,
                "create_pr": create_pr,
                "action": "approve before applying patches to worktree or creating GitHub PR",
            },
        )
        return {
            "gate_id": decision.gate_id,
            "approved": decision.approved,
            "reason": decision.reason,
            "db_path": str(approval_db_path),
            "blocked_actions": ["apply_worktree", "create_pr"] if not decision.approved else [],
        }
