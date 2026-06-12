from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.run_store import RunStore
from app.scenarios.repo_pilot_graph import RepoPilotGraphWorkflow


@dataclass
class SWEBenchCase:
    instance_id: str
    repo: str
    issue: str
    base_commit: str = ""
    test_command: str = ""
    setup_commands: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    expected_paths: list[str] = field(default_factory=list)
    expected_repair_context: bool = False
    expected_multi_file: bool = False


class SWEBenchStyleRunner:
    def __init__(self, work_dir: str | Path) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def load_cases(self, path: str | Path) -> list[SWEBenchCase]:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in text.splitlines() if line.strip()] if p.suffix == ".jsonl" else json.loads(text)
        return [
            SWEBenchCase(
                instance_id=str(item.get("instance_id") or item.get("name") or index),
                repo=str(item["repo"]),
                issue=str(item.get("issue") or item.get("problem_statement") or ""),
                base_commit=str(item.get("base_commit") or ""),
                test_command=str(item.get("test_command") or ""),
                setup_commands=list(item.get("setup_commands") or []),
                tags=list(item.get("tags") or []),
                expected_paths=list(item.get("expected_paths") or []),
                expected_repair_context=bool(item.get("expected_repair_context", False)),
                expected_multi_file=bool(item.get("expected_multi_file", False)),
            )
            for index, item in enumerate(rows, start=1)
        ]

    def run_suite(
        self,
        cases: list[SWEBenchCase],
        *,
        use_llm: bool = False,
        require_llm: bool = False,
        apply_sandbox: bool = True,
        max_cases: int | None = None,
    ) -> dict[str, Any]:
        results = []
        for case in cases[: max_cases or len(cases)]:
            results.append(
                self.run_case(
                    case,
                    use_llm=use_llm,
                    require_llm=require_llm,
                    apply_sandbox=apply_sandbox,
                )
            )
        passed = [item for item in results if item.get("passed")]
        public_summary = self._public_eval_summary(results)
        return {
            "case_count": len(results),
            "pass_at_1": round(len(passed) / max(1, len(results)), 3),
            "adjusted_pass_at_1": round(sum(1 for item in results if item.get("adjusted_passed")) / max(1, len(results)), 3),
            "average_elapsed_seconds": round(
                sum(item.get("elapsed_seconds", 0.0) for item in results) / max(1, len(results)),
                2,
            ),
            "public_eval": public_summary,
            "markdown_table": self._markdown_table(results),
            "public_markdown": self._public_markdown(results, public_summary),
            "results": results,
        }

    def run_case(
        self,
        case: SWEBenchCase,
        *,
        use_llm: bool,
        require_llm: bool,
        apply_sandbox: bool,
    ) -> dict[str, Any]:
        started = time.time()
        repo_path = self._prepare_repo(case)
        setup = [self._run_shell(repo_path, command, timeout=180) for command in case.setup_commands]
        workflow = RepoPilotGraphWorkflow(use_llm=use_llm, require_llm=require_llm)
        result = workflow.run(
            repo_path,
            case.issue,
            run_tests=bool(case.test_command),
            apply_sandbox=apply_sandbox,
            save_memory=False,
        )
        external_test = self._run_shell(repo_path, case.test_command, timeout=180) if case.test_command else None
        payload = result.to_dict()
        run_id = RunStore(repo_path / ".repopilot" / "runs.sqlite3").save(payload)
        analysis = payload.get("analysis", {}) or {}
        suspected_files = list(analysis.get("suspected_files") or [])
        repair_context = analysis.get("repair_context") or {}
        repair_journal = analysis.get("repair_journal") or []
        coordination_plan = analysis.get("coordination_plan") or []
        expected_path_recall = self._expected_path_recall(case.expected_paths, suspected_files)
        cross_file_localized = self._matches_expected_paths(case.expected_paths, suspected_files)
        repair_context_used = bool(repair_context) or bool(repair_journal)
        selected_patch = ((analysis.get("selected_patch") or {}).get("selected") or {})
        selected_patch_files = list(selected_patch.get("touched_files") or [])
        coordination_depth = max((len(item.get("related_files", []) or []) for item in coordination_plan), default=0)
        bundle_type = str((analysis.get("atomic_change_bundle") or {}).get("bundle_type") or "")
        repo_snapshot_exact = bool(case.base_commit and (repo_path / ".git").exists())
        external_test_credit = self._external_test_credit(external_test)
        environment_limited = external_test is not None and external_test_credit > 0.0 and not external_test.get("passed", False)
        passed = bool(payload.get("evaluation", {}).get("passed")) and (external_test is None or external_test.get("returncode") == 0)
        adjusted_passed = bool(payload.get("evaluation", {}).get("passed")) and (
            external_test is None or external_test_credit >= 0.5
        )
        return {
            "instance_id": case.instance_id,
            "repo_path": str(repo_path),
            "base_commit": case.base_commit,
            "passed": passed,
            "adjusted_passed": adjusted_passed,
            "overall": payload.get("evaluation", {}).get("overall"),
            "elapsed_seconds": round(time.time() - started, 2),
            "setup": setup,
            "external_test": external_test,
            "external_test_credit": external_test_credit,
            "environment_limited": environment_limited,
            "saved_run_id": run_id,
            "graph_run_id": payload.get("analysis", {}).get("graph_run_id"),
            "trace_db_path": payload.get("analysis", {}).get("trace_db_path"),
            "tags": case.tags,
            "expected_paths": case.expected_paths,
            "expected_repair_context": case.expected_repair_context,
            "expected_multi_file": case.expected_multi_file,
            "suspected_files": suspected_files[:8],
            "cross_file_localized": cross_file_localized,
            "expected_path_recall": expected_path_recall,
            "repair_context_used": repair_context_used,
            "repair_rounds": int(analysis.get("repair_rounds", 0) or 0),
            "repair_journal_length": len(repair_journal),
            "selected_patch_files": selected_patch_files[:6],
            "selected_patch_file": str(selected_patch.get("patch_file") or ""),
            "selected_patch": selected_patch,
            "selected_patch_multi_file": len(selected_patch_files) > 1,
            "coordination_depth": coordination_depth,
            "bundle_type": bundle_type,
            "repo_snapshot_exact": repo_snapshot_exact,
            "score_breakdown": payload.get("evaluation", {}).get("scores", {}),
        }

    def _prepare_repo(self, case: SWEBenchCase) -> Path:
        target = self.work_dir / case.instance_id
        if target.exists():
            shutil.rmtree(target)
        source = Path(case.repo)
        if source.exists():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    ".repopilot",
                    "__pycache__",
                    ".pytest_cache",
                    "node_modules",
                ),
            )
        else:
            subprocess.run(["git", "clone", case.repo, str(target)], check=True, timeout=240, shell=False)
        if case.base_commit:
            subprocess.run(["git", "checkout", case.base_commit], cwd=target, check=True, timeout=60, shell=False)
        return target

    def _run_shell(self, repo: Path, command: str, timeout: int) -> dict[str, Any]:
        if not command:
            return {"command": "", "returncode": 0, "stdout": "", "stderr": ""}
        command = self._normalize_python_command(command)
        completed = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        }

    def _normalize_python_command(self, command: str) -> str:
        stripped = command.strip()
        if stripped == "python":
            return f'"{sys.executable}"'
        if stripped.startswith("python "):
            return f'"{sys.executable}" {stripped[len("python "):]}'
        return command

    def _markdown_table(self, results: list[dict[str, Any]]) -> str:
        lines = [
            "| case | strict | adjusted | overall | elapsed_s | repair_rounds | path_recall | trace_db |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for item in results:
            lines.append(
                "| {case} | {passed} | {adjusted} | {overall} | {elapsed} | {repair_rounds} | {path_recall} | `{trace}` |".format(
                    case=item.get("instance_id", ""),
                    passed="yes" if item.get("passed") else "no",
                    adjusted="yes" if item.get("adjusted_passed") else "no",
                    overall=item.get("overall", ""),
                    elapsed=item.get("elapsed_seconds", ""),
                    repair_rounds=item.get("repair_rounds", 0),
                    path_recall=item.get("expected_path_recall", 0.0),
                    trace=item.get("trace_db_path", ""),
                )
            )
        return "\n".join(lines)

    def _matches_expected_paths(self, expected_paths: list[str], suspected_files: list[str]) -> bool:
        if not expected_paths:
            return False
        normalized = {str(item).replace("\\", "/") for item in suspected_files}
        return all(str(path).replace("\\", "/") in normalized for path in expected_paths)

    def _expected_path_recall(self, expected_paths: list[str], suspected_files: list[str]) -> float:
        if not expected_paths:
            return 0.0
        normalized = {str(item).replace("\\", "/") for item in suspected_files}
        matched = sum(1 for path in expected_paths if str(path).replace("\\", "/") in normalized)
        return round(matched / max(1, len(expected_paths)), 3)

    def _external_test_credit(self, external_test: dict[str, Any] | None) -> float:
        if external_test is None:
            return 1.0
        if external_test.get("passed"):
            return 1.0
        output = f"{external_test.get('stdout', '')}\n{external_test.get('stderr', '')}".lower()
        dependency_signals = [
            "no module named pytest",
            "modulenotfounderror: no module named 'pytest'",
            "no module named text_unidecode",
            "no module named unidecode",
        ]
        if any(signal in output for signal in dependency_signals):
            return 0.5
        return 0.0

    def _public_eval_summary(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        cross_file_cases = [item for item in results if item.get("expected_multi_file") or "cross_file" in (item.get("tags") or [])]
        repair_context_cases = [item for item in results if item.get("expected_repair_context") or "repair_context" in (item.get("tags") or [])]
        localized_cases = [item for item in results if item.get("expected_paths")]
        approximate_cases = [item for item in results if item.get("base_commit") and not item.get("repo_snapshot_exact")]
        return {
            "strict_pass_at_1": round(sum(1 for item in results if item.get("passed")) / max(1, len(results)), 3),
            "env_adjusted_pass_at_1": round(sum(1 for item in results if item.get("adjusted_passed")) / max(1, len(results)), 3),
            "average_overall": round(sum(float(item.get("overall") or 0.0) for item in results) / max(1, len(results)), 3),
            "average_elapsed_seconds": round(sum(float(item.get("elapsed_seconds") or 0.0) for item in results) / max(1, len(results)), 2),
            "cross_file_case_count": len(cross_file_cases),
            "cross_file_pass_rate": round(sum(1 for item in cross_file_cases if item.get("adjusted_passed")) / max(1, len(cross_file_cases)), 3),
            "expected_path_hit_rate": round(sum(1 for item in localized_cases if item.get("cross_file_localized")) / max(1, len(localized_cases)), 3),
            "average_expected_path_recall": round(sum(float(item.get("expected_path_recall") or 0.0) for item in localized_cases) / max(1, len(localized_cases)), 3),
            "repair_context_case_count": len(repair_context_cases),
            "repair_context_usage_rate": round(sum(1 for item in repair_context_cases if item.get("repair_context_used")) / max(1, len(repair_context_cases)), 3),
            "average_repair_rounds": round(sum(float(item.get("repair_rounds") or 0.0) for item in results) / max(1, len(results)), 2),
            "multi_file_patch_rate": round(sum(1 for item in results if item.get("selected_patch_multi_file")) / max(1, len(results)), 3),
            "environment_limited_case_count": sum(1 for item in results if item.get("environment_limited")),
            "approximate_repo_case_count": len(approximate_cases),
            "official_reproducibility": "approximate" if approximate_cases else "exact_or_local",
        }

    def _public_markdown(self, results: list[dict[str, Any]], public_summary: dict[str, Any]) -> str:
        lines = [
            "## RepoPilot Public Eval Snapshot",
            "",
            f"- strict_pass@1: `{public_summary.get('strict_pass_at_1')}`",
            f"- env_adjusted_pass@1: `{public_summary.get('env_adjusted_pass_at_1')}`",
            f"- average_overall: `{public_summary.get('average_overall')}`",
            f"- average_elapsed_seconds: `{public_summary.get('average_elapsed_seconds')}`",
            f"- cross_file_pass_rate: `{public_summary.get('cross_file_pass_rate')}`",
            f"- expected_path_hit_rate: `{public_summary.get('expected_path_hit_rate')}`",
            f"- average_expected_path_recall: `{public_summary.get('average_expected_path_recall')}`",
            f"- repair_context_usage_rate: `{public_summary.get('repair_context_usage_rate')}`",
            f"- multi_file_patch_rate: `{public_summary.get('multi_file_patch_rate')}`",
            f"- environment_limited_case_count: `{public_summary.get('environment_limited_case_count')}`",
            f"- approximate_repo_case_count: `{public_summary.get('approximate_repo_case_count')}`",
            f"- official_reproducibility: `{public_summary.get('official_reproducibility')}`",
            "",
        ]
        if public_summary.get("approximate_repo_case_count"):
            lines.extend(
                [
                    "> Warning: some benchmark repos were local snapshots instead of exact base commits.",
                    "> Treat those results as approximate public-eval signals, not strict official SWE-bench reproduction.",
                    "",
                ]
            )
        lines.append("### Bucketed Cases")
        for item in results:
            tags = ", ".join(item.get("tags") or [])
            lines.append(
                f"- `{item.get('instance_id')}` strict={item.get('passed')} adjusted={item.get('adjusted_passed')} "
                f"overall={item.get('overall')} repair_rounds={item.get('repair_rounds')} "
                f"path_recall={item.get('expected_path_recall')} tags=[{tags}]"
            )
        return "\n".join(lines)
