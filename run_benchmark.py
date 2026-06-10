from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.core.run_store import RunStore
from app.scenarios.repo_pilot_graph import RepoPilotGraphWorkflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RepoPilot benchmark cases.")
    parser.add_argument("--cases", default="benchmarks/repo_pilot_cases.json")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--require-llm", action="store_true")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--apply-sandbox", action="store_true")
    parser.add_argument("--save-run", action="store_true")
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Run both rule-based baseline and requested mode, then report deltas.",
    )
    parser.add_argument(
        "--compare-multi-candidate",
        action="store_true",
        help="Compare single-candidate mode against multi-candidate patch portfolio mode.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    cases = json.loads((root / args.cases).read_text(encoding="utf-8"))
    if args.compare_multi_candidate:
        single_candidate = run_suite(
            root=root,
            cases=cases,
            use_llm=args.use_llm,
            require_llm=args.require_llm,
            run_tests=args.run_tests,
            apply_sandbox=args.apply_sandbox,
            save_run=False,
            label="single_candidate",
            enable_multi_candidate=False,
        )
        multi_candidate = run_suite(
            root=root,
            cases=cases,
            use_llm=args.use_llm,
            require_llm=args.require_llm,
            run_tests=args.run_tests,
            apply_sandbox=args.apply_sandbox,
            save_run=args.save_run,
            label="multi_candidate",
            enable_multi_candidate=True,
        )
        summary = {
            "single_candidate": single_candidate,
            "multi_candidate": multi_candidate,
            "delta": {
                "pass_rate": round(multi_candidate["pass_rate"] - single_candidate["pass_rate"], 3),
                "average_overall": round(multi_candidate["average_overall"] - single_candidate["average_overall"], 3),
            },
        }
    elif args.compare_baseline:
        baseline = run_suite(
            root=root,
            cases=cases,
            use_llm=False,
            require_llm=False,
            run_tests=args.run_tests,
            apply_sandbox=args.apply_sandbox,
            save_run=False,
            label="baseline",
            enable_multi_candidate=True,
        )
        candidate = run_suite(
            root=root,
            cases=cases,
            use_llm=args.use_llm,
            require_llm=args.require_llm,
            run_tests=args.run_tests,
            apply_sandbox=args.apply_sandbox,
            save_run=args.save_run,
            label="candidate",
            enable_multi_candidate=True,
        )
        summary = {
            "baseline": baseline,
            "candidate": candidate,
            "delta": {
                "pass_rate": round(candidate["pass_rate"] - baseline["pass_rate"], 3),
                "average_overall": round(candidate["average_overall"] - baseline["average_overall"], 3),
            },
        }
    else:
        summary = run_suite(
            root=root,
            cases=cases,
            use_llm=args.use_llm,
            require_llm=args.require_llm,
            run_tests=args.run_tests,
            apply_sandbox=args.apply_sandbox,
            save_run=args.save_run,
            label="suite",
            enable_multi_candidate=True,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def run_suite(
    *,
    root: Path,
    cases: list[dict[str, str]],
    use_llm: bool,
    require_llm: bool,
    run_tests: bool,
    apply_sandbox: bool,
    save_run: bool,
    label: str,
    enable_multi_candidate: bool,
) -> dict[str, object]:
    workflow = RepoPilotGraphWorkflow(
        use_llm=use_llm,
        require_llm=require_llm,
        enable_multi_candidate=enable_multi_candidate,
    )
    results = []
    for idx, case in enumerate(cases, start=1):
        started_at = time.time()
        print(f"[{label} {idx}/{len(cases)}] running {case['name']} on {case['repo']}", flush=True)
        repo = (root / case["repo"]).resolve()
        result = workflow.run(
            repo,
            case["issue"],
            run_tests=run_tests,
            apply_sandbox=apply_sandbox,
        )
        payload = result.to_dict()
        if save_run:
            payload["saved_run_id"] = RunStore(repo / ".repopilot" / "runs.sqlite3").save(payload)
        case_result = {
            "name": case["name"],
            "overall": payload["evaluation"]["overall"],
            "passed": payload["evaluation"]["passed"],
            "scores": payload["evaluation"]["scores"],
            "elapsed_seconds": round(time.time() - started_at, 2),
        }
        results.append(case_result)
        print(
            json.dumps(
                {
                    "label": label,
                    "case": case["name"],
                    "passed": case_result["passed"],
                    "overall": case_result["overall"],
                    "elapsed_seconds": case_result["elapsed_seconds"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return {
        "case_count": len(results),
        "pass_rate": round(sum(1 for item in results if item["passed"]) / max(1, len(results)), 3),
        "average_overall": round(sum(item["overall"] for item in results) / max(1, len(results)), 3),
        "results": results,
    }


if __name__ == "__main__":
    main()
