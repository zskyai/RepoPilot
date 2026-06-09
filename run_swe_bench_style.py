from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.eval.swe_bench_runner import SWEBenchStyleRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SWE-bench style RepoPilot evaluation cases.")
    parser.add_argument("--cases", required=True, help="JSON or JSONL cases file.")
    parser.add_argument("--work-dir", default=".repopilot/swe_bench_runs")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--require-llm", action="store_true")
    parser.add_argument("--no-apply-sandbox", action="store_true")
    parser.add_argument("--max-cases", type=int, default=None)
    args = parser.parse_args()

    runner = SWEBenchStyleRunner(Path(args.work_dir))
    cases = runner.load_cases(args.cases)
    summary = runner.run_suite(
        cases,
        use_llm=args.use_llm,
        require_llm=args.require_llm,
        apply_sandbox=not args.no_apply_sandbox,
        max_cases=args.max_cases,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
