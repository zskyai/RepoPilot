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
        return {
            "case_count": len(results),
            "pass_at_1": round(len(passed) / max(1, len(results)), 3),
            "average_elapsed_seconds": round(
                sum(item.get("elapsed_seconds", 0.0) for item in results) / max(1, len(results)),
                2,
            ),
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
        passed = bool(payload.get("evaluation", {}).get("passed")) and (
            external_test is None or external_test.get("returncode") == 0
        )
        return {
            "instance_id": case.instance_id,
            "repo_path": str(repo_path),
            "base_commit": case.base_commit,
            "passed": passed,
            "overall": payload.get("evaluation", {}).get("overall"),
            "elapsed_seconds": round(time.time() - started, 2),
            "setup": setup,
            "external_test": external_test,
            "saved_run_id": run_id,
            "graph_run_id": payload.get("analysis", {}).get("graph_run_id"),
            "trace_db_path": payload.get("analysis", {}).get("trace_db_path"),
        }

    def _prepare_repo(self, case: SWEBenchCase) -> Path:
        target = self.work_dir / case.instance_id
        if target.exists():
            shutil.rmtree(target)
        source = Path(case.repo)
        if source.exists():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", ".venv", ".repopilot", "__pycache__"))
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
