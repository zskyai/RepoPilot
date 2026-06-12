from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.run_store import RunStore
from app.scenarios.repo_pilot import RepoPilotWorkflow
from app.scenarios.repo_pilot_graph import RepoPilotGraphWorkflow


def _interactive_args() -> argparse.Namespace:
    print("RepoPilot Interactive Mode")
    print("=" * 40)
    repo = input("Repository path [.]: ").strip() or "."
    print("Describe the issue. Finish with an empty line:")
    lines: list[str] = []
    while True:
        line = input()
        if not line:
            break
        lines.append(line)
    issue = "\n".join(lines).strip() or "Fix a repository issue with minimal safe changes."
    mode = input("Mode [diagnose/patch/repair/deploy] (default: patch): ").strip().lower() or "patch"
    use_llm = input("Use LLM? [Y/n]: ").strip().lower() != "n"
    graph = input("Use graph workflow? [Y/n]: ").strip().lower() != "n"
    ns = argparse.Namespace()
    ns.repo = repo
    ns.issue = issue
    ns.json = False
    ns.run_tests = mode in {"repair", "deploy"}
    ns.use_llm = use_llm
    ns.require_llm = False
    ns.graph = graph
    ns.apply_sandbox = mode in {"repair", "deploy"}
    ns.apply_worktree = mode == "deploy"
    ns.create_pr = mode == "deploy"
    ns.poll_ci = False
    ns.ci_feedback = False
    ns.auto_repair_ci = False
    ns.auto_sync_repair = False
    ns.no_memory = False
    ns.no_save_memory = False
    ns.pr_number = None
    ns.comment_body = ""
    ns.no_approval = False
    ns.resume_run_id = ""
    ns.save_run = True
    ns.interactive = True
    return ns


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RepoPilot software engineering agent scenario.")
    parser.add_argument("--repo", default=".", help="Repository path to inspect.")
    parser.add_argument(
        "--issue",
        default="Fix a repository issue with minimal safe changes.",
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
    parser.add_argument("--ci-feedback", action="store_true", help="Fetch structured CI failure feedback for repair loops.")
    parser.add_argument("--auto-repair-ci", action="store_true", help="Auto-generate a repair comment from CI failures.")
    parser.add_argument("--auto-sync-repair", action="store_true", help="Sync validated auto-repair patches back to the PR branch.")
    parser.add_argument("--no-memory", action="store_true", help="Disable retrieval from RepoPilot long-term memory.")
    parser.add_argument("--no-save-memory", action="store_true", help="Disable saving this run into RepoPilot long-term memory.")
    parser.add_argument("--pr-number", type=int, default=None, help="Existing PR number for CI polling or commenting.")
    parser.add_argument("--comment-body", default="", help="Write a comment back to the PR with gh CLI.")
    parser.add_argument("--no-approval", action="store_true", help="Disable human approval gates for mutation actions.")
    parser.add_argument("--resume-run-id", default="", help="Resume a graph thread id / run id from the latest checkpoint metadata.")
    parser.add_argument("--save-run", action="store_true", help="Persist run payload to .repopilot/runs.sqlite3.")
    parser.add_argument("--interactive", action="store_true", help="Guided interactive mode; no need to remember flags.")
    args = parser.parse_args()
    if args.interactive:
        args = _interactive_args()

    workflow_cls = RepoPilotGraphWorkflow if args.graph else RepoPilotWorkflow
    run_kwargs = {
        "run_tests": args.run_tests,
        "apply_sandbox": args.apply_sandbox,
        "apply_worktree": args.apply_worktree,
        "create_pr": args.create_pr,
        "poll_ci": args.poll_ci,
        "ci_feedback": args.ci_feedback,
        "auto_repair_ci": args.auto_repair_ci,
        "auto_sync_repair": args.auto_sync_repair,
        "use_memory": not args.no_memory,
        "save_memory": not args.no_save_memory,
        "pr_number": args.pr_number,
        "comment_body": args.comment_body,
    }
    if args.graph:
        run_kwargs["require_approval"] = not args.no_approval
        run_kwargs["resume_run_id"] = args.resume_run_id

    result = workflow_cls(use_llm=args.use_llm, require_llm=args.require_llm).run(
        Path(args.repo),
        args.issue,
        **run_kwargs,
    )
    if args.save_run:
        run_id = RunStore(Path(args.repo) / ".repopilot" / "runs.sqlite3").save(result.to_dict())
        result.task.analysis["saved_run_id"] = run_id
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    if getattr(args, "interactive", False):
        selected = ((result.task.analysis.get("selected_patch") or {}).get("selected") or {})
        decision = result.task.analysis.get("decision_tree") or {}
        print("\n## Quick Summary")
        print(f"overall={result.task.evaluation.get('overall')} passed={result.task.evaluation.get('passed')}")
        print(f"selected_patch={selected.get('title', '')}")
        if decision.get("challenge"):
            print(
                "challenge="
                f"{decision['challenge'].get('recommendation')} "
                f"robustness={decision['challenge'].get('robustness_score')}"
            )

    print(result.task.report)
    print("\n## Evaluation")
    print(json.dumps(result.task.evaluation, ensure_ascii=False, indent=2))
    print("\n## Optimization")
    print(json.dumps(result.task.optimization, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
