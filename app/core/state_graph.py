from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


GraphNode = Callable[[dict[str, Any]], dict[str, Any]]
Router = Callable[[dict[str, Any]], str | None]


@dataclass
class StateGraph:
    """A tiny LangGraph-style runtime for deterministic local execution.

    It supports named nodes, normal edges, conditional routers, and bounded
    loops. The API is intentionally small so the project can run without extra
    dependencies while preserving a state-graph architecture.
    """

    max_steps: int = 32
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: dict[str, str] = field(default_factory=dict)
    routers: dict[str, Router] = field(default_factory=dict)
    entrypoint: str | None = None

    def add_node(self, name: str, node: GraphNode) -> None:
        self.nodes[name] = node

    def set_entrypoint(self, name: str) -> None:
        self.entrypoint = name

    def add_edge(self, source: str, target: str) -> None:
        self.edges[source] = target

    def add_conditional_edges(self, source: str, router: Router) -> None:
        self.routers[source] = router

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        if not self.entrypoint:
            raise ValueError("StateGraph entrypoint is not set.")
        current: str | None = self.entrypoint
        steps = 0
        state.setdefault("graph_trace", [])
        while current:
            if steps >= self.max_steps:
                raise RuntimeError(f"StateGraph exceeded max_steps={self.max_steps}")
            node = self.nodes[current]
            state["graph_trace"].append({"step": steps + 1, "node": current})
            updates = node(state) or {}
            state.update(updates)
            if current in self.routers:
                current = self.routers[current](state)
            else:
                current = self.edges.get(current)
            steps += 1
        return state

