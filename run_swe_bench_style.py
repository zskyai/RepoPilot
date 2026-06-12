from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.eval.swe_bench_public import (
    build_official_eval_instructions,
    load_official_swe_bench_cases,
    write_official_predictions,
)
from app.eval.swe_bench_runner import SWEBenchStyleRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SWE-bench style RepoPilot evaluation cases.")
    parser.add_argument("--cases", default="benchmarks/swe_style_cases.json", help="JSON or JSONL cases file.")
    parser.add_argument("--work-dir", default=".repopilot/swe_bench_runs")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--require-llm", action="store_true")
    parser.add_argument("--no-apply-sandbox", action="store_true")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--write-json", default="", help="Optional path to save the JSON summary.")
    parser.add_argument("--write-markdown", default="", help="Optional path to save the public markdown summary.")
    parser.add_argument("--dataset-path", default="", help="Optional official SWE-bench JSON/JSONL export.")
    parser.add_argument("--dataset-name", default="", help="Optional public dataset id for HuggingFace `datasets`.")
    parser.add_argument("--dataset-split", default="test", help="Split name when using --dataset-name.")
    parser.add_argument("--instance-id", action="append", default=[], help="Optional official instance id filter; can be repeated.")
    parser.add_argument(
        "--write-preds",
        default="",
        help="Optional path to save official SWE-bench harness-compatible predictions JSONL.",
    )
    parser.add_argument(
        "--model-name",
        default="RepoPilot",
        help="Model or agent name to write into official SWE-bench prediction rows.",
    )
    args = parser.parse_args()

    runner = SWEBenchStyleRunner(Path(args.work_dir))
    if args.dataset_path or args.dataset_name:
        cases = load_official_swe_bench_cases(
            dataset_path=args.dataset_path,
            dataset_name=args.dataset_name,
            split=args.dataset_split,
            instance_ids=args.instance_id,
            max_cases=args.max_cases,
        )
    else:
        cases = runner.load_cases(args.cases)
    summary = runner.run_suite(
        cases,
        use_llm=args.use_llm,
        require_llm=args.require_llm,
        apply_sandbox=not args.no_apply_sandbox,
        max_cases=args.max_cases,
    )
    if args.dataset_path or args.dataset_name:
        summary["public_dataset"] = {
            "dataset_path": args.dataset_path,
            "dataset_name": args.dataset_name,
            "dataset_split": args.dataset_split,
            "instance_filter_count": len(args.instance_id),
        }
    if args.write_markdown:
        target = Path(args.write_markdown)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(summary.get("public_markdown") or summary.get("markdown_table") or ""), encoding="utf-8")
    if args.write_preds:
        preds_path = write_official_predictions(
            summary.get("results") or [],
            args.write_preds,
            model_name_or_path=args.model_name,
        )
        summary["predictions_path"] = str(preds_path)
        summary["official_harness_instructions"] = build_official_eval_instructions(
            predictions_path=preds_path,
            dataset_name=args.dataset_name,
            split=args.dataset_split,
        )
    if args.write_json:
        target = Path(args.write_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
