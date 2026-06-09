from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.run_store import RunStore
from app.scenarios.repo_pilot import RepoPilotWorkflow
from app.scenarios.repo_pilot_graph import RepoPilotGraphWorkflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RepoPilot software engineering agent scenario.")
    parser.add_argument("--repo", default=".", help="Repository path to inspect.")
    parser.add_argument(
        "--issue",
        default="运行 API 服务时出现 No module named app，怀疑是启动目录或包路径配置问题。",
        help="Bug report, feature request, or engineering issue.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    parser.add_argument("--run-tests", action="store_true", help="Run safe local tests and smoke checks.")
    parser.add_argument("--use-llm", action="store_true", help="Use real OpenAI-compatible LLM agents.")
    parser.add_argument("--require-llm", action="store_true", help="Fail if LLM_BASE_URL/API key are not configured.")
    parser.add_argument("--graph", action="store_true", help="Use StateGraph Plan-Act-Verify-Repair architecture.")
    parser.add_argument("--apply-sandbox", action="store_true", help="Apply patch in an isolated sandbox copy and run tests.")
    parser.add_argument(
        "--apply-worktree",
        action="store_true",
        help="Apply patch to the original repository only after sandbox validation passes.",
    )
    parser.add_argument("--create-pr", action="store_true", help="Create a GitHub pull request with gh CLI.")
    parser.add_argument("--poll-ci", action="store_true", help="Fetch CI checks for the active PR with gh CLI.")
    parser.add_argument("--pr-number", type=int, default=None, help="Existing PR number for CI polling or commenting.")
    parser.add_argument("--comment-body", default="", help="Write a comment back to the PR with gh CLI.")
    parser.add_argument("--save-run", action="store_true", help="Persist run payload to .repopilot/runs.sqlite3.")
    args = parser.parse_args()

    workflow_cls = RepoPilotGraphWorkflow if args.graph else RepoPilotWorkflow
    result = workflow_cls(use_llm=args.use_llm, require_llm=args.require_llm).run(
        Path(args.repo),
        args.issue,
        run_tests=args.run_tests,
        apply_sandbox=args.apply_sandbox,
        apply_worktree=args.apply_worktree,
        create_pr=args.create_pr,
        poll_ci=args.poll_ci,
        pr_number=args.pr_number,
        comment_body=args.comment_body,
    )
    if args.save_run:
        run_id = RunStore(Path(args.repo) / ".repopilot" / "runs.sqlite3").save(result.to_dict())
        result.task.analysis["saved_run_id"] = run_id
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.task.report)
        print("\n## 自动评测")
        print(json.dumps(result.task.evaluation, ensure_ascii=False, indent=2))
        print("\n## 优化建议")
        print(json.dumps(result.task.optimization, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
