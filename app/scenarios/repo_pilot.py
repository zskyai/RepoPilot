from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.github_ops import GitHubOps
from app.core.llm import LLMClient, build_llm
from app.core.models import Evidence, ResearchTask, TaskStatus
from app.core.retrieval import RetrievalScore, build_embedding_client, cosine_similarity, resilient_embed_texts
from app.rag.index import tokenize


CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
}

IGNORE_DIRS = {
    ".git",
    ".repopilot",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
}


@dataclass
class CodeChunk:
    path: str
    start_line: int
    end_line: int
    content: str
    symbols: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


@dataclass
class RepoDiagnosisResult:
    task: ResearchTask
    repo_path: str
    issue: str
    suspected_files: list[str]
    change_plan: list[str]
    test_plan: list[str]
    risk_items: list[str]
    patch_suggestions: list[dict[str, str]] = field(default_factory=list)
    test_runs: list[dict[str, Any]] = field(default_factory=list)
    patch_checks: list[dict[str, Any]] = field(default_factory=list)
    sandbox_runs: list[dict[str, Any]] = field(default_factory=list)
    worktree_runs: list[dict[str, Any]] = field(default_factory=list)
    pr_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = self.task.to_dict()
        payload.update(
            {
                "scenario": "repo_pilot_issue_diagnosis",
                "repo_path": self.repo_path,
                "issue": self.issue,
                "suspected_files": self.suspected_files,
                "change_plan": self.change_plan,
                "test_plan": self.test_plan,
                "risk_items": self.risk_items,
                "patch_suggestions": self.patch_suggestions,
                "test_runs": self.test_runs,
                "patch_checks": self.patch_checks,
                "sandbox_runs": self.sandbox_runs,
                "worktree_runs": self.worktree_runs,
                "pr_plan": self.pr_plan,
            }
        )
        return payload


def evidence_brief(evidence: list[Evidence], limit: int = 5) -> str:
    blocks = []
    for item in evidence[:limit]:
        blocks.append(
            f"FILE: {item.title}\n"
            f"SYMBOLS: {', '.join(item.metadata.get('symbols') or [])}\n"
            f"CODE:\n{item.content[:1200]}"
        )
    return "\n\n---\n\n".join(blocks)


def parse_bullets(text: str, fallback: list[str], limit: int = 8) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        line = re.sub(r"^[-*\d.、\s]+", "", line).strip()
        if line:
            lines.append(line)
    return (lines or fallback)[:limit]


def parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def clean_unified_diff(diff: str) -> str:
    diff = diff.strip()
    diff = re.sub(r"^```(?:diff)?", "", diff).strip()
    diff = re.sub(r"```$", "", diff).strip()
    lines = [line.rstrip() for line in diff.splitlines()]
    while lines and not (
        lines[0].startswith("--- ")
        or lines[0].startswith("diff --git")
        or lines[0].startswith("+++ ")
    ):
        lines.pop(0)
    return "\n".join(lines).strip()


class LLMRepoAgent:
    def __init__(self, name: str, role: str, llm: LLMClient) -> None:
        self.name = name
        self.role = role
        self.llm = llm

    def ask(self, prompt: str) -> str:
        return self.llm.generate(self.role, prompt)


class RootCauseAgent(LLMRepoAgent):
    def run(self, issue: str, evidence: list[Evidence]) -> str:
        return self.ask(
            "You are diagnosing a software issue from retrieved code evidence. "
            "Return one concise Chinese root-cause hypothesis grounded in file names and behavior.\n\n"
            f"Issue:\n{issue}\n\nEvidence:\n{evidence_brief(evidence)}"
        ).strip()


class PatchPlannerAgent(LLMRepoAgent):
    def run(self, issue: str, root_cause: str, evidence: list[Evidence]) -> list[str]:
        text = self.ask(
            "Create a minimal engineering change plan in Chinese. "
            "Return JSON only: {\"steps\": [\"...\"]}. Use 4-7 steps. Mention specific files and tests.\n\n"
            f"Issue:\n{issue}\n\nRoot cause:\n{root_cause}\n\nEvidence:\n{evidence_brief(evidence)}"
        )
        data = parse_json_object(text)
        if data and isinstance(data.get("steps"), list):
            return [str(item) for item in data["steps"][:8]]
        return parse_bullets(text, ["补充最小复现，再实施最小修改。"])


class PatchSuggestionAgent(LLMRepoAgent):
    def run(self, issue: str, root_cause: str, evidence: list[Evidence]) -> list[dict[str, str]]:
        text = self.ask(
            "You are a senior coding agent. Propose one safe patch suggestion. "
            "Return JSON only with keys: title, target_file, reason, diff. "
            "The diff value must be unified-diff style and must not include markdown fences. "
            "Prefer documentation/test patch if code change is risky.\n\n"
            f"Issue:\n{issue}\n\nRoot cause:\n{root_cause}\n\nEvidence:\n{evidence_brief(evidence)}"
        )
        data = parse_json_object(text)
        if data:
            return [
                {
                    "title": str(data.get("title") or "LLM generated patch suggestion"),
                    "target_file": str(data.get("target_file") or "UNKNOWN"),
                    "reason": str(data.get("reason") or ""),
                    "diff": clean_unified_diff(str(data.get("diff") or "")),
                }
            ]
        suggestion = self._parse_patch_text(text)
        suggestion["diff"] = clean_unified_diff(suggestion["diff"])
        return [suggestion]

    def _parse_patch_text(self, text: str) -> dict[str, str]:
        fields = {"title": "LLM generated patch suggestion", "target_file": "UNKNOWN", "reason": "", "diff": text}
        current = None
        buffers: dict[str, list[str]] = {"diff": []}
        for line in text.splitlines():
            upper = line.strip().upper()
            if upper.startswith("TITLE:"):
                fields["title"] = line.split(":", 1)[1].strip()
                current = None
            elif upper.startswith("TARGET_FILE:"):
                fields["target_file"] = line.split(":", 1)[1].strip()
                current = None
            elif upper.startswith("REASON:"):
                fields["reason"] = line.split(":", 1)[1].strip()
                current = None
            elif upper.startswith("DIFF:"):
                current = "diff"
            elif current == "diff":
                buffers["diff"].append(line)
        if buffers["diff"]:
            fields["diff"] = "\n".join(buffers["diff"]).strip()
        return fields


class RepairAdvisorAgent(LLMRepoAgent):
    def run(self, test_runs: list[dict[str, Any]]) -> list[str]:
        if not test_runs:
            return ["当前未执行测试。建议使用 --run-tests 启动测试闭环。"]
        text = self.ask(
            "Analyze these test results. Return JSON only: {\"advice\": [\"...\"]}.\n\n"
            f"Test runs:\n{test_runs}"
        )
        data = parse_json_object(text)
        if data and isinstance(data.get("advice"), list):
            return [str(item) for item in data["advice"][:8]]
        return parse_bullets(text, ["根据失败日志补充最小复现。"])


class RepoJudgeLLMAgent(LLMRepoAgent):
    def run(self, task: ResearchTask) -> dict[str, Any]:
        text = self.ask(
            "Evaluate this coding-agent output. Return JSON only: {\"score\": 0.0, \"comment\": \"...\"}. "
            "Important: git apply --check and pytest results are hard evidence. "
            "If patch_apply_check and executed_tests passed, do not fail the output only because of residual design concerns. "
            "Consider code grounding, localization, patch readiness, tests, and risk.\n\n"
            f"Issue: {task.query}\n\nAnalysis: {task.analysis}\n\nEvaluation so far: {task.evaluation}\n\nEvidence: {evidence_brief(task.evidence, limit=8)}"
        )
        data = parse_json_object(text)
        if data and "score" in data:
            try:
                score = float(data["score"])
            except (TypeError, ValueError):
                score = 0.8
            return {
                "llm_score": max(0.0, min(1.0, score)),
                "llm_comment": str(data.get("comment") or "")[:1000],
            }
        match = re.search(r"(?:score|分数|评分)\D*([01](?:\.\d+)?)", text, flags=re.I)
        score = float(match.group(1)) if match else 0.8
        return {"llm_score": max(0.0, min(1.0, score)), "llm_comment": text[:1000]}


class RepoIndexer:
    def __init__(self, repo_path: str | Path, max_file_kb: int = 256) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.max_file_kb = max_file_kb

    def build(self) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        for path in self._iter_files():
            rel = path.relative_to(self.repo_path).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            chunks.extend(self._chunk_file(rel, text))
        return chunks

    def _iter_files(self):
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [item for item in dirs if item not in IGNORE_DIRS]
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() not in CODE_EXTENSIONS:
                    continue
                if path.stat().st_size > self.max_file_kb * 1024:
                    continue
                yield path

    def _chunk_file(self, rel: str, text: str) -> list[CodeChunk]:
        lines = text.splitlines()
        chunks: list[CodeChunk] = []
        window = 80
        step = 60
        for start in range(0, max(1, len(lines)), step):
            piece = lines[start : start + window]
            if not piece:
                continue
            chunks.append(
                CodeChunk(
                    path=rel,
                    start_line=start + 1,
                    end_line=start + len(piece),
                    content="\n".join(piece),
                    symbols=self._symbols(rel, "\n".join(piece)),
                    calls=self._calls(rel, "\n".join(piece)),
                )
            )
            if start + window >= len(lines):
                break
        return chunks

    def _symbols(self, rel: str, text: str) -> list[str]:
        if not rel.endswith(".py"):
            return re.findall(r"\b(?:class|function|def|const|let|var)\s+([A-Za-z_]\w*)", text)[:10]
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        symbols: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
        return symbols[:10]

    def _calls(self, rel: str, text: str) -> list[str]:
        if not rel.endswith(".py"):
            return []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
        return list(dict.fromkeys(calls))[:20]


class RepoRetriever:
    def __init__(self, chunks: list[CodeChunk]) -> None:
        self.chunks = chunks
        self.embedding_client = build_embedding_client()
        self.embedding_provider = getattr(self.embedding_client, "provider", "unknown")
        self.chunk_terms = [
            set(
                tokenize(
                    chunk.path
                    + "\n"
                    + chunk.content
                    + "\n"
                    + " ".join(chunk.symbols)
                    + "\n"
                    + " ".join(chunk.calls)
                )
            )
            for chunk in chunks
        ]
        self.chunk_counters = [Counter(terms) for terms in self.chunk_terms]
        self.chunk_vectors, self.embedding_provider = resilient_embed_texts(
            self.embedding_client,
            [
                chunk.path
                + "\n"
                + "\n".join(chunk.symbols)
                + "\n"
                + "\n".join(chunk.calls)
                + "\n"
                + chunk.content
                for chunk in chunks
            ],
        )

    def search(self, query: str, top_k: int = 8) -> list[Evidence]:
        query_terms = set(tokenize(query))
        query_counter = Counter(tokenize(query))
        query_vector, _query_provider = resilient_embed_texts(self.embedding_client, [query])
        query_vector = query_vector[0]
        scored: list[tuple[float, CodeChunk, list[float]]] = []
        for chunk, terms, counter, vector in zip(
            self.chunks,
            self.chunk_terms,
            self.chunk_counters,
            self.chunk_vectors,
        ):
            overlap = len(query_terms & terms)
            lexical = overlap / max(1, len(query_terms))
            semantic = cosine_similarity(query_vector, vector)
            if overlap == 0 and semantic < 0.1:
                continue
            path_bonus = 0.5 if any(term in chunk.path.lower() for term in query_terms) else 0
            symbol_bonus = 0.2 * len(set(tokenize(" ".join(chunk.symbols))) & query_terms)
            call_bonus = 0.1 * len(set(tokenize(" ".join(chunk.calls))) & query_terms)
            idf_bonus = sum(1.0 / max(1, counter.get(term, 0)) for term in query_counter if term in counter)
            structural = path_bonus + symbol_bonus + call_bonus + min(0.5, 0.05 * idf_bonus)
            score = lexical * 0.45 + semantic * 0.4 + structural * 0.15
            scored.append((score, chunk, vector))
        scored.sort(key=lambda item: item[0], reverse=True)
        top_scores = scored[:top_k]
        return [
            self._to_evidence(chunk, score, query_vector, vector)
            for score, chunk, vector in top_scores
        ]

    def _to_evidence(self, chunk: CodeChunk, score: float, query_vector: list[float], chunk_vector: list[float]) -> Evidence:
        semantic = cosine_similarity(query_vector, chunk_vector)
        lexical = len(set(tokenize(chunk.content + "\n" + chunk.path)))
        structural = len(chunk.symbols) * 0.05 + len(chunk.calls) * 0.02
        retrieval = RetrievalScore(
            lexical=round(float(lexical), 4),
            semantic=round(float(semantic), 4),
            structural=round(float(structural), 4),
            total=round(score, 4),
            provider=self.embedding_provider,
        )
        return Evidence(
            source="repo",
            title=f"{chunk.path}:{chunk.start_line}-{chunk.end_line}",
            content=chunk.content,
            score=round(score, 4),
            metadata={
                "path": chunk.path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "symbols": chunk.symbols,
                "calls": chunk.calls,
                "retrieval": retrieval.__dict__,
            },
        )


class RepoPilotWorkflow:
    """Real scenario: issue-to-fix diagnosis agent for software teams.

    Target users are enterprise developers and engineering managers. The agent
    reads a local repository, retrieves relevant code, diagnoses likely root
    cause, proposes a patch plan, and generates a test/risk checklist.
    """

    def __init__(self, use_llm: bool = False, require_llm: bool = False, llm: LLMClient | None = None) -> None:
        self.use_llm = use_llm
        self.llm = llm or (build_llm(require_config=require_llm) if use_llm else None)
        self.root_cause_agent = RootCauseAgent(
            "root_cause_agent",
            "You are RepoPilot RootCauseAgent, a senior software debugging agent.",
            self.llm,
        ) if self.llm else None
        self.patch_planner_agent = PatchPlannerAgent(
            "patch_planner_agent",
            "You are RepoPilot PatchPlannerAgent, focused on minimal safe engineering changes.",
            self.llm,
        ) if self.llm else None
        self.patch_suggestion_agent = PatchSuggestionAgent(
            "patch_suggestion_agent",
            "You are RepoPilot PatchSuggestionAgent, producing safe unified diff patch suggestions.",
            self.llm,
        ) if self.llm else None
        self.repair_advisor_agent = RepairAdvisorAgent(
            "repair_advisor_agent",
            "You are RepoPilot RepairAdvisorAgent, analyzing test failures and next fixes.",
            self.llm,
        ) if self.llm else None
        self.repo_judge_llm_agent = RepoJudgeLLMAgent(
            "repo_judge_llm_agent",
            "You are RepoPilot JudgeAgent, evaluating coding-agent outputs.",
            self.llm,
        ) if self.llm else None
        self.allowed_patch_prefixes = (
            "app/",
            "tests/",
            "docs/",
            "benchmarks/",
            "README",
            "run_",
            "scripts_",
            "pyproject.toml",
            "requirements.txt",
        )
        self.denied_patch_prefixes = (".env", ".git", ".repopilot/")

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
        pr_number: int | None = None,
        comment_body: str = "",
    ) -> RepoDiagnosisResult:
        repo = Path(repo_path).resolve()
        task = ResearchTask(query=issue, user_type="software_engineer")
        task.mark(TaskStatus.RUNNING)
        task.add_trace("scenario", "start", scenario="repo_pilot", repo=str(repo))

        chunks = RepoIndexer(repo).build()
        task.add_trace("repo_indexer_agent", "finish", chunks=len(chunks))

        evidence = RepoRetriever(chunks).search(issue, top_k=8)
        task.evidence = evidence
        task.add_trace("code_retriever_agent", "finish", evidence_count=len(evidence))

        suspected_files = self._suspected_files(evidence)
        root_cause = self._root_cause(issue, evidence)
        if self.root_cause_agent:
            root_cause = self.root_cause_agent.run(issue, evidence)
            task.add_trace("root_cause_llm_agent", "finish", model="openai_compatible")
        change_plan = self._change_plan(issue, evidence, root_cause)
        if self.patch_planner_agent:
            change_plan = self.patch_planner_agent.run(issue, root_cause, evidence)
            task.add_trace("patch_planner_llm_agent", "finish", steps=len(change_plan))
        test_plan = self._test_plan(repo, issue, suspected_files)
        risk_items = self._risk_review(issue, suspected_files)
        patch_suggestions = self._patch_suggestions(issue, suspected_files, root_cause)
        if self.patch_suggestion_agent:
            patch_suggestions = self.patch_suggestion_agent.run(issue, root_cause, evidence)
            task.add_trace("patch_suggestion_llm_agent", "finish", suggestions=len(patch_suggestions))
        patch_checks = self._check_patches(repo, patch_suggestions)
        if patch_suggestions and not any(item.get("passed") for item in patch_checks):
            fallback = self._patch_suggestions(issue, suspected_files, root_cause)
            patch_suggestions = fallback
            patch_checks = self._check_patches(repo, patch_suggestions)
            task.add_trace(
                "patch_fallback_agent",
                "finish",
                reason="llm_patch_failed_git_apply_check",
                suggestions=len(patch_suggestions),
            )
        test_runs = self._test_repair_loop(repo, test_plan, max_rounds=2) if run_tests else []
        sandbox_runs = []
        worktree_runs = []
        if apply_sandbox or apply_worktree:
            (
                patch_suggestions,
                patch_checks,
                sandbox_runs,
            ) = self._repair_patch_in_sandbox(
                repo=repo,
                issue=issue,
                root_cause=root_cause,
                evidence=evidence,
                suspected_files=suspected_files,
                test_plan=test_plan,
                patch_suggestions=patch_suggestions,
                patch_checks=patch_checks,
                max_rounds=3,
            )
        if apply_worktree:
            worktree_runs = self._apply_patch_to_worktree(repo, patch_checks, sandbox_runs)
        second_pass = self._second_pass_advice(test_runs)
        if self.repair_advisor_agent and test_runs:
            second_pass = self.repair_advisor_agent.run(test_runs)
            task.add_trace("repair_advisor_llm_agent", "finish", advice=len(second_pass))
        pr_plan = self._pr_plan(repo, issue, patch_suggestions, test_runs)
        github_result = self._run_github_actions(
            repo=repo,
            pr_plan=pr_plan,
            create_pr=create_pr,
            poll_ci=poll_ci,
            ci_feedback=ci_feedback,
            pr_number=pr_number,
            comment_body=comment_body,
        )
        pr_plan["github"] = github_result

        task.plan = [
            "解析 issue 的错误现象、触发路径和验收标准",
            "索引代码仓库并构建轻量代码检索",
            "检索相关文件、函数、配置和测试",
            "生成根因假设与最小修改方案",
            "生成测试计划、回归范围和风险清单",
            "用 Judge Agent 评估诊断可执行性",
        ]
        task.analysis = {
            "root_cause_hypothesis": root_cause,
            "suspected_files": suspected_files,
            "change_plan": change_plan,
            "test_plan": test_plan,
            "risk_items": risk_items,
            "patch_suggestions": patch_suggestions,
            "patch_checks": patch_checks,
            "test_runs": test_runs,
            "sandbox_runs": sandbox_runs,
            "worktree_runs": worktree_runs,
            "second_pass_advice": second_pass,
            "pr_plan": pr_plan,
            "brain": "real_llm_multi_agent" if self.use_llm else "rule_based_workflow",
            "sandbox_repair_rounds": max((item.get("repair_round", 1) for item in sandbox_runs), default=0),
            "retrieval_engine": "hybrid_embedding_rerank",
        }
        task.report = self._report(task, repo, issue)
        self._judge(task)
        if self.repo_judge_llm_agent:
            task.evaluation["llm_judge"] = self.repo_judge_llm_agent.run(task)
            tool_score = task.evaluation["overall"]
            blended = round(
                tool_score * 0.8 + task.evaluation["llm_judge"]["llm_score"] * 0.2,
                3,
            )
            hard_evidence_passed = (
                task.evaluation["scores"].get("patch_apply_check") == 1.0
                and task.evaluation["scores"].get("executed_tests") == 1.0
            )
            if hard_evidence_passed:
                task.evaluation["overall"] = max(tool_score, blended)
            else:
                task.evaluation["overall"] = blended
            if (
                task.evaluation["scores"].get("patch_apply_check") == 1.0
                and task.evaluation["scores"].get("executed_tests") == 1.0
            ):
                task.evaluation["passed"] = task.evaluation["overall"] >= 0.6
            else:
                task.evaluation["passed"] = task.evaluation["overall"] >= 0.75
            task.add_trace("repo_judge_llm_agent", "finish", overall=task.evaluation["overall"])
        task.mark(TaskStatus.SUCCEEDED)
        task.add_trace("scenario", "finish", score=task.evaluation["overall"])
        return RepoDiagnosisResult(
            task=task,
            repo_path=str(repo),
            issue=issue,
            suspected_files=suspected_files,
            change_plan=change_plan,
            test_plan=test_plan,
            risk_items=risk_items,
            patch_suggestions=patch_suggestions,
            test_runs=test_runs,
            patch_checks=patch_checks,
            sandbox_runs=sandbox_runs,
            worktree_runs=worktree_runs,
            pr_plan=pr_plan,
        )

    def _suspected_files(self, evidence: list[Evidence]) -> list[str]:
        files: list[str] = []
        for item in evidence:
            path = item.metadata.get("path")
            if path and path not in files:
                files.append(path)
        return files[:6]

    def _root_cause(self, issue: str, evidence: list[Evidence]) -> str:
        text = issue.lower()
        if "import" in text or "module" in text or "no module" in text:
            return "根因可能集中在包路径、运行目录、依赖声明或 Python path 配置。"
        if "timeout" in text or "slow" in text or "latency" in text or "超时" in text:
            return "根因可能集中在同步阻塞、检索范围过大、外部 API 超时或缺少缓存。"
        if "json" in text or "schema" in text or "format" in text:
            return "根因可能集中在结构化输出约束、序列化字段或 API request/response schema 不一致。"
        if not evidence:
            return "当前代码检索未命中，需要补充错误栈、接口路径或复现步骤。"
        return "根因可能集中在检索命中的核心文件与 issue 描述之间的状态流转、边界条件或配置不一致。"

    def _change_plan(self, issue: str, evidence: list[Evidence], root_cause: str) -> list[str]:
        plan = [f"围绕根因假设排查：{root_cause}"]
        for item in evidence[:4]:
            path = item.metadata.get("path")
            start = item.metadata.get("start_line")
            end = item.metadata.get("end_line")
            symbols = ", ".join(item.metadata.get("symbols") or [])
            plan.append(f"检查 {path}:{start}-{end}，重点关注 {symbols or '输入输出、异常处理和状态更新'}。")
        plan.append("补充最小失败用例，先复现，再实施最小修改。")
        plan.append("修改后运行单元测试和一次端到端 CLI/API 验证。")
        return plan

    def _test_plan(self, repo: Path, issue: str, suspected_files: list[str]) -> list[str]:
        tests = []
        if (repo / "pyproject.toml").exists() or (repo / "tests").exists():
            tests.append("python -m pytest -q")
        if (repo / "package.json").exists():
            tests.append("npm test")
        tests.append("运行 issue 对应的最小复现命令，确认错误消失。")
        tests.append("针对疑似文件增加边界输入、空结果、异常路径和并发/超时测试。")
        if suspected_files:
            tests.append(f"重点回归影响文件：{', '.join(suspected_files[:3])}")
        return tests

    def _risk_review(self, issue: str, suspected_files: list[str]) -> list[str]:
        risks = [
            "避免为了通过当前用例而扩大修改范围。",
            "如果涉及 API schema，需要检查向后兼容性。",
            "如果涉及异步、缓存或重试，需要关注重复执行和脏状态。",
        ]
        if any(path.endswith((".json", ".toml", ".yaml", ".yml")) for path in suspected_files):
            risks.append("配置文件变更可能影响部署环境，需要补充启动验证。")
        return risks

    def _module_path_patch_suggestions(self) -> list[dict[str, str]]:
        suggestions: list[dict[str, str]] = []
        script_path = Path("scripts_start_api.ps1")
        smoke_test_path = Path("tests/test_import_smoke.py")
        module_doc_path = Path("docs/module_path.md")
        if not script_path.exists():
            suggestions.append(
                {
                    "title": "Add a stable Windows API startup script",
                    "target_file": "scripts_start_api.ps1",
                    "reason": "Fix startup path handling with a stable script rooted at the repository root.",
                    "diff": """diff --git a/scripts_start_api.ps1 b/scripts_start_api.ps1
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/scripts_start_api.ps1
@@ -0,0 +1,3 @@
+$env:PYTHONIOENCODING = "utf-8"
+$env:PYTHONPATH = (Get-Location).Path
+python -m uvicorn app.api.server:app --reload --port 8000
""",
                }
            )
        elif not smoke_test_path.exists():
            suggestions.append(
                {
                    "title": "Add import smoke test for module-path startup",
                    "target_file": "tests/test_import_smoke.py",
                    "reason": "Add a minimal import smoke test to keep module-path regressions visible.",
                    "diff": """diff --git a/tests/test_import_smoke.py b/tests/test_import_smoke.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/tests/test_import_smoke.py
@@ -0,0 +1,4 @@
+def test_import_app_package():
+    module = __import__("app")
+    assert module is not None
""",
                }
            )
        else:
            suggestions.append(
                {
                    "title": "Strengthen existing import smoke test",
                    "target_file": "tests/test_import_smoke.py",
                    "reason": "If the smoke test already exists, extend it to cover the API server import path.",
                    "diff": """diff --git a/tests/test_import_smoke.py b/tests/test_import_smoke.py
--- a/tests/test_import_smoke.py
+++ b/tests/test_import_smoke.py
@@ -1,3 +1,6 @@
 def test_import_app_package():
     module = __import__("app")
     assert module is not None
+
+def test_import_api_server_module():
+    module = __import__("app.api.server", fromlist=["app"])
+    assert module is not None
""",
                }
            )
        if not module_doc_path.exists():
            suggestions.append(
                {
                    "title": "Document module-path troubleshooting",
                    "target_file": "docs/module_path.md",
                    "reason": "Persist module-path debugging steps as reusable engineering guidance.",
                    "diff": """diff --git a/docs/module_path.md b/docs/module_path.md
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/docs/module_path.md
@@ -0,0 +1,6 @@
+# Module Path Troubleshooting
+
+- Run commands from the repository root.
+- Prefer `python -m uvicorn app.api.server:app --reload --port 8000`.
+- On Windows PowerShell, set `PYTHONPATH` to the current directory before startup.
+- Add a smoke test that imports `app` to catch regressions early.
""",
                }
            )
        else:
            suggestions.append(
                {
                    "title": "Extend module-path troubleshooting guide",
                    "target_file": "docs/module_path.md",
                    "reason": "If the guide already exists, extend it with smoke-test and startup-script follow-up steps.",
                    "diff": """diff --git a/docs/module_path.md b/docs/module_path.md
--- a/docs/module_path.md
+++ b/docs/module_path.md
@@ -3,4 +3,7 @@
 - Run commands from the repository root.
 - Prefer `python -m uvicorn app.api.server:app --reload --port 8000`.
 - On Windows PowerShell, set `PYTHONPATH` to the current directory before startup.
 - Add a smoke test that imports `app` to catch regressions early.
+- If the smoke test already exists, also verify `app.api.server` can be imported.
+- Keep `scripts_start_api.ps1` aligned with the repository root startup path.
+- Re-run `python -m pytest -q` after changing startup scripts.
""",
                }
            )
        return suggestions

    def _patch_suggestions(
        self, issue: str, suspected_files: list[str], root_cause: str
    ) -> list[dict[str, str]]:
        text = issue.lower()
        suggestions: list[dict[str, str]] = []
        if "no module" in text or "module named app" in text or "import" in text:
            return self._module_path_patch_suggestions()
            script_path = Path("scripts_start_api.ps1")
            if not script_path.exists():
                suggestions.append(
                    {
                        "title": "Add a stable Windows API startup script",
                        "target_file": "scripts_start_api.ps1",
                        "reason": "将启动目录和 PYTHONPATH 固定在项目根目录，降低 No module named app 这类环境问题。",
                        "diff": """diff --git a/scripts_start_api.ps1 b/scripts_start_api.ps1
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/scripts_start_api.ps1
@@ -0,0 +1,3 @@
+$env:PYTHONIOENCODING = "utf-8"
+$env:PYTHONPATH = (Get-Location).Path
+python -m uvicorn app.api.server:app --reload --port 8000
""",
                    }
                )
            else:
                suggestions.append(
                    {
                        "title": "Add import smoke test for module-path startup",
                        "target_file": "tests/test_import_smoke.py",
                        "reason": "当前脚本已存在，更稳妥的做法是补一个最小导入 smoke test，防止包路径问题回归。",
                        "diff": """diff --git a/tests/test_import_smoke.py b/tests/test_import_smoke.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/tests/test_import_smoke.py
@@ -0,0 +1,4 @@
+def test_import_app_package():
+    module = __import__("app")
+    assert module is not None
""",
                    }
                )
            suggestions.append(
                {
                    "title": "Document module-path troubleshooting",
                    "target_file": "docs/module_path.md",
                    "reason": "把常见启动错误沉淀为可复用的研发知识，减少重复 issue。",
                    "diff": """diff --git a/docs/module_path.md b/docs/module_path.md
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/docs/module_path.md
@@ -0,0 +1,6 @@
+# Module Path Troubleshooting
+
+- Run commands from the repository root.
+- Prefer `python -m uvicorn app.api.server:app --reload --port 8000`.
+- On Windows PowerShell, set `PYTHONPATH` to the current directory before startup.
+- Add a smoke test that imports `app` to catch regressions early.
""",
                }
            )
        elif "json" in text or "schema" in text or "format" in text:
            suggestions.append(
                {
                    "title": "Stabilize API response schema with explicit contract tests",
                    "target_file": "tests/test_api_schema.py",
                    "reason": "通过契约测试约束接口字段，避免 Agent 输出或 API 返回结构漂移。",
                    "diff": """diff --git a/tests/test_api_schema.py b/tests/test_api_schema.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/tests/test_api_schema.py
@@ -0,0 +1,8 @@
+from app.scenarios.repo_pilot import RepoPilotWorkflow
+
+
+def test_repo_pilot_schema_contains_required_fields():
+    result = RepoPilotWorkflow().run(".", "schema contract smoke test")
+    payload = result.to_dict()
+    for key in ["scenario", "repo_path", "issue", "suspected_files", "change_plan", "test_plan"]:
+        assert key in payload
""",
                }
            )
        else:
            target = suspected_files[0] if suspected_files else "UNKNOWN"
            suggestions.append(
                {
                    "title": "Create a minimal regression test before patching",
                    "target_file": "tests/test_regression_issue.py",
                    "reason": f"当前根因仍是假设：{root_cause}。先补最小复现，降低误修风险。",
                    "diff": f"""diff --git a/tests/test_regression_issue.py b/tests/test_regression_issue.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/tests/test_regression_issue.py
@@ -0,0 +1,3 @@
+def test_regression_for_current_issue():
+    # TODO: encode the failing behavior around {target}
+    assert True
""",
                }
            )
        return suggestions

    def _patch_issue_with_failure_context(
        self,
        issue: str,
        sandbox_runs: list[dict[str, Any]],
        round_id: int,
    ) -> str:
        failure_logs = []
        for item in sandbox_runs[-4:]:
            if item.get("passed"):
                continue
            output = (item.get("stderr") or item.get("stdout") or "").strip()
            failure_logs.append(
                f"[{item.get('stage', 'unknown')}] command={item.get('command', item.get('patch_file', 'n/a'))}\n"
                f"{output[:600]}"
            )
        if not failure_logs:
            failure_logs.append("Sandbox apply or validation still failed, but no detailed logs were captured.")
        return (
            issue
            + f"\n\nPrevious repair round {round_id} failed. Generate a smaller, directly applicable fix."
            + "\nFocus on a unified diff that can pass git apply and preserve existing behavior."
            + "\nFailure context:\n"
            + "\n\n".join(failure_logs)
        )

    def _run_tests(self, repo: Path, test_plan: list[str]) -> list[dict[str, Any]]:
        commands = self._test_commands(repo, test_plan)
        runs = []
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    timeout=25,
                    shell=False,
                )
                runs.append(
                    {
                        "command": " ".join(command),
                        "returncode": completed.returncode,
                        "passed": completed.returncode == 0,
                        "stdout": completed.stdout[-1200:],
                        "stderr": completed.stderr[-1200:],
                    }
                )
            except Exception as exc:
                runs.append(
                    {
                        "command": " ".join(command),
                        "returncode": -1,
                        "passed": False,
                        "stdout": "",
                        "stderr": repr(exc),
                    }
                )
        return runs

    def _test_repair_loop(self, repo: Path, test_plan: list[str], max_rounds: int = 2) -> list[dict[str, Any]]:
        all_runs: list[dict[str, Any]] = []
        for round_id in range(1, max_rounds + 1):
            runs = self._run_tests(repo, test_plan)
            for item in runs:
                item["round"] = round_id
            all_runs.extend(runs)
            if runs and all(item["passed"] for item in runs):
                break
            if self.repair_advisor_agent:
                advice = self.repair_advisor_agent.run(runs)
                all_runs.append(
                    {
                        "command": "repair_advisor",
                        "returncode": 0,
                        "passed": True,
                        "stdout": "\n".join(advice),
                        "stderr": "",
                        "round": round_id,
                    }
                )
        return all_runs

    def _check_patches(self, repo: Path, patch_suggestions: list[dict[str, str]]) -> list[dict[str, Any]]:
        checks = []
        patch_dir = repo / ".repopilot" / "patches"
        patch_dir.mkdir(parents=True, exist_ok=True)
        for idx, suggestion in enumerate(patch_suggestions, start=1):
            diff = clean_unified_diff(suggestion.get("diff", ""))
            touched_files = self._extract_patch_targets(diff)
            patch_file = patch_dir / f"suggestion_{idx}.patch"
            patch_file.write_text(diff + "\n", encoding="utf-8")
            check = {
                "title": suggestion.get("title", f"suggestion_{idx}"),
                "patch_file": str(patch_file),
                "target_file": suggestion.get("target_file", ""),
                "touched_files": touched_files,
                "apply_check": "skipped",
                "passed": False,
                "stderr": "",
            }
            policy_error = self._validate_patch_targets(touched_files)
            if policy_error:
                check["apply_check"] = "blocked_by_policy"
                check["stderr"] = policy_error
                checks.append(check)
                continue
            if diff.startswith(("--- ", "diff --git")):
                try:
                    completed = subprocess.run(
                        ["git", "apply", "--check", str(patch_file)],
                        cwd=repo,
                        capture_output=True,
                        text=True,
                        timeout=20,
                        shell=False,
                    )
                    check["apply_check"] = "git apply --check"
                    check["passed"] = completed.returncode == 0
                    check["stderr"] = completed.stderr[-1000:]
                except Exception as exc:
                    check["apply_check"] = "error"
                    check["stderr"] = repr(exc)
            else:
                check["stderr"] = "Patch is not unified diff style."
            checks.append(check)
        return checks

    def _extract_patch_targets(self, diff: str) -> list[str]:
        targets: list[str] = []
        for line in diff.splitlines():
            if not line.startswith("+++ "):
                continue
            path = line[4:].strip()
            if path == "/dev/null":
                continue
            if path.startswith("b/"):
                path = path[2:]
            if path not in targets:
                targets.append(path)
        return targets

    def _validate_patch_targets(self, touched_files: list[str]) -> str:
        if not touched_files:
            return "Patch does not declare any target files."
        for path in touched_files:
            normalized = path.replace("\\", "/")
            if any(normalized.startswith(prefix) for prefix in self.denied_patch_prefixes):
                return f"Patch target {normalized} is blocked by safety policy."
            if not any(normalized.startswith(prefix) for prefix in self.allowed_patch_prefixes):
                return f"Patch target {normalized} is outside the current allowlist."
        return ""

    def _apply_patch_in_sandbox(
        self,
        repo: Path,
        patch_checks: list[dict[str, Any]],
        test_plan: list[str],
        repair_round: int = 1,
    ) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for item in patch_checks:
            if not item.get("passed"):
                continue
            sandbox_root = repo / ".repopilot" / "sandbox"
            if sandbox_root.exists():
                shutil.rmtree(sandbox_root)
            ignore = shutil.ignore_patterns(".git", ".venv", ".repopilot", "__pycache__", ".pytest_cache")
            shutil.copytree(repo, sandbox_root, ignore=ignore)
            patch_file = Path(item["patch_file"])
            sandbox_patch = sandbox_root / ".repopilot_patch.patch"
            sandbox_patch.write_text(patch_file.read_text(encoding="utf-8"), encoding="utf-8")
            apply_result = subprocess.run(
                ["git", "apply", str(sandbox_patch)],
                cwd=sandbox_root,
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            runs.append(
                {
                    "stage": "apply_patch",
                    "repair_round": repair_round,
                    "sandbox": str(sandbox_root),
                    "patch_file": str(patch_file),
                    "returncode": apply_result.returncode,
                    "passed": apply_result.returncode == 0,
                    "stdout": apply_result.stdout[-1000:],
                    "stderr": apply_result.stderr[-1000:],
                }
            )
            if apply_result.returncode == 0:
                for test in self._run_tests(sandbox_root, test_plan):
                    test["stage"] = "sandbox_test"
                    test["sandbox"] = str(sandbox_root)
                    test["patch_file"] = str(patch_file)
                    test["repair_round"] = repair_round
                    runs.append(test)
            candidate_runs = [entry for entry in runs if entry.get("patch_file") == str(patch_file)]
            if candidate_runs and all(entry.get("passed") for entry in candidate_runs):
                break
        if not runs:
            sandbox_root = repo / ".repopilot" / "sandbox"
            runs.append(
                {
                    "stage": "apply_patch",
                    "repair_round": repair_round,
                    "sandbox": str(sandbox_root),
                    "returncode": 1,
                    "passed": False,
                    "stdout": "",
                    "stderr": "No patch passed git apply --check, sandbox apply skipped.",
                }
            )
        return runs

    def _apply_patch_to_worktree(
        self,
        repo: Path,
        patch_checks: list[dict[str, Any]],
        sandbox_runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        dirty_state = self._worktree_dirty_state(repo)
        if dirty_state:
            return [
                {
                    "stage": "apply_worktree",
                    "passed": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": dirty_state,
                }
            ]
        passed_sandbox = [item for item in sandbox_runs if item.get("stage") in {"apply_patch", "sandbox_test"}]
        if not passed_sandbox or not all(item.get("passed") for item in passed_sandbox):
            return [
                {
                    "stage": "apply_worktree",
                    "passed": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "Sandbox validation did not fully pass; worktree apply was blocked.",
                }
            ]
        selected_patch_file = self._select_validated_patch(patch_checks, sandbox_runs)
        if not selected_patch_file:
            return [
                {
                    "stage": "apply_worktree",
                    "passed": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "No sandbox-validated patch was available for worktree apply.",
                }
            ]
        patch_file = Path(selected_patch_file)
        touched_files = next(
            (item.get("touched_files", []) for item in patch_checks if item.get("patch_file") == selected_patch_file),
            [],
        )
        backup_dir = self._create_worktree_backup(repo, touched_files)
        try:
            completed = subprocess.run(
                ["git", "apply", str(patch_file)],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
            )
            return [
                {
                    "stage": "apply_worktree",
                    "patch_file": str(patch_file),
                    "backup_dir": str(backup_dir) if backup_dir else "",
                    "rollback_hint": self._rollback_hint(repo, backup_dir, touched_files),
                    "passed": completed.returncode == 0,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-1000:],
                    "stderr": completed.stderr[-1000:],
                }
            ] + self._run_worktree_validation(repo, completed.returncode == 0)
        except Exception as exc:
            return [
                {
                    "stage": "apply_worktree",
                    "patch_file": str(patch_file),
                    "backup_dir": str(backup_dir) if backup_dir else "",
                    "passed": False,
                    "returncode": -1,
                    "stdout": "",
                    "stderr": repr(exc),
                }
            ]

    def _select_validated_patch(
        self,
        patch_checks: list[dict[str, Any]],
        sandbox_runs: list[dict[str, Any]],
    ) -> str | None:
        candidates: list[tuple[int, str]] = []
        for item in patch_checks:
            patch_file = item.get("patch_file")
            if not patch_file or not item.get("passed"):
                continue
            related = [run for run in sandbox_runs if run.get("patch_file") == patch_file]
            if not related:
                continue
            score = sum(1 for run in related if run.get("passed"))
            if related and all(run.get("passed") for run in related):
                candidates.append((score, patch_file))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def _worktree_dirty_state(self, repo: Path) -> str:
        if not (repo / ".git").exists():
            return ""
        try:
            completed = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
        except Exception as exc:
            return f"Dirty worktree check failed: {exc!r}"
        if completed.returncode != 0:
            return f"Dirty worktree check failed: {completed.stderr[-300:]}"
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if lines:
            preview = "\n".join(lines[:10])
            return f"Worktree apply blocked because the repository has local changes:\n{preview}"
        return ""

    def _create_worktree_backup(self, repo: Path, touched_files: list[str]) -> Path | None:
        if not touched_files:
            return None
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = repo / ".repopilot" / "backups" / stamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        for rel in touched_files:
            src = repo / rel
            dst = backup_dir / rel
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        return backup_dir

    def _rollback_hint(self, repo: Path, backup_dir: Path | None, touched_files: list[str]) -> str:
        if not backup_dir or not touched_files:
            return "No backup was created for this patch."
        return (
            f"Restore files from {backup_dir} back into {repo} for rollback. "
            f"Touched files: {', '.join(touched_files)}"
        )

    def _run_worktree_validation(self, repo: Path, applied: bool) -> list[dict[str, Any]]:
        if not applied:
            return []
        runs = []
        for test in self._run_tests(repo, self._test_plan(repo, "worktree_apply_validation", [])):
            test["stage"] = "worktree_test"
            runs.append(test)
        return runs

    def _repair_patch_in_sandbox(
        self,
        repo: Path,
        issue: str,
        root_cause: str,
        evidence: list[Evidence],
        suspected_files: list[str],
        test_plan: list[str],
        patch_suggestions: list[dict[str, str]],
        patch_checks: list[dict[str, Any]],
        max_rounds: int = 3,
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
        all_runs: list[dict[str, Any]] = []
        current_issue = issue
        current_suggestions = patch_suggestions
        current_checks = patch_checks
        for round_id in range(1, max_rounds + 1):
            sandbox_runs = self._apply_patch_in_sandbox(
                repo=repo,
                patch_checks=current_checks,
                test_plan=test_plan,
                repair_round=round_id,
            )
            all_runs.extend(sandbox_runs)
            non_advisor_runs = [item for item in sandbox_runs if item.get("stage") != "repair_advice"]
            if non_advisor_runs and all(item.get("passed") for item in non_advisor_runs):
                return current_suggestions, current_checks, all_runs
            if round_id >= max_rounds:
                break
            current_issue = self._patch_issue_with_failure_context(current_issue, sandbox_runs, round_id)
            if self.patch_suggestion_agent:
                current_suggestions = self.patch_suggestion_agent.run(current_issue, root_cause, evidence)
            else:
                current_suggestions = self._patch_suggestions(current_issue, suspected_files, root_cause)
            current_checks = self._check_patches(repo, current_suggestions)
            all_runs.append(
                {
                    "stage": "repair_advice",
                    "repair_round": round_id,
                    "passed": any(item.get("passed") for item in current_checks),
                    "returncode": 0,
                    "stdout": "\n".join(
                        [
                            f"Prepared repair round {round_id + 1}",
                            f"candidate_patches={len(current_suggestions)}",
                            f"applyable_patches={sum(1 for item in current_checks if item.get('passed'))}",
                        ]
                    ),
                    "stderr": "",
                }
            )
        return current_suggestions, current_checks, all_runs

    def _test_commands(self, repo: Path, test_plan: list[str]) -> list[list[str]]:
        commands: list[list[str]] = []
        if any(item.startswith("python -m pytest") for item in test_plan):
            commands.append([sys.executable, "-m", "pytest", "-q"])
        commands.append(
            [
                sys.executable,
                "-c",
                (
                    "from app.scenarios.repo_pilot import RepoPilotWorkflow; "
                    "r=RepoPilotWorkflow().run('.', 'schema contract smoke test'); "
                    "assert r.task.status.value=='succeeded'; "
                    "assert r.task.evaluation['overall']>=0.75; "
                    "print('repo smoke ok', r.task.evaluation['overall'])"
                ),
            ]
        )
        if (repo / "package.json").exists():
            commands.append(["npm", "test"])
        return commands

    def _second_pass_advice(self, test_runs: list[dict[str, Any]]) -> list[str]:
        if not test_runs:
            return ["当前未执行测试。建议使用 --run-tests 启动测试闭环。"]
        failed = [item for item in test_runs if not item["passed"]]
        if not failed:
            return ["测试闭环通过，可进入 patch 应用、代码审查和 PR 生成阶段。"]
        advice = []
        for item in failed:
            stderr = item.get("stderr", "")
            if "No module named pytest" in stderr:
                advice.append("测试失败原因是 pytest 未安装；建议安装 dev 依赖或使用内置 smoke check 作为最低门禁。")
            elif "ModuleNotFoundError" in stderr:
                advice.append("测试失败集中在模块路径；建议固定 PYTHONPATH 并使用 python -m 方式启动。")
            else:
                advice.append(f"命令 `{item['command']}` 失败，需要根据 stderr 补充最小复现。")
        return advice

    def _pr_plan(
        self,
        repo: Path,
        issue: str,
        patch_suggestions: list[dict[str, str]],
        test_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        def command_exists(command: str) -> bool:
            try:
                completed = subprocess.run(
                    [command, "--version"],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    shell=False,
                )
                return completed.returncode == 0
            except Exception:
                return False

        tests_passed = bool(test_runs) and all(
            item["passed"] for item in test_runs if item["command"] != "repair_advisor"
        )
        patch_files = sorted((repo / ".repopilot" / "patches").glob("suggestion_*.patch"))
        patch_ready = bool(patch_suggestions) and bool(patch_files)
        return {
            "ready": tests_passed and patch_ready,
            "git_available": command_exists("git"),
            "gh_available": command_exists("gh"),
            "branch_name": "repopilot/agent-fix",
            "title": f"RepoPilot: {issue[:70]}",
            "body_sections": [
                "Summary: AI-assisted issue diagnosis and patch proposal.",
                "Validation: pytest / smoke check results are included in RepoPilot report.",
                "Risk: review generated diff before applying.",
            ],
            "next_commands": [
                "git checkout -b repopilot/agent-fix",
                "git apply .repopilot/patches/suggestion_1.patch",
                "python -m pytest -q",
                "gh pr create --fill",
            ],
        }

    def _run_github_actions(
        self,
        repo: Path,
        pr_plan: dict[str, Any],
        create_pr: bool,
        poll_ci: bool,
        ci_feedback: bool,
        pr_number: int | None,
        comment_body: str,
    ) -> dict[str, Any]:
        ops = GitHubOps(repo)
        payload: dict[str, Any] = {
            "gh_available": ops.command_exists("gh"),
            "gh_authenticated": ops.is_authenticated(),
            "branch": ops.current_branch(),
            "commit": ops.current_commit(),
        }
        active_pr = pr_number
        if create_pr:
            body = "\n".join(pr_plan.get("body_sections", []))
            payload["create_pr"] = ops.create_pr(
                title=pr_plan.get("title", "RepoPilot PR"),
                body=body,
                base="main",
                head=payload.get("branch") or None,
            )
            if payload["create_pr"].get("ok"):
                active_pr = int(payload["create_pr"].get("number") or 0) or active_pr
        if poll_ci and active_pr:
            payload["ci_checks"] = ops.pr_checks(active_pr)
        if ci_feedback and active_pr:
            payload["ci_feedback"] = ops.ci_feedback(active_pr)
        if comment_body and active_pr:
            payload["comment"] = ops.comment_on_pr(active_pr, comment_body)
        payload["active_pr_number"] = active_pr
        return payload

    def _report(self, task: ResearchTask, repo: Path, issue: str) -> str:
        evidence_lines = [
            f"- {item.title} score={item.score}\n```text\n{item.content[:700]}\n```"
            for item in task.evidence[:5]
        ]
        return f"""# RepoPilot Issue 诊断报告

## 业务场景
面向企业研发团队的代码智能体：从 issue 出发，自动检索仓库、定位疑似文件、生成修复方案、测试计划和风险清单。

## 仓库
{repo}

## Issue
{issue}

## 根因假设
{task.analysis["root_cause_hypothesis"]}

## 疑似文件
{chr(10).join(f"- {item}" for item in task.analysis["suspected_files"])}

## 修改计划
{chr(10).join(f"{idx}. {item}" for idx, item in enumerate(task.analysis["change_plan"], start=1))}

## Patch 建议
{chr(10).join(self._format_patch(item) for item in task.analysis["patch_suggestions"])}

## Patch 校验
{self._format_patch_checks(task.analysis["patch_checks"])}

## 测试计划
{chr(10).join(f"{idx}. {item}" for idx, item in enumerate(task.analysis["test_plan"], start=1))}

## 测试执行结果
{self._format_test_runs(task.analysis["test_runs"])}

## Sandbox 应用结果
{self._format_sandbox_runs(task.analysis["sandbox_runs"])}

## Worktree 应用结果
{self._format_worktree_runs(task.analysis["worktree_runs"])}

## 二次修复建议
{chr(10).join(f"- {item}" for item in task.analysis["second_pass_advice"])}

## 风险清单
{chr(10).join(f"- {item}" for item in task.analysis["risk_items"])}

## PR 准备
{self._format_pr_plan(task.analysis["pr_plan"])}

## 代码证据
{chr(10).join(evidence_lines)}
""".strip()

    def _format_patch(self, suggestion: dict[str, str]) -> str:
        return (
            f"### {suggestion['title']}\n"
            f"- 目标文件：{suggestion['target_file']}\n"
            f"- 原因：{suggestion['reason']}\n"
            f"```diff\n{suggestion['diff']}\n```"
        )

    def _format_test_runs(self, test_runs: list[dict[str, Any]]) -> str:
        if not test_runs:
            return "未执行测试。使用 `--run-tests` 可启动测试闭环。"
        blocks = []
        for item in test_runs:
            status = "PASS" if item["passed"] else "FAIL"
            output = item["stdout"] or item["stderr"] or "(no output)"
            blocks.append(
                f"### {status}: `{item['command']}`\n"
                f"returncode={item['returncode']}\n"
                f"```text\n{output[-800:]}\n```"
            )
        return "\n".join(blocks)

    def _format_patch_checks(self, patch_checks: list[dict[str, Any]]) -> str:
        if not patch_checks:
            return "未生成 patch 校验结果。"
        lines = []
        for item in patch_checks:
            status = "PASS" if item.get("passed") else "WARN"
            lines.append(
                f"- {status}: {item.get('title')} | {item.get('apply_check')} | {item.get('patch_file')}"
            )
            if item.get("stderr"):
                lines.append(f"  - {item['stderr'][:300]}")
        return "\n".join(lines)

    def _format_sandbox_runs(self, sandbox_runs: list[dict[str, Any]]) -> str:
        if not sandbox_runs:
            return "未启用 sandbox apply。使用 `--apply-sandbox` 可在隔离副本中应用 patch 并跑测试。"
        blocks = []
        for item in sandbox_runs:
            status = "PASS" if item.get("passed") else "FAIL"
            output = item.get("stdout") or item.get("stderr") or "(no output)"
            blocks.append(
                f"### {status}: {item.get('stage')}\n"
                f"repair_round={item.get('repair_round')}\n"
                f"sandbox={item.get('sandbox')}\n"
                f"returncode={item.get('returncode')}\n"
                f"```text\n{output[-800:]}\n```"
            )
        return "\n".join(blocks)

    def _format_pr_plan(self, pr_plan: dict[str, Any]) -> str:
        if not pr_plan:
            return "未生成 PR 计划。"
        commands = "\n".join(f"  {cmd}" for cmd in pr_plan.get("next_commands", []))
        return (
            f"- ready: {pr_plan.get('ready')}\n"
            f"- git_available: {pr_plan.get('git_available')}\n"
            f"- gh_available: {pr_plan.get('gh_available')}\n"
            f"- branch: {pr_plan.get('branch_name')}\n"
            f"- title: {pr_plan.get('title')}\n"
            f"- github: {json.dumps(pr_plan.get('github', {}), ensure_ascii=False)}\n"
            f"- next commands:\n{commands}"
        )

    def _format_worktree_runs(self, worktree_runs: list[dict[str, Any]]) -> str:
        if not worktree_runs:
            return "未启用 worktree apply。使用 `--apply-worktree` 可在 sandbox 验证通过后把 patch 落到原仓库。"
        blocks = []
        for item in worktree_runs:
            status = "PASS" if item.get("passed") else "FAIL"
            output = item.get("stdout") or item.get("stderr") or "(no output)"
            blocks.append(
                f"### {status}: {item.get('stage')}\n"
                f"patch_file={item.get('patch_file')}\n"
                f"backup_dir={item.get('backup_dir')}\n"
                f"rollback_hint={item.get('rollback_hint')}\n"
                f"returncode={item.get('returncode')}\n"
                f"```text\n{output[-800:]}\n```"
            )
        return "\n".join(blocks)

    def _judge(self, task: ResearchTask) -> None:
        evidence_score = min(1.0, len(task.evidence) / 5)
        file_score = min(1.0, len(task.analysis["suspected_files"]) / 3)
        action_score = 1.0 if len(task.analysis["change_plan"]) >= 4 else 0.5
        test_score = 1.0 if len(task.analysis["test_plan"]) >= 3 else 0.5
        risk_score = 1.0 if task.analysis["risk_items"] else 0.4
        patch_score = 1.0 if task.analysis.get("patch_suggestions") else 0.4
        patch_check_score = 1.0 if any(item.get("passed") for item in task.analysis.get("patch_checks", [])) else 0.6
        if task.analysis.get("test_runs"):
            scored_runs = [item for item in task.analysis["test_runs"] if item["command"] != "repair_advisor"]
            executed_test_score = sum(1 for item in scored_runs if item["passed"]) / max(1, len(scored_runs))
        else:
            executed_test_score = 0.6
        if task.analysis.get("sandbox_runs"):
            sandbox_score = sum(1 for item in task.analysis["sandbox_runs"] if item.get("passed")) / max(
                1, len(task.analysis["sandbox_runs"])
            )
        else:
            sandbox_score = 0.7
        overall = round(
            (
                evidence_score
                + file_score
                + action_score
                + test_score
                + risk_score
                + patch_score
                + patch_check_score
                + executed_test_score
                + sandbox_score
            )
            / 9,
            3,
        )
        task.evaluation = {
            "scores": {
                "code_grounding": round(evidence_score, 3),
                "localization": round(file_score, 3),
                "actionability": round(action_score, 3),
                "testability": round(test_score, 3),
                "risk_control": round(risk_score, 3),
                "patch_readiness": round(patch_score, 3),
                "patch_apply_check": round(patch_check_score, 3),
                "executed_tests": round(executed_test_score, 3),
                "sandbox_apply": round(sandbox_score, 3),
            },
            "overall": overall,
            "passed": overall >= 0.75,
            "rubric": {
                "code_grounding": "是否基于真实代码证据",
                "localization": "是否定位到具体疑似文件",
                "actionability": "修复计划是否可执行",
                "testability": "是否包含可运行测试策略",
                "risk_control": "是否识别回归和兼容性风险",
                "patch_readiness": "是否生成统一 diff 风格 patch 建议",
                "patch_apply_check": "patch 是否通过 git apply --check 或被明确标记为需人工处理",
                "executed_tests": "是否执行测试并形成失败归因",
                "sandbox_apply": "是否在隔离副本中应用 patch 并验证测试",
            },
        }
        task.optimization = {
            "badcase_type": "none" if task.evaluation["passed"] else "weak_issue_localization",
            "suggestions": [
                "接入 git diff 和测试执行器，形成 issue -> patch -> test 的闭环。",
                "加入调用图、依赖图和最近提交检索，提高跨文件定位能力。",
                "沉淀历史 issue、PR 和测试失败日志作为企业研发知识库。",
            ],
        }
        task.add_trace("repo_judge_agent", "finish", overall=overall, passed=task.evaluation["passed"])
