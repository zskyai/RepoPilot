# Benchmark

## Goal

RepoPilot benchmark is designed to answer:

- can the agent localize relevant files?
- can it generate patch suggestions?
- can patches pass `git apply --check`?
- can patches be applied in sandbox?
- do tests pass?

## Current Cases

Cases are stored in:

```text
benchmarks/repo_pilot_cases.json
```

SWE-bench style cases are stored in:

```text
benchmarks/swe_style_cases.json
```

## Run

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --save-run
```

To compare the current LLM workflow against the deterministic baseline:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --use-llm --require-llm --run-tests --apply-sandbox --compare-baseline
```

To compare single-candidate patch generation against the new multi-candidate portfolio mode:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --run-tests --apply-sandbox --compare-multi-candidate
```

To compare no-graph retrieval against the new graph-enhanced rerank and impact prediction mode:

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --run-tests --apply-sandbox --compare-graph-ablation
```

To run the SWE-bench style evaluator:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --cases benchmarks\swe_style_cases.json --work-dir .repopilot\swe_runs --max-cases 11 --write-json .repopilot\reports\public_eval_latest.json --write-markdown .repopilot\reports\public_eval_latest.md
```

To run RepoPilot against official/public SWE-bench instances and export harness-compatible predictions:

```powershell
.\.venv\Scripts\python.exe run_swe_bench_style.py --cases benchmarks\swe_style_cases.json --dataset-path path\to\official_swe_bench.jsonl --dataset-name princeton-nlp/SWE-bench_Verified --dataset-split test --instance-id django__django-16527 --write-preds .repopilot\reports\all_preds.jsonl --write-json .repopilot\reports\official_eval_summary.json
```

`--dataset-path` accepts local `json`, `jsonl`, or `parquet` exports.

The exported `all_preds.jsonl` is meant to be scored by the official SWE-bench harness, for example:

```powershell
python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Verified --split test --predictions_path .repopilot\reports\all_preds.jsonl
```

## Output

The benchmark outputs:

- `case_count`
- `pass_rate`
- `average_overall`
- per-case `scores`
- optional baseline-vs-candidate deltas
- `pass_at_1` for SWE-style runs
- `adjusted_pass_at_1` for environment-limited SWE-style runs
- external repo test results
- cross-file expected-path recall and repair-context usage
- `graph_run_id` and `trace_db_path`
- a markdown summary table for README / report reuse
- a public markdown summary for GitHub / benchmark reporting
- official-harness-compatible `all_preds.jsonl` prediction export for public SWE-bench evaluation

## Public Snapshot

Current public self-hosted SWE-style snapshot:

- `case_count = 8`
- `pass_at_1 = 1.0`
- `pass_rate = 1.0`
- `average_overall = 0.936`
- `average_elapsed_seconds = 21.0`

This is a self-hosted stable suite, not an official SWE-bench leaderboard claim. Its purpose is to show repeatable end-to-end agent behavior on controlled repository tasks.

For a public benchmark that is actually recognized in the coding-agent field, use the official SWE-bench path above. RepoPilot now supports loading official instances and exporting harness-compatible predictions, but the authoritative pass rate must still come from the official harness environment.

Recent validated documentation-oriented benchmark gains:

- `schema_stability_self_repo = 0.954`
- `module_path_self_repo = 0.954`
- `readme_quickstart_self_repo = 0.954`
- `benchmark_docs_self_repo = 0.954`
- `sqlite_trace_self_repo = 0.954`
- `slugify_contributor_docs = 0.907`
- `slugify_test_entrypoint = 0.907`
- `slugify_release_docs = 0.907`

These gains came from real patch-quality improvements, especially better README-targeted patch generation, whitespace-tolerant `git apply` fallback on mixed-EOL repositories, automatic unified-diff hunk recounting before patch validation, and graph-level repair context replay that carries failure signals and patch-ranking hints across rounds.

## Current State

Current benchmark contains 8 stable cases covering:

- API schema issues
- module path issues
- README / contributor experience
- test entrypoint issues
- open source repos

The important point is that failed cases are preserved instead of hidden.

The runner now prints per-case progress and elapsed time before the final JSON summary, which makes long LLM-backed benchmark runs observable in real time.

## SWE-Style Coverage

The SWE-style suite is intentionally smaller than full SWE-bench, but it uses the same idea:

- one issue description per case
- repository checkout into an isolated workspace
- optional setup commands
- optional external test command
- pass/fail determined by both RepoPilot output and external test status

The current local cases focus on:

- retrieval and graph localization
- approval gate behavior
- structured repair signal generation
- benchmark runner usability
- GitHub/PR workflow documentation and CLI ergonomics
- memory store discovery
- persistent trace and checkpoint discovery
- dashboard operator controls
- cross-file repair-context replay
- cross-file patch-portfolio coordination
- public-eval metric aggregation and markdown export

## Latest SWE-Style Results

Validated on the local self-hosted 11-case suite:

- `case_count = 11`
- `strict_pass_at_1 = 0.0`
- `env_adjusted_pass_at_1 = 1.0`
- `average_overall = 0.954`
- `average_elapsed_seconds = 27.76`
- `cross_file_case_count = 3`
- `cross_file_pass_rate = 1.0`
- `expected_path_hit_rate = 0.0`
- `average_expected_path_recall = 0.5`
- `repair_context_usage_rate = 1.0`
- `environment_limited_case_count = 11`

The strict pass rate is `0.0` on this machine because copied SWE-style sandboxes currently lack `pytest`. RepoPilot now reports that limitation explicitly and also surfaces an environment-adjusted pass rate so the agent signal is still visible.

```markdown
| case | strict | adjusted | overall | elapsed_s | repair_rounds | path_recall | trace_db |
|---|---:|---:|---:|---:|---:|---:|---|
| repopilot_self_retrieval_smoke | no | yes | 0.954 | 39.28 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_retrieval_smoke\.repopilot\traces.sqlite3` |
| repopilot_self_approval_gate | no | yes | 0.954 | 26.99 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_approval_gate\.repopilot\traces.sqlite3` |
| repopilot_self_repair_signals | no | yes | 0.954 | 22.44 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_repair_signals\.repopilot\traces.sqlite3` |
| repopilot_self_swe_runner | no | yes | 0.954 | 19.82 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_swe_runner\.repopilot\traces.sqlite3` |
| repopilot_self_github_workflow | no | yes | 0.954 | 25.86 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_github_workflow\.repopilot\traces.sqlite3` |
| repopilot_self_memory_store | no | yes | 0.954 | 24.60 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_memory_store\.repopilot\traces.sqlite3` |
| repopilot_self_trace_store | no | yes | 0.954 | 27.88 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_trace_store\.repopilot\traces.sqlite3` |
| repopilot_self_dashboard | no | yes | 0.954 | 23.34 | 0 | 0.0 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_dashboard\.repopilot\traces.sqlite3` |
| repopilot_self_cross_file_repair_context | no | yes | 0.954 | 32.83 | 0 | 0.5 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_cross_file_repair_context\.repopilot\traces.sqlite3` |
| repopilot_self_cross_file_patch_portfolio | no | yes | 0.954 | 32.44 | 0 | 0.5 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_cross_file_patch_portfolio\.repopilot\traces.sqlite3` |
| repopilot_self_public_eval_reporting | no | yes | 0.954 | 29.93 | 0 | 0.5 | `F:\agent 项目\enterprise_agent_platform\.repopilot\swe_bench_runs\repopilot_self_public_eval_reporting\.repopilot\traces.sqlite3` |
```
