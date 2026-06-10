from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodeSymbol:
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    parent: str = ""


@dataclass(frozen=True)
class CodeRelation:
    source: str
    target: str
    kind: str
    path: str
    line: int


@dataclass
class CodeGraph:
    parser_backend: str
    symbols: list[CodeSymbol] = field(default_factory=list)
    relations: list[CodeRelation] = field(default_factory=list)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)

    def symbols_for_chunk(self, path: str, start_line: int, end_line: int) -> list[str]:
        names = [
            item.name
            for item in self.symbols
            if item.path == path and item.start_line <= end_line and item.end_line >= start_line
        ]
        return list(dict.fromkeys(names))

    def calls_for_chunk(self, path: str, start_line: int, end_line: int) -> list[str]:
        names = [
            item.target
            for item in self.relations
            if item.path == path and start_line <= item.line <= end_line and item.kind == "calls"
        ]
        return list(dict.fromkeys(names))

    def file_context(self, path: str) -> dict[str, Any]:
        return self.files.get(path, {})

    def neighbors(self, path: str) -> list[str]:
        related: list[str] = []
        symbol_to_path = {symbol.name: symbol.path for symbol in self.symbols}
        for relation in self.relations:
            if relation.path == path:
                target_path = symbol_to_path.get(relation.target, "")
                if target_path and target_path != path and target_path not in related:
                    related.append(target_path)
        imports = self.files.get(path, {}).get("imports", []) or []
        file_names = {item_path.split("/")[-1].split(".")[0]: item_path for item_path in self.files}
        for entry in imports:
            tokens = entry.replace(",", " ").replace(";", " ").split()
            for token in tokens:
                normalized = token.strip().split(".")[-1]
                target_path = file_names.get(normalized, "")
                if target_path and target_path != path and target_path not in related:
                    related.append(target_path)
        return related

    def impact_subgraph(self, seed_paths: list[str], max_hops: int = 2) -> dict[str, Any]:
        normalized = [path.replace("\\", "/") for path in seed_paths if path]
        frontier = normalized[:]
        visited = set(normalized)
        edges: list[dict[str, Any]] = []
        for hop in range(1, max_hops + 1):
            next_frontier: list[str] = []
            for path in frontier:
                for neighbor in self.neighbors(path):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)
                    edges.append({"source": path, "target": neighbor, "hop": hop})
            frontier = next_frontier
            if not frontier:
                break
        return {
            "seed_paths": normalized,
            "nodes": list(visited),
            "edges": edges,
        }

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for symbol in self.symbols:
            by_kind[symbol.kind] = by_kind.get(symbol.kind, 0) + 1
        return {
            "parser_backend": self.parser_backend,
            "file_count": len(self.files),
            "symbol_count": len(self.symbols),
            "relation_count": len(self.relations),
            "symbols_by_kind": by_kind,
        }


class TreeSitterCodeGraphBuilder:
    """Build a source-code knowledge graph with real Tree-sitter parsers.

    The main path uses grammar wheels such as `tree-sitter-python`,
    `tree-sitter-javascript`, and `tree-sitter-typescript`, so parsing does not
    depend on runtime grammar downloads.
    """

    LANGUAGE_BY_SUFFIX = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
    }

    SYMBOL_NODE_TYPES = {
        "function_definition": "function",
        "class_definition": "class",
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "arrow_function": "function",
        "function": "function",
        "generator_function_declaration": "function",
    }

    CALL_NODE_TYPES = {
        "call",
        "call_expression",
    }

    IMPORT_NODE_TYPES = {
        "import_statement",
        "import_from_statement",
        "import_declaration",
    }

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path).resolve()
        self._parsers: dict[str, Any] = {}
        self._backend = "tree_sitter"

    def build_for_files(self, files: list[tuple[str, str]]) -> CodeGraph:
        graph = CodeGraph(parser_backend=self._backend)
        for rel, text in files:
            language_name = self.LANGUAGE_BY_SUFFIX.get(Path(rel).suffix.lower())
            if not language_name:
                continue
            parser = self._parser(language_name)
            if parser is None:
                graph.parser_backend = "tree_sitter_unavailable"
                continue
            tree = parser.parse(text.encode("utf-8", errors="ignore"))
            imports: list[str] = []
            self._walk_tree(rel, text, tree.root_node, graph, imports, parent="")
            graph.files[rel] = {
                "language": language_name,
                "imports": list(dict.fromkeys(imports)),
                "content_hash": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16],
            }
        return graph

    def _parser(self, language_name: str) -> Any | None:
        if language_name in self._parsers:
            return self._parsers[language_name]
        try:
            from tree_sitter import Language, Parser
        except Exception:
            self._backend = "tree_sitter_missing"
            return None

        try:
            if language_name == "python":
                import tree_sitter_python

                language = Language(tree_sitter_python.language())
            elif language_name == "javascript":
                import tree_sitter_javascript

                language = Language(tree_sitter_javascript.language())
            elif language_name == "typescript":
                import tree_sitter_typescript

                language = Language(tree_sitter_typescript.language_typescript())
            elif language_name == "tsx":
                import tree_sitter_typescript

                language = Language(tree_sitter_typescript.language_tsx())
            else:
                return None
            parser = Parser(language)
            self._parsers[language_name] = parser
            return parser
        except Exception:
            self._backend = "tree_sitter_parser_error"
            return None

    def _walk_tree(
        self,
        rel: str,
        text: str,
        node: Any,
        graph: CodeGraph,
        imports: list[str],
        parent: str,
    ) -> None:
        current_parent = parent
        if node.type in self.SYMBOL_NODE_TYPES:
            name = self._node_name(node, text)
            if name:
                kind = self.SYMBOL_NODE_TYPES[node.type]
                graph.symbols.append(
                    CodeSymbol(
                        name=name,
                        kind=kind,
                        path=rel,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parent=parent,
                    )
                )
                current_parent = name
        elif node.type in self.CALL_NODE_TYPES:
            target = self._call_target(node, text)
            if target:
                graph.relations.append(
                    CodeRelation(
                        source=current_parent or "<module>",
                        target=target,
                        kind="calls",
                        path=rel,
                        line=node.start_point[0] + 1,
                    )
                )
        elif node.type in self.IMPORT_NODE_TYPES:
            import_text = self._node_text(node, text).strip()
            if import_text:
                imports.append(import_text[:300])

        for child in node.children:
            self._walk_tree(rel, text, child, graph, imports, current_parent)

    def _node_name(self, node: Any, text: str) -> str:
        named = node.child_by_field_name("name")
        if named is not None:
            return self._node_text(named, text).strip()
        for child in node.children:
            if child.type in {"identifier", "property_identifier", "type_identifier"}:
                return self._node_text(child, text).strip()
        return ""

    def _call_target(self, node: Any, text: str) -> str:
        func = node.child_by_field_name("function")
        if func is None and node.children:
            func = node.children[0]
        if func is None:
            return ""
        return self._name_from_expression(func, text)

    def _name_from_expression(self, node: Any, text: str) -> str:
        if node.type in {"identifier", "property_identifier", "attribute", "type_identifier"}:
            return self._node_text(node, text).strip()
        if node.type in {"member_expression", "attribute"}:
            prop = node.child_by_field_name("property") or node.child_by_field_name("attribute")
            if prop is not None:
                return self._node_text(prop, text).strip()
        children = [self._name_from_expression(child, text) for child in node.children]
        children = [item for item in children if item]
        return children[-1] if children else ""

    def _node_text(self, node: Any, text: str) -> str:
        return text.encode("utf-8", errors="ignore")[node.start_byte : node.end_byte].decode(
            "utf-8",
            errors="ignore",
        )
